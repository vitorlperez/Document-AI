import type { NextRequest } from "next/server";
import { forwardedRequestHeaders, sessionProbeResponse } from "../proxy-headers.mjs";

export const dynamic = "force-dynamic";

async function proxy(request: NextRequest): Promise<Response> {
  const configuredUpstream = process.env.API_UPSTREAM_URL;
  if (!configuredUpstream) {
    return new Response("API upstream is not configured", { status: 503 });
  }

  let upstream: URL;
  try {
    upstream = new URL(configuredUpstream);
    if (!["http:", "https:"].includes(upstream.protocol) || upstream.username || upstream.password) {
      throw new Error("Invalid API upstream");
    }
  } catch {
    return new Response("API upstream is invalid", { status: 503 });
  }

  const incoming = new URL(request.url);
  const sessionProbe = incoming.pathname === "/api/session";
  upstream.pathname = sessionProbe ? "/me" : incoming.pathname.slice("/api".length);
  upstream.search = incoming.search;

  let headers: Headers;
  try {
    headers = forwardedRequestHeaders(request.headers, {
      ipSource: process.env.AUTH_CLIENT_IP_SOURCE,
      secret: process.env.AUTH_PROXY_SECRET,
      method: request.method,
      path: upstream.pathname,
    });
  } catch {
    return new Response("Trusted ingress is unavailable", { status: 503, headers: { "cache-control": "no-store" } });
  }

  try {
    const upstreamResponse = await fetch(upstream, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
      redirect: "manual",
      cache: "no-store",
    });
    const response = sessionProbe ? await sessionProbeResponse(upstreamResponse) : upstreamResponse;

    const responseHeaders = new Headers();
    response.headers.forEach((value: string, name: string) => {
      if (!["connection", "content-encoding", "content-length", "set-cookie", "transfer-encoding"].includes(name)) {
        responseHeaders.set(name, value);
      }
    });
    for (const cookie of response.headers.getSetCookie()) responseHeaders.append("set-cookie", cookie);
    responseHeaders.set("cache-control", "no-store");

    return new Response(response.body, { status: response.status, headers: responseHeaders });
  } catch {
    return new Response("API upstream is unavailable", { status: 502 });
  }
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as HEAD };
