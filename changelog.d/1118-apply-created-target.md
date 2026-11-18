Fixed
`apply` into a tree target that no longer exists now says so: the plan carries
`"created": true` and a real run prints `created <dest> from run <id>; nothing
was restored and no backup was taken` once on stderr, instead of a
`written`/`backup: []` plan that read like an ordinary in-place update. An
in-place apply keeps `"created": false` and prints no line; so does a no-op one,
because an empty artifact into a missing target writes nothing and must not
claim a recreate. The dry run reports the flag without the line, since it
creates nothing. The flag is emitted for the tree path only: a text `--to` plan
is unchanged and carries no `created` key (#1118).
