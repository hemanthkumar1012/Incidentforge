import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

const TITLES: [RegExp, string][] = [
  [/^\/$/, "Overview"], [/^\/incidents\/[^/]+/, "Incident"], [/^\/incidents/, "Incidents"],
  [/^\/approvals/, "Approvals"], [/^\/evaluation/, "Evaluation"],
];

export function titleFor(pathname: string): string {
  return TITLES.find(([re]) => re.test(pathname))?.[1] ?? "Not found";
}

// Single-page navigation does not move focus or announce anything on its own. On each route change this sets the
// document title, moves focus to the main region (skipped on first load), and returns text for a polite live region.
export function useRouteAnnouncer(): string {
  const { pathname } = useLocation();
  const [message, setMessage] = useState("");
  const [first, setFirst] = useState(true);
  useEffect(() => {
    const title = titleFor(pathname);
    document.title = `${title} · IncidentForge`;
    setMessage(`${title} page`);
    if (!first) document.getElementById("main")?.focus();
    setFirst(false);
    // `first` is intentionally read but not a trigger: only a pathname change should refocus.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);
  return message;
}
