from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class Genre(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Movie(models.Model):
    tmdb_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    imdb_id = models.CharField(max_length=16, null=True, blank=True, unique=True)
    kinopoisk_id = models.CharField(max_length=32, null=True, blank=True, unique=True)
    title_en = models.CharField(max_length=255, blank=True)
    title_ru = models.CharField(max_length=255, blank=True)
    title_uz = models.CharField(max_length=255, blank=True)
    title_original = models.CharField(max_length=255)
    original_language = models.CharField(max_length=12, blank=True)
    release_year = models.PositiveSmallIntegerField(null=True, blank=True)
    runtime_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    overview_en = models.TextField(blank=True)
    overview_ru = models.TextField(blank=True)
    overview_uz = models.TextField(blank=True)
    poster_path = models.URLField(max_length=500, blank=True)
    genres = models.ManyToManyField(Genre, related_name="movies", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title_original", "release_year"]
        indexes = [
            models.Index(fields=["release_year"]),
            models.Index(fields=["original_language"]),
            models.Index(fields=["title_en"]),
            models.Index(fields=["title_ru"]),
            models.Index(fields=["title_uz"]),
        ]

    def __str__(self):
        return self.title_original


class Person(models.Model):
    tmdb_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    name = models.CharField(max_length=255)
    profile_path = models.URLField(max_length=500, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Credit(models.Model):
    class Role(models.TextChoices):
        DIRECTOR = "director", "Director"
        WRITER = "writer", "Writer"
        CAST = "cast", "Cast"

    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="credits")
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="credits")
    role = models.CharField(max_length=16, choices=Role.choices)
    character_name = models.CharField(max_length=255, blank=True)
    credit_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["credit_order", "person__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["movie", "person", "role"], name="unique_movie_person_role"
            ),
        ]

    def __str__(self):
        return f"{self.person} ({self.role})"


class Rating(models.Model):
    class Source(models.TextChoices):
        IMDB = "imdb", "IMDb"
        RT_CRITICS = "rotten_tomatoes_critics", "Rotten Tomatoes Critics"
        RT_AUDIENCE = "rotten_tomatoes_audience", "Rotten Tomatoes Audience"
        METACRITIC = "metacritic", "Metacritic"
        KINOPOISK = "kinopoisk", "Kinopoisk"
        TMDB = "tmdb", "TMDB"

    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="ratings")
    source = models.CharField(max_length=32, choices=Source.choices)
    score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    raw_score = models.CharField(max_length=32, blank=True)
    vote_count = models.PositiveIntegerField(null=True, blank=True)
    snapshot_key = models.CharField(max_length=160, unique=True, null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-fetched_at"]
        indexes = [models.Index(fields=["movie", "source", "-fetched_at"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(score__gte=0, score__lte=100), name="rating_score_0_to_100"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Rating snapshots are append-only and cannot be updated.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.movie}: {self.get_source_display()} {self.score}"


class ReleaseDate(models.Model):
    class ReleaseType(models.TextChoices):
        THEATRICAL = "theatrical", "Theatrical"
        DIGITAL = "digital", "Digital"
        PHYSICAL = "physical", "Physical"

    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="release_dates")
    country = models.CharField(max_length=2, db_index=True)
    release_type = models.CharField(max_length=16, choices=ReleaseType.choices)
    release_date = models.DateField()
    source = models.CharField(max_length=48, blank=True)

    class Meta:
        ordering = ["release_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["movie", "country", "release_type", "release_date"],
                name="unique_movie_release_date",
            ),
        ]

    def __str__(self):
        return f"{self.movie}: {self.country} {self.release_type} {self.release_date}"


class DiscRelease(models.Model):
    class Format(models.TextChoices):
        BLU_RAY = "blu_ray", "Blu-ray"
        UHD_4K = "uhd_4k", "4K UHD"

    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="disc_releases")
    country = models.CharField(max_length=2, blank=True)
    disc_format = models.CharField(max_length=16, choices=Format.choices)
    hdr_formats = models.JSONField(default=list, blank=True)
    audio_formats = models.JSONField(default=list, blank=True)
    region_code = models.CharField(max_length=32, blank=True)
    edition_name = models.CharField(max_length=255, blank=True)
    release_date = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=48, blank=True)
    source_url = models.URLField(max_length=500, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-release_date", "edition_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["movie", "country", "disc_format", "edition_name", "source"],
                name="unique_disc_release_source",
            ),
        ]

    def __str__(self):
        return f"{self.movie}: {self.get_disc_format_display()} {self.edition_name}".strip()


class StreamingAvailability(models.Model):
    class Type(models.TextChoices):
        SUBSCRIPTION = "subscription", "Subscription"
        FREE = "free", "Free"
        ADS = "ads", "With ads"
        RENT = "rent", "Rent"
        BUY = "buy", "Buy"

    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="streaming_options")
    country = models.CharField(max_length=2, db_index=True)
    provider = models.CharField(max_length=48, default="justwatch")
    service_name = models.CharField(max_length=100)
    availability_type = models.CharField(max_length=16, choices=Type.choices)
    url = models.URLField(max_length=500, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["service_name", "availability_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["movie", "country", "provider", "service_name", "availability_type"],
                name="unique_streaming_option",
            ),
        ]

    def __str__(self):
        return f"{self.service_name} ({self.country})"