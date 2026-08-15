Real Android Task Manager screenshots are placed here as PNGs and passed as a
`src="/screenshots/<file>.png"` prop into the corresponding `ScreenshotFrame`
usage in `components/Hero.tsx`, `components/DashboardShowcase.tsx`, and
`components/ProcessInspector.tsx`.

Status:
- dashboard.png — REAL capture of the main GUI dashboard (captured from the
  packaged AndroidTaskManager.exe while connected to a Vivo V2026, Android 11).
- cpu-panel.png — pending.
- process-inspector.png — pending.

Until a slot has a real screenshot, it renders an honest "screenshot pending"
placeholder instead of a fabricated mockup.
