"""Evolve a **multi-file skill library** that a real agent reads off disk.

This is the flagship skill path: the artifact is a directory *of* Agent Skills
(``skills/*/SKILL.md`` with YAML frontmatter), materialised under
``.claude/skills/`` via ``layout="skill_library"``. The agent has to open the
files to know what to do — there is no prompt-paste path. That is the claim the
example exists to make.

Contrast:

* ``examples.skill_evolution`` — AppendRules **instruction / playbook** text on BBH
  (lessons in a prompt; not an Agent Skill folder).
* ``examples.skill_dir_evolution`` — **one** Agent Skill directory.
* ``examples.evoskill`` — paper port that also evolves a skill library.

The seed library is deliberately wrong on two skills:

* ``csv-total`` — ``COLUMN: id`` (should be ``amount``)
* ``date-parse`` — ``FIELD: month`` (should be ``year``)

Held-out tasks mix both kinds. Wrong or unread skills score 0.

    python -m examples.skill_library_evolution --dry-run
    python -m examples.skill_library_evolution                  # offline, no API key
    python -m examples.skill_library_evolution --agent claude-code
    python -m examples.skill_library_evolution --install-to ~/.claude/skills

Offline mode is not a mock of the framework: the agent is a separate process
bound to a workspace (``cli_agent``); only the reflector is a fixed edit.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sys
import tempfile
from typing import Dict, List, Mapping, Optional

from agentdescent import (
    AggregatorConfig, FileTree, Policies, evolve, load_tree, scorer,
    tree_reflector, tree_runner,
)
from agentdescent.agents import claude_code, cli_agent, codex, openai_compatible
from agentdescent.governance import SKILL_BLAST_RADIUS
from agentdescent.skillspec import validate_skill_tree

SKILL_NAMES = ("csv-total", "date-parse")

_CSV_SKILL_MD = """\
---
name: csv-total
description: Total one column of data.csv in the working directory. Use when asked for a column total or sum from a CSV.
---

# csv-total

Total one column of `data.csv`, which is in the working directory.

1. Read `references/rules.md` to find out **which** column to total.
2. Sum that column across every data row (skip the header).
3. Reply with only the number.
"""

_CSV_RULES_MD = """\
COLUMN: id
"""  # wrong on purpose: `id` is a row number

_DATE_SKILL_MD = """\
---
name: date-parse
description: Extract one calendar field from date.txt in the working directory. Use when asked for year, month, or day from a date file.
---

# date-parse

Read `date.txt` (ISO `YYYY-MM-DD`) and extract one field.

1. Read `references/rules.md` to find out **which** field to report.
2. Parse the date and reply with only that field's value (no leading zeros for month/day).
"""

_DATE_RULES_MD = """\
FIELD: month
"""  # wrong on purpose: tasks ask for the year


def make_library_dir() -> str:
    """Seed ≥2 Agent Skills under a throwaway parent directory."""
    root = tempfile.mkdtemp(prefix="agentdescent-skill-library-")
    csv_path = os.path.join(root, "csv-total")
    os.makedirs(os.path.join(csv_path, "references"))
    with open(os.path.join(csv_path, "SKILL.md"), "w") as fh:
        fh.write(_CSV_SKILL_MD)
    with open(os.path.join(csv_path, "references", "rules.md"), "w") as fh:
        fh.write(_CSV_RULES_MD)

    date_path = os.path.join(root, "date-parse")
    os.makedirs(os.path.join(date_path, "references"))
    with open(os.path.join(date_path, "SKILL.md"), "w") as fh:
        fh.write(_DATE_SKILL_MD)
    with open(os.path.join(date_path, "references", "rules.md"), "w") as fh:
        fh.write(_DATE_RULES_MD)
    return root


def library_validator(state: Mapping[str, Optional[str]]) -> Optional[str]:
    """Every top-level ``*/SKILL.md`` must be a valid Agent Skill."""
    names = {p.split("/", 1)[0] for p in state
             if p and ("/" in p or p.endswith("SKILL.md"))}
    for name in sorted(names):
        if not name or "/" in name:
            continue
        skill_state = {}
        for p, body in state.items():
            if p == f"{name}/SKILL.md":
                skill_state["SKILL.md"] = body
            elif p.startswith(f"{name}/"):
                skill_state[p[len(name) + 1:]] = body
        if "SKILL.md" not in skill_state and not any(
                p.startswith(f"{name}/") for p in state):
            continue
        errors = validate_skill_tree(skill_state, root_name=name)
        if errors:
            return f"skill-library-{name}-{errors[0]}"
    return None


def make_csv_rows(n: int, seed: int) -> List[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        amounts = [rng.randint(1, 99) for _ in range(rng.randint(3, 6))]
        csv = "id,amount,note\n" + "\n".join(
            f"{j + 1},{a},row-{j}" for j, a in enumerate(amounts))
        rows.append({
            "kind": "csv",
            "prompt": "What is the total of the requested column in data.csv?",
            "gold": str(sum(amounts)),
            "fixtures": {"data.csv": csv},
        })
    return rows


def make_date_rows(n: int, seed: int) -> List[dict]:
    rng = random.Random(seed + 17)
    rows = []
    for i in range(n):
        year = rng.randint(1990, 2025)
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        rows.append({
            "kind": "date",
            "prompt": "What year is recorded in date.txt?",
            "gold": str(year),
            "fixtures": {"date.txt": f"{year:04d}-{month:02d}-{day:02d}\n"},
        })
    return rows


def make_rows(n: int = 16, seed: int = 0) -> List[dict]:
    """A mixed library-level suite: half CSV totals, half date years."""
    n_csv = n // 2
    n_date = n - n_csv
    rows = make_csv_rows(n_csv, seed) + make_date_rows(n_date, seed)
    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows


def to_tasks(rows):
    from agentdescent import Task

    return [Task(id=f"t{i}", prompt=r["prompt"],
                 meta={"gold": r["gold"], "fixtures": r["fixtures"],
                       "kind": r["kind"]})
            for i, r in enumerate(rows)]


# ---------------------------------------------------------------------------
# Offline stand-ins -- a real subprocess agent, and a fixed reflector
# ---------------------------------------------------------------------------

_OFFLINE_AGENT = r"""
import csv, os, re, sys

skills = os.path.join('.claude', 'skills')

def read_rules(name):
    p = os.path.join(skills, name, 'references', 'rules.md')
    if not os.path.exists(p):
        return ''
    return open(p).read()

if os.path.exists('data.csv'):
    rules = read_rules('csv-total')
    if not rules:
        print('MISSING_SKILL')
        sys.exit(0)
    m = re.search(r'COLUMN:\s*(\w+)', rules)
    column = m.group(1) if m else 'id'
    rows = list(csv.DictReader(open('data.csv')))
    total = sum(int(r[column]) for r in rows if r.get(column, '').strip().isdigit())
    print(total)
elif os.path.exists('date.txt'):
    rules = read_rules('date-parse')
    if not rules:
        print('MISSING_SKILL')
        sys.exit(0)
    m = re.search(r'FIELD:\s*(\w+)', rules)
    field = (m.group(1) if m else 'month').lower()
    text = open('date.txt').read().strip()
    parts = text.split('-')
    if len(parts) != 3:
        print('BAD_DATE')
        sys.exit(0)
    year, month, day = parts
    mapping = {'year': str(int(year)), 'month': str(int(month)), 'day': str(int(day))}
    print(mapping.get(field, 'UNKNOWN_FIELD'))
else:
    print('NO_FIXTURE')
"""


def offline_agent():
    """A genuine WorkspaceAgent: a separate process, bound to the workspace."""
    return cli_agent([sys.executable, "-c", _OFFLINE_AGENT])


def offline_reflector():
    """Returns the edits a model would return — derived from what it is shown."""
    def complete(prompt: str) -> str:
        edits = []
        # Fix csv-total when the wrong column is still in the shown tree.
        m = re.search(
            r"--- csv-total/references/rules\.md ---\n(.*?)\n(?:---|TASK )",
            prompt, re.DOTALL)
        body = (m.group(1) if m else "COLUMN: id").strip()
        if "COLUMN: amount" not in body:
            fixed = re.sub(r"COLUMN:\s*\w+", "COLUMN: amount", body) or "COLUMN: amount"
            if fixed == body:
                fixed = "COLUMN: amount"
            edits.append({"path": "csv-total/references/rules.md",
                          "content": fixed + "\n"})
        m2 = re.search(
            r"--- date-parse/references/rules\.md ---\n(.*?)\n(?:---|TASK )",
            prompt, re.DOTALL)
        body2 = (m2.group(1) if m2 else "FIELD: month").strip()
        if "FIELD: year" not in body2:
            fixed2 = re.sub(r"FIELD:\s*\w+", "FIELD: year", body2) or "FIELD: year"
            if fixed2 == body2:
                fixed2 = "FIELD: year"
            edits.append({"path": "date-parse/references/rules.md",
                          "content": fixed2 + "\n"})
        if not edits:
            # Already correct; propose a no-op-looking touch so the loop can stop.
            edits.append({"path": "csv-total/references/rules.md",
                          "content": "COLUMN: amount\n"})
        return "<EDITS>" + json.dumps({
            "rationale": "csv-total must sum amount (not id); date-parse tasks ask for year",
            "edits": edits[:2],
        }) + "</EDITS>"
    return complete


def estimate_calls(rounds: int, workers: int, tasks: int) -> Dict[str, int]:
    """Rough upper bound for the dry-run plan (no network)."""
    held = max(1, int(tasks * 0.3))
    per_round = workers * 3 + held * 2
    return {
        "agent_rollouts_upper": rounds * per_round,
        "reflector_calls_upper": rounds * workers,
        "held_out": held,
    }


def evolve_library(path, tasks, *, agent, reflect_with, score="contains", **kw):
    """Everything a skill *library* needs before ``evolve()`` — spelled out.

    ``load_tree`` turns the parent directory into artifact state (keys like
    ``csv-total/SKILL.md``), ``FileTree`` makes paths the merge keys,
    ``tree_runner(..., layout="skill_library")`` materialises each candidate
    under ``.claude/skills/`` and runs the agent there, and ``tree_reflector``
    asks for multi-file edits. ``Policies()`` is the preferred decision-plane
    entry (no bespoke ``aggregator_factory``).
    """
    tree = load_tree(path)
    strategy = FileTree(tree, max_files_per_diff=2, validators=[library_validator])
    run = tree_runner(agent, layout="skill_library", name="skills",
                      overlay=strategy.frozen_files(tree))
    for key, value in (("self_verify", False), ("cheap_eval_tasks", 4),
                       ("held_out_frac", 0.3), ("patience", 3), ("target_reward", 0.98),
                       ("agg_config", AggregatorConfig(batch_trigger=2, max_wait_rounds=1)),
                       ("policies", Policies())):
        kw.setdefault(key, value)
    return evolve(tasks, scorer(score), run=run, strategy=strategy,
                  artifact_id="skill_library",
                  propose=tree_reflector(reflect_with, strategy=strategy),
                  blast_radius=SKILL_BLAST_RADIUS, **kw)


def _print_library_tree(path: str) -> None:
    tree = load_tree(path)
    print("Library tree:")
    for rel in sorted(tree):
        preview = tree[rel].strip().splitlines()[0] if tree[rel].strip() else "(empty)"
        if len(preview) > 72:
            preview = preview[:69] + "..."
        print(f"  {rel}")
        print(f"    {preview}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--agent", default="offline",
                    choices=["offline", "claude-code", "codex"],
                    help="who performs the rollouts (default: a local subprocess)")
    ap.add_argument("--model", default=None,
                    help="reflector model on an OpenAI-compatible endpoint "
                         "(needs OPENAI_API_KEY / OPENAI_BASE_URL)")
    ap.add_argument("--tasks", type=int, default=16)
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the seeded library tree + estimate; no network, no evolve")
    ap.add_argument("--install-to", default=None,
                    help="write the evolved skill library here when the run improves it")
    args = ap.parse_args()

    path = make_library_dir()
    print(f"Library  : {path}")
    print(f"Skills   : {', '.join(SKILL_NAMES)}")
    print(f"Layout   : skill_library (.claude/skills/<name>/)")
    _print_library_tree(path)

    est = estimate_calls(args.rounds, args.workers, args.tasks)
    print(f"\nPlan     : agent={args.agent}, rounds={args.rounds}, "
          f"workers={args.workers}, tasks={args.tasks}")
    print(f"Budget   : up to ~{est['agent_rollouts_upper']} agent rollouts, "
          f"~{est['reflector_calls_upper']} reflector calls "
          f"(held-out ≈ {est['held_out']})")

    if args.dry_run:
        print("\n[dry-run] library tree + estimate only; no evolve, no network.")
        shutil.rmtree(path, ignore_errors=True)
        return

    if args.agent == "offline":
        agent = offline_agent()
    elif args.agent == "claude-code":
        agent = claude_code(extra_args=["--permission-mode", "acceptEdits"],
                            timeout=300.0)
    else:
        agent = codex(timeout=300.0)
    reflect = (openai_compatible(model=args.model) if args.model
               else (offline_reflector() if args.agent == "offline" else agent))

    print(f"Reflector: {args.model or ('stub' if args.agent == 'offline' else args.agent)}")
    print("Start    : csv-total COLUMN=id (wrong); date-parse FIELD=month (wrong)\n")

    result = evolve_library(
        path, to_tasks(make_rows(args.tasks)), agent=agent, reflect_with=reflect,
        rounds=args.rounds, n_workers=args.workers, max_concurrency=args.workers,
        verbose=True)

    print(f"\nfinal reward : {result.final_reward:.3f}")
    print(f"stop reason  : {result.stop_reason}")
    print(f"outcomes     : {result.outcomes()}")
    print(f"error        : {result.error}")
    print("\nevolved rules:")
    print("  csv-total :",
          result.state.get("csv-total/references/rules.md", "(missing)").strip())
    print("  date-parse:",
          result.state.get("date-parse/references/rules.md", "(missing)").strip())

    if args.install_to:
        plan = result.write_to(args.install_to)
        written_skills = {p.split("/", 1)[0] for p in plan["written"] + plan.get("unchanged", [])
                          if "/" in p}
        print(f"\ninstalled {len(plan['written'])} file(s) "
              f"({len(written_skills)} skill dirs) to {args.install_to}"
              + (f" (backup: {plan['backup'][0]})" if plan["backup"] else ""))
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    main()
