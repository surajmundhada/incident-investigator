import { useEffect, useState } from "react";
import { api } from "./api";
import type { ApplicationConfiguration } from "./types";

type Head = {
  revision: string | null;
  documents: { id: string; title: string }[];
};
type Document = {
  id: string;
  title: string;
  service: string;
  markdown: string;
};

export function RunbookUpload({
  configuration,
}: {
  configuration: ApplicationConfiguration;
}) {
  const [head, setHead] = useState<Head | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  async function reload() {
    setError("");
    setAcknowledged(false);
    try {
      setHead(
        await api<Head>(
          `/api/knowledge/head?application=${encodeURIComponent(configuration.application)}`,
        ),
      );
    } catch (e) {
      setHead(null);
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void reload();
  }, [configuration.application]);
  async function choose(files: FileList | null) {
    setError("");
    setSuccess("");
    setDocuments([]);
    setAcknowledged(false);
    if (!files?.length) return;
    try {
      if (
        files.length > 50 ||
        [...files].some(
          (file) =>
            file.size > 100000 || !file.name.toLowerCase().endsWith(".md"),
        )
      )
        throw new Error("Choose up to 50 Markdown files, each at most 100 KB.");
      if ([...files].reduce((size, file) => size + file.size, 0) > 1000000)
        throw new Error("The complete corpus must be at most 1 MB.");
      const next = await Promise.all(
        [...files].map(async (file) => {
          const markdown = await file.text();
          const id = file.name
            .replace(/\.md$/i, "")
            .toLowerCase()
            .replace(/[^a-z0-9-]/g, "-")
            .slice(0, 70);
          return {
            id,
            markdown,
            service: "global",
            title: (markdown.match(/^#\s+(.+)$/m)?.[1] || file.name).slice(
              0,
              120,
            ),
          };
        }),
      );
      setDocuments(next);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  function change(index: number, field: keyof Document, value: string) {
    setDocuments((old) =>
      old.map((doc, i) => (i === index ? { ...doc, [field]: value } : doc)),
    );
  }
  async function publish(event: React.FormEvent) {
    event.preventDefault();
    if (!head || !acknowledged) return;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const result = await api<{ revision: string; passages: number }>(
        "/api/knowledge/documents",
        {
          method: "POST",
          body: JSON.stringify({
            application: configuration.application,
            configuration_revision: configuration.revision,
            expected_revision: head.revision,
            replace_application_corpus: true,
            documents,
          }),
        },
      );
      await reload();
      setSuccess(
        `Published ${result.passages} searchable passages. Revision ${result.revision.slice(0, 12)}.`,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card upload-panel">
      <div className="row">
        <h2>Runbooks for {configuration.application}</h2>
        <button
          type="button"
          className="secondary"
          onClick={() => void reload()}
          disabled={busy}
        >
          Reload knowledge
        </button>
      </div>
      <p className="small muted">
        Upload reviewed Markdown guidance for {configuration.environment} ·{" "}
        {configuration.release}. Documents are untrusted guidance, not current
        incident evidence. Recognised credentials are redacted before indexing.
      </p>
      {head && (
        <p className="small">
          Current corpus: {head.documents.length}{" "}
          {head.documents.length === 1 ? "document" : "documents"} ·{" "}
          {head.revision?.slice(0, 12) || "none"}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {success && <p role="status">{success}</p>}
      <form className="onboarding-form" onSubmit={publish}>
        <fieldset disabled={busy}>
          <label>
            Complete Markdown corpus
            <input
              type="file"
              accept=".md,text/markdown"
              multiple
              onChange={(e) => void choose(e.target.files)}
            />
          </label>
          {documents.map((doc, index) => (
            <div className="two" key={index}>
              <label>
                Document ID
                <input
                  required
                  pattern="[a-z][a-z0-9-]{1,79}"
                  value={doc.id}
                  onChange={(e) => change(index, "id", e.target.value)}
                />
              </label>
              <label>
                Title
                <input
                  required
                  minLength={3}
                  maxLength={120}
                  value={doc.title}
                  onChange={(e) => change(index, "title", e.target.value)}
                />
              </label>
              <label>
                Applies to
                <select
                  value={doc.service}
                  onChange={(e) => change(index, "service", e.target.value)}
                >
                  <option value="global">All services (global)</option>
                  {Object.keys(configuration.services).map((service) => (
                    <option key={service}>{service}</option>
                  ))}
                </select>
              </label>
            </div>
          ))}
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />
            Replace this application's entire active corpus, across all releases
            and environments, with these {documents.length} documents.
            Historical citations remain available.
          </label>
          <button
            className="primary"
            disabled={!head || !documents.length || !acknowledged || busy}
          >
            {busy ? "Indexing locally…" : "Publish runbooks"}
          </button>
        </fieldset>
      </form>
    </section>
  );
}
