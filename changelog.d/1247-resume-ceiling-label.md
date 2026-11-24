Fixed
A registered `resume` clamped by the operator's Ticket ceiling now names that
ceiling in the resumed run's `stop_detail` (`max_calls (AGENTDESCENT_MAX_CALLS):
2 call(s) made, cap 2`) instead of the bare `max_calls: … cap 2` that
contradicted the reply's `source`. The marker is scoped to the run it was
applied to, so a descendant that inherits it cannot label a run of its own, and
a caller that names its own cap stays bare (#1247).
