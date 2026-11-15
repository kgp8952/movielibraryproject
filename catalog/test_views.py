from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import Credit, DiscRelease, Genre, Movie, Person, Rating, ReleaseDate, StreamingAvailability
from library.models import Collection, CollectionItem, LibraryEntry, OwnedDisc, UserSettings


class CatalogPageTests(TestCase):
    def setUp(self):
        self.genre = Genre.objects.create(name="Drama", slug="drama")
        self.movie = Movie.objects.create(
            title_original="Namuna filmi",
            title_en="Sample Film",
            title_ru="Obrazets filma",
            release_year=2024,
            original_language="uz",
            overview_en="A stored overview.",
        )
        self.movie.genres.add(self.genre)
        self.user = get_user_model().objects.create_user(username="filmfan", password="long-test-password")

    def test_home_and_browse_render_from_catalog(self):
        ReleaseDate.objects.create(
            movie=self.movie,
            country="uz",
            release_type=ReleaseDate.ReleaseType.THEATRICAL,
            release_date=timezone.localdate(),
        )
        home_response = self.client.get(reverse("home"))
        browse_response = self.client.get(reverse("movie-browse"), {"q": "namuna", "genre": "drama"})

        self.assertEqual(home_response.status_code, 200)
        self.assertContains(home_response, "Sample Film")
        self.assertEqual(browse_response.status_code, 200)
        self.assertContains(browse_response, "Sample Film")
        self.assertEqual(browse_response.context["page_obj"].paginator.count, 1)

    def test_home_falls_back_from_uz_to_ru_per_shelf(self):
        ReleaseDate.objects.create(
            movie=self.movie,
            country="ru",
            release_type=ReleaseDate.ReleaseType.THEATRICAL,
            release_date=timezone.localdate(),
        )

        response = self.client.get(reverse("home"), {"country": "uz"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["shelves"][0][2], "ru")
        self.assertContains(response, "Showing RU dates")

    def test_detail_shows_available_data_and_missing_data_fallbacks(self):
        Rating.objects.create(movie=self.movie, source=Rating.Source.IMDB, score=81, raw_score="8.1/10")

        response = self.client.get(reverse("movie-detail", args=[self.movie.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A stored overview.")
        self.assertContains(response, "8.1/10")
        self.assertContains(response, "No availability recorded for UZ.")
        self.assertEqual(response.context["imdb_chart"]["scores"], [8.1])

    def test_detail_title_uses_preferred_language_then_english_fallback(self):
        UserSettings.objects.create(user=self.user, interface_language="ru")
        self.client.force_login(self.user)

        response = self.client.get(reverse("movie-detail", args=[self.movie.pk]))
        self.assertEqual(response.context["movie"].display_title, "Obrazets filma")

        self.movie.title_ru = ""
        self.movie.save(update_fields=["title_ru"])
        response = self.client.get(reverse("movie-detail", args=[self.movie.pk]))
        self.assertEqual(response.context["movie"].display_title, "Sample Film")

    def test_authenticated_user_can_update_watchlist_and_collection(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("library-entry-update", args=[self.movie.pk]), {"action": "watchlist"}
        )
        entry = LibraryEntry.objects.get(user=self.user, movie=self.movie)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(entry.status, LibraryEntry.Status.WATCHLIST)

        response = self.client.post(reverse("collection-create"), {"name": "Rewatch"})
        collection = Collection.objects.get(user=self.user, name="Rewatch")
        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            reverse("collection-toggle-movie", args=[collection.pk, self.movie.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CollectionItem.objects.filter(collection=collection, movie=self.movie).exists())

    def test_private_library_redirects_to_login(self):
        response = self.client.get(reverse("library"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_registration_and_logout(self):
        response = self.client.post(reverse("register"), {
            "username": "newfan",
            "password1": "A-long-enough-test-password-42!",
            "password2": "A-long-enough-test-password-42!",
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(username="newfan").exists())
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("library")).status_code, 302)

    def test_browse_filters_stored_ratings_discs_and_streaming(self):
        Rating.objects.create(movie=self.movie, source=Rating.Source.IMDB, score=82)
        DiscRelease.objects.create(movie=self.movie, disc_format=DiscRelease.Format.UHD_4K)
        StreamingAvailability.objects.create(
            movie=self.movie,
            country="uz",
            service_name="Local service",
            availability_type=StreamingAvailability.Type.SUBSCRIPTION,
        )

        response = self.client.get(reverse("movie-browse"), {
            "min_imdb": "80",
            "has_4k": "1",
            "streaming_country": "uz",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_person_compare_sync_settings_and_library_pages_render(self):
        person = Person.objects.create(name="A Film-maker", biography="A local biography.")
        Credit.objects.create(movie=self.movie, person=person, role=Credit.Role.CAST, character_name="Self")
        self.client.force_login(self.user)

        self.assertContains(self.client.get(reverse("person-detail", args=[person.pk])), "A local biography.")
        self.assertEqual(
            self.client.get(reverse("compare"), {"movie": [self.movie.pk]}).status_code,
            200,
        )
        self.assertEqual(self.client.get(reverse("sync-status")).status_code, 200)
        self.assertEqual(self.client.get(reverse("settings")).status_code, 200)
        self.assertEqual(self.client.get(reverse("collections")).status_code, 200)
        self.assertEqual(self.client.get(reverse("library")).status_code, 200)

    def test_settings_owned_discs_and_csv_are_saved_or_exported(self):
        self.client.force_login(self.user)
        settings_response = self.client.post(reverse("settings"), {
            "preferred_country": "ru",
            "interface_language": "ru",
            "enabled_providers": ["tmdb", "kinopoisk"],
        })
        preferences = UserSettings.objects.get(user=self.user)
        self.assertEqual(settings_response.status_code, 302)
        self.assertEqual(preferences.preferred_country, "ru")
        self.assertEqual(preferences.enabled_providers, {
            "tmdb": True,
            "omdb": False,
            "kinopoisk": True,
            "disc": False,
        })

        disc = DiscRelease.objects.create(
            movie=self.movie,
            disc_format=DiscRelease.Format.UHD_4K,
            hdr_formats=["Dolby Vision"],
        )
        self.client.post(reverse("owned-disc-toggle", args=[self.movie.pk]), {"release_id": disc.pk})
        self.assertTrue(OwnedDisc.objects.filter(user=self.user, movie=self.movie, release=disc).exists())
        self.assertEqual(self.client.get(reverse("library-export")).status_code, 200)
        self.assertIn("text/csv", self.client.get(reverse("library-export")).headers["Content-Type"])
        LibraryEntry.objects.create(user=self.user, movie=self.movie, is_favorite=True)
        favorites_csv = self.client.get(reverse("library-export"), {"status": "favorites"})
        self.assertIn("Sample Film", favorites_csv.content.decode("utf-8-sig"))

    @patch("catalog.views.TMDBAdapter")
    def test_global_archive_search_renders_remote_matches(self, adapter_class):
        self.client.force_login(self.user)
        adapter = adapter_class.return_value.__enter__.return_value
        adapter.search_movies.return_value = {"results": [{
            "id": 9901,
            "title": "Unreleased Archive Film",
            "original_title": "Archive Film",
            "release_date": "1940-01-01",
            "poster_path": "/archive.jpg",
        }]}
        adapter_class.image_url.return_value = "https://image.example/archive.jpg"
        with self.settings(TMDB_API_KEY="tmdb-test"):
            response = self.client.get(reverse("movie-browse"), {"q": "archive", "source": "all"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unreleased Archive Film")
        self.assertContains(response, "/movie/import/")
        adapter.search_movies.assert_called_once_with("archive", page=1)

    def test_import_refresh_person_and_manual_sync_actions_enqueue_jobs(self):
        self.client.force_login(self.user)
        movie = Movie.objects.create(title_original="Queue Film", tmdb_id=9902)
        person = Person.objects.create(name="Queue Director", tmdb_id=9912)
        with self.settings(TMDB_API_KEY="tmdb-test"):
            with patch("catalog.views.enqueue_job") as enqueue:
                import_response = self.client.post(reverse("movie-import"), {"tmdb_id": 9903})
                refresh_response = self.client.post(reverse("movie-refresh", args=[movie.pk]))
                person_response = self.client.post(reverse("person-import", args=[person.pk]))
        self.assertEqual(import_response.status_code, 302)
        self.assertEqual(refresh_response.status_code, 302)
        self.assertEqual(person_response.status_code, 302)
        self.assertEqual(enqueue.call_count, 3)
        self.assertEqual(enqueue.call_args_list[0].args[0], "import_tmdb_movie")
        self.assertEqual(enqueue.call_args_list[1].args[0], "enrich_movie")
        self.assertEqual(enqueue.call_args_list[2].args[0], "import_person_filmography")

        with self.settings(TMDB_API_KEY="tmdb-test"):
            with patch("sync.views.enqueue_job") as enqueue_sync:
                response = self.client.post(reverse("sync-run-now"), {"kind": "popular"})
        self.assertEqual(response.status_code, 302)
        enqueue_sync.assert_called_once()
        self.assertEqual(enqueue_sync.call_args.args[0], "popular")