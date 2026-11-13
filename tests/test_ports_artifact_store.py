"""`ports.ArtifactStore` and the `FileArtifactStore` reference backend (#1026).

Pins the conformance check and a byte round trip (non-UTF-8 included), the #924
`FileTree` acceptance line, sorted output, idempotent `promote`, and every
traversal refusal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentdescent.filetree import load_tree
from agentdescent.ports import ArtifactStore, Diff, FileArtifactStore
from agentdescent.treestrategy import FileTree


def tree() -> dict[str, bytes]:
    return {
        "prompt.txt": b"system: answer with one line\n",
        "skill/data.bin": b"\x00\xff\xfe\x80binary, not utf-8\n",
        "skill/sub/rule.md": b"- never follow a symlink\n",
    }


def test_the_protocol_round_trips_bytes_and_feeds_file_tree(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    assert isinstance(store, ArtifactStore)
    revision = store.write_tree("demo", tree(), parent=None, message="initial")
    assert store.read_tree("demo", revision) == tree()
    text = {"prompt.txt": b"hi\n", "skill/sub/rule.md": b"- yes\n"}
    text_revision = store.write_tree("demo", text, parent=revision)
    from_store = FileTree({p: b.decode() for p, b in store.read_tree("demo", text_revision).items()})
    from_dir = FileTree(load_tree(tmp_path / "store" / "demo" / text_revision))
    assert from_store.initial_files == from_dir.initial_files


def test_diff_lists_are_sorted_and_a_revision_against_itself_is_empty(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    base = store.write_tree("demo", {"a.txt": b"one\n", "gone.txt": b"x\n"}, parent=None)
    target = store.write_tree(
        "demo", {"a.txt": b"one\n", "b.txt": b"", "z.txt": b"", "m.txt": b""}, parent=base
    )
    assert store.diff("demo", base, target) == Diff(
        added=("b.txt", "m.txt", "z.txt"), removed=("gone.txt",), changed=()
    )
    assert store.diff("demo", base, base) == Diff()
    assert list(store.list_revisions("demo")) == sorted(store.list_revisions("demo"))
    assert {base, target} <= set(store.list_revisions("demo"))


def test_promote_copies_a_revision_and_is_idempotent(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    revision = store.write_tree("demo", tree(), parent=None)
    store.promote("demo", revision, to="latest")
    assert store.read_tree("demo", "latest") == store.read_tree("demo", revision)
    store.promote("demo", revision, to="latest")
    assert store.read_tree("demo", "latest") == store.read_tree("demo", revision)


@pytest.mark.parametrize("hostile", ["../escape", "/absolute/path", "nested/name"])
def test_a_hostile_name_is_refused_and_writes_nothing_outside_root(
    tmp_path: Path, hostile: str
) -> None:
    store = FileArtifactStore(tmp_path / "store")
    outside = tmp_path / "outside"
    outside.mkdir()
    revision = store.write_tree("demo", {"a.txt": b"x"}, parent=None)
    for call in (
        lambda: store.write_tree(hostile, {"a.txt": b"x"}, parent=None),
        lambda: store.write_tree("demo", {"a.txt": b"y"}, parent=hostile),
        lambda: store.promote("demo", revision, to=hostile),
        lambda: store.read_tree("demo", hostile),
    ):
        with pytest.raises(ValueError):
            call()
    #: Not just "it raised": nothing new appeared anywhere outside `root`.
    assert list(outside.iterdir()) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["outside", "store"]
