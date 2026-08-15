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

const NETWORK_FIELDS = [
  "TCP",
  "UDP",
  "IPv4",
  "IPv6",
  "Connection state",
  "UID attribution",
  "Verified package names",
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

        <div className="mt-16 rounded-xl border border-border bg-surface p-8 sm:p-10">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
            Network connections
          </p>
          <h3 className="font-display mt-3 text-2xl font-semibold tracking-tight text-text-primary">
            The Inspector also shows the process&apos;s connections.
          </h3>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-text-secondary">
            The inspector&apos;s network section surfaces the device&apos;s live
            socket tables: protocol, local and remote endpoints and connection
            state for every socket owned by the process&apos;s UID — with the
            verified Android package names attached. Attribution is at the{" "}
            <span className="text-text-primary">UID level</span> (the
            identifier Android grants per package), not per-process socket
            ownership, and it is read-only — no packet capture, no traffic
            interception.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            {NETWORK_FIELDS.map((field) => (
              <span
                key={field}
                className="font-mono rounded-md border border-border-strong bg-bg-raised px-2.5 py-1 text-[11px] text-text-secondary"
              >
                {field}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}