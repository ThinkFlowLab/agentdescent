# dsh-super-agent — the zero-code composition

> Status: **reference page, written against `main`; not executed on a live
> dsh-superagent host.** What is verified here is the plugin's rows, the CLI
> commands they name, the command dsh itself prints for a missing profile, and
> the offline pilot the verification script runs. What needs a live host is
> marked *unverified on this page*; `scripts/verify-dsh-superagent.sh` settles it
> on your machine, and skips rather than guesses when it cannot compose (no dsh,
> no profile, or a read-only DSH home — this page's authoring box is the last one).

AgentDescent does not need a new plugin for [dsh-super-agent](https://github.com/deepseek-ai/dsh-superagent-prototype).
The rows it already ships are ordinary Cordis rows, so the same install that
works for the `web` profile composes in the `superagent` profile. This page is
the shortest path from a fresh checkout to one offline pilot run from a
`dsh-superagent-worker`, and the four traps that make it fail silently.

## 1. What composes

`integrations/dsh-agentdescent/cordis.patch.yml` contributes two rows:

- `dsh-agentdescent` — the skill, registered at runtime, so it cannot drift from
  the package;
- `mcp-agentdescent` — a `@deepseek-ai/dsh-mcp-client` row with
  `command: agentdescent`, `args: ["mcp"]`, `transport: stdio`, a 120000 ms
  tool-call timeout, and an explicit env allowlist because dsh scrubs
  `KEY|PASSWORD|SECRET|TOKEN` from the ambient environment
  (`integrations/dsh-agentdescent/cordis.patch.yml:8-26`).

Rows are `insert`ed, not overridden: a bare row would be read as an override of
an id that does not exist and dsh composes without it — the same trap the file's
own header names.

`agentdescent install dsh` is the file-based alternative: it writes
`$DSH_HOME/skills/agentdescent/SKILL.md`, `$DSH_HOME/skills/agentdescent/hooks.json`,
and a marked block in `$DSH_HOME/cordis.patch.yml`
(`agentdescent/integrations/__init__.py:345-355`). Use the plugin or the files,
never both: two `mcp-agentdescent` rows expose the same tools twice.

## 2. Install into the `superagent` profile

The profile is chosen by the same flag the plugin README documents for `web`
(`integrations/dsh-agentdescent/README.md`):

```bash
pip install "agentdescent[mcp]"
dsh plugin --profile superagent add link:/path/to/dsh-agentdescent
```

*Unverified on this page:* that the `superagent` profile behaves exactly as
`web` does. What dsh itself does say: `dsh --profile superagent --dump-config`
fails with `profile "superagent" does not exist; create it with 'dsh plugin
--profile superagent add <package>'`, so the profile is created by the install
rather than before it. If `dsh plugin --profile superagent` reports no plugin
surface, use the file-based install instead — it needs no profile support beyond
the skill directory dsh already reads:

```bash
agentdescent install dsh
```

## 3. Verify the rows, not the intent

```bash
dsh --profile superagent --dump-config | grep -n agentdescent
agentdescent doctor
```

The first command must print both rows: `dsh-agentdescent` and
`mcp-agentdescent`. One row means the other was dropped as a dangling override.
`doctor` reports which agents, keys and optional pieces this machine actually
has; it does not prove the worker preset exposes the tools, which is step 4.

## 4. The worker loop, and the one rule

A worker asks for a Ticket, plans, starts, and then **hands the run back** — it
does not apply:

```text
plan   -> validate the spec and estimate the cost   (writes nothing)
start  -> create the run                            (writes under the store)
status -> progress; a long run survives a turn boundary
show   -> the pilot report and the learned artifact
```

Then attach the pilot report to the Ticket and stop. `--dry-run` or an offline
`text` kind first is the cheap rehearsal; a real model run costs tokens and
should be its own Ticket.

The no-auto-apply rule is not stylistic: a run's artifact is a candidate, and
applying it is a separate, reviewed step (`apply` is the tool that writes into
your tree, under the operator's write allowlist).

## 5. Write dirs and budget for a worker

- Set `AGENTDESCENT_SURFACE_WRITE_DIRS` to the worker's own workspace. The
  default is the server's cwd plus `$AGENTDESCENT_HOME`
  (`agentdescent/surface_common.py:178-190`); an empty value refuses every MCP
  write path, which is the safest setting for a worker that should only plan.
  `algorithm_spec` obeys this allowlist from the release that carries
  [`#1018`](https://github.com/ThinkFlowLab/agentdescent/issues/1018) (fix in
  [`#1022`](https://github.com/ThinkFlowLab/agentdescent/pull/1022)). On an older
  version it can drop a spec outside its Ticket by naming an `out`: set the
  allowlist empty for a plan-only worker, or do not expose `algorithm_spec`
  at all.
- Keep `--store` inside the run directory, so a Ticket's runs are removable with
  the Ticket.
- `plan` is the budget line: it estimates cost without executing. Read it before
  `start`, and put the number in the Ticket.

## 6. Long runs, Reports and Attention

A run outlives a worker turn: `status` is cheap and safe to poll, and the store
is on disk, so a worker that dies mid-run loses its turn, not the run. Report the
run id and the store path in the Ticket rather than pasting a transcript; the
Report is the attachment, the run is the evidence.

Do not start a nested run from inside a run's turn. A worker that evolves a
harness which itself starts runs multiplies cost with no ceiling — keep one run
per Ticket, and make the second one a follow-up Ticket.

### Handing a run off instead of holding the slot

A worker's background shell job is killed at 30 minutes; an evolution run is
often longer. Start it outside the worker's process group and give the slot
back:

```bash
bash scripts/dsh-superagent-run.sh --store "$RUN_STORE" -- \
    agentdescent evolve spec.json --detach --budget 5
# waiting 3f9c1a… round 2 /runs/3f9c1a…
# report /runs/3f9c1a…/waiting.json
```

It starts the command in a detached `tmux` session (`setsid` when tmux is
absent), waits for the run's own `status.json`, writes `waiting.json` beside it
with `run_id`, `round`, `state`, `run_dir`, `driver`, `session` and `log`, and
exits 0 within seconds. Post the run id, the round and the run directory on the
Ticket and end the turn; nothing holds the slot.

Read it back from a follow-up Trigger, a person, or a scheduled check — the
wrapper adds no daemon and no scheduler. `--store` is a **global** flag, so it
goes before the verb: after the verb the CLI exits 2 with `unrecognized
arguments`, and without it the run is looked up in the default store
(`~/.agentdescent/runs`, or `$AGENTDESCENT_HOME/runs`), not in the handoff's.

```bash
agentdescent --store "$RUN_STORE" status "$RUN_ID" --brief   # one line; safe to poll
agentdescent --store "$RUN_STORE" show "$RUN_ID"             # the artifact, once there is one
```

Measured against a handoff of a fake run, a second in — `status` keeps it to
one line, and `show` reports the gap instead of inventing a result:

```console
$ agentdescent --store "$RUN_STORE" status fake-run-1 --brief
fake-run-1  running   round 2      calls=0  skill_dir:./skill
$ agentdescent --store "$RUN_STORE" show fake-run-1
run_id: fake-run-1
state: running
note: no result yet
```

What the wrapper changes, and what it cannot:

| failure | what happens |
|---|---|
| the worker's turn ends, or its background job is killed | with the `--detach` above, the run is in its own session — not the worker's process group, and not the wrapper's tmux session either, which holds only the launcher — so it keeps going when either ends |
| no tmux on the host (`setsid` fallback) | survives the group kill, not a reboot; the run directory is still the handoff |
| the host restarts | the run directory reads `failed`; `agentdescent resume <run_id>` continues it |
| an orphan outlives the Ticket | `agentdescent --store "$RUN_STORE" cancel <run_id>` sends SIGTERM to the run's process group; `tmux kill-session -t <session>` only stops the wrapper's own launcher, because a `--detach` run is not in that session |
| the budget runs out | the run stops itself and writes why into its status; the follow-up reads it, nobody is waiting |

## 7. The check

```bash
bash scripts/verify-dsh-superagent.sh
```

It exits `0` when both rows compose, `doctor` answers, and an offline `text`
pilot writes nothing outside its temp run directory. Without dsh it prints a
skip line and exits `0`; set `DSH_SUPERAGENT_REQUIRED=1` to make a missing host
an error (useful in CI on a machine that is supposed to have it).

## Related

- [`#903`](https://github.com/ThinkFlowLab/agentdescent/issues/903) — hosts could
  not reach the offline demo; the `--kind text` path above is the workaround this
  page relies on.
- [`#918`](https://github.com/ThinkFlowLab/agentdescent/issues/918) — `doctor`
  reported `ok` for a launcher that could not start; step 3 checks the rows, not
  just the exit code.
- [Use it from your agent](plugins.md) — the same composition for the other
  hosts, including the `web` profile this page is derived from.
