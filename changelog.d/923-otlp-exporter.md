Added
An opt-in OpenTelemetry bridge (`agentdescent.otel_export`): `export_run()` writes
one span per round and one per decision, and re-publishes the `rsi_metrics`
families plus a round-reward histogram. It is off unless
`OTEL_EXPORTER_OTLP_ENDPOINT` is set, a host can inject any object with
`export_span`/`export_metric` (so tests need no collector), and the new optional
`agentdescent[otel]` extra is imported only when an `OtlpExporter` is
constructed — importing the package and running normally needs nothing new. No
prompts or responses are exported by default. Credentials embedded in the endpoint
are refused (they belong in `OTEL_EXPORTER_OTLP_HEADERS`), and plain `http://`
is accepted only for a literal loopback collector unless
`AGENTDESCENT_OTEL_ALLOW_INSECURE=1` is set (#923).
