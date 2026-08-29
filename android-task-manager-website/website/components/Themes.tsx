const THEMES = [
  {
    name: "Dark",
    description: "The default desktop look — calm dark surfaces for long sessions.",
  },
  {
    name: "Light",
    description: "A high-contrast light theme for bright environments.",
  },
  {
    name: "System",
    description: "Follows your operating system's light or dark preference.",
  },
  {
    name: "Cyber",
    description: "A neon-accented theme for the dashboard.",
  },
];

export function Themes() {
  return (
    <section id="themes" className="bg-bg border-b border-border">
      <div className="mx-auto max-w-5xl px-6 py-24">
        <div className="max-w-2xl">
          <span className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
            Themes
          </span>
          <h2 className="mt-3 font-display text-balance text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
            Four themes, your preference.
          </h2>
          <p className="mt-4 text-base leading-relaxed text-text-secondary">
            Switch between Dark, Light, System and Cyber from Settings. The
            selection is persistent and applied across every page of the
            dashboard.
          </p>
        </div>

        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {THEMES.map((theme) => (
            <div
              key={theme.name}
              className="rounded-xl border border-border bg-bg-raised p-5"
            >
              <h3 className="font-display text-base font-semibold text-text-primary">
                {theme.name}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                {theme.description}
              </p>
            </div>
          ))}
        </div>

        <p className="mt-8 text-sm text-text-tertiary">
          The dashboard screenshot in the showcase reflects the active theme —
          only the Dark theme capture is shown above; the others change the
          color treatment, not the layout.
        </p>
      </div>
    </section>
  );
}
