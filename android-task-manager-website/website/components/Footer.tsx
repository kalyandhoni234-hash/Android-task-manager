import { GITHUB_URL } from "@/lib/constants";

export function Footer() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-10 text-sm text-text-tertiary sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <span
            className="inline-block h-1.5 w-1.5 rounded-full bg-accent"
            aria-hidden="true"
          />
          <span>Android Task Manager</span>
        </div>
        <div className="flex flex-wrap items-center gap-6">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-text-primary"
          >
            GitHub
          </a>
          <a
            href={`${GITHUB_URL}/blob/master/LICENSE`}
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-text-primary"
          >
            MIT License
          </a>
          <span>Monitoring + device actions · No accounts</span>
        </div>
      </div>
    </footer>
  );
}
