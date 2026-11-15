import logging
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from catalog.models import DiscRelease, Movie, Person
from catalog.providers import DiscReleaseAdapter, ProviderError, ProviderQuotaExceeded, TMDBAdapter
from catalog.services.ingest import refresh_tmdb_movie
from sync.models import SyncJob

logger = logging.getLogger(__name__)
MAX_JOB_ATTEMPTS = 3


def enqueue_job(kind: str, *, payload: dict | None = None, idempotency_key: str | None = None, available_at=None):
    if not idempotency_key:
        raise ValueError("An idempotency key is required when enqueuing sync jobs.")
    return SyncJob.objects.get_or_create(
        idempotency_key=idempotency_key[:160],
        defaults={
            "kind": kind,
            "status": SyncJob.Status.QUEUED,
            "payload": payload or {},
            "available_at": available_at or timezone.now(),
        },
    )


def enqueue_scheduled_jobs(now=None) -> int:
    if not settings.TMDB_API_KEY:
        return 0
    now = timezone.localtime(now or timezone.now())
    today = now.date()
    if now.time() < time(6, 0):
        return 0
    created = 0
    daily_jobs = (
        (SyncJob.Kind.NOW_PLAYING, "now_playing"),
        (SyncJob.Kind.UPCOMING, "upcoming"),
        (SyncJob.Kind.POPULAR, "popular"),
    )
    for kind, name in daily_jobs:
        _, was_created = enqueue_job(
            kind,
            payload={"country": "uz", "page": 1},
            idempotency_key=f"schedule:{today.isoformat()}:{name}",
            available_at=now,
        )
        created += int(was_created)

    if today.weekday() == 6 and now.time() >= time(7, 0):
        week_key = today.isocalendar().week
        for kind in (SyncJob.Kind.REFRESH_RATINGS, SyncJob.Kind.REFRESH_DISCS):
            _, was_created = enqueue_job(
                kind,
                payload={"limit": 100},
                idempotency_key=f"schedule:{today.isocalendar().year}-w{week_key}:{kind}",
                available_at=now,
            )
            created += int(was_created)
    return created


def _run_movie_list(job: SyncJob) -> int:
    country = (job.payload.get("country") or "uz").lower()
    page = max(1, int(job.payload.get("page", 1)))
    with TMDBAdapter() as adapter:
        response = adapter.movie_list(job.kind, country=country, page=page)
    results = response.get("results") or []
    for item in results:
        tmdb_id = item.get("id")
        if not tmdb_id:
            continue
        enqueue_job(
            SyncJob.Kind.ENRICH_MOVIE,
            payload={"tmdb_id": tmdb_id, "country": country},
            idempotency_key=f"{job.idempotency_key}:movie:{tmdb_id}",
        )
    return len(results)


def _run_movie_import(job: SyncJob) -> Movie:
    tmdb_id = int(job.payload.get("tmdb_id") or 0)
    if not tmdb_id:
        raise ValueError("The job requires a tmdb_id.")
    return refresh_tmdb_movie(
        tmdb_id,
        run_key=job.idempotency_key or f"job:{job.pk}",
        enabled_providers=job.payload.get("enabled_providers"),
    )


def _run_person_filmography(job: SyncJob) -> int:
    tmdb_id = int(job.payload.get("person_tmdb_id") or 0)
    if not tmdb_id:
        raise ValueError("The job requires a person_tmdb_id.")
    with TMDBAdapter() as adapter:
        person_data = adapter.person_details(tmdb_id)
        credits = adapter.person_movie_credits(tmdb_id)
    person, _ = Person.objects.update_or_create(
        tmdb_id=tmdb_id,
        defaults={
            "name": person_data.get("name") or "Unknown person",
            "biography": person_data.get("biography") or "",
            "profile_path": adapter.image_url(person_data.get("profile_path")),
        },
    )
    items = (credits.get("cast") or []) + (credits.get("crew") or [])
    queued = 0
    for item in items:
        movie_id = item.get("id")
        if not movie_id:
            continue
        _, created = enqueue_job(
            SyncJob.Kind.IMPORT_TMDB_MOVIE,
            payload={"tmdb_id": movie_id, "person_tmdb_id": tmdb_id},
            idempotency_key=f"{job.idempotency_key}:movie:{movie_id}",
        )
        queued += int(created)
    return queued


def _run_rating_refresh(job: SyncJob) -> int:
    queryset = Movie.objects.filter(tmdb_id__isnull=False).order_by("-updated_at")
    limit = min(500, max(1, int(job.payload.get("limit", 100))))
    movie_ids = list(queryset.values_list("tmdb_id", flat=True)[:limit])
    for tmdb_id in movie_ids:
        refresh_tmdb_movie(
            tmdb_id,
            run_key=f"{job.idempotency_key}:movie:{tmdb_id}",
            enabled_providers=job.payload.get("enabled_providers"),
        )
    return len(movie_ids)


def _normalized_disc_release(item: dict) -> dict | None:
    raw_format = (item.get("disc_format") or item.get("format") or "").lower()
    formats = {
        "4k": DiscRelease.Format.UHD_4K,
        "uhd": DiscRelease.Format.UHD_4K,
        "uhd_4k": DiscRelease.Format.UHD_4K,
        "4k_uhd": DiscRelease.Format.UHD_4K,
        "blu-ray": DiscRelease.Format.BLU_RAY,
        "blu_ray": DiscRelease.Format.BLU_RAY,
        "bluray": DiscRelease.Format.BLU_RAY,
    }
    disc_format = formats.get(raw_format)
    if not disc_format:
        return None
    hdr = item.get("hdr_formats") or item.get("hdr") or []
    audio = item.get("audio_formats") or item.get("audio") or []
    if isinstance(hdr, str):
        hdr = [value.strip() for value in hdr.split(",") if value.strip()]
    if isinstance(audio, str):
        audio = [value.strip() for value in audio.split(",") if value.strip()]
    raw_release_date = item.get("release_date") or ""
    try:
        release_date = date.fromisoformat(raw_release_date[:10]) if raw_release_date else None
    except ValueError:
        release_date = None
    return {
        "disc_format": disc_format,
        "country": (item.get("country") or "").lower()[:2],
        "hdr_formats": hdr,
        "audio_formats": audio,
        "region_code": item.get("region_code") or item.get("region") or "",
        "edition_name": item.get("edition_name") or item.get("edition") or "Standard",
        "release_date": release_date,
        "source": item.get("source") or "disc",
        "source_url": item.get("source_url") or item.get("url") or "",
        "checked_at": timezone.now(),
    }


def _run_disc_refresh(job: SyncJob) -> int:
    if not settings.DISC_API_BASE_URL:
        logger.info("Disc refresh skipped: no disc API endpoint is configured.")
        return 0
    queryset = Movie.objects.filter(tmdb_id__isnull=False).order_by("-updated_at")
    limit = min(500, max(1, int(job.payload.get("limit", 100))))
    movies = list(queryset[:limit])
    updated = 0
    with DiscReleaseAdapter() as adapter:
        for movie in movies:
            releases = adapter.search_releases(
                tmdb_id=movie.tmdb_id,
                imdb_id=movie.imdb_id or "",
                title=movie.title_original,
            )
            for item in releases:
                defaults = _normalized_disc_release(item)
                if defaults is None:
                    continue
                release_date = defaults.pop("release_date")
                lookup = {
                    "movie": movie,
                    "country": defaults["country"],
                    "disc_format": defaults["disc_format"],
                    "edition_name": defaults["edition_name"],
                    "source": defaults["source"],
                }
                DiscRelease.objects.update_or_create(
                    **lookup,
                    defaults={**defaults, "release_date": release_date},
                )
                updated += 1
    return updated


def requeue_stale_jobs(*, stale_after: timedelta = timedelta(minutes=30)) -> int:
    now = timezone.now()
    return SyncJob.objects.filter(
        status=SyncJob.Status.RUNNING,
        started_at__lt=now - stale_after,
    ).update(
        status=SyncJob.Status.QUEUED,
        available_at=now,
        started_at=None,
        last_error="Recovered after worker interruption; retrying idempotently.",
    )


def dispatch_job(job: SyncJob):
    if job.kind in {SyncJob.Kind.NOW_PLAYING, SyncJob.Kind.UPCOMING, SyncJob.Kind.POPULAR}:
        return _run_movie_list(job)
    if job.kind in {SyncJob.Kind.ENRICH_MOVIE, SyncJob.Kind.IMPORT_TMDB_MOVIE}:
        return _run_movie_import(job)
    if job.kind == SyncJob.Kind.IMPORT_PERSON_FILMOGRAPHY:
        return _run_person_filmography(job)
    if job.kind == SyncJob.Kind.REFRESH_RATINGS:
        return _run_rating_refresh(job)
    if job.kind == SyncJob.Kind.REFRESH_DISCS:
        return _run_disc_refresh(job)
    raise ValueError(f"No handler registered for sync job kind: {job.kind}")


def claim_next_job():
    requeue_stale_jobs()
    now = timezone.now()
    with transaction.atomic():
        job = SyncJob.objects.filter(
            status=SyncJob.Status.QUEUED,
            available_at__lte=now,
        ).order_by("available_at", "created_at").first()
        if job is None:
            return None
        claimed = SyncJob.objects.filter(pk=job.pk, status=SyncJob.Status.QUEUED).update(
            status=SyncJob.Status.RUNNING,
            started_at=now,
            attempts=F("attempts") + 1,
        )
        if not claimed:
            return None
        job.refresh_from_db()
        return job


def _defer_until_tomorrow(job: SyncJob) -> None:
    local_now = timezone.localtime()
    tomorrow = local_now.date() + timedelta(days=1)
    local_midnight = datetime.combine(tomorrow, time.min, tzinfo=local_now.tzinfo)
    job.status = SyncJob.Status.DEFERRED
    job.available_at = local_midnight
    job.last_error = "OMDb daily quota reached; retry scheduled for tomorrow."
    job.completed_at = None
    job.save(update_fields=["status", "available_at", "last_error", "completed_at", "updated_at"])


def process_next_job() -> SyncJob | None:
    job = claim_next_job()
    if job is None:
        return None
    try:
        result = dispatch_job(job)
    except ProviderQuotaExceeded:
        _defer_until_tomorrow(job)
    except (ProviderError, ValueError) as exc:
        job.last_error = str(exc)[:4000]
        job.completed_at = None
        if job.attempts < MAX_JOB_ATTEMPTS:
            job.status = SyncJob.Status.QUEUED
            job.available_at = timezone.now() + timedelta(seconds=30 * (2 ** (job.attempts - 1)))
        else:
            job.status = SyncJob.Status.FAILED
            job.completed_at = timezone.now()
        job.save(update_fields=["status", "available_at", "last_error", "completed_at", "updated_at"])
        logger.warning("Sync job %s failed: %s", job.pk, exc)
    except Exception as exc:
        job.status = SyncJob.Status.FAILED
        job.last_error = str(exc)[:4000]
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "last_error", "completed_at", "updated_at"])
        logger.exception("Unexpected sync job failure: %s", job.pk)
    else:
        job.status = SyncJob.Status.SUCCEEDED
        job.last_error = ""
        job.completed_at = timezone.now()
        if isinstance(result, int):
            job.payload = {**job.payload, "result_count": result}
        job.save(update_fields=["status", "last_error", "completed_at", "payload", "updated_at"])
    return job