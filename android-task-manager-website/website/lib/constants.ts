export const GITHUB_URL =
  "https://github.com/kalyandhoni234-hash/Android-task-manager";

export const GITHUB_RELEASES_URL = `${GITHUB_URL}/releases`;

// No public release asset exists yet (verified against the GitHub Releases
// API while building this page). Point download CTAs at the repository
// instead of a fabricated .exe URL. Flip this the moment a real release
// asset is published.
export const DOWNLOAD_URL = GITHUB_URL;
export const HAS_RELEASE_ASSET = false;

// Actual collected test count as of the last verified `pytest --collect-only`
// run against this repository (tests/ directory, 252 tests).
export const TEST_COUNT = 252;
