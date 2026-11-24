Fixed
`plan` and `algorithms run` on a `kind=text` spec now name the case `fixtures`
a text prompt never shows: the runner sends `{skill} + {prompt}` and has no
workspace, so a `skill_dir` `cases.jsonl` reused through the one-file hint
planned `ok` while the model could not read the CSV. The note names the
dropped files and the repair (inline the body, or reuse the prompt-inlined
cases from `agentdescent demo --kind text`), and the kind-mismatch hint no
longer stops at `--kind text` without saying that `fixtures` stay behind
(#1251).
