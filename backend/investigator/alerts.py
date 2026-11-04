"""Provider-neutral, closed-window alert adapter; no implicit external connections."""

import hashlib
import json
from datetime import timezone
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .catalog import Identifier
from .schemas import IncidentCreate


class AlertDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Identifier
    occurrence_id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,128}$")
    status: Literal["firing", "resolved"] = "firing"
    incident: IncidentCreate

    def idempotency_key(self):
        # A source occurrence is stable across retries. A recurrence needs a new ID.
        scope = [self.source, self.occurrence_id, self.incident.application]
        return "alert-v1:" + hashlib.sha256(json.dumps(scope).encode()).hexdigest()


ShortText = Annotated[str, Field(max_length=1000)]


class AlertmanagerAlert(BaseModel):
    # Native diagnostic URLs and future additive fields are ignored, never fetched.
    model_config = ConfigDict(extra="ignore")
    status: Literal["firing", "resolved"]
    labels: dict[Annotated[str, Field(max_length=100)], ShortText] = Field(max_length=40)
    annotations: dict[Annotated[str, Field(max_length=100)], ShortText] = Field(max_length=30)
    startsAt: AwareDatetime


class AlertmanagerDelivery(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: Literal["4"]
    receiver: str = Field(min_length=1, max_length=200)
    truncatedAlerts: int = Field(default=0, ge=0, le=0)
    alerts: list[AlertmanagerAlert] = Field(min_length=1, max_length=20)

    def normalized(self):
        deliveries = []
        for alert in self.alerts:
            if alert.status == "resolved":
                deliveries.append(None)
                continue
            labels, annotations = alert.labels, alert.annotations
            required = {"application", "service", "environment", "release", "investigator_source"}
            if not required.issubset(labels) or not {
                "investigator_window_start",
                "investigator_window_end",
            }.issubset(annotations):
                raise ValueError(
                    "Firing alerts require explicit scope/source labels and fixed investigator window annotations"
                )
            identity = [
                self.receiver,
                sorted(labels.items()),
                alert.startsAt.astimezone(timezone.utc).isoformat(),
            ]
            incident = IncidentCreate(
                application=labels["application"],
                service=labels["service"],
                environment=labels["environment"],
                release=labels["release"],
                title=annotations.get("summary", labels.get("alertname", "Service alert")),
                description=annotations.get(
                    "description", "Monitor reported a service alert in the declared closed window."
                ),
                starts_at=annotations["investigator_window_start"],
                ends_at=annotations["investigator_window_end"],
                configuration_revision=annotations.get("investigator_configuration_revision"),
                snapshot_id=annotations.get("investigator_snapshot_id"),
            )
            deliveries.append(
                AlertDelivery(
                    source=labels["investigator_source"],
                    occurrence_id=hashlib.sha256(
                        json.dumps(identity, separators=(",", ":")).encode()
                    ).hexdigest(),
                    incident=incident,
                )
            )
        return deliveries
