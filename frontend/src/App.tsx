import { useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { Icon } from "./Icon";
import { Overview } from "./Overview";
import { Applications } from "./Applications";
import { Evaluation } from "./Evaluation";
import { CacheStatus } from "./CacheStatus";
import type { Item } from "./types";

export function App({
  renderDetail,
  renderNewIncident,
}: {
  renderDetail: (id: string) => ReactNode;
  renderNewIncident: (
    close: () => void,
    created: (id: string) => void,
  ) => ReactNode;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [error, setError] = useState("");
  const [online, setOnline] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [creating, setCreating] = useState(false);
  const [route, setRoute] = useState(location.hash.slice(1));
  const selected = [
    "investigations",
    "applications",
    "evaluation",
    "cache",
  ].includes(route)
    ? ""
    : route;
  useEffect(() => {
    const change = () => setRoute(location.hash.slice(1));
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function refresh() {
      try {
        const [result] = await Promise.all([
          api<{ items: Item[] }>("/api/incidents?limit=100", {
            signal: controller.signal,
          }),
          api("/readyz", { signal: controller.signal }),
        ]);
        if (active) {
          setItems(result.items);
          setLoaded(true);
          setOnline(true);
          setError("");
        }
      } catch (e) {
        if (active) {
          setOnline(false);
          setError((e as Error).message);
        }
      }
      if (active) timer = setTimeout(refresh, 5000);
    }
    void refresh();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, []);
  function select(value: string) {
    location.hash = value;
    setRoute(value);
  }
  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <a className="brand" href="#" onClick={() => select("")}>
          <span className="brand-mark">
            <Icon name="pulse" size={23} />
          </span>
          <span>
            Incident<small>INVESTIGATOR</small>
          </span>
        </a>
        <div className="workspace-switch">
          <span className="workspace-avatar">W</span>
          <span>
            <strong>My workspace</strong>
            <small>Local environment</small>
          </span>
          <span className="workspace-switch-indicator">LOCAL</span>
        </div>
        <div className="nav-caption">WORKSPACE</div>
        <nav className="primary-nav" aria-label="Workspace navigation">
          <button className={!route ? "active" : ""} onClick={() => select("")}>
            <Icon name="grid" />
            <span>Overview</span>
          </button>
          <button
            className={selected || route === "investigations" ? "active" : ""}
            onClick={() => select("investigations")}
          >
            <Icon name="layers" />
            <span>Investigations</span>
            {loaded && <span className="nav-count">{items.length}</span>}
          </button>
          <button
            className={route === "applications" ? "active" : ""}
            onClick={() => select("applications")}
          >
            <Icon name="layers" />
            <span>Applications</span>
          </button>
        </nav>
        <nav className="primary-nav" aria-label="Evaluation navigation">
          <button
            className={route === "evaluation" ? "active" : ""}
            onClick={() => select("evaluation")}
          >
            <Icon name="grid" />
            <span>Evaluation</span>
          </button>
          <button
            className={route === "cache" ? "active" : ""}
            onClick={() => select("cache")}
          >
            <Icon name="pulse" />
            <span>Cache status</span>
          </button>
        </nav>
        <div className="recent-nav">
          <div className="nav-caption">RECENT CASES</div>
          {items.slice(0, 5).map((item) => (
            <button
              key={item.investigation_id}
              title={item.title}
              className={`recent-link ${selected === item.investigation_id ? "active" : ""}`}
              onClick={() => select(item.investigation_id)}
            >
              <span className={`recent-dot ${item.status}`} />
              <span>{item.title}</span>
            </button>
          ))}
          {loaded && !items.length && (
            <p className="muted small">Your saved cases will appear here.</p>
          )}
        </div>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <span className="note-icon">
              <Icon name="shield" size={19} />
            </span>
            <strong>Built around evidence.</strong>
            <p>
              Read-only tools.
              <br />
              Findings you can inspect.
            </p>
          </div>
          <div className="workspace-profile">
            <span className="profile-avatar">L</span>
            <div>
              <strong>Local workspace</strong>
              <small>Private demonstration</small>
            </div>
            <span className="profile-dot" />
          </div>
        </div>
      </aside>
      <div className="app-body">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Workspace</span>
            <Icon name="chevron" size={13} />
            <strong>
              {selected
                ? "Investigation"
                : route === "applications"
                  ? "Applications"
                  : route === "evaluation"
                    ? "Evaluation"
                    : route === "cache"
                      ? "Cache status"
                      : route
                        ? "Investigations"
                        : "Overview"}
            </strong>
          </div>
          <div className="header-actions">
            <div className="connection">
              <i className={online ? "online" : ""} />
              {online ? "API ready" : "API unavailable"}
            </div>
            <button
              className="primary new-button"
              onClick={() => setCreating(true)}
            >
              + New investigation
            </button>
          </div>
        </header>
        <main>
          {error && (
            <p className="error workspace-error" role="alert">
              {error}
            </p>
          )}
          {route === "cache" ? (
            <CacheStatus />
          ) : route === "evaluation" ? (
            <Evaluation />
          ) : route === "applications" ? (
            <Applications />
          ) : selected ? (
            <div key={selected}>{renderDetail(selected)}</div>
          ) : (
            <Overview
              key={route}
              items={items}
              online={online}
              loaded={loaded}
              all={route === "investigations"}
              create={() => setCreating(true)}
              select={select}
              viewAll={() => select("investigations")}
            />
          )}
        </main>
      </div>
      {creating &&
        renderNewIncident(
          () => setCreating(false),
          (id) => {
            setCreating(false);
            select(id);
          },
        )}
    </div>
  );
}
