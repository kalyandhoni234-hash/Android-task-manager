import { ScreenshotFrame } from "./ScreenshotFrame";

const FIELDS = [
  "PID",
  "UID",
  "CPU",
  "Memory",
  "State",
  "Threads",
  "Priority",
  "Nice",
  "Virtual memory",
  "Resident memory",
  "Shared memory",
  "I/O",
  "Command line",
];

export function ProcessInspector() {
  return (
    <section className="border-b border-border bg-bg-raised">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <div className="grid gap-12 lg:grid-cols-2 lg:items-center lg:gap-16">
          <ScreenshotFrame
            alt="Process Inspector panel showing detailed /proc information for a selected process"
            label="process-inspector.png — detail panel for a selected process"
            className="lg:order-2"
          />

          <div className="lg:order-1">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
              Process Inspector
            </p>
            <h2 className="font-display text-balance mt-3 text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
              Look inside a process.
            </h2>
            <p className="mt-4 max-w-md text-base leading-relaxed text-text-secondary">
              Select a row in the process table and Android Task Manager
              reads that process&apos;s <code className="font-mono text-text-primary">/proc/&lt;pid&gt;</code>{" "}
              files once, on a background thread, and shows what it finds.
            </p>

            <div className="mt-7 flex flex-wrap gap-2">
              {FIELDS.map((field) => (
                <span
                  key={field}
                  className="font-mono rounded-md border border-border-strong bg-surface px-2.5 py-1 text-[11px] text-text-secondary"
                >
                  {field}
                </span>
              ))}
            </div>

            <p className="font-mono mt-6 text-xs text-warn">
              Unavailable values are shown as N/A — never a fabricated zero.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
