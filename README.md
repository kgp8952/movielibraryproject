# Kino

Kino is a Django movie library and release tracker. The initial project is split into three Django apps:

- `catalog`: movie, person, credit, rating history, release, disc, and streaming data.
- `library`: user watch state, owned discs, and custom collections.
- `sync`: queued sync bookkeeping and provider-call metrics.

Provider HTTP behavior is defined in `catalog.providers.ProviderAdapter`. Implementations should normalize provider-specific movie payloads, use its validated JSON request path, and catch `ProviderError` at the service/view boundary so an unavailable provider never breaks a page.

## Local setup

1. Copy `.env.example` to `.env` and set a private `DJANGO_SECRET_KEY`.
2. Create a virtual environment and install `requirements.txt`.
3. Run `python manage.py migrate` and `python manage.py runserver`.

`docker compose up --build` starts the web and sync-worker services. Both containers mount the same named `kino-data` volume for SQLite at `/data/kino.sqlite3`. The worker currently provides a runnable polling shell; scheduled task registration and provider-specific job handlers are the next implementation step.