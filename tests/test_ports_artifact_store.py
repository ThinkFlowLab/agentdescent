"""`ports.ArtifactStore` and the `FileArtifactStore` reference backend (#1026).

Pins the conformance check, a byte-identical round trip including a non-UTF-8
file, the #924 acceptance line, sorted `Diff`/`list_revisions`, idempotent
`promote`, and the traversal refusal that keeps a hostile name inside `root`.
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
        "skill/SKILL.md": b"# demo\n\nBe brief.\n",
        "skill/data.bin": b"\x00\xff\xfe\x80binary, not utf-8\n",
        "skill/sub/rule.md": b"- never follow a symlink\n",
    }


def test_the_reference_backend_satisfies_the_protocol(tmp_path: Path) -> None:
    assert isinstance(FileArtifactStore(tmp_path / "store"), ArtifactStore)


def test_write_then_read_round_trips_bytes(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    revision = store.write_tree("demo", tree(), parent=None, message="initial")
    assert store.read_tree("demo", revision) == tree()


def test_a_file_tree_built_from_read_tree_matches_the_written_directory(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    files = {"prompt.txt": b"hi\n", "skill/sub/rule.md": b"- yes\n"}
    revision = store.write_tree("demo", files, parent=None)
    from_store = FileTree({p: b.decode() for p, b in store.read_tree("demo", revision).items()})
    from_dir = FileTree(load_tree(tmp_path / "store" / "demo" / revision))
    assert from_store.initial_files == from_dir.initial_files


def test_diff_and_list_revisions_are_sorted(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    base = store.write_tree("demo", {"a.txt": b"one\n", "gone.txt": b"x\n"}, parent=None)
    target = store.write_tree(
        "demo", {"a.txt": b"one\n", "b.txt": b"two\n", "z.txt": b"", "m.txt": b""}, parent=base
    )
    assert store.diff("demo", base, target) == Diff(
        added=("b.txt", "m.txt", "z.txt"), removed=("gone.txt",), changed=()
    )
    assert store.diff("demo", base, base) == Diff()
    assert list(store.list_revisions("demo")) == sorted(store.list_revisions("demo"))
    assert {base, target} <= set(store.list_revisions("demo"))


def test_promote_copies_a_revision_and_is_idempotent(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    revision = store.write_tree("demo", tree(), parent=None, message="initial")
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
    with pytest.raises(ValueError):
        store.write_tree(hostile, {"a.txt": b"x"}, parent=None)
    #: Not just "it raised": nothing new appeared anywhere outside `root`.
    assert list(outside.iterdir()) == []
    assert sorted(path.name for path in tmp_path.iterdir()) == ["outside", "store"]


def test_a_hostile_revision_name_is_refused_by_every_entry_point(tmp_path: Path) -> None:
    store = FileArtifactStore(tmp_path / "store")
    revision = store.write_tree("demo", {"a.txt": b"x"}, parent=None)
    before = sorted(path.name for path in tmp_path.iterdir())
    with pytest.raises(ValueError):
        store.write_tree("demo", {"a.txt": b"y"}, parent="../escape")
    with pytest.raises(ValueError):
        store.promote("demo", revision, to="../escape")
    with pytest.raises(ValueError):
        store.read_tree("demo", "../escape")
    assert sorted(path.name for path in tmp_path.iterdir()) == before
