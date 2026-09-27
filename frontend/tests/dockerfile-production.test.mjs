import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const dockerfile = await readFile(new URL("../Dockerfile.production", import.meta.url), "utf8");
const runtimeStage = dockerfile.split("FROM node:22-bookworm-slim AS runtime\n")[1];

test("production image includes every file required by its startup command", () => {
  assert.ok(runtimeStage, "runtime stage is present");
  assert.match(
    runtimeStage,
    /COPY --from=build \/app\/scripts\/sites-env\.mjs \.\/scripts\/sites-env\.mjs/,
  );
  assert.match(runtimeStage, /CMD \["sh", "-c", "exec node --import \.\/scripts\/sites-env\.mjs/);
  assert.doesNotMatch(runtimeStage, /npm start/);
});
