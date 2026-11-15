from typing import Any

from django.conf import settings

from catalog.providers.base import ProviderAdapter


class TMDBAdapter(ProviderAdapter):
    base_url = "https://api.themoviedb.org/3/"

    def __init__(self, *, api_key: str | None = None, **kwargs):
        super().__init__(api_key=api_key if api_key is not None else settings.TMDB_API_KEY, **kwargs)

    @property
    def provider_name(self) -> str:
        return "tmdb"

    def request_json(self, method: str, path: str, *, params=None, json=None, headers=None):
        params = dict(params or {})
        params.setdefault("api_key", self.api_key)
        return super().request_json(method, path, params=params, json=json, headers=headers)

    @staticmethod
    def normalize_movie(payload: dict[str, Any]) -> dict[str, Any]:
        release_date = payload.get("release_date") or ""
        return {
            "tmdb_id": payload.get("id"),
            "imdb_id": payload.get("imdb_id"),
            "title_original": payload.get("original_title") or payload.get("title") or "",
            "title_en": payload.get("title") or "",
            "original_language": payload.get("original_language") or "",
            "release_year": int(release_date[:4]) if len(release_date) >= 4 and release_date[:4].isdigit() else None,
            "runtime_minutes": payload.get("runtime"),
            "overview_en": payload.get("overview") or "",
            "popularity": payload.get("popularity") or 0,
            "poster_path": TMDBAdapter.image_url(payload.get("poster_path")),
            "backdrop_path": TMDBAdapter.image_url(payload.get("backdrop_path")),
            "genre_data": payload.get("genres") or [],
        }

    @staticmethod
    def image_url(path: str | None, size: str = "w500") -> str:
        return f"https://image.tmdb.org/t/p/{size}{path}" if path else ""

    def search_movies(self, query: str, *, page: int = 1, language: str = "en-US") -> dict[str, Any]:
        return self.request_json("GET", "search/movie", params={"query": query, "page": page, "language": language})

    def movie_list(self, list_name: str, *, country: str = "uz", page: int = 1, language: str = "en-US") -> dict[str, Any]:
        if list_name not in {"now_playing", "upcoming", "popular"}:
            raise ValueError(f"Unsupported TMDB movie list: {list_name}")
        return self.request_json(
            "GET",
            f"movie/{list_name}",
            params={"region": country.upper(), "page": page, "language": language},
        )

    def movie_details(self, tmdb_id: int, *, language: str = "en-US") -> dict[str, Any]:
        return self.request_json(
            "GET",
            f"movie/{tmdb_id}",
            params={
                "language": language,
                "append_to_response": "credits,external_ids,release_dates,watch/providers",
            },
        )

    def person_details(self, tmdb_id: int, *, language: str = "en-US") -> dict[str, Any]:
        return self.request_json("GET", f"person/{tmdb_id}", params={"language": language})

    def person_movie_credits(self, tmdb_id: int, *, language: str = "en-US") -> dict[str, Any]:
        return self.request_json("GET", f"person/{tmdb_id}/movie_credits", params={"language": language})