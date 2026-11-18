Fixed
A snapshot's `artifact_id` is validated as one path-safe component when the
snapshot is built, and both staging writes (`snapshot eval`, `snapshot apply`)
stage under a fixed name inside their temp directory instead of deriving a
path from the id: applying or scoring a snapshot JSON received from someone
else can no longer make the staging write land outside that temp directory.
A malformed id is reported as a clean CLI error (exit 2), not a traceback
(#1150).
