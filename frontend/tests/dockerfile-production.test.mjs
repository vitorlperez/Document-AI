import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const dockerfile = await readFile(new URL("../Dockerfile.production", import.meta.url), "utf8");
const runtimeStage = dockerfile.split("FROM node:22-bookworm-slim AS runtime\n")[1];

test("production image starts the lightweight Node server, not the wrangler dev runtime", () => {
  assert.ok(runtimeStage, "runtime stage is present");
  assert.match(
    runtimeStage,
    /CMD \["sh", "-c", "exec node \.\/node_modules\/vinext\/dist\/cli\.js start --port \$\{PORT:-3000\}"\]/,
  );
  assert.doesNotMatch(runtimeStage, /wrangler/);
  assert.doesNotMatch(runtimeStage, /npm start/);
});
