import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { codeSample, endpointsFrom } from "../app/docs/api/api-docs-logic.ts";

const spec = JSON.parse(readFileSync(new URL("../../docs/api/openapi-v1.json", import.meta.url), "utf8"));
const endpoints = endpointsFrom(spec);

test("the five public endpoints are listed in reading order with their scope", () => {
  assert.deepEqual(endpoints.map((e) => `${e.method} ${e.path}`), [
    "GET /v1/whoami", "GET /v1/sources", "POST /v1/search", "GET /v1/documents/{document_id}", "POST /v1/ask",
  ]);
  assert.deepEqual(endpoints.map((e) => e.scope), [null, "search:read", "search:read", "documents:read", "ask:run"]);
});

test("request bodies and path parameters come from the schema", () => {
  const search = endpoints.find((e) => e.path === "/v1/search");
  assert.deepEqual(search.body.map((f) => [f.name, f.required]), [["limit", false], ["node_ids", false], ["query", true], ["space_ids", false]]);
  assert.match(search.body.find((f) => f.name === "query").constraints, /1–500 caracteres/);
  assert.equal(search.body.find((f) => f.name === "node_ids").type, "string (uuid)[]");
  const document = endpoints.find((e) => e.path.startsWith("/v1/documents"));
  assert.equal(document.params[0].location, "path");
});

test("code samples keep the key as a placeholder and the contract's URL", () => {
  const search = endpoints.find((e) => e.path === "/v1/search");
  const curl = codeSample(search, "curl");
  assert.match(curl, /-X POST "https:\/\/api\.arquivio\.com\.br\/v1\/search"/);
  assert.match(curl, /Bearer \$KEY/);
  assert.match(curl, /'\{"query":"Aurora","limit":10\}'/);
  assert.match(codeSample(search, "python"), /json=\{"query": "Aurora", "limit": 10\}/);
  const document = endpoints.find((e) => e.path.startsWith("/v1/documents"));
  assert.match(codeSample(document, "javascript"), /\$\{documentId\}/);
  assert.match(codeSample(document, "python"), /f"https:\/\/api\.arquivio\.com\.br\/v1\/documents\/\{document_id\}"/);
});

test("an unexpected document yields no endpoints instead of throwing", () => {
  assert.deepEqual(endpointsFrom({}), []);
});

test("the public contract documents Spaces: space_ids narrows, spaces label results", () => {
  const search = endpoints.find((e) => e.path === "/v1/search");
  assert.equal(search.body.find((f) => f.name === "space_ids").type, "string (uuid)[]");
  const ask = endpoints.find((e) => e.path === "/v1/ask");
  assert.ok(ask.body.some((f) => f.name === "space_ids"));
  const page = readFileSync(new URL("../app/docs/api/page.tsx", import.meta.url), "utf8");
  assert.match(page, /id="espacos"/);
  assert.match(page, /space_ids/);
  assert.match(page, /interseção/);
  assert.match(page, /404/);
});
