import logging
from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.text import slugify

from catalog.models import Credit, Genre, Movie, Person, Rating, ReleaseDate, StreamingAvailability
from catalog.providers import KinopoiskAdapter, OMDbAdapter, ProviderError, ProviderQuotaExceeded, TMDBAdapter

logger = logging.getLogger(__name__)

TMDB_RELEASE_TYPES = {
    3: ReleaseDate.ReleaseType.THEATRICAL,
    4: ReleaseDate.ReleaseType.DIGITAL,
    5: ReleaseDate.ReleaseType.PHYSICAL,
}
TMDB_STREAMING_TYPES = {
    "flatrate": StreamingAvailability.Type.SUBSCRIPTION,
    "free": StreamingAvailability.Type.FREE,
    "ads": StreamingAvailability.Type.ADS,
    "rent": StreamingAvailability.Type.RENT,
    "buy": StreamingAvailability.Type.BUY,
}


def _snapshot_key(run_key: str, source: str) -> str:
    return f"{run_key or uuid4().hex}:{source}"[:160]


def append_rating_snapshot(movie: Movie, data: dict, *, run_key: str) -> tuple[Rating, bool]:
    score = Decimal(str(data["score"])).quantize(Decimal("0.01"))
    if not Decimal("0") <= score <= Decimal("100"):
        raise ValueError("Normalized rating score must be between 0 and 100.")
    source = data["source"]
    return Rating.objects.get_or_create(
        snapshot_key=_snapshot_key(run_key, source),
        defaults={
            "movie": movie,
            "source": source,
            "score": score,
            "raw_score": str(data.get("raw_score", ""))[:32],
            "vote_count": data.get("vote_count"),
        },
    )


def _parse_release_date(value: str | None):
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _upsert_movie_fields(payload: dict) -> Movie:
    tmdb_id = payload.get("tmdb_id")
    imdb_id = payload.get("imdb_id") or None
    kinopoisk_id = str(payload.get("kinopoisk_id") or "") or None
    movie = Movie.objects.filter(tmdb_id=tmdb_id).first() if tmdb_id else None
    if movie is None and imdb_id:
        movie = Movie.objects.filter(imdb_id=imdb_id).first()
    if movie is None and kinopoisk_id:
        movie = Movie.objects.filter(kinopoisk_id=kinopoisk_id).first()
    defaults = {
        key: payload.get(key)
        for key in (
            "title_original", "title_en", "title_ru", "title_uz", "original_language",
            "release_year", "runtime_minutes", "certification", "overview_en", "overview_ru",
            "overview_uz", "poster_path", "backdrop_path", "popularity",
        )
        if payload.get(key) not in (None, "")
    }
    if "title_original" not in defaults:
        defaults["title_original"] = payload.get("title_en") or payload.get("title_ru") or "Untitled"
    if movie is None:
        create_values = dict(defaults)
        create_values.update({"tmdb_id": tmdb_id, "imdb_id": imdb_id, "kinopoisk_id": kinopoisk_id})
        try:
            movie = Movie.objects.create(**create_values)
        except IntegrityError:
            movie = Movie.objects.get(tmdb_id=tmdb_id) if tmdb_id else Movie.objects.get(imdb_id=imdb_id)
    else:
        for key, value in defaults.items():
            setattr(movie, key, value)
        if tmdb_id and not movie.tmdb_id:
            movie.tmdb_id = tmdb_id
        if imdb_id and not movie.imdb_id:
            movie.imdb_id = imdb_id
        if kinopoisk_id and not movie.kinopoisk_id:
            movie.kinopoisk_id = kinopoisk_id
        movie.save()
    return movie


def _sync_genres(movie: Movie, genre_data: list[dict]) -> None:
    for data in genre_data:
        name = (data.get("name") or "").strip()
        if not name:
            continue
        slug = slugify(name) or f"genre-{data.get('id', uuid4().hex[:8])}"
        genre, _ = Genre.objects.get_or_create(slug=slug, defaults={"name": name})
        movie.genres.add(genre)


def _upsert_person(data: dict) -> Person | None:
    tmdb_id = data.get("id") or data.get("tmdb_id")
    name = data.get("name")
    if not tmdb_id or not name:
        return None
    person, _ = Person.objects.update_or_create(
        tmdb_id=tmdb_id,
        defaults={
            "name": name,
            "profile_path": TMDBAdapter.image_url(data.get("profile_path")),
            "biography": data.get("biography") or "",
        },
    )
    return person


def _sync_credits(movie: Movie, payload: dict) -> None:
    credits = payload.get("credits") or {}
    cast = (credits.get("cast") or [])[:10]
    for index, person_data in enumerate(cast):
        person = _upsert_person(person_data)
        if person:
            Credit.objects.update_or_create(
                movie=movie,
                person=person,
                role=Credit.Role.CAST,
                defaults={"character_name": person_data.get("character") or "", "credit_order": index},
            )

    crew_roles = {"director": Credit.Role.DIRECTOR, "writer": Credit.Role.WRITER, "screenplay": Credit.Role.WRITER, "story": Credit.Role.WRITER}
    for person_data in credits.get("crew") or []:
        role = crew_roles.get((person_data.get("job") or "").lower())
        person = _upsert_person(person_data) if role else None
        if person:
            Credit.objects.get_or_create(
                movie=movie,
                person=person,
                role=role,
                defaults={"credit_order": person_data.get("order") or 0},
            )


def _sync_release_dates(movie: Movie, payload: dict) -> None:
    results = (payload.get("release_dates") or {}).get("results") or []
    for country_data in results:
        country = (country_data.get("iso_3166_1") or "").lower()
        if len(country) != 2:
            continue
        for item in country_data.get("release_dates") or []:
            release_type = TMDB_RELEASE_TYPES.get(item.get("type"))
            release_date = _parse_release_date(item.get("release_date"))
            if not release_type or not release_date:
                continue
            ReleaseDate.objects.get_or_create(
                movie=movie,
                country=country,
                release_type=release_type,
                release_date=release_date,
                defaults={"source": "tmdb"},
            )
            certification = (item.get("certification") or "").strip()
            if country == "us" and certification and not movie.certification:
                movie.certification = certification[:16]
                movie.save(update_fields=["certification", "updated_at"])


def _sync_streaming(movie: Movie, payload: dict) -> None:
    countries = ((payload.get("watch/providers") or {}).get("results") or {})
    for country_code, country_data in countries.items():
        country = country_code.lower()
        link = country_data.get("link") or ""
        for provider_type, availability_type in TMDB_STREAMING_TYPES.items():
            for item in country_data.get(provider_type) or []:
                name = (item.get("provider_name") or "").strip()
                if not name:
                    continue
                StreamingAvailability.objects.get_or_create(
                    movie=movie,
                    country=country,
                    provider="justwatch",
                    service_name=name,
                    availability_type=availability_type,
                    defaults={"url": link},
                )


@transaction.atomic
def ingest_tmdb_movie(payload: dict, *, run_key: str) -> Movie:
    external_ids = payload.get("external_ids") or {}
    normalized_payload = dict(payload)
    normalized_payload["imdb_id"] = payload.get("imdb_id") or external_ids.get("imdb_id")
    normalized = {
        **normalized_payload,
        **{
            key: value
            for key, value in TMDBAdapter.normalize_movie(normalized_payload).items()
            if key != "genre_data"
        },
    }
    normalized["genre_data"] = normalized_payload.get("genres") or []
    movie = _upsert_movie_fields(normalized)
    _sync_genres(movie, normalized.get("genre_data", []))
    _sync_credits(movie, payload)
    _sync_release_dates(movie, payload)
    _sync_streaming(movie, payload)

    vote_average = payload.get("vote_average")
    vote_count = payload.get("vote_count") or 0
    if vote_average and vote_count:
        append_rating_snapshot(movie, {
            "source": Rating.Source.TMDB,
            "score": Decimal(str(vote_average)) * 10,
            "raw_score": str(vote_average),
            "vote_count": vote_count,
        }, run_key=run_key)
    return movie


def sync_external_ratings(movie: Movie, *, run_key: str) -> None:
    if settings.OMDB_API_KEY and movie.imdb_id:
        try:
            with OMDbAdapter() as adapter:
                payload = adapter.lookup(imdb_id=movie.imdb_id)
                for rating in adapter.normalize_ratings(payload):
                    append_rating_snapshot(movie, rating, run_key=run_key)
        except ProviderQuotaExceeded:
            raise
        except ProviderError:
            logger.warning("OMDb ratings unavailable for movie %s", movie.pk, exc_info=True)

    if settings.KINOPOISK_API_KEY and (movie.imdb_id or movie.kinopoisk_id):
        try:
            with KinopoiskAdapter() as adapter:
                payload = adapter.lookup(imdb_id=movie.imdb_id or "", kinopoisk_id=movie.kinopoisk_id or "")
                rating = adapter.normalize_rating(payload)
                if rating:
                    append_rating_snapshot(movie, rating, run_key=run_key)
                if not movie.kinopoisk_id and payload.get("id"):
                    movie.kinopoisk_id = str(payload["id"])
                    movie.save(update_fields=["kinopoisk_id", "updated_at"])
        except ProviderQuotaExceeded:
            raise
        except ProviderError:
            logger.warning("Kinopoisk ratings unavailable for movie %s", movie.pk, exc_info=True)


def refresh_tmdb_movie(tmdb_id: int, *, run_key: str) -> Movie:
    if not settings.TMDB_API_KEY:
        raise ProviderError("TMDB API key is not configured.")
    with TMDBAdapter() as adapter:
        payload = adapter.movie_details(tmdb_id)
    movie = ingest_tmdb_movie(payload, run_key=run_key)
    sync_external_ratings(movie, run_key=run_key)
    return movie