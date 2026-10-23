import type { NextConfig } from "next";
import { apexToWwwRedirects } from "./app/canonical-host.mjs";

const nextConfig: NextConfig = {
  async redirects() {
    return apexToWwwRedirects;
  },
  async headers() {
    return [{ source: "/login", headers: [{ key: "Referrer-Policy", value: "no-referrer" }, { key: "Cache-Control", value: "no-store" }] }];
  },
};

export default nextConfig;
