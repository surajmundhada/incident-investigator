"""Run inside the live worker container to verify its permitted network surface."""

import socket
from pathlib import Path

with socket.create_connection(("demo-evidence", 8000), timeout=2):
    pass
for service in ("fault-controller", "checkout", "payment", "inventory"):
    try:
        connection = socket.create_connection((service, 8000), timeout=2)
    except OSError:
        continue
    connection.close()
    raise AssertionError(f"Worker unexpectedly reached {service}")
if Path("/control/payment.json").exists():
    raise AssertionError("Fault settings are visible to the worker")
print("PASS: worker reaches evidence source; target services and fault controller are unreachable.")
print("PASS: no fault settings mounted in the worker.")
