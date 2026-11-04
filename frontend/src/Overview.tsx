import { useState } from "react";
import { date } from "./api";
import { Icon } from "./Icon";
import type { Item } from "./types";

export function Overview({
  items,
  online,
  loaded,
  all,
  create,
  select,
  viewAll,
}: {
  items: Item[];
  online: boolean;
  loaded: boolean;
  all: boolean;
  create: () => void;
  select: (id: string) => void;
  viewAll: () => void;
}) {
  const [filter, setFilter] = useState("");
  const [status, setStatus] = useState("all");
  const [page, setPage] = useState(0);
  const active = items.filter((item) =>
    ["queued", "running"].includes(item.status),
  ).length;
  const completed = items.filter((item) => item.status === "complete").length;
  const visible = items.filter(
    (item) =>
      `${item.application || "shopping-demo"} ${item.title} ${item.service} ${item.status}`
        .toLowerCase()
        .includes(filter.toLowerCase()) &&
      (status === "all" ||
        (status === "active"
          ? ["queued", "running"].includes(item.status)
          : item.status === status)),
  );
  const size = all ? 10 : 6;
  const maxPage = Math.max(0, Math.ceil(visible.length / size) - 1);
  const currentPage = Math.min(page, maxPage);
  const rows = visible.slice(currentPage * size, (currentPage + 1) * size);
  return (
    <section className="overview">
      <div className="page-intro">
        <div>
          <div className="eyebrow">YOUR WORKSPACE, AT A GLANCE</div>
          <h1>
            {all ? "Investigations" : "A clearer view of every incident."}
          </h1>
          <p className="muted">
            {all
              ? "Find a case, follow its evidence, and pick up where you left off."
              : "From the first symptom to a conclusion you can inspect."}
          </p>
        </div>
        <span className="workspace-pill">
          <span /> Local workspace
        </span>
      </div>
      {!all && (
        <>
          <div className="overview-stats">
            <article>
              <span className="metric-icon blue">
                <Icon name="layers" />
              </span>
              <div>
                <span className="metric-label">Loaded investigations</span>
                <strong>
                  {loaded ? items.length.toString().padStart(2, "0") : "—"}
                </strong>
              </div>
              <span className="metric-note">Latest 100</span>
            </article>
            <article>
              <span className="metric-icon pink">
                <Icon name="pulse" />
              </span>
              <div>
                <span className="metric-label">In progress</span>
                <strong>
                  {loaded ? active.toString().padStart(2, "0") : "—"}
                </strong>
              </div>
              <span className="metric-note">Queued & running</span>
            </article>
            <article>
              <span className="metric-icon violet">
                <Icon name="check" />
              </span>
              <div>
                <span className="metric-label">Completed</span>
                <strong>
                  {loaded ? completed.toString().padStart(2, "0") : "—"}
                </strong>
              </div>
              <span className="metric-note">Review conclusions</span>
            </article>
          </div>
          <article className="start-banner">
            <div className="start-copy">
              <span className="feature-label">
                <Icon name="spark" size={13} /> AI-ASSISTED INVESTIGATION
              </span>
              <h2>
                Less digging.
                <br />
                More understanding.
              </h2>
              <p>
                Connect the symptoms, follow the evidence,
                <br className="desktop-break" /> and see what still needs an
                answer.
              </p>
              <button className="primary" onClick={create}>
                Start an investigation <Icon name="arrow" size={16} />
              </button>
            </div>
            <div
              className="flow-illustration"
              aria-label="Investigation flow: collect logs, retrieve guidance, review findings"
            >
              <div className="flow-orbit orbit-one" />
              <div className="flow-orbit orbit-two" />
              <span className="orbit-dot" />
              <div className="flow-chip chip-logs">
                <span className="flow-icon blue">
                  <Icon name="pulse" />
                </span>
                <div>
                  <strong>Collect signals</strong>
                  <small>Read-only operational logs</small>
                </div>
                <span className="flow-step">01</span>
              </div>
              <div className="flow-chip chip-guidance">
                <span className="flow-icon pink">
                  <Icon name="document" />
                </span>
                <div>
                  <strong>Find the context</strong>
                  <small>Versioned runbook guidance</small>
                </div>
                <span className="flow-step">02</span>
              </div>
              <div className="flow-chip chip-findings">
                <span className="flow-icon violet">
                  <Icon name="spark" />
                </span>
                <div>
                  <strong>Connect the evidence</strong>
                  <small>Findings you can review</small>
                </div>
                <span className="flow-step">03</span>
              </div>
            </div>
          </article>
        </>
      )}
      <section className="cases-panel" aria-labelledby="cases-title">
        <div className="cases-heading">
          <div>
            <h2 id="cases-title">
              {all ? "All investigations" : "Recent investigations"}{" "}
              <span className="count">{loaded ? items.length : "—"}</span>
            </h2>
            <p className="muted">Your saved cases, ready for a closer look.</p>
          </div>
          {!all && (
            <button className="view-all" onClick={viewAll}>
              View all <Icon name="arrow" size={15} />
            </button>
          )}
        </div>
        <div className="table-toolbar">
          <div className="filter-tabs" aria-label="Filter investigation status">
            {[
              ["all", "All cases"],
              ["active", "In progress"],
              ["complete", "Completed"],
            ].map(([value, label]) => (
              <button
                key={value}
                aria-pressed={status === value}
                onClick={() => {
                  setStatus(value);
                  setPage(0);
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <label className="case-search">
            <Icon name="search" size={16} />
            <input
              aria-label="Search investigations"
              placeholder="Search investigations…"
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value);
                setPage(0);
              }}
            />
          </label>
        </div>
        <div className="table-scroll">
          <table className="cases-table">
            <thead>
              <tr>
                <th>INVESTIGATION</th>
                <th>SERVICE</th>
                <th>STATUS</th>
                <th>CREATED</th>
                <th>
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr key={item.investigation_id}>
                  <td>
                    <button
                      className="case-title"
                      onClick={() => select(item.investigation_id)}
                    >
                      <span className={`case-icon ${item.service}`}>
                        <Icon name="layers" size={17} />
                      </span>
                      <span>
                        <strong>{item.title}</strong>
                        <small>
                          CASE ·{" "}
                          {item.investigation_id.slice(0, 8).toUpperCase()}
                        </small>
                      </span>
                    </button>
                  </td>
                  <td>
                    <span className="service-pill">
                      <span className={`service-dot ${item.service}`} />
                      {item.service}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${item.status}`}>
                      <i />
                      {item.status}
                    </span>
                  </td>
                  <td className="case-date">{date(item.created_at)}</td>
                  <td>
                    <button
                      className="open-case"
                      aria-label={`Open ${item.title}`}
                      onClick={() => select(item.investigation_id)}
                    >
                      <Icon name="chevron" size={17} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!rows.length && (
          <div className="table-empty">
            <Icon name="search" size={24} />
            <strong>
              {!loaded
                ? online
                  ? "Loading investigations…"
                  : "Waiting for the local API"
                : filter || status !== "all"
                  ? "No matching investigations"
                  : "Your first investigation starts here"}
            </strong>
            <p>
              {!loaded
                ? "Cases will appear when the workspace connects."
                : filter || status !== "all"
                  ? "Try a different search or status filter."
                  : "Describe a symptom and let the investigator gather evidence."}
            </p>
            {loaded && !items.length && (
              <button onClick={create}>Create an investigation</button>
            )}
          </div>
        )}
        <footer className="table-footer">
          <span>
            {rows.length
              ? `${currentPage * size + 1}–${currentPage * size + rows.length} of ${visible.length} matching cases`
              : "0 cases"}
            {!online && loaded && " · saved view; API unavailable"}
          </span>
          {all && (
            <div>
              <button
                disabled={currentPage === 0}
                onClick={() => setPage(currentPage - 1)}
              >
                Previous
              </button>
              <button
                disabled={currentPage >= maxPage}
                onClick={() => setPage(currentPage + 1)}
              >
                Next
              </button>
            </div>
          )}
        </footer>
      </section>
      <footer className="workspace-footer">
        <span>
          <Icon name="shield" size={14} /> Read-only investigation. Every
          conclusion stays open to review.
        </span>
        <span>Local · demo-v1</span>
      </footer>
    </section>
  );
}
