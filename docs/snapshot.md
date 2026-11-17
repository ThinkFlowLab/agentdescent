# Portable snapshots

A snapshot is the **complete candidate** the ledger already stores — every
editable file plus the frozen context around it — together with the lineage
that history already implies (`id`, `parent`, `root`). It is a portable JSON
file, not a second ledger.

Algorithms still edit only the declared scope (`FileTree.editable`, with
`frozen` winning). Evaluation and restore use the whole tree. You can take a
selected snapshot and score it, read-only, on another compatible dataset;
that pass does not search, commit, or apply anything.

This is not “run this snapshot inside Claude Code.” Host selection stays the
existing agent / runner path on the destination spec. `kind: plugin` still
means “evolve the plugin itself.”

## Capture

From a finished run (the run’s `result.json` supplies the files; the run
ledger, when still on disk, supplies lineage):

```bash
agentdescent snapshot export <run_id> -o skill.json
agentdescent snapshot show skill.json
```

From a `FileTree` or a live ledger in Python:

```python
from agentdescent import ArtifactSnapshot, FileTree
from agentdescent.ledger import Ledger, read_artifact_lineage

snap = ArtifactSnapshot.from_filetree(
    FileTree(files, frozen=["tests/**"]),
    artifact_id="skill", kind="skill_dir")
# or ArtifactSnapshot.from_ledger(ledger, "skill", strategy=tree, kind="skill_dir")
snap.save("skill.json")
```

`id` is `{artifact_id}@v{version}`, `parent` is the previous version, and
`root` is `{artifact_id}@v1`. Those are the identifiers the ledger already
uses. Existing `status` / `show` / `apply` on a run are unchanged; a snapshot
is what you take *with you* when the run directory is not the destination.

## Re-evaluate without search

```bash
agentdescent snapshot eval skill.json --spec dest.yaml
```

The destination spec supplies the **tasks and the scorer** (including whatever
host agent that spec already selects). Its `target` is ignored; the candidate
is the snapshot. Kind must match. In Python:

```python
from agentdescent import evaluate_snapshot, evaluate_snapshot_spec, load_spec

report = evaluate_snapshot(snap, tasks, run=run, reward=reward)
# or evaluate_snapshot_spec(snap, load_spec("dest.yaml"))
report.reward, report.scores, report.searched  # searched is always False
```

This does **not** change `evolve(test_frac=…)` defaults or add a new
train/test product verb. It only scores a frozen candidate.

## Restore

```bash
agentdescent snapshot apply skill.json --to ./out --dry-run
agentdescent snapshot apply skill.json --to ./out
```

That materialises the complete tree (frozen files included) with the same
backup rules as `apply --from`. `show` and `apply` on the original run_id
still work as they do today.

## What a file contains

The JSON names its format (`agentdescent.artifact_snapshot`, version 1) and
carries `files`, `editable`, `frozen`, derived `roles`, a content `digest`,
and the lineage fields above. Missing lineage (a run whose ledger was
removed) is left empty rather than invented.
