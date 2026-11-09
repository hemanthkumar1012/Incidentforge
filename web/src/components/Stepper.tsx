import type { Stage } from "../lib/workflow";

const MARK: Record<Stage["state"], string> = { done: "✓", current: "•", failed: "!", todo: "" };
const SR: Record<Stage["state"], string> = { done: "completed", current: "in progress or next", failed: "did not succeed", todo: "not started" };

export function Stepper({ stages }: { stages: Stage[] }) {
  return (
    <ol className="stepper" aria-label="Response progress">
      {stages.map((s, i) => (
        <li key={s.key} className={s.state} aria-current={s.state === "current" ? "step" : undefined}>
          <span className="step-dot" aria-hidden="true">{MARK[s.state] || i + 1}</span>
          <span>{s.label}<span className="sr-only"> — {SR[s.state]}</span></span>
        </li>
      ))}
    </ol>
  );
}
