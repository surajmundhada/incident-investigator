"""Versioned, bounded application topology; never accepts URLs or instructions."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")]
Release = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{1,40}$")]
Environment = Literal["local", "staging", "production"]
DEFAULT_APPLICATION = "shopping-demo"


class ServiceConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dependencies: list[Identifier] = Field(default_factory=list, max_length=10)


class ApplicationConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application: Identifier
    environment: Environment = "local"
    release: Release = "demo-v1"
    services: dict[Identifier, ServiceConfiguration] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def valid_dependencies(self):
        if "global" in self.services:
            raise ValueError("The service ID global is reserved for shared runbook guidance")
        for name, service in self.services.items():
            if len(set(service.dependencies)) != len(service.dependencies):
                raise ValueError("Dependency IDs must be unique")
            if name in service.dependencies or set(service.dependencies) - self.services.keys():
                raise ValueError("Dependencies must reference other registered services")
        return self

    def canonical(self):
        value = self.model_dump()
        for service in value["services"].values():
            service["dependencies"].sort()
        return value

    @property
    def revision(self):
        return hashlib.sha256(
            json.dumps(self.canonical(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


DEMO_CONFIGURATION = ApplicationConfiguration(
    application=DEFAULT_APPLICATION,
    services={
        "checkout": {"dependencies": ["inventory", "payment"]},
        "inventory": {},
        "payment": {},
    },
)


def incident_configuration(incident):
    """Use the repository's pinned configuration; legacy default incidents stay readable."""
    payload = incident.get("application_config")
    if payload is None:
        if incident.get("application", DEFAULT_APPLICATION) != DEFAULT_APPLICATION:
            raise ValueError("A pinned application configuration is required")
        return DEMO_CONFIGURATION
    config = ApplicationConfiguration.model_validate(payload)
    if (
        config.application != incident.get("application", DEFAULT_APPLICATION)
        or config.environment != incident.get("environment", "local")
        or config.release != incident.get("release", "demo-v1")
        or config.revision != incident.get("configuration_revision")
    ):
        raise ValueError("Pinned application configuration does not match incident scope")
    return config


def permitted_services(incident):
    config = incident_configuration(incident)
    root = incident["service"]
    if root not in config.services:
        raise ValueError("Incident service is not registered")
    # Direct dependencies only. Reading a service map cannot expand this boundary.
    return {root, *config.services[root].dependencies}
