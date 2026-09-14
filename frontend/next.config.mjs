/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // No `env` block here — the only backend-facing value the browser
  // needs is NEXT_PUBLIC_AGENTABI_API_URL, which Next.js already
  // inlines automatically from .env.local at build time (spec §9/§40).
  // Never add non-NEXT_PUBLIC_* values here — they would leak to the client.
};

export default nextConfig;
