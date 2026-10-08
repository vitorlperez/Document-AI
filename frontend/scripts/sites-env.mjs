import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const runtimeRoot = process.env.SITES_RUNTIME_ROOT || path.join(projectRoot, ".sites-runtime");

// Wrangler needs server environment as bindings. Use a private dotenv file so
// proxy credentials are hidden secret_text bindings, never CLI --var values.
const authSettings = ["AUTH_CLIENT_IP_SOURCE", "AUTH_PROXY_SECRET"]
  .filter((name) => process.env[name]);
if (authSettings.length) {
  mkdirSync(runtimeRoot, { recursive: true });
  const privateDirectory = mkdtempSync(path.join(runtimeRoot, "auth-proxy-"));
  const envFile = path.join(privateDirectory, ".env");
  writeFileSync(envFile, authSettings.map((name) => `${name}=${JSON.stringify(process.env[name])}`).join("\n") + "\n", { mode: 0o600 });
  process.argv.push("--env-file", envFile);
  process.on("exit", () => rmSync(privateDirectory, { recursive: true, force: true }));
}

process.env.CLOUDFLARE_CF_FETCH_ENABLED ||= "false";
process.env.WRANGLER_SEND_METRICS ||= "false";
process.env.WRANGLER_WRITE_LOGS ||= "false";
process.env.WRANGLER_LOG_PATH ||= path.join(runtimeRoot, "wrangler/logs");
process.env.WRANGLER_REGISTRY_PATH ||= path.join(runtimeRoot, "wrangler/dev-registry");
process.env.MINIFLARE_REGISTRY_PATH ||= path.join(runtimeRoot, "wrangler/registry");

// Wrangler exposes runtime configuration to the Vinext Worker as bindings.
// Preserve an explicit CLI --var; otherwise bridge the server-only process
// variable without baking it into the client bundle.
if (
  process.env.API_UPSTREAM_URL &&
  !process.argv.some((argument, index) => argument === "--var" && process.argv[index + 1]?.startsWith("API_UPSTREAM_URL:"))
) {
  process.argv.push("--var", `API_UPSTREAM_URL:${process.env.API_UPSTREAM_URL}`);
}

process.chdir(projectRoot);
for (const directory of [
  path.dirname(process.env.WRANGLER_LOG_PATH),
  process.env.WRANGLER_REGISTRY_PATH,
  process.env.MINIFLARE_REGISTRY_PATH,
]) {
  mkdirSync(directory, { recursive: true });
}
