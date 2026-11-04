"""One bounded cloud round trip for an existing synthetic, zero-model report.

Does not create incidents, invoke models, delete objects or provision AWS resources.
Never prints the signed download URL. Run only after configuring the S3 launcher.
"""

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx


def expected_download_host(bucket, region):
    if not re.fullmatch(r"(?=.{3,63}$)[a-z0-9][a-z0-9-]*[a-z0-9]", bucket):
        raise ValueError("Configure a DNS-label S3 bucket name")
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d", region):
        raise ValueError("Configure an AWS region")
    return f"{bucket}.s3.{region}.amazonaws.com"


def verify(base_url, investigation_id, *, bucket, region):
    destination = expected_download_host(bucket, region)
    if urlparse(base_url).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("This operator check accepts only the local API")
    with httpx.Client(base_url=base_url, timeout=20, trust_env=False) as client:
        path = "/api/investigations/" + investigation_id
        saved = client.get(path)
        saved.raise_for_status()
        report = saved.json()
        if (
            report["status"] != "complete"
            or not report["incident"]["application"].startswith("verification-")
            or report["report"]["usage"]["model_calls"] != 0
        ):
            raise ValueError(
                "Select a completed synthetic verification report with zero model calls"
            )
        response = client.post(path + "/artifacts")
        response.raise_for_status()
        archive = response.json()
        if archive["backend"] != "s3" or not 0 < archive["size"] <= 64_000:
            raise ValueError("Expected a small synthetic S3 archive")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            listing = client.get(path + "/artifacts")
            listing.raise_for_status()
            archive = next(item for item in listing.json()["items"] if item["id"] == archive["id"])
            if archive["status"] == "available":
                break
            if archive["status"] == "failed":
                raise RuntimeError("Archive delivery failed")
            time.sleep(1)
        if archive["status"] != "available":
            raise RuntimeError("Archive delivery did not finish within one minute")
        redirect = client.get(f"/api/artifacts/{archive['id']}/download", follow_redirects=False)
        if redirect.status_code not in {302, 303, 307}:
            raise RuntimeError("Expected a signed S3 download redirect")
        url = redirect.headers["location"]
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != destination
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
        ):
            raise ValueError(
                "Signed download destination differs from the configured bucket/region"
            )
        # Stream and bound even a malformed/misconfigured storage response.
        payload = bytearray()
        with httpx.stream("GET", url, timeout=30, trust_env=False) as downloaded:
            if downloaded.status_code != 200:
                raise RuntimeError("Signed download failed")
            for chunk in downloaded.iter_bytes():
                payload.extend(chunk)
                if len(payload) > 64_000:
                    raise ValueError("Downloaded artifact exceeds smoke-test bound")
        if (
            len(payload) != archive["size"]
            or hashlib.sha256(payload).hexdigest() != archive["checksum"]
        ):
            raise ValueError("Downloaded bytes do not match the saved archive checksum")
        if json.loads(payload)["id"] != investigation_id:
            raise ValueError("Downloaded report identity differs")
        replay = client.post(path + "/artifacts")
        replay.raise_for_status()
        if replay.json()["id"] != archive["id"]:
            raise ValueError("Duplicate archive request created a different identity")
        return {
            "kind": "synthetic-s3-roundtrip-v1",
            "investigation_id": investigation_id,
            "artifact_id": archive["id"],
            "bytes": len(payload),
            "backend": "s3",
            "checksum_verified": True,
            "signed_download_verified": True,
            "duplicate_request_reused_archive": True,
            "model_calls": 0,
            "diagnosis_accuracy_evaluated": False,
            "deletion_attempted": False,
        }


def main():
    from start_s3 import setting

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--investigation-id", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    try:
        result = verify(
            args.base_url,
            args.investigation_id,
            bucket=setting("ARTIFACT_S3_BUCKET"),
            region=setting("AWS_REGION"),
        )
    except Exception as exc:
        # HTTP exceptions can embed the complete signed URL; keep those private.
        reason = str(exc) if type(exc) in {ValueError, RuntimeError} else type(exc).__name__
        raise SystemExit(
            f"S3 verification failed: {reason}; no signed URL or raw response emitted"
        ) from None
    root = Path(__file__).resolve().parents[1]
    (root / "work").mkdir(exist_ok=True)
    (root / "work/s3-roundtrip-verification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
