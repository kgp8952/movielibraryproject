from django.test import TestCase

from catalog.models import Credit, Movie, Person, Rating, ReleaseDate, StreamingAvailability
from catalog.services.ingest import ingest_tmdb_movie


class TMDBIngestionTests(TestCase):
    def setUp(self):
        self.payload = {
            "id": 601,
            "title": "Localized title",
            "original_title": "Original title",
            "original_language": "ko",
            "release_date": "2023-08-12",
            "runtime": 121,
            "overview": "A stored synopsis.",
            "popularity": 24.7,
            "vote_average": 7.8,
            "vote_count": 1590,
            "poster_path": "/poster.jpg",
            "backdrop_path": "/backdrop.jpg",
            "external_ids": {"imdb_id": "tt0000601"},
            "genres": [{"id": 18, "name": "Drama"}],
            "credits": {
                "cast": [{"id": 11, "name": "Lead Actor", "character": "Detective", "profile_path": "/actor.jpg"}],
                "crew": [
                    {"id": 12, "name": "Director One", "job": "Director", "order": 0},
                    {"id": 13, "name": "Writer One", "job": "Screenplay", "order": 1},
                ],
            },
            "release_dates": {"results": [{
                "iso_3166_1": "US",
                "release_dates": [
                    {"type": 3, "release_date": "2023-09-01T00:00:00.000Z"},
                    {"type": 4, "release_date": "2023-11-03T00:00:00.000Z"},
                    {"type": 5, "release_date": "2024-01-09T00:00:00.000Z"},
                ],
            }]},
            "watch/providers": {"results": {"US": {
                "link": "https://www.justwatch.com/us/movie/sample",
                "flatrate": [{"provider_name": "Example Stream"}],
                "rent": [{"provider_name": "Example Store"}],
            }}},
        }

    def test_import_is_retry_safe_and_keeps_later_rating_history(self):
        movie = ingest_tmdb_movie(self.payload, run_key="daily:2026-11-15:tmdb:601")
        retry = ingest_tmdb_movie(self.payload, run_key="daily:2026-11-15:tmdb:601")

        self.assertEqual(movie.pk, retry.pk)
        self.assertEqual(Movie.objects.filter(tmdb_id=601).count(), 1)
        self.assertEqual(Rating.objects.filter(movie=movie, source=Rating.Source.TMDB).count(), 1)
        self.assertEqual(movie.genres.get().name, "Drama")
        self.assertEqual(Credit.objects.filter(movie=movie).count(), 3)
        self.assertEqual(Person.objects.count(), 3)
        self.assertEqual(ReleaseDate.objects.filter(movie=movie).count(), 3)
        self.assertEqual(StreamingAvailability.objects.filter(movie=movie).count(), 2)

        changed_payload = {**self.payload, "vote_average": 8.0, "vote_count": 1800}
        ingest_tmdb_movie(changed_payload, run_key="daily:2026-11-16:tmdb:601")
        self.assertEqual(Rating.objects.filter(movie=movie, source=Rating.Source.TMDB).count(), 2)
        self.assertEqual(list(movie.ratings.order_by("fetched_at").values_list("score", flat=True)), [78, 80])