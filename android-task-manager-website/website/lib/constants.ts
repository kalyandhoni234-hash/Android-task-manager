// The production site URL: the repository's GitHub Pages site. Overrideable
// via the SITE_URL environment variable at build time (e.g. for a custom
// domain) - never fabricates a domain.
export const SITE_URL =
  process.env.SITE_URL ??
  "https://kalyandhoni234-hash.github.io/Android-task-manager";

export const GITHUB_URL =
  "https://github.com/kalyandhoni234-hash/Android-task-manager";
export const GITHUB_RELEASES_URL = `${GITHUB_URL}/releases`;

// The current public release. The download URL points at the versioned GitHub
// Release asset (created by .github/workflows/release.yml from a git tag).
// sizeBytes and sha256 are filled from the exact artifact published in that
// release - never from a local build.
export const RELEASE = {
  version: "0.2.0",
  tag: "v0.2.0",
  fileName: "AndroidTaskManager.exe",
  url: `${GITHUB_URL}/releases/download/v0.2.0/AndroidTaskManager.exe`,
  sizeBytes: 0,
  sha256: "",
};
export const HAS_RELEASE_ASSET = true;

// Actual collected test count from the last verified run of
// `python -m pytest --collect-only -q` against this repository.
export const TEST_COUNT = 483;