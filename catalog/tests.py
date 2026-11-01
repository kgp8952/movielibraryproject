from decimal import Decimal

import httpx
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from catalog.models import Movie, Rating
from catalog.providers.base import ProviderAdapter, ProviderUnavailable
from sync.models import ProviderCall


class RatingHistoryTests(TestCase):
    def setUp(self):
        self.movie = Movie.objects.create(title_original="Sample film")

    def test_rating_rows_are_append_only(self):
        rating = Rating.objects.create(
            movie=self.movie,
            source=Rating.Source.IMDB,
            score=Decimal("82.50"),
        )
        rating.score = Decimal("90.00")
        with self.assertRaises(ValidationError):
            rating.save()

    def test_snapshot_key_prevents_retry_duplicates(self):
        Rating.objects.create(
            movie=self.movie,
            source=Rating.Source.IMDB,
            score=Decimal("82.50"),
            snapshot_key="imdb:tt123:2026-10-20T06:00:00Z",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Rating.objects.create(
                movie=self.movie,
                source=Rating.Source.IMDB,
                score=Decimal("82.50"),
                snapshot_key="imdb:tt123:2026-10-20T06:00:00Z",
            )


class SampleAdapter(ProviderAdapter):
    base_url = "https://provider.example/api"

    @property
    def provider_name(self):
        return "sample"

    def normalize_movie(self, payload):
        return payload


class OmdbSampleAdapter(SampleAdapter):
    @property
    def provider_name(self):
        return "omdb"


class ProviderAdapterTests(TestCase):
    def test_valid_json_is_returned_and_call_is_logged(self):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"id": 7},
            )
        )
        with httpx.Client(transport=transport) as client:
            adapter = SampleAdapter(client=client)
            self.assertEqual(adapter.request_json("GET", "/movie/7"), {"id": 7})

        call = ProviderCall.objects.get(provider="sample")
        self.assertTrue(call.succeeded)
        self.assertEqual(call.status_code, 200)

    def test_non_json_response_becomes_provider_unavailable(self):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text="bad")
        )
        with httpx.Client(transport=transport) as client:
            adapter = SampleAdapter(client=client)
            with self.assertRaises(ProviderUnavailable):
                adapter.request_json("GET", "/movie/7")

    def test_quota_gate_rejects_exhausted_provider(self):
        from catalog.providers.base import ProviderQuotaExceeded

        ProviderCall.objects.create(
            provider="sample",
            endpoint="/movie/7",
            succeeded=True,
        )
        adapter = SampleAdapter()
        with self.assertRaises(ProviderQuotaExceeded):
            adapter.assert_daily_quota(1)
        adapter.close()

    def test_omdb_quota_blocks_request_before_transport(self):
        from catalog.providers.base import ProviderQuotaExceeded

        ProviderCall.objects.create(provider="omdb", endpoint="/", succeeded=True)
        transport = httpx.MockTransport(
            lambda request: self.fail("quota-exhausted request reached the transport")
        )
        with httpx.Client(transport=transport) as client:
            adapter = OmdbSampleAdapter(client=client)
            with self.settings(OMDB_DAILY_LIMIT=1):
                with self.assertRaises(ProviderQuotaExceeded):
                    adapter.request_json("GET", "/movie/7")