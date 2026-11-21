Fixed
Sixteen annotation names `agentdescent` uses in annotations that nothing bound at
module scope now resolve there: `Union`, `Optional` and `Sequence` join existing
`typing` imports, `selection.py` gets a plain `import random`, and twelve
cycle-prone cross-module names sit behind `if TYPE_CHECKING:` blocks (seven new,
one extended). Static readers -- a type checker, a schema generator, the new
`tests/test_annotation_names.py` sweep -- now resolve all 24 sites. Runtime
`typing.get_type_hints()` is unchanged for the twelve names kept behind
`if TYPE_CHECKING:` (that block does not execute), which is why the issue scopes
this as AST-level; no annotation text, signature or generated API text changes
(#1203).
