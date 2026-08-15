import { DOWNLOAD_URL, GITHUB_URL, HAS_RELEASE_ASSET } from "@/lib/constants";

export function DownloadCta() {
  return (
    <section id="download" className="bg-grid relative overflow-hidden">
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-full bg-[radial-gradient(ellipse_60%_50%_at_50%_110%,rgba(76,130,247,0.14),transparent)]" />
      <div className="relative mx-auto max-w-3xl px-6 py-28 text-center">
        <h2 className="font-display text-balance text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
          Ready to see inside your Android device?
        </h2>
        <p className="mt-4 text-base leading-relaxed text-text-secondary">
          Download Android Task Manager for Windows.
        </p>

        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <a
            href={DOWNLOAD_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center rounded-md bg-accent px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
          >
            {HAS_RELEASE_ASSET ? "Download for Windows" : "Get Android Task Manager"}
          </a>
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-2 rounded-md border border-border-strong px-6 py-3 text-sm font-medium text-text-primary transition-colors hover:border-accent-border hover:bg-surface"
          >
            View on GitHub
          </a>
        </div>

        {!HAS_RELEASE_ASSET && (
          <p className="font-mono mt-5 text-xs text-text-tertiary">
            No packaged .exe has been published as a GitHub Release yet —
            this links to the repository, where build instructions live.
          </p>
        )}
      </div>
    </section>
  );
}
