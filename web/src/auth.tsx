import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api, session } from "./api/client";
import type { Me } from "./api/types";

export interface AuthState {
  me: Me | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  can: (permission: string) => boolean;
}

export const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const logout = useCallback(() => { session.set(null); setMe(null); }, []);
  useEffect(() => session.onExpired(logout), [logout]);

  const login = useCallback(async (username: string, password: string) => {
    const result = await api.login(username, password);
    session.set(result.access_token);
    setMe(await api.me()); // permissions come from the server, not from the token
  }, []);

  const can = useCallback((p: string) => !!me?.permissions.includes(p), [me]);
  return <AuthContext.Provider value={{ me, login, logout, can }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const location = useLocation();
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}
