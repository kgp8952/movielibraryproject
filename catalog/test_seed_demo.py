from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from catalog.models import Credit, DiscRelease, Movie, Rating, ReleaseDate, StreamingAvailability


class SeedDemoTests(TestCase):
    def test_seed_demo_is_offline_complete_and_idempotent(self):
        output = StringIO()
        with patch("httpx.Client.request", side_effect=AssertionError("seed_demo must not use the network")):
            call_command("seed_demo", stdout=output)

        movie_count = Movie.objects.filter(tmdb_id__gte=900001, tmdb_id__lte=900183).count()
        self.assertEqual(movie_count, 183)
        self.assertGreaterEqual(Credit.objects.count(), movie_count * 6)
        self.assertGreaterEqual(Rating.objects.count(), movie_count * 18)
        self.assertGreaterEqual(ReleaseDate.objects.count(), movie_count * 9)
        self.assertGreaterEqual(DiscRelease.objects.count(), movie_count * 2)
        self.assertGreaterEqual(StreamingAvailability.objects.count(), movie_count * 6)
        self.assertIn("No network requests were made", output.getvalue())

        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(Movie.objects.filter(tmdb_id__gte=900001, tmdb_id__lte=900183).count(), 183)
        self.assertEqual(Rating.objects.filter(movie__tmdb_id__gte=900001, movie__tmdb_id__lte=900183).count(), movie_count * 19)