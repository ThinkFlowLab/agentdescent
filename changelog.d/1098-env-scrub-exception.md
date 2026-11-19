Fixed
The env-scrub note no longer says it drops "every" session marker and then keeps
some of them: `docs/dsh-super-agent.md` and the #1082 release note now name the
four host config roots (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `DSH_HOME`,
`XDG_CONFIG_HOME`) as an exception to the marker list before that list appears,
so the first clause cannot be read as dropping them (#1098).
