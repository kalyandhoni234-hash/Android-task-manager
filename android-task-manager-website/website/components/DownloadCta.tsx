import {
  GITHUB_RELEASES_URL,
  HAS_RELEASE_ASSET,
  RELEASE,
} from "@/lib/constants";

const PLATFORM_TOOLS_URL = "https://developer.android.com/tools/releases/platform-tools";

function formatSize(bytes: number): string {
  if (bytes <= 0) return "";
  const mb = bytes / (1024 * 1024);
  return `${mb.toFixed(1)} MB`;
}

export function DownloadCta() {
  const size = formatSize(RELEASE.sizeBytes);

  return (
    <section id="download" className="bg-grid relative overflow-hidden">
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-full bg-[radial-gradient(ellipse_60%_50%_at_50%_110%,rgba(76,130,247,0.14),transparent)]" />
      <div className="relative mx-auto max-w-3xl px-6 py-28 text-center">
        <h2 className="font-display text-balance text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
          Ready to see inside your Android device?
        </h2>
        <p className="mt-4 text-base leading-relaxed text-text-secondary">
          Download Android Task Manager for Windows — a single portable EXE
          that runs without installing Python.
        </p>

        <div className="mt-9 flex flex-col items-stretch justify-center gap-3 sm:flex-row">
          {HAS_RELEASE_ASSET ? (
            <a
              href={RELEASE.url}
              download={RELEASE.fileName}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-accent px-6 py-3.5 text-base font-medium text-white transition-colors hover:bg-accent-strong"
            >
              Download for Windows
              <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                aria-hidden="true"
              >
                <path
                  d="M8 1.5V10M8 10L4.5 6.5M8 10L11.5 6.5M2.5 13.5H13.5"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </a>
          ) : (
            <a
              href={GITHUB_RELEASES_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center justify-center rounded-md bg-accent px-6 py-3.5 text-base font-medium text-white transition-colors hover:bg-accent-strong"
            >
              Get Android Task Manager
            </a>
          )}
          <a
            href={GITHUB_RELEASES_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-2 rounded-md border border-border-strong px-6 py-3.5 text-base font-medium text-text-primary transition-colors hover:border-accent-border hover:bg-surface"
          >
            View on GitHub
          </a>
        </div>

        <dl className="mx-auto mt-10 grid max-w-2xl gap-px overflow-hidden rounded-xl border border-border bg-border text-left sm:grid-cols-2">
          <div className="bg-bg-raised p-5">
            <dt className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-tertiary">
              Release
            </dt>
            <dd className="mt-1 text-sm text-text-primary">
              v{RELEASE.version} · {RELEASE.fileName}
            </dd>
          </div>
          <div className="bg-bg-raised p-5">
            <dt className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-tertiary">
              File size
            </dt>
            <dd className="mt-1 text-sm text-text-primary">{size || "—"}</dd>
          </div>
          <div className="col-span-full bg-bg-raised p-5">
            <dt className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-tertiary">
              SHA-256
            </dt>
            <dd className="font-mono mt-2 break-all text-xs leading-relaxed text-text-secondary">
              {RELEASE.sha256 || "—"}
            </dd>
          </div>
        </dl>

        <ul className="mt-8 space-y-2 text-sm text-text-tertiary">
          <li>64-bit Windows · portable single EXE — no installation, no Python.</li>
          <li>
            Uses the ADB already on your computer, or guides you to the{" "}
            <a
              href={PLATFORM_TOOLS_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent-strong underline decoration-accent-border underline-offset-2 hover:text-text-primary"
            >
              official Android Platform-Tools
            </a>
            {" "}(ADB is not bundled).
          </li>
          <li>
            The EXE is not code-signed — Windows SmartScreen may warn; choose
            “More info → Run anyway”.
          </li>
          <li>This build is for 64-bit Windows; no other platform builds are published.</li>
        </ul>
      </div>
    </section>
  );
}