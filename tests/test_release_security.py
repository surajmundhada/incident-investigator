"""Release boundaries: explicit configuration, local ports and S3 templates."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml
from investigator.config import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("value", [None, "", "  "])
def test_database_configuration_has_no_password_fallback(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(ValueError, match="DATABASE_URL must be explicitly configured"):
        Settings.from_env()


def test_explicit_database_configuration_is_retained(monkeypatch):
    url = "postgresql+psycopg://example.invalid/explicit"
    monkeypatch.setenv("DATABASE_URL", url)
    assert Settings.from_env().database_url == url


def test_all_compose_published_ports_are_loopback_only():
    published = []
    for path in ROOT.glob("compose*.yaml"):
        document = yaml.safe_load(path.read_text())
        for name, service in document.get("services", {}).items():
            for port in service.get("ports", []):
                published.append((path.name, name))
                if isinstance(port, str):
                    assert port.startswith("127.0.0.1:"), (path.name, name, port)
                else:
                    assert port.get("host_ip") == "127.0.0.1", (path.name, name)
    assert ("compose.yaml", "api") in published
    package = json.loads((ROOT / "frontend/package.json").read_text())
    assert "--host 127.0.0.1" in package["scripts"]["dev"]
    assert "--host 127.0.0.1" in package["scripts"]["preview"]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_policy_uses_the_configured_bucket_and_rejects_injection():
    launcher = load_script("start_s3")
    policy = launcher.rendered_archive_policy("example-private-archive")
    assert policy["Statement"][0]["Resource"] == "arn:aws:s3:::example-private-archive"
    assert policy["Statement"][1]["Resource"] == "arn:aws:s3:::example-private-archive/exports/v1/*"
    for bad in ['bad"bucket', "*", "bucket/path", "UPPERCASE"]:
        with pytest.raises(ValueError):
            launcher.rendered_archive_policy(bad)


def test_signed_download_host_uses_explicit_bucket_and_region():
    verifier = load_script("verify_s3")
    assert verifier.expected_download_host("example-private-archive", "ap-southeast-2") == (
        "example-private-archive.s3.ap-southeast-2.amazonaws.com"
    )
    with pytest.raises(ValueError):
        verifier.expected_download_host("example-private-archive", "region/attacker")
