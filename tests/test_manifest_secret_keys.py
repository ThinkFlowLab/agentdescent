"""A manifest must keep the promise its module docstring makes.

``manifest._is_secret_key`` is a second, shorter copy of the credential table
``rsi_telemetry._is_secret_key`` keeps. Measured at live main ``f5cc52ef``, 12
of the 18 credential rows of #1095's acceptance table are ``False`` here, and
one of them is ``PGPASSWORD`` -- so a credential written as one word is stored
in clear *and* hashed in clear, while the module docstring says secrets "are
redacted before hashing and never stored" (#1100).
"""

from __future__ import annotations

import json

import pytest

from agentdescent.evolvespec import EvolveSpec
from agentdescent.manifest import _is_secret_key, build_manifest, redact

# The 18 True rows of #1095's acceptance table: spellings telemetry catches.
CREDENTIAL_KEYS = (
    "PGPASSWORD", "pgpassword", "pgpasswords", "client_secrets",
    "CLIENT_SECRETS", "api_keys", "secret_keys", "s3secretkey", "db_secrets",
    "db_passwords", "passwords", "credentials", "api_key", "client_secret",
    "S3_SECRET_KEY", "AWS_SECRET_ACCESS_KEY", "MYSQL_ROOT_PASSWORD",
    "authorization",
)

# What a cost or budget record exists to carry: a measurement is not a secret.
MEASUREMENT_KEYS = (
    "tokens", "max_tokens", "input_tokens", "output_tokens", "token_count",
    "tokens_in", "budget_tokens", "secret_free", "secrets_scanned",
)

# Spellings a substring rule would swallow, and the recorded #1095 non-goals.
ORDINARY_KEYS = (
    "monkey", "status", "access_level", "max_new_tokens", "total_tokens",
    "REDISCLI_AUTH", "auth", "model", "prompt",
)

# Manifest-only rows: `bearer` is a credential name telemetry does not carry,
# and `sort_key` is a retained false positive of the `_key` suffix rule --
# narrowing it would rewrite existing hashes for no security gain.
MANIFEST_ONLY_KEYS = (
    "bearer", "sort_key", "cache_key", "idempotency_key", "MY_KEY",
)


def _telemetry(key: object) -> bool:
    from agentdescent.rsi_telemetry import _is_secret_key as predicate
    return predicate(key)


def _spec(tmp_path):
    data = tmp_path / "cases.jsonl"
    data.write_text(json.dumps({"prompt": "q", "gold": "a"}) + "\n")
    return EvolveSpec(kind="text", target=str(tmp_path / "prompt.txt"),
                      data={"path": str(data)}, agent="echo"), data


@pytest.mark.parametrize("key", CREDENTIAL_KEYS)
def test_a_credential_spelling_is_redacted(key):
    assert _is_secret_key(key) is True


@pytest.mark.parametrize("key", MEASUREMENT_KEYS + ORDINARY_KEYS)
def test_a_measurement_or_ordinary_key_is_kept(key):
    assert _is_secret_key(key) is False


@pytest.mark.parametrize("key", MANIFEST_ONLY_KEYS)
def test_the_manifest_only_names_stay_redacted(key):
    assert _is_secret_key(key) is True


@pytest.mark.parametrize("key", CREDENTIAL_KEYS + MEASUREMENT_KEYS
                         + ORDINARY_KEYS)
def test_every_telemetry_credential_is_a_manifest_credential(key):
    # Parity: the manifest predicate must not lose a rule telemetry has. A
    # future edit to either predicate alone fails here instead of silently
    # dropping a credential spelling.
    if _telemetry(key):
        assert _is_secret_key(key) is True


@pytest.mark.parametrize("key", CREDENTIAL_KEYS)
def test_a_credential_spelling_is_also_a_telemetry_credential(key):
    assert _telemetry(key) is True


@pytest.mark.parametrize("key", MEASUREMENT_KEYS)
def test_a_measurement_stays_a_measurement_in_telemetry(key):
    # The #1070 counters the widening must not swallow, pinned on both sides of
    # the parity table: `max_tokens` is not a credential because `tokens` is.
    assert _telemetry(key) is False
    assert _is_secret_key(key) is False


def test_redact_scrubs_a_one_word_credential():
    assert redact({"PGPASSWORD": "hunter2", "s3secretkey": "zz-abc-zz"}) == {
        "PGPASSWORD": "<redacted>", "s3secretkey": "<redacted>"}


def test_redact_keeps_a_measurement():
    assert redact({"MAX_TOKENS": 16, "secrets_scanned": 12}) == {
        "MAX_TOKENS": 16, "secrets_scanned": 12}


def test_build_manifest_stores_no_one_word_credential(tmp_path):
    spec, data = _spec(tmp_path)
    manifest = build_manifest(
        spec, data_paths=[str(data)],
        model_config={"model": "m", "PGPASSWORD": "hunter2"},
        extra={"s3secretkey": "zz-abc-zz"})
    dump = json.dumps(manifest.to_dict())
    assert "hunter2" not in dump and "zz-abc-zz" not in dump
    assert manifest.model_config["PGPASSWORD"] == "<redacted>"
    assert manifest.extra["s3secretkey"] == "<redacted>"


def test_the_credential_value_does_not_enter_the_model_hash(tmp_path):
    # Redacted before hashing: two passwords that differ in value are the same
    # model configuration, so the same record. A digest of a value is value
    # material (#952).
    spec, data = _spec(tmp_path)
    a = build_manifest(spec, data_paths=[str(data)],
                       model_config={"PGPASSWORD": "hunter2"})
    b = build_manifest(spec, data_paths=[str(data)],
                       model_config={"PGPASSWORD": "correcthorse"})
    assert a.model_hash == b.model_hash
    assert a.manifest_id == b.manifest_id
