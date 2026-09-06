# Repository Guidelines

## Project Structure

SxDevOps is split into `backend/` and `frontend/`.

- `backend/` is a Django project. Shared settings live in `backend/sxdevops/`; domain apps include `ops/`, `marketplace/`, `sqlaudit/`, `iac/`, `multicloud/`, `aiops/`, `rbac/`, and `eventwall/`.
- `frontend/src/` contains the Vue 3 app. Views live in `frontend/src/views/`, layout in `frontend/src/layout/`, API wrappers in `frontend/src/api/`, routes in `frontend/src/router/`, and stores in `frontend/src/stores/`.
- `docs/` is reserved for public-facing product and architecture documentation.
- Treat `frontend/dist/`, `frontend/node_modules/`, `backend/__pycache__/`, runtime logs, local SQLite databases, and temporary screenshots as generated artifacts.

## Development Commands

Backend:

```bash
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python manage.py seed_templates
python -m daphne -b 0.0.0.0 -p 8000 sxdevops.asgi:application
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Build and test:

```bash
cd backend && python manage.py test
cd frontend && npm run build
docker compose up -d --build
```

## Coding Style

- Python uses 4-space indentation, snake_case modules and app-local helpers.
- Vue view and layout files use PascalCase filenames, for example `K8sManage.vue`.
- API, store and utility modules use lower-case filenames, for example `request.js` and `app.js`.
- No formatter or linter is committed; match the surrounding style and remove unused imports.

## Frontend UI Convention

Management and console pages should follow the existing Feishu-style workbench rhythm used by pages such as `TaskWorkbench.vue`, `Deployments.vue`, `K8sManage.vue`, `ContainerManage.vue`, and `MiddlewareManage.vue`.

- Use a compact top hero with the main title on the first row only.
- Follow the `hero + stats cards + compact hint strip + tabs/content` pattern when applicable.
- Reuse the `release-stat-card` visual language for top metrics.
- Put environment, cluster, namespace, domain and similar filters in compact toolbars near tabs or top controls.
- Avoid old `page-header` blocks, duplicate inner stats and oversized marketing-style sections in operational pages.

## RBAC Convention

Any feature that adds or changes permissions, route guards, menu visibility, page actions or WebSocket access must update backend enforcement first.

Key references:

- `backend/rbac/registry.py`
- `backend/rbac/permissions.py`
- `frontend/src/router/index.js`
- `frontend/src/layout/AppLayout.vue`
- `frontend/src/stores/auth.js`

Frontend hiding is only a mirror of backend permissions, not a security boundary.

## Chinese Text And Encoding

- Source files containing Chinese text must be saved as UTF-8.
- Preserve readable Chinese in comments, labels, tooltips, alerts, API responses and operation logs.
- If a task touches Chinese UI or API text, run a quick mojibake scan before finishing.
- Do not paste terminal output back into source files when terminal encoding is uncertain.

## Documentation

Public docs should describe the mature product and core architecture. Avoid keeping temporary process notes, private presentation drafts, local runtime logs, database backups, or one-off verification screenshots in git.

README-facing screenshots should be captured from the running product and stored under `docs/screenshots/`.

## Security

`backend/sxdevops/settings.py` supports local defaults, but production deployments should set `SECRET_KEY`, `DEBUG=0`, `ALLOWED_HOSTS`, database credentials and Redis URLs explicitly. Do not commit production secrets, real credentials, Kubeconfig files, SSH keys, customer data, host-specific endpoints or private tokens.
