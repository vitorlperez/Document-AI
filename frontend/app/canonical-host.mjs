/** Canonical public host: the apex serves the same app but the API trusts only PUBLIC_APP_URL (www) as Origin. */
export const CANONICAL_ORIGIN = "https://www.arquivio.com.br";
export const APEX_HOST = "arquivio.com.br";

/**
 * next.config `redirects()` rule: apex → www, keeping path and query (308 keeps the method).
 * @type {Awaited<ReturnType<NonNullable<import("next").NextConfig["redirects"]>>>}
 */
export const apexToWwwRedirects = [
  { source: "/:path*", has: [{ type: /** @type {"host"} */ ("host"), value: APEX_HOST }], destination: `${CANONICAL_ORIGIN}/:path*`, permanent: true },
];
