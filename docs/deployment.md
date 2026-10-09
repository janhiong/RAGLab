# Deploy the read-only portfolio

The final milestone packages a static saved-results demo. No backend service, database, Ollama, paid API, or secret is required for this deployment. The private workspace remains available locally. The public demo contains only the original CC0 sample and checked-in provisional benchmark; do not replace the imported export with private uploaded documents.

## Netlify

Import `janhiong/RAGLab` from GitHub and select `main`. The root `netlify.toml` supplies the base directory (`apps/web`), build command, publish directory (`out`, relative to the base), Node 22, and static-only settings. The build explicitly clears the GitHub Pages path prefix and requires `out/index.html` before publishing. The Next.js runtime plugin is disabled because this deployment consists entirely of static files.

For an existing site, deploy the latest `main` commit using **Deploys → Trigger deploy → Clear cache and deploy site**. Check the log shows a Next.js production build and publishing from `apps/web/out`. A log saying **No build steps found** and deploying from `/` means Netlify published the source repository rather than the website; check that the latest commit includes the root configuration and that Netlify is building the connected `main` branch. Do not set a different configuration-file path in the site settings.

Open the production domain (for example `raglab-demo.netlify.app`) after the new deployment succeeds. Old deploy-specific URLs stay attached to their old artifacts and will continue to show the old 404. No SPA redirect is needed: Next.js exports an actual root `index.html` and a `/demo/index.html` page.

## GitHub Pages

1. In the repository's **Settings → Pages**, choose **GitHub Actions** as the source. Confirm the repository/plan permits Pages.
2. In **Actions**, open **Deploy read-only portfolio** and choose **Run workflow** on `main`.
3. Open the deployment URL reported by the successful workflow. Inspect the comparison, an expanded failure case, and mobile layout. A configured workflow or pushed commit alone is not a verified live deployment.

The workflow builds with `NEXT_PUBLIC_DEMO_ONLY=true` and `NEXT_PUBLIC_BASE_PATH=/RAGLab`, uploads `apps/web/out`, and deploys with scoped Pages/OIDC permissions. Run it again after benchmark changes. For a renamed repository or custom domain, update the base path to the actual mount path (empty for a domain root). Deployment is explicit, so code pushes do not silently republish benchmarks.

GitHub API access to Pages settings was denied in the implementation environment, including an elevated retry. Hosting activation and a live URL remain unverified; the deployment workflow and static output were validated locally. No hosting account was created and no public backend was exposed.

## Build for any static host

```bash
cd apps/web
npm ci
NEXT_PUBLIC_DEMO_ONLY=true npm run build
npm run typecheck
```

Publish `apps/web/out` on your chosen static host. This output includes `index.html`, `demo/index.html`, and `_next` assets. For hosting under a path:

```bash
NEXT_PUBLIC_DEMO_ONLY=true NEXT_PUBLIC_BASE_PATH=/RAGLab npm run build
```

Do not set `NEXT_PUBLIC_DEMO_ONLY=false` for this public deployment: the ordinary dashboard expects a private API. Static mode uses saved data and makes no API calls. No secrets belong in `NEXT_PUBLIC_*` variables. The local `/demo` page can be inspected with the normal Next.js server too.

## Verification and update procedure

Check that the root shows **Saved results · read-only**, the draft-label notice and unavailable generation status are visible, all 24 paired questions are available, and searching/filtering works with no API requests. Inspect the q09 baseline miss and recovered candidate source. Scores not measured must stay labeled **Not measured**. Test the configured path prefix and narrow screens. Hard reload the deployed page to verify assets resolve.

Update benchmark content only from real exported runs, inspect source provenance/privacy, and preserve limitations. Re-run the normal and static production builds before deploying. The existing CI now checks both build modes; backend tests retain their separate database workflow. The screenshots and short walkthrough in docs/screenshots reflect the saved portfolio, not real local-model inference.

## Private API deployment

Public API hosting is outside the static deployment. If separately hosting read-only API inspection, set `PRIVATE_UPLOADS_ENABLED=false` and `GENERATION_ENABLED=false`, restrict CORS to the actual frontend origin, provision a non-owner database role with only needed read permissions, and keep PostgreSQL/Ollama off public ports. Apply all migrations through an administrative connection. Add authentication before enabling writes. The static portfolio avoids this runtime dependency entirely.
