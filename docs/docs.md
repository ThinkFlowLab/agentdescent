---
description: Choose a path through the AgentDescent docs — first run, hosts and plugins, or algorithms — then follow the deeper reference when you need it.
---

# Documentation

AgentDescent is a parallel, asynchronous engine for self-evolving LLM agents.
You give it an artifact — a prompt, a skill, a directory, a program or a
harness — a way to try tasks, and a reward. It runs candidates in parallel,
merges their edits, accepts only what the held-out evidence supports, and writes
every accepted change to a git-backed ledger.

**Diffs are the gradients; the aggregator is the optimizer.**

Choose the route that matches what you want to do. Each guide links to the
deeper reference when you need it.

<div class="ad-doc-paths">
  <a href="../start/"><span>01 / START</span><strong>Install and first run</strong><small>Install AgentDescent, run the offline demo, then take the Python or CLI path. No API key required for the first run.</small><b>Open first run ↗</b></a>
  <a href="../plugin-quickstart/"><span>02 / HOSTS</span><strong>Use it from your agent</strong><small>Connect Claude Code, Codex, OpenCode, DeepSeek Harness or Grok Bot, review a plan, and apply a diff.</small><b>Open the plugin guide ↗</b></a>
  <a href="../algorithms/"><span>03 / ALGORITHMS</span><strong>Call or add an algorithm</strong><small>Named cards on the wheel, twenty-three research ports in the repo, and how to register your own.</small><b>Open the catalog ↗</b></a>
  <a href="../main-path/"><span>04 / MAP</span><strong>Read the supported path</strong><small>Three product paths, the advanced layers, and the canonical module for each concept.</small><b>Open the main path ↗</b></a>
</div>

## Three audiences

### Getting started

1. **Install and see the loop once, offline.**
   `pip install "agentdescent[mcp]>=0.12.0"`, then `agentdescent demo`.
   Skill evolution means a multi-file library:
   `agentdescent demo --kind skill_library`.
   [Install and first run](start.md)
2. **Point it at your artifact.** From the CLI: `init` → `plan` → `evolve` →
   `show` → `apply`. From Python: `evolve(tasks, reward, run=…, propose=…)`.
   [Dataset to skill](quickstart-skill.md) ·
   [Directory](quickstart-directory.md) ·
   [Agent code](quickstart-agent-code.md)
3. **Read the evidence.** The report carries the decision, the cost and the
   next action. [Measured results](results.md) ·
   [Trust evidence](trust-evidence.md)

The [interactive demo](index.md#demo) walks through the same flow inside a
host agent. The [website quickstart](install.md) is the one-command installer
that also wires supported agents already on your `PATH`.

!!! note "What it is not"

    A research reference implementation, not a hosted product or a benchmark
    leaderboard. The engine and the evidence layer are the product; a host agent
    or a platform owns the UI. Missing evidence defers, and an unchanged artifact
    is not repriced as a gain. Read [the main path](main-path.md) for the
    supported surface and [the results page](results.md) for the caveats behind
    every number.

### Hosts and plugins

The same engine runs as a plugin: a shared skill teaches the host when to reach
for it, an MCP server exposes Path A (`doctor` → `plan` → `start` → `apply`),
and the CLI mirrors those verbs so a run started from an agent can be inspected
from a shell. The host quotes the call count before starting and asks again
before it writes anything back.

- [The plugin, step by step](plugin-quickstart.md)
- [Use it from your agent](plugins.md) — every host, the MCP tools, and evolving
  the plugins themselves
- [MCP / CLI Path A](mcp-path-a.md) — the default loop, and what
  `--advanced` unlocks
- [Set it up and test it](testing-guide.md)
- [dsh-super-agent](dsh-super-agent.md) — the zero-code DeepSeek Harness
  composition
- [Agents & LLMs](agents.md) — providers, keys, and CLI agents

### Algorithms

Named **cards** are wheel mechanism slices you can select from the CLI, a spec,
MCP, or a host plugin. The **twenty-three research ports** live under
`examples/` and need a source checkout. The same slug is not the same fidelity;
never read a card run as paper numbers.

- [Named algorithms](algorithms.md) ·
  [Algorithm decision tree](algorithm-decision-tree.md)
- [Twenty-three ports](self-evolution-examples.md) ·
  [Port fidelity](port-fidelity.md)
- [Register a named Algorithm card](algorithm-authoring.md)
- [Porting checklist](porting-checklist.md) ·
  [MethodPolicy checklist](porting-methodpolicy.md)

## The three supported paths

| path | you have | the product surface |
|---|---|---|
| **A — evolve one artifact** | tasks, a reward, an actor | `agentdescent plan/evolve/status/show/apply/snapshot` |
| **B — governed release** | paired held-out scores | `agentdescent release` + `release verify` |
| **C — continuous platform** | a run database and callbacks | `agentdescent platform` + `platform status` |

These are product surfaces over the same `evolve()` engine, not separate
algorithms. [The main path](main-path.md) is the design contract for where a new
capability belongs. Individual surfaces (`release`, `traces`,
`governed-harness`, `tenant`, `ops`, `platform`, `capability`) each have their
own page under **Product surfaces** in the navigation.

## Go deeper

**The engine.**
[Architecture](architecture.md) · [Concepts](concepts.md) ·
[The `evolve()` method](evolution.md) · [Strategies](strategies.md) ·
[Portable snapshots](snapshot.md) ·
[Policies](policies.md) · [API reference](api.md).

**Run and operate it.**
[Parallelism](parallelism.md) · [Async](async.md) · [Budget](budget.md) ·
[Diagnose](diagnose.md) · [Usage — demos and extension](usage.md).

**Trust and release.**
[Verifier](verifier.md) · [Trusted promotion](trusted-promotion.md) ·
[Release](release.md) · [Safety](safety.md).

**Measurements.**
[Results](results.md) · [Efficiency](efficiency.md) ·
[Runtime matrix](matrix-overview.md).

**Questions about the code?**
[Ask DeepWiki](deepwiki.md) indexes the repository and answers with links to the
source.
