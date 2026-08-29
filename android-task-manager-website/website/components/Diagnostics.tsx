const SEVERITIES = [
  {
    name: "INFO",
    description: "Context worth knowing — no action required.",
  },
  {
    name: "WARNING",
    description: "Something is off; look at it soon.",
  },
  {
    name: "CRITICAL",
    description: "Needs attention now.",
  },
];

const EXAMPLE = {
  severity: "WARNING",
  what: "Memory pressure is elevated",
  why: "Available memory has stayed below the healthy threshold for the last few samples.",
  evidence: "MemAvailable ≈ 380 MB of 5.5 GB (7%) over the last 60 s.",
  action: "Close background apps or restart heavier ones; check the Processes panel for top consumers.",
};

export function Diagnostics() {
  return (
    <section id="diagnostics" className="bg-bg border-b border-border">
      <div className="mx-auto max-w-5xl px-6 py-24">
        <div className="max-w-2xl">
          <span className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
            Diagnostics
          </span>
          <h2 className="mt-3 font-display text-balance text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
            Explainable findings, not a mystery score.
          </h2>
          <p className="mt-4 text-base leading-relaxed text-text-secondary">
            The Diagnostics engine turns the live CPU, memory, battery, storage
            and security snapshots into individual, evidence-based findings. Each
            one carries a clear severity, the raw evidence behind it, and a
            recommended action — so you can see exactly why a conclusion was
            reached.
          </p>
        </div>

        <div className="mt-10 grid gap-4 sm:grid-cols-3">
          {SEVERITIES.map((severity) => (
            <div
              key={severity.name}
              className="rounded-xl border border-border bg-bg-raised p-5"
            >
              <div className="font-mono text-xs font-semibold tracking-[0.1em] text-accent-strong">
                {severity.name}
              </div>
              <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                {severity.description}
              </p>
            </div>
          ))}
        </div>

        <div className="mt-10 rounded-xl border border-border-strong bg-surface p-6">
          <div className="flex items-center gap-3">
            <span className="font-mono rounded border border-border-strong px-2 py-0.5 text-[10px] text-text-tertiary">
              {EXAMPLE.severity}
            </span>
            <span className="font-display text-base font-semibold text-text-primary">
              {EXAMPLE.what}
            </span>
          </div>
          <dl className="mt-5 grid gap-x-6 gap-y-4 sm:grid-cols-[auto_1fr]">
            <dt className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-tertiary">
              Why
            </dt>
            <dd className="text-sm text-text-secondary">{EXAMPLE.why}</dd>
            <dt className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-tertiary">
              Evidence
            </dt>
            <dd className="font-mono text-xs text-text-secondary">
              {EXAMPLE.evidence}
            </dd>
            <dt className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-tertiary">
              Action
            </dt>
            <dd className="text-sm text-text-secondary">{EXAMPLE.action}</dd>
          </dl>
        </div>

        <p className="mt-8 text-sm text-text-tertiary">
          Missing data yields no finding — never an invented one. An absence of
          findings is shown honestly as &quot;no issues detected&quot;, not as proof of
          health.
        </p>
      </div>
    </section>
  );
}
