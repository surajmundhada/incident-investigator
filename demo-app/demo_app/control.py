"""Operator-only temporary fault controls. Never mounted or routed to the agent."""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field


class PaymentState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["healthy", "unavailable", "slow", "application_error"]
    ttl_seconds: int = Field(default=60, ge=5, le=300)


def payment_unavailable(directory):
    return payment_mode(directory) == "unavailable"


def payment_mode(directory):
    try:
        state = json.loads((Path(directory) / "payment.json").read_text(encoding="utf-8"))
        mode = state["mode"]
        if mode not in {"healthy", "unavailable", "slow", "application_error"}:
            raise ValueError("Unknown payment control state")
        return mode if float(state["expires_at"]) > time.time() else "healthy"
    except FileNotFoundError:
        return "healthy"
    # Malformed control state must not silently look healthy.


def create_app(directory=None):
    directory = Path(directory or os.environ.get("CONTROL_DIR", "/control"))
    directory.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Local operator fault controller")

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.post("/faults/payment")
    def set_payment(state: PaymentState):
        expires_at = time.time() + state.ttl_seconds
        temporary = directory / f".{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(
                json.dumps({"mode": state.mode, "expires_at": expires_at}), encoding="utf-8"
            )
            temporary.replace(directory / "payment.json")
        finally:
            temporary.unlink(missing_ok=True)
        return {"mode": state.mode, "expires_at": expires_at}

    return app
