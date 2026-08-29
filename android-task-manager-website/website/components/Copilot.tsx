import { GITHUB_URL } from "@/lib/constants";

const EXAMPLES = [
  "Why is my phone slow?",
  "What's using my RAM?",
  "Why is my battery draining?",
  "Explain my health",
];

export function Copilot() {
  return (
    <section id="copilot" className="bg-bg-raised border-y border-border">
      <div className="mx-auto max-w-5xl px-6 py-24">
        <div className="max-w-2xl">
          <span className="font-mono text-xs uppercase tracking-[0.2em] text-accent-strong">
            AI Copilot · Gemini
          </span>
          <h2 className="mt-3 font-display text-balance text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
            Ask your device what&apos;s going on.
          </h2>
          <p className="mt-4 text-base leading-relaxed text-text-secondary">
            The in-app Copilot is an assistant that helps you understand your
            device, diagnose problems and make sense of what you are seeing. It
            is powered by Google&apos;s Gemini API and grounded in your live device
            context — CPU, memory, processes, the current page and the
            diagnostics findings — plus the conversation so far.
          </p>
        </div>

        <div className="mt-10 grid gap-6 md:grid-cols-2">
          <div className="rounded-xl border border-border bg-bg p-6">
            <h3 className="font-display text-lg font-semibold text-text-primary">
              It explains, it doesn&apos;t act
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-text-secondary">
              The Copilot is advisory, not autonomous. It answers questions and
              suggests next steps — it never controls your device or runs
              commands on your behalf. The dashboard keeps sampling while a
              request is in flight, on a background worker thread.
            </p>
          </div>

          <div className="rounded-xl border border-border bg-bg p-6">
            <h3 className="font-display text-lg font-semibold text-text-primary">
              Your key, your computer
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-text-secondary">
              You provide a Gemini API key, stored locally in your user-data
              directory and sent only to the Gemini API. A Test Connection
              button validates it before you rely on it. API errors map to clear
              messages — the app never crashes on a Copilot failure.
            </p>
          </div>
        </div>

        <div className="mt-10">
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-text-tertiary">
            Try asking
          </p>
          <ul className="mt-4 flex flex-wrap gap-3">
            {EXAMPLES.map((example) => (
              <li
                key={example}
                className="rounded-full border border-border-strong px-4 py-2 text-sm text-text-secondary"
              >
                {example}
              </li>
            ))}
          </ul>
        </div>

        <p className="mt-10 text-sm text-text-tertiary">
          The Copilot is optional. Enable it from{" "}
          <span className="text-text-secondary">Settings → Configure API Key</span>{" "}
          or the AI Copilot page. See the{" "}
          <a
            href={`${GITHUB_URL}#ai-copilot-setup`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent-strong underline decoration-accent-border underline-offset-2 hover:text-text-primary"
          >
            README
          </a>{" "}
          for setup details.
        </p>
      </div>
    </section>
  );
}
