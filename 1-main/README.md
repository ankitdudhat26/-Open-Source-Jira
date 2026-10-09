# 1 · Main app

Everything the Main panel needs: the frontend, the backend, the database and the supporting services.

| Folder | What it is | Local URL |
|---|---|---|
| `frontend/` | Main web app (React Router + Vite). Package name: `web` | http://localhost:3000 |
| `backend/` | Django REST API, Celery workers and the database models/migrations. Serves both the Main app and the Admin panel | http://localhost:8000 |
| `database/` | Postgres, Redis, RabbitMQ and MinIO setup, plus database notes | — |
| `space/` | Public pages for published projects. Package name: `space` | http://localhost:3002/spaces |
| `live/` | Real-time collaborative editing server. Package name: `live` | http://localhost:3100/live |
| `proxy/` | Caddy reverse proxy used in production (routes `/`, `/api`, `/god-mode`, …) | — |

Shared code used by both the Main app and the Admin panel lives in `../packages/`.

## Run

From the repository root:

```bash
./run-local.sh              # services + backend + all frontends (incl. Admin)
./run-local.sh backend      # services + backend only
pnpm dev --filter=web       # Main frontend only
```
