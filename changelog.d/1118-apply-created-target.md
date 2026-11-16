Fixed
`apply` into a target that no longer exists now says so: the plan carries
`"created": true` and a real run prints `created <dest> from run <id>; nothing
was restored and no backup was taken` once on stderr, instead of a
`written`/`backup: []` plan that read like an ordinary in-place update. An
in-place apply keeps `"created": false` and prints no line, and the dry run
reports the flag without the line, since it creates nothing (#1118).
