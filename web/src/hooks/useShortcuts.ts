import { useEffect, useRef } from "react";

export interface Shortcut {
  keys: string;            // "g o" = press g, then o within a second; "?" = single key
  description: string;
  run: () => void;
}

const SEQUENCE_WINDOW_MS = 1000;

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

// Global single-key and two-key shortcuts. Ignored while typing in a field and when a modifier is held,
// so they never collide with browser shortcuts or text entry.
export function useShortcuts(shortcuts: Shortcut[]): void {
  const list = useRef(shortcuts);
  list.current = shortcuts;
  useEffect(() => {
    let pending: string | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const reset = () => { pending = null; clearTimeout(timer); };

    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      const typed = pending ? `${pending} ${key}` : key;
      const exact = list.current.find((s) => s.keys === typed);
      if (exact) { e.preventDefault(); reset(); exact.run(); return; }
      if (!pending && list.current.some((s) => s.keys.startsWith(`${key} `))) {
        pending = key;
        timer = setTimeout(reset, SEQUENCE_WINDOW_MS);
        return;
      }
      reset();
    }
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); reset(); };
  }, []);
}
