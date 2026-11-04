"""On-demand immutable exports, leased delivery and checksum reconciliation.

Object storage is optional. No AWS connection is made unless backend=s3 is explicit.
"""

import base64
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from .models import Artifact
from .repository import Conflict, LostLease, NotFound

MAX_ARTIFACT_BYTES = 5_000_000


def checksum(payload):
    return hashlib.sha256(payload).hexdigest()


def serialize(value):
    # SQL row return order is unspecified; export identity must survive reconstruction.
    value = {**value, "evidence": sorted(value.get("evidence", []), key=lambda row: row["id"])}
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise ValueError("Export exceeds the 5 MB artifact limit")
    return payload


def atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class LocalObjects:
    name = "local"

    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, key):
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or not key.startswith("exports/v1/"):
            raise ValueError("Invalid artifact key")
        return path

    def verified(self, key, expected, size):
        path = self.path(key)
        if not path.exists():
            return False
        if path.stat().st_size != size or checksum(path.read_bytes()) != expected:
            raise ValueError("Stored artifact checksum mismatch")
        return True

    def put(self, key, payload):
        atomic_write(self.path(key), payload)


class S3Objects:
    name = "s3"

    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def verified(self, key, expected, size):
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key, ChecksumMode="ENABLED")
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        encoded = base64.b64encode(bytes.fromhex(expected)).decode()
        if head.get("ContentLength") != size or head.get("ChecksumSHA256") != encoded:
            raise ValueError("Stored artifact checksum mismatch")
        return True

    def put(self, key, payload):
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=payload,
            ContentType="application/json",
            ServerSideEncryption="AES256",
            ChecksumSHA256=base64.b64encode(hashlib.sha256(payload).digest()).decode(),
        )

    def download(self, key):
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": 'attachment; filename="investigation.json"',
            },
            ExpiresIn=300,
        )


class ArtifactManager:
    def __init__(self, repo, spool, objects):
        self.repo, self.spool, self.objects = repo, Path(spool).resolve(), objects

    @staticmethod
    def describe(row):
        return {
            key: getattr(row, key)
            for key in (
                "id",
                "investigation_id",
                "checksum",
                "size",
                "backend",
                "status",
                "attempts",
                "error",
                "created_at",
            )
        }

    def list(self, iid):
        self.repo.progress_status(iid)
        with self.repo.sessions() as db:
            return [
                {
                    **self.describe(row),
                    "downloadable": row.status == "available" and row.backend == self.objects.name,
                }
                for row in db.scalars(
                    select(Artifact)
                    .where(Artifact.investigation_id == iid)
                    .order_by(Artifact.created_at)
                )
            ]

    def get(self, artifact_id):
        with self.repo.sessions() as db:
            row = db.get(Artifact, artifact_id)
            if row is None:
                raise NotFound("Artifact not found")
            return row

    def spool_path(self, artifact_id):
        if not re.fullmatch(r"[a-f0-9]{64}", artifact_id):
            raise ValueError("Invalid artifact ID")
        return self.spool / (artifact_id + ".json")

    def create(self, iid):
        value = self.repo.investigation(iid)
        if value["status"] not in {"complete", "failed", "cancelled"}:
            raise Conflict("Wait for a terminal investigation before archiving")
        payload = serialize(value)
        content_hash = checksum(payload)
        artifact_id = checksum((iid + ":" + self.objects.name + ":" + content_hash).encode())
        # Spool before admitting delivery; orphan spool files after DB failure are harmless.
        atomic_write(self.spool_path(artifact_id), payload)
        try:
            with self.repo.sessions.begin() as db:
                row = db.get(Artifact, artifact_id)
                if row is None:
                    row = Artifact(
                        id=artifact_id,
                        investigation_id=iid,
                        checksum=content_hash,
                        size=len(payload),
                        backend=self.objects.name,
                        object_key=f"exports/v1/{value['incident']['application']}/{iid}/{content_hash}.json",
                    )
                    db.add(row)
                    db.flush()
                return self.describe(row)
        except IntegrityError:
            return self.describe(self.get(artifact_id))

    def claim(self, now):
        with self.repo.sessions.begin() as db:
            row = db.scalar(
                select(Artifact)
                .where(
                    Artifact.status == "pending_upload",
                    Artifact.backend == self.objects.name,
                    Artifact.next_attempt_at <= now,
                    or_(Artifact.lease_until.is_(None), Artifact.lease_until < now),
                )
                .order_by(Artifact.created_at, Artifact.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            if row.attempts >= 5:
                row.status, row.error = "failed", "artifact_attempt_limit"
                row.lease_token, row.lease_until = None, None
                return None
            row.attempts += 1
            row.lease_token, row.lease_until = uuid.uuid4().hex, now + 60
            db.flush()
            return row

    def finalize(self, row, values, now):
        with self.repo.sessions.begin() as db:
            changed = db.execute(
                update(Artifact)
                .where(
                    Artifact.id == row.id,
                    Artifact.status == "pending_upload",
                    Artifact.lease_token == row.lease_token,
                    Artifact.lease_until >= now,
                )
                .values(**values, lease_token=None, lease_until=None)
            )
            if changed.rowcount != 1:
                raise LostLease("Artifact upload ownership expired")

    def deliver_once(self, *, now=None):
        fixed_time = now is not None
        now = time.time() if now is None else now
        row = self.claim(now)
        if row is None:
            return False
        try:
            # Reconcile object-first success after a previous process died before DB commit.
            if not self.objects.verified(row.object_key, row.checksum, row.size):
                path = self.spool_path(row.id)
                if not path.exists():
                    payload = serialize(self.repo.investigation(row.investigation_id))
                    if checksum(payload) != row.checksum:
                        raise ValueError("Cannot reconstruct the original artifact")
                    atomic_write(path, payload)
                if path.stat().st_size != row.size:
                    raise ValueError("Spool size mismatch")
                payload = path.read_bytes()
                if checksum(payload) != row.checksum:
                    raise ValueError("Spool checksum mismatch")
                self.objects.put(row.object_key, payload)
                if not self.objects.verified(row.object_key, row.checksum, row.size):
                    raise RuntimeError("Object verification did not confirm availability")
        except Exception:
            self.finalize(
                row,
                {
                    "status": "failed" if row.attempts >= 5 else "pending_upload",
                    "next_attempt_at": now + min(300, 2**row.attempts),
                    "error": "artifact_delivery_failed",
                },
                now if fixed_time else time.time(),
            )
        else:
            self.finalize(
                row, {"status": "available", "error": None}, now if fixed_time else time.time()
            )
        return True

    def retry(self, artifact_id):
        with self.repo.sessions.begin() as db:
            row = db.scalar(select(Artifact).where(Artifact.id == artifact_id).with_for_update())
            if row is None:
                raise NotFound("Artifact not found")
            if row.status != "failed" or row.backend != self.objects.name:
                raise Conflict("Only failed artifacts in the configured backend can be retried")
            row.status, row.attempts, row.next_attempt_at = "pending_upload", 0, 0
            row.error, row.lease_token, row.lease_until = None, None, None
            return self.describe(row)


def configured_artifacts(repo):
    backend = os.environ.get("ARTIFACT_BACKEND", "disabled")
    if backend == "disabled":
        return None
    spool = os.environ.get("ARTIFACT_SPOOL_DIR")
    if not spool:
        raise ValueError("ARTIFACT_SPOOL_DIR is required")
    if backend == "local":
        root = os.environ.get("ARTIFACT_LOCAL_DIR")
        if not root or Path(root).resolve() == Path(spool).resolve():
            raise ValueError("Use separate local archive and spool directories")
        objects = LocalObjects(root)
    elif backend == "s3":
        from importlib.metadata import version

        import boto3
        from botocore.config import Config

        if version("boto3") != "1.43.123" or version("botocore") != "1.43.123":
            raise ValueError("AWS SDK differs from requirements-artifacts.lock")

        if os.environ.get("ARTIFACT_S3_PRIVATE_CONFIRMED") != "1":
            raise ValueError("Confirm the bucket's private configuration before enabling S3")
        bucket, region = os.environ.get("ARTIFACT_S3_BUCKET"), os.environ.get("AWS_REGION")
        if (
            not bucket
            or not region
            or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket)
        ):
            raise ValueError("Configure a private S3 bucket and region explicitly")
        client = boto3.client(
            "s3",
            region_name=region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual", "us_east_1_regional_endpoint": "regional"},
                connect_timeout=1,
                read_timeout=5,
                retries={"total_max_attempts": 1},
            ),
        )
        objects = S3Objects(client, bucket)
    else:
        raise ValueError("Unknown artifact backend")
    return ArtifactManager(repo, spool, objects)
