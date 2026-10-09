# 2 · Admin panel

| Folder | What it is | Local URL |
|---|---|---|
| `admin/` | Instance admin panel ("God mode"): instance setup, authentication, email, AI and image settings. Package name: `admin` | http://localhost:3001/god-mode |

The Admin panel has no backend or database of its own. It uses the same Django API and Postgres database as the Main app (`../1-main/backend`, `../1-main/database`), and the shared code in `../packages/`.

## Run

From the repository root:

```bash
./run-local.sh                # everything, including the Admin panel
pnpm dev --filter=admin       # Admin frontend only (needs the backend running)
```
