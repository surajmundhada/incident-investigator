"""A read-only HTTP log adapter with bounded responses and explicit availability."""

import json
from datetime import datetime, timezone

import httpx
from pydantic import ValidationError

from .catalog import DEFAULT_APPLICATION, DEMO_CONFIGURATION
from .schemas import LogBatch


class LogTool:
    def __init__(self, base_url, timeout=5.0, transport=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def collect(self, incident):
        start, end = incident["starts_at"], incident["ends_at"]
        result = {
            "application": incident.get("application", DEFAULT_APPLICATION),
            "configuration_revision": incident.get("configuration_revision"),
            "source": "http_log_adapter",
            "service": incident["service"],
            "window": {"start": start, "end": end},
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "availability": "unavailable",
            "records": [],
            "truncated": False,
        }
        if (
            incident.get("application", DEFAULT_APPLICATION) != DEFAULT_APPLICATION
            or incident.get("configuration_revision", DEMO_CONFIGURATION.revision)
            != DEMO_CONFIGURATION.revision
            or incident.get("environment", "local") != "local"
            or incident.get("release", "demo-v1") != "demo-v1"
        ):
            result["error"] = "unsupported_observation_scope"
            return result
        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=self.transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                with client.stream(
                    "GET",
                    self.base_url + "/evidence/logs",
                    params={
                        "service": incident["service"],
                        "start": start,
                        "end": end,
                        "limit": 100,
                    },
                ) as response:
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 256_000:
                            raise ValueError("Source response exceeded size limit")
            batch = LogBatch.model_validate(json.loads(body))
            records = [
                r.model_dump(mode="json")
                for r in batch.records
                if r.service == incident["service"] and start <= r.timestamp.timestamp() <= end
            ]
            result.update(
                availability="available",
                records=records,
                truncated=batch.truncated,
                data_origin=batch.origin,
            )
        except httpx.TimeoutException:
            result["error"] = "source_timeout"
        except httpx.HTTPStatusError:
            result["error"] = "source_http_error"
        except httpx.RequestError:
            result["error"] = "source_unreachable"
        except (ValidationError, ValueError, UnicodeDecodeError):
            result["error"] = "invalid_source_response"
        return result
