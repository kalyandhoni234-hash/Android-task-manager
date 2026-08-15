const STEPS = [
  { title: "Download", body: "Get the packaged Windows executable — no Python required." },
  { title: "Launch", body: "Open AndroidTaskManager.exe." },
  { title: "Connect Android device", body: "Plug in over USB (or reach it over adb Wi-Fi)." },
  { title: "Enable USB debugging", body: "Turned on once in Developer options." },
  { title: "Authorize ADB", body: "Accept the debugging prompt on the phone." },
  { title: "Start monitoring", body: "The live dashboard appears automatically." },
];

const STATES = [
  "ADB discovery",
  "Locate ADB",
  "No-device state",
  "Authorization state",
  "Offline-device state",
  "Multiple-device selection",
  "Automatic reconnect handling",
];

export function ConnectionFlow() {
  return (
    <section id="connect" className="border-b border-border bg-bg-raised">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <div className="max-w-xl">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
            How it works
          </p>
          <h2 className="font-display text-balance mt-3 text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
            Connect. Launch. Monitor.
          </h2>
        </div>

        <ol className="mt-12 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map((step, i) => (
            <li
              key={step.title}
              className="rounded-lg border border-border bg-surface p-6"
            >
              <span className="font-mono text-xs text-accent-strong">
                {String(i + 1).padStart(2, "0")}
              </span>
              <h3 className="font-display mt-3 text-base font-semibold text-text-primary">
                {step.title}
              </h3>
              <p className="mt-1.5 text-sm leading-relaxed text-text-secondary">
                {step.body}
              </p>
            </li>
          ))}
        </ol>

        <div className="mt-10 rounded-lg border border-border bg-surface p-6">
          <p className="text-sm text-text-secondary">
            ADB <span className="text-text-primary">is required</span> — it&apos;s
            the communication mechanism the app uses to reach the device. The
            packaged Windows application itself does not require Python; it
            handles the rest of the connection experience for you:
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            {STATES.map((state) => (
              <span
                key={state}
                className="font-mono rounded-md border border-border-strong bg-bg-raised px-2.5 py-1 text-[11px] text-text-secondary"
              >
                {state}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
