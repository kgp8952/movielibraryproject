from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import httpx
from django.test import TestCase

from catalog.models import Rating
from catalog.providers import DiscReleaseAdapter, KinopoiskAdapter, OMDbAdapter, TMDBAdapter
from catalog.providers.base import ProviderQuotaExceeded, ProviderUnavailable
from sync.models import ProviderCall


class ProviderAdapterTests(TestCase):
    def test_tmdb_search_adds_key_and_normalizes_movie(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"results": [{"id": 42, "title": "Localized", "original_title": "Original", "release_date": "2022-05-06", "vote_average": 7.3}]},
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            adapter = TMDBAdapter(api_key="tmdb-test", client=client)
            response = adapter.search_movies("Original", language="ru-RU")

        request = requests[0]
        query = parse_qs(urlparse(str(request.url)).query)
        self.assertEqual(query["api_key"], ["tmdb-test"])
        self.assertEqual(query["language"], ["ru-RU"])
        self.assertEqual(response["results"][0]["id"], 42)
        normalized = TMDBAdapter(api_key="test").normalize_movie({
            "id": 42,
            "title": "Localized",
            "original_title": "Original",
            "release_date": "2022-05-06",
            "vote_average": 7.3,
            "poster_path": "/poster.jpg",
        })
        self.assertEqual(normalized["release_year"], 2022)
        self.assertEqual(normalized["poster_path"], "https://image.tmdb.org/t/p/w500/poster.jpg")

    def test_omdb_normalizes_ratings_and_votes(self):
        adapter = OMDbAdapter(api_key="omdb-test")
        ratings = adapter.normalize_ratings({
            "imdbVotes": "123,456",
            "Ratings": [
                {"Source": "Internet Movie Database", "Value": "8.4/10"},
                {"Source": "Rotten Tomatoes", "Value": "91%"},
                {"Source": "Metacritic", "Value": "77/100"},
            ],
            "AudienceScore": "88%",
        })
        by_source = {item["source"]: item for item in ratings}
        self.assertEqual(by_source[Rating.Source.IMDB]["score"], Decimal("84.00"))
        self.assertEqual(by_source[Rating.Source.IMDB]["vote_count"], 123456)
        self.assertEqual(by_source[Rating.Source.RT_CRITICS]["score"], Decimal("91.00"))
        self.assertEqual(by_source[Rating.Source.RT_AUDIENCE]["score"], Decimal("88.00"))
        self.assertEqual(by_source[Rating.Source.METACRITIC]["score"], Decimal("77.00"))

    def test_omdb_quota_is_checked_before_network_request(self):
        ProviderCall.objects.create(provider="omdb", endpoint="?i=tt1")
        transport = httpx.MockTransport(lambda request: self.fail("quota must block transport"))
        with httpx.Client(transport=transport) as client:
            adapter = OMDbAdapter(api_key="omdb-test", client=client)
            with self.settings(OMDB_DAILY_LIMIT=1):
                with self.assertRaises(ProviderQuotaExceeded):
                    adapter.lookup(imdb_id="tt123")

    def test_kinopoisk_uses_key_header_and_normalizes_rating(self):
        def respond(request):
            self.assertEqual(request.headers["X-API-KEY"], "kp-test")
            return httpx.Response(200, headers={"content-type": "application/json"}, json={
                "id": 12,
                "name": "Название",
                "year": 2020,
                "rating": {"kp": 8.1, "kpVoteCount": 44},
            })

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            adapter = KinopoiskAdapter(api_key="kp-test", client=client)
            payload = adapter.lookup(kinopoisk_id="12")
            rating = adapter.normalize_rating(payload)

        self.assertEqual(adapter.normalize_movie(payload)["kinopoisk_id"], "12")
        self.assertEqual(rating["score"], Decimal("81.00"))
        self.assertEqual(rating["vote_count"], 44)

    def test_disc_provider_contract_validates_release_list(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"releases": [{"format": "uhd_4k", "hdr": ["Dolby Vision"]}]},
        ))
        with httpx.Client(transport=transport) as client:
            adapter = DiscReleaseAdapter(base_url="https://disc.example/api", client=client)
            releases = adapter.search_releases(imdb_id="tt123")

        self.assertEqual(releases[0]["format"], "uhd_4k")

    def test_omdb_application_error_is_graceful(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"Response": "False", "Error": "Movie not found!"},
        ))
        with httpx.Client(transport=transport) as client:
            adapter = OMDbAdapter(api_key="omdb-test", client=client)
            with self.assertRaises(ProviderUnavailable):
                adapter.lookup(imdb_id="tt-missing")