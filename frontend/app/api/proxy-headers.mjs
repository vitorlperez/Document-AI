const FORWARDED_REQUEST_HEADERS = [
  "accept",
  "content-type",
  "cookie",
  "authorization",
  "origin",
  "sec-fetch-site",
  "x-request-id",
];

/** Keep the proxy allowlist narrow while preserving the backend's CSRF signals. */
export function forwardedRequestHeaders(incoming) {
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = incoming.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}
