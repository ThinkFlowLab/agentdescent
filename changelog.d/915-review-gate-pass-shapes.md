Fixed
The review gate now counts a `Verdict: PASS` written above its `Tip SHA:` line,
or carrying `(tip <sha>)` inline, so a PASS at the right tip is no longer read
as "says nothing at this tip"; a PASS with no `Ran:`/`Not run:` is counted but
marked `weak: no Ran:/Not run:` (#915).
