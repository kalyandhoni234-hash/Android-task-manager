const FEATURES = [
  {
    label: "CPU",
    title: "Per-core detail, live history",
    body: "Per-core utilization, frequency and a live CPU history graph.",
    stat: "cpu0–cpu7",
  },
  {
    label: "Memory",
    title: "Real pressure, not just free RAM",
    body: "Track available memory and overall memory pressure.",
    stat: "MemAvailable",
  },
  {
    label: "Processes",
    title: "Sorted, classified, live",
    body: "Monitor CPU and memory usage across Android processes, with sorting and filtering.",
    stat: "ps + top",
  },
  {
    label: "Process Inspector",
    title: "Look inside a single process",
    body: "Inspect detailed Linux /proc information for individual processes.",
    stat: "/proc/<pid>",
  },
  {
    label: "Network",
    title: "Throughput by interface",
    body: "Monitor upload/download throughput, interface activity and active-interface filtering.",
    stat: "/proc/net/dev",
  },
  {
    label: "Battery",
    title: "More than a percentage",
    body: "Monitor battery level, charging state, health, temperature, voltage and technology.",
    stat: "dumpsys battery",
  },
  {
    label: "Network Investigation",
    title: "TCP and UDP, per UID",
    body: "Live socket tables: TCP/UDP over IPv4/IPv6, with connections attributed to the owning Android UID and its verified packages.",
    stat: "/proc/net/tcp*",
  },
  {
    label: "Device Actions",
    title: "Open App · App Info · Force Stop",
    body: "Targeted actions against a selected app — no kill-all, no data clearing, no restarts.",
    stat: "verified packages",
  },
  {
    label: "Device Information",
    title: "An \"About phone\" dashboard",
    body: "Hardware, Android version, security patch, build, kernel, memory, battery, storage, display and identifiers — collected once per connection.",
    stat: "getprop · wm · df",
  },
  {
    label: "Applications",
    title: "Installed-app inventory",
    body: "List system and user apps with versions and APK paths, inspect per-package details, audit permissions and run capability-gated actions.",
    stat: "pm list packages",
  },
];

export function Features() {
  return (
    <section id="features" className="border-b border-border">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <div className="max-w-xl">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
            Feature overview
          </p>
          <h2 className="font-display text-balance mt-3 text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
            Everything you need at a glance.
          </h2>
        </div>

        <div className="mt-12 grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((feature) => (
            <div
              key={feature.label}
              className="group flex flex-col gap-4 bg-bg-raised p-7 transition-colors hover:bg-surface"
            >
              <div className="flex items-start justify-between gap-3">
                <span className="font-display text-base font-semibold text-text-primary">
                  {feature.label}
                </span>
                <span className="font-mono rounded border border-border-strong px-1.5 py-0.5 text-[10px] text-text-tertiary">
                  {feature.stat}
                </span>
              </div>
              <div>
                <h3 className="text-sm font-medium text-text-primary">
                  {feature.title}
                </h3>
                <p className="mt-1.5 text-sm leading-relaxed text-text-secondary">
                  {feature.body}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}