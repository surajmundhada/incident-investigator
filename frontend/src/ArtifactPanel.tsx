import { useEffect, useState } from "react";
import { api } from "./api";

type Artifact = {
  id: string;
  backend: string;
  status: string;
  size: number;
  checksum: string;
  attempts: number;
  downloadable?: boolean;
};

export function ArtifactPanel({ id }: { id: string }) {
  const [items, setItems] = useState<Artifact[]>([]);
  const [message, setMessage] = useState("");
  const [configured, setConfigured] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function refresh() {
      try {
        const result = await api<{ items: Artifact[] }>(
          `/api/investigations/${encodeURIComponent(id)}/artifacts`,
          { signal: controller.signal },
        );
        if (!active) return;
        setItems(result.items);
        setConfigured(true);
        setMessage("");
        if (result.items.some((item) => item.status === "pending_upload"))
          timer = setTimeout(refresh, 2000);
      } catch {
        if (!active) return;
        setMessage(
          "Server archive is unavailable. Export JSON above still works.",
        );
      }
    }
    void refresh();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [id, revision]);
  async function submit(artifactId?: string) {
    setBusy(true);
    try {
      await api(
        artifactId
          ? `/api/artifacts/${artifactId}/retry`
          : `/api/investigations/${encodeURIComponent(id)}/artifacts`,
        { method: "POST" },
      );
      setRevision((old) => old + 1);
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card">
      <div className="row">
        <h2>Saved archive</h2>
        {configured && (
          <button disabled={busy} onClick={() => void submit()}>
            Archive investigation
          </button>
        )}
      </div>
      <p className="small muted">
        Archives include the report and all saved evidence. Storage delivery
        runs separately from diagnosis.
      </p>
      {message && <p className="small muted">{message}</p>}
      {items.map((item) => (
        <div className="row" key={item.id}>
          <span className="small">
            {item.backend} · {item.status.replaceAll("_", " ")} ·{" "}
            {(item.size / 1024).toFixed(1)} KB · SHA-256{" "}
            {item.checksum.slice(0, 12)}
          </span>
          {item.status === "available" && item.downloadable !== false && (
            <a href={`/api/artifacts/${item.id}/download`}>Download archive</a>
          )}
          {item.status === "available" && item.downloadable === false && (
            <span className="small muted">
              This storage backend is not active.
            </span>
          )}
          {item.status === "failed" && (
            <button disabled={busy} onClick={() => void submit(item.id)}>
              Retry archive
            </button>
          )}
        </div>
      ))}
    </section>
  );
}
