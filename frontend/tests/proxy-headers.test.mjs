import assert from "node:assert/strict";
import test from "node:test";

import { forwardedRequestHeaders } from "../app/api/proxy-headers.mjs";

test("forwards cookie mutation origin signals required by the backend gate", () => {
  const forwarded = forwardedRequestHeaders(new Headers({
    cookie: "document_intelligence_session=opaque",
    origin: "https://app.example.test",
    "sec-fetch-site": "same-origin",
    "content-type": "application/json",
  }));

  assert.equal(forwarded.get("origin"), "https://app.example.test");
  assert.equal(forwarded.get("sec-fetch-site"), "same-origin");
  assert.equal(forwarded.get("cookie"), "document_intelligence_session=opaque");
});

test("does not forward browser-controlled routing or hop-by-hop headers", () => {
  const forwarded = forwardedRequestHeaders(new Headers({
    host: "evil.example.test",
    connection: "keep-alive",
    "x-forwarded-host": "evil.example.test",
    "x-request-id": "request-1",
  }));

  assert.equal(forwarded.get("host"), null);
  assert.equal(forwarded.get("connection"), null);
  assert.equal(forwarded.get("x-forwarded-host"), null);
  assert.equal(forwarded.get("x-request-id"), "request-1");
});
