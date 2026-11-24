Added
`python -m bench` lists the benchmark modules that can be run on their own, one
line per module saying what it measures, and `python -m bench <name> ...`
dispatches to that module; an unknown name exits `2` with the list instead of a
traceback (#1262).
