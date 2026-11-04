"""Explicit operator download; runtime embedding never fetches network files."""

import argparse
import hashlib
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def prepare(destination, write_lock=False, lock_path=None):
    lock_path = lock_path or ROOT / "knowledge" / "embedding-lock.json"
    spec = json.loads(lock_path.read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for name, expected in spec["files"].items():
            if not expected and not write_lock:
                raise ValueError("The embedding lock must contain file checksums")
            path = destination / name
            if not path.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Artifact path must remain inside the model directory")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or (
                expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected
            ):
                url = (
                    f"https://huggingface.co/{spec['repository']}/resolve/{spec['revision']}/{name}"
                )
                temporary = path.with_suffix(path.suffix + ".part")
                try:
                    with client.stream("GET", url) as response, temporary.open("wb") as handle:
                        response.raise_for_status()
                        size = 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > 128_000_000:
                                raise ValueError("Embedding artifact exceeds download bound")
                            handle.write(chunk)
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if expected and expected != actual:
                raise ValueError(f"Checksum mismatch for {name}")
            spec["files"][name] = actual
            print(f"Verified {name}")
    if write_lock:
        lock_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"Local model prepared at {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=ROOT / "data" / "embeddings" / "minilm")
    parser.add_argument("--spec", type=Path, help="Optional locked model specification")
    parser.add_argument(
        "--write-lock", action="store_true", help="Record initial artifact checksums"
    )
    args = parser.parse_args()
    prepare(args.destination.resolve(), args.write_lock, args.spec)
