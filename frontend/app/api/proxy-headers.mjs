import { createHmac } from "node:crypto";
import { isIP } from "node:net";

const FORWARDED_REQUEST_HEADERS = [
  "accept",
  "content-type",
  "cookie",
  "authorization",
  "origin",
  "sec-fetch-site",
  "user-agent",
  "x-request-id",
];

/** Keep the proxy allowlist narrow while preserving the backend's CSRF signals. */
export function forwardedRequestHeaders(incoming, options = {}) {
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = incoming.get(name);
    if (value) headers.set(name, value);
  }
  // Opt-in contract: this server is reachable ONLY through a Railway edge
  // that overwrites X-Real-IP. No XFF chain or caller-supplied signature is used.
  if (options.path?.startsWith("/auth/") && options.ipSource) {
    if (options.ipSource !== "railway" || !options.secret || options.secret.length < 32) {
      throw new Error("Trusted IP ingress is not configured");
    }
    const ip = incoming.get("x-real-ip")?.trim();
    if (!ip || !isIP(ip)) throw new Error("Trusted ingress IP is missing or invalid");
    const timestamp = String(options.now ?? Math.floor(Date.now() / 1000));
    const message = `${timestamp}\n${options.method}\n${options.path}\n${ip}`;
    headers.set("x-auth-client-ip", ip);
    headers.set("x-auth-ip-timestamp", timestamp);
    headers.set("x-auth-ip-signature", createHmac("sha256", options.secret).update(message).digest("hex"));
  }
  return headers;
}

/** A missing anonymous session is data for the public landing, not an error. */
export async function sessionProbeResponse(response) {
  if (response.status !== 401) return response;
  await response.body?.cancel();
  return Response.json(null, {
    status: 200,
    headers: { "cache-control": "no-store" },
  });
}
