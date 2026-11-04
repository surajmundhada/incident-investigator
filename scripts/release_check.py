"""Check candidate source for configured secrets; export a clean source tree.

This is not a comprehensive secret-detection guarantee or remote CI execution.
Never prints matching values or copies ignored credentials/runtime databases.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    "backend",
    "demo-app",
    "frontend",
    "tests",
    "scripts",
    "knowledge",
    "scenarios",
    "examples",
    "docs",
    "evaluation",
    "infra",
    ".github",
}
SECRET_NAMES = {
    "GEMINI_API_KEY",
    "POSTGRES_PASSWORD",
    "ALERT_WEBHOOK_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
}


def candidates():
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    paths = []
    for name in result.stdout.decode("utf-8").split("\0"):
        if not name:
            continue
        relative = Path(name)
        path = ROOT / relative
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise RuntimeError("Unexpected symlink or path outside release workspace")
        if path.is_file() and (len(relative.parts) == 1 or relative.parts[0] in ALLOWED):
            paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path)
    args = parser.parse_args()
    secrets = []
    local_env = ROOT / ".env"
    for line in (
        local_env.read_text(encoding="utf-8-sig").splitlines() if local_env.exists() else []
    ):
        name, separator, value = line.partition("=")
        if separator and name.strip() in SECRET_NAMES:
            value = value.strip().strip("\"'")
            if len(value) >= 12:
                secrets.append(value.encode())
    paths = candidates()
    issues, hashes = [], {}
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        payload = path.read_bytes()
        if any(secret in payload for secret in secrets):
            issues.append({"file": relative, "reason": "configured_secret_value"})
        if (
            path.name == ".env"
            or ".aws" in path.parts
            or path.suffix in {".sqlite3", ".pem", ".key"}
        ):
            issues.append({"file": relative, "reason": "private_runtime_material"})
        hashes[relative] = hashlib.sha256(payload).hexdigest()
    report = {
        "candidate_files": len(paths),
        "configured_secrets_checked": len(secrets),
        "issues": issues,
        "scope": "configured-secret exact matching and private runtime exclusions; not exhaustive secret scanning",
    }
    (ROOT / "work").mkdir(exist_ok=True)
    (ROOT / "work/release-check.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if issues:
        raise SystemExit(1)
    if args.export:
        target = args.export.resolve()
        if not target.is_relative_to(ROOT / "work") or target.exists():
            raise ValueError("Export must be a new directory inside this workspace's work folder")
        target.mkdir(parents=True)
        for path in paths:
            output = target / path.relative_to(ROOT)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, output)
        (ROOT / "work/release-source-manifest.json").write_text(json.dumps(hashes, indent=2))
        print("Clean source export created; ignored keys, models and runtime data were not copied.")


if __name__ == "__main__":
    main()
