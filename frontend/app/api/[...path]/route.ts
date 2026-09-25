import type { NextRequest } from "next/server";

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
  upstream.pathname = incoming.pathname.slice("/api".length);
  upstream.search = incoming.search;

  const headers = new Headers();
  for (const name of ["accept", "content-type", "cookie", "authorization", "x-request-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  try {
    const response = await fetch(upstream, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
      redirect: "manual",
      cache: "no-store",
    });

    const responseHeaders = new Headers();
    response.headers.forEach((value, name) => {
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
