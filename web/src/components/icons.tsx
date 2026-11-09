import type { ReactElement } from "react";

// Small inline icon set (stroke icons, 24x24 grid) so the app ships no icon font and no extra dependency.
// Icons are decorative: the visible label next to them carries the meaning.
const PATHS: Record<string, ReactElement> = {
  overview: <><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></>,
  incidents: <><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" /></>,
  approvals: <><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></>,
  metrics: <><path d="M3 12h4l3-8 4 16 3-8h4" /></>,
  evaluation: <><path d="M3 3v18h18" /><path d="M7 15l4-5 3 3 5-7" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />,
  collapse: <><path d="M15 18l-6-6 6-6" /></>,
  expand: <><path d="M9 18l6-6-6-6" /></>,
  logout: <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5M21 12H9" /></>,
};

export type IconName = keyof typeof PATHS;

export function Icon({ name }: { name: IconName }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">{PATHS[name]}</svg>;
}
