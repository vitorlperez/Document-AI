import assert from "node:assert/strict";
import test from "node:test";
import { errorDetail } from "../app/api-error-detail.ts";

const FALLBACK = "Não foi possível concluir esta ação.";

test("a plain string detail is shown as is", () => {
  assert.equal(errorDetail({ detail: "Lista fora da seleção." }), "Lista fora da seleção.");
});

test("a FastAPI validation list becomes a readable sentence with the field, not the generic fallback", () => {
  const body = { detail: [{ type: "missing", loc: ["header", "Idempotency-Key"], msg: "Field required", input: null }] };
  const text = errorDetail(body);
  assert.notEqual(text, FALLBACK);
  assert.match(text, /Idempotency-Key/);
  assert.match(text, /Field required/);
});

test("body fields are named without the transport prefix and several problems are joined", () => {
  const text = errorDetail({ detail: [
    { loc: ["body", "due_date"], msg: "Input should be a valid date" },
    { loc: ["body", "priority"], msg: "Input should be less than or equal to 4" },
  ] });
  assert.match(text, /due_date: Input should be a valid date/);
  assert.match(text, /priority: Input should be less than or equal to 4/);
  assert.doesNotMatch(text, /body/);
});

test("unknown shapes fall back to the generic text", () => {
  assert.equal(errorDetail(null), FALLBACK);
  assert.equal(errorDetail({}), FALLBACK);
  assert.equal(errorDetail({ detail: [] }), FALLBACK);
  assert.equal(errorDetail({ detail: 5 }), FALLBACK);
});
