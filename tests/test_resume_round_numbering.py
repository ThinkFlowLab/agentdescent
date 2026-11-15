"""A resumed run continues the ledger's round numbering (#1092).

``resume`` relaunches a run on its existing directory, and ``execute`` appends
to that run's ``rounds.jsonl``. The engine numbered every process from zero, so
a resume without a checkpoint (``checkpointing`` is off by default) appended
``[0, 1, 2]`` after ``[0, 1, 2]`` and reported ``status.round`` 1, 2, 3 again.
The same per-process reset made ``status.best_reward`` start empty, so it
rewound below a reward the run's own history still held.

The resume still runs its full ``rounds``: this is numbering, not extra work.
"""

from __future__ import annotations

from typing import Optional

import pytest

from agentdescent import EvolveSpec, Task, demo, evolve, runstore
from agentdescent.evolution import EvolutionResult, RoundInfo


def _spec_dict(tmp_path, rounds: int) -> dict:
    """A demo spec that does not stop at its target, so ``rounds`` is the bound."""
    spec = demo.build(str(tmp_path / "work"))
    spec["evolve"] = dict(spec.get("evolve") or {}, rounds=rounds, n_workers=1,
                          target_reward=2.0)
    return EvolveSpec.from_dict(spec).to_dict()


def test_resume_continues_round_numbering(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    store = str(tmp_path / "runs")
    rd = runstore.create(_spec_dict(tmp_path, 3), store=store)
    runstore.execute(rd)
    assert [row["round"] for row in rd.rounds()] == [0, 1, 2]

    runstore.execute(rd)

    rows = [row["round"] for row in rd.rounds()]
    assert rows == [0, 1, 2, 3, 4, 5], f"resume renumbered the rounds: {rows}"
    assert rd.status().round == 6


def test_resume_seeds_best_reward_from_the_ledger(tmp_path, monkeypatch):
    """A second pass that scores lower must not rewind the panel's best (#1092).

    Driven through ``execute``'s own plumbing with the engine stubbed out: what
    is under test is what the store carries across a relaunch, and the real
    engine's per-round callback would only add a second, slower spelling of it.
    """
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    store = str(tmp_path / "runs")
    rd = runstore.create(_spec_dict(tmp_path, 2), store=store)
    for i in range(3):
        rd.append_round(RoundInfo(round=i, held_out_reward=1.0, n_items=1,
                                  committed=1, rejected=0))
    rd.update_status(state="done", round=3, best_reward=1.0, last_reward=1.0)

    seen: dict = {}

    def fake_compose(spec, **kw):
        seen["round_base"] = kw.get("round_base")

        class _Composition:
            tree: Optional[dict] = None
            notes: list = []
            kwargs: dict = {"rounds": 1}

            def run(self):
                return EvolutionResult(state={}, rendered="", final_reward=0.25,
                                       history=[], ledger_log=[])

        return _Composition()

    monkeypatch.setattr("agentdescent.evolvespec.compose", fake_compose)
    runstore.execute(rd)

    assert seen["round_base"] == 3, (
        f"execute() told the engine to start at {seen['round_base']!r}, not at "
        "one past the ledger's last round")
    assert rd.status().best_reward == 1.0, (
        "best_reward rewound below a reward the history still holds")


def test_a_checkpoint_further_ahead_than_the_ledger_still_wins(tmp_path, monkeypatch):
    """``max(checkpoint, ledger)``: numbering never goes backwards on a resume."""
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("agentdescent.checkpoint.restore_checkpoint",
                        lambda *a, **kw: {"round": 7})
    repo = tmp_path / "repo"
    repo.mkdir()
    tasks = [Task(id=f"t{i}", prompt="x", meta={"expected": "GOAL"})
             for i in range(10)]

    def reward(task, output):
        return 1.0 if output == task.meta["expected"] else 0.0

    class _Slot:
        def initial(self):
            return {}

        def render(self, state):
            return state.get("v", "")

    from agentdescent.evolution import SingleSlot
    result = evolve(tasks, reward, run=lambda a, t: "x", propose=lambda *a: None,
                    strategy=SingleSlot(initial_value="v"), n_workers=1, rounds=2,
                    round_base=1, checkpointing=True, repo_path=str(repo),
                    self_verify=False, target_reward=2.0)
    assert [h.round for h in result.history] == [8, 9]


@pytest.mark.parametrize("empty", [True])
def test_an_empty_ledger_still_starts_at_zero(tmp_path, monkeypatch, empty):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    store = str(tmp_path / "runs")
    rd = runstore.create(_spec_dict(tmp_path, 2), store=store)
    runstore.execute(rd)
    assert [row["round"] for row in rd.rounds()] == [0, 1]
