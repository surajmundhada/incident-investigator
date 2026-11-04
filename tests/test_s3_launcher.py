"""Security boundaries for the operator's temporary-credential bridge, no AWS calls."""

import importlib.util
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "s3_launcher", Path(__file__).resolve().parents[1] / "scripts/start_s3.py"
)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_human_login_environment_drops_inherited_application_secrets(monkeypatch):
    for key in (*launcher.CREDENTIAL_NAMES, "AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.setenv(key, "must-not-use-this")
    monkeypatch.setenv("PATH", "keep-executables")
    env = launcher.clean_environment()
    assert not any(
        key in env for key in (*launcher.CREDENTIAL_NAMES, "AWS_PROFILE", "AWS_DEFAULT_PROFILE")
    )
    assert env["PATH"] == "keep-executables"


def test_external_failure_output_never_exposes_tokens(monkeypatch):
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=1, stdout="SECRET_SESSION_TOKEN", stderr="SECRET_ACCESS_KEY"
        ),
    )
    with pytest.raises(RuntimeError) as error:
        launcher.run(["aws", "sts", "assume-role"], json_output=True)
    assert "SECRET" not in str(error.value)


def test_refresh_precedes_expiration_and_rejects_short_sessions():
    now = datetime.now(timezone.utc)
    assert launcher.refresh_delay((now + timedelta(hours=1)).isoformat(), now) == 2700
    assert launcher.refresh_delay((now + timedelta(minutes=20)).isoformat(), now) == 600
    with pytest.raises(RuntimeError):
        launcher.refresh_delay((now + timedelta(minutes=9)).isoformat(), now)


def test_transient_renewal_is_bounded_and_terminal_auth_failure_is_not_retried():
    now = datetime.now(timezone.utc)
    expiration = (now + timedelta(minutes=15)).isoformat()
    attempts, delays = [], []

    def transient():
        attempts.append(1)
        raise launcher.SetupFailure("temporary", retryable=True)

    with pytest.raises(launcher.SetupFailure):
        launcher.renew_session(transient, expiration, wait=delays.append, now=lambda: now)
    assert len(attempts) == 4 and delays == [10, 20, 40]
    attempts.clear()

    def terminal():
        attempts.append(1)
        raise launcher.SetupFailure("credentials expired", retryable=False)

    with pytest.raises(launcher.SetupFailure):
        launcher.renew_session(terminal, expiration, wait=delays.append, now=lambda: now)
    assert len(attempts) == 1
    with pytest.raises(RuntimeError, match="near credential expiry"):
        launcher.renew_session(
            transient, (now + timedelta(minutes=4)).isoformat(), wait=delays.append, now=lambda: now
        )
    assert len(attempts) == 1


def test_second_s3_launcher_is_rejected_and_lock_releases(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    with launcher.launcher_lock():
        with pytest.raises(RuntimeError, match="Another S3 launcher"):
            with launcher.launcher_lock():
                pytest.fail("Duplicate launcher acquired the lock")
    with launcher.launcher_lock():
        pass


@pytest.mark.parametrize("change", ["extra_principal", "inline", "admin", "long_session"])
def test_rejects_permission_or_trust_expansion(change):
    source = "arn:aws:iam::123456789012:role/setup"
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "TrustOnlyAuthenticatedProjectSetupRole",
                "Effect": "Allow",
                "Principal": {"AWS": source},
                "Action": "sts:AssumeRole",
                "Condition": {"StringLike": {"sts:RoleSessionName": "incident-investigator-*"}},
            }
        ],
    }
    role = {"AssumeRolePolicyDocument": trust, "MaxSessionDuration": 3600}
    expected = {"Statement": [{"Action": ["s3:GetObject", "s3:PutObject"]}]}
    policy = deepcopy(expected)
    attached, inline = ["archive"], []
    launcher.validate_role(role, source, attached, inline, policy, expected)
    if change == "extra_principal":
        trust["Statement"][0]["Principal"]["AWS"] = "*"
    elif change == "inline":
        inline.append("unexpected")
    elif change == "admin":
        policy["Statement"][0]["Action"] = ["*"]
    else:
        role["MaxSessionDuration"] = 43200
    with pytest.raises(RuntimeError):
        launcher.validate_role(role, source, attached, inline, policy, expected)
