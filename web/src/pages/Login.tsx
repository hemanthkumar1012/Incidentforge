import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) { setError("Enter both username and password."); return; }
    setBusy(true); setError(null);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? (err.isAuth ? "Invalid username or password." : err.message) : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="main" style={{ maxWidth: 420, margin: "10vh auto" }}>
      <div className="card">
        <h1>IncidentForge</h1>
        <p className="muted">Incident investigation and verified recovery for the demo shop. All traffic and data are synthetic.</p>
        <form onSubmit={submit} noValidate>
          <div className="field">
            <label htmlFor="username">Username</label>
            <input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {error && <p className="field-error" role="alert">{error}</p>}
          <button className="primary" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
        <p className="muted" style={{ fontSize: 13 }}>Your session is kept in memory only; reloading the page signs you out.</p>
      </div>
    </main>
  );
}
