import { TEST_COUNT } from "@/lib/constants";

const STACK = [
  { name: "Python", role: "Core application" },
  { name: "PySide6", role: "Desktop interface" },
  { name: "ADB", role: "Android communication" },
  { name: "GitHub Actions", role: "Automated CI" },
];

const FACTS = [
  "Validated against a real Vivo V2026 (Android 11) over USB",
  "Every collector reads real /proc, /sys and dumpsys output",
  "ADB is never bundled — discovered or pointed at official Platform-Tools",
];

export function Credibility() {
  return (
    <section className="border-b border-border bg-bg-raised">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <div className="flex flex-col gap-10 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-lg">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
              Under the hood
            </p>
            <h2 className="font-display text-balance mt-3 text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
              Built with real system interfaces.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-text-secondary">
              No mock data layer — every panel reads real{" "}
              <code className="font-mono text-text-primary">/proc</code>,{" "}
              <code className="font-mono text-text-primary">/sys</code> and{" "}
              <code className="font-mono text-text-primary">dumpsys</code>{" "}
              output from the connected device.
            </p>
            <ul className="mt-6 space-y-2.5">
              {FACTS.map((fact) => (
                <li
                  key={fact}
                  className="flex items-start gap-2.5 text-sm text-text-secondary"
                >
                  <span
                    className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent"
                    aria-hidden="true"
                  />
                  {fact}
                </li>
              ))}
            </ul>
          </div>

          <div className="font-mono rounded-lg border border-border-strong bg-surface px-6 py-5 text-center">
            <div className="text-3xl font-semibold text-text-primary">
              {TEST_COUNT}
            </div>
            <div className="mt-1 text-xs text-text-tertiary">
              tests, run headlessly in CI
              <br />
              on Python 3.10 / 3.11 / 3.12
            </div>
          </div>
        </div>

        <div className="mt-12 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-4">
          {STACK.map((item) => (
            <div key={item.name} className="bg-bg p-6">
              <div className="font-display text-base font-semibold text-text-primary">
                {item.name}
              </div>
              <div className="mt-1 text-sm text-text-secondary">
                {item.role}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}