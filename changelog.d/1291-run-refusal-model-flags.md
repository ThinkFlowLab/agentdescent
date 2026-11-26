Fixed
The `demo --algorithm` refusal for a card that needs a real model, and the
kind-mismatch hint that retargets a text-only card at one file, now name
`--model` and `--base-url`, in the same shape #1276 already put on first-run
`algorithms run` recipes, so a copied refusal can plan instead of exiting
on placeholders (#1291).
