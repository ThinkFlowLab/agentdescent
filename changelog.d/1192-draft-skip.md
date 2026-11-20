Fixed
The label controller skips a draft pull request instead of labelling it, so a
draft parked before it is ready no longer picks up `agent-pr` or a `risk:T*`
label and enter the review queue; a pull request marked ready is labelled as
before (#1192).
