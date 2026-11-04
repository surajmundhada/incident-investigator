"""Bridge a host AWS browser login to scoped, temporary API/uploader sessions.

Run after the normal local stack. No IAM mutation, model call or object upload.
--watch renews by recreating only API/uploader before their sessions expire.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE = "IncidentInvestigatorArchiveRole"
CREDENTIAL_NAMES = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
OVERRIDES = (
    "compose.yaml",
    "compose.demo.yaml",
    "compose.knowledge.yaml",
    "compose.agent.yaml",
    "compose.artifacts.yaml",
    "compose.s3.yaml",
)


class SetupFailure(RuntimeError):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


@contextmanager
def launcher_lock():
    (ROOT / "work").mkdir(exist_ok=True)
    with (ROOT / "work/s3-launcher.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError(
                "Another S3 launcher/watcher is running; stop it before changing configuration"
            ) from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def renew_session(
    operation,
    expiration,
    *,
    wait=time.sleep,
    now=lambda: datetime.now(timezone.utc),
    notify=lambda attempt: None,
):
    for attempt in range(4):
        if (
            expiration
            and (datetime.fromisoformat(expiration.replace("Z", "+00:00")) - now()).total_seconds()
            <= 300
        ):
            raise RuntimeError(
                "Session renewal stopped near credential expiry; sign in and restart explicitly"
            )
        try:
            return operation()
        except SetupFailure as exc:
            if not expiration or not exc.retryable or attempt == 3:
                raise
            notify(attempt + 1)
            wait(10 * 2**attempt)


def executable(name, relative):
    found = shutil.which(name)
    if found:
        return found
    candidate = Path(os.environ.get("LOCALAPPDATA", "")) / relative
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError(f"Install {name} or add it to PATH first")


def run(command, *, env=None, timeout=120, json_output=False):
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        if Path(command[0]).stem.lower() == "aws":
            raise SetupFailure("AWS setup request timed out", retryable=True) from None
        raise
    if result.returncode:
        # CLI/Compose diagnostics can contain credential values or signed URLs.
        if Path(command[0]).stem.lower() == "aws":
            transient = {
                "RequestTimeout",
                "Throttling",
                "ThrottlingException",
                "ServiceUnavailable",
                "InternalFailure",
                "InternalError",
                "TooManyRequestsException",
            }
            codes = re.findall(r"An error occurred \(([A-Za-z0-9.]+)\)", result.stderr)
            retryable = bool(codes and codes[0] in transient) or any(
                value in result.stderr
                for value in (
                    "Could not connect to the endpoint",
                    "Connection was closed",
                    "timed out",
                )
            )
            raise SetupFailure(
                "AWS setup operation failed; re-login if credentials expired", retryable=retryable
            )
        raise RuntimeError(
            f"{Path(command[0]).stem} operation failed (exit {result.returncode}); no raw output emitted"
        )
    return json.loads(result.stdout) if json_output else None


def clean_environment():
    env = os.environ.copy()
    for name in (*CREDENTIAL_NAMES, "AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        env.pop(name, None)
    return env


def setting(name):
    if os.environ.get(name):
        return os.environ[name]
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == name:
            return value.strip().strip("\"'")
    raise RuntimeError(f"Configure {name} in local .env first")


def rendered_archive_policy(bucket):
    """Render the reviewed template without embedding an operator's bucket in source."""
    if not re.fullmatch(r"(?=.{3,63}$)[a-z0-9][a-z0-9-]*[a-z0-9]", bucket):
        raise ValueError("Use a DNS-label S3 bucket name (3-63 lowercase letters/digits/hyphens)")
    template = (ROOT / "infra/iam/incident-archive-policy.json").read_text()
    return json.loads(template.replace("${ARTIFACT_S3_BUCKET}", bucket))


def validate_role(role, source_arn, attached, inline, policy, expected):
    expected_trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "TrustOnlyAuthenticatedProjectSetupRole",
                "Effect": "Allow",
                "Principal": {"AWS": source_arn},
                "Action": "sts:AssumeRole",
                "Condition": {"StringLike": {"sts:RoleSessionName": "incident-investigator-*"}},
            }
        ],
    }
    if (
        role["AssumeRolePolicyDocument"] != expected_trust
        or role["MaxSessionDuration"] != 3600
        or role.get("PermissionsBoundary")
        or inline
        or len(attached) != 1
        or policy != expected
    ):
        raise RuntimeError(
            "Archive role configuration differs from reviewed permissions; refusing credentials"
        )


def refresh_delay(expiration, now=None):
    remaining = (
        datetime.fromisoformat(expiration.replace("Z", "+00:00"))
        - (now or datetime.now(timezone.utc))
    ).total_seconds()
    if remaining < 600:
        raise RuntimeError("Temporary session has less than ten minutes remaining")
    return min(2700, remaining - 600)


def session(aws, profile, bucket, region):
    base_env = clean_environment()
    deadline = time.monotonic() + 120

    def call(service, operation, *arguments, credentials=None):
        env = base_env.copy()
        command = [
            aws,
            service,
            operation,
            *arguments,
            "--region",
            region,
            "--output",
            "json",
            "--no-cli-pager",
        ]
        if credentials is None:
            command += ["--profile", profile]
        else:
            env.update(
                dict(
                    zip(
                        CREDENTIAL_NAMES,
                        (
                            credentials["AccessKeyId"],
                            credentials["SecretAccessKey"],
                            credentials["SessionToken"],
                        ),
                        strict=True,
                    )
                )
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SetupFailure("AWS setup preflight exceeded its deadline", retryable=True)
        return run(command, env=env, json_output=True, timeout=min(30, remaining))

    identity = call("sts", "get-caller-identity")
    try:
        source_name = identity["Arn"].split(":assumed-role/", 1)[1].split("/", 1)[0]
    except IndexError:
        raise RuntimeError("Use the reviewed project browser-login setup role") from None
    source = call("iam", "get-role", "--role-name", source_name)["Role"]["Arn"]
    role = call("iam", "get-role", "--role-name", ROLE)["Role"]
    attached = call("iam", "list-attached-role-policies", "--role-name", ROLE)["AttachedPolicies"]
    inline = call("iam", "list-role-policies", "--role-name", ROLE)["PolicyNames"]
    expected_arn = f"arn:aws:iam::{identity['Account']}:policy/IncidentInvestigatorArchiveAccess"
    if len(attached) != 1 or attached[0]["PolicyArn"] != expected_arn:
        raise RuntimeError("Archive role policy attachment changed")
    metadata = call("iam", "get-policy", "--policy-arn", expected_arn)["Policy"]
    policy = call(
        "iam",
        "get-policy-version",
        "--policy-arn",
        expected_arn,
        "--version-id",
        metadata["DefaultVersionId"],
    )["PolicyVersion"]["Document"]
    expected = rendered_archive_policy(bucket)
    validate_role(role, source, attached, inline, policy, expected)
    if expected["Statement"][0]["Resource"] != f"arn:aws:s3:::{bucket}":
        raise RuntimeError("Configured bucket differs from reviewed IAM policy")
    credentials = call(
        "sts",
        "assume-role",
        "--role-arn",
        role["Arn"],
        "--role-session-name",
        "incident-investigator-runtime",
        "--duration-seconds",
        "3600",
    )["Credentials"]
    kwargs = {"credentials": credentials}
    args = ("--bucket", bucket, "--expected-bucket-owner", identity["Account"])
    location = call("s3api", "get-bucket-location", *args, **kwargs)
    blocks = call("s3api", "get-public-access-block", *args, **kwargs)
    ownership = call("s3api", "get-bucket-ownership-controls", *args, **kwargs)
    encryption = call("s3api", "get-bucket-encryption", *args, **kwargs)
    if (
        location["LocationConstraint"] != region
        or blocks["PublicAccessBlockConfiguration"]
        != {
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        }
        or ownership["OwnershipControls"]["Rules"] != [{"ObjectOwnership": "BucketOwnerEnforced"}]
        or any(
            rule["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] != "AES256"
            for rule in encryption["ServerSideEncryptionConfiguration"]["Rules"]
        )
    ):
        raise RuntimeError("Bucket privacy, ownership, encryption or region changed")
    refresh_delay(credentials["Expiration"])
    return credentials


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="incident-investigator-setup")
    parser.add_argument("--build", action="store_true", help="Build the locked optional S3 image")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Refresh in foreground every ~45 minutes; Ctrl+C stops refresh",
    )
    parser.add_argument(
        "--cache", action="store_true", help="Preserve explicitly enabled Redis configuration"
    )
    args = parser.parse_args()
    with launcher_lock():
        try:
            start(args)
        finally:
            if args.watch:
                path = ROOT / "work/s3-runtime-status.json"
                if path.exists():
                    state = json.loads(path.read_text())
                    if state.get("launcher_pid") == os.getpid():
                        state.update(
                            refresh_state="stopped",
                            updated_at=datetime.now(timezone.utc).isoformat(),
                        )
                        path.write_text(json.dumps(state, indent=2))


def start(args):
    aws = executable("aws.exe" if os.name == "nt" else "aws", "Programs/Amazon/AWSCLIV2/aws.exe")
    docker = executable(
        "docker.exe" if os.name == "nt" else "docker",
        "Programs/DockerDesktop/resources/bin/docker.exe",
    )
    bucket, region = setting("ARTIFACT_S3_BUCKET"), setting("AWS_REGION")
    base_env = clean_environment()
    base_env["PATH"] = str(Path(docker).parent) + os.pathsep + base_env.get("PATH", "")
    if args.build:
        print("Building locked S3 image without credentials...", flush=True)
        run(
            [
                docker,
                "build",
                "--target",
                "s3",
                "-f",
                "infra/Dockerfile",
                "-t",
                "incident-investigator-s3:local",
                ".",
            ],
            env=base_env,
            timeout=1800,
        )
    files = list(OVERRIDES)
    if args.cache:
        files.insert(-2, "compose.cache.yaml")
    compose = [docker, "compose"]
    for file in files:
        compose += ["-f", file]
    previous = None
    while True:

        def notify(attempt):
            summary = {
                **previous,
                "refresh_state": "retrying",
                "retry_attempt": attempt,
                "last_error": "temporary_aws_setup_failure",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            (ROOT / "work/s3-runtime-status.json").write_text(json.dumps(summary, indent=2))
            print("Temporary AWS setup failure; bounded renewal retry before expiry.", flush=True)

        try:
            credentials = renew_session(
                lambda: session(aws, args.profile, bucket, region),
                previous["session_expires_at"] if previous else None,
                notify=notify,
            )
        except Exception:
            if previous:
                (ROOT / "work/s3-runtime-status.json").write_text(
                    json.dumps(
                        {
                            **previous,
                            "refresh_state": "stopped",
                            "last_error": "renewal_failed",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        indent=2,
                    )
                )
            raise
        runtime_env = base_env.copy()
        runtime_env.update(
            dict(
                zip(
                    CREDENTIAL_NAMES,
                    (
                        credentials["AccessKeyId"],
                        credentials["SecretAccessKey"],
                        credentials["SessionToken"],
                    ),
                    strict=True,
                )
            )
        )
        runtime_env.update(
            ARTIFACT_S3_BUCKET=bucket, AWS_REGION=region, ARTIFACT_S3_PRIVATE_CONFIRMED="1"
        )
        run(
            [
                *compose,
                "up",
                "--no-build",
                "--no-deps",
                "-d",
                "--wait",
                "--wait-timeout",
                "180",
                "api",
                "artifact-uploader",
            ],
            env=runtime_env,
            timeout=240,
        )
        summary = {
            "backend": "s3",
            "bucket": bucket,
            "region": region,
            "session_expires_at": credentials["Expiration"],
            "refresh_watch": args.watch,
            "credentials_written_to_file": False,
            "refresh_state": "watching" if args.watch else "manual",
            "automatic_renewals": previous["automatic_renewals"] + 1 if previous else 0,
            "launcher_pid": os.getpid(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        (ROOT / "work").mkdir(exist_ok=True)
        (ROOT / "work/s3-runtime-status.json").write_text(json.dumps(summary, indent=2))
        previous = summary
        print(
            f"S3 API/uploader ready. Temporary session expires {credentials['Expiration']}.",
            flush=True,
        )
        delay = refresh_delay(credentials["Expiration"])
        del credentials, runtime_env
        if not args.watch:
            print("Re-run this command before expiry, or use --watch for foreground refresh.")
            return
        print(
            "Refresh watcher active. Keep this process running; Ctrl+C stops refresh.", flush=True
        )
        time.sleep(delay)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Refresh stopped; running containers retain credentials only until their expiry.")
    except RuntimeError as exc:
        print(
            f"S3 startup/refresh failed: {exc}. Existing sessions are not extended.",
            file=sys.stderr,
        )
        sys.exit(1)
    except (subprocess.TimeoutExpired, ValueError, KeyError):
        print(
            "S3 startup/refresh timed out or returned an invalid response. Existing sessions are not extended; no raw credential output emitted.",
            file=sys.stderr,
        )
        sys.exit(1)
