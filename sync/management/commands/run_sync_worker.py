import time

from django.core.management.base import BaseCommand
from django.db.utils import OperationalError
from django.utils import timezone

from sync.models import SyncJob


class Command(BaseCommand):
    help = "Poll for due sync jobs; provider handlers are added in the sync implementation step."

    def add_arguments(self, parser):
        parser.add_argument("--poll-seconds", type=float, default=5.0)
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        poll_seconds = max(0.25, options["poll_seconds"])
        self.stdout.write(self.style.SUCCESS("Kino sync worker started."))
        while True:
            try:
                due_count = SyncJob.objects.filter(
                    status=SyncJob.Status.QUEUED,
                    available_at__lte=timezone.now(),
                ).count()
                if due_count:
                    self.stdout.write(f"{due_count} due job(s) await registered handlers.")
            except OperationalError:
                self.stdout.write("Waiting for the shared SQLite database to be initialized.")
            if options["once"]:
                break
            try:
                time.sleep(poll_seconds)
            except KeyboardInterrupt:
                self.stdout.write("Stopping Kino sync worker.")
                break