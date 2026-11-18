Fixed
`algorithms run` no longer prints the `--rounds 1 --workers 1` quick-trial hint
after a refused `--probe`: with the kind's default rounds and workers the hint
used to land below `next: renew the subscription …`, so the last line on screen
answered a question the refusal had already answered. The hint still prints
after a passing probe and when no probe runs, and every other line of the
refusal is unchanged (#1106).
