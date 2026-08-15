"use client";

import { useState } from "react";
import { GITHUB_URL } from "@/lib/constants";

const LINKS = [
  { href: "#features", label: "Features" },
  { href: "#connect", label: "How it works" },
  { href: GITHUB_URL, label: "GitHub", external: true },
];

export function Nav() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-bg/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <a
          href="#top"
          className="font-display flex items-center gap-2 text-[15px] font-semibold tracking-tight text-text-primary"
        >
          <span
            className="inline-block h-2 w-2 rounded-full bg-accent"
            aria-hidden="true"
          />
          Android Task Manager
        </a>

        <nav
          className="hidden items-center gap-8 md:flex"
          aria-label="Primary"
        >
          {LINKS.map((link) => (
            <a
              key={link.label}
              href={link.href}
              target={link.external ? "_blank" : undefined}
              rel={link.external ? "noopener noreferrer" : undefined}
              className="text-sm text-text-secondary transition-colors hover:text-text-primary"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <a
          href="#download"
          className="hidden rounded-md bg-text-primary px-4 py-2 text-sm font-medium text-bg transition-colors hover:bg-accent-strong md:inline-block"
        >
          Download
        </a>

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls="mobile-nav"
          aria-label={open ? "Close menu" : "Open menu"}
          className="flex h-9 w-9 items-center justify-center rounded-md border border-border text-text-secondary md:hidden"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            {open ? (
              <path
                d="M2 2L14 14M14 2L2 14"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            ) : (
              <path
                d="M1.5 4H14.5M1.5 8H14.5M1.5 12H14.5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            )}
          </svg>
        </button>
      </div>

      {open && (
        <nav
          id="mobile-nav"
          aria-label="Mobile"
          className="border-t border-border px-6 py-4 md:hidden"
        >
          <ul className="flex flex-col gap-4">
            {LINKS.map((link) => (
              <li key={link.label}>
                <a
                  href={link.href}
                  target={link.external ? "_blank" : undefined}
                  rel={link.external ? "noopener noreferrer" : undefined}
                  onClick={() => setOpen(false)}
                  className="text-sm text-text-secondary"
                >
                  {link.label}
                </a>
              </li>
            ))}
            <li>
              <a
                href="#download"
                onClick={() => setOpen(false)}
                className="inline-block rounded-md bg-text-primary px-4 py-2 text-sm font-medium text-bg"
              >
                Download
              </a>
            </li>
          </ul>
        </nav>
      )}
    </header>
  );
}
