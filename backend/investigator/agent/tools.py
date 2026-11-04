import hashlib
import json

from sqlalchemy.exc import SQLAlchemyError

from investigator.catalog import DEFAULT_APPLICATION, incident_configuration, permitted_services
from investigator.knowledge.store import KnowledgeUnavailable, SearchRequest


def call_key(name, arguments):
    canonical = json.dumps({"name": name, "arguments": arguments}, sort_keys=True)
    return "agent." + hashlib.sha256(canonical.encode()).hexdigest()


class Toolset:
    def __init__(self, logs, knowledge=None):
        self.logs, self.knowledge = logs, knowledge

    def execute(self, name, arguments, incident):
        if arguments.service not in permitted_services(incident):
            raise ValueError("Tool service is outside the reviewed dependency scope")
        if name == "search_logs":
            payload = self.logs.collect({**incident, "service": arguments.service})
            if arguments.request_id:
                payload["records"] = [
                    row
                    for row in payload["records"]
                    if row.get("request_id") == arguments.request_id
                ]
                payload["request_id_filter"] = arguments.request_id
            return payload
        if name == "get_service_dependencies":
            return {
                "source": "reviewed_service_map",
                "availability": "available",
                "application": incident.get("application", DEFAULT_APPLICATION),
                "configuration_revision": incident.get("configuration_revision"),
                "release": incident.get("release", "demo-v1"),
                "service": arguments.service,
                "dependencies": incident_configuration(incident)
                .services[arguments.service]
                .dependencies,
            }
        if name == "search_runbooks":
            try:
                if self.knowledge is None:
                    raise KnowledgeUnavailable("No configured corpus")
                return self.knowledge.search(
                    SearchRequest(
                        query=arguments.query,
                        application=incident.get("application", DEFAULT_APPLICATION),
                        service=arguments.service,
                        environment=incident.get("environment", "local"),
                        release=incident.get("release", "demo-v1"),
                        revision=incident.get("knowledge_revision"),
                        profile=incident.get("retrieval_profile"),
                    )
                )
            except (SQLAlchemyError, KnowledgeUnavailable, ValueError, RuntimeError):
                return {
                    "source": "versioned_runbooks",
                    "availability": "unavailable",
                    "hits": [],
                    "error": "knowledge_unavailable",
                }
        raise ValueError("Unknown read-only tool")
