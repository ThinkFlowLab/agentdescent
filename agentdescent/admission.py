"""What a verifier admitted, what it rejected, and what the oracle says (#940).

Auditing only accepted commits measures precision and nothing else -- a verifier
that rejects everything measures 1.0. This report adds the rejected stratum.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from .audit.estimate import bootstrap_ci, hajek_mean

__all__ = ["AdmissionReport", "admission_report"]


@dataclass(frozen=True)
class AdmissionReport:
    """Both strata of one verifier's admissions.

    ``precision``: audited accepted commits whose gain the oracle confirms.
    ``recall_bound``: lower bound on the share of rejected commits that were good.
    ``None`` means "not audited", never "perfect".
    """

    n_accepted: int
    n_rejected: int
    precision: Optional[float]
    recall_bound: Optional[float]
    recommendation: str = "defer"
    reason: str = ""


def admission_report(*, n_accepted: int, n_rejected: int,
                     accepted_confirmed: Sequence[float],
                     rejected_missed: Sequence[float],
                     rejected_sample_rate: float, seed: int = 0
                     ) -> AdmissionReport:
    """Bars: ``reject`` under 0.5, ``admit`` from 0.8; inputs are one
    ``1.0``/``0.0`` per audited commit of that stratum."""
    confirmed = [float(value) for value in accepted_confirmed]
    precision = (sum(confirmed) / len(confirmed)) if confirmed else None
    missed = [float(value) for value in rejected_missed]
    recall_bound: Optional[float] = None
    if missed:
        probs = [rejected_sample_rate or 1.0] * len(missed)
        _, upper = bootstrap_ci(missed, probs, seed=seed)
        if upper != upper:                   # fewer than two audited units
            upper = hajek_mean(missed, probs)
        recall_bound = max(0.0, 1.0 - float(upper))
    if recall_bound is not None and recall_bound < 0.5:
        verdict, reason = "reject", f"recall >= {recall_bound:.3f}: rejects good work"
    elif precision is not None and precision < 0.5:
        verdict, reason = "reject", f"precision {precision:.3f}: the oracle denies"
    elif precision is None or recall_bound is None:
        verdict = "defer"
        reason = "admission is incomplete: the rejected stratum was not audited"
    else:
        verdict = "admit" if precision >= 0.8 and recall_bound >= 0.8 else "defer"
        reason = f"precision {precision:.3f}, recall >= {recall_bound:.3f}"
    return AdmissionReport(n_accepted, n_rejected, precision, recall_bound,
                           verdict, reason)
