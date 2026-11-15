from typing import Any

from django.conf import settings

from catalog.models import Rating
from catalog.providers.base import ProviderAdapter, ProviderUnavailable


class KinopoiskAdapter(ProviderAdapter):
    base_url = "https://api.kinopoisk.dev/v1.4/"

    def __init__(self, *, api_key: str | None = None, **kwargs):
        super().__init__(api_key=api_key if api_key is not None else settings.KINOPOISK_API_KEY, **kwargs)

    @property
    def provider_name(self) -> str:
        return "kinopoisk"

    def lookup(self, *, imdb_id: str = "", kinopoisk_id: str = "", title: str = "") -> dict[str, Any]:
        if not self.api_key:
            raise ProviderUnavailable("Kinopoisk API key is not configured.")
        headers = {"X-API-KEY": self.api_key}
        if kinopoisk_id:
            payload = self.request_json("GET", f"movie/{kinopoisk_id}", headers=headers)
        elif imdb_id:
            payload = self.request_json("GET", "movie", params={"externalId.imdb": imdb_id}, headers=headers)
            if isinstance(payload, dict) and "docs" in payload:
                docs = payload.get("docs") or []
                payload = docs[0] if docs else {}
        elif title:
            payload = self.request_json("GET", "movie/search", params={"query": title}, headers=headers)
            if isinstance(payload, dict):
                docs = payload.get("docs") or []
                payload = docs[0] if docs else {}
        else:
            raise ValueError("An IMDb ID, Kinopoisk ID, or title is required.")
        if not isinstance(payload, dict) or not payload:
            raise ProviderUnavailable("Kinopoisk returned no matching movie.")
        return payload

    def normalize_movie(self, payload: dict[str, Any]) -> dict[str, Any]:
        poster = payload.get("poster") or {}
        external = payload.get("externalId") or {}
        title = payload.get("name") or payload.get("alternativeName") or ""
        return {
            "kinopoisk_id": str(payload.get("id") or ""),
            "imdb_id": external.get("imdb") or "",
            "title_original": title,
            "title_ru": payload.get("name") or "",
            "release_year": payload.get("year"),
            "runtime_minutes": payload.get("movieLength"),
            "overview_ru": payload.get("description") or "",
            "poster_path": poster.get("url") or "",
        }

    def normalize_rating(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        rating = payload.get("rating") or {}
        score = rating.get("kp")
        if score is None:
            return None
        return {
            "source": Rating.Source.KINOPOISK,
            "score": self.normalize_score(score),
            "raw_score": str(score),
            "vote_count": rating.get("kpVoteCount"),
        }

    @staticmethod
    def normalize_score(score: Any):
        from decimal import Decimal

        return (Decimal(str(score)) * 10).quantize(Decimal("0.01"))