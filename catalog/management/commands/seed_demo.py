import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from catalog.models import DiscRelease, Movie, Rating
from catalog.services.ingest import append_rating_snapshot, ingest_tmdb_movie

GENRES = [
    (18, "Drama"),
    (53, "Thriller"),
    (878, "Science Fiction"),
    (35, "Comedy"),
    (80, "Crime"),
    (10749, "Romance"),
    (27, "Horror"),
    (12, "Adventure"),
    (16, "Animation"),
    (36, "History"),
]
DIRECTORS = [
    "Aki Tanaka", "Mara Voss", "Elias North", "Nadia Rahim", "Jonas Vale",
    "Iris Moreau", "Theo Park", "Leila Haddad", "Ravi Mehta", "Clara Weiss",
]
WRITERS = [
    "Mina Cho", "Owen Mercer", "Samira Bell", "Pavel Novak", "June Ortega",
    "Emil Laurent", "Hana Kim", "David Ilyin", "Rosa Silva", "Arman Sato",
]
CAST = [
    "Mina Park", "Jon Bell", "Ari Chen", "Luca Moretti", "Nora Wells",
    "Rafi Karim", "Eva Lund", "Noah Reed", "Sana Iqbal", "Leo Marin",
    "Maya Costa", "Dara Kim", "Omar Vale", "Inez Ford", "Ken Ito",
]
STREAMING_SERVICES = {
    "uz": ["Netflix", "Apple TV", "Amazon Prime Video"],
    "ru": ["Kinopoisk", "Apple TV", "Okko"],
    "us": ["Netflix", "Max", "Criterion Channel"],
}
RATING_OFFSETS = {
    Rating.Source.IMDB: 0,
    Rating.Source.RT_CRITICS: 4,
    Rating.Source.RT_AUDIENCE: 7,
    Rating.Source.METACRITIC: -3,
    Rating.Source.KINOPOISK: 2,
    Rating.Source.TMDB: 1,
}


def _mock_release_date(index: int, release_type: int, film_year: int) -> date:
    today = timezone.localdate()
    if release_type == 3 and index % 29 == 0:
        return today - timedelta(days=12)
    if release_type == 3 and index % 29 == 1:
        return today + timedelta(days=24)
    if release_type == 4 and index % 17 == 0:
        return today - timedelta(days=8)
    if release_type == 5 and index % 19 == 0:
        return today - timedelta(days=5)
    month = 1 + (index * 7 % 12)
    day = 1 + (index * 11 % 26)
    return date(film_year, month, day)


def _mock_response(index: int, title: str, year: int, language: str) -> dict:
    director_index = index % len(DIRECTORS)
    writer_index = (index * 3) % len(WRITERS)
    genre_indices = sorted({index % len(GENRES), (index * 3 + 2) % len(GENRES)})
    genres = [{"id": GENRES[genre_index][0], "name": GENRES[genre_index][1]} for genre_index in genre_indices]
    cast = [
        {
            "id": 700000 + index * 10 + cast_order,
            "name": CAST[(index + cast_order * 2) % len(CAST)],
            "character": ["Mara", "The Inspector", "Eli", "Dr. Vale"][cast_order % 4],
            "order": cast_order,
            "profile_path": None,
        }
        for cast_order in range(5)
    ]
    crew = [
        {"id": 700000 + index * 10 + 7, "name": DIRECTORS[director_index], "job": "Director", "order": 0},
        {"id": 700000 + index * 10 + 8, "name": WRITERS[writer_index], "job": "Screenplay", "order": 1},
    ]
    release_results = []
    for country in ("US", "UZ", "RU"):
        dates = []
        for release_type in (3, 4, 5):
            release_date = _mock_release_date(index, release_type, year)
            dates.append({
                "type": release_type,
                "release_date": f"{release_date.isoformat()}T00:00:00.000Z",
                "certification": "PG-13" if country == "US" and release_type == 3 else "",
            })
        release_results.append({"iso_3166_1": country, "release_dates": dates})

    watch_providers = {}
    for country, services in STREAMING_SERVICES.items():
        watch_providers[country.upper()] = {
            "link": f"https://www.justwatch.com/{country}/movie/demo-{index + 1}",
            "flatrate": [
                {"provider_name": service, "provider_id": service_index + 1}
                for service_index, service in enumerate(services[:2])
            ],
            "rent": [{"provider_name": services[-1], "provider_id": 9}],
        }

    theatrical_date = _mock_release_date(index, 3, year)
    return {
        "id": 900000 + index + 1,
        "title": title,
        "original_title": title,
        "original_language": language,
        "release_date": f"{year:04d}-{1 + index % 12:02d}-{1 + index % 27:02d}",
        "runtime": 82 + index * 7 % 88,
        "overview": f"Offline demonstration record for {title} ({year}); synopsis text is intentionally marked as fixture data.",
        "popularity": float(8 + index * 3.71 % 92),
        "vote_average": float(5.2 + index * 0.17 % 4.7),
        "vote_count": 240 + index * 137,
        "poster_path": None,
        "backdrop_path": None,
        "external_ids": {"imdb_id": f"tt{9000000 + index + 1:07d}"},
        "genres": genres,
        "credits": {"cast": cast, "crew": crew},
        "release_dates": {"results": release_results},
        "watch/providers": {"results": watch_providers},
        "demo_theatrical_date": theatrical_date,
    }


def _seed_rating_history(movie: Movie, index: int) -> None:
    base = Decimal(56 + (index * 17 % 39))
    tz = ZoneInfo("Asia/Tashkent")
    current_year = timezone.localdate().year
    for source_index, source in enumerate(Rating.Source.values):
        for snapshot_index in range(3):
            score = max(Decimal("20"), min(Decimal("99"), base + RATING_OFFSETS[source] + snapshot_index - 1))
            fetched_at = timezone.make_aware(
                datetime(current_year - 2 + snapshot_index, 2 + (index % 10), 4 + (index % 20), 6, 0),
                tz,
            )
            if source in {Rating.Source.IMDB, Rating.Source.KINOPOISK, Rating.Source.TMDB}:
                raw_score = f"{score / 10:.1f}/10"
            elif source in {Rating.Source.RT_CRITICS, Rating.Source.RT_AUDIENCE}:
                raw_score = f"{score:.0f}%"
            else:
                raw_score = f"{score:.0f}/100"
            append_rating_snapshot(movie, {
                "source": source,
                "score": score,
                "raw_score": raw_score,
                "vote_count": 350 + index * 41,
                "fetched_at": fetched_at,
            }, run_key=f"seed-demo:{movie.tmdb_id}:{source}:{snapshot_index}")


def _seed_discs(movie: Movie, index: int) -> None:
    base_date = date(movie.release_year or 2000, 3 + index % 9, 2 + index % 24)
    variants = [
        {
            "country": "us",
            "disc_format": DiscRelease.Format.BLU_RAY,
            "hdr_formats": [],
            "audio_formats": ["DTS-HD MA 5.1", "LPCM 2.0"],
            "region_code": "A",
            "edition_name": "Criterion Collection" if index % 5 == 0 else "Standard Blu-ray",
            "release_date": base_date,
        },
        {
            "country": "us",
            "disc_format": DiscRelease.Format.UHD_4K,
            "hdr_formats": ["Dolby Vision", "HDR10"] if index % 3 == 0 else ["HDR10"],
            "audio_formats": ["Dolby Atmos", "DTS-HD MA 5.1"],
            "region_code": "A / B / C",
            "edition_name": "Steelbook" if index % 4 == 0 else "4K UHD Edition",
            "release_date": base_date + timedelta(days=21),
        },
    ]
    for item in variants:
        DiscRelease.objects.update_or_create(
            movie=movie,
            country=item["country"],
            disc_format=item["disc_format"],
            edition_name=item["edition_name"],
            source="demo-fixture",
            defaults={**item, "source_url": "", "checked_at": timezone.now()},
        )


class Command(BaseCommand):
    help = "Load the bundled offline demo fixture with catalog, rating, release, disc, and streaming records."

    def handle(self, *args, **options):
        fixture_path = Path(settings.BASE_DIR) / "catalog" / "fixtures" / "demo_movies.json"
        try:
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Unable to read demo fixture: {exc}") from exc
        films = fixture.get("films", [])
        if len(films) < 150:
            raise CommandError(f"Demo fixture must contain at least 150 films; found {len(films)}.")

        created = 0
        with transaction.atomic():
            for index, row in enumerate(films):
                if not isinstance(row, list) or len(row) != 3:
                    raise CommandError(f"Invalid film row at fixture index {index}.")
                title, year, language = row
                tmdb_id = 900000 + index + 1
                existed = Movie.objects.filter(tmdb_id=tmdb_id).exists()
                payload = _mock_response(index, title, int(year), str(language))
                movie = ingest_tmdb_movie(payload, run_key=f"seed-demo:{tmdb_id}")
                movie.title_en = title if language != "ru" else ""
                movie.title_original = title
                movie.certification = "PG-13" if index % 3 else "R"
                movie.save(update_fields=["title_en", "title_original", "certification", "updated_at"])
                _seed_rating_history(movie, index)
                _seed_discs(movie, index)
                created += int(not existed)

        self.stdout.write(self.style.SUCCESS(
            f"Loaded {len(films)} offline demo films ({created} newly created). No network requests were made."
        ))