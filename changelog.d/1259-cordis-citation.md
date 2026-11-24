Fixed
`docs/dsh-super-agent.md` cited the `mcp-agentdescent` row as
`cordis.patch.yml:8-26` on a page whose value is that its citations are the
verified part, while that file has 17 lines and the row is `:7-17`. The
citation now names the range that exists, and `tests/test_docs_citations.py`
fails when a `path:line` citation in `docs/` or `README.md` runs past the end
of its file or names a file that is not in this repository (#1259).
