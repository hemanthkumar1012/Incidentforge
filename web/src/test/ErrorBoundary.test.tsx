import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { titleFor } from "../hooks/useRouteAnnouncer";

function Bomb({ explode }: { explode: boolean }) {
  if (explode) throw new Error("boom <script>x</script>");
  return <p>fine</p>;
}

function Harness() {
  const [explode, setExplode] = useState(true);
  return <ErrorBoundary onReset={() => setExplode(false)}><Bomb explode={explode} /></ErrorBoundary>;
}

describe("ErrorBoundary", () => {
  it("shows the error as text, then recovers when reset", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<Harness />);
    expect(screen.getByRole("alert")).toHaveTextContent("boom <script>x</script>");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("fine")).toBeInTheDocument();
  });
});

describe("titleFor", () => {
  it("names each route and falls back for unknown paths", () => {
    expect(titleFor("/")).toBe("Overview");
    expect(titleFor("/incidents")).toBe("Incidents");
    expect(titleFor("/incidents/abc")).toBe("Incident");
    expect(titleFor("/nope")).toBe("Not found");
  });
});
