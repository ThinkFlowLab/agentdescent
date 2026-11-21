Fixed
Sixteen annotation names `agentdescent` uses in its own annotations are now
imported at module scope, so `typing.get_type_hints()` on those objects no
longer raises `NameError`. Import-only change: no behaviour, signature or
generated API text changes (#1203).
