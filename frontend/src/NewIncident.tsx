import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, date } from "./api";
import type { ApplicationConfiguration, SnapshotSummary } from "./types";

export function NewIncident({
  close,
  created,
}: {
  close: () => void;
  created: (id: string) => void;
}) {
  const [form, setForm] = useState({
    title: "",
    description: "",
    service: "",
    minutes: "5",
    configuration: "",
    snapshot: "",
  });
  const [configurations, setConfigurations] = useState<
    ApplicationConfiguration[]
  >([]);
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const retry = useRef<{
    fingerprint: string;
    key: string;
    body: string;
  } | null>(null);
  const configuration = configurations.find(
    (item) => item.revision === form.configuration,
  );
  const snapshot = snapshots.find((item) => item.id === form.snapshot);
  useEffect(() => {
    let active = true;
    api<{ items: ApplicationConfiguration[] }>("/api/applications")
      .then((result) => {
        if (!active) return;
        setConfigurations(result.items);
        const chosen =
          result.items.find(
            (item) =>
              item.application === "shopping-demo" &&
              item.environment === "local",
          ) || result.items[0];
        if (chosen)
          setForm((old) => ({
            ...old,
            configuration: chosen.revision,
            service: Object.keys(chosen.services)[0],
          }));
      })
      .catch((e) => {
        if (active) setError((e as Error).message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);
  const selectedApplication = configuration?.application;
  useEffect(() => {
    if (!selectedApplication) return;
    let active = true;
    setSnapshots([]);
    api<{ items: SnapshotSummary[] }>(
      `/api/snapshots?application=${encodeURIComponent(selectedApplication)}`,
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
  }, [selectedApplication]);
  async function selectSnapshot(value: string) {
    setError("");
    if (!value) {
      setForm((old) => ({ ...old, snapshot: "" }));
      return;
    }
    const selected = snapshots.find((item) => item.id === value);
    if (!selected) return;
    setBusy(true);
    try {
      let config = configurations.find(
        (item) => item.revision === selected.configuration_revision,
      );
      if (!config) {
        config = await api<ApplicationConfiguration>(
          `/api/applications/revisions/${selected.configuration_revision}`,
        );
        setConfigurations((old) => [...old, config!]);
      }
      setForm((old) => ({
        ...old,
        snapshot: value,
        configuration: config!.revision,
        service: selected.covered_services.includes(old.service)
          ? old.service
          : selected.covered_services[0],
      }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !configuration) return;
    setBusy(true);
    setError("");
    const fingerprint = JSON.stringify(form);
    if (retry.current?.fingerprint !== fingerprint) {
      const end = snapshot
        ? new Date(snapshot.ends_at * 1000)
        : new Date(Date.now() - 1000);
      retry.current = {
        fingerprint,
        key: crypto.randomUUID(),
        body: JSON.stringify({
          title: form.title,
          description: form.description,
          service: form.service,
          application: configuration.application,
          configuration_revision: configuration.revision,
          snapshot_id: snapshot?.id || null,
          environment: configuration.environment,
          release: configuration.release,
          ends_at: end.toISOString(),
          starts_at: new Date(
            snapshot
              ? snapshot.starts_at * 1000
              : end.getTime() - Number(form.minutes) * 60000,
          ).toISOString(),
        }),
      };
    }
    try {
      const result = await api<{ investigation_id: string }>("/api/incidents", {
        method: "POST",
        headers: { "Idempotency-Key": retry.current.key },
        body: retry.current.body,
      });
      created(result.investigation_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="overlay">
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-title"
      >
        <div className="row">
          <h2 id="create-title">Start an investigation</h2>
          <button onClick={close} disabled={busy} aria-label="Close">
            ×
          </button>
        </div>
        <p className="muted">
          Investigate a registered application using captured logs or the
          connected demo. Uses the configured model when enabled.
        </p>
        <form onSubmit={submit}>
          <fieldset disabled={busy}>
            <label>
              Application configuration
              <select
                aria-label="Application configuration"
                required
                value={form.configuration}
                disabled={loading}
                onChange={(e) => {
                  const chosen = configurations.find(
                    (item) => item.revision === e.target.value,
                  );
                  if (chosen)
                    setForm((old) => ({
                      ...old,
                      configuration: chosen.revision,
                      snapshot: "",
                      service: Object.keys(chosen.services)[0],
                    }));
                }}
              >
                <option value="" disabled>
                  {loading
                    ? "Loading configurations…"
                    : "Select a configuration"}
                </option>
                {configurations.map((config) => (
                  <option key={config.revision} value={config.revision}>
                    {config.application} · {config.environment} ·{" "}
                    {config.release} · {config.revision.slice(0, 6)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Evidence source
              <select
                aria-label="Evidence source"
                value={form.snapshot}
                onChange={(e) => void selectSnapshot(e.target.value)}
              >
                <option value="">
                  {configuration?.application === "shopping-demo"
                    ? "Connected demo logs"
                    : "No live source connected"}
                </option>
                {snapshots.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.source_name} · {item.record_count} records
                    {item.synthetic_example ? " · example" : ""}
                  </option>
                ))}
              </select>
            </label>
            {configuration?.application !== "shopping-demo" &&
              !snapshot &&
              !loading && (
                <p className="notice">
                  Upload a log snapshot under Applications and select it here.
                  Registration alone does not connect live evidence.
                </p>
              )}
            <label>
              Incident title
              <input
                autoFocus
                required
                minLength={3}
                maxLength={200}
                placeholder="Requests are returning errors"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
              />
            </label>
            <div className="two">
              <label>
                Affected service
                <select
                  value={form.service}
                  onChange={(e) =>
                    setForm({ ...form, service: e.target.value })
                  }
                >
                  {Object.keys(configuration?.services || {})
                    .filter(
                      (service) =>
                        !snapshot ||
                        snapshot.covered_services.includes(service),
                    )
                    .map((service) => (
                      <option key={service}>{service}</option>
                    ))}
                </select>
              </label>
              <label>
                Look back
                <select
                  disabled={!!snapshot}
                  value={form.minutes}
                  onChange={(e) =>
                    setForm({ ...form, minutes: e.target.value })
                  }
                >
                  <option value="5">5 minutes</option>
                  <option value="15">15 minutes</option>
                  <option value="30">30 minutes</option>
                  <option value="60">1 hour</option>
                </select>
              </label>
            </div>
            <label>
              Symptoms
              <textarea
                required
                minLength={3}
                maxLength={4000}
                rows={4}
                placeholder="Describe the symptoms you observed. Avoid credentials or personal data."
                value={form.description}
                onChange={(e) =>
                  setForm({ ...form, description: e.target.value })
                }
              />
            </label>
            <p className="small muted">
              {configuration && (
                <>
                  Scope: {configuration.application} ·{" "}
                  {configuration.environment} · {configuration.release}.{" "}
                </>
              )}
              {snapshot && (
                <>
                  Captured window: {date(snapshot.starts_at)} —{" "}
                  {date(snapshot.ends_at)}.{" "}
                </>
              )}
              Retrying an unchanged submission reuses its request key and time
              window.
            </p>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <button
              className="primary wide"
              type="submit"
              disabled={
                loading ||
                !configuration ||
                (configuration.application !== "shopping-demo" && !snapshot)
              }
            >
              {busy ? "Submitting…" : "Investigate incident →"}
            </button>
          </fieldset>
        </form>
      </section>
    </div>
  );
}
