import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from investigator.agent.tools import Toolset
from investigator.agent.workflow import Investigator
from investigator.knowledge.corpus import Document, chunk_document
from investigator.knowledge.metrics import measure
from investigator.knowledge.query import incident_query, keyword_query
from investigator.knowledge.store import select_context
from investigator.knowledge.tool import RunbookTool
from investigator.models import Incident
from investigator.repository import Conflict
from investigator.schemas import IncidentCreate
from investigator.tools import LogTool
from sqlalchemy import select
from test_agent import ScriptedProvider, finish, prepare
from test_knowledge import ToyEmbedder


def test_metrics_do_not_reward_duplicate_sections():
    relevant = [{"document": "a", "heading": "one"}, {"document": "b", "heading": "two"}]
    hits = [
        {"document_id": "a", "heading": "one"},
        {"document_id": "a", "heading": "one"},
        {"document_id": "b", "heading": "two"},
    ]
    result = measure(hits, relevant)
    assert result["recall_at_5"] == 1 and result["mrr_at_5"] == 1
    assert 0 < result["ndcg_at_5"] < 1
    assert measure([], [relevant[0]])["recall_at_5"] == 0
    assert measure([], [])["abstained"]
    assert not measure(hits, [])["abstained"]


def test_query_shaping_prioritizes_codes_and_keeps_arguments_as_data():
    value = keyword_query(
        "Please help me understand payment source_timeout HTTP 503 OR 'DROP TABLE'"
    )
    assert value.startswith('"503" OR "source_timeout"')
    assert "please" not in value and "help" not in value
    incident = {"service": "checkout", "title": "Checkout fails", "description": "filler " * 1000}
    query = incident_query(
        incident,
        {
            "records": [
                {
                    "level": "ERROR",
                    "status_code": 503,
                    "dependency": "payment",
                    "message": "Downstream request failed",
                }
            ]
        },
    )
    assert "503" in query[:40] and "payment" in query[:40]
    assert len(query) <= 500


def test_chunking_preserves_markdown_and_source_line_numbers():
    document = Document(id="markdown-test", path="test.md", title="Procedure", service="global")
    body = "# Procedure\n\n## Steps\n\n- first step\n- second step\n\n```python\nif ready:\n    inspect()\n```\n"
    passages = chunk_document(document, body, ToyEmbedder().token_count)
    assert len(passages) == 1
    assert "- first step\n- second step\n\n```python" in passages[0]["body"]
    assert "\n    inspect()\n```" in passages[0]["body"]
    assert passages[0]["line_start"] == 5 and passages[0]["line_end"] == 11


def test_context_diversity_is_bounded_and_can_be_disabled():
    rows = [
        {
            "id": str(i),
            "document_id": "a" if i < 3 else "b",
            "body": f"passage {i}",
            "token_count": 100,
        }
        for i in range(4)
    ]
    selected, tokens = select_context(rows, 3, diversify=True)
    assert [hit["id"] for hit in selected] == ["0", "1", "3"]
    assert tokens == 300
    assert [hit["id"] for hit in select_context(rows, 3)[0]] == ["0", "1", "2"]


def test_old_idempotency_hashes_remain_replayable_with_default_scope(repo, payload):
    original = IncidentCreate(**payload)
    admitted = repo.admit(original, "legacy-scope")
    canonical = {
        "title": original.title,
        "service": original.service,
        "description": original.description,
        "starts_at": original.starts_at.timestamp(),
        "ends_at": original.ends_at.timestamp(),
    }
    with repo.sessions.begin() as db:
        row = db.scalar(select(Incident).where(Incident.id == admitted["incident_id"]))
        row.request_hash_version = 1
        row.request_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True).encode()
        ).hexdigest()
    assert repo.admit(original, "legacy-scope")["replayed"]
    with pytest.raises(Conflict):
        repo.admit(original.model_copy(update={"environment": "staging"}), "legacy-scope")


def test_scope_is_part_of_new_request_identity_and_reported_incident(repo, payload):
    from investigator.catalog import DEMO_CONFIGURATION
    from investigator.registry import Registry

    Registry(repo.sessions).register(
        DEMO_CONFIGURATION.model_copy(update={"environment": "staging", "release": "demo-v2"})
    )
    request = IncidentCreate(**payload, environment="staging", release="demo-v2")
    result = repo.admit(request, "new-scope")
    incident = repo.investigation(result["investigation_id"])["incident"]
    assert incident["environment"] == "staging" and incident["release"] == "demo-v2"
    with pytest.raises(Conflict):
        repo.admit(request.model_copy(update={"release": "demo-v3"}), "new-scope")


def test_local_logs_cannot_be_relabelled_as_another_environment():
    def unexpected(request):
        pytest.fail("Unsupported source scope should never issue an HTTP read")

    tool = LogTool("http://source", transport=httpx.MockTransport(unexpected))
    result = tool.collect(
        {"service": "payment", "environment": "production", "starts_at": 1, "ends_at": 2}
    )
    assert result["availability"] == "unavailable"
    assert result["error"] == "unsupported_observation_scope"


def test_initial_guidance_receives_incident_applicability():
    captured = []

    def search(request):
        captured.append(request)
        return {"availability": "available", "hits": []}

    incident = {
        "title": "Payment fails",
        "description": "Observe errors",
        "service": "payment",
        "environment": "staging",
        "release": "demo-v2",
    }
    RunbookTool(SimpleNamespace(search=search, profile="improved")).collect(
        incident, {"records": []}
    )
    assert captured[0].environment == "staging" and captured[0].release == "demo-v2"


def test_agent_followup_pins_first_knowledge_revision_and_profile(repo, payload):
    claim, incident, initial, _ = prepare(repo, payload)
    seed = repo.record_evidence(
        claim,
        "runbooks.v1",
        {
            "availability": "available",
            "source": "versioned_runbooks",
            "revision": "a" * 64,
            "ranking_profile": "query",
            "hits": [],
        },
    )
    captured = []

    def search(request):
        captured.append(request)
        return {
            "availability": "available",
            "source": "versioned_runbooks",
            "revision": request.revision,
            "ranking_profile": request.profile,
            "hits": [],
        }

    tools = Toolset(SimpleNamespace(), SimpleNamespace(search=search))
    provider = ScriptedProvider(
        [
            {
                "name": "search_runbooks",
                "arguments": {"service": "payment", "query": "payment unavailable"},
            },
            finish,
        ]
    )
    report = Investigator(repo, provider, tools).run(claim, incident, initial + [seed])
    assert captured[0].revision == "a" * 64 and captured[0].profile == "query"
    assert report["knowledge_revision"] == "a" * 64
