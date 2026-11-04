# Persisted progress streaming

GET `/api/investigations/{id}/events/stream?after=0` emits SSE `progress` frames whose IDs are the committed database event IDs. Reconnect accepts Last-Event-ID and uses the larger of header/query cursors. Invalid or out-of-range IDs are rejected. JSON `/events` remains available.

The server drains 100-row pages, reads terminal status before fetching events, and emits `complete` only after the terminal event pages are drained. Each connection lasts at most about thirty seconds, checks disconnects, emits periodic comment heartbeats and releases its slot on exit. A process accepts at most thirty-two streams. Synchronous database calls run in the thread pool and do not hold a database connection while sleeping. Redis is not involved. Streams internally poll PostgreSQL; there is no LISTEN/NOTIFY or global push broker.

The dashboard opens one stream for a running investigation. Unsupported/failed streams fall back to JSON polling. Report/status polling continues independently. IDs are deduplicated and sorted, and a terminal report triggers a final JSON drain to avoid losing an event still in transport. A stream error exposes a generic message, not SQL or credentials. Existing safe React text rendering applies to event messages.

SSE suits one-way progress updates; bidirectional WebSockets are unnecessary here. See the browser's [EventSource framing and reconnect contract](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events). This local implementation is not a high-concurrency qualification; polling cost and browser connection limits matter when expanding deployment.
