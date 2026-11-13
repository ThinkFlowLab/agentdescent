"""The artifact store port, and the file-backed reference (#1026).

An artifact is a tree of files with revisions: a worker proposes bytes, the
store keeps every revision, and ``promote`` names the one an evaluation reads.
#924 makes that a port instead of a convention, so a directory or object store
can back it without the loop copying files around.

Layout: ``<root>/<artifact_id>/<revision>/`` holds the bytes and
``<revision>.json`` its parent and message. Revision names are content-addressed
(``r-<16 hex>``): the same tree written twice against the same parent is one
revision. A name or relative path that could leave ``root`` raises
:class:`ValueError` before anything is written. Stdlib only; no network call.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Protocol, Sequence, Union, runtime_checkable

__all__ = ["ArtifactStore", "Diff", "FileArtifactStore"]

_SAFE_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")


@dataclass(frozen=True)
class Diff:
    """Added / removed / changed paths; sorted, so two runs print identically."""

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()


@runtime_checkable
class ArtifactStore(Protocol):
    """``read_tree``/``write_tree`` speak bytes (a weight or an image is not
    UTF-8); ``list_revisions`` is sorted; ``diff`` is a :class:`Diff`;
    ``promote`` copies a revision to a stable name and is idempotent."""

    def read_tree(self, artifact_id: str, revision: str) -> Dict[str, bytes]: ...

    def write_tree(
        self,
        artifact_id: str,
        files: Mapping[str, bytes],
        *,
        parent: Optional[str] = None,
        message: str = "",
    ) -> str: ...

    def list_revisions(self, artifact_id: str) -> Sequence[str]: ...

    def diff(self, artifact_id: str, base: str, target: str) -> Diff: ...

    def promote(self, artifact_id: str, revision: str, *, to: str) -> None: ...


def _name(value: str, what: str) -> str:
    if not isinstance(value, str) or not _SAFE_NAME.match(value):
        raise ValueError(f"unsafe {what} {value!r}: expected [A-Za-z0-9][A-Za-z0-9._-]*")
    return value


def _relpath(path: str) -> str:
    if not isinstance(path, str):
        raise TypeError(f"file path must be str, got {type(path).__name__}")
    escape = ("", ".", "..")
    if not path or path.startswith("/") or "\x00" in path or any(
        part in escape for part in path.split("/")
    ):
        raise ValueError(f"unsafe file path {path!r}: expected a relative path")
    return path


def _revision_name(parent: Optional[str], files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256(b"agentdescent.ports.v1\0")
    digest.update((parent or "").encode("utf-8") + b"\0")
    for path in sorted(files):
        data = files[path]
        digest.update(path.encode("utf-8") + b"\0")
        digest.update(str(len(data)).encode("ascii") + b"\0" + data)
    return "r-" + digest.hexdigest()[:16]


class FileArtifactStore:
    """The reference backend: one directory tree under ``root`` (created on
    construction); a revision is staged and renamed, so a partial one is never
    listed."""

    def __init__(self, root: Union[str, os.PathLike]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def read_tree(self, artifact_id: str, revision: str) -> Dict[str, bytes]:
        return self._read(self._dir(artifact_id, revision))

    def write_tree(
        self,
        artifact_id: str,
        files: Mapping[str, bytes],
        *,
        parent: Optional[str] = None,
        message: str = "",
    ) -> str:
        artifact = self._dir(artifact_id)
        if parent is not None:
            _name(parent, "parent revision")
        payload: Dict[str, bytes] = {}
        for path, data in dict(files).items():
            _relpath(path)
            if not isinstance(data, (bytes, bytearray)):
                raise TypeError(f"file {path!r} must be bytes, got {type(data).__name__}")
            payload[path] = bytes(data)
        revision = _revision_name(parent, payload)
        target = artifact / revision
        if target.is_dir():
            return revision
        artifact.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=str(artifact)))
        try:
            for path, data in payload.items():
                destination = staging / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            os.replace(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        (artifact / (revision + ".json")).write_text(
            json.dumps({"parent": parent, "message": message}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return revision

    def list_revisions(self, artifact_id: str) -> Sequence[str]:
        artifact = self._dir(artifact_id)
        if not artifact.is_dir():
            return ()
        return tuple(sorted(
            entry.name for entry in artifact.iterdir()
            if entry.is_dir() and _SAFE_NAME.match(entry.name)
        ))

    def diff(self, artifact_id: str, base: str, target: str) -> Diff:
        before = self.read_tree(artifact_id, base)
        after = self.read_tree(artifact_id, target)
        return Diff(
            added=tuple(sorted(set(after) - set(before))),
            removed=tuple(sorted(set(before) - set(after))),
            changed=tuple(
                sorted(p for p in set(before) & set(after) if before[p] != after[p])
            ),
        )

    def promote(self, artifact_id: str, revision: str, *, to: str) -> None:
        artifact = self._dir(artifact_id)
        source = self._dir(artifact_id, revision)
        target = artifact / _name(to, "promotion target")
        if target.is_dir():
            if self._read(target) == self._read(source):
                return
            shutil.rmtree(target)
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=str(artifact)))
        try:
            shutil.copytree(source, staging, dirs_exist_ok=True)
            os.replace(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def _dir(self, artifact_id: str, revision: Optional[str] = None) -> Path:
        """``<root>/<artifact_id>``, or its ``revision`` subdirectory, validated."""
        directory = self.root / _name(artifact_id, "artifact id")
        if revision is None:
            return directory
        directory = directory / _name(revision, "revision")
        if not directory.is_dir():
            raise FileNotFoundError(f"no revision {revision!r} for artifact {artifact_id!r}")
        return directory

    @staticmethod
    def _read(directory: Path) -> Dict[str, bytes]:
        return {
            path.relative_to(directory).as_posix(): path.read_bytes()
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        }
