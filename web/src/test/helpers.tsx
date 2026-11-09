import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import type { Me, Role } from "../api/types";
import { AuthContext } from "../auth";

const PERMS: Record<Role, string[]> = {
  viewer: ["read"],
  operator: ["read", "incident:register", "incident:close", "investigation:run", "proposal:validate", "approval:request", "recovery:execute"],
  approver: ["read", "approval:decide"],
  admin: ["read", "incident:register", "investigation:run", "proposal:validate", "approval:request", "approval:decide", "recovery:execute"],
};

export function renderAs(role: Role, ui: ReactNode, username = role === "approver" ? "arun" : "olivia") {
  const me: Me = { username, role, permissions: PERMS[role] };
  return render(
    <AuthContext.Provider value={{ me, login: async () => {}, logout: () => {}, can: (p) => me.permissions.includes(p) }}>
      <MemoryRouter>{ui}</MemoryRouter>
    </AuthContext.Provider>,
  );
}
