import base64
import hashlib
from types import SimpleNamespace

import pytest
from investigator.artifacts import (
    ArtifactManager,
    LocalObjects,
    S3Objects,
    checksum,
    configured_artifacts,
)
from investigator.models import Artifact
from investigator.repository import Conflict, LostLease
from investigator.schemas import IncidentCreate


@pytest.fixture
def archive(repo, tmp_path, payload):
    iid = repo.admit(IncidentCreate(**payload), "archive")["investigation_id"]
    manager = ArtifactManager(repo, tmp_path / "spool", LocalObjects(tmp_path / "objects"))
    return manager, iid


def test_archive_disabled_and_no_artifact_before_terminal(archive):
    manager, iid = archive
    assert configured_artifacts(manager.repo) is None
    with pytest.raises(Conflict, match="terminal"):
        manager.create(iid)
    assert manager.list(iid) == []


def test_export_duplicate_delivery_checksum_and_spool_reconstruction(archive):
    manager, iid = archive
    manager.repo.cancel(iid)
    first = manager.create(iid)
    assert manager.create(iid)["id"] == first["id"]
    assert first["status"] == "pending_upload"
    manager.spool_path(first["id"]).unlink()  # Terminal DB records reconstruct missing spool.
    assert manager.deliver_once(now=100)
    row = manager.get(first["id"])
    assert row.status == "available" and row.attempts == 1
    payload = manager.objects.path(row.object_key).read_bytes()
    assert checksum(payload) == first["checksum"] and len(payload) == first["size"]
    assert manager.objects.verified(row.object_key, row.checksum, row.size)
    assert not manager.deliver_once(now=101)


def test_same_terminal_report_can_be_archived_in_each_storage_backend(archive, tmp_path):
    local, iid = archive
    local.repo.cancel(iid)
    original = local.create(iid)
    assert local.deliver_once(now=100)
    # A second filesystem store exercises backend identity without cloud requests.
    remote_objects = LocalObjects(tmp_path / "remote-objects")
    remote_objects.name = "s3"
    remote = ArtifactManager(local.repo, tmp_path / "remote-spool", remote_objects)
    second = remote.create(iid)
    assert second["id"] != original["id"]
    assert second["checksum"] == original["checksum"]
    assert remote.create(iid)["id"] == second["id"]
    assert remote.deliver_once(now=100)
    assert local.get(original["id"]).status == "available"
    assert remote.get(second["id"]).status == "available"
    assert local.objects.path(local.get(original["id"]).object_key).is_file()
    assert remote.objects.path(remote.get(second["id"]).object_key).is_file()


@pytest.mark.postgres
def test_pg_upgrade_preserves_local_archive_and_allows_s3_metadata(
    postgres_repo, payload, tmp_path
):
    from alembic import command

    repo, _, config = postgres_repo
    command.downgrade(config, "0007")
    iid = repo.admit(IncidentCreate(**payload), "cross-backend-migration")["investigation_id"]
    repo.cancel(iid)
    local = ArtifactManager(repo, tmp_path / "spool", LocalObjects(tmp_path / "local"))
    first = local.create(iid)
    local.deliver_once(now=100)
    command.upgrade(config, "head")
    objects = LocalObjects(tmp_path / "remote")
    objects.name = "s3"
    remote = ArtifactManager(repo, tmp_path / "spool", objects)
    second = remote.create(iid)
    assert second["checksum"] == first["checksum"]
    assert local.get(first["id"]).status == "available"
    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        command.downgrade(config, "0007")
    assert len(local.list(iid)) == 2


def test_upload_success_before_database_commit_reconciles_and_fences_old_owner(archive):
    manager, iid = archive
    manager.repo.cancel(iid)
    artifact = manager.create(iid)
    original = manager.claim(100)
    payload = manager.spool_path(artifact["id"]).read_bytes()
    manager.objects.put(original.object_key, payload)
    manager.spool_path(artifact["id"]).unlink()
    assert manager.deliver_once(now=161)  # Remote object exists; no spool required.
    assert manager.get(artifact["id"]).status == "available"
    with pytest.raises(LostLease):
        manager.finalize(original, {"status": "failed"}, 162)


def test_artifact_outage_bounded_retry_and_recovery(archive):
    manager, iid = archive
    manager.repo.cancel(iid)
    artifact = manager.create(iid)
    original = manager.objects.verified

    def unavailable(*args):
        raise OSError("secret storage configuration must never be persisted")

    manager.objects.verified = unavailable
    for now in (100, 200, 400, 800, 1200):
        assert manager.deliver_once(now=now)
    failed = manager.get(artifact["id"])
    assert failed.status == "failed" and failed.attempts == 5
    assert failed.error == "artifact_delivery_failed"
    assert not manager.deliver_once(now=1300)
    manager.objects.verified = original
    manager.retry(artifact["id"])
    assert manager.deliver_once(now=1400)
    assert manager.get(artifact["id"]).status == "available"


def test_corrupt_spool_never_becomes_available(archive):
    manager, iid = archive
    manager.repo.cancel(iid)
    artifact = manager.create(iid)
    path = manager.spool_path(artifact["id"])
    payload = path.read_bytes()
    path.write_bytes(b"x" * len(payload))
    assert manager.deliver_once(now=100)
    assert manager.get(artifact["id"]).status == "pending_upload"
    assert not manager.objects.path(manager.get(artifact["id"]).object_key).exists()
    with pytest.raises(ValueError):
        manager.objects.path("../../outside")


def test_artifact_api_serves_verified_download_only(client, archive):
    manager, iid = archive
    client.app.state.artifacts = manager
    manager.repo.cancel(iid)
    artifact = client.post(f"/api/investigations/{iid}/artifacts").json()
    path = f"/api/artifacts/{artifact['id']}/download"
    assert client.get(path).status_code == 409
    manager.deliver_once()
    response = client.get(path)
    assert response.status_code == 200 and response.json()["id"] == iid
    assert response.headers["cache-control"] == "no-store"
    assert checksum(response.content) == artifact["checksum"]
    assert len(client.get(f"/api/investigations/{iid}/artifacts").json()["items"]) == 1
    assert client.get(f"/api/investigations/{iid}/artifacts").json()["items"][0]["downloadable"]
    manager.objects.name = "other"
    assert not client.get(f"/api/investigations/{iid}/artifacts").json()["items"][0]["downloadable"]
    assert client.get(path).status_code == 409
    manager.objects.name = "local"
    assert client.post(f"/api/artifacts/{artifact['id']}/retry").status_code == 409


def test_s3_adapter_requires_checksum_and_encrypts_puts_without_network():
    payload = b'{"example":"synthetic artifact"}'
    expected = checksum(payload)
    calls = []
    encoded = base64.b64encode(hashlib.sha256(payload).digest()).decode()
    client = SimpleNamespace(
        put_object=lambda **kwargs: calls.append(kwargs),
        head_object=lambda **kwargs: {"ContentLength": len(payload), "ChecksumSHA256": encoded},
        generate_presigned_url=lambda *args, **kwargs: (calls.append(kwargs), "signed-test-url")[1],
    )
    store = S3Objects(client, "private-test-bucket")
    store.put("exports/v1/example.json", payload)
    assert calls[0]["ServerSideEncryption"] == "AES256"
    assert calls[0]["ChecksumSHA256"] == encoded and "ACL" not in calls[0]
    assert store.verified("exports/v1/example.json", expected, len(payload))
    assert store.download("exports/v1/example.json") == "signed-test-url"
    assert calls[-1]["ExpiresIn"] == 300
    client.head_object = lambda **kwargs: {"ContentLength": len(payload), "ChecksumSHA256": "wrong"}
    with pytest.raises(ValueError, match="checksum"):
        store.verified("exports/v1/example.json", expected, len(payload))


@pytest.mark.postgres
def test_pg_artifact_claim_has_one_owner_and_expired_claim_recovers(
    postgres_repo, tmp_path, payload
):
    from concurrent.futures import ThreadPoolExecutor

    from investigator.registry import Registry

    repo, _, _ = postgres_repo
    Registry(repo.sessions).ensure_demo()
    iid = repo.admit(IncidentCreate(**payload), "pg-artifact")["investigation_id"]
    repo.cancel(iid)
    manager = ArtifactManager(repo, tmp_path / "spool", LocalObjects(tmp_path / "objects"))
    created = manager.create(iid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: manager.claim(100), range(2)))
    assert sum(claim is not None for claim in claims) == 1
    assert manager.deliver_once(now=161)
    assert manager.get(created["id"]).status == "available"
    with repo.sessions() as db:
        assert db.get(Artifact, created["id"]).attempts == 2
