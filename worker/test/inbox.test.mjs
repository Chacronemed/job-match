// ADR 0018: the recruiter inbox. A service token on two routes, idempotence by message_id,
// the confidence threshold, the daily cap, the usage row, and a log that never carries the
// email. The Claude API is a double registered on idp.hosts (as in ai.test.mjs).
import assert from "node:assert/strict";
import { before, beforeEach, describe, test } from "node:test";

import { principalOf, resetJwksCache } from "../src/auth.js";
import worker from "../src/index.js";
import { CONFIDENCE_THRESHOLD, INBOX_MODEL, INBOX_SCHEMA, listFollowupsDue, validateInboxVerdict } from "../src/inbox.js";
import { validateInboxAction, validateInboxMessage } from "../src/validate.js";
import { env, fakeAssets, fakeD1, identityProvider, request } from "./helpers.mjs";

// An Access service token's common_name is its Client ID, "<32 hex>.access", not its name.
const CN = "3f2a9c0e1b4d5e6f7a8b9c0d1e2f3a4b.access";
const KEY_A = "france_travail:A1";
const KEY_B = "france_travail:B2";
const DATA = {
  jobs: [{ key: KEY_A, title: "Ingénieur DevOps", company: "Acme", url: "https://acme.example/jobs/1" }],
  tracked: [{ key: KEY_B, title: "SRE", company: "Globex", url: "https://globex.example/jobs/2" }],
};
// Trap values: none of them may show in a log line.
const TEXT = "Bonjour SECRET_BODY_TRAP, nous vous proposons un entretien le 12 novembre 2026 à 10h.";
const SUBJECT = "SECRET_SUBJECT_TRAP Entretien Acme";
const FROM = "Jane Recruiter <jane.secret@acme.example>";
const MSG = { message_id: "<msg-1@acme.example>", from: FROM, subject: SUBJECT, date: "2026-11-02T09:00:00Z", text: TEXT };

function verdict(type, confidence, key = KEY_A, interview_at = "2026-11-12") {
  return { type, confidence, interview_at, application_key: key, reason: "Entretien proposé par Acme." };
}

function anthropic(answers) {
  const calls = [];
  const handler = async (url, init) => {
    calls.push({ url, init, body: JSON.parse(init.body) });
    const next = answers.length ? answers.shift() : verdict("entretien", 0.95);
    if (next instanceof Error) throw next;
    if (next && typeof next.status === "number") return new Response(JSON.stringify(next.body || {}), { status: next.status });
    const text = typeof next === "string" ? next : JSON.stringify(next);
    return new Response(
      JSON.stringify({ content: [{ type: "text", text }], stop_reason: "end_turn", usage: { input_tokens: 900, cache_read_input_tokens: 600, output_tokens: 60 } }),
      { status: 200 },
    );
  };
  return { calls, handler };
}

let idp;
let db;
let userToken;
let serviceToken;
let logged;
const realLog = console.log;

before(async () => {
  idp = await identityProvider();
});

beforeEach(async () => {
  resetJwksCache();
  idp.hosts = {};
  db = fakeD1();
  userToken = await idp.sign();
  serviceToken = await idp.sign({ common_name: CN, email: undefined, sub: "" });
  logged = [];
  console.log = (...args) => logged.push(args.map(String).join(" "));
  db.raw.exec(
    `INSERT INTO applications (job_key, status, applied_at, follow_up_at, updated_at) VALUES
      ('${KEY_A}', 'applied', '2026-10-20', '2026-10-27', '2026-10-20T08:00:00Z'),
      ('${KEY_B}', 'applied', '2026-10-25', '2026-12-01', '2026-10-25T08:00:00Z'),
      ('france_travail:C3', 'interview', '2026-10-01', '2026-10-08', '2026-10-01T08:00:00Z')`,
  );
});

function inboxEnv(overrides = {}) {
  return env(db, { ASSETS: fakeAssets({ "/data.json": DATA }), ANTHROPIC_API_KEY: "sk-ant-test-secret", ACCESS_SERVICE_CN: CN, ...overrides });
}

async function post(body = MSG, opts = {}, overrides = {}) {
  const res = await worker.fetch(request("/api/inbox", { method: "POST", token: serviceToken, origin: null, body, ...opts }), inboxEnv(overrides));
  return { res, body: await res.json() };
}

function app(key) {
  return { ...db.raw.prepare("SELECT status, interview_at, follow_up_at FROM applications WHERE job_key = ?").get(key) };
}

function item(id) {
  return db.raw.prepare("SELECT * FROM inbox_items WHERE message_id = ?").get(id);
}

describe("service token", () => {
  test("principalOf: a login is a user, the named token a service, anything else nothing", () => {
    assert.deepEqual(principalOf({ email: "me@example.com" }, {}), { kind: "user", email: "me@example.com" });
    assert.deepEqual(principalOf({ common_name: CN }, { ACCESS_SERVICE_CN: CN }), { kind: "service", cn: CN });
    assert.equal(principalOf({ common_name: "other.access" }, { ACCESS_SERVICE_CN: CN }), null);
    assert.equal(principalOf({ common_name: "n8n-inbox" }, { ACCESS_SERVICE_CN: CN }), null); // the token's name is not its id
    assert.equal(principalOf({ common_name: CN }, {}), null);
    assert.equal(principalOf({}, { ACCESS_SERVICE_CN: CN }), null);
  });

  test("the named token posts to /api/inbox without an Origin and reads the due follow-ups", async () => {
    idp.hosts["api.anthropic.com"] = anthropic([]).handler;
    const { res } = await post();
    assert.equal(res.status, 201);
    const due = await worker.fetch(request("/api/followups/due", { token: serviceToken }), inboxEnv());
    assert.equal(due.status, 200);
  });

  test("the named token is refused everywhere else", async () => {
    for (const [path, method] of [["/api/applications", "GET"], [`/api/inbox/${encodeURIComponent("<x@y>")}`, "PUT"], ["/api/ai/run", "POST"]]) {
      const res = await worker.fetch(request(path, { method, token: serviceToken, origin: null, body: method === "GET" ? undefined : {} }), inboxEnv());
      assert.equal(res.status, 403, path);
      assert.deepEqual(await res.json(), { error: "service token: route not allowed" });
    }
  });

  test("another Client ID, or no ACCESS_SERVICE_CN secret at all -> 401 and nothing stored", async () => {
    const other = await idp.sign({ common_name: "ffffffffffffffffffffffffffffffff.access", email: undefined });
    let res = await worker.fetch(request("/api/inbox", { method: "POST", token: other, origin: null, body: MSG }), inboxEnv());
    assert.equal(res.status, 401);
    res = await worker.fetch(request("/api/inbox", { method: "POST", token: serviceToken, origin: null, body: MSG }), inboxEnv({ ACCESS_SERVICE_CN: undefined }));
    assert.equal(res.status, 401);
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM inbox_items").get().n, 0);
  });

  test("my login still works everywhere, and still needs a same-origin write", async () => {
    idp.hosts["api.anthropic.com"] = anthropic([]).handler;
    let res = await worker.fetch(request("/api/inbox", { method: "POST", token: userToken, body: MSG }), inboxEnv());
    assert.equal(res.status, 201);
    res = await worker.fetch(request("/api/inbox", { method: "POST", token: userToken, origin: null, body: { ...MSG, message_id: "<m2@x>" } }), inboxEnv());
    assert.equal(res.status, 403);
    res = await worker.fetch(request("/api/applications", { token: userToken }), inboxEnv());
    assert.equal(res.status, 200);
  });
});

describe("POST /api/inbox", () => {
  test("a sure interview updates the application, with its date, and the item is applied", async () => {
    const api = anthropic([verdict("entretien", 0.92)]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const { res, body } = await post();
    assert.equal(res.status, 201);
    assert.deepEqual(body, { message_id: MSG.message_id, state: "applied", kind: "entretien", confidence: 0.92, proposed_key: KEY_A, ai: "ok" });
    assert.deepEqual(app(KEY_A), { status: "interview", interview_at: "2026-11-12", follow_up_at: null });
    const row = item(MSG.message_id);
    assert.equal(row.applied_key, KEY_A);
    assert.equal(row.sender_domain, "acme.example");
    assert.equal(row.subject, SUBJECT);
    assert.ok(!JSON.stringify(row).includes("SECRET_BODY_TRAP"), "the body is never stored");
    assert.ok(!JSON.stringify(row).includes("jane.secret"), "the address is never stored");
    // The request: Haiku, strict schema, the candidates (keys, companies, titles) in a cached
    // system block, the email text cut and wrapped.
    const sent = api.calls[0].body;
    assert.equal(sent.model, INBOX_MODEL);
    assert.deepEqual(sent.output_config, { effort: "low", format: { type: "json_schema", schema: INBOX_SCHEMA } });
    assert.equal(sent.system[0].cache_control.type, "ephemeral");
    assert.ok(sent.system[0].text.includes(KEY_A) && sent.system[0].text.includes("Globex"));
    assert.ok(!sent.system[0].text.includes("C3"), "only sent applications are candidates");
    assert.ok(sent.messages[0].content.includes("<email domaine=\"acme.example\""));
    assert.ok(sent.messages[0].content.includes(TEXT));
  });

  test("a sure refusal moves the application to rejected", async () => {
    idp.hosts["api.anthropic.com"] = anthropic([verdict("refus", 0.9, KEY_B, null)]).handler;
    const { body } = await post();
    assert.equal(body.state, "applied");
    assert.deepEqual(app(KEY_B), { status: "rejected", interview_at: null, follow_up_at: null });
  });

  test("under the threshold, or a kind that is not entretien/refus, waits for me", async () => {
    idp.hosts["api.anthropic.com"] = anthropic([verdict("entretien", CONFIDENCE_THRESHOLD - 0.01), verdict("accuse_reception", 0.99)]).handler;
    let out = await post();
    assert.equal(out.body.state, "to_confirm");
    assert.equal(out.body.kind, "entretien");
    out = await post({ ...MSG, message_id: "<m2@acme.example>" });
    assert.equal(out.body.state, "to_confirm");
    assert.equal(out.body.kind, "accuse_reception");
    assert.equal(app(KEY_A).status, "applied");
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM inbox_items WHERE state = 'to_confirm'").get().n, 2);
  });

  test("exactly the threshold applies; a sure verdict without a key does not", async () => {
    idp.hosts["api.anthropic.com"] = anthropic([verdict("entretien", CONFIDENCE_THRESHOLD, null), verdict("refus", CONFIDENCE_THRESHOLD, KEY_A, null)]).handler;
    let out = await post();
    assert.equal(out.body.state, "to_confirm");
    out = await post({ ...MSG, message_id: "<m2@acme.example>" });
    assert.equal(out.body.state, "applied");
    assert.equal(app(KEY_A).status, "rejected");
  });

  test("idempotent by message_id: the second post makes no call and answers 200", async () => {
    const api = anthropic([verdict("entretien", 0.95)]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const first = await post();
    const again = await post({ ...MSG, text: "another body" });
    assert.equal(first.res.status, 201);
    assert.equal(again.res.status, 200);
    assert.equal(again.body.duplicate, true);
    assert.equal(again.body.state, "applied");
    assert.equal(api.calls.length, 1);
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM inbox_items").get().n, 1);
  });

  test("the text is cut to 4 000 characters before the model", async () => {
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const long = "x".repeat(10000);
    const { res } = await post({ ...MSG, text: long });
    assert.equal(res.status, 201);
    const content = api.calls[0].body.messages[0].content;
    assert.ok(content.includes("x".repeat(4000)) && !content.includes("x".repeat(4001)));
  });

  test("an unknown key or a bad date from the model is invalid: parked, billed", async () => {
    idp.hosts["api.anthropic.com"] = anthropic([verdict("entretien", 0.99, "france_travail:ZZZ"), verdict("entretien", 0.99, KEY_A, "12 novembre")]).handler;
    let out = await post();
    assert.equal(out.body.state, "to_confirm");
    assert.equal(out.body.ai, "invalid");
    out = await post({ ...MSG, message_id: "<m2@acme.example>" });
    assert.equal(out.body.ai, "invalid");
    assert.equal(app(KEY_A).status, "applied");
    const usage = db.raw.prepare("SELECT calls FROM ai_usage WHERE model = ?").get(INBOX_MODEL);
    assert.equal(usage.calls, 2);
  });

  test("validateInboxVerdict refuses extra keys and bad shapes", () => {
    assert.equal(validateInboxVerdict({ ...verdict("refus", 0.5), extra: 1 }, [KEY_A]), null);
    assert.equal(validateInboxVerdict(verdict("maybe", 0.5), [KEY_A]), null);
    assert.equal(validateInboxVerdict(verdict("refus", 1.5), [KEY_A]), null);
    assert.deepEqual(validateInboxVerdict(verdict("refus", 0.5, null, null), []), { type: "refus", confidence: 0.5, application_key: null, interview_at: null });
  });

  test("the daily cap: over it the email is parked without a call, nothing lost", async () => {
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    const first = await post(MSG, {}, { AI_INBOX_DAILY_LIMIT: "1" });
    const second = await post({ ...MSG, message_id: "<m2@acme.example>" }, {}, { AI_INBOX_DAILY_LIMIT: "1" });
    assert.equal(first.body.ai, "ok");
    assert.equal(second.body.state, "to_confirm");
    assert.equal(second.body.ai, "skipped_cap");
    assert.equal(api.calls.length, 1);
    assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM inbox_items").get().n, 2);
  });

  test("usage is counted in ai_usage under the Haiku model, billed answers only", async () => {
    idp.hosts["api.anthropic.com"] = anthropic([verdict("entretien", 0.95), { status: 500 }, { status: 402 }]).handler;
    await post();
    const err = await post({ ...MSG, message_id: "<m2@acme.example>" });
    const credit = await post({ ...MSG, message_id: "<m3@acme.example>" });
    assert.equal(err.body.ai, "error");
    assert.equal(credit.body.ai, "credit");
    assert.equal(err.body.state, "to_confirm");
    const usage = { ...db.raw.prepare("SELECT calls, tokens_in, tokens_out FROM ai_usage WHERE provider = 'anthropic' AND model = ?").get(INBOX_MODEL) };
    assert.deepEqual(usage, { calls: 1, tokens_in: 1500, tokens_out: 60 });
  });

  test("no sent application, or no API key: parked without a call", async () => {
    const api = anthropic([]);
    idp.hosts["api.anthropic.com"] = api.handler;
    let out = await post(MSG, {}, { ANTHROPIC_API_KEY: undefined });
    assert.equal(out.body.ai, "no_key");
    db.raw.exec("UPDATE applications SET status = 'interview'");
    out = await post({ ...MSG, message_id: "<m2@acme.example>" });
    assert.equal(out.body.ai, "skipped_none");
    assert.equal(api.calls.length, 0);
  });

  test("the log never carries the text, the subject, the sender, the id or the key", async () => {
    idp.hosts["api.anthropic.com"] = anthropic([verdict("entretien", 0.95)]).handler;
    await post();
    assert.equal(logged.length, 1);
    assert.equal(logged[0], "inbox applied kind=entretien ai=ok");
    for (const trap of ["SECRET_BODY_TRAP", "SECRET_SUBJECT_TRAP", "jane", "acme", "msg-1", KEY_A]) {
      assert.ok(!logged.join("\n").includes(trap), trap);
    }
    const src = await import("node:fs").then((fs) => fs.readFileSync(new URL("../src/inbox.js", import.meta.url), "utf8"));
    assert.ok(!src.includes("console."), "inbox.js never logs");
  });

  test("validation: unknown field, bad id, non-string text; errors never echo", async () => {
    for (const [body, error] of [
      [{ ...MSG, extra: 1 }, "body: unknown field"],
      [{ ...MSG, message_id: "has space" }, "message_id: invalid"],
      [{ ...MSG, text: 42 }, "text: must be text"],
      [{ ...MSG, date: "yesterday" }, "date: must be an ISO date"],
    ]) {
      const { res, body: out } = await post(body);
      assert.equal(res.status, 400);
      assert.equal(out.error, error);
    }
    assert.equal(validateInboxMessage({ message_id: "a", text: "t", from: "Someone <x@Ex.Com>" }).value.sender_domain, "ex.com");
    assert.equal(validateInboxMessage({ message_id: "a", text: "t" }).value.sender_domain, null);
    const big = await post({ ...MSG, text: "x".repeat(70 * 1024) });
    assert.equal(big.res.status, 413);
  });

  test("GET on /api/inbox is 405", async () => {
    const res = await worker.fetch(request("/api/inbox", { token: serviceToken }), inboxEnv());
    assert.equal(res.status, 405);
  });

  test("the user's GET /api/applications carries the inbox and interview_at", async () => {
    idp.hosts["api.anthropic.com"] = anthropic([verdict("entretien", 0.5)]).handler;
    await post();
    const res = await worker.fetch(request("/api/applications", { token: userToken }), inboxEnv());
    const body = await res.json();
    assert.equal(body.inbox.to_confirm.length, 1);
    assert.equal(body.inbox.history.length, 0);
    assert.ok(!JSON.stringify(body.inbox).includes("SECRET_BODY_TRAP"));
    assert.ok("interview_at" in body.applications[0]);
  });
});

describe("PUT /api/inbox/:id (Valider / Corriger / Ignorer)", () => {
  const id = encodeURIComponent(MSG.message_id);
  async function act(body, messageId = id) {
    const res = await worker.fetch(request(`/api/inbox/${messageId}`, { method: "PUT", token: userToken, body }), inboxEnv());
    return { res, body: await res.json() };
  }

  beforeEach(async () => {
    idp.hosts["api.anthropic.com"] = anthropic([verdict("entretien", 0.6)]).handler;
    await post();
  });

  test("confirm applies the proposed verdict and returns the application", async () => {
    const { res, body } = await act({ action: "confirm" });
    assert.equal(res.status, 200);
    assert.equal(body.item.state, "applied");
    assert.equal(body.item.applied_key, KEY_A);
    assert.equal(body.application.status, "interview");
    assert.equal(body.application.interview_at, "2026-11-12");
  });

  test("correct re-targets the reply: another application, another kind, a date", async () => {
    const { res, body } = await act({ action: "correct", application_key: KEY_B, kind: "refus", interview_at: null });
    assert.equal(res.status, 200);
    assert.equal(body.item.state, "corrected");
    assert.equal(body.item.kind, "refus");
    assert.equal(app(KEY_B).status, "rejected");
    assert.equal(app(KEY_A).status, "applied");
  });

  test("correct to a kind that changes nothing leaves the applications as they are", async () => {
    const { body } = await act({ action: "correct", application_key: KEY_A, kind: "accuse_reception" });
    assert.equal(body.item.state, "corrected");
    assert.equal(body.application, null);
    assert.equal(app(KEY_A).status, "applied");
  });

  test("ignore archives the item untouched", async () => {
    const { body } = await act({ action: "ignore" });
    assert.equal(body.item.state, "ignored");
    assert.equal(body.item.applied_key, null);
    assert.equal(app(KEY_A).status, "applied");
  });

  test("404 unknown, 409 already handled, 400 bad action or correct without a key", async () => {
    assert.equal((await act({ action: "ignore" }, encodeURIComponent("<nope@x>"))).res.status, 404);
    await act({ action: "ignore" });
    assert.equal((await act({ action: "confirm" })).res.status, 409);
    assert.equal((await act({ action: "delete" })).res.status, 400);
    assert.equal((await act({ action: "correct", kind: "refus" })).res.status, 400);
    assert.deepEqual(validateInboxAction({ action: "correct", kind: "refus" }), { error: "correct: needs application_key and kind" });
  });

  test("a service token may not act on items; a foreign origin neither", async () => {
    let res = await worker.fetch(request(`/api/inbox/${id}`, { method: "PUT", token: serviceToken, origin: null, body: { action: "ignore" } }), inboxEnv());
    assert.equal(res.status, 403);
    res = await worker.fetch(request(`/api/inbox/${id}`, { method: "PUT", token: userToken, origin: "https://evil.example", body: { action: "ignore" } }), inboxEnv());
    assert.equal(res.status, 403);
  });
});

describe("GET /api/followups/due", () => {
  test("sent applications due today or before, oldest first, with the offer when known", async () => {
    db.raw.exec(`INSERT INTO applications (job_key, status, applied_at, follow_up_at, updated_at) VALUES ('adzuna:gone', 'applied', '2026-10-01', '2026-10-05', '2026-10-01T08:00:00Z')`);
    const due = await listFollowupsDue(db, DATA, "2026-11-02");
    assert.deepEqual(due, [
      { key: "adzuna:gone", title: null, company: null, url: null, applied_at: "2026-10-01", follow_up_at: "2026-10-05" },
      { key: KEY_A, title: "Ingénieur DevOps", company: "Acme", url: "https://acme.example/jobs/1", applied_at: "2026-10-20", follow_up_at: "2026-10-27" },
    ]);
    // KEY_B is due in December, C3 is an interview: neither is listed.
  });

  test("the route answers {today, due} and refuses other methods", async () => {
    const res = await worker.fetch(request("/api/followups/due", { token: serviceToken }), inboxEnv());
    const body = await res.json();
    assert.match(body.today, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(Array.isArray(body.due));
    assert.equal((await worker.fetch(request("/api/followups/due", { method: "POST", token: userToken, body: {} }), inboxEnv())).status, 405);
  });
});

describe("PUT /api/applications/:key", () => {
  test("accepts and returns interview_at", async () => {
    const res = await worker.fetch(
      request(`/api/applications/${KEY_A}`, { method: "PUT", token: userToken, body: { status: "interview", interview_at: "2026-11-15" } }),
      inboxEnv(),
    );
    assert.equal(res.status, 200);
    assert.equal((await res.json()).application.interview_at, "2026-11-15");
    const bad = await worker.fetch(
      request(`/api/applications/${KEY_A}`, { method: "PUT", token: userToken, body: { status: "interview", interview_at: "15/11/2026" } }),
      inboxEnv(),
    );
    assert.equal(bad.status, 400);
  });
});

process.on("exit", () => {
  console.log = realLog;
});
