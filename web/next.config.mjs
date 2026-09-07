/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit .next/standalone: a self-contained server with only the
  // modules actually imported. Lets the runtime image skip node_modules
  // entirely, which is the difference between a ~200MB image and a
  // ~1.5GB one.
  output: "standalone",
};

export default nextConfig;
