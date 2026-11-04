"""Actual AWS SDK request/response shape checks with botocore's offline stubber."""

import base64
import hashlib

import pytest
from investigator.artifacts import S3Objects


def test_aws_sdk_put_and_head_contract_without_service_calls():
    boto3 = pytest.importorskip("boto3")
    from botocore.stub import Stubber

    client = boto3.client(
        "s3",
        region_name="ap-south-1",
        aws_access_key_id="test-only-access",
        aws_secret_access_key="test-only-secret",
    )
    payload = b'{"synthetic":"contract test"}'
    digest = hashlib.sha256(payload).hexdigest()
    encoded = base64.b64encode(bytes.fromhex(digest)).decode()
    key = "exports/v1/test/contract.json"
    store = S3Objects(client, "private-contract-example")
    with Stubber(client) as stub:
        stub.add_client_error(
            "head_object",
            service_error_code="404",
            http_status_code=404,
            expected_params={"Bucket": store.bucket, "Key": key, "ChecksumMode": "ENABLED"},
        )
        stub.add_response(
            "put_object",
            {},
            expected_params={
                "Bucket": store.bucket,
                "Key": key,
                "Body": payload,
                "ContentType": "application/json",
                "ServerSideEncryption": "AES256",
                "ChecksumSHA256": encoded,
            },
        )
        stub.add_response(
            "head_object",
            {"ContentLength": len(payload), "ChecksumSHA256": encoded},
            expected_params={"Bucket": store.bucket, "Key": key, "ChecksumMode": "ENABLED"},
        )
        assert not store.verified(key, digest, len(payload))
        store.put(key, payload)
        assert store.verified(key, digest, len(payload))
        stub.assert_no_pending_responses()
    client.close()


def test_aws_permission_errors_are_not_successful_empty_objects():
    boto3 = pytest.importorskip("boto3")
    from botocore.exceptions import ClientError
    from botocore.stub import Stubber

    client = boto3.client(
        "s3",
        region_name="ap-south-1",
        aws_access_key_id="test-only-access",
        aws_secret_access_key="test-only-secret",
    )
    store = S3Objects(client, "private-contract-example")
    with Stubber(client) as stub:
        stub.add_client_error(
            "head_object", service_error_code="AccessDenied", http_status_code=403
        )
        with pytest.raises(ClientError):
            store.verified("exports/v1/test/contract.json", "a" * 64, 1)
    client.close()


def test_s3_factory_requires_private_confirmation_and_signs_locally(repo, tmp_path, monkeypatch):
    pytest.importorskip("boto3")
    from urllib.parse import parse_qs, urlsplit

    from investigator.artifacts import configured_artifacts

    for name, value in {
        "ARTIFACT_BACKEND": "s3",
        "ARTIFACT_SPOOL_DIR": str(tmp_path),
        "ARTIFACT_S3_BUCKET": "private-contract-example",
        "AWS_REGION": "ap-south-1",
        "AWS_ACCESS_KEY_ID": "test-only-access",
        "AWS_SECRET_ACCESS_KEY": "test-only-secret",
        "AWS_EC2_METADATA_DISABLED": "true",
        "ARTIFACT_S3_PRIVATE_CONFIRMED": "0",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    with pytest.raises(ValueError, match="private"):
        configured_artifacts(repo)
    monkeypatch.setenv("ARTIFACT_S3_PRIVATE_CONFIRMED", "1")
    manager = configured_artifacts(repo)

    def no_network(*args, **kwargs):
        raise AssertionError("Presigning must not contact AWS")

    monkeypatch.setattr(manager.objects.client._endpoint.http_session, "send", no_network)
    signed = urlsplit(manager.objects.download("exports/v1/test/report.json"))
    assert signed.hostname == "private-contract-example.s3.ap-south-1.amazonaws.com"
    query = parse_qs(signed.query)
    assert query["X-Amz-Credential"][0].split("/")[2] == "ap-south-1"
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Expires"] == ["300"]
    manager.objects.client.close()
