import re
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings

from catalog.models import Rating
from catalog.providers.base import ProviderAdapter, ProviderUnavailable


class OMDbAdapter(ProviderAdapter):
    base_url = "https://www.omdbapi.com/"

    def __init__(self, *, api_key: str | None = None, **kwargs):
        super().__init__(api_key=api_key if api_key is not None else settings.OMDB_API_KEY, **kwargs)

    @property
    def provider_name(self) -> str:
        return "omdb"

    def lookup(self, *, imdb_id: str = "", title: str = "", year: int | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderUnavailable("OMDb API key is not configured.")
        params: dict[str, Any] = {"apikey": self.api_key, "r": "json"}
        if imdb_id:
            params["i"] = imdb_id
        elif title:
            params["t"] = title
            if year:
                params["y"] = year
        else:
            raise ValueError("An IMDb ID or title is required for OMDb lookup.")
        payload = self.request_json("GET", "", params=params)
        if not isinstance(payload, dict) or payload.get("Response") == "False":
            reason = payload.get("Error", "invalid response") if isinstance(payload, dict) else "invalid response"
            raise ProviderUnavailable(f"OMDb lookup failed: {reason}")
        return payload

    def normalize_movie(self, payload: dict[str, Any]) -> dict[str, Any]:
        year_value = payload.get("Year") or ""
        year_match = re.search(r"\d{4}", year_value)
        runtime_match = re.search(r"\d+", payload.get("Runtime") or "")
        imdb_value = payload.get("imdbRating")
        try:
            popularity = Decimal(imdb_value) * 10 if imdb_value and imdb_value != "N/A" else Decimal("0")
        except InvalidOperation:
            popularity = Decimal("0")
        return {
            "imdb_id": payload.get("imdbID") or "",
            "title_original": payload.get("Title") or "",
            "title_en": payload.get("Title") or "",
            "release_year": int(year_match.group()) if year_match else None,
            "runtime_minutes": int(runtime_match.group()) if runtime_match else None,
            "overview_en": payload.get("Plot") if payload.get("Plot") != "N/A" else "",
            "poster_path": payload.get("Poster") if payload.get("Poster") != "N/A" else "",
            "original_language": payload.get("Language") or "",
            "popularity": popularity,
        }

    def normalize_ratings(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        normalized = []
        source_map = {
            "internet movie database": Rating.Source.IMDB,
            "imdb": Rating.Source.IMDB,
            "rotten tomatoes": Rating.Source.RT_CRITICS,
            "metacritic": Rating.Source.METACRITIC,
        }
        for item in payload.get("Ratings", []):
            source = source_map.get((item.get("Source") or "").strip().lower())
            if source:
                value = item.get("Value")
                parsed = self._normalize_score(value)
                if parsed is not None:
                    normalized.append({"source": source, "score": parsed, "raw_score": value or ""})

        for field, source in (("AudienceScore", Rating.Source.RT_AUDIENCE), ("tomatoAudience", Rating.Source.RT_AUDIENCE)):
            value = payload.get(field)
            parsed = self._normalize_score(value)
            if parsed is not None:
                normalized.append({"source": source, "score": parsed, "raw_score": str(value)})
                break

        vote_text = payload.get("imdbVotes") or ""
        digits = re.sub(r"\D", "", vote_text)
        for rating in normalized:
            if rating["source"] == Rating.Source.IMDB:
                rating["vote_count"] = int(digits) if digits else None
        return normalized

    @staticmethod
    def _normalize_score(raw_value: Any) -> Decimal | None:
        if raw_value is None:
            return None
        value = str(raw_value).strip()
        if not value or value.upper() == "N/A":
            return None
        try:
            if "/" in value:
                numerator, denominator = value.split("/", 1)
                score = Decimal(numerator.strip()) / Decimal(denominator.strip()) * 100
            elif value.endswith("%"):
                score = Decimal(value[:-1].strip())
            else:
                score = Decimal(value)
                if score <= 10:
                    score *= 10
            return max(Decimal("0"), min(Decimal("100"), score)).quantize(Decimal("0.01"))
        except (InvalidOperation, ZeroDivisionError):
            return None