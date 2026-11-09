import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { proxy, resolveOrigin } from "./_proxy.js";

function upstream(handler) {
  return new Promise((resolve) => {
    const seen = [];
    const server = http.createServer(async (req, res) => {
      const chunks = [];
      for await (const c of req) chunks.push(c);
      seen.push({ url: req.url, method: req.method, headers: req.headers, body: Buffer.concat(chunks).toString() });
      handler(req, res);
    });
    server.listen(0, "127.0.0.1", () => resolve({ server, seen, origin: `http://127.0.0.1:${server.address().port}` }));
  });
}
const req = (path, init) => new Request(`https://app.example.com${path}`, init);

test("resolveOrigin requires https in production and a bare origin", () => {
  assert.equal(resolveOrigin("https://api.example.com", "production"), "https://api.example.com");
  assert.equal(resolveOrigin("http://api.example.com", "production"), null);
  assert.equal(resolveOrigin("http://localhost:8000", "preview"), "http://localhost:8000");
  assert.equal(resolveOrigin("https://api.example.com/v1", "production"), null);
  assert.equal(resolveOrigin("https://api.example.com?x=1", "production"), null);
  assert.equal(resolveOrigin("", "production"), null);
  assert.equal(resolveOrigin("not a url", "production"), null);
});

test("503 when the origin is not configured", async () => {
  const r = await proxy(req("/api/me"), { origin: undefined, env: "production" });
  assert.equal(r.status, 503);
  assert.equal((await r.json()).error.code, "proxy_misconfigured");
});

test("forwards path, query, method, body and auth; drops hop-by-hop headers", async () => {
  const u = await upstream((_, res) => { res.writeHead(201, { "content-type": "application/json", "x-extra": "1" }); res.end('{"ok":true}'); });
  try {
    const r = await proxy(
      req("/api/incidents?status=open", { method: "POST", body: '{"a":1}', headers: { authorization: "Bearer t", "content-type": "application/json", connection: "keep-alive", "x-forwarded-for": "9.9.9.9" } }),
      { origin: u.origin, env: "preview" },
    );
    assert.equal(r.status, 201);
    assert.deepEqual(await r.json(), { ok: true });
    const s = u.seen[0];
    assert.equal(s.url, "/api/incidents?status=open");
    assert.equal(s.method, "POST");
    assert.equal(s.body, '{"a":1}');
    assert.equal(s.headers.authorization, "Bearer t");
    assert.notEqual(s.headers["x-forwarded-for"], "9.9.9.9");
  } finally { u.server.close(); }
});

test("passes upstream error status and body through", async () => {
  const u = await upstream((_, res) => { res.writeHead(401, { "content-type": "application/json" }); res.end('{"error":{"code":"unauthorized"}}'); });
  try {
    const r = await proxy(req("/api/me"), { origin: u.origin, env: "preview" });
    assert.equal(r.status, 401);
    assert.equal((await r.json()).error.code, "unauthorized");
  } finally { u.server.close(); }
});

test("refuses non-/api paths and traversal without contacting upstream", async () => {
  const u = await upstream((_, res) => res.end("x"));
  try {
    assert.equal((await proxy(req("/admin"), { origin: u.origin, env: "preview" })).status, 404);
    assert.equal((await proxy(req("/api/../admin"), { origin: u.origin, env: "preview" })).status, 404);
    assert.equal(u.seen.length, 0);
  } finally { u.server.close(); }
});

test("upstream redirects are not followed", async () => {
  const u = await upstream((_, res) => { res.writeHead(302, { location: "http://evil.example/" }); res.end(); });
  try {
    const r = await proxy(req("/api/me"), { origin: u.origin, env: "preview" });
    assert.equal(r.status, 502);
    assert.equal(r.headers.get("location"), null);
  } finally { u.server.close(); }
});

test("oversized bodies are rejected with 413", async () => {
  const u = await upstream((_, res) => res.end("x"));
  try {
    const r = await proxy(req("/api/auth/login", { method: "POST", body: "x".repeat(300 * 1024) }), { origin: u.origin, env: "preview" });
    assert.equal(r.status, 413);
    assert.equal(u.seen.length, 0);
  } finally { u.server.close(); }
});

test("unreachable upstream yields a generic 502 with no internals", async () => {
  const r = await proxy(req("/api/me"), { origin: "http://127.0.0.1:1", env: "preview" });
  assert.equal(r.status, 502);
  const text = await r.text();
  assert.ok(!text.includes("127.0.0.1"));
});
