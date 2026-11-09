import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { Approval, Proposal, ValidationRun } from "../api/types";
import { ActionPanel } from "../pages/workspace/ActionPanel";
import { renderAs } from "./helpers";

afterEach(() => vi.restoreAllMocks());

const proposal: Proposal = {
  id: "prop_1", incident_id: "inc_1", investigation_id: "inv_1", action_type: "rollback_config_version", target: "checkout",
  parameters: { to_version: 1 }, expected_active_version: 2, status: "validated", created_at: "2026-11-08T10:00:00Z",
  expected_effect: [{ key: "payment_url", op: "changed", old: "http://payment:8020", new: "http://payment:8002" }], side_effects: [],
};
const passed: ValidationRun = { id: "val_1", proposal_id: "prop_1", status: "passed", production_version: 2, requested_by: "olivia",
  created_at: "2026-11-08T10:01:00Z", finished_at: "2026-11-08T10:02:00Z", report: { steps: [] } };
const pending: Approval = { id: "apr_1", proposal_id: "prop_1", validation_run_id: "val_1", binding_digest: "a".repeat(64), status: "pending",
  binding: { action_type: "rollback_config_version", target: "checkout", parameters: { to_version: 1 }, expected_active_version: 2 },
  requested_by: "olivia", requested_at: "2026-11-08T10:03:00Z", expires_at: "2026-11-08T10:18:00Z", decided_by: null, decided_at: null, note: null };

it("approver sees the exact action and the decision sends the reviewed digest", async () => {
  const decide = vi.spyOn(api, "decide").mockResolvedValue({ ...pending, status: "approved" });
  renderAs("approver", <ActionPanel proposal={proposal} validation={passed} approval={pending} recovery={undefined} onChange={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "Approve…" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText(/expecting production config v2/)).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
  expect(within(dialog).getByRole("alert")).toHaveTextContent(/note/);       // note is required
  expect(decide).not.toHaveBeenCalled();
  await userEvent.type(within(dialog).getByLabelText("Decision note"), "verified diff");
  await userEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
  expect(decide).toHaveBeenCalledWith("apr_1", true, "verified diff", "a".repeat(64));
});

it("requester cannot decide their own request", () => {
  renderAs("admin", <ActionPanel proposal={proposal} validation={passed} approval={pending} recovery={undefined} onChange={() => {}} />, "olivia");
  expect(screen.queryByRole("button", { name: "Approve…" })).not.toBeInTheDocument();
  expect(screen.getByText(/Waiting for a different approver/)).toBeInTheDocument();
});

it("failed validation blocks approval and execution", () => {
  renderAs("operator", <ActionPanel proposal={{ ...proposal, status: "validation_failed" }} validation={{ ...passed, status: "failed" }}
    approval={undefined} recovery={undefined} onChange={() => {}} />);
  expect(screen.getByText(/Execution is blocked/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Request approval" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Execute/ })).not.toBeInTheDocument();
});

it("not-reproducible validation is labelled unverified", () => {
  renderAs("operator", <ActionPanel proposal={{ ...proposal, status: "not_reproducible" }} validation={{ ...passed, status: "not_reproducible" }}
    approval={undefined} recovery={undefined} onChange={() => {}} />);
  expect(screen.getByText(/NOT verified/)).toBeInTheDocument();
});

it("execution shows the exact change and surfaces refusal reasons", async () => {
  vi.spyOn(api, "requestRecovery").mockRejectedValue(Object.assign(new (await import("../api/client")).ApiError(412, "precondition_failed",
    "production config moved", { reasons: ["v2 -> v3"] })));
  renderAs("operator", <ActionPanel proposal={proposal} validation={passed} approval={{ ...pending, status: "approved", decided_by: "arun" }}
    recovery={undefined} onChange={() => {}} />);
  await userEvent.click(screen.getByRole("button", { name: "Execute approved action" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("http://payment:8002")).toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: "Execute on production" }));
  expect(await screen.findByText(/production config moved \(v2 -> v3\)/)).toBeInTheDocument();
});

it("stale approval tells the operator to request a new one", () => {
  renderAs("operator", <ActionPanel proposal={proposal} validation={passed} approval={{ ...pending, status: "invalidated" }} recovery={undefined} onChange={() => {}} />);
  expect(screen.getByText(/Stale/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Request approval" })).toBeInTheDocument();
});

it("viewer gets no action buttons", () => {
  renderAs("viewer", <ActionPanel proposal={proposal} validation={passed} approval={undefined} recovery={undefined} onChange={() => {}} />);
  expect(screen.queryAllByRole("button").filter((b) => !b.closest("summary"))).toHaveLength(0);
});
