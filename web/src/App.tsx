import { useState, type ReactNode } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api/client";
import { RequireAuth, useAuth } from "./auth";
import { Icon, type IconName } from "./components/icons";
import { usePolling } from "./hooks/usePolling";
import { ApprovalQueue } from "./pages/ApprovalQueue";
import { Evaluation } from "./pages/Evaluation";
import { Incidents } from "./pages/Incidents";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { IncidentWorkspace } from "./pages/workspace/IncidentWorkspace";
import { useTheme } from "./theme";

const SIDEBAR_KEY = "incidentforge.sidebar";

// Cosmetic preference only (see theme.tsx); storage failures fall back to expanded.
function storedCollapsed(): boolean {
  try { return window.localStorage.getItem(SIDEBAR_KEY) === "collapsed"; } catch { return false; }
}

// Count of approvals waiting for a decision, from the server. Rendered only for users who can decide,
// so other roles never fire a request they are not allowed to make.
function PendingApprovals() {
  const q = usePolling((s) => api.approvals("pending", s), 15_000);
  const n = q.data?.items.length ?? 0;
  if (!n) return null;
  return <span className="count" aria-label={`${n} pending`}>{n}</span>;
}

function NavItem({ to, icon, label, end, extra }: { to: string; icon: IconName; label: string; end?: boolean; extra?: ReactNode }) {
  return (
    <NavLink to={to} end={end} title={label}>
      <Icon name={icon} /><span className="label">{label}</span>{extra}
    </NavLink>
  );
}

function Breadcrumbs() {
  const { pathname } = useLocation();
  const parts = pathname.split("/").filter(Boolean);
  const trail: { to?: string; text: string }[] = [{ to: parts.length ? "/" : undefined, text: "Overview" }];
  if (parts[0] === "incidents") {
    trail.push({ to: parts[1] ? "/incidents" : undefined, text: "Incidents" });
    if (parts[1]) trail.push({ text: `Incident ${parts[1].slice(0, 8)}` });
  } else if (parts[0] === "approvals") trail.push({ text: "Approvals" });
  else if (parts[0] === "evaluation") trail.push({ text: "Evaluation" });
  else if (parts.length) trail.push({ text: "Not found" });
  const shown = parts.length ? trail : [{ text: "Overview" }];
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      {shown.map((t, i) => (
        <span key={t.text}>
          {i > 0 && <span aria-hidden="true"> / </span>}
          {t.to ? <Link to={t.to}>{t.text}</Link> : <span aria-current="page">{t.text}</span>}
        </span>
      ))}
    </nav>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const { me, logout, can } = useAuth();
  const { theme, toggle } = useTheme();
  const [collapsed, setCollapsed] = useState(storedCollapsed);
  function toggleSidebar() {
    setCollapsed((c) => {
      try { window.localStorage.setItem(SIDEBAR_KEY, c ? "expanded" : "collapsed"); } catch { /* not remembered */ }
      return !c;
    });
  }
  return (
    <div className={`shell${collapsed ? " collapsed" : ""}`}>
      <a href="#main" className="skip">Skip to content</a>
      <nav className="nav" aria-label="Primary">
        <div className="brand"><span className="brand-mark" aria-hidden="true" /><span className="label">IncidentForge</span></div>
        <NavItem to="/" end icon="overview" label="Overview" />
        <NavItem to="/incidents" icon="incidents" label="Incidents" />
        <NavItem to="/approvals" icon="approvals" label="Approvals" extra={can("approval:decide") ? <PendingApprovals /> : null} />
        <NavItem to="/evaluation" icon="evaluation" label="Evaluation" />
        <div className="spacer" />
        <div className="nav-foot">
          <div className="who">
            <span className="avatar" aria-hidden="true">{me?.username.slice(0, 2)}</span>
            <span className="who-text"><strong>{me?.username}</strong><br />{me?.role}</span>
          </div>
          <button className="ghost" onClick={logout} title="Sign out"><Icon name="logout" /><span className="label">Sign out</span></button>
          <button className="ghost collapse-toggle" onClick={toggleSidebar} aria-pressed={collapsed}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
            <Icon name={collapsed ? "expand" : "collapse"} /><span className="label">Collapse</span>
          </button>
        </div>
      </nav>
      <div className="content">
        <header className="topbar">
          <Breadcrumbs />
          <span className="spacer" />
          <span className="env-pill" title="Demo shop, synthetic traffic, injected faults">Research lab · not production</span>
          <button className="icon-btn" onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
            <Icon name={theme === "dark" ? "sun" : "moon"} />
          </button>
        </header>
        <main id="main" className="main" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}

export function App() {
  const protectedRoute = (el: ReactNode) => <RequireAuth><Shell>{el}</Shell></RequireAuth>;
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={protectedRoute(<Overview />)} />
      <Route path="/incidents" element={protectedRoute(<Incidents />)} />
      <Route path="/incidents/:id" element={protectedRoute(<IncidentWorkspace />)} />
      <Route path="/approvals" element={protectedRoute(<ApprovalQueue />)} />
      <Route path="/evaluation" element={protectedRoute(<Evaluation />)} />
      <Route path="*" element={protectedRoute(<p>Page not found.</p>)} />
    </Routes>
  );
}
