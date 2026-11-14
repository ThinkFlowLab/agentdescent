Added
An `otel-wire` CI leg installs the `[otel]` extra and exports one span and one
metric to a closed port on `127.0.0.1`, asserting a refused connection is logged
and contained rather than raised out of `export_run`. A test pins that
`export_span` copies `ExportedSpan.attributes` verbatim — it filters and invents
nothing — so the no-content guarantee is `export_run`'s and the caller's for
spans built by hand (#1083).
