const NETWORK_ITEMS = [
  "Download and upload throughput",
  "Interface-level activity",
  "Interface classification (Wi-Fi / Mobile Data / VPN / …)",
  "Active-interface filtering, with a show-all toggle",
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
      </div>
    </section>
  );
}
