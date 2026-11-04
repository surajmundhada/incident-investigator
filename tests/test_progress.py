import asyncio
import json
from types import SimpleNamespace

import pytest
from investigator.progress import event_stream, frame
from sqlalchemy.exc import OperationalError


def test_stream_terminal_replays_all_pages_and_header_resume(client, repo, payload):
    admitted = client.post(
        "/api/incidents", json=payload, headers={"Idempotency-Key": "sse"}
    ).json()
    iid = admitted["investigation_id"]
    with repo.sessions.begin() as db:
        for number in range(205):
            repo.event(db, iid, "progress", f"row {number}")
    repo.cancel(iid)
    rows = repo.events(iid)
    after = rows[25]["id"]
    response = client.get(
        f"/api/investigations/{iid}/events/stream?after=0", headers={"Last-Event-ID": str(after)}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    ids = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
    assert len(ids) == 181 and ids == sorted(set(ids)) and min(ids) > after
    assert "event: complete\n" in response.text and '"status":"cancelled"' in response.text
    last = client.get(
        f"/api/investigations/{iid}/events/stream", headers={"Last-Event-ID": str(ids[-1])}
    )
    assert "event: progress" not in last.text and "event: complete" in last.text


@pytest.mark.parametrize("cursor", ["-1", "abc", "１２", "9223372036854775808"])
def test_invalid_stream_cursor_rejected(client, cursor):
    assert (
        client.get(
            "/api/investigations/missing/events/stream", headers={"Last-Event-ID": cursor.encode()}
        ).status_code
        == 422
    )


def test_stream_unknown_investigation_and_json_escaping(client):
    assert client.get("/api/investigations/missing/events/stream").status_code == 404
    result = frame("progress", {"message": "text\n\nevent: injected"}, 4)
    assert result.count("\n\n") == 1
    assert json.loads(result.split("data: ")[1])["message"].endswith("injected")


def test_stream_disconnect_and_sanitized_database_error():
    async def disconnected():
        return True

    async def connected():
        return False

    async def collect(repo, check):
        return [
            message
            async for message in event_stream(
                repo, "case", 0, SimpleNamespace(is_disconnected=check), interval=0
            )
        ]

    assert asyncio.run(collect(object(), disconnected)) == ["retry: 2000\n\n"]

    def failure(iid):
        raise OperationalError("secret SQL", {}, Exception("password"))

    messages = asyncio.run(collect(SimpleNamespace(progress_status=failure), connected))
    assert len(messages) == 2 and "progress_unavailable" in messages[-1]
    assert "password" not in "".join(messages) and "secret SQL" not in "".join(messages)
