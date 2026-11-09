import type { KeyboardEvent } from "react";

export interface TabSpec { id: string; label: string; count?: number }

// WAI-ARIA tabs with automatic activation: arrow keys, Home and End move between tabs.
// The caller renders the matching panel with role="tabpanel", id=`${idPrefix}-panel`, aria-labelledby=`${idPrefix}-${active}`.
export function Tabs({ tabs, active, onChange, idPrefix, label }: {
  tabs: TabSpec[]; active: string; onChange: (id: string) => void; idPrefix: string; label: string;
}) {
  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const i = tabs.findIndex((t) => t.id === active);
    const target = e.key === "ArrowRight" ? (i + 1) % tabs.length : e.key === "ArrowLeft" ? (i - 1 + tabs.length) % tabs.length
      : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : -1;
    if (target < 0) return;
    e.preventDefault();
    onChange(tabs[target]!.id);
    document.getElementById(`${idPrefix}-${tabs[target]!.id}`)?.focus();
  }
  return (
    <div className="tabs" role="tablist" aria-label={label} onKeyDown={onKey}>
      {tabs.map((t) => (
        <button key={t.id} id={`${idPrefix}-${t.id}`} role="tab" className="tab" aria-selected={t.id === active}
          aria-controls={`${idPrefix}-panel`} tabIndex={t.id === active ? 0 : -1} onClick={() => onChange(t.id)}>
          {t.label}{t.count !== undefined && <span className="tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}
