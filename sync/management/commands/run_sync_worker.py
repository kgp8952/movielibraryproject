import time

from django.core.management.base import BaseCommand
from django.db.utils import OperationalError

from sync.services import enqueue_scheduled_jobs, process_next_job


class Command(BaseCommand):
    help = "Schedule and run Kino provider sync jobs."

    def add_arguments(self, parser):
        parser.add_argument("--poll-seconds", type=float, default=5.0)
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        poll_seconds = max(0.25, options["poll_seconds"])
        self.stdout.write(self.style.SUCCESS("Kino sync worker started."))
        while True:
            job = None
            try:
                scheduled = enqueue_scheduled_jobs()
                job = process_next_job()
                if scheduled:
                    self.stdout.write(f"Scheduled {scheduled} sync job(s).")
                if job:
                    self.stdout.write(f"{job.kind}: {job.status} (attempt {job.attempts}).")
            except OperationalError:
                self.stdout.write("Waiting for the shared SQLite database to be initialized.")
            if options["once"]:
                break
            if not job:
                try:
                    time.sleep(poll_seconds)
                except KeyboardInterrupt:
                    self.stdout.write("Stopping Kino sync worker.")
                    break