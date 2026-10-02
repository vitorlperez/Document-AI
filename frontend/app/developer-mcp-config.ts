/** Remote client examples are generated only from the backend's configured resource URL. */
export function mcpClientExamples(url: string | null) {
  if (!url) return null;
  const shellUrl = `'${url.replaceAll("'", "'\"'\"'")}'`;
  return {
    cursor: JSON.stringify({ mcpServers: { arquivio: { url } } }, null, 2),
    claudeCode: `claude mcp add --transport http arquivio ${shellUrl}`,
  };
}
