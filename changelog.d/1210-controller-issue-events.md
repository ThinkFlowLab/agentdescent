Changed
The controller wakes on the `issues` events `labeled`, `unlabeled` and `edited`
as well as on the four-a-day cron, so a label set by a non-maintainer or an edit
after the approval demotes the issue in the same minute instead of at the next
tick (#1210).
