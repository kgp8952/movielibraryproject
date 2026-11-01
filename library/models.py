from django.conf import settings
from django.db import models


class LibraryEntry(models.Model):
    class Status(models.TextChoices):
        WATCHLIST = "watchlist", "Watchlist"
        WATCHED = "watched", "Watched"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    movie = models.ForeignKey("catalog.Movie", on_delete=models.CASCADE, related_name="library_entries")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.WATCHLIST)
    is_favorite = models.BooleanField(default=False)
    added_at = models.DateTimeField(auto_now_add=True)
    watched_at = models.DateField(null=True, blank=True)
    personal_rating = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-added_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "movie"], name="unique_user_library_movie"),
            models.CheckConstraint(
                condition=models.Q(personal_rating__isnull=True)
                | models.Q(personal_rating__gte=1, personal_rating__lte=10),
                name="personal_rating_1_to_10",
            ),
        ]

    def __str__(self):
        return f"{self.user}: {self.movie} ({self.status})"


class OwnedDisc(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    movie = models.ForeignKey("catalog.Movie", on_delete=models.CASCADE, related_name="owned_copies")
    release = models.ForeignKey(
        "catalog.DiscRelease", null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_copies"
    )
    edition_notes = models.CharField(max_length=255, blank=True)
    purchased_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["movie__title_original"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "movie", "release", "edition_notes"], name="unique_owned_disc_copy"
            ),
        ]

    def __str__(self):
        return f"{self.user}: {self.movie}"


class Collection(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    movies = models.ManyToManyField("catalog.Movie", through="CollectionItem", related_name="collections")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="unique_user_collection_name"),
        ]

    def __str__(self):
        return self.name


class CollectionItem(models.Model):
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    movie = models.ForeignKey("catalog.Movie", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "added_at"]
        constraints = [
            models.UniqueConstraint(fields=["collection", "movie"], name="unique_collection_movie"),
        ]