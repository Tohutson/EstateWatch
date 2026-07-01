# Agent Guidance

- Inspect the existing architecture before changing code.
- Keep the system single-process and simple. Do not add Redis, Celery, queues, Kubernetes, or services.
- Preserve idempotency: reruns must not duplicate image analysis or email notifications.
- Keep EstateSales.NET behavior isolated in `src/estate_sale_finder/sources/estatesales_net.py`.
- Add fixture-based parser tests whenever sale-page or API parsing changes.
- Current targets are only golf clubs, golf bags, golf balls, modern digital cameras, and modern camera lenses.
- Never commit secrets, `.env`, database files, thumbnails, model caches, or live credentials.
- Run formatting, Ruff, mypy, tests, CLI help, and migrations before handing work back.
- Update Alembic migrations when the schema changes.
- Update the README for operational changes.
- Commit work in focused, descriptive commits when commits are requested.
- Avoid TODOs unless blocked by an external dependency; document the blocker and runtime behavior.
- Document assumptions, especially around undocumented EstateSales.NET endpoints.
