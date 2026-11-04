"""Three small services with actual HTTP dependencies and operational logs."""

import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from .control import payment_mode
from .telemetry import Telemetry


class Cart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: Literal["book"] = "book"
    quantity: int = Field(default=1, ge=1, le=10)


def create_app(service=None, log_dir=None, control_dir=None, transport=None):
    service = service or os.environ.get("DEMO_SERVICE", "checkout")
    if service not in {"checkout", "payment", "inventory"}:
        raise ValueError("Unknown demo service")
    log_dir = log_dir or os.environ.get("TELEMETRY_DIR", "/telemetry")
    control_dir = Path(control_dir or os.environ.get("CONTROL_DIR", "/control"))
    telemetry = Telemetry(service, log_dir)

    @asynccontextmanager
    async def lifespan(app):
        telemetry.emit("Service started")
        yield
        telemetry.close()

    app = FastAPI(title=f"Demo {service}", lifespan=lifespan)

    @app.get("/healthz")
    def health():
        return {"status": "ok", "service": service}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        return telemetry.metrics()

    route = {"checkout": "/checkout", "payment": "/charge", "inventory": "/availability"}[service]

    @app.post(route)
    def transact(cart: Cart, x_request_id: str | None = Header(default=None)):
        request_id = (
            x_request_id
            if x_request_id and re.fullmatch(r"[a-f0-9]{32}", x_request_id)
            else uuid.uuid4().hex
        )
        started = time.monotonic()
        status, message = 200, "Request completed"
        dependency = None
        if service == "payment":
            try:
                mode = payment_mode(control_dir)
            except (ValueError, KeyError, TypeError, OSError):
                mode = "unavailable"
            if mode == "slow":
                time.sleep(1.5)  # Exceeds checkout's real one-second downstream deadline.
            if mode == "unavailable":
                status, message = 503, "Payment processing unavailable"
            elif mode == "application_error":
                status, message = 500, "Payment processing failed"
                telemetry.emit("Charge handler failed", level="ERROR", request_id=request_id)
        elif service == "checkout":
            for name, path in (("inventory", "/availability"), ("payment", "/charge")):
                base = os.environ.get(f"{name.upper()}_URL", f"http://{name}:8000")
                try:
                    with httpx.Client(
                        timeout=1.0, transport=transport, trust_env=False, follow_redirects=False
                    ) as client:
                        response = client.post(
                            base + path,
                            json=cart.model_dump(),
                            headers={"X-Request-ID": request_id},
                        )
                        response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    status, message, dependency = 502, "Downstream request failed", name
                    telemetry.emit(
                        message,
                        level="ERROR",
                        request_id=request_id,
                        dependency=name,
                        status_code=exc.response.status_code,
                    )
                    break
                except httpx.TimeoutException:
                    status, message, dependency = 504, "Downstream request deadline exceeded", name
                    telemetry.emit(message, level="ERROR", request_id=request_id, dependency=name)
                    break
                except httpx.RequestError:
                    status, message, dependency = 502, "Downstream request unavailable", name
                    telemetry.emit(message, level="ERROR", request_id=request_id, dependency=name)
                    break
        elapsed = time.monotonic() - started
        telemetry.observe(elapsed, status >= 500)
        telemetry.emit(
            "HTTP request completed",
            level="ERROR" if status >= 500 else "INFO",
            request_id=request_id,
            status_code=status,
            duration_ms=round(elapsed * 1000, 3),
        )
        body = {"service": service, "request_id": request_id, "message": message}
        if dependency:
            body["dependency"] = dependency
        return JSONResponse(body, status_code=status, headers={"X-Request-ID": request_id})

    return app
