import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, date, download } from "./api";
import type {
  Evidence,
  Investigation,
  Passage,
  ProgressEvent,
  Reference,
} from "./types";
import "./style.css";
import { App } from "./App";
import { ArtifactPanel } from "./ArtifactPanel";
import { Icon } from "./Icon";
import { NewIncident } from "./NewIncident";

const terminal = new Set(["complete", "failed", "cancelled"]);
const statusLabel = (value: string) => value.replaceAll("_", " ");
function Badge({ value }: { value: string }) {
  return <span className={`badge ${value}`}>{statusLabel(value)}</span>;
}
function ErrorBox({ message }: { message: string }) {
  return message ? (
    <p className="error" role="alert">
      {message}
    </p>
  ) : null;
}

function EvidenceCard({
  evidence,
  selected,
  openPassage,
}: {
  evidence: Evidence;
  selected: number | null;
  openPassage: (id: string) => void;
}) {
  return (
    <article className="card evidence" id={`evidence-${evidence.id}`}>
      <div className="row">
        <h3>{evidence.service || evidence.source.replaceAll("_", " ")}</h3>
        <Badge value={evidence.availability} />
      </div>
      <p className="small muted">
        {evidence.source} · {date(evidence.collected_at)} ·{" "}
        {evidence.data_origin || "guidance"}
      </p>
      {evidence.error && <ErrorBox message={evidence.error} />}
      {evidence.truncated && (
        <p className="notice">
          This evidence is truncated. Missing records may affect the conclusion.
        </p>
      )}
      {evidence.records?.map((record, index) => (
        <div
          key={index}
          className={`log ${selected === index ? "highlight" : ""}`}
        >
          <div className="row small">
            <strong>
              #{index} · {record.level} {record.status_code || ""}
            </strong>
            <span className="muted">{date(record.timestamp)}</span>
          </div>
          <p>{record.message}</p>
          <div className="small mono muted">
            {record.request_id && `request ${record.request_id}`}
            {record.dependency && ` · dependency ${record.dependency}`}
          </div>
        </div>
      ))}
      {evidence.records?.length === 0 && (
        <p className="muted">
          No records returned. Check source availability and window.
        </p>
      )}
      {evidence.hits?.map((passage) => (
        <div key={passage.id} className="passage">
          <button
            className="text-button"
            onClick={() => openPassage(passage.id)}
          >
            {passage.heading} ↗
          </button>
          <p className="preserve">{passage.body}</p>
          <p className="small muted">
            {passage.source} · lines {passage.line_start}–{passage.line_end}
          </p>
        </div>
      ))}
      {evidence.hits?.length === 0 && (
        <p className="muted">No guidance retrieved.</p>
      )}
      {evidence.revision && (
        <p className="small mono muted">
          Revision {evidence.revision.slice(0, 16)}
        </p>
      )}
      <details>
        <summary>Stored evidence JSON</summary>
        <pre>{JSON.stringify(evidence, null, 2)}</pre>
      </details>
    </article>
  );
}

function Detail({ id }: { id: string }) {
  const [data, setData] = useState<Investigation | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("report");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Reference | null>(null);
  const [passage, setPassage] = useState<Passage | null>(null);
  const [passageError, setPassageError] = useState("");
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let cursor = 0;
    let stream: EventSource | null = null;
    let streamAttempted = false;
    let streamOpen = false;
    setData(null);
    setEvents([]);
    setError("");
    setTab("report");
    setSelected(null);
    setPassage(null);
    const controller = new AbortController();
    function mergeEvents(items: ProgressEvent[]) {
      cursor = Math.max(cursor, ...items.map((item) => item.id));
      setEvents((old) =>
        [
          ...old,
          ...items.filter((event) => !old.some((item) => item.id === event.id)),
        ].sort((a, b) => a.id - b.id),
      );
    }
    function stopStream() {
      streamOpen = false;
      stream?.close();
    }
    function startStream() {
      if (streamAttempted || typeof EventSource === "undefined") return;
      streamAttempted = true;
      stream = new EventSource(
        `/api/investigations/${encodeURIComponent(id)}/events/stream?after=${cursor}`,
      );
      stream.onopen = () => {
        streamOpen = true;
      };
      stream.addEventListener("progress", (message) => {
        if (!active) return;
        try {
          const item = JSON.parse(
            (message as MessageEvent).data,
          ) as ProgressEvent;
          if (
            !Number.isSafeInteger(item.id) ||
            item.id < 1 ||
            typeof item.kind !== "string" ||
            typeof item.message !== "string" ||
            typeof item.created_at !== "number"
          )
            throw new Error("Invalid progress event");
          mergeEvents([item]);
        } catch {
          stopStream();
        }
      });
      stream.addEventListener("complete", stopStream);
      stream.addEventListener("stream_error", stopStream);
      stream.onerror = stopStream; // Existing bounded polling takes over after failure.
    }
    async function refresh() {
      try {
        const usedStream = streamOpen;
        const [next, polled] = await Promise.all([
          api<Investigation>(`/api/investigations/${encodeURIComponent(id)}`, {
            signal: controller.signal,
          }),
          usedStream
            ? Promise.resolve({ items: [] as ProgressEvent[] })
            : api<{ items: ProgressEvent[] }>(
                `/api/investigations/${encodeURIComponent(id)}/events?after=${cursor}`,
                { signal: controller.signal },
              ),
        ]);
        // A terminal status may arrive before the last stream frame; drain saved events.
        const progress =
          usedStream && terminal.has(next.status)
            ? await api<{ items: ProgressEvent[] }>(
                `/api/investigations/${encodeURIComponent(id)}/events?after=${cursor}`,
                { signal: controller.signal },
              )
            : polled;
        if (!active) return;
        setData(next);
        setError("");
        mergeEvents(progress.items);
        if (terminal.has(next.status)) stopStream();
        else startStream();
        // Drain all event pages before stopping after a terminal result.
        if (!terminal.has(next.status) || progress.items.length === 100)
          timer = setTimeout(refresh, 1500);
      } catch (e) {
        if (!active) return;
        setError((e as Error).message);
        timer = setTimeout(refresh, 4000);
      }
    }
    void refresh();
    return () => {
      active = false;
      controller.abort();
      stopStream();
      clearTimeout(timer);
    };
  }, [id]);
  async function cancel() {
    setBusy(true);
    try {
      await api(`/api/investigations/${encodeURIComponent(id)}/cancel`, {
        method: "POST",
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function openPassage(passageId: string) {
    if (!/^[a-f0-9]{64}$/.test(passageId)) return;
    setPassageError("");
    try {
      setPassage(
        await api<Passage>(
          `/api/knowledge/passages/${passageId}?application=${encodeURIComponent(data?.incident.application || "shopping-demo")}`,
        ),
      );
    } catch (e) {
      setPassageError((e as Error).message);
    }
  }
  function reference(ref: Reference) {
    setSelected(ref);
    setTab("evidence");
    setTimeout(
      () =>
        document
          .getElementById(`evidence-${ref.evidence_id}`)
          ?.scrollIntoView({ behavior: "smooth", block: "start" }),
      0,
    );
  }
  function refs(values: Reference[] = []) {
    return (
      <span className="references">
        {values.map((ref, index) => (
          <button key={index} onClick={() => reference(ref)}>
            Log #{ref.record_index} · {ref.evidence_id.slice(0, 6)}
          </button>
        ))}
      </span>
    );
  }
  if (!data)
    return (
      <section className="detail">
        <ErrorBox message={error} />
        <p className="muted">Loading investigation…</p>
      </section>
    );
  const report = data.report;
  return (
    <section className="detail">
      <div className="eyebrow">
        <Icon name="layers" size={13} /> CASE / {id.slice(0, 12).toUpperCase()}
      </div>
      <div className="row title-row">
        <h1>{data.incident.title}</h1>
        <Badge value={data.status} />
      </div>
      <p className="muted">
        {data.incident.application || "shopping-demo"} · {data.incident.service}{" "}
        · {data.incident.environment} · {data.incident.release}
      </p>
      <p className="preserve">{data.incident.description}</p>
      <div className="row scope">
        <span className="small muted">
          {date(data.incident.starts_at)} — {date(data.incident.ends_at)}
        </span>
        <div className="actions">
          <button onClick={() => download(data, `investigation-${id}.json`)}>
            Export JSON
          </button>
          {!terminal.has(data.status) && (
            <button className="danger" disabled={busy} onClick={cancel}>
              {busy ? "Cancelling…" : "Cancel"}
            </button>
          )}
        </div>
      </div>
      <ErrorBox message={error} />
      <ErrorBox message={passageError} />
      <nav className="tabs" aria-label="Investigation views">
        {["report", "evidence", "timeline"].map((value) => (
          <button
            key={value}
            aria-current={tab === value ? "page" : undefined}
            className={tab === value ? "active" : ""}
            onClick={() => setTab(value)}
          >
            {value}
            {value === "evidence" && ` (${data.evidence.length})`}
          </button>
        ))}
      </nav>
      {tab === "report" &&
        (!report ? (
          <div className="card empty">
            <span className="symbol">◎</span>
            <h2>
              {terminal.has(data.status)
                ? "No report was completed"
                : "Collecting evidence"}
            </h2>
            <p className="muted">
              {terminal.has(data.status)
                ? "Review the timeline and collected evidence for details."
                : "Progress and evidence appear as the worker saves them."}
            </p>
          </div>
        ) : (
          <>
            <article className="card summary-card">
              <div className="row">
                <h2>
                  <Icon name="spark" size={18} /> Investigation summary
                </h2>
                {report.conclusion && <Badge value={report.conclusion} />}
              </div>
              <p className="preserve">{report.summary}</p>
              <p className="small muted">
                {report.mode} ·{" "}
                {report.provider_origin || "evidence collection"}
                {report.model && ` · ${report.model}`}
              </p>
              {report.usage && (
                <div className="stats">
                  <span>
                    <strong>{report.usage.model_calls}</strong> model calls
                  </span>
                  <span>
                    <strong>{report.usage.tool_calls_started}</strong> tool
                    attempts
                  </span>
                  <span>
                    <strong>
                      {report.usage.model_tokens.toLocaleString()}
                    </strong>{" "}
                    reported tokens
                  </span>
                </div>
              )}
            </article>
            {!!report.observations?.length && (
              <article className="card">
                <h2>Observed facts</h2>
                {report.observations.map((claim, index) => (
                  <div className="claim" key={index}>
                    <p>{claim.text}</p>
                    {refs(claim.references)}
                  </div>
                ))}
              </article>
            )}
            {!!report.hypotheses?.length && (
              <article className="card">
                <h2>Hypotheses to review</h2>
                {report.hypotheses.map((hypothesis, index) => (
                  <div className="claim" key={index}>
                    <Badge value={hypothesis.service} />
                    <p>{hypothesis.explanation}</p>
                    <div className="small muted">Supporting evidence</div>
                    {refs(hypothesis.supporting)}
                    {!!hypothesis.contradicting.length && (
                      <>
                        <div className="small muted">
                          Contradicting evidence
                        </div>
                        {refs(hypothesis.contradicting)}
                      </>
                    )}
                  </div>
                ))}
              </article>
            )}
            <div className="two">
              {[
                ["Missing evidence", report.missing_evidence],
                ["Suggested checks", report.suggested_checks],
              ].map(([title, values]) => (
                <article className="card" key={title as string}>
                  <h2>{title as string}</h2>
                  <ul>
                    {((values as string[]) || []).map((value, index) => (
                      <li key={index}>{value}</li>
                    ))}
                  </ul>
                  {!((values as string[]) || []).length && (
                    <p className="muted">None listed.</p>
                  )}
                </article>
              ))}
            </div>
            {!!report.runbook_references?.length && (
              <article className="card">
                <h2>Referenced guidance</h2>
                {report.runbook_references.map((ref, index) => (
                  <button
                    className="citation"
                    key={index}
                    onClick={() => openPassage(ref.passage_id)}
                  >
                    Passage {ref.passage_id.slice(0, 12)} ↗
                  </button>
                ))}
              </article>
            )}
            <article className="card">
              <h2>Provenance & limitations</h2>
              <ul>
                {report.limitations?.map((value, index) => (
                  <li key={index}>{value}</li>
                ))}
              </ul>
              <p className="small muted">
                Stop reason: {report.termination_reason || "not recorded"} ·
                Attempt {data.attempts}
              </p>
              {report.knowledge_revision && (
                <p className="small mono muted">
                  Knowledge {report.knowledge_revision} ·{" "}
                  {report.retrieval_profile}
                </p>
              )}
              <details>
                <summary>Stored report JSON</summary>
                <pre>{JSON.stringify(report, null, 2)}</pre>
              </details>
            </article>
          </>
        ))}
      {tab === "evidence" && (
        <>
          {!data.evidence.length && (
            <div className="card empty">No evidence collected yet.</div>
          )}
          {data.evidence.map((evidence) => (
            <EvidenceCard
              key={evidence.id}
              evidence={evidence}
              selected={
                selected?.evidence_id === evidence.id
                  ? selected.record_index
                  : null
              }
              openPassage={openPassage}
            />
          ))}
        </>
      )}
      {tab === "timeline" && (
        <article className="card">
          <h2>Persisted activity</h2>
          <p className="muted small">
            Saved worker events, streamed live with polling fallback.
          </p>
          <ol className="timeline">
            {events.map((event) => (
              <li key={event.id}>
                <div className="row">
                  <strong>{statusLabel(event.kind)}</strong>
                  <time>{date(event.created_at)}</time>
                </div>
                <p>{event.message}</p>
              </li>
            ))}
          </ol>
          {!events.length && <p className="muted">No events available.</p>}
        </article>
      )}
      {terminal.has(data.status) && <ArtifactPanel id={id} />}
      {passage && (
        <div className="overlay">
          <section
            className="modal passage-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="passage-title"
          >
            <div className="row">
              <h2 id="passage-title">{passage.heading}</h2>
              <button
                aria-label="Close passage"
                onClick={() => setPassage(null)}
              >
                ×
              </button>
            </div>
            <p className="small muted">
              {passage.source} · lines {passage.line_start}–{passage.line_end}
            </p>
            <pre className="passage-body">{passage.body}</pre>
            <p className="small mono muted">Immutable passage {passage.id}</p>
          </section>
        </div>
      )}
    </section>
  );
}

createRoot(document.getElementById("root")!).render(
  <App
    renderDetail={(id) => <Detail key={id} id={id} />}
    renderNewIncident={(close, created) => (
      <NewIncident close={close} created={created} />
    )}
  />,
);
