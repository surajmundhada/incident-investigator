import { useEffect, useState } from "react";
import { api, date, download } from "./api";

type Latency = {
  samples: number;
  p50_ms: number | null;
  p95_ms: number | null;
};
type Status = {
  enabled: boolean;
  state: "unconfigured" | "disabled" | "enabled" | "bypassing";
  scope: string;
  started_at: number | null;
  process_instance: string | null;
  counters: Record<string, number>;
  hit_rates: { retrieval: number | null; embedding: number | null };
  latency: Record<string, Latency>;
  bypass_seconds_remaining: number;
};

export function CacheStatus() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const value = await api<Status>("/api/diagnostics/cache", {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!active) return;
        setStatus(value);
        setUpdated(new Date().toLocaleTimeString());
        setError("");
      } catch {
        if (!active) return;
        setStatus(null);
        setError(
          "Cache status is unavailable. Check the local API; no configuration was changed.",
        );
      }
      if (active) timer = setTimeout(refresh, 5000);
    }
    void refresh();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [revision]);
  const count = (key: string) => status?.counters[key] ?? 0;
  const rate = (value: number | null | undefined) =>
    value == null ? "No lookups yet" : `${(value * 100).toFixed(1)}%`;
  const ms = (value: number | null | undefined) =>
    value == null ? "—" : `${value.toFixed(2)} ms`;
  const label =
    status?.state === "disabled"
      ? "Off"
      : status?.state === "bypassing"
        ? "Temporarily bypassed"
        : status?.state === "unconfigured"
          ? "Retrieval not configured"
          : "Enabled";
  return (
    <div className="evaluation-page">
      <section className="card">
        <p className="small muted">OPERATOR VIEW · READ ONLY</p>
        <div className="row">
          <h1>Cache status</h1>
          <button onClick={() => setRevision((old) => old + 1)}>
            Refresh status
          </button>
        </div>
        <p>
          Decide whether Redis helps your workload using observed activity and
          matched latency comparisons.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!status && !error && <p role="status">Loading cache status…</p>}
        {status && (
          <>
            <h2>{label}</h2>
            <p>
              {status.state === "unconfigured"
                ? "Runbook retrieval is not configured in this API process. Enable knowledge retrieval before evaluating caching."
                : status.enabled
                  ? "Caching is configured. Connectivity is not actively probed by this page; errors and bypasses come from actual operations."
                  : "Retrieval works without Redis. Try caching when representative traffic contains repeated work, then compare the results."}
            </p>
            {status.state === "bypassing" && (
              <p className="error">
                Redis operations are temporarily bypassed after an error.
                PostgreSQL and local embeddings remain the fallback.
              </p>
            )}
            <p className="small muted">
              This API process only. Worker and indexer activity are excluded.
              Counters reset when this process restarts. Updated {updated}
              {status.started_at
                ? ` · Counters started ${date(status.started_at)}`
                : ""}
              .
            </p>
            <div className="row">
              <button onClick={() => download(status, "cache-status.json")}>
                Export status snapshot
              </button>
              <span className="small muted">
                Refreshes every five seconds; viewing this page does not contact
                Redis.
              </span>
            </div>
          </>
        )}
      </section>
      {status && (
        <>
          <section className="card">
            <h2>Observed cache activity</h2>
            <div
              className="evaluation-table"
              role="region"
              aria-label="Cache activity"
              tabIndex={0}
            >
              <table>
                <thead>
                  <tr>
                    <th>Layer</th>
                    <th>Hits</th>
                    <th>Misses</th>
                    <th>Hit rate</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Retrieval results</td>
                    <td>{count("retrieval_hits")}</td>
                    <td>{count("retrieval_misses")}</td>
                    <td>{rate(status.hit_rates.retrieval)}</td>
                  </tr>
                  <tr>
                    <td>Embeddings</td>
                    <td>{count("embedding_hits")}</td>
                    <td>{count("embedding_misses")}</td>
                    <td>{rate(status.hit_rates.embedding)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p>
              Retrieval searches: {count("search_calls")} · Failed searches:{" "}
              {count("search_errors")} · Cache I/O errors: {count("errors")} ·
              Bypassed I/O operations:{" "}
              {count("bypass") + count("capacity_bypass")} · Invalid cache
              payloads: {count("corrupt")}
            </p>
            <p className="small muted">
              Misses include expiry, invalid data and unavailable cache reads.
              One search can involve several cache operations. Embedding
              counters can include document indexing in this API process.
            </p>
          </section>
          <section className="card">
            <h2>Retrieval latency</h2>
            <div
              className="evaluation-table"
              role="region"
              aria-label="Live retrieval latency"
              tabIndex={0}
            >
              <table>
                <thead>
                  <tr>
                    <th>Path</th>
                    <th>Samples</th>
                    <th>p50</th>
                    <th>p95</th>
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ["all", "All successful searches"],
                      ["hit", "Retrieval cache hit"],
                      ["miss", "Retrieval miss / fallback"],
                      ["uncached", "Retrieval cache off"],
                    ] as const
                  ).map(([key, title]) => (
                    <tr key={key}>
                      <td>{title}</td>
                      <td>{status.latency[key]?.samples ?? 0}</td>
                      <td>{ms(status.latency[key]?.p50_ms)}</td>
                      <td>{ms(status.latency[key]?.p95_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="small muted">
              At most the last 512 successful samples in each row, including
              PostgreSQL revision checks. Failed searches are counted
              separately. These are retrieval timings, not model or complete
              investigation timings. Different request mixes do not establish a
              causal speedup.
            </p>
          </section>
        </>
      )}
      <section className="card">
        <h2>When should the operator enable it?</h2>
        <ol>
          <li>
            Collect a representative uncached baseline and export a snapshot.
          </li>
          <li>
            Enable Redis for a controlled trial and send the same workload.
          </li>
          <li>
            Compare p50/p95, errors, repeated-query hit rate and Redis resource
            use.
          </li>
          <li>
            Keep it enabled only if the benefit justifies the added cost. A high
            hit rate alone is insufficient.
          </li>
        </ol>
        <p>
          Our historical local benchmark improved repeated-query median by
          81.7%, but unique-query median became 27.5% slower. It does not
          predict your workload. Redis memory usage is not collected by this
          panel.
        </p>
        <details>
          <summary>Operator setup and S3 precautions</summary>
          <p>
            Configuration changes belong to the person running Docker, not the
            investigator agent. There is no browser switch or automatic mode
            change.
          </p>
          <p>Enable the local stack with caching:</p>
          <pre>
            powershell -ExecutionPolicy Bypass -File .\scripts\start-stack.ps1
            -LiveDemo -Knowledge -Agent -Artifacts -Cache
          </pre>
          <p>
            To disable caching, rerun that command without -Cache, then stop the
            unused Redis container. Restarting resets this process’s counters;
            export snapshots before comparing.
          </p>
          <p>
            That stack command selects local archives. If using S3, first stop
            the existing S3 refresh watcher, change the stack mode, then restore
            S3 with the matching cache option:
          </p>
          <pre>
            .\.venv\Scripts\python.exe .\scripts\start_s3.py --cache --watch
          </pre>
          <p>
            Omit --cache when disabling it. Keep only one watcher running, so a
            later credential refresh cannot restore an older cache
            configuration.
          </p>
        </details>
      </section>
    </div>
  );
}
