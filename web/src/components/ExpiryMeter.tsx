import { useEffect, useState } from "react";
import { countdown } from "../lib/countdown";

// Live countdown to an approval's expiry. Ticks once a second; the timer stops once expired.
export function ExpiryMeter({ requestedAt, expiresAt }: { requestedAt: string; expiresAt: string }) {
  const [now, setNow] = useState(() => Date.now());
  const c = countdown(requestedAt, expiresAt, now);
  const expired = c?.state === "expired";
  useEffect(() => {
    if (expired) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [expired]);
  if (!c) return null;
  return (
    <span className={`expiry ${c.state}`} role="timer" aria-label={`Approval ${c.label}`}>
      <span className="expiry-track" aria-hidden="true"><span className="expiry-fill" style={{ width: `${c.fractionLeft * 100}%` }} /></span>
      <span>{c.label}</span>
    </span>
  );
}
