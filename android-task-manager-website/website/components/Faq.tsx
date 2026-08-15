const FAQ_ITEMS = [
  {
    q: "Does Android Task Manager require Python?",
    a: "The packaged Windows application does not require the user to install Python.",
  },
  {
    q: "Does it require ADB?",
    a: "Yes. Android Task Manager communicates with Android through ADB. The application can help locate an existing adb.exe.",
  },
  {
    q: "Does it modify my phone?",
    a: "Current monitoring functionality is read-only.",
  },
  {
    q: "Does it require root?",
    a: "This has not been verified across devices, so no blanket root / no-root claim is made here — see the GitHub repository for current details.",
  },
  {
    q: "What platforms are supported?",
    a: "The packaged application currently targets Windows 10/11 x64.",
  },
  {
    q: "Is it open source?",
    a: "Yes — MIT licensed, on GitHub.",
  },
];

export function Faq() {
  return (
    <section className="border-b border-border bg-bg-raised">
      <div className="mx-auto max-w-3xl px-6 py-24">
        <p className="font-mono text-center text-xs uppercase tracking-[0.2em] text-accent-strong">
          FAQ
        </p>
        <h2 className="font-display text-balance mt-3 text-center text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
          Common questions.
        </h2>

        <dl className="mt-12 divide-y divide-border border-t border-border">
          {FAQ_ITEMS.map((item) => (
            <div key={item.q} className="py-6">
              <dt className="text-base font-medium text-text-primary">
                {item.q}
              </dt>
              <dd className="mt-2 text-sm leading-relaxed text-text-secondary">
                {item.a}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
