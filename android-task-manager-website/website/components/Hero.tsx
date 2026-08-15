import { ScreenshotFrame } from "./ScreenshotFrame";
import { Sparkline } from "./Sparkline";
import { GITHUB_URL } from "@/lib/constants";

export function Hero() {
  return (
    <section
      id="top"
      className="bg-grid relative overflow-hidden border-b border-border"
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-full bg-[radial-gradient(ellipse_60%_50%_at_50%_-10%,rgba(76,130,247,0.16),transparent)]" />

      <div className="relative mx-auto grid max-w-6xl gap-16 px-6 pt-20 pb-24 lg:grid-cols-[1.05fr_1fr] lg:items-center lg:pt-28 lg:pb-32">
        <div>
          <div className="font-mono mb-6 inline-flex items-center gap-2 rounded-full border border-border-strong bg-surface px-3 py-1 text-[11px] text-text-secondary">
            <span
              className="h-1.5 w-1.5 animate-blink rounded-full bg-accent"
              aria-hidden="true"
            />
            Windows 10/11 · Open Source · Read-only monitoring
          </div>

          <h1 className="font-display text-balance text-4xl font-semibold leading-[1.08] tracking-tight text-text-primary sm:text-5xl lg:text-[3.4rem]">
            Monitor your Android device
            <br />
            from your Windows desktop.
          </h1>

          <p className="mt-6 max-w-lg text-lg leading-relaxed text-text-secondary">
            Real-time CPU, memory, process, battery and network monitoring
            through ADB — presented in a focused desktop dashboard.
          </p>

          <div className="mt-9 flex flex-col gap-3 sm:flex-row sm:items-center">
            <a
              href="#download"
              className="inline-flex items-center justify-center rounded-md bg-accent px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
            >
              Download for Windows
            </a>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center justify-center gap-2 rounded-md border border-border-strong px-5 py-3 text-sm font-medium text-text-primary transition-colors hover:border-accent-border hover:bg-surface"
            >
              View on GitHub
            </a>
          </div>

          <div className="mt-12 flex items-center gap-4 text-text-tertiary">
            <Sparkline className="h-8 w-40 text-accent-strong" />
            <span className="font-mono text-xs">
              cpu0–cpu7 · live history
            </span>
          </div>
        </div>

        <ScreenshotFrame
          src={undefined}
          alt="Android Task Manager desktop dashboard showing CPU, memory, process and battery panels"
          label="dashboard.png — main GUI dashboard (CPU / memory / processes / battery / network)"
          priority
        />
      </div>
    </section>
  );
}
