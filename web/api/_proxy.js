// Runtime reverse proxy from the Vercel-hosted SPA to the forge-api.
// vercel.json rewrites cannot read environment variables, so the API origin is
// resolved here at request time from API_ORIGIN. Only /api/ paths are forwarded.

const HOP_BY_HOP = new Set([
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
  "trailer", "transfer-encoding", "upgrade", "host", "content-length",
  "x-forwarded-host", "x-forwarded-for", "x-forwarded-proto", "x-real-ip",
]);
const MAX_BODY_BYTES = 256 * 1024;
const TIMEOUT_MS = 25_000;

function problem(status, code, message, extra = {}) {
  return new Response(JSON.stringify({ error: { code, message, details: {} } }), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store", ...extra },
  });
}

export function resolveOrigin(raw, env = "production") {
  if (!raw) return null;
  let url;
  try { url = new URL(raw); } catch { return null; }
  if (url.search || url.hash || (url.pathname !== "/" && url.pathname !== "")) return null;
  if (url.protocol !== "https:" && !(env !== "production" && url.protocol === "http:")) return null;
  return url.origin;
}

export async function proxy(request, { origin: rawOrigin, env, fetchImpl = fetch } = {}) {
  const origin = resolveOrigin(rawOrigin, env);
  if (!origin) return problem(503, "proxy_misconfigured", "API origin is not configured");

  const incoming = new URL(request.url);
  if (!incoming.pathname.startsWith("/api/") || incoming.pathname.includes("..")) {
    return problem(404, "not_found", "not found");
  }

  const headers = new Headers();
  for (const [k, v] of request.headers) if (!HOP_BY_HOP.has(k.toLowerCase())) headers.set(k, v);

  let body;
  if (request.method !== "GET" && request.method !== "HEAD") {
    const buf = await request.arrayBuffer();
    if (buf.byteLength > MAX_BODY_BYTES) return problem(413, "payload_too_large", "request body too large");
    body = buf;
  }

  try {
    const upstream = await fetchImpl(origin + incoming.pathname + incoming.search, {
      method: request.method,
      headers,
      body,
      redirect: "manual",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (upstream.status >= 300 && upstream.status < 400) {
      return problem(502, "bad_gateway", "upstream returned an unexpected redirect");
    }
    const out = new Headers();
    for (const [k, v] of upstream.headers) {
      if (!HOP_BY_HOP.has(k.toLowerCase()) && k.toLowerCase() !== "content-encoding") out.set(k, v);
    }
    return new Response(upstream.body, { status: upstream.status, headers: out });
  } catch {
    return problem(502, "bad_gateway", "the IncidentForge API is unreachable");
  }
}
