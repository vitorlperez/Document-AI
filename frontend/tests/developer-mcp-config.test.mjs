import assert from "node:assert/strict";
import test from "node:test";
import { mcpClientExamples } from "../app/developer-mcp-config.ts";

test("MCP examples use the configured URL including custom paths", () => {
  const url = "https://mcp.example.test/custom/mcp";
  const examples = mcpClientExamples(url);
  assert.equal(JSON.parse(examples.cursor).mcpServers.arquivio.url, url);
  assert.equal(examples.claudeCode, `claude mcp add --transport http arquivio '${url}'`);
});

test("no URL means no invented client configuration", () => {
  assert.equal(mcpClientExamples(null), null);
  assert.equal(mcpClientExamples(""), null);
});

test("Claude Code example shell-quotes URL characters", () => {
  const examples = mcpClientExamples("https://mcp.example.test/a'b?x=$(echo unsafe)");
  assert.equal(examples.claudeCode, "claude mcp add --transport http arquivio 'https://mcp.example.test/a'\"'\"'b?x=$(echo unsafe)'");
});
