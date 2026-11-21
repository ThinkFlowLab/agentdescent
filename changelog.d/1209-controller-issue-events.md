Fixed
The controller workflow also runs on the `issues` events `labeled`, `unlabeled`
and `edited`, so an approval that someone voided by setting a label or editing
the issue is read in the same minute instead of at the next cron tick -- the
schedule once skipped 14 h 16 min (#1209).
