// The production site URL: the repository's GitHub Pages site. Overrideable
// via the SITE_URL environment variable at build time (e.g. for a custom
// domain) - never fabricates a domain.
export const SITE_URL =
  process.env.SITE_URL ??
  "https://kalyandhoni234-hash.github.io/Android-task-manager";

export const GITHUB_URL =
  "https://github.com/kalyandhoni234-hash/Android-task-manager";
export const GITHUB_RELEASES_URL = `${GITHUB_URL}/releases`;

// Actual collected test count from the last verified run of
// `python -m pytest --collect-only -q` against this repository.
export const TEST_COUNT = 734;