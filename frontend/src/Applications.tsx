import { useEffect, useState } from "react";
import { api, date } from "./api";
import { Icon } from "./Icon";
import { RunbookUpload } from "./RunbookUpload";
import type { ApplicationConfiguration, SnapshotSummary } from "./types";

type Row = { name: string; dependencies: string };

function LogUpload({
  configuration,
  uploaded,
}: {
  configuration: ApplicationConfiguration;
  uploaded: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [records, setRecords] = useState<Record<string, unknown>[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [covered, setCovered] = useState<string[]>([]);
  const [synthetic, setSynthetic] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  function localInput(timestamp: number) {
    const value = new Date(timestamp);
    return new Date(timestamp - value.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 19);
  }
  async function choose(value: File | null) {
    setFile(null);
    setRecords([]);
    setError("");
    setSaved(false);
    if (!value) return;
    if (value.size > 750_000) {
      setError(
        "Choose a JSONL file smaller than 750 KB. The complete upload is limited to 1 MB.",
      );
      return;
    }
    try {
      const lines = (await value.text())
        .split(/\r?\n/)
        .filter((line) => line.trim());
      if (lines.length > 2000)
        throw new Error("The snapshot limit is 2,000 log records.");
      const parsed = lines.map((line, index) => {
        try {
          const record = JSON.parse(line);
          if (!record || typeof record !== "object" || Array.isArray(record))
            throw new Error();
          return record as Record<string, unknown>;
        } catch {
          throw new Error(`Line ${index + 1} must be a JSON object.`);
        }
      });
      const times = parsed.map((record) =>
        Date.parse(String(record.timestamp)),
      );
      if (!times.length || times.some((time) => !Number.isFinite(time)))
        throw new Error(
          "Each record needs a valid timestamp with a timezone. Empty captures can be submitted through the API.",
        );
      setRecords(parsed);
      setFile(value);
      setStart(localInput(Math.min(...times) - 1000));
      setEnd(localInput(Math.max(...times) + 1000));
      setCovered(
        [...new Set(parsed.map((record) => String(record.service)))].filter(
          (service) => service in configuration.services,
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/snapshots", {
        method: "POST",
        body: JSON.stringify({
          application: configuration.application,
          configuration_revision: configuration.revision,
          environment: configuration.environment,
          release: configuration.release,
          source_name: file.name,
          starts_at: new Date(start).toISOString(),
          ends_at: new Date(end).toISOString(),
          covered_services: covered,
          records,
          synthetic_example: synthetic,
        }),
      });
      setSaved(true);
      uploaded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="onboarding-form" onSubmit={submit}>
      <h3>Upload incident logs</h3>
      <p className="muted small">
        One JSON object per line. Required: timestamp, service, level, message.
        Optional: request_id (32 lowercase hex characters), dependency,
        status_code, duration_ms.
      </p>
      <label>
        JSONL file
        <input
          aria-label="JSONL file"
          type="file"
          accept=".jsonl,.ndjson,.txt"
          disabled={busy}
          onChange={(event) => void choose(event.target.files?.[0] || null)}
        />
      </label>
      {file && (
        <>
          <p className="small muted">
            {records.length} parsed records. Review the suggested coverage
            bounds below.
          </p>
          <div className="two">
            <label>
              Coverage starts
              <input
                required
                aria-label="Coverage starts"
                type="datetime-local"
                step="1"
                value={start}
                disabled={busy}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label>
              Coverage ends
              <input
                required
                aria-label="Coverage ends"
                type="datetime-local"
                step="1"
                value={end}
                disabled={busy}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
          </div>
          <p className="small muted">
            Declared coverage: which services does this export cover? Missing
            services will be reported as unavailable. Maximum window: one hour.
          </p>
          <div className="coverage-options">
            {Object.keys(configuration.services).map((service) => (
              <label key={service}>
                <input
                  type="checkbox"
                  checked={covered.includes(service)}
                  disabled={busy}
                  onChange={(e) =>
                    setCovered((old) =>
                      e.target.checked
                        ? [...old, service]
                        : old.filter((value) => value !== service),
                    )
                  }
                />
                {service}
              </label>
            ))}
          </div>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={synthetic}
              disabled={busy}
              onChange={(e) => setSynthetic(e.target.checked)}
            />
            These are synthetic example logs
          </label>
          <p className="small muted">
            Known credential patterns are redacted before storage. Review
            exports yourself: redaction does not recognise every secret.
            Coverage is your declaration, not independently verified
            completeness.
          </p>
          <button
            className="primary"
            type="submit"
            disabled={busy || !covered.length}
          >
            {busy ? "Uploading…" : "Save evidence snapshot"}
          </button>
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {saved && (
        <p className="success" role="status">
          Snapshot saved. Select it when creating an investigation.
        </p>
      )}
    </form>
  );
}

export function Applications() {
  const [items, setItems] = useState<ApplicationConfiguration[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [application, setApplication] = useState("");
  const [environment, setEnvironment] = useState("local");
  const [release, setRelease] = useState("v1");
  const [services, setServices] = useState<Row[]>([
    { name: "", dependencies: "" },
  ]);
  const [selected, setSelected] = useState<ApplicationConfiguration | null>(
    null,
  );
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  async function refresh() {
    try {
      setItems(
        (await api<{ items: ApplicationConfiguration[] }>("/api/applications"))
          .items,
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void refresh();
  }, []);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    api<{ items: SnapshotSummary[] }>(
      `/api/snapshots?application=${encodeURIComponent(selected.application)}`,
    )
      .then((result) => {
        if (active) setSnapshots(result.items);
      })
      .catch((e) => {
        if (active) setError((e as Error).message);
      });
    return () => {
      active = false;
    };
  }, [selected]);
  async function register(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const names = services.map((row) => row.name.trim());
      if (new Set(names).size !== names.length)
        throw new Error("Service IDs must be unique.");
      const result = await api<ApplicationConfiguration>("/api/applications", {
        method: "POST",
        body: JSON.stringify({
          application,
          environment,
          release,
          services: Object.fromEntries(
            services.map((row) => [
              row.name.trim(),
              {
                dependencies: row.dependencies
                  .split(",")
                  .map((value) => value.trim())
                  .filter(Boolean),
              },
            ]),
          ),
        }),
      });
      await refresh();
      setSelected(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function update(index: number, key: keyof Row, value: string) {
    setServices((old) =>
      old.map((row, i) => (i === index ? { ...row, [key]: value } : row)),
    );
  }
  return (
    <section className="overview applications-page">
      <div className="page-intro">
        <div>
          <div className="eyebrow">CONNECT YOUR APPLICATION</div>
          <h1>Bring your own context.</h1>
          <p className="muted">
            Register a service map, supply incident logs, and investigate the
            evidence.
          </p>
        </div>
      </div>
      <ErrorMessage message={error} />
      <div className="onboarding-grid">
        <section className="card">
          <h2>
            <Icon name="layers" size={16} /> Register an application
          </h2>
          <p className="small muted">
            Configuration defines scope; it does not automatically connect live
            logs. Publishing changes creates a revision. Existing cases keep
            their original revision.
          </p>
          <form className="onboarding-form" onSubmit={register}>
            <fieldset disabled={busy}>
              <label>
                Application ID
                <input
                  required
                  pattern="[a-z][a-z0-9-]{0,39}"
                  maxLength={40}
                  placeholder="booking"
                  value={application}
                  onChange={(e) => setApplication(e.target.value)}
                />
              </label>
              <div className="two">
                <label>
                  Environment
                  <select
                    value={environment}
                    onChange={(e) => setEnvironment(e.target.value)}
                  >
                    <option>local</option>
                    <option>staging</option>
                    <option>production</option>
                  </select>
                </label>
                <label>
                  Release
                  <input
                    required
                    pattern="[a-zA-Z0-9_.-]{1,40}"
                    maxLength={40}
                    value={release}
                    onChange={(e) => setRelease(e.target.value)}
                  />
                </label>
              </div>
              <div className="row">
                <h3 className="service-form-heading">
                  Services & dependencies
                </h3>
                <button
                  type="button"
                  disabled={services.length >= 20}
                  onClick={() =>
                    setServices((old) => [
                      ...old,
                      { name: "", dependencies: "" },
                    ])
                  }
                >
                  + Add service
                </button>
              </div>
              {services.map((row, index) => (
                <div className="service-config-row" key={index}>
                  <label>
                    Service ID
                    <input
                      aria-label={`Service ID ${index + 1}`}
                      required
                      pattern="[a-z][a-z0-9-]{0,39}"
                      maxLength={40}
                      placeholder="booking-api"
                      value={row.name}
                      onChange={(e) => update(index, "name", e.target.value)}
                    />
                  </label>
                  <label>
                    Dependencies
                    <input
                      aria-label={`Dependencies ${index + 1}`}
                      placeholder="availability-api, notification-api"
                      value={row.dependencies}
                      onChange={(e) =>
                        update(index, "dependencies", e.target.value)
                      }
                    />
                  </label>
                  <button
                    type="button"
                    aria-label={`Remove service ${index + 1}`}
                    disabled={services.length === 1}
                    onClick={() =>
                      setServices((old) => old.filter((_, i) => i !== index))
                    }
                  >
                    ×
                  </button>
                </div>
              ))}
              <p className="small muted">
                Use lowercase IDs and hyphens. List dependencies as
                comma-separated service IDs registered in this same map.
              </p>
              <button className="primary" type="submit">
                {busy ? "Publishing…" : "Register application"}
              </button>
            </fieldset>
          </form>
        </section>
        <section className="registered-apps">
          <h2>
            Registered configurations{" "}
            <span className="count">{items.length}</span>
          </h2>
          {items.map((config) => (
            <button
              key={config.revision}
              className={`registered-app ${selected?.revision === config.revision ? "selected" : ""}`}
              onClick={() => {
                setSelected(config);
                setSnapshots([]);
                setError("");
              }}
            >
              <div className="row">
                <strong>{config.application}</strong>
                <span className="badge">
                  {Object.keys(config.services).length} services
                </span>
              </div>
              <span className="small muted">
                {config.environment} · {config.release}
              </span>
              <div className="app-service-tags">
                {Object.keys(config.services).map((service) => (
                  <span key={service}>{service}</span>
                ))}
              </div>
              <span className="small mono muted">
                Revision {config.revision.slice(0, 12)}
              </span>
            </button>
          ))}
          {!items.length && (
            <p className="muted small">No configurations loaded.</p>
          )}
        </section>
      </div>
      {selected && (
        <RunbookUpload key={selected.revision} configuration={selected} />
      )}
      {selected && (
        <section className="card upload-panel">
          <div className="row">
            <h2>Evidence for {selected.application}</h2>
            <span className="badge">
              {selected.environment} · {selected.release}
            </span>
          </div>
          <LogUpload
            key={selected.revision}
            configuration={selected}
            uploaded={() => {
              void api<{ items: SnapshotSummary[] }>(
                `/api/snapshots?application=${encodeURIComponent(selected.application)}`,
              )
                .then((result) => setSnapshots(result.items))
                .catch((e) => setError((e as Error).message));
            }}
          />
          {!!snapshots.length && (
            <div className="snapshot-list">
              <h3>Saved snapshots</h3>
              {snapshots.map((snapshot) => (
                <div key={snapshot.id}>
                  <strong>{snapshot.source_name}</strong>
                  <span>
                    {snapshot.record_count} records ·{" "}
                    {snapshot.covered_services.join(", ")}
                    {snapshot.synthetic_example ? " · synthetic example" : ""}
                  </span>
                  <small>
                    {date(snapshot.starts_at)} — {date(snapshot.ends_at)} ·
                    configuration {snapshot.configuration_revision.slice(0, 8)}
                  </small>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </section>
  );
}
function ErrorMessage({ message }: { message: string }) {
  return message ? (
    <p className="error" role="alert">
      {message}
    </p>
  ) : null;
}
