"""Create ignored local database configuration without displaying credentials."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root / ".env"
try:
    with destination.open("x", encoding="utf-8") as file:
        file.write(
            "POSTGRES_USER=investigator\n"
            f"POSTGRES_PASSWORD={secrets.token_hex(24)}\n"
            "POSTGRES_DB=investigator\n"
            "API_PORT=8001\n"
        )
    print("Created ignored local configuration with a generated database password")
except FileExistsError:
    print("Existing local configuration retained")
