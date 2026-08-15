import { GITHUB_RELEASES_URL, GITHUB_URL } from "@/lib/constants";

export function OpenSource() {
  return (
    <section className="border-b border-border">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <div className="flex flex-col items-start justify-between gap-8 rounded-xl border border-border bg-surface p-10 sm:p-12 lg:flex-row lg:items-center">
          <div className="max-w-lg">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
              Open source
            </p>
            <h2 className="font-display text-balance mt-3 text-2xl font-semibold tracking-tight text-text-primary sm:text-3xl">
              Built in the open.
            </h2>
            <p className="mt-3 text-base leading-relaxed text-text-secondary">
              The source, architecture and tests are available on GitHub —
              MIT licensed. Release assets (EXE + SHA-256) are published
              through GitHub Releases.
            </p>
          </div>

          <div className="flex shrink-0 flex-col gap-3 sm:flex-row">
            <a
              href={GITHUB_RELEASES_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center justify-center gap-2 rounded-md bg-accent px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
            >
              Release notes
            </a>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center justify-center gap-2 rounded-md border border-border-strong px-5 py-3 text-sm font-medium text-text-primary transition-colors hover:border-accent-border hover:bg-bg-raised"
            >
              View source on GitHub
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
