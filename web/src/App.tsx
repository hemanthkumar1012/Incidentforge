import type { ReactNode } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { RequireAuth, useAuth } from "./auth";
import { ApprovalQueue } from "./pages/ApprovalQueue";
import { Evaluation } from "./pages/Evaluation";
import { Incidents } from "./pages/Incidents";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { IncidentWorkspace } from "./pages/workspace/IncidentWorkspace";

function Shell({ children }: { children: ReactNode }) {
  const { me, logout } = useAuth();
  return (
    <div className="shell">
      <a href="#main" className="skip">Skip to content</a>
      <nav className="nav" aria-label="Primary">
        <span className="brand">IncidentForge</span>
        <NavLink to="/" end>Overview</NavLink>
        <NavLink to="/incidents">Incidents</NavLink>
        <NavLink to="/approvals">Approvals</NavLink>
        <NavLink to="/evaluation">Evaluation</NavLink>
        <span className="who">{me?.username} · {me?.role} <button className="link" style={{ color: "#cfe0ff" }} onClick={logout}>Sign out</button></span>
      </nav>
      <main id="main" className="main" tabIndex={-1}>
        <p className="banner">Controlled research environment: demo shop, synthetic traffic, injected faults. Not a production system.</p>
        {children}
      </main>
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
