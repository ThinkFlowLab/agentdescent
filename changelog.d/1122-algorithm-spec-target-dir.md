Fixed
`algorithm_spec` no longer writes its default starter spec inside a directory
target: when the only allowed write roots are the target itself or below it,
the call returns `ok: false` naming the target and the roots instead of
dropping `agentdescent.<name>.spec.json` into the user's directory; a usable
root outside the target is still preferred, and the description no longer
claims `$AGENTDESCENT_HOME` when that home is the target (#1122).
