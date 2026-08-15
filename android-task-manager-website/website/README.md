# Android Task Manager — product website

Product / download site for
[Android Task Manager](https://github.com/kalyandhoni234-hash/Android-task-manager),
an Android system monitor for Windows (64-bit) that talks to the device over
ADB. The site is the user-facing download experience: the primary CTA links
directly to the versioned Windows EXE published as a GitHub Release asset.

Built with Next.js (App Router, static export), React, TypeScript and
Tailwind CSS.

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

`npm run build` produces a fully static export in `out/` (see
`next.config.ts`), ready for GitHub Pages.

## Deployment

The site deploys to GitHub Pages
(`https://kalyandhoni234-hash.github.io/Android-task-manager/`) via
`.github/workflows/deploy-pages.yml` (push to `master` touching
`android-task-manager-website/website/**`, or `workflow_dispatch`). The
`basePath` in `next.config.ts` matches the Pages subdirectory; the canonical
SITE_URL in `lib/constants.ts` points at the Pages URL and can be overridden
with the `SITE_URL` build-time environment variable when a custom domain is
added.

### Repository settings requirement

The repository's Pages publishing source MUST be **GitHub Actions**
(Settings → Pages → Build and deployment → Source). A "Deploy from a branch"
source serving the repository root would render the README instead of this
site; the README must remain in the repository.

## Release facts

The download section's version / file size / SHA-256 come from
`lib/constants.ts` and are filled in from the exact artifact of the current
GitHub Release (built by `.github/workflows/release.yml`) — never from a
local build. `TEST_COUNT` is updated from an actual
`python -m pytest --collect-only -q` run.

Screenshots: real application screenshots are added as PNGs under
`public/screenshots/` and passed as `src` props into `ScreenshotFrame`.
Until then, each slot renders an honest "screenshot pending" placeholder.