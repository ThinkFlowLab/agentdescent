"""A run may claim a replay only for the inputs it actually captured.

Two runs can share a ``RunManifest`` and still diverge: the RNG state, the
harness's hidden state and the environment are not manifest inputs. A replay or
counterfactual claim made from such a record overstates what is reconstructible,
and a "same run" comparison can silently change the environment underneath the
score. These tests pin the contract that closes that gap:

* the environment fingerprint stores *hashes* of allowlisted variables, never
  values, and refuses a secret-shaped name even when a caller asks for it;
* an RNG boundary digest needs a seed or a state summary -- no guessing;
* a record with an uncaptured source is not eligible, and says what it missed;
* a manifest without a capture is ``replay_eligible=False`` with a reason and
  round-trips through JSON, while the capture never changes ``manifest_id``;
* a trajectory keeps the capture through the store, and ``replay_check`` refuses
  a comparison over a side that was not captured;
* ``ReplayLab`` refuses a counterfactual over an ineligible manifest, names what
  was not reconstructed, and leaves ``baseline`` (not a claim) working.
"""

import json

import pytest

from agentdescent import (EnvironmentFingerprint, ReplayCheck, ReplayFidelity,
                          ReplayNotEligible, RngRecord, RunManifest,
                          build_manifest, content_digest, diff_manifest,
                          replay_check, rng_digest)
from agentdescent.counterfactual import (Intervention, ReplayLab, ReplayTrace,
                                         TraceStep)
from agentdescent.evolvespec import EvolveSpec
from agentdescent.trajectory import Trajectory, TrajectoryStore


def _spec(tmp_path, *, prompt="q"):
    data = tmp_path / "cases.jsonl"
    data.write_text(json.dumps({"prompt": prompt, "gold": "a"}) + "\n")
    return EvolveSpec(kind="text", target=str(tmp_path / "prompt.txt"),
                      data={"path": str(data)}, agent="echo"), data


def _fingerprint(**env):
    values = {"PYTHONHASHSEED": "0", "LANG": "C.UTF-8"}
    values.update(env)
    return EnvironmentFingerprint.capture(
        cwd="/work", tools={"pytest": "9.2.0"}, env=values,
        platform_string="Linux-test", python="3.10.12")


def _fidelity(**env):
    return ReplayFidelity.capture(
        environment=_fingerprint(**env),
        rng=(RngRecord("start", rng_digest(seed="7")),
             RngRecord("interaction:1", rng_digest(seed="7", state={"calls": 1}))),
        hidden_state={"tool:sqlite": {"cursor": 3}})


def _sum(steps):
    return sum(step.payload for step in steps if not step.metadata.get("disabled"))


def _trace(*weights, trace_id="t"):
    return ReplayTrace(trace_id, tuple(
        TraceStep(f"s{i}", payload=weight) for i, weight in enumerate(weights)))


# -- the capture itself ------------------------------------------------------


def test_environment_values_are_stored_only_as_hashes():
    fingerprint = _fingerprint()
    assert set(fingerprint.env_hashes) == {"LANG", "PYTHONHASHSEED"}
    assert all(len(v) == 64 and v.isalnum() for v in fingerprint.env_hashes.values())
    assert "0" not in fingerprint.env_hashes.values()
    assert fingerprint.env_hashes["PYTHONHASHSEED"] != fingerprint.env_hashes["LANG"]


def test_the_same_environment_fingerprints_identically_and_a_change_is_named():
    one = _fingerprint()
    assert EnvironmentFingerprint.capture(
        cwd="/work", tools={"pytest": "9.2.0"},
        env={"PYTHONHASHSEED": "0", "LANG": "C.UTF-8"},
        platform_string="Linux-test", python="3.10.12") == one
    moved = _fingerprint(PYTHONHASHSEED="1")
    assert moved.diff(one) == ("environment:env:PYTHONHASHSEED",)


def test_a_secret_value_can_never_appear_in_the_manifest(tmp_path):
    token = "sk-live-939-do-not-store"
    env = {"OPENAI_API_KEY": token, "PYTHONHASHSEED": "0", "LANG": "C.UTF-8"}
    # Not allowlisted -> never read.
    fingerprint = EnvironmentFingerprint.capture(
        cwd="/work", tools={}, env=env, platform_string="Linux-test",
        python="3.10.12")
    assert "OPENAI_API_KEY" not in fingerprint.env_hashes
    # ...and not even when a caller puts it on the list explicitly.
    refused = EnvironmentFingerprint.capture(
        cwd="/work", tools={}, env=env,
        env_names=("OPENAI_API_KEY", "PYTHONHASHSEED"),
        platform_string="Linux-test", python="3.10.12")
    assert "OPENAI_API_KEY" not in refused.env_hashes
    assert set(refused.env_hashes) == {"PYTHONHASHSEED"}

    spec, data = _spec(tmp_path)
    manifest = build_manifest(
        spec, data_paths=[str(data)], code_version="1",
        model_config={"model": "m", "api_key": token},
        replay=ReplayFidelity.capture(
            environment=_fingerprint(), rng=(RngRecord("start", rng_digest(seed="0")),)))
    assert token not in json.dumps(manifest.to_dict(), sort_keys=True)


def test_an_rng_boundary_needs_a_seed_or_a_state_summary():
    with pytest.raises(ValueError, match="seed or a state"):
        rng_digest()
    assert rng_digest(seed="7") == rng_digest(seed="7")
    assert rng_digest(seed="7") != rng_digest(seed="8")
    assert rng_digest(state={"counter": 3}) != rng_digest(state={"counter": 4})
    with pytest.raises(ValueError, match="digest"):
        RngRecord("start", "not-a-digest")
    with pytest.raises(ValueError, match="boundary"):
        RngRecord("", rng_digest(seed="1"))


def test_an_uncaptured_source_makes_the_record_ineligible_and_is_named():
    fidelity = ReplayFidelity.capture(
        environment=_fingerprint(),
        rng=(RngRecord("start", rng_digest(seed="0")),),
        hidden_state={"tool:sqlite": {"cursor": 3}},
        uncaptured=("hidden state: the provider's sampler exposes nothing",))
    assert fidelity.eligible is False
    assert "sampler exposes nothing" in " ".join(fidelity.notes())
    assert ReplayFidelity.from_dict(
        json.loads(json.dumps(fidelity.to_dict()))) == fidelity


def test_a_complete_capture_is_eligible_and_round_trips():
    fidelity = _fidelity()
    assert fidelity.eligible is True
    assert fidelity.notes() == ()
    assert ReplayFidelity.from_dict(
        json.loads(json.dumps(fidelity.to_dict()))) == fidelity
    # Hidden-state summaries are digested on the way in, never stored raw.
    assert fidelity.hidden_state["tool:sqlite"] == content_digest({"cursor": 3})


# -- the manifest ------------------------------------------------------------


def test_a_manifest_without_a_capture_is_not_eligible_and_says_why(tmp_path):
    spec, data = _spec(tmp_path)
    manifest = build_manifest(spec, data_paths=[str(data)], code_version="1")
    assert manifest.replay_eligible is False
    assert manifest.replay_notes
    assert "not captured" in " ".join(manifest.replay_notes)
    back = RunManifest.from_dict(json.loads(json.dumps(manifest.to_dict())))
    assert back == manifest and back.replay_eligible is False


def test_a_captured_manifest_is_eligible_and_round_trips(tmp_path):
    spec, data = _spec(tmp_path)
    manifest = build_manifest(spec, data_paths=[str(data)], code_version="1",
                              replay=_fidelity())
    assert manifest.replay_eligible is True and manifest.replay_notes == ()
    assert manifest.replay["environment"]["cwd"] == "/work"
    back = RunManifest.from_dict(json.loads(json.dumps(manifest.to_dict())))
    assert back == manifest and back.replay_eligible is True


def test_the_capture_does_not_change_the_manifest_id_or_the_input_diff(tmp_path):
    spec, data = _spec(tmp_path)
    plain = build_manifest(spec, data_paths=[str(data)], code_version="1")
    captured = build_manifest(spec, data_paths=[str(data)], code_version="1",
                              replay=_fidelity())
    # The id describes the inputs that make two runs the same run; fidelity is a
    # property of the record kept about one of them.
    assert plain.manifest_id == captured.manifest_id
    assert diff_manifest(plain, captured) == {}


# -- the trajectory ----------------------------------------------------------


def test_a_trajectory_keeps_the_capture_through_the_store(tmp_path):
    store = TrajectoryStore(str(tmp_path))
    captured = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                          rendered="r", replay=_fidelity())
    trace_id = store.record(captured)
    back = store.get(trace_id)
    assert back.replay == captured.replay
    assert back.replay_eligible is True and back.replay_notes == ()
    plain = Trajectory(artifact_id="b", task_id="t", env_fingerprint="env",
                       rendered="r2")
    assert plain.replay_eligible is False and plain.replay_notes


# -- the counterfactual gate -------------------------------------------------


def test_a_counterfactual_is_refused_when_the_manifest_is_not_replay_eligible(tmp_path):
    spec, data = _spec(tmp_path)
    lab = ReplayLab(_sum, manifest=build_manifest(
        spec, data_paths=[str(data)], code_version="1"))
    trace = _trace(1.0, 2.0)
    assert lab.replay_eligible is False
    # Scoring what happened is not a counterfactual claim.
    assert lab.baseline(trace) == 3.0
    with pytest.raises(ReplayNotEligible) as refused:
        lab.counterfactual(trace, [Intervention("s0")])
    assert "not reconstructed" in str(refused.value)
    assert "not captured" in str(refused.value)
    with pytest.raises(ReplayNotEligible):
        lab.leave_one_out(trace)
    with pytest.raises(ReplayNotEligible):
        lab.shapley(trace)


def test_an_eligible_manifest_allows_the_counterfactual(tmp_path):
    spec, data = _spec(tmp_path)
    lab = ReplayLab(_sum, manifest=build_manifest(
        spec, data_paths=[str(data)], code_version="1", replay=_fidelity()))
    result = lab.counterfactual(_trace(1.0, 2.0), [Intervention("s1")])
    assert result.score == 1.0 and result.delta == 2.0


def test_a_lab_without_a_manifest_makes_no_replay_claim():
    lab = ReplayLab(_sum)
    assert lab.replay_eligible is None
    assert lab.counterfactual(_trace(1.0, 2.0),
                              [Intervention("s1")]).delta == 2.0


# -- comparing a replay ------------------------------------------------------


def test_replay_check_accepts_the_same_run_and_names_a_changed_environment():
    captured = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                          rendered="r", output="ok", reward=1.0, replay=_fidelity())
    same = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                      rendered="r", output="ok", reward=1.0, replay=_fidelity())
    assert replay_check(captured, same) == ReplayCheck(ok=True)
    moved = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                       rendered="r", output="ok", reward=1.0,
                       replay=_fidelity(PYTHONHASHSEED="1"))
    report = replay_check(captured, moved)
    assert report.ok is False
    assert "environment:env:PYTHONHASHSEED" in report.changed


def test_replay_check_reports_a_changed_verdict():
    captured = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                          rendered="r", output="ok", reward=1.0, replay=_fidelity())
    degraded = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                          rendered="r", output="bad", reward=0.0, replay=_fidelity())
    report = replay_check(captured, degraded)
    assert report.ok is False and report.verdict_changed is True


def test_replay_check_refuses_a_side_that_was_never_captured():
    plain = Trajectory(artifact_id="a", task_id="t", env_fingerprint="env",
                       rendered="r")
    report = replay_check(plain, plain)
    assert report.ok is False
    assert report.notes and "not captured" in " ".join(report.notes)
