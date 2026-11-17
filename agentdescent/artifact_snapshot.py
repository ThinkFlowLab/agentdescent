"""A portable snapshot of one candidate: full context plus ledger lineage.

A snapshot is not a second ledger. It is the FileTree state already stored
on the ledger (or in a run's ``result.json``) plus the id / parent / root
that history already implies, written as a JSON file so the same candidate
can be restored or scored elsewhere.

Algorithms still edit only the declared editable scope; evaluation and
restore use the complete tree, including frozen files. Taking a selected
snapshot and scoring it on another compatible dataset does not search,
commit, or apply anything.

This is not "run this snapshot inside Claude Code". Plugin kind still
means "evolve the plugin itself". Host selection stays the existing
agent / runner path on the destination spec.

    snap = ArtifactSnapshot.from_filetree(tree, artifact_id="skill")
    snap.save("skill.json")
    report = evaluate_snapshot(snap, tasks, run=run, reward=reward)
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from .evolution import Task
from .filetree import canonical, materialize, match_any, safe_relpath
from .ledger import Ledger, read_artifact_lineage
from .treestrategy import FileTree

__all__ = [
    "FORMAT",
    "FORMAT_VERSION",
    "ArtifactSnapshot",
    "SnapshotEvalReport",
    "evaluate_snapshot",
    "evaluate_snapshot_spec",
    "read_artifact_lineage",
    "load_snapshot_source",
]

FORMAT = "agentdescent.artifact_snapshot"
FORMAT_VERSION = 1


def _as_patterns(value: Optional[Sequence[str]], default: Tuple[str, ...]) -> Tuple[str, ...]:
    if value is None:
        return default
    return tuple(str(item) for item in value)


def _files(value: Mapping[str, str]) -> Dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError("snapshot files must be a mapping of path to text")
    files: Dict[str, str] = {}
    for path, content in value.items():
        if not isinstance(path, str) or not isinstance(content, str):
            raise TypeError("snapshot files must be str paths to str content")
        files[safe_relpath(path) if path not in (".", "") else path] = content
    return files


def _ident(artifact_id: str, version: Optional[int]) -> Optional[str]:
    if not artifact_id:
        return None
    if version is None:
        return artifact_id
    return f"{artifact_id}@v{version}"


@dataclass(frozen=True)
class ArtifactSnapshot:
    """One candidate's complete context and the lineage already on the ledger."""

    artifact_id: str
    files: Mapping[str, str]
    editable: Tuple[str, ...] = ("**",)
    frozen: Tuple[str, ...] = ()
    kind: str = ""
    version: Optional[int] = None
    id: Optional[str] = None
    parent: Optional[str] = None
    root: Optional[str] = None
    commit: Optional[str] = None
    parent_commit: Optional[str] = None
    root_commit: Optional[str] = None
    branch: Optional[str] = None
    rendered: Optional[str] = None
    format: str = FORMAT
    format_version: int = FORMAT_VERSION
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, str) or not self.artifact_id.strip():
            raise ValueError("artifact_id must be a non-empty string")
        object.__setattr__(self, "files", _files(self.files))
        object.__setattr__(self, "editable", _as_patterns(self.editable, ("**",)))
        object.__setattr__(self, "frozen", _as_patterns(self.frozen, ()))
        if self.id is None:
            object.__setattr__(self, "id", _ident(self.artifact_id, self.version))

    @property
    def snapshot_id(self) -> str:
        return self.id or self.artifact_id

    def role(self, path: str) -> str:
        """``frozen``, ``editable``, or ``context`` (loaded, but not in scope)."""
        rel = safe_relpath(path)
        if match_any(rel, self.frozen):
            return "frozen"
        if match_any(rel, self.editable):
            return "editable"
        return "context"

    def roles(self) -> Dict[str, str]:
        return {path: self.role(path) for path in self.files}

    def to_filetree(self) -> FileTree:
        return FileTree(self.files, editable=self.editable, frozen=self.frozen)

    def render(self) -> str:
        if self.rendered is not None:
            return self.rendered
        return self.to_filetree().render(self.files)

    def materialize(self, dest: str) -> None:
        materialize(dict(self.files), dest)

    def digest(self) -> str:
        body = canonical(self.files)
        return hashlib.sha256(body.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "format": self.format,
            "format_version": self.format_version,
            "id": self.snapshot_id,
            "parent": self.parent,
            "root": self.root,
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "version": self.version,
            "commit": self.commit,
            "parent_commit": self.parent_commit,
            "root_commit": self.root_commit,
            "branch": self.branch,
            "editable": list(self.editable),
            "frozen": list(self.frozen),
            "files": dict(self.files),
            "roles": self.roles(),
            "digest": self.digest(),
        }
        if self.rendered is not None:
            payload["rendered"] = self.rendered
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ArtifactSnapshot":
        if not isinstance(payload, Mapping):
            raise TypeError("snapshot payload must be an object")
        fmt = payload.get("format")
        if fmt not in (None, FORMAT):
            raise ValueError(f"unsupported snapshot format: {fmt!r}")
        version = payload.get("format_version", FORMAT_VERSION)
        if version != FORMAT_VERSION:
            raise ValueError(f"unsupported snapshot format_version: {version!r}")
        files = payload.get("files")
        if files is None:
            raise ValueError("snapshot is missing files")
        return cls(
            artifact_id=str(payload.get("artifact_id") or payload.get("id") or "artifact"),
            files=files,
            editable=tuple(payload.get("editable") or ("**",)),
            frozen=tuple(payload.get("frozen") or ()),
            kind=str(payload.get("kind") or ""),
            version=payload.get("version"),
            id=payload.get("id"),
            parent=payload.get("parent"),
            root=payload.get("root"),
            commit=payload.get("commit"),
            parent_commit=payload.get("parent_commit"),
            root_commit=payload.get("root_commit"),
            branch=payload.get("branch"),
            rendered=payload.get("rendered"),
            extra=dict(payload.get("extra") or {}),
        )

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")

    @classmethod
    def load(cls, path: str) -> "ArtifactSnapshot":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    @classmethod
    def from_filetree(
            cls, tree: FileTree, *,
            artifact_id: str,
            state: Optional[Mapping[str, str]] = None,
            kind: str = "",
            lineage: Optional[Mapping[str, Any]] = None,
            rendered: Optional[str] = None,
    ) -> "ArtifactSnapshot":
        files = dict(state if state is not None else tree.initial())
        # Evaluation/restore must see frozen context even if a caller passed
        # only the editable slice; fill any missing frozen keys from the tree.
        for path, content in tree.frozen_files(tree.initial_files).items():
            files.setdefault(path, content)
        line = dict(lineage or {})
        return cls(
            artifact_id=artifact_id,
            files=files,
            editable=tuple(tree.editable),
            frozen=tuple(tree.frozen),
            kind=kind,
            version=line.get("version"),
            id=line.get("id"),
            parent=line.get("parent"),
            root=line.get("root"),
            commit=line.get("commit"),
            parent_commit=line.get("parent_commit"),
            root_commit=line.get("root_commit"),
            branch=line.get("branch"),
            rendered=rendered,
        )

    @classmethod
    def from_result(
            cls, result: Any, *,
            artifact_id: str,
            kind: str = "",
            editable: Sequence[str] = ("**",),
            frozen: Sequence[str] = (),
            lineage: Optional[Mapping[str, Any]] = None,
    ) -> "ArtifactSnapshot":
        tree = FileTree(dict(result.state), editable=editable, frozen=frozen)
        return cls.from_filetree(
            tree, artifact_id=artifact_id, state=result.state, kind=kind,
            lineage=lineage, rendered=getattr(result, "rendered", None))

    @classmethod
    def from_ledger(
            cls, ledger: Ledger, artifact_id: str, *,
            branch: str = Ledger.DEV,
            strategy: Optional[FileTree] = None,
            kind: str = "",
    ) -> "ArtifactSnapshot":
        view = ledger.snapshot(branch)
        artifact = view.get(artifact_id)
        if artifact is None:
            raise KeyError(f"ledger has no artifact {artifact_id!r} on {branch}")
        state = dict(getattr(artifact, "state", None) or {})
        if not state and hasattr(artifact, "table"):
            # Non-FileTree Evolvable used in tests; keep a portable mapping.
            state = {"state.json": json.dumps(getattr(artifact, "table"),
                                              sort_keys=True)}
        tree = strategy or FileTree(state)
        lineage = read_artifact_lineage(ledger.repo_path, artifact_id, branch=branch) or {}
        version = getattr(artifact, "version", None)
        if version is not None:
            lineage.setdefault("version", version)
        return cls.from_filetree(
            tree, artifact_id=artifact_id, state=state or dict(tree.initial()),
            kind=kind, lineage=lineage,
            rendered=artifact.render() if hasattr(artifact, "render") else None)

    @classmethod
    def from_run(cls, run_id: str, *, store: Optional[str] = None) -> "ArtifactSnapshot":
        from . import runstore
        from .evolvespec import EvolveSpec

        rd = runstore.get(run_id, store=store)
        result = rd.result()
        if result is None:
            raise runstore.RunStoreError(f"run {run_id} has no result yet")
        spec = EvolveSpec.from_dict(rd.spec_dict())
        aid = spec.artifact_id()
        lineage = None
        if os.path.isdir(rd.ledger_path):
            lineage = read_artifact_lineage(
                rd.ledger_path, aid, branch=Ledger.DEV)
        return cls.from_result(
            result, artifact_id=aid, kind=spec.kind,
            editable=spec.editable, frozen=spec.frozen, lineage=lineage)


@dataclass(frozen=True)
class SnapshotEvalReport:
    """A read-only score of one snapshot; no search happened."""

    snapshot_id: str
    n: int
    reward: Optional[float]
    scores: Mapping[str, float]
    failed: Tuple[str, ...] = ()
    kind: str = ""
    digest: str = ""
    searched: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "n": self.n,
            "reward": self.reward,
            "scores": dict(self.scores),
            "failed": list(self.failed),
            "kind": self.kind,
            "digest": self.digest,
            "searched": self.searched,
        }


def _task_id(task: Any) -> str:
    value = getattr(task, "id", None)
    if value is None and isinstance(task, Mapping):
        value = task.get("id")
    if value is None:
        raise ValueError("every snapshot eval task needs an id")
    return str(value)



def load_snapshot_source(source: str, *, store: Optional[str] = None) -> ArtifactSnapshot:
    """Load a snapshot JSON file, or capture one from a finished run id."""
    path = os.path.abspath(os.path.expanduser(source))
    if os.path.isfile(path):
        return ArtifactSnapshot.load(path)
    return ArtifactSnapshot.from_run(source, store=store)


def evaluate_snapshot(
        snapshot: ArtifactSnapshot,
        tasks: Sequence[Task],
        *,
        run: Callable[[str, Task], str],
        reward: Callable[[Task, str], float],
) -> SnapshotEvalReport:
    """Score a frozen snapshot on ``tasks``. Does not search or write a ledger."""
    rendered = snapshot.render()
    scores: Dict[str, float] = {}
    failed = []
    for task in tasks:
        task_id = _task_id(task)
        try:
            output = run(rendered, task)
            value = float(reward(task, output))
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError(f"reward for {task_id!r} must be finite")
        except Exception:  # noqa: BLE001 - a scorer/harness failure, not a zero
            failed.append(task_id)
            continue
        scores[task_id] = value
    n = len(scores)
    return SnapshotEvalReport(
        snapshot_id=snapshot.snapshot_id,
        n=n,
        reward=(sum(scores.values()) / n if n else None),
        scores=scores,
        failed=tuple(failed),
        kind=snapshot.kind,
        digest=snapshot.digest(),
        searched=False,
    )


def _write_target(snapshot: ArtifactSnapshot, kind: str, tmp: str) -> str:
    if kind == "text":
        path = os.path.join(tmp, snapshot.artifact_id)
        text = snapshot.render()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path
    dest = os.path.join(tmp, snapshot.artifact_id)
    os.makedirs(dest, exist_ok=True)
    snapshot.materialize(dest)
    return dest


def evaluate_snapshot_spec(
        snapshot: ArtifactSnapshot,
        spec: Any,
        **compose_hooks: Any,
) -> SnapshotEvalReport:
    """Score ``snapshot`` with a destination spec's tasks and scorer.

    The destination supplies the dataset and the run/reward (including the
    already-selectable host agent). The candidate is the snapshot, not the
    spec's ``target``. Nothing is evolved.
    """
    from .evolvespec import EvolveSpec, compose

    if not isinstance(spec, EvolveSpec):
        raise TypeError("evaluate_snapshot_spec expects an EvolveSpec")
    if snapshot.kind and spec.kind and snapshot.kind != spec.kind:
        raise ValueError(
            f"snapshot kind {snapshot.kind!r} is not compatible with "
            f"destination kind {spec.kind!r}")
    kind = snapshot.kind or spec.kind
    with tempfile.TemporaryDirectory(prefix="ad-snapshot-eval-") as tmp:
        target = _write_target(snapshot, kind, tmp)
        dest = replace(
            spec, target=target,
            editable=tuple(snapshot.editable),
            frozen=tuple(snapshot.frozen),
        )
        # Search knobs on the dest spec must not start a search: we only compose.
        dest = replace(dest, evolve={})
        comp = compose(dest, **compose_hooks)
        run = comp.kwargs.get("run")
        if run is None:
            agent = comp.kwargs.get("agent")
            if agent is not None and callable(getattr(agent, "solve", None)):
                run = agent.solve
        if run is None:
            raise ValueError("destination spec produced no run callable")
        return evaluate_snapshot(
            snapshot, comp.tasks, run=run, reward=comp.reward)
