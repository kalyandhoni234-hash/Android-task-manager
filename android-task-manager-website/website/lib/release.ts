// Build-time release metadata: the website's download section reflects the
// latest *published* GitHub release, fetched from the public GitHub API
// during prerender (static export). No token, no backend, no hardcoded
// version: the release page is the source of truth.
//
// Any failure returns `null` — the caller renders an honest "release
// information temporarily unavailable" state instead of stale data.
// This module never throws.

// Mirrors `GITHUB_URL` in `lib/constants.ts`; kept local so this module
// stays importable by plain Node (test runner) without extension-loader
// tricks. This is project identity, not release metadata.
const GITHUB_URL =
  "https://github.com/kalyandhoni234-hash/Android-task-manager";

const API_URL =
  "https://api.github.com/repos/kalyandhoni234-hash/Android-task-manager/releases/latest";
const USER_AGENT = "android-task-manager-website";
const REQUEST_TIMEOUT_MS = 10_000;

export const EXE_FILE_NAME = "AndroidTaskManager.exe";
const CHECKSUMS_FILE_NAME = "SHA256SUMS.txt";

export interface ReleaseInfo {
  /** Version without the leading "v" (e.g. "0.3.0"). */
  version: string;
  /** Tag as published (e.g. "v0.3.0"). */
  tag: string;
  /** Primary download asset name (always the normal EXE, never the debug build). */
  fileName: string;
  /** Direct download URL of the primary asset. */
  url: string;
  /** Asset size in bytes as reported by the GitHub API. */
  sizeBytes: number;
  /** SHA-256 of the primary asset from the release's SHA256SUMS.txt, or null. */
  sha256: string | null;
  /** ISO timestamp of the release, or null. */
  publishedAt: string | null;
}

interface ReleaseAsset {
  name: string;
  size: number;
  browser_download_url: string;
}

/**
 * Parse a `sha256sum`-style file and return the checksum for exactly
 * `AndroidTaskManager.exe` — never the debug build. Tolerates the common
 * formats: `hash  name`, `hash *name` (binary marker) and Windows-style
 * paths (`dist\AndroidTaskManager.exe`). Returns null when the file has no
 * matching line.
 */
export function parseSha256Sums(text: string): string | null {
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const parts = trimmed.split(/\s+/);
    if (parts.length < 2) continue;
    const [hash, rawName] = parts;
    if (!/^[0-9a-fA-F]{64}$/.test(hash)) continue;
    const name = rawName.replace(/^\*/, "").split(/[\\/]/).pop() ?? "";
    if (name === EXE_FILE_NAME) return hash.toLowerCase();
  }
  return null;
}

function isAsset(value: unknown): value is ReleaseAsset {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.name === "string" &&
    typeof record.size === "number" &&
    record.size > 0 &&
    typeof record.browser_download_url === "string"
  );
}

async function fetchJson(
  url: string,
  fetchImpl: typeof fetch,
): Promise<unknown | null> {
  try {
    const response = await fetchImpl(url, {
      headers: { "User-Agent": USER_AGENT, Accept: "application/vnd.github+json" },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

async function fetchText(
  url: string,
  fetchImpl: typeof fetch,
): Promise<string | null> {
  try {
    const response = await fetchImpl(url, {
      headers: { "User-Agent": USER_AGENT },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) return null;
    return await response.text();
  } catch {
    return null;
  }
}

/**
 * Fetch the latest published release from the public GitHub API.
 *
 * The primary asset is `AndroidTaskManager.exe` — the debug build is never
 * used as the download. The displayed SHA-256 comes from the release's own
 * `SHA256SUMS.txt` (matched by exact asset name), never from a local build
 * or a different asset. Any missing or malformed data yields `null`.
 */
export async function fetchLatestRelease(
  fetchImpl: typeof fetch = fetch,
): Promise<ReleaseInfo | null> {
  const payload = await fetchJson(API_URL, fetchImpl);
  if (typeof payload !== "object" || payload === null) return null;
  const release = payload as Record<string, unknown>;
  const tag = typeof release.tag_name === "string" ? release.tag_name : "";
  if (!tag) return null;

  const assets = Array.isArray(release.assets)
    ? (release.assets.filter(isAsset) as ReleaseAsset[])
    : [];
  const exe = assets.find((asset) => asset.name === EXE_FILE_NAME);
  if (!exe) return null;

  let sha256: string | null = null;
  const checksums = assets.find((asset) => asset.name === CHECKSUMS_FILE_NAME);
  if (checksums) {
    const text = await fetchText(checksums.browser_download_url, fetchImpl);
    if (text !== null) sha256 = parseSha256Sums(text);
  }

  const publishedAt =
    typeof release.published_at === "string" ? release.published_at : null;

  return {
    version: tag.replace(/^v/, ""),
    tag,
    fileName: EXE_FILE_NAME,
    url: `${GITHUB_URL}/releases/download/${tag}/${EXE_FILE_NAME}`,
    sizeBytes: exe.size,
    sha256,
    publishedAt,
  };
}