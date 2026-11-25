Fixed
`python -m bench.candidate_methods --help` no longer loads every port's dataset
before it can print usage: the matrix reads each port's name, fidelity and
reserved proposal calls from module constants instead of building a policy at
import time, so the command works on a host whose dataset cache is read-only and
needs no download on a clean one (#1260).
