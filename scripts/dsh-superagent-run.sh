#!/usr/bin/env bash
# Start a long evolution run outside the worker's process group, then hand it
# back (#964). The worker reports `waiting` and ends its turn; a follow-up
# Trigger, a person or a scheduled check reads the run with `status`/`show`.
#
#   dsh-superagent-run.sh --store DIR -- agentdescent --store DIR evolve spec.json --detach
#
# The wrapper's --store is where the report goes; the run's store is the CLI's
# own --store. Give both the same value: the wrapper decides "failed" from the
# store it was given, so a child that writes its status into a different store
# is reported as a failed handoff even when the run did start (#1096).
#
# tmux is preferred because dsh-superagent already depends on it and a session
# is not in the worker's process group, so the kill that ends the worker's
# background job does not reach the run. `setsid` is the fallback: it survives
# that kill, not a reboot -- the run directory, not the process, is what a
# worker hands on.
#
# Exit 0 once the run is detached and DIR/waiting.json is written. It never
# waits for the run: a handoff that blocks is the failure this replaces. Exit 2
# when the child was already gone at the end of the wait window and wrote no
# status.json -- nothing was handed off, and DIR/worker.log holds its reason
# (#1096).
set -euo pipefail

WAIT="${DSH_RUN_HANDOFF_WAIT:-10}"   # seconds to wait for the run's status.json

die() { echo "error: $*" >&2; exit 2; }
usage() { awk 'NR > 1 && /^#/ {sub(/^# ?/, ""); print; next} NR > 1 {exit}' "$0"; }

STORE=""; CMD=()
while [ $# -gt 0 ]; do
  case "$1" in
    --store) [ $# -ge 2 ] || die "--store needs a directory"; STORE="$2"; shift 2 ;;
    --) shift; CMD=("$@"); break ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done
[ -n "$STORE" ] || die "--store is required"
[ ${#CMD[@]} -gt 0 ] || die "nothing to start: give -- <command ...>"
mkdir -p "$STORE"
STORE="$(cd "$STORE" && pwd)"
command -v python3 >/dev/null || die "python3 is required to write the handoff report"

LOG="$STORE/worker.log"
# The store's basename is not unique -- a worker that hands off two runs keeps
# both in a directory called `runs` -- so the session carries a per-launch
# suffix. Two handoffs then never ask tmux for the same name (#1084 review).
SESSION="ad-$(printf '%s' "$(basename "$STORE")" | tr -c 'A-Za-z0-9_.-' '-')-$$-$RANDOM"
# Report text only: this string is what `waiting.json` shows as `command`, and
# nothing ever executes it.
QUOTED="$(printf '%q ' "${CMD[@]}")"
# The log path and the command reach the driver as **arguments**, never spliced
# into a shell string: the old `>> '$LOG'` let an apostrophe in --store close the
# quote, and the rest of the path ran as shell words outside the worker's process
# group with the operator's privileges (#1109). `exec >>"$1"` opens the log,
# `shift` drops it from argv, and the run is exec'd in this process, so it keeps
# the same process group and exit status and nothing re-parses either value.
LAUNCH=(bash -c 'exec >>"$1" 2>&1; shift; exec "$@"' _ "$LOG")

# What the store already holds, taken before the launch: a reused store always
# has earlier runs in it, and reporting the newest of those as this handoff is
# worse than reporting nothing (#1084 review). Only a status.json that this
# launch creates or rewrites may be reported.
SNAP="$STORE/.handoff-$$-$RANDOM.json"
trap 'rm -f "$SNAP"' EXIT
python3 - "$STORE" "$SNAP" <<'PY'
import glob, json, os, sys, time
store, out = sys.argv[1:3]
# The launch epoch rides in the snapshot: `started` is written once at launch
# and never reset, so a changed file can be checked against it (#1101).
snap = {"epoch": time.time()}
paths = [os.path.join(store, "status.json")] + sorted(
    glob.glob(os.path.join(store, "*", "status.json")))
for path in paths:
    if os.path.isfile(path):
        st = os.stat(path)
        snap[path] = [st.st_mtime, st.st_size]
with open(out, "w", encoding="utf-8") as fh:
    json.dump(snap, fh)
PY
if command -v tmux >/dev/null 2>&1; then
  DRIVER=tmux
  RUN_PID=""
  tmux new-session -d -s "$SESSION" -c "$PWD" "${LAUNCH[@]}" "${CMD[@]}" \
    || die "tmux refused the session $SESSION"
elif command -v setsid >/dev/null 2>&1; then
  DRIVER=setsid
  setsid "${LAUNCH[@]}" "${CMD[@]}" >/dev/null 2>&1 &
  RUN_PID=$!
else
  die "neither tmux nor setsid is available; this host cannot hand off a run"
fi

# The run owns its status.json (`<store>/<run_id>/status.json`, or the store
# itself when the caller owns the run directory). Absent is reported as such:
# an invented run id is worse than a gap a Trigger can see.
python3 - "$STORE" "$WAIT" "$DRIVER" "$SESSION" "$LOG" "$QUOTED" "$SNAP" "$RUN_PID" <<'PY'
import glob, json, os, subprocess, sys, time
store, wait, driver, session, log, command, snap_path, run_pid = sys.argv[1:9]
before = json.load(open(snap_path, encoding="utf-8"))
epoch = float(before.pop("epoch"))
deadline, found = time.time() + float(wait), None


def still_running():
    """Whether the command this handoff started is alive at the window's end.

    `found: false` alone cannot tell "alive, no status yet" from "gone" (#1096).
    The driver answers it: a tmux session ends with its command, and the setsid
    pid is this shell's own child, so `kill(pid, 0)` says whether it is still
    there. Unknown is reported as alive -- a false "failed" would be worse than
    a missed one.
    """
    if driver == "tmux":
        try:
            return subprocess.run(["tmux", "has-session", "-t", "=" + session],
                                  capture_output=True).returncode == 0
        except OSError:
            # The probe could not run at all (exec pressure, binary gone,
            # permission): it did not answer, and "cannot judge" is alive. Letting
            # this raise would kill the report before it is written (#1096 review).
            return True
    if not run_pid:
        return True
    try:
        os.kill(int(run_pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError):
        return True
    return True


def started_at(path):
    """A run's launch time, or None when the file does not carry a numeric one."""
    try:
        with open(path, encoding="utf-8") as fh:
            started = json.load(fh).get("started")
    except (OSError, ValueError):
        return None
    if isinstance(started, bool) or not isinstance(started, (int, float)):
        return None
    return float(started)


def fresh():
    """This launch's own status.json, read from the store now, or None.

    The scan is a function so the decision comes from a read taken at decision
    time: the old loop exited on a scan up to 200 ms old, and a status.json
    written during that last sleep was reported as a failed handoff (#1096
    review).
    """
    paths = [p for p in [os.path.join(store, "status.json")]
             + sorted(glob.glob(os.path.join(store, "*", "status.json")))
             if os.path.isfile(p)]
    found_paths = []
    for path in paths:
        try:
            st = os.stat(path)
        except OSError:
            continue
        seen = before.get(path)
        if seen is None:
            # Not there when the snapshot was taken: this launch made it.
            found_paths.append(path)
            continue
        if [st.st_mtime, st.st_size] == seen:
            continue
        if path == os.path.join(store, "status.json"):
            # The store *is* the run directory when the caller owns it, so this
            # file is this handoff's own run and its `started` predates the
            # launch by construction. The epoch filter below is for another run
            # in a shared store and must not reject it (#1096 review).
            found_paths.append(path)
            continue
        # A reused store can hold a run that is still going, and that run
        # rewrites its own status.json every round (#1101). Only a file whose
        # `started` is no older than this launch is this handoff's.
        started = started_at(path)
        if started is None or started < epoch:
            continue
        found_paths.append(path)
    return max(found_paths, key=os.path.getmtime) if found_paths else None


def make_report(found):
    """The report for the status file this handoff is, or a bare `waiting`."""
    status = json.load(open(found)) if found else {}
    return {"status": "waiting", "found": bool(found),
            "run_id": status.get("run_id", "") if found else "",
            "round": status.get("round", 0),
            "state": status.get("state", "unknown"),
            "run_dir": os.path.dirname(found) if found else store,
            "driver": driver,
            "session": session if driver == "tmux" else "", "log": log,
            "command": command.strip()}


while True:
    found = fresh()
    if found is not None or time.time() >= deadline:
        break
    time.sleep(0.2)
report = make_report(found)
path = os.path.join(store, "waiting.json")


def write_report():
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")


# The report lands before the liveness question is asked: if the probe cannot
# run -- or the wrapper is killed while it waits -- a `waiting` report still
# exists, which is the direction #1096 calls for. Nothing this launch could
# report and the child gone means nothing was handed off; the wrapper used to
# print `waiting` and exit 0 there, which is how a child that refused to start
# read as a successful handoff (#1096).
write_report()
expired = found is None and not still_running()
if expired:
    # The probe spawns a tmux client -- 10-30 ms, unbounded on a loaded box --
    # and nothing reads the store while it runs, so a status.json written in
    # that window is on disk when the verdict says it is not. Read once more at
    # the moment of the decision and believe the file over the probe: a run
    # that wrote and exited 20 ms after the window is a handoff, and calling it
    # failed costs a duplicate run (#1096 review). This is the probe's window
    # only; the deadline is not extended, so a child that wrote nothing is
    # still `failed`.
    late = fresh()
    if late is not None:
        found = late
        report = make_report(found)
        expired = False
        # The provisional `waiting` report is already on disk and names no run;
        # replace it so a reader sees the handoff this launch actually made.
        write_report()
if expired:
    report["status"] = "failed"
    report["state"] = "exited"
    write_report()
print(f"{report['status']} {report['run_id'] or '(no run yet)'} "
      f"round {report['round']} {report['run_dir']}")
print(f"report {path}")
if expired:
    print(f"error: the run exited before writing a status; its reason, if it "
          f"wrote one, is in {log}", file=sys.stderr)
    sys.exit(2)
PY
