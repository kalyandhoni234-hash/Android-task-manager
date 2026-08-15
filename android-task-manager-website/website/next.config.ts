import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Statically exported site, deployed to GitHub Pages
  // (https://<owner>.github.io/Android-task-manager/). The basePath matches
  // the Pages subdirectory derived from the repository name.
  output: "export",
  basePath: "/Android-task-manager",
  images: { unoptimized: true },
};

export default nextConfig;