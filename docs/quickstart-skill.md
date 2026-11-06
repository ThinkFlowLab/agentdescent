---
description: Turn a dataset into an evolved instruction, Agent Skill, or skill library. Worked HotpotQA numbers for the instruction path; library and skill-dir demos for real on-disk skills.
---

# Dataset → evolved skill (which kind?)

"Skill" in this repo covers three different artifacts. Pick the one you mean
before you copy a snippet:

| Artifact | What evolves | Agent sees it as | Start here |
|---|---|---|---|
| **Instruction / playbook** | One prompt string (`SingleSlot`) or accumulated lessons (`AppendRules`) | Text pasted into the prompt | This page (below), or [`examples.skill_evolution`](skill-evolution.md) |
| **Agent Skill (one dir)** | A folder with `SKILL.md` + helpers | Files under `.claude/skills/<name>/` | [`examples.skill_dir_evolution`](quickstart-directory.md) |
| **Skill library** | Several `*/SKILL.md` skills together | Files under `.claude/skills/` (`layout="skill_library"`) | [`examples.skill_library_evolution`](https://github.com/ThinkFlowLab/agentdescent/blob/main/examples/skill_library_evolution.py), [`examples.evoskill`](algo-evoskill.md) |

Calling a `SingleSlot` / `AppendRules` result "a skill" without that split
teaches the wrong mental model: those demos never write an Agent Skill folder.
If you want a host (Claude Code, Codex, OpenCode, DSH) to *discover* what you
evolved, use the skill-dir or skill-library path.

---

## Instruction path — one `evolve()` call

There is one entry point, [`evolve`](evolution.md). Evolving an **instruction**
from a dataset needs three things that are genuinely yours:

1. **your data**,
2. **how to score an answer**,
3. **which model**.

Everything else — wrapping rows as `Task`s, the line that puts the instruction in
front of the question, the scorer, the proposer — is a public building block, so
the whole program is a dozen lines and every one of them is an ordinary
`evolve()` argument:

```python
from agentdescent import SingleSlot, evolve, openai_compatible, reflector, scorer, tasks_from
from agentdescent.dataloader import hf_rows

rows = hf_rows("hotpotqa/hotpot_qa", "validation", config="distractor", limit=40)
model = openai_compatible(model="deepseek-v4-flash")

tasks = tasks_from(rows, prompt="question", gold="answer")     # rows -> Task objects
run = lambda instruction, task: model(f"{instruction}\n\n{task.prompt}")

result = evolve(tasks, scorer("exact"), run=run, propose=reflector(model),
                strategy=SingleSlot(initial_value="You are a helpful assistant."),
                rounds=8, n_workers=8, max_concurrency=8, held_out_frac=0.3,
                patience=3, target_reward=0.98)

print(result.rendered)        # the instruction it learned
print(result.final_reward)    # held-out reward
print(result.outcomes())      # why it went that way
```

## What that call actually does — measured

The block above, run as written on 40 real HotpotQA items with
`deepseek-v4-flash` (12 held out):

| | held-out exact match |
|---|---|
| starting instruction (`"You are a helpful assistant."`) | 2/12 = **0.167** |
| after evolution | 7/12 = **0.583** |

Four rounds, stopped by `patience`; 338 model calls, ~25 min wall-clock. The
instruction it wrote:

> *"Respond with only the requested answer, omitting any extra explanation or
> restatement."*

Which is exactly the failure it was looking at — asked for a short span, the model
was answering with a paragraph:

```
gold='Arena of Khazan'  got='In *Tunnels and Trolls*, an adventure is called a **tunnel** - a playf...'
```

`result.outcomes()` was `{'committed': 1, 'below-threshold': 3}`: one proposal
cleared the gate and three were rejected for not beating it — the gate doing its
job, not a stuck run.

## The pieces

| | |
|---|---|
| `tasks_from(rows, prompt=, gold=)` | rows (dicts) from anywhere → `Task`s; the gold lands in `meta`, where [the reflector reads it](evolution.md#bring-an-agent-you-already-have). Ready-made `Task`s need no wrapping. |
| `scorer(name_or_callable)` | a name from `SCORERS` below, or your own `(task, output) -> float` |
| `run=` | how the instruction meets the question. The lambda above is the whole default; put it after the question, or inside a scaffold, by writing a different one |
| `propose=reflector(model)` | any [completion](agents.md) as the proposer. A cheap model here behind an expensive one in `run=` is a fine trade |
| `strategy=SingleSlot(initial_value=…)` | the artifact is one instruction, and each accepted proposal replaces it. `AppendRules` / `KeyedRules` are the other [text strategies](strategies.md) |

## The scorers

`agentdescent.rewards` covers the common cases, and gets the details right that
are easy to get wrong:

| `scorer(…)` | matches when | notes |
|---|---|---|
| `"last_number"` | the **last** number in the output equals the gold number | the default for arithmetic — models show their working, so the answer is the last number |
| `"exact"` | output equals the gold | casefolds, collapses whitespace, strips trailing punctuation |
| `"contains"` | the gold appears anywhere in the output | forgiving, and the easiest to fool: gold `"2"` is inside `"12"` |
| `"numeric_close"` | last number within a relative tolerance | for rounded answers |

!!! tip "A dataset's answer column is often not just the answer"
    GSM8K's `answer` is the whole worked solution, ending in `#### 72`.
    `last_number` reads the gold the same way it reads the output, so `"72"`,
    `"#### 72"` and `"The answer is 72."` all match. A gold with no number in it
    raises, rather than scoring every item zero.

## The knobs worth choosing

The values in the block above are the ones a dataset run wants, and none of them
is a default of `evolve()` itself:

* `n_workers = max_concurrency = min(8, train tasks)` — one worker per
  training task is the useful ceiling
* `rounds = 8`, `patience = 3`, `target_reward = 0.98` — early stopping, so a
  small dataset does not buy eight rounds of nothing
* `held_out_frac = 0.3`; and `shuffle=True` is worth knowing about — rows arrive
  in dataset order and the train/held-out split is positional, so grouped data
  otherwise holds out one end of the file

Everything else — a barrier-free run (`asynchronous=True, max_seconds=600`), a
custom optimizer (`aggregator_factory=`), a multi-step agent as `run=` — is
[a further argument to the same call](evolution.md). Prefer
[`Policies(...)`](aggregator-factory.md) when you need a decision-plane override
instead of inventing a bespoke factory.

---

## Want a real Agent Skill / skill library instead?

```bash
python -m examples.skill_dir_evolution --dry-run            # one skill folder
python -m examples.skill_library_evolution --dry-run        # ≥2 skills, layout=skill_library
python -m examples.evoskill.evoskill_skill_discovery --dry-run
```

Those demos materialise files into a workspace and fail closed when the agent
does not read them. Installing is explicit: `--install-to DIR` /
`result.write_to(...)`.

---

## Next

* **Have a folder rather than a dataset?**
  [Quickstart — evolve a directory](quickstart-directory.md) does the same thing
  for a skill folder, an agent folder, or its code, with a real agent reading the
  files off disk.
* **Want the knobs?** [The `evolve` method](evolution.md).
* **Want to know why it works?** [Concepts](concepts.md), then
  [the aggregator](aggregator.md).
