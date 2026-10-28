import assert from "node:assert/strict";
import test from "node:test";

import { forwardedRequestHeaders } from "../app/api/proxy-headers.mjs";

test("forwards cookie mutation origin signals required by the backend gate", () => {
  const forwarded = forwardedRequestHeaders(new Headers({
    cookie: "document_intelligence_session=opaque",
    origin: "https://app.example.test",
    "sec-fetch-site": "same-origin",
    "content-type": "application/json",
    "user-agent": "auth-browser-test",
  }));

  assert.equal(forwarded.get("origin"), "https://app.example.test");
  assert.equal(forwarded.get("sec-fetch-site"), "same-origin");
  assert.equal(forwarded.get("cookie"), "document_intelligence_session=opaque");
  assert.equal(forwarded.get("user-agent"), "auth-browser-test");
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

const proxyOptions = {
  ipSource: "railway", secret: "test-only-proxy-secret-at-least-32-chars",
  method: "POST", path: "/auth/password", now: 1700000000,
};

test("signs only the explicitly trusted ingress IP and discards forged context", () => {
  const headers = forwardedRequestHeaders(new Headers({
    "x-real-ip": "198.51.100.10",
    "x-forwarded-for": "203.0.113.66",
    "x-auth-client-ip": "203.0.113.66",
    "x-auth-ip-signature": "forged",
  }), proxyOptions);
  assert.equal(headers.get("x-auth-client-ip"), "198.51.100.10");
  assert.match(headers.get("x-auth-ip-signature"), /^[a-f0-9]{64}$/);
  assert.equal(headers.get("x-forwarded-for"), null);
});

test("does not trust forwarding headers without an ingress contract", () => {
  const headers = forwardedRequestHeaders(new Headers({ "x-real-ip": "198.51.100.10" }));
  assert.equal(headers.get("x-auth-client-ip"), null);
  assert.throws(() => forwardedRequestHeaders(new Headers(), proxyOptions), /IP/);
  assert.throws(() => forwardedRequestHeaders(new Headers({"x-real-ip": "a, b"}), proxyOptions), /IP/);
});

test("only auth routes require signed IP context; session and API stay available", () => {
  for (const path of ["/me", "/session", "/health/ready", "/organizations", "/authenticators"]) {
    const headers = forwardedRequestHeaders(new Headers({
      cookie: "opaque-session", "x-auth-client-ip": "203.0.113.66",
      "x-auth-ip-signature": "forged", "x-auth-ip-timestamp": "1",
    }), { ...proxyOptions, path });
    assert.equal(headers.get("cookie"), "opaque-session");
    for (const name of ["x-auth-client-ip", "x-auth-ip-signature", "x-auth-ip-timestamp"]) {
      assert.equal(headers.get(name), null);
    }
    assert.doesNotThrow(() => forwardedRequestHeaders(new Headers(), { ...proxyOptions, path, secret: undefined }));
  }
  assert.throws(() => forwardedRequestHeaders(new Headers(), proxyOptions), /IP/);
});

test("forwards the Idempotency-Key header the ClickUp task endpoint requires (without it the API answers 422)", () => {
  const forwarded = forwardedRequestHeaders(new Headers({ "idempotency-key": "0f8fad5b-d9cb-469f-a165-70867728950e", "content-type": "application/json" }));
  assert.equal(forwarded.get("idempotency-key"), "0f8fad5b-d9cb-469f-a165-70867728950e");
});

test("forwards the Stripe-Signature header so a proxied billing webhook can be verified by the API", () => {
  const signature = "t=1700000000,v1=5257a869e7ecebeda32affa62cdca3fa51cad7e77a0e56ff536d0ce8e108d8bd";
  const forwarded = forwardedRequestHeaders(new Headers({ "stripe-signature": signature, "content-type": "application/json" }));
  assert.equal(forwarded.get("stripe-signature"), signature);
});
