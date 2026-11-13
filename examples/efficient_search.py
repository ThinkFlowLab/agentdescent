"""Run an offline artifact-search recipe: python -m examples.efficient_search.

The two deterministic proposers stand in for model callbacks. The evaluator is
fixed; only the proposal source is routed. This demonstrates the integration,
not a benchmark result or a faithful reproduction of ShinkaEvolve.
"""

import json
import tempfile

from agentdescent.artifact_search import ArtifactSearch
from agentdescent.evolution import SingleSlot, Task, evolve
from agentdescent.model_router import ModelSpec


def main():
    search = ArtifactSearch(
        [ModelSpec("small", cost=1), ModelSpec("large", cost=4)],
        {"small": lambda *args: "Use the exact integer sum.",
         "large": lambda *args: "Add both integers and return only the sum."},
        seed=7)
    tasks = [Task(str(i), f"{i} + {i + 1}", meta={"a": i, "b": i + 1})
             for i in range(12)]

    def run(instruction, task):
        if "sum" in instruction:
            return str(task.meta["a"] + task.meta["b"])
        return "unknown"

    def reward(task, output):
        return float(output == str(task.meta["a"] + task.meta["b"]))

    with tempfile.TemporaryDirectory(prefix="agentdescent-efficient-search-") as root:
        result = evolve(
            tasks, reward, run=run, strategy=SingleSlot(initial_value="Try to answer."),
            policies=search.policies(), self_verify=False, rounds=2,
            n_workers=2, held_out_frac=0.5, seed=7, repo_path=root)
        print(json.dumps({"artifact": result.rendered, "reward": result.final_reward,
                          "error": result.error, "search": search.report()}, indent=2))
        return 0 if result.error is None and result.final_reward == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
