// Release metadata tests — Node's built-in test runner (no test framework
// dependency). The fetch layer is stubbed, so no network and no GitHub
// token are involved.
//
// Run with: npm test   (node --test --experimental-strip-types test/)

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import test from "node:test";

import {
  fetchLatestRelease,
  parseSha256Sums,
} from "../lib/release.ts";

const EXE_SHA = "8cc48979aac2d1be482746143f6442000531dcabbce8c08957152b943603a9e7";
const DEBUG_SHA = "6f3c3aab321b8067c2287f734e7717e63eae7bda9d9754d4edbf93ff8201fee8";

const SUMS_WITH_BOTH = `${EXE_SHA}  dist\\AndroidTaskManager.exe\n${DEBUG_SHA}  dist\\AndroidTaskManager-debug.exe\n`;

function asset(name, size, extra = {}) {
  return {
    name,
    size,
    browser_download_url: `https://github.com/kalyandhoni234-hash/Android-task-manager/releases/download/v0.3.0/${name}`,
    ...extra,
  };
}

function apiPayload(
  assets = [
    asset("AndroidTaskManager.exe", 49715759),
    asset("AndroidTaskManager-debug.exe", 49720984),
    asset("SHA256SUMS.txt", 196),
  ],
) {
  return {
    tag_name: "v0.3.0",
    published_at: "2026-08-15T16:52:53Z",
    assets,
  };
}

/** Stub fetch: routes known URLs to canned responses; else 500. */
function stubFetch(overrides = {}) {
  return async (url) => {
    const urls = new URL(url);
    if (urls.pathname.endsWith("/releases/latest")) {
      const status = overrides.latestStatus ?? 200;
      if (status !== 200) return { ok: false, status };
      return { ok: true, json: async () => overrides.latest ?? apiPayload() };
    }
    if (urls.pathname.endsWith("/SHA256SUMS.txt")) {
      if (overrides.sumsStatus === 404) return { ok: false, status: 404 };
      return {
        ok: true,
        text: async () => overrides.sumsText ?? SUMS_WITH_BOTH,
      };
    }
    return { ok: false, status: 500 };
  };
}

// ---------------------------------------------------------------------------
// parseSha256Sums
// ---------------------------------------------------------------------------

test("parseSha256Sums picks the normal EXE, not the debug build", () => {
  assert.equal(parseSha256Sums(SUMS_WITH_BOTH), EXE_SHA);
});

test("parseSha256Sums tolerates the binary marker and plain filenames", () => {
  assert.equal(parseSha256Sums(`${EXE_SHA}  *AndroidTaskManager.exe`), EXE_SHA);
  assert.equal(
    parseSha256Sums(`${EXE_SHA}  AndroidTaskManager.exe`),
    EXE_SHA,
  );
});

test("parseSha256Sums returns null when the EXE line is missing", () => {
  assert.equal(
    parseSha256Sums(`${DEBUG_SHA}  dist\\AndroidTaskManager-debug.exe`),
    null,
  );
});

test("parseSha256Sums ignores malformed lines", () => {
  assert.equal(
    parseSha256Sums("not-a-hash  AndroidTaskManager.exe\n\nshort  x\n"),
    null,
  );
});

test("parseSha256Sums accepts CRLF line endings", () => {
  assert.equal(parseSha256Sums(`${EXE_SHA}  AndroidTaskManager.exe\r\n`), EXE_SHA);
});

// ---------------------------------------------------------------------------
// fetchLatestRelease — happy path
// ---------------------------------------------------------------------------

test("latest release is v0.3.0 with the normal EXE and matching facts", async () => {
  const release = await fetchLatestRelease(stubFetch());
  assert.ok(release);
  assert.equal(release.version, "0.3.0");
  assert.equal(release.tag, "v0.3.0");
  assert.equal(release.fileName, "AndroidTaskManager.exe");
  assert.equal(
    release.url,
    "https://github.com/kalyandhoni234-hash/Android-task-manager/releases/download/v0.3.0/AndroidTaskManager.exe",
  );
  // File size comes from the release asset, never a hardcoded value.
  assert.equal(release.sizeBytes, 49715759);
  // SHA-256 comes from the release's SHA256SUMS.txt, matched by exact name.
  assert.equal(release.sha256, EXE_SHA);
  assert.equal(release.publishedAt, "2026-08-15T16:52:53Z");
});

test("sha256 is null when SHA256SUMS.txt has no EXE line", async () => {
  const release = await fetchLatestRelease(
    stubFetch({ sumsText: `${DEBUG_SHA}  AndroidTaskManager-debug.exe\n` }),
  );
  assert.ok(release);
  assert.equal(release.sha256, null);
});

test("sha256 is null when SHA256SUMS.txt is unavailable", async () => {
  const release = await fetchLatestRelease(stubFetch({ sumsStatus: 404 }));
  assert.ok(release);
  assert.equal(release.sha256, null);
});

// ---------------------------------------------------------------------------
// fetchLatestRelease — failure modes (honest fallback)
// ---------------------------------------------------------------------------

test("debug-only release never becomes the primary download", async () => {
  const release = await fetchLatestRelease(
    stubFetch({
      latest: apiPayload([asset("AndroidTaskManager-debug.exe", 49720984)]),
    }),
  );
  assert.equal(release, null);
});

test("missing assets yield null", async () => {
  assert.equal(await fetchLatestRelease(stubFetch({ latest: apiPayload([]) })), null);
});

test("non-200 API response yields null", async () => {
  assert.equal(await fetchLatestRelease(stubFetch({ latestStatus: 403 })), null);
});

test("network failure yields null instead of throwing", async () => {
  const broken = async () => {
    throw new Error("network down");
  };
  assert.equal(await fetchLatestRelease(broken), null);
});

test("malformed JSON yields null", async () => {
  const badJson = async () => ({ ok: true, json: async () => "not json" });
  assert.equal(await fetchLatestRelease(badJson), null);
});

test("missing tag yields null", async () => {
  assert.equal(
    await fetchLatestRelease(stubFetch({ latest: { assets: [] } })),
    null,
  );
});

// ---------------------------------------------------------------------------
// No stale release facts remain in the site sources
// ---------------------------------------------------------------------------

const here = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(here, "..");

test("constants no longer carry a hardcoded release", async () => {
  const source = await readFile(
    path.join(projectRoot, "lib", "constants.ts"),
    "utf8",
  );
  assert.ok(!source.includes("export const RELEASE"));
  assert.ok(!source.includes("HAS_RELEASE_ASSET"));
  assert.ok(!source.includes("0.2.0"));
});

test("download section has no hardcoded release reference and renders an honest fallback", async () => {
  const source = await readFile(
    path.join(projectRoot, "components", "DownloadCta.tsx"),
    "utf8",
  );
  assert.ok(!source.includes("0.2.0"));
  assert.ok(!source.includes("RELEASE."));
  assert.ok(source.includes("Release information temporarily unavailable."));
  assert.ok(source.includes("Download for Windows"));
  assert.ok(!source.includes("Download v"));
});