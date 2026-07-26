/** @type {import('next').NextConfig} */
const nextConfig = {
  // Profiles are frozen snapshots, so every page can be pre-rendered at build time.
  // A share link is a static document, not a live query against someone's activity.
  output: "export",
};

export default nextConfig;
