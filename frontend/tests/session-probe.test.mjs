import assert from "node:assert/strict";
import test from "node:test";

import { sessionProbeResponse } from "../app/api/proxy-headers.mjs";

test("normalizes only the expected anonymous /me response", async () => {
  const response = await sessionProbeResponse(new Response('{"detail":"authentication required"}', { status: 401 }));

  assert.equal(response.status, 200);
  assert.equal(await response.json(), null);
});

test("preserves real session probe failures", async () => {
  const response = await sessionProbeResponse(new Response('{"detail":"unavailable"}', { status: 503 }));

  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { detail: "unavailable" });
});
