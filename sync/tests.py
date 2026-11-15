from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings
from django.utils import timezone

from catalog.providers.base import ProviderQuotaExceeded, ProviderUnavailable
from sync.models import SyncJob
from sync.services import claim_next_job, dispatch_job, enqueue_job, enqueue_scheduled_jobs, process_next_job


class SyncSchedulingTests(TestCase):
    @override_settings(TMDB_API_KEY="tmdb-test")
    def test_daily_and_weekly_schedules_are_local_and_idempotent(self):
        sunday_morning = datetime(2026, 11, 15, 7, 5, tzinfo=ZoneInfo("Asia/Tashkent"))

        created = enqueue_scheduled_jobs(sunday_morning)
        repeated = enqueue_scheduled_jobs(sunday_morning)

        self.assertEqual(created, 5)
        self.assertEqual(repeated, 0)
        self.assertEqual(SyncJob.objects.count(), 5)
        self.assertEqual(
            SyncJob.objects.filter(kind__in=[SyncJob.Kind.NOW_PLAYING, SyncJob.Kind.UPCOMING, SyncJob.Kind.POPULAR]).count(),
            3,
        )

    @override_settings(TMDB_API_KEY="")
    def test_scheduler_does_not_queue_provider_jobs_without_tmdb_key(self):
        self.assertEqual(enqueue_scheduled_jobs(timezone.now()), 0)
        self.assertFalse(SyncJob.objects.exists())


class SyncExecutionTests(TestCase):
    def create_job(self, kind=SyncJob.Kind.NOW_PLAYING, key="test:job", payload=None):
        return SyncJob.objects.create(
            kind=kind,
            idempotency_key=key,
            payload=payload or {"country": "uz", "page": 1},
            available_at=timezone.now(),
        )

    @patch("sync.services.TMDBAdapter")
    def test_movie_list_dispatch_queues_unique_enrichment_jobs(self, adapter_class):
        adapter = adapter_class.return_value.__enter__.return_value
        adapter.movie_list.return_value = {"results": [{"id": 71}, {"id": 72}, {"title": "No ID"}]}
        job = self.create_job()

        count = dispatch_job(job)

        self.assertEqual(count, 3)
        queued = SyncJob.objects.filter(kind=SyncJob.Kind.ENRICH_MOVIE)
        self.assertEqual(queued.count(), 2)
        self.assertEqual(set(queued.values_list("payload__tmdb_id", flat=True)), {71, 72})
        dispatch_job(job)
        self.assertEqual(queued.count(), 2)

    @patch("sync.services.dispatch_job", return_value=3)
    def test_claimed_job_is_completed_and_attempt_counted(self, dispatch):
        job = self.create_job()

        processed = process_next_job()

        job.refresh_from_db()
        self.assertEqual(processed.pk, job.pk)
        self.assertEqual(job.status, SyncJob.Status.SUCCEEDED)
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.payload["result_count"], 3)
        dispatch.assert_called_once()

    @patch("sync.services.dispatch_job", side_effect=ProviderQuotaExceeded("limit reached"))
    def test_omdb_quota_defers_job_until_next_tashkent_day(self, dispatch):
        self.create_job(kind=SyncJob.Kind.ENRICH_MOVIE)

        job = process_next_job()

        job.refresh_from_db()
        self.assertEqual(job.status, SyncJob.Status.DEFERRED)
        self.assertEqual(timezone.localtime(job.available_at).hour, 0)
        self.assertIn("quota", job.last_error.lower())
        dispatch.assert_called_once()

    @patch("sync.services.dispatch_job", side_effect=ProviderUnavailable("temporary outage"))
    def test_provider_failure_retries_with_backoff(self, dispatch):
        job = self.create_job()

        processed = process_next_job()

        processed.refresh_from_db()
        self.assertEqual(processed.status, SyncJob.Status.QUEUED)
        self.assertEqual(processed.attempts, 1)
        self.assertIn("temporary outage", processed.last_error)
        self.assertGreater(processed.available_at, timezone.now())
        dispatch.assert_called_once()

    def test_worker_reclaims_stale_running_job_after_restart(self):
        job = self.create_job()
        job.status = SyncJob.Status.RUNNING
        job.started_at = timezone.now() - timedelta(minutes=45)
        job.save(update_fields=["status", "started_at"])

        claimed = claim_next_job()

        job.refresh_from_db()
        self.assertEqual(claimed.pk, job.pk)
        self.assertEqual(job.status, SyncJob.Status.RUNNING)
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.idempotency_key, "test:job")
        self.assertIn("Recovered", job.last_error)