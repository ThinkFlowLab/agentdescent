Added
Verifier admission on both strata: `VerifierAgreement(rejected_sample_rate=...)`
audits a sample of the commits it rejected, and `admission_report()` reports precision
on the accepted stratum and a lower confidence bound on the recall of the rejected
one (Hajek mean, bootstrap upper bound), so a verifier that rejects good work no
longer scores 1.0 on precision alone. `require_verifier_admission=True` carries it on
`EnsembleReport.admission`: missing or incomplete defers, `reject` fails closed (#940).
