import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const screen = readFileSync(new URL("../app/product/developer-screen.tsx", import.meta.url), "utf8");

test("API keys and MCP panels sit in one grid: 1 column below lg, 2 columns from lg", () => {
  const wrapper = screen.match(/<div data-testid="developer-panels" className="([^"]*)">([\s\S]*?)<\/div>\s*<\/Enter>/);
  assert.ok(wrapper, "missing developer-panels wrapper");
  assert.match(wrapper[1], /\bgrid-cols-1\b/);
  assert.match(wrapper[1], /\blg:grid-cols-2\b/);
  assert.match(wrapper[1], /\bitems-stretch\b/);
  assert.match(wrapper[1], /\[&>section\]:mt-0/);
  assert.ok(wrapper[2].indexOf("<AccessSettings") < wrapper[2].indexOf("<McpSettings"), "keys left, MCP right");
});

test("MCP panel has no nested multi-column grids that would crush a half-width card", () => {
  const mcp = screen.slice(screen.indexOf('aria-labelledby="mcp-title"'), screen.indexOf('aria-labelledby="api-docs-title"'));
  assert.doesNotMatch(mcp, /grid[^"]*lg:grid-cols-2/);
});
