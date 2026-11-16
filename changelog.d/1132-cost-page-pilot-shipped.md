Fixed
The cost page no longer says `agentdescent/pilot.py` is absent: the module shipped
in #1121, its `PilotReport` carries the run's cost mapping, and `CostReport`
stays the cost-only surface that page describes (#1132).
