import logging
from abc import ABC, abstractmethod
from time import monotonic
from typing import Any
from urllib.parse import urljoin

import httpx
from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Base class for provider failures safe for callers to handle."""


class ProviderUnavailable(ProviderError):
    """The provider timed out, returned an error, or sent invalid data."""


class ProviderQuotaExceeded(ProviderError):
    """A provider's configured daily request budget has been reached."""


class ProviderAdapter(ABC):
    """Shared HTTP, validation, and call-metrics contract for data providers."""

    base_url: str
    timeout_seconds: float | None = None

    def __init__(self, *, api_key: str = "", client: httpx.Client | None = None):
        self.api_key = api_key
        self._owns_client = client is None
        self.client = client or httpx.Client()

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable provider identifier used in call logs and settings."""

    @abstractmethod
    def normalize_movie(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Map a provider response to the catalog's normalized movie fields."""

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        if self.provider_name == "omdb":
            self.assert_daily_quota(settings.OMDB_DAILY_LIMIT)
        url = urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))
        timeout = self.timeout_seconds or settings.PROVIDER_TIMEOUT_SECONDS
        started = monotonic()
        response = None
        error_type = ""
        try:
            response = self.client.request(
                method,
                url,
                params=params,
                json=json,
                timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "json" not in content_type:
                raise ProviderUnavailable("Provider response was not JSON.")
            payload = response.json()
            if not isinstance(payload, (dict, list)):
                raise ProviderUnavailable("Provider returned an unsupported JSON value.")
            return payload
        except (httpx.HTTPError, ValueError, ProviderUnavailable) as exc:
            error_type = type(exc).__name__
            raise ProviderUnavailable(f"{self.provider_name} request failed: {exc}") from exc
        finally:
            self._record_call(
                endpoint=path,
                duration_ms=max(0, round((monotonic() - started) * 1000)),
                status_code=response.status_code if response is not None else None,
                succeeded=response is not None and response.is_success and not error_type,
                error_type=error_type,
            )

    def assert_daily_quota(self, daily_limit: int) -> None:
        """Raise before a request when this provider has exhausted today's budget."""
        from sync.models import ProviderCall

        calls_today = ProviderCall.objects.filter(
            provider=self.provider_name,
            called_at__date=timezone.localdate(),
        ).count()
        if calls_today >= daily_limit:
            raise ProviderQuotaExceeded(
                f"{self.provider_name} daily request limit ({daily_limit}) reached."
            )

    def _record_call(
        self,
        *,
        endpoint: str,
        duration_ms: int,
        status_code: int | None,
        succeeded: bool,
        error_type: str,
    ) -> None:
        try:
            from sync.models import ProviderCall

            ProviderCall.objects.create(
                provider=self.provider_name,
                endpoint=endpoint[:255],
                duration_ms=duration_ms,
                status_code=status_code,
                succeeded=succeeded,
                error_type=error_type[:80],
            )
        except DatabaseError:
            logger.exception("Unable to record provider call for %s", self.provider_name)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()