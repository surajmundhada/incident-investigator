import threading
import time

from investigator.fixture_source import make_fixture_server
from investigator.schemas import IncidentCreate
from investigator.tools import LogTool
from investigator.worker import run_once


def test_real_http_collection_preserves_fixture_origin(repo, payload):
    server = make_fixture_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = IncidentCreate(**payload)
        from datetime import datetime, timezone

        request.ends_at = datetime.fromtimestamp(time.time() + 0.01, timezone.utc)
        admission = repo.admit(request, "real-http")
        assert run_once(repo, LogTool(f"http://127.0.0.1:{server.server_port}"))
        result = repo.investigation(admission["investigation_id"])
        assert len(result["evidence"][0]["records"]) == 2
        assert result["evidence"][0]["data_origin"] == "fixture"
        assert any("fixture" in text for text in result["report"]["limitations"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
