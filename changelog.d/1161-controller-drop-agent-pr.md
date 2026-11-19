Fixed
The label controller no longer adds the retired `agent-pr` label, so a
scheduled run cannot undo the repository-wide strip the owner made: the add
block, its reason string and the agent-author/branch heuristics behind it are
gone, and `controller.json` drops the two keys only that rule read (#1161).
