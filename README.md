# AgentDescent

**[Website & interactive demo](https://thinkflowlab.github.io/agentdescent/)** ·
[Get started](https://thinkflowlab.github.io/agentdescent/start/) ·
[Documentation](https://thinkflowlab.github.io/agentdescent/docs/)

> **Gradient descent — but the parameters are agents.** AgentDescent evolves
> prompts, skills, agent directories, agent code and host plugins against your
> own examples. *N* workers propose edits **in parallel**, one aggregator merges
> them into a version-controlled artifact, and a held-out gate decides what is
> kept. Use it from Python with one `evolve()` call, from the CLI, or from inside
> Claude Code, Codex, OpenCode, DeepSeek Harness or Grok Bot.

[![PyPI](https://img.shields.io/pypi/v/agentdescent)](https://pypi.org/project/agentdescent/)
[![tests](https://github.com/ThinkFlowLab/agentdescent/actions/workflows/tests.yml/badge.svg)](https://github.com/ThinkFlowLab/agentdescent/actions/workflows/tests.yml)
[![docs](https://img.shields.io/badge/docs-mkdocs--material-1f6feb)](https://thinkflowlab.github.io/agentdescent/)
[![python](https://img.shields.io/badge/python-%E2%89%A53.9-1f6feb)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-3fb950)](https://github.com/ThinkFlowLab/agentdescent/blob/main/LICENSE)

## Install

```bash
pip install "agentdescent[mcp]>=0.10.0"
agentdescent demo                         # a complete evolution, offline, no API key, ~10 s
agentdescent doctor                       # which agent CLIs and provider keys this machine has
```

The default host / MCP loop is **Path A** (`doctor` → `plan` → `start` → `apply`).
Advanced MCP tools need `agentdescent mcp --advanced` — see
[MCP / CLI Path A](docs/mcp-path-a.md).

`[mcp]` adds the agent-facing MCP server and needs Python ≥ 3.10; the library
itself supports 3.9, where you drop `[mcp]` and drive it with the CLI. Research
examples are outside the wheel: to run `python -m examples.run_demo` or any
algorithm port, clone the repo and follow
[Install and first run](docs/start.md#source-examples):

```bash
git clone https://github.com/ThinkFlowLab/agentdescent && cd agentdescent
pip install -e ".[dev,mcp]"
```

`agentdescent demo` builds a skill whose rules name the wrong CSV column, twelve
cases with known totals and a local program as the agent, then runs the real
loop — only the model is replaced — and ends with:

```
held-out reward: 1.000 outcomes: {'committed': 1}
what it learned: rules.md -> 'COLUMN: amount'
```

Skill evolution here means a **multi-file skill library**, not a single prompt:
`agentdescent demo --kind skill_library`.

## 60-second quickstart

Runnable as-is — no API key, no dependencies. Three functions are the whole
contract: how to run a task, how to score it, and what to propose on a failure.

```python
from agentdescent import Task, evolve

tasks = [Task(id=f"t{i}", prompt=f"item {i}") for i in range(12)]

def reward(task, output):                  # must return [0, 1]
    return 1.0 if "2026" in output else 0.0

def run(rendered, task):                   # your solver
    return "answer" + (" 2026" if "year" in rendered else "")

def propose(rendered, task, output, reward):   # what to add on a failure
    return "always state the year"

result = evolve(tasks, reward, run=run, propose=propose,
                rounds=6, n_workers=3, max_concurrency=3)
print(result.rendered, result.final_reward, result.error)
```

To point the same loop at a file or directory:

```bash
agentdescent init ./my-skill --data cases.jsonl --out spec.json
agentdescent plan spec.json            # validates and prices it; runs nothing
agentdescent evolve spec.json --detach
agentdescent status                    # then: show, apply --dry-run, apply
```

Credentials are read from the environment at call time — never from code.
Nothing is written back until `apply`, which backs up first.
[Install and first run](https://thinkflowlab.github.io/agentdescent/start/) has
the real-model path, host setup, and the cost and permission notes. A
dataset-to-skill walkthrough is in
[Quickstart — dataset to skill](https://thinkflowlab.github.io/agentdescent/quickstart-skill/).

## Where to go next

| If you want to… | Start here |
|---|---|
| **Install and run it once** | [Install and first run](https://thinkflowlab.github.io/agentdescent/start/) |
| **Use it from an agent** | [The plugin, step by step](https://thinkflowlab.github.io/agentdescent/plugin-quickstart/) · [Every host](https://thinkflowlab.github.io/agentdescent/plugins/) · [Set it up and test it](https://thinkflowlab.github.io/agentdescent/testing-guide/) |
| **Evolve a skill, a directory, or agent code** | [Dataset to skill](https://thinkflowlab.github.io/agentdescent/quickstart-skill/) · [Directory](https://thinkflowlab.github.io/agentdescent/quickstart-directory/) · [Agent code](https://thinkflowlab.github.io/agentdescent/quickstart-agent-code/) |
| **Call or add an algorithm** | [Named algorithms](https://thinkflowlab.github.io/agentdescent/algorithms/) · [Twenty-three ports](https://thinkflowlab.github.io/agentdescent/self-evolution-examples/) · [Register a card](https://thinkflowlab.github.io/agentdescent/algorithm-authoring/) |
| **Understand the engine** | [Architecture](https://thinkflowlab.github.io/agentdescent/architecture/) · [`evolve()`](https://thinkflowlab.github.io/agentdescent/evolution/) · [API](https://thinkflowlab.github.io/agentdescent/api/) |
| **Read the measurements** | [Results](https://thinkflowlab.github.io/agentdescent/results/) · [Efficiency](https://thinkflowlab.github.io/agentdescent/efficiency/) |

On 40 HotpotQA items (12 held out) a one-call `evolve()` run took held-out exact
match from **0.167 to 0.583**. The [results page](https://thinkflowlab.github.io/agentdescent/results/)
records the setting, the caveats, and the runs where there was nothing left to
learn.

## How it works

![AgentDescent architecture: N workers roll out against ledger snapshots and emit
diffs with evidence cards into a buffer; a single aggregator thread runs the
five-stage merge pipeline and commits to a git-backed ledger; four pluggable
seams sit under the components they select; the L0 governance layer gates the
audit step.](https://raw.githubusercontent.com/ThinkFlowLab/agentdescent/main/docs/assets/architecture.png)

*N* workers roll out in parallel; one aggregator merges diffs; a held-out gate
decides what is kept. The long form — strategies, policy slots, and why
governance is not a seam — is in
[Architecture](https://thinkflowlab.github.io/agentdescent/architecture/) and
[Concepts](https://thinkflowlab.github.io/agentdescent/concepts/).

## Citing, scope and contributing

Use GitHub's **Cite this repository** button ([`CITATION.cff`](CITATION.cff));
per-result raw data is in [`bench/results/`](bench/results/).

A **research reference implementation**, not a production system. The novelty is
a narrow engineering synthesis — concurrent, staleness-bounded,
conflict-resolved diff-level merge over a git-backed versioned ledger — and its
throughput premise is a testable hypothesis rather than community consensus.
Contributions welcome: [CONTRIBUTING.md](CONTRIBUTING.md). The suite is offline
and deterministic, so `pytest -q` needs no API key.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=ThinkFlowLab/agentdescent&type=Date)](https://www.star-history.com/#ThinkFlowLab/agentdescent&Date)
