import { screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type { Evidence } from "../api/types";
import { Incidents } from "../pages/Incidents";
import { EvidencePanel } from "../pages/workspace/InvestigationView";
import { renderAs } from "./helpers";

afterEach(() => vi.restoreAllMocks());

it("renders untrusted log content as text, never as HTML, and shows injection flags", () => {
  const evil: Evidence = { id: "E1", tool: "search_logs", arguments: { service: "checkout" }, ok: true, summary: "search_logs: 1 items",
    data: { lines: [{ msg: '<img src=x onerror="alert(1)"><script>steal()</script>' }] }, error: null,
    injection_flags: ["override_instructions"], truncated: false, duration_ms: 12, created_at: "2026-11-08T10:00:00Z", trust: "untrusted" };
  const { container } = renderAs("viewer", <EvidencePanel evidence={[evil]} focused="E1" />);
  expect(container.querySelector("img, script")).toBeNull();
  expect(screen.getByText(/<script>steal\(\)<\/script>/)).toBeInTheDocument();
  expect(screen.getByText(/possible prompt injection: override_instructions/)).toBeInTheDocument();
});

it("incident list: empty state", async () => {
  vi.spyOn(api, "incidents").mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
  renderAs("viewer", <Incidents />);
  expect(await screen.findByText(/No incidents match/)).toBeInTheDocument();
  expect(screen.queryByText("Register an incident")).not.toBeInTheDocument(); // viewer cannot register
});

it("incident list: failed request shows the error and a retry", async () => {
  vi.spyOn(api, "incidents").mockRejectedValue(new ApiError(503, "service_unavailable", "database unavailable"));
  renderAs("operator", <Incidents />);
  expect(await screen.findByRole("alert")).toHaveTextContent("database unavailable");
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

it("incident list: permission denied state", async () => {
  vi.spyOn(api, "incidents").mockRejectedValue(new ApiError(403, "forbidden", "role viewer lacks permission"));
  renderAs("viewer", <Incidents />);
  expect(await screen.findByText(/Permission denied/)).toBeInTheDocument();
});

it("register form validates before calling the API", async () => {
  const userEvent = (await import("@testing-library/user-event")).default;
  vi.spyOn(api, "incidents").mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 });
  const register = vi.spyOn(api, "registerIncident");
  renderAs("operator", <Incidents />);
  await userEvent.click(await screen.findByText("Register an incident"));
  await userEvent.type(screen.getByLabelText("Title"), "abc");
  await userEvent.click(screen.getByRole("button", { name: "Register incident" }));
  expect(screen.getByText(/at least 5 characters/)).toBeInTheDocument();
  expect(register).not.toHaveBeenCalled();
});
