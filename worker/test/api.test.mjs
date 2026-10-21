import assert from "node:assert/strict";
import { before, beforeEach, describe, test } from "node:test";

import { resetJwksCache } from "../src/auth.js";
import worker from "../src/index.js";
import { AUD, env, fakeD1, identityProvider, request, TEAM } from "./helpers.mjs";

const KEY = "france_travail:123ABCD";
const PATH = `/api/applications/${KEY}`;
const VALID = {
  status: "applied",
  applied_at: "2026-10-20",
  follow_up_at: "2026-10-27",
  note: "Called the recruiter",
  cv_url: "https://drive.example.com/cv.pdf",
};

let idp;
let db;
let token;

async function call(path, opts = {}, envOverrides = {}) {
  return worker.fetch(request(path, { token, ...opts }), env(db, envOverrides));
}

function rows(table) {
  return db.raw.prepare(`SELECT COUNT(*) AS n FROM ${table}`).get().n;
}

function assertNoCors(res) {
  for (const name of res.headers.keys()) {
    assert.ok(!name.toLowerCase().startsWith("access-control-"), `CORS header ${name}`);
  }
}

const b64json = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");

before(async () => {
  idp = await identityProvider(); // one RSA key per file: generating it is the slow part
});

beforeEach(async () => {
  resetJwksCache();
  idp.jwksCalls = 0;
  idp.jwksStatus = 200;
  db = fakeD1();
  token = await idp.sign();
});

describe("authentication", () => {
  test("no JWT -> 401", async () => {
    const res = await call("/api/applications", { token: null });
    assert.equal(res.status, 401);
    assertNoCors(res);
  });

  const bad = {
    "garbage token": async () => "not.a.jwt",
    "two segments": async () => "abc.def",
    "signature from another token": async () => {
      const other = await idp.sign({ email: "x@example.com" });
      const [h, p] = (await idp.sign()).split(".");
      return `${h}.${p}.${other.split(".")[2]}`;
    },
    "tampered payload": async () => {
      const [h, , s] = (await idp.sign()).split(".");
      return `${h}.${b64json({ aud: [AUD], iss: TEAM, exp: 9999999999 })}.${s}`;
    },
    "wrong audience": () => idp.sign({ aud: ["someone-else"] }),
    "wrong issuer": () => idp.sign({ iss: "https://evil.cloudflareaccess.com" }),
    expired: () => idp.sign({ exp: Math.floor(Date.now() / 1000) - 3600 }),
    "not yet valid": () => idp.sign({ nbf: Math.floor(Date.now() / 1000) + 3600 }),
    "alg none": async () => {
      const [, p] = (await idp.sign()).split(".");
      return `${b64json({ alg: "none", kid: "kid-1" })}.${p}.`;
    },
    "alg HS256": async () => {
      const [, p, s] = (await idp.sign()).split(".");
      return `${b64json({ alg: "HS256", kid: "kid-1" })}.${p}.${s}`;
    },
    "unknown kid": () => idp.sign({}, { kid: "kid-unknown" }),
  };
  for (const [name, make] of Object.entries(bad)) {
    test(`${name} -> 401`, async () => {
      const res = await call("/api/applications", { token: await make() });
      assert.equal(res.status, 401);
      assert.deepEqual(await res.json(), { error: "unauthenticated" });
    });
  }

  test("an invalid JWT never reaches D1", async () => {
    const bogus = await idp.sign({ aud: ["x"] });
    const res = await call(PATH, { method: "PUT", body: VALID, token: bogus });
    assert.equal(res.status, 401);
    assert.equal(rows("applications"), 0);
  });

  test("missing secrets -> 500, fail closed", async () => {
    for (const missing of ["CF_ACCESS_AUD", "CF_ACCESS_TEAM_DOMAIN"]) {
      const res = await call("/api/applications", {}, { [missing]: undefined });
      assert.equal(res.status, 500);
    }
  });

  test("JWKS unreachable -> 503", async () => {
    idp.jwksStatus = 500;
    assert.equal((await call("/api/applications")).status, 503);
  });

  test("JWKS is cached across calls", async () => {
    await call("/api/applications");
    await call("/api/applications");
    assert.equal(idp.jwksCalls, 1);
  });

  test("an unknown kid refetches at most once a minute", async () => {
    await call("/api/applications");
    const unknown = await idp.sign({}, { kid: "rotated" });
    await call("/api/applications", { token: unknown });
    await call("/api/applications", { token: unknown });
    assert.equal(idp.jwksCalls, 1);
  });

  test("team domain without scheme is accepted", async () => {
    const res = await call("/api/applications", {}, {
      CF_ACCESS_TEAM_DOMAIN: "team.cloudflareaccess.com",
    });
    assert.equal(res.status, 200);
  });
});

describe("origin", () => {
  test("foreign Origin on a write -> 403", async () => {
    const res = await call(PATH, { method: "PUT", body: VALID, origin: "https://evil.example" });
    assert.equal(res.status, 403);
    assertNoCors(res);
    assert.equal(rows("applications"), 0);
  });

  test("write without Origin -> 403", async () => {
    const res = await call(PATH, { method: "PUT", body: VALID, origin: null });
    assert.equal(res.status, 403);
  });

  test("foreign Origin on a read -> 403", async () => {
    const res = await call("/api/applications", { headers: { Origin: "https://evil.example" } });
    assert.equal(res.status, 403);
  });

  test("cross-site fetch metadata on a read -> 403", async () => {
    const res = await call("/api/applications", { headers: { "Sec-Fetch-Site": "cross-site" } });
    assert.equal(res.status, 403);
  });

  test("OPTIONS preflight gets no CORS answer", async () => {
    const res = await call("/api/applications", { method: "OPTIONS" });
    assert.equal(res.status, 405);
    assertNoCors(res);
  });
});

describe("validation", () => {
  const cases = {
    "unknown status": { ...VALID, status: "hired" },
    "missing status": { applied_at: "2026-10-20" },
    "impossible date": { ...VALID, applied_at: "2026-02-30" },
    "date with time": { ...VALID, follow_up_at: "2026-10-20T10:00:00Z" },
    "date as number": { ...VALID, applied_at: 20261020 },
    "note too long": { ...VALID, note: "x".repeat(2001) },
    "note not text": { ...VALID, note: ["a"] },
    "http cv_url": { ...VALID, cv_url: "http://drive.example.com/cv.pdf" },
    "javascript cv_url": { ...VALID, cv_url: "javascript:alert(1)" },
    "data cv_url": { ...VALID, cv_url: "data:text/html,<script>alert(1)</script>" },
    "cv_url with credentials": { ...VALID, cv_url: "https://user:pw@example.com/cv" },
    "cv_url too long": { ...VALID, cv_url: `https://example.com/${"a".repeat(500)}` },
    "unknown field": { ...VALID, updated_at: "2020-01-01" },
    "array body": [VALID],
  };
  for (const [name, body] of Object.entries(cases)) {
    test(`${name} -> 400`, async () => {
      const res = await call(PATH, { method: "PUT", body });
      assert.equal(res.status, 400);
      const { error } = await res.json();
      assert.match(error, /^[a-z_]+: /);
      assert.equal(rows("applications"), 0);
    });
  }

  test("note of exactly 2000 characters is accepted", async () => {
    const res = await call(PATH, { method: "PUT", body: { ...VALID, note: "é".repeat(2000) } });
    assert.equal(res.status, 200);
  });

  test("errors never echo the submitted value", async () => {
    const res = await call(PATH, {
      method: "PUT",
      body: { ...VALID, status: "<script>x</script>" },
    });
    assert.ok(!(await res.text()).includes("script"));
  });

  test("invalid job key in the path -> 400", async () => {
    const keys = ["nocolon", "FT:abc", "france_travail:a%20b", "france_travail:%3Cx%3E", "%E0%A4%A"];
    for (const key of keys) {
      const res = await call(`/api/applications/${key}`, { method: "PUT", body: VALID });
      assert.equal(res.status, 400, key);
    }
  });

  test("non-JSON content type -> 415", async () => {
    const res = await call(PATH, {
      method: "PUT",
      body: "status=applied",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    assert.equal(res.status, 415);
  });

  test("malformed JSON -> 400", async () => {
    assert.equal((await call(PATH, { method: "PUT", body: "{status:" })).status, 400);
  });

  test("oversize body -> 413", async () => {
    const body = JSON.stringify({ ...VALID, note: "x".repeat(9000) });
    assert.equal((await call(PATH, { method: "PUT", body })).status, 413);
  });

  test("decision rules", async () => {
    const bad = [
      { job_key: KEY, label: "great" },
      { job_key: "bad key", label: "good_fit" },
      { job_key: KEY, label: "good_fit", score_at_decision: 101 },
      { job_key: KEY, label: "good_fit", score_at_decision: 7.5 },
      { job_key: KEY, label: "good_fit", extra: 1 },
    ];
    for (const body of bad) {
      const res = await call("/api/decisions", { method: "POST", body });
      assert.equal(res.status, 400, JSON.stringify(body));
    }
    assert.equal(rows("decisions"), 0);
  });
});

describe("routes", () => {
  test("PUT then GET round trip, upsert keeps one row", async () => {
    let res = await call(PATH, { method: "PUT", body: VALID });
    assert.equal(res.status, 200);
    const { application } = await res.json();
    assert.equal(application.job_key, KEY);
    assert.equal(application.status, "applied");
    assert.match(application.updated_at, /^\d{4}-\d{2}-\d{2}T/);

    res = await call(PATH, { method: "PUT", body: { status: "interview", note: "" } });
    assert.equal(res.status, 200);
    res = await call("/api/applications");
    const body = await res.json();
    assert.equal(body.applications.length, 1);
    assert.equal(body.applications[0].status, "interview");
    assert.equal(body.applications[0].note, null);
    assert.equal(body.applications[0].cv_url, null);
    assert.equal(res.headers.get("Cache-Control"), "no-store");
    assert.equal(res.headers.get("X-Content-Type-Options"), "nosniff");
    assert.match(res.headers.get("Content-Type"), /^application\/json/);
    assertNoCors(res);
  });

  test("POST decision -> 201 and the latest label per job is listed", async () => {
    let res = await call("/api/decisions", {
      method: "POST",
      body: { job_key: KEY, label: "too_senior", score_at_decision: 64 },
    });
    assert.equal(res.status, 201);
    assert.equal((await res.json()).decision.label, "too_senior");
    await call("/api/decisions", {
      method: "POST",
      body: { job_key: KEY, label: "good_fit", score_at_decision: null },
    });
    res = await call("/api/applications");
    const labels = (await res.json()).decisions.map((d) => [d.job_key, d.label]);
    assert.deepEqual(labels, [[KEY, "good_fit"]]);
    assert.equal(rows("decisions"), 2);
  });

  test("wrong methods and unknown routes", async () => {
    assert.equal((await call("/api/applications", { method: "DELETE" })).status, 405);
    assert.equal((await call(PATH)).status, 405);
    assert.equal((await call("/api/decisions")).status, 405);
    assert.equal((await call("/api/other")).status, 404);
  });

  test("non-API paths go to the static assets", async () => {
    const res = await worker.fetch(new Request("https://jm.example.com/index.html"), env(db));
    assert.equal(await res.text(), "asset");
  });

  test("a D1 failure answers 500 without detail", async () => {
    const broken = {
      prepare() {
        throw new Error("D1 exploded with note=secret");
      },
    };
    const res = await worker.fetch(request("/api/applications", { token }), env(broken));
    assert.equal(res.status, 500);
    assert.ok(!(await res.text()).includes("secret"));
  });
});

describe("skill overrides", () => {
  const SKILL = "/api/skill-overrides/gitlab%20ci";

  test("PUT is idempotent, GET lists it, DELETE undoes it", async () => {
    let res = await call(SKILL, { method: "PUT" });
    assert.equal(res.status, 200);
    const first = (await res.json()).skill_override;
    assert.equal(first.skill, "gitlab ci");
    res = await call(SKILL, { method: "PUT" });
    assert.equal((await res.json()).skill_override.created_at, first.created_at);
    assert.equal(rows("skill_overrides"), 1);

    res = await call("/api/applications");
    assert.deepEqual((await res.json()).skill_overrides, [first]);

    res = await call(SKILL, { method: "DELETE" });
    assert.equal(res.status, 200);
    assert.equal(rows("skill_overrides"), 0);
    assert.equal((await call(SKILL, { method: "DELETE" })).status, 200);
  });

  test("needs a JWT and a same-origin write", async () => {
    const anon = await worker.fetch(request(SKILL, { method: "PUT" }), env(db));
    assert.equal(anon.status, 401);
    const foreign = await call(SKILL, { method: "PUT", origin: "https://evil.example" });
    assert.equal(foreign.status, 403);
    assertNoCors(foreign);
    assert.equal((await call(SKILL, { method: "DELETE", origin: null })).status, 403);
    assert.equal(rows("skill_overrides"), 0);
  });

  test("an invalid name -> 400 and is never echoed", async () => {
    const names = ["Helm", "%3Cscript%3E", "a".repeat(41), "", "-helm", "helm%0A", "%E0%A4%A"];
    for (const name of names) {
      const res = await call(`/api/skill-overrides/${name}`, { method: "PUT" });
      assert.equal(res.status, 400, name);
      assert.ok(!(await res.text()).includes("script"));
    }
    assert.equal(rows("skill_overrides"), 0);
  });

  test("a name of exactly 40 characters is accepted, other methods are not", async () => {
    assert.equal((await call(`/api/skill-overrides/${"a".repeat(40)}`, { method: "PUT" })).status, 200);
    assert.equal((await call(SKILL)).status, 405);
    assert.equal((await call(SKILL, { method: "POST", body: {} })).status, 405);
  });
});

describe("decision undo", () => {
  async function decide(label) {
    const res = await call("/api/decisions", { method: "POST", body: { job_key: KEY, label, score_at_decision: 70 } });
    return res;
  }

  test("the location verdict is accepted (migration 0003)", async () => {
    const res = await decide("location");
    assert.equal(res.status, 201);
    assert.equal((await res.json()).decision.label, "location");
  });

  test("DELETE removes one decision; an unknown id is 404", async () => {
    const id = (await (await decide("good_fit")).json()).decision.id;
    let res = await call(`/api/decisions/${id}`, { method: "DELETE" });
    assert.equal(res.status, 200);
    assert.equal((await res.json()).deleted, id);
    assert.equal(rows("decisions"), 0);
    res = await call(`/api/decisions/${id}`, { method: "DELETE" });
    assert.equal(res.status, 404);
  });

  test("a bad id is 400, a foreign origin 403, another method 405", async () => {
    for (const bad of ["0", "-1", "abc", "1.5", "99999999999999999"]) {
      assert.equal((await call(`/api/decisions/${bad}`, { method: "DELETE" })).status, 400, bad);
    }
    const id = (await (await decide("good_fit")).json()).decision.id;
    const foreign = await call(`/api/decisions/${id}`, { method: "DELETE", origin: "https://evil.example" });
    assert.equal(foreign.status, 403);
    assert.equal(rows("decisions"), 1);
    assert.equal((await call(`/api/decisions/${id}`)).status, 405);
  });
});
