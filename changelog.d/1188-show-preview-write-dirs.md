Fixed
`agentdescent show --diff` previews the same write `apply` performs: when the
directory backup a plan would take sits outside
`AGENTDESCENT_SURFACE_WRITE_DIRS`, its `apply_plan` reports that refusal --
naming the path and the allowed roots -- instead of listing the same files as
`written` (#1188).
