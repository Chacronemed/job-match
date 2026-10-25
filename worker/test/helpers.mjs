// Test doubles for the Worker: D1 over node:sqlite running the real migration, an Access
// identity provider (RSA key, JWKS served through a mocked fetch) and request builders.
import { readdirSync, readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";

export const ORIGIN = "https://jm.example.com";
export const TEAM = "https://team.cloudflareaccess.com";
export const AUD = "test-aud-tag";

class FakeStatement {
  constructor(db, sql, params = []) {
    this.db = db;
    this.sql = sql;
    this.params = params;
  }
  bind(...params) {
    return new FakeStatement(this.db, this.sql, params);
  }
  async all() {
    return { results: this.db.prepare(this.sql).all(...this.params).map((r) => ({ ...r })) };
  }
  async first() {
    const row = this.db.prepare(this.sql).get(...this.params);
    return row ? { ...row } : null;
  }
  async run() {
    this.db.prepare(this.sql).run(...this.params);
    return { success: true };
  }
}

export function fakeD1() {
  const db = new DatabaseSync(":memory:");
  // Every migration in order, as `wrangler d1 migrations apply` runs them.
  const dir = new URL("../migrations/", import.meta.url);
  for (const name of readdirSync(dir).filter((f) => f.endsWith(".sql")).sort()) {
    db.exec(readFileSync(new URL(name, dir), "utf8"));
  }
  return { prepare: (sql) => new FakeStatement(db, sql), raw: db };
}

function b64url(bytes) {
  return Buffer.from(bytes).toString("base64url");
}

export async function identityProvider() {
  const pair = await crypto.subtle.generateKey(
    {
      name: "RSASSA-PKCS1-v1_5",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["sign", "verify"],
  );
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  const idp = {
    kid: "kid-1",
    jwksCalls: 0,
    jwksStatus: 200,
    keys() {
      return [{ kty: "RSA", kid: this.kid, alg: "RS256", n: jwk.n, e: jwk.e }];
    },
    async sign(claims = {}, header = {}) {
      const now = Math.floor(Date.now() / 1000);
      const h = { alg: "RS256", kid: idp.kid, typ: "JWT", ...header };
      const p = { aud: [AUD], iss: TEAM, exp: now + 600, iat: now, email: "me@example.com", ...claims };
      const enc = (o) => b64url(new TextEncoder().encode(JSON.stringify(o)));
      const input = `${enc(h)}.${enc(p)}`;
      const sig = await crypto.subtle.sign(
        "RSASSA-PKCS1-v1_5",
        pair.privateKey,
        new TextEncoder().encode(input),
      );
      return `${input}.${b64url(new Uint8Array(sig))}`;
    },
  };
  // Every other URL is refused, unless a test registers a handler in `idp.hosts` (the
  // AI tests mock api.anthropic.com this way).
  idp.hosts = {};
  globalThis.fetch = async (url, init) => {
    const u = String(url);
    if (u === `${TEAM}/cdn-cgi/access/certs`) {
      idp.jwksCalls += 1;
      return new Response(JSON.stringify({ keys: idp.keys() }), { status: idp.jwksStatus });
    }
    const handler = idp.hosts[new URL(u).host];
    if (!handler) throw new Error("unexpected fetch");
    return handler(u, init);
  };
  return idp;
}

// The assets binding serving a few JSON files, as the deployed site does.
export function fakeAssets(files = {}) {
  return {
    fetch: async (request) => {
      const path = new URL(request.url).pathname;
      if (!(path in files)) return new Response("not found", { status: 404 });
      return new Response(JSON.stringify(files[path]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
  };
}

export function env(db, overrides = {}) {
  return {
    DB: db,
    CF_ACCESS_AUD: AUD,
    CF_ACCESS_TEAM_DOMAIN: TEAM,
    ASSETS: { fetch: async () => new Response("asset") },
    ...overrides,
  };
}

export function request(path, { method = "GET", token, body, headers = {}, origin = ORIGIN } = {}) {
  const h = new Headers(headers);
  if (token) h.set("Cf-Access-Jwt-Assertion", token);
  if (origin !== null && method !== "GET" && !h.has("Origin")) h.set("Origin", origin);
  let payload;
  if (body !== undefined) {
    payload = typeof body === "string" ? body : JSON.stringify(body);
    if (!h.has("Content-Type")) h.set("Content-Type", "application/json");
  }
  return new Request(`${ORIGIN}${path}`, { method, headers: h, body: payload });
}
