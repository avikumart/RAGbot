# Frontend

The browser application is isolated in `frontend/`.

| Location | Responsibility |
| --- | --- |
| `frontend/app/` | App Router pages, styles, and server-side proxy routes. |
| `frontend/components/` | Reusable document-library UI. |
| `frontend/lib/` | Typed browser API client. |
| `frontend/public/` | Public static assets, including the social preview image. |
| `frontend/tests/` | Node rendering/client tests and Playwright browser tests. |
| `frontend/worker/` | Cloudflare worker entrypoint used by the Vite build. |
| `frontend/db/` and `frontend/drizzle/` | Optional D1 schema and generated migrations for the hosted frontend. |

## Commands

Run commands from the repository root. The package scripts enter `frontend/` automatically.

```bash
npm run dev
npm run lint
npm test
npm run test:e2e
```

Install Playwright Chromium once before the end-to-end test:

```bash
npx playwright install chromium
```

## Backend boundary

The browser never supplies a user identifier directly to FastAPI. The frontend route handlers under `frontend/app/api/` proxy chat and session calls, derive an opaque owner identity, and sign it with `AUTH_PROXY_SECRET`. Browser document and people requests use the configured API URL. Keep production API access behind this frontend proxy; direct public FastAPI access is not an authorization boundary.

## Build configuration

`frontend/vite.config.ts` is the frontend build entrypoint. Supporting tool configuration is grouped in `frontend/config/`; `frontend/tsconfig.json` remains beside the app so the build can discover TypeScript paths. The root `package.json`, Docker files, and Compose manifest are intentionally kept at the repository root because they orchestrate the entire stack.
