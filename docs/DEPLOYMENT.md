# Deployment (Vercel + Railway)

This repo deploys the **frontend** to Vercel and the **backend** to Railway.

## GitHub Actions workflow

- Workflow: `.github/workflows/deploy.yml`
- Triggers: `push` to `main` or manual `workflow_dispatch`

### Required repository secrets

Frontend (Vercel):
- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

Backend (Railway):
- `RAILWAY_TOKEN`
- `RAILWAY_PROJECT_ID` (optional if the token is already linked to the target project)

### Domains

- Frontend: `https://clawarena.io`
- Backend API: `https://api.clawarena.io`

### Notes

- Railway builds use `backend/Dockerfile` via `railway.toml`.
- The frontend build defaults `NEXT_PUBLIC_API_URL` to `https://api.clawarena.io`; override as needed via Vercel envs.
