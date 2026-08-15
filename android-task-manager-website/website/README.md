# Android Task Manager — product website

Marketing / product site for
[Android Task Manager](https://github.com/kalyandhoni234-hash/Android-task-manager),
a read-only Android system monitor for Windows 10/11 x64 that talks to the
device over ADB.

Built with Next.js (App Router), React, TypeScript and Tailwind CSS.

## Development

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Checks

```bash
npm run lint
npm run build
```

## Deployment notes

- No production domain is deployed yet. The site intentionally emits no
  absolute canonical / Open Graph URLs. Set `SITE_URL` (e.g.
  `https://android-task-manager.example`) when deploying to opt in.
- The download CTA points at the GitHub repository: no public release asset
  exists yet. There is an intentional placeholder state in
  `components/ScreenshotFrame.tsx` — real application screenshots will be
  added later as PNGs under `public/screenshots/` and passed as `src` props.