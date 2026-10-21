// Cloudflare Access JWT verification (Cf-Access-Jwt-Assertion), with the team's JWKS cached
// per isolate. Fail closed: anything unexpected is "not authenticated".

const JWKS_TTL_MS = 60 * 60 * 1000;
const REFETCH_MIN_MS = 60 * 1000; // an unknown kid refetches at most once a minute
const SKEW_S = 60;
const MAX_TOKEN = 8192;

export class JwksUnavailable extends Error {}

let cache = { team: null, keys: new Map(), fetchedAt: 0 };

export function resetJwksCache() {
  cache = { team: null, keys: new Map(), fetchedAt: 0 };
}

// "team.cloudflareaccess.com" or "https://team.cloudflareaccess.com/" -> "https://team..."
export function teamOrigin(domain) {
  const withScheme = /^https?:\/\//.test(domain) ? domain : `https://${domain}`;
  return withScheme.replace(/\/+$/, "");
}

function b64urlBytes(part) {
  const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

function b64urlJson(part) {
  return JSON.parse(new TextDecoder().decode(b64urlBytes(part)));
}

async function fetchKeys(team) {
  let res;
  try {
    res = await fetch(`${team}/cdn-cgi/access/certs`);
  } catch {
    throw new JwksUnavailable();
  }
  if (!res.ok) throw new JwksUnavailable();
  const body = await res.json().catch(() => null);
  const keys = new Map();
  for (const jwk of (body && Array.isArray(body.keys)) ? body.keys : []) {
    if (jwk.kty !== "RSA" || !jwk.kid || (jwk.alg && jwk.alg !== "RS256")) continue;
    try {
      const key = await crypto.subtle.importKey(
        "jwk",
        { kty: "RSA", n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
        { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
        false,
        ["verify"],
      );
      keys.set(jwk.kid, key);
    } catch {
      // a malformed key is skipped, the others still work
    }
  }
  return keys;
}

async function keyFor(team, kid, now) {
  const fresh = cache.team === team && now - cache.fetchedAt < JWKS_TTL_MS;
  if (fresh && cache.keys.has(kid)) return cache.keys.get(kid);
  if (fresh && now - cache.fetchedAt < REFETCH_MIN_MS) return null; // rotated? not yet
  cache = { team, keys: await fetchKeys(team), fetchedAt: now };
  return cache.keys.get(kid) || null;
}

// Returns the payload when the token is valid for this application, null otherwise.
// Throws JwksUnavailable when the keys cannot be fetched (the caller answers 503).
export async function verifyAccessJwt(token, { aud, teamDomain }, now = Date.now()) {
  if (typeof token !== "string" || token.length > MAX_TOKEN) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  let header, payload, signature;
  try {
    header = b64urlJson(parts[0]);
    payload = b64urlJson(parts[1]);
    signature = b64urlBytes(parts[2]);
  } catch {
    return null;
  }
  if (!header || header.alg !== "RS256" || typeof header.kid !== "string") return null;
  if (!payload || typeof payload !== "object") return null;

  const team = teamOrigin(teamDomain);
  const key = await keyFor(team, header.kid, now);
  if (!key) return null;
  const signed = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, signature, signed);
  if (!ok) return null;

  const audiences = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!audiences.includes(aud)) return null;
  if (payload.iss !== team) return null;
  const nowS = Math.floor(now / 1000);
  if (typeof payload.exp !== "number" || payload.exp + SKEW_S < nowS) return null;
  if (typeof payload.nbf === "number" && payload.nbf - SKEW_S > nowS) return null;
  return payload;
}
