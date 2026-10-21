// Local stand-in for the Cloudflare Access edge, for `wrangler dev` only. Never deployed.
//
//   node scripts/dev-access-proxy.mjs [--port 8790] [--upstream http://127.0.0.1:8787]
//
// It signs a short-lived RS256 JWT with a key generated at start-up, serves the matching
// JWKS at /cdn-cgi/access/certs (the Worker fetches it like the real team domain), and
// forwards every other request to `wrangler dev` with Cf-Access-Jwt-Assertion added, exactly
// what Access does in production. Point the Worker at it with a gitignored .dev.vars:
//
//   CF_ACCESS_AUD=dev-aud
//   CF_ACCESS_TEAM_DOMAIN=http://127.0.0.1:8790
//
// POST /__dev/fail-next makes the next /api/ write answer 500 (to check the page's error
// and revert path).
import { generateKeyPairSync, sign } from "node:crypto";
import http from "node:http";

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
};
const PORT = Number(opt("port", "8790"));
const UPSTREAM = new URL(opt("upstream", "http://127.0.0.1:8787"));
const ISSUER = `http://127.0.0.1:${PORT}`;
const AUD = "dev-aud";
const KID = "dev-key";

const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk = publicKey.export({ format: "jwk" });
let failNext = false;

const b64url = (buf) => Buffer.from(buf).toString("base64url");

function token() {
  const now = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: "RS256", kid: KID, typ: "JWT" }));
  const payload = b64url(JSON.stringify({ aud: [AUD], iss: ISSUER, iat: now, exp: now + 300, email: "dev@localhost" }));
  const sig = sign("RSA-SHA256", Buffer.from(`${header}.${payload}`), privateKey);
  return `${header}.${payload}.${b64url(sig)}`;
}

http.createServer((req, res) => {
  if (req.url === "/cdn-cgi/access/certs") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ keys: [{ ...jwk, kid: KID, alg: "RS256", use: "sig" }] }));
    return;
  }
  if (req.url === "/__dev/fail-next" && req.method === "POST") {
    failNext = true;
    res.writeHead(204);
    res.end();
    return;
  }
  if (failNext && req.url.startsWith("/api/") && req.method !== "GET") {
    failNext = false;
    req.resume();
    res.writeHead(500, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "internal error" }));
    return;
  }
  const headers = { ...req.headers, "cf-access-jwt-assertion": token() };
  const upstream = http.request(
    { hostname: UPSTREAM.hostname, port: UPSTREAM.port, path: req.url, method: req.method, headers },
    (up) => {
      res.writeHead(up.statusCode, up.headers);
      up.pipe(res);
    },
  );
  upstream.on("error", () => {
    res.writeHead(502);
    res.end("upstream unavailable");
  });
  req.pipe(upstream);
}).listen(PORT, "127.0.0.1", () => {
  console.log(`dev Access proxy on http://127.0.0.1:${PORT} -> ${UPSTREAM.origin}`);
});
