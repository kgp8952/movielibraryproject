from typing import Any

from django.conf import settings

from catalog.providers.base import ProviderAdapter, ProviderUnavailable


class DiscReleaseAdapter(ProviderAdapter):
    """Adapter contract for a configured disc catalog that returns normalized JSON releases."""

    def __init__(self, *, base_url: str | None = None, api_key: str | None = None, **kwargs):
        self.base_url = (base_url or settings.DISC_API_BASE_URL).rstrip("/")
        super().__init__(api_key=api_key if api_key is not None else settings.DISC_API_KEY, **kwargs)

    @property
    def provider_name(self) -> str:
        return "disc"

    def search_releases(self, *, imdb_id: str = "", tmdb_id: int | None = None, title: str = "") -> list[dict[str, Any]]:
        if not self.base_url:
            raise ProviderUnavailable("No disc catalog endpoint is configured.")
        if not any((imdb_id, tmdb_id, title)):
            raise ValueError("A movie identifier or title is required.")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
        params = {key: value for key, value in {"imdb_id": imdb_id, "tmdb_id": tmdb_id, "title": title}.items() if value}
        payload = self.request_json("GET", "releases", params=params, headers=headers)
        releases = payload.get("releases", []) if isinstance(payload, dict) else payload
        if not isinstance(releases, list) or not all(isinstance(item, dict) for item in releases):
            raise ProviderUnavailable("Disc catalog returned an invalid release list.")
        return releases

    def normalize_movie(self, payload: dict[str, Any]) -> dict[str, Any]:
        return payload