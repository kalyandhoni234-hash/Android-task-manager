const NETWORK_ITEMS = [
  "Download and upload throughput",
  "Interface-level activity",
  "Interface classification (Wi-Fi / Mobile Data / VPN / …)",
  "Active-interface filtering, with a show-all toggle",
];

const INVESTIGATION_ITEMS = [
  "TCP and UDP",
  "IPv4 and IPv6",
  "Local / remote endpoints",
  "Connection states (ESTABLISHED, LISTEN, TIME-WAIT, …)",
  "Attribution to the owning UID",
  "Verified Android package names per UID",
];

const BATTERY_ITEMS = [
  "Battery level",
  "Charging state",
  "Health",
  "Temperature",
  "Voltage",
  "Technology",
  "Power source",
];

export function NetworkBattery() {
  return (
    <section className="border-b border-border">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <div className="grid gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-2">
          <div className="bg-bg-raised p-8 sm:p-10">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
              Network
            </p>
            <h3 className="font-display mt-3 text-2xl font-semibold tracking-tight text-text-primary">
              Throughput, by interface.
            </h3>
            <p className="mt-3 text-sm leading-relaxed text-text-secondary">
              Delta-based throughput readings from{" "}
              <code className="font-mono text-text-primary">/proc/net/dev</code>{" "}
              — this is throughput monitoring, not packet capture or traffic
              interception.
            </p>
            <ul className="mt-6 space-y-2.5">
              {NETWORK_ITEMS.map((item) => (
                <li
                  key={item}
                  className="flex items-start gap-2.5 text-sm text-text-secondary"
                >
                  <span
                    className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent"
                    aria-hidden="true"
                  />
                  {item}
                </li>
              ))}
            </ul>
          </div>

          <div className="bg-bg-raised p-8 sm:p-10">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
              Battery
            </p>
            <h3 className="font-display mt-3 text-2xl font-semibold tracking-tight text-text-primary">
              More than a percentage.
            </h3>
            <p className="mt-3 text-sm leading-relaxed text-text-secondary">
              Parsed from{" "}
              <code className="font-mono text-text-primary">
                dumpsys battery
              </code>
              , with Android&apos;s status and health enums normalized to
              readable states.
            </p>
            <ul className="mt-6 grid grid-cols-2 gap-2.5">
              {BATTERY_ITEMS.map((item) => (
                <li
                  key={item}
                  className="flex items-start gap-2.5 text-sm text-text-secondary"
                >
                  <span
                    className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent"
                    aria-hidden="true"
                  />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="mt-6 grid gap-px overflow-hidden rounded-xl border border-border bg-border lg:grid-cols-[1.1fr_1fr]">
          <div className="bg-bg-raised p-8 sm:p-10">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
              Network Investigation
            </p>
            <h3 className="font-display mt-3 text-2xl font-semibold tracking-tight text-text-primary">
              Which app owns this connection?
            </h3>
            <p className="mt-3 text-sm leading-relaxed text-text-secondary">
              The inspector parses the device&apos;s kernel socket tables
              directly —{" "}
              <code className="font-mono text-text-primary">/proc/net/tcp</code>,{" "}
              <code className="font-mono text-text-primary">/proc/net/tcp6</code>,{" "}
              <code className="font-mono text-text-primary">/proc/net/udp</code>{" "}
              and{" "}
              <code className="font-mono text-text-primary">
                /proc/net/udp6
              </code>{" "}
              — and pairs each socket&apos;s owner UID with the exact package
              names reported by Android. No root, no packet capture, no
              telemetry.
            </p>
          </div>
          <div className="bg-bg-raised p-8 sm:p-10">
            <ul className="space-y-2.5">
              {INVESTIGATION_ITEMS.map((item) => (
                <li
                  key={item}
                  className="flex items-start gap-2.5 text-sm text-text-secondary"
                >
                  <span
                    className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent"
                    aria-hidden="true"
                  />
                  {item}
                </li>
              ))}
            </ul>
            <p className="font-mono mt-6 text-xs text-warn">
              Attribution is UID-level, not PID-level. If a socket table
              cannot be read, the UI says so — it never guesses.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}