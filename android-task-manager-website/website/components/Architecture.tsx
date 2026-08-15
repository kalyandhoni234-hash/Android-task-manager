const INTERFACES = [
  "/proc/stat",
  "/proc/meminfo",
  "/proc/<pid>",
  "/proc/net/dev",
  "cpufreq sysfs",
  "dumpsys battery",
  "ADB",
];

const COLLECTORS = ["CPU", "Memory", "Processes", "Battery", "Network"];

export function Architecture() {
  return (
    <section className="border-b border-border">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <div className="grid gap-14 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
              Architecture
            </p>
            <h2 className="font-display text-balance mt-3 text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
              Built close to the system.
            </h2>
            <p className="mt-4 max-w-md text-base leading-relaxed text-text-secondary">
              Every collector talks to the device through a single
              centralized ADB layer. Raw output is parsed into normalized
              models before it ever reaches a renderer — the terminal and GUI
              never touch ADB or parse device text themselves.
            </p>

            <p className="font-mono mt-8 text-xs uppercase tracking-[0.2em] text-text-tertiary">
              Interfaces used
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {INTERFACES.map((item) => (
                <span
                  key={item}
                  className="font-mono rounded-md border border-border-strong bg-surface px-2.5 py-1 text-[11px] text-text-secondary"
                >
                  {item}
                </span>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-border bg-bg-raised p-6 sm:p-10">
            <svg
              viewBox="0 0 480 380"
              className="w-full"
              role="img"
              aria-label="Architecture diagram: Android device connects over ADB to a Connection Manager, which feeds CPU, Memory, Process, Battery and Network collectors, which normalize data into a shared model layer that both the Terminal renderer and the GUI Desktop Dashboard read from."
            >
              <g
                fontFamily="var(--font-mono)"
                fontSize="12"
                fill="var(--text-secondary)"
              >
                <rect
                  x="150"
                  y="8"
                  width="180"
                  height="40"
                  rx="6"
                  fill="var(--surface)"
                  stroke="var(--border-strong)"
                />
                <text x="240" y="33" textAnchor="middle" fill="var(--text-primary)">
                  Android Device
                </text>

                <line x1="240" y1="48" x2="240" y2="78" stroke="var(--border-strong)" />
                <text x="252" y="66" fill="var(--accent-strong)">
                  ADB
                </text>

                <rect
                  x="130"
                  y="80"
                  width="220"
                  height="40"
                  rx="6"
                  fill="var(--surface)"
                  stroke="var(--accent-border)"
                />
                <text x="240" y="105" textAnchor="middle" fill="var(--text-primary)">
                  Connection Manager
                </text>

                <line x1="240" y1="120" x2="240" y2="140" stroke="var(--border-strong)" />
                <line x1="60" y1="140" x2="420" y2="140" stroke="var(--border-strong)" />

                {COLLECTORS.map((name, i) => {
                  const boxWidth = 76;
                  const x = 22 + i * 90;
                  const cx = x + boxWidth / 2;
                  return (
                    <g key={name}>
                      <line
                        x1={cx}
                        y1="140"
                        x2={cx}
                        y2="160"
                        stroke="var(--border-strong)"
                      />
                      <rect
                        x={x}
                        y="160"
                        width={boxWidth}
                        height="36"
                        rx="6"
                        fill="var(--bg-raised)"
                        stroke="var(--border-strong)"
                      />
                      <text x={cx} y="182" textAnchor="middle" fontSize="11" fill="var(--text-secondary)">
                        {name}
                      </text>
                      <line
                        x1={cx}
                        y1="196"
                        x2={240}
                        y2="230"
                        stroke="var(--border)"
                      />
                    </g>
                  );
                })}

                <rect
                  x="110"
                  y="230"
                  width="260"
                  height="40"
                  rx="6"
                  fill="var(--surface)"
                  stroke="var(--border-strong)"
                />
                <text x="240" y="255" textAnchor="middle" fill="var(--text-primary)">
                  Normalized Models
                </text>

                <line x1="240" y1="270" x2="240" y2="290" stroke="var(--border-strong)" />
                <line x1="150" y1="290" x2="330" y2="290" stroke="var(--border-strong)" />
                <line x1="150" y1="290" x2="150" y2="310" stroke="var(--border-strong)" />
                <line x1="330" y1="290" x2="330" y2="310" stroke="var(--border-strong)" />

                <rect
                  x="90"
                  y="310"
                  width="120"
                  height="40"
                  rx="6"
                  fill="var(--bg-raised)"
                  stroke="var(--border-strong)"
                />
                <text x="150" y="335" textAnchor="middle" fill="var(--text-primary)">
                  Terminal
                </text>

                <rect
                  x="270"
                  y="310"
                  width="120"
                  height="40"
                  rx="6"
                  fill="var(--bg-raised)"
                  stroke="var(--accent-border)"
                />
                <text x="330" y="335" textAnchor="middle" fill="var(--text-primary)">
                  GUI Dashboard
                </text>
              </g>
            </svg>
          </div>
        </div>
      </div>
    </section>
  );
}
