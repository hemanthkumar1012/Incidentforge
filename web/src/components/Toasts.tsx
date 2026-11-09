import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

type ToastKind = "ok" | "bad" | "info";
interface Toast { id: number; kind: ToastKind; text: string }
interface ToastApi { push: (kind: ToastKind, text: string) => void }

// Default is a no-op so components render in tests without a provider.
const ToastContext = createContext<ToastApi>({ push: () => {} });
const LIFETIME_MS = 6000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setToasts((all) => all.filter((t) => t.id !== id));
  }, []);

  const push = useCallback((kind: ToastKind, text: string) => {
    const id = nextId.current++;
    setToasts((all) => [...all.slice(-3), { id, kind, text }]);
    timers.current.set(id, setTimeout(() => dismiss(id), LIFETIME_MS));
  }, [dismiss]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  const api = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* Errors are announced assertively, everything else politely. Text only: never rendered as HTML. */}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`} role={t.kind === "bad" ? "alert" : "status"}>
            <span>{t.text}</span>
            <button aria-label="Dismiss notification" onClick={() => dismiss(t.id)}>×</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
