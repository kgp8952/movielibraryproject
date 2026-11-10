from datetime import timedelta

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

    def test_detail_shows_available_data_and_missing_data_fallbacks(self):
        Rating.objects.create(movie=self.movie, source=Rating.Source.IMDB, score=81, raw_score="8.1/10")

        response = self.client.get(reverse("movie-detail", args=[self.movie.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A stored overview.")
        self.assertContains(response, "8.1/10")
        self.assertContains(response, "No availability recorded for UZ.")
        self.assertEqual(response.context["imdb_chart"]["scores"], [8.1])

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
        })
        preferences = UserSettings.objects.get(user=self.user)
        self.assertEqual(settings_response.status_code, 302)
        self.assertEqual(preferences.preferred_country, "ru")

        disc = DiscRelease.objects.create(
            movie=self.movie,
            disc_format=DiscRelease.Format.UHD_4K,
            hdr_formats=["Dolby Vision"],
        )
        self.client.post(reverse("owned-disc-toggle", args=[self.movie.pk]), {"release_id": disc.pk})
        self.assertTrue(OwnedDisc.objects.filter(user=self.user, movie=self.movie, release=disc).exists())
        self.assertEqual(self.client.get(reverse("library-export")).status_code, 200)
        self.assertIn("text/csv", self.client.get(reverse("library-export")).headers["Content-Type"])