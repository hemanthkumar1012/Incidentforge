import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { rankCommands, type Command } from "../lib/palette";

const SEARCH_DELAY_MS = 250;
const MIN_SEARCH_CHARS = 2;

// Ctrl/Cmd+K palette: static commands plus a live incident search against the API.
// Incident titles are rendered as text only. A failed search simply shows no incident results.
export function CommandPalette({ open, onClose, commands }: { open: boolean; onClose: () => void; commands: Command[] }) {
  const ref = useRef<HTMLDialogElement>(null);
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const [incidents, setIncidents] = useState<Command[]>([]);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) { setQuery(""); setIndex(0); setIncidents([]); d.showModal?.(); }
    if (!open && d.open) d.close?.();
  }, [open]);

  useEffect(() => {
    const text = query.trim();
    if (!open || text.length < MIN_SEARCH_CHARS) { setIncidents([]); return; }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api.incidents({ q: text, sort: "created_at", order: "desc" }, controller.signal)
        .then((page) => setIncidents(page.items.slice(0, 6).map((i) => ({
          id: `incident-${i.id}`, label: i.title, group: "Incidents", hint: `${i.severity} · ${i.status.replaceAll("_", " ")}`,
          run: () => navigate(`/incidents/${i.id}`),
        }))))
        .catch(() => { if (!controller.signal.aborted) setIncidents([]); });
    }, SEARCH_DELAY_MS);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, open, navigate]);

  const results = useMemo(() => [...rankCommands(commands, query), ...incidents], [commands, query, incidents]);
  const active = Math.min(index, Math.max(results.length - 1, 0));

  function choose(c: Command | undefined) {
    if (!c) return;
    onClose();
    c.run();
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setIndex((active + 1) % Math.max(results.length, 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIndex((active - 1 + results.length) % Math.max(results.length, 1)); }
    else if (e.key === "Enter") { e.preventDefault(); choose(results[active]); }
  }

  if (!open) return null;
  return (
    <dialog ref={ref} className="palette" aria-label="Command palette" onCancel={(e) => { e.preventDefault(); onClose(); }}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <input role="combobox" aria-expanded="true" aria-controls="palette-list" aria-activedescendant={results[active] ? `palette-${results[active]!.id}` : undefined}
        aria-label="Search commands and incidents" placeholder="Type a command or search incidents…" autoFocus value={query}
        onChange={(e) => { setQuery(e.target.value); setIndex(0); }} onKeyDown={onKey} />
      <ul id="palette-list" role="listbox" aria-label="Results">
        {results.length === 0 && <li className="palette-empty" role="presentation">No matches.</li>}
        {results.map((c, i) => (
          <li key={c.id} id={`palette-${c.id}`} role="option" aria-selected={i === active} className={i === active ? "active" : undefined}
            onMouseEnter={() => setIndex(i)} onClick={() => choose(c)}>
            <span className="palette-group">{c.group}</span><span className="palette-label">{c.label}</span>
            {c.hint && <kbd>{c.hint}</kbd>}
          </li>
        ))}
      </ul>
    </dialog>
  );
}
