---
description: Install AgentDescent, run the offline demo, and take the shortest path into Python, the CLI, or your coding agent.
---

# Install and first run

This is the shortest path from a fresh machine to one complete evolution.
Nothing here needs an API key until you point the loop at a real model.

## Install

```bash
pip install "agentdescent[mcp]>=0.11.0"
agentdescent demo                         # a complete evolution, offline, no API key, ~10 s
agentdescent doctor                       # which agent CLIs and provider keys this machine has
```

`[mcp]` adds the agent-facing MCP server and needs Python ≥ 3.10. The library
itself supports 3.9: drop `[mcp]` and drive it with the CLI.

`agentdescent demo` builds a skill whose rules name the wrong CSV column, twelve
cases with known totals and a local program as the agent, then runs the real
loop — only the model is replaced — and ends with:

```
held-out reward: 0.000 -> 1.000   outcomes: {'committed': 1}
what it learned:  rules.md -> 'COLUMN: amount'
```

Skill evolution means a **multi-file skill library**, not a single prompt:

```bash
agentdescent demo --kind skill_library
```

For the one-command installer that also wires Claude Code, Codex, OpenCode or
DeepSeek Harness when they are already on your `PATH`, use the
[website quickstart](install.md).

## 60-second Python path

Runnable as-is — no API key, no extra dependencies. Three callbacks are the
whole contract: how to run a task, how to score it, and what to propose on a
failure.

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

## CLI path

```bash
agentdescent init ./my-skill --data cases.jsonl --out spec.json
agentdescent plan spec.json            # validates and prices it; runs nothing
agentdescent evolve spec.json --detach
agentdescent status                    # then: show <run_id>, apply <run_id> --dry-run, apply <run_id>
```

`cases.jsonl` is one JSON object per line with `prompt` and `gold`. Nothing is
written back to the target until `apply`, which backs up first. Prefer
`apply --dry-run` before the write.

The default host / MCP loop is the same idea, with slightly different verbs:
`doctor` → `plan` → `start` → `apply`. See [MCP / CLI Path A](mcp-path-a.md).
Advanced MCP tools stay hidden unless you launch `agentdescent mcp --advanced`.

## With a real model {#real-model}

Credentials are read from the environment at call time — never from code — and
the base URL selects the provider
([every provider](agents.md#configuring-your-provider-and-key)):

```bash
export OPENAI_BASE_URL=https://api.deepseek.com   # or GLM, Ark, a local vLLM, OpenAI itself
export OPENAI_API_KEY=sk-...                      # your key for *that* endpoint
```

`agentdescent doctor` tells you which keys and agent CLIs this machine already
has. `plan` quotes an estimated call count and starts nothing. On a model-backed
spec, `plan --probe` makes one minimal call so an expired subscription or a bad
endpoint is refused before a run is written.

Two more checks are opt-in and answer "is this run worth paying for?". Nothing
about them is sent by a plain `plan`:

```bash
agentdescent plan spec.json --baseline-sample 8   # one call per task, quoted first
```

`--baseline-sample N` scores the **seed** artifact on the first N tasks before
the run is quoted: the seed is what every round starts from, so its score is the
ceiling the run has to climb. A seed at or above `--saturation` (default `0.90`)
prints `no headroom` and the paid run is **not** quoted — it could only report
`below-threshold` — unless `--force` asks for the estimate anyway. The sample
itself is priced before its first call (one agent call per task).

`plan` also says when the artifact holds **one key** (a `SingleSlot` prompt, a
one-file tree): every pair of worker proposals contradicts on that key and
collapses to one candidate, so `n_workers` buys best-of-N selection, not
merging. Several keys — several files, `AppendRules` — give the merge something
to fuse.

A dollar cap needs a per-call price, because the engine counts calls and cannot
know a tool-using agent's bill in advance:

```bash
agentdescent plan spec.json --budget 5 --usd-per-call 0.02
```

`--budget` is checked between rounds, so a wide round can overshoot it. For a
cap that holds **per call**, pass `--max-calls` / `--max-usd`: the call that
would cross the limit is not made, the round winds down, and the run ends with
`stop_reason=budget` plus the limit and the spend it observed, in `status.json`
and in `agentdescent status`:

```bash
agentdescent evolve spec.json --max-calls 40
agentdescent evolve spec.json --max-usd 5 --usd-per-call 0.02
```

`--max-calls 0` is a real limit — no calls at all — not "unset". Leave both
flags off and the run behaves exactly as before.

The walkthrough that loads a dataset, calls a model, and evolves an instruction
is in [Quickstart — dataset to skill](quickstart-skill.md). That path evolves a
`SingleSlot` instruction; for a skill library use
`agentdescent demo --kind skill_library` or
`agentdescent init <your-skill-library> --kind skill_library`.

## Source examples {#source-examples}

Research examples are outside the wheel. To run `python -m examples.run_demo`
or any of the twenty-three algorithm ports, clone the repository:

```bash
git clone https://github.com/ThinkFlowLab/agentdescent && cd agentdescent
pip install -e ".[dev,mcp]"
python -m examples.run_demo
```

All 23 ports accept `--dry-run` and make no model call. See the
[port catalog](self-evolution-examples.md). To build these docs:
`pip install -e ".[docs]"` and `mkdocs serve`.

## Where to go next

| If you want to… | Start here |
|---|---|
| **Use it from an agent** | [The plugin, step by step](plugin-quickstart.md) · [Every host](plugins.md) · [Set it up and test it](testing-guide.md) |
| **Evolve a skill, a directory, or agent code** | [Dataset to skill](quickstart-skill.md) · [Directory](quickstart-directory.md) · [Agent code](quickstart-agent-code.md) |
| **Call or add an algorithm** | [Named algorithms](algorithms.md) · [Twenty-three ports](self-evolution-examples.md) · [Register a card](algorithm-authoring.md) |
| **Understand the engine** | [Architecture](architecture.md) · [`evolve()`](evolution.md) · [The main path](main-path.md) |
