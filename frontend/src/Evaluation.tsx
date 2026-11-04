import { useState } from "react";
import { evaluationSummary as data } from "./evaluationSummary";

export function Evaluation() {
  const [tab, setTab] = useState<"retrieval" | "latency">("retrieval");
  const baseline = data.rag.find((row) => row.id === "v2_baseline")!;
  const candidate = data.rag.find((row) => row.id === "improved")!;
  const percentage = (value: number) => `${(value * 100).toFixed(1)}%`;
  return (
    <div className="evaluation-page">
      <section className="card">
        <p className="small muted">MEASURED PROGRESS · {data.study_date}</p>
        <h1>Evaluation results</h1>
        <p>
          Compare saved measurements, inspect tradeoffs, and keep claims tied to
          evidence.
        </p>
        <div className="row">
          <button
            className={tab === "retrieval" ? "primary" : ""}
            onClick={() => setTab("retrieval")}
          >
            Retrieval quality
          </button>
          <button
            className={tab === "latency" ? "primary" : ""}
            onClick={() => setTab("latency")}
          >
            Cache latency
          </button>
        </div>
      </section>
      {tab === "retrieval" ? (
        <section className="card">
          <h2>More coverage, weaker ranking</h2>
          <p>
            Recall@5:{" "}
            <strong>
              {percentage(baseline.recall_at_5)} →{" "}
              {percentage(candidate.recall_at_5)}
            </strong>
            . MRR@5:{" "}
            <strong>
              {baseline.mrr_at_5.toFixed(3)} → {candidate.mrr_at_5.toFixed(3)}
            </strong>
            . The experimental change was not promoted; production keeps the
            baseline.
          </p>
          <div
            className="evaluation-table"
            role="region"
            aria-label="Retrieval comparison"
            tabIndex={0}
          >
            <table>
              <thead>
                <tr>
                  <th>Method</th>
                  <th>Recall@5</th>
                  <th>MRR@5</th>
                  <th>nDCG@5</th>
                  <th>Warm p95</th>
                </tr>
              </thead>
              <tbody>
                {data.rag.map((row) => (
                  <tr key={row.id}>
                    <td>{row.name}</td>
                    <td>{percentage(row.recall_at_5)}</td>
                    <td>{row.mrr_at_5.toFixed(3)}</td>
                    <td>{row.ndcg_at_5.toFixed(3)}</td>
                    <td>{row.p95_ms.toFixed(1)} ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">
            Recall@5 measures relevant section coverage. MRR rewards the first
            relevant result appearing earlier; nDCG considers ranking quality
            across results. None measures diagnosis accuracy.
          </p>
        </section>
      ) : (
        <section className="card">
          <h2>Cache benefit depends on repeated work</h2>
          <div
            className="evaluation-table"
            role="region"
            aria-label="Cache comparison"
            tabIndex={0}
          >
            <table>
              <thead>
                <tr>
                  <th>Workload</th>
                  <th>Without cache p50</th>
                  <th>With cache p50</th>
                  <th>Observed change</th>
                </tr>
              </thead>
              <tbody>
                {data.cache.map((row) => (
                  <tr key={row.workload}>
                    <td>
                      {row.workload === "warm_repeated"
                        ? "Repeated queries"
                        : "Unique queries"}
                    </td>
                    <td>{row.before_ms.toFixed(3)} ms</td>
                    <td>{row.after_ms.toFixed(3)} ms</td>
                    <td>
                      {Math.abs(row.reduction_percent).toFixed(1)}%{" "}
                      {row.reduction_percent >= 0 ? "lower" : "higher"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Results matched across modes. Each workload used 40 measured
            requests per mode. Unique queries became slower, so Redis remains
            optional and disabled by default.
          </p>
        </section>
      )}
      {data.pilot.available && (
        <section className="card">
          <h2>Fresh development pilot</h2>
          <p>
            {data.pilot.calls_started} model calls across four fixed-evidence
            cases, with {data.pilot.reported_tokens.toLocaleString()}{" "}
            provider-reported tokens. This development pilot is separate from
            the reserved workflow comparison.
          </p>
          <div
            className="evaluation-table"
            role="region"
            aria-label="Development pilot results"
            tabIndex={0}
          >
            <table>
              <thead>
                <tr>
                  <th>Method</th>
                  <th>Structurally valid reports</th>
                </tr>
              </thead>
              <tbody>
                {data.pilot.methods.map((row) => (
                  <tr key={row.method}>
                    <td>{row.method.replaceAll("_", " ")}</td>
                    <td>
                      {row.valid}/{row.attempted}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Schema and citation-ID checks passed or rejected these reports. They
            do not establish semantic faithfulness, diagnosis accuracy, or an
            improvement from RAG. This small internal pilot is separate from the
            historical retrieval study.
          </p>
        </section>
      )}
      {data.workflow.available && (
        <section className="card">
          <h2>
            Reserved workflow comparison —{" "}
            {data.workflow.complete ? "complete" : "incomplete"}
          </h2>
          <p>
            {data.workflow.attempted}/{data.workflow.planned} planned episodes
            attempted; {data.workflow.valid_reports} validated reports,{" "}
            {data.workflow.calls_started} model starts and{" "}
            {data.workflow.reported_tokens.toLocaleString()} reported tokens.
          </p>
          {!data.workflow.complete && (
            <p>
              Stopped on a provider error. Failed or unknown requests were not
              retried. This partial run cannot establish final accuracy or
              method superiority. {data.workflow.untouched_cases} captured cases
              remain untouched.
            </p>
          )}
          <p className="small muted">
            This comparison uses the production worker, scoped replay tools and
            LangGraph with isolated persistence. Typed service matching is not a
            semantic faithfulness or underlying-cause guarantee.
          </p>
        </section>
      )}
      <section className="card">
        <h2>What these results establish</h2>
        <ul>
          {data.limits.map((limit) => (
            <li key={limit}>{limit}</li>
          ))}
        </ul>
        <p>
          Next study: compare the complete active workflow on the reserved
          cases, with frozen budgets and a separate evidence-support review. New
          results must have a separate version.
        </p>
        <details>
          <summary>Measurement provenance</summary>
          {data.sources.map((source) => (
            <p className="small" key={source.path}>
              {source.path}
              <br />
              <code className="evaluation-hash">SHA-256 {source.sha256}</code>
            </p>
          ))}
        </details>
      </section>
    </div>
  );
}
