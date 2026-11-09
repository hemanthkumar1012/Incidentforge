import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, session } from "../api/client";

afterEach(() => { vi.restoreAllMocks(); session.set(null); });

describe("api client", () => {
  it("sends the bearer token and parses JSON", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ username: "olivia" }), { status: 200 }));
    session.set("tok123");
    await api.me();
    const headers = (fetchMock.mock.calls[0]![1] as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok123");
  });

  it("maps API errors to ApiError with code and details", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(
      { error: { code: "precondition_failed", message: "config moved", details: { reasons: ["moved"] } } }), { status: 412 }));
    await expect(api.requestRecovery("p1")).rejects.toMatchObject({ status: 412, code: "precondition_failed", details: { reasons: ["moved"] } });
  });

  it("clears the session and notifies on 401", async () => {
    const expired = vi.fn();
    session.onExpired(expired);
    session.set("old");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: { code: "unauthorized", message: "token expired" } }), { status: 401 }));
    await expect(api.overview()).rejects.toBeInstanceOf(ApiError);
    expect(expired).toHaveBeenCalled();
    expect(session.active).toBe(false);
  });

  it("reports network failures without inventing data", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(api.incidents({})).rejects.toMatchObject({ status: 0, code: "network_error" });
  });
});
