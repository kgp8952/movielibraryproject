from django.db import models


class SyncJob(models.Model):
    class Kind(models.TextChoices):
        NOW_PLAYING = "now_playing", "Now playing"
        UPCOMING = "upcoming", "Upcoming"
        POPULAR = "popular", "Popular"
        ENRICH_MOVIE = "enrich_movie", "Enrich movie"
        REFRESH_RATINGS = "refresh_ratings", "Refresh ratings"
        REFRESH_DISCS = "refresh_discs", "Refresh discs"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        DEFERRED = "deferred", "Deferred"

    kind = models.CharField(max_length=24, choices=Kind.choices, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True)
    idempotency_key = models.CharField(max_length=160, unique=True, null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    available_at = models.DateTimeField(db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["available_at", "created_at"]
        indexes = [models.Index(fields=["status", "available_at"])]

    def __str__(self):
        return f"{self.kind} ({self.status})"


class ProviderCall(models.Model):
    provider = models.CharField(max_length=48, db_index=True)
    endpoint = models.CharField(max_length=255)
    duration_ms = models.PositiveIntegerField(default=0)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    succeeded = models.BooleanField(default=False)
    error_type = models.CharField(max_length=80, blank=True)
    called_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-called_at"]
        indexes = [models.Index(fields=["provider", "called_at"])]

    def __str__(self):
        return f"{self.provider} {self.endpoint} ({self.status_code or 'no response'})"