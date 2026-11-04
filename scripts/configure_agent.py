"""Set non-secret agent configuration while preserving the existing ignored .env."""

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--confirm-free-tier", action="store_true")
    args = parser.parse_args()
    if not args.confirm_free_tier or not re.fullmatch(r"gemini-[a-zA-Z0-9.-]{1,80}", args.model):
        parser.error("A validated model ID and confirmed Free-tier project are required")
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8").splitlines()
    values = {"AGENT_MODE": "gemini", "GEMINI_MODEL": args.model, "GEMINI_FREE_TIER_CONFIRMED": "1"}
    output = []
    for line in lines:
        name = line.split("=", 1)[0].strip()
        if name not in values:
            output.append(line)
    output.extend(f"{name}={value}" for name, value in values.items())
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print("Updated non-secret agent settings; the API key and database settings were preserved.")


if __name__ == "__main__":
    main()
