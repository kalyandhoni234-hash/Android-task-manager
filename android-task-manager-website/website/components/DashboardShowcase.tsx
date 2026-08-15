import { ScreenshotFrame } from "./ScreenshotFrame";
import { Sparkline } from "./Sparkline";

export function DashboardShowcase() {
  return (
    <section className="border-b border-border">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <div className="grid gap-12 lg:grid-cols-2 lg:items-center lg:gap-16">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
              Dashboard
            </p>
            <h2 className="font-display text-balance mt-3 text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
              See your device in real time.
            </h2>
            <p className="mt-4 max-w-md text-base leading-relaxed text-text-secondary">
              CPU, memory, processes, battery and network activity are
              visible from one desktop dashboard — overall utilization, the
              recent-history graph, and one bar per core with live frequency.
            </p>

            <div className="mt-8 flex items-center gap-4 rounded-lg border border-border bg-bg-raised px-5 py-4">
              <Sparkline className="h-10 w-32 shrink-0 text-accent-strong" />
              <div className="font-mono text-xs leading-relaxed text-text-tertiary">
                <div>utilization = busy_delta / total_delta × 100</div>
                <div>computed from two /proc/stat samples, never one</div>
              </div>
            </div>
          </div>

          <ScreenshotFrame
            alt="CPU panel showing overall utilization, per-core bars, frequency and a live history graph"
            label="cpu-panel.png — overall utilization, per-core bars + frequency, history graph"
          />
        </div>
      </div>
    </section>
  );
}
