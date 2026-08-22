"""
Asynchronous TMDB (The Movie Database) API Client.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

TMDB_API_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"


@dataclass
class TMDBMediaResult:
    id: int
    title: str
    original_title: str
    year: Optional[int]
    media_type: str  # "movie" or "tv"
    overview: str
    poster_url: Optional[str] = None
    vote_average: float = 0.0

    @property
    def display_name(self) -> str:
        if self.year:
            return f"{self.title} ({self.year})"
        return self.title


@dataclass
class TMDBEpisodeInfo:
    episode_number: int
    name: str
    overview: str
    air_date: Optional[str] = None


class TMDBClient:
    """TMDB v3 API Client using HTTPX."""

    def __init__(
        self,
        api_key: str,
        default_language: str = "zh-CN",
        include_adult: bool = False,
        base_url: str = TMDB_API_BASE_URL,
    ):
        self.api_key = api_key.strip()
        self.default_language = default_language
        self.include_adult = include_adult
        self.base_url = base_url

    def _get_auth_params_and_headers(self) -> tuple[Dict[str, str], Dict[str, str]]:
        params: Dict[str, str] = {}
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "tg-baidu/0.1.0",
        }
        # If API key is long (v4 Read Access Token JWT), send Bearer header
        if len(self.api_key) > 50:
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            params["api_key"] = self.api_key
        return params, headers

    async def _request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("TMDB API key is not configured.")

        auth_params, headers = self._get_auth_params_and_headers()
        req_params = {**auth_params}
        if params:
            req_params.update(params)

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=req_params, headers=headers)
            if resp.status_code != 200:
                logger.error(
                    "TMDB API request failed (%s): %s", resp.status_code, resp.text
                )
                resp.raise_for_status()
            return resp.json()

    async def search_movie(
        self,
        query: str,
        year: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[TMDBMediaResult]:
        """Search for movies matching query."""
        params: Dict[str, Any] = {
            "query": query,
            "language": language or self.default_language,
            "include_adult": self.include_adult,
        }
        if year:
            params["year"] = year

        data = await self._request("search/movie", params)
        results = []
        for item in data.get("results", []):
            release_date = item.get("release_date") or ""
            item_year = int(release_date.split("-")[0]) if release_date else None
            poster_path = item.get("poster_path")
            poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else None

            results.append(
                TMDBMediaResult(
                    id=item["id"],
                    title=item.get("title") or item.get("original_title") or "",
                    original_title=item.get("original_title") or "",
                    year=item_year,
                    media_type="movie",
                    overview=item.get("overview") or "",
                    poster_url=poster_url,
                    vote_average=item.get("vote_average", 0.0),
                )
            )
        return results

    async def search_tv(
        self,
        query: str,
        year: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[TMDBMediaResult]:
        """Search for TV shows matching query."""
        params: Dict[str, Any] = {
            "query": query,
            "language": language or self.default_language,
            "include_adult": self.include_adult,
        }
        if year:
            params["first_air_date_year"] = year

        data = await self._request("search/tv", params)
        results = []
        for item in data.get("results", []):
            air_date = item.get("first_air_date") or ""
            item_year = int(air_date.split("-")[0]) if air_date else None
            poster_path = item.get("poster_path")
            poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else None

            results.append(
                TMDBMediaResult(
                    id=item["id"],
                    title=item.get("name") or item.get("original_name") or "",
                    original_title=item.get("original_name") or "",
                    year=item_year,
                    media_type="tv",
                    overview=item.get("overview") or "",
                    poster_url=poster_url,
                    vote_average=item.get("vote_average", 0.0),
                )
            )
        return results

    async def search_multi(
        self,
        query: str,
        media_type: str = "auto",  # "auto", "movie", "tv"
        year: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[TMDBMediaResult]:
        """Search TMDB for movies, TV shows, or auto."""
        if media_type == "movie":
            return await self.search_movie(query, year=year, language=language)
        if media_type == "tv":
            return await self.search_tv(query, year=year, language=language)

        # Auto: search both and combine
        movies = await self.search_movie(query, year=year, language=language)
        tv_shows = await self.search_tv(query, year=year, language=language)
        combined = movies + tv_shows
        # Sort by popularity / vote count / exact year match
        combined.sort(
            key=lambda x: (
                1 if (year and x.year == year) else 0,
                x.vote_average,
            ),
            reverse=True,
        )
        return combined

    async def get_movie_details(
        self, movie_id: int, language: Optional[str] = None
    ) -> TMDBMediaResult:
        """Fetch movie details by ID."""
        data = await self._request(
            f"movie/{movie_id}",
            {"language": language or self.default_language},
        )
        release_date = data.get("release_date") or ""
        year = int(release_date.split("-")[0]) if release_date else None
        poster_path = data.get("poster_path")
        poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else None

        return TMDBMediaResult(
            id=data["id"],
            title=data.get("title") or data.get("original_title") or "",
            original_title=data.get("original_title") or "",
            year=year,
            media_type="movie",
            overview=data.get("overview") or "",
            poster_url=poster_url,
            vote_average=data.get("vote_average", 0.0),
        )

    async def get_tv_details(
        self, tv_id: int, language: Optional[str] = None
    ) -> TMDBMediaResult:
        """Fetch TV show details by ID."""
        data = await self._request(
            f"tv/{tv_id}",
            {"language": language or self.default_language},
        )
        air_date = data.get("first_air_date") or ""
        year = int(air_date.split("-")[0]) if air_date else None
        poster_path = data.get("poster_path")
        poster_url = f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else None

        return TMDBMediaResult(
            id=data["id"],
            title=data.get("name") or data.get("original_name") or "",
            original_title=data.get("original_name") or "",
            year=year,
            media_type="tv",
            overview=data.get("overview") or "",
            poster_url=poster_url,
            vote_average=data.get("vote_average", 0.0),
        )

    async def get_season_episodes(
        self,
        tv_id: int,
        season_number: int,
        language: Optional[str] = None,
    ) -> Dict[int, TMDBEpisodeInfo]:
        """Fetch list of episode names in a season."""
        try:
            data = await self._request(
                f"tv/{tv_id}/season/{season_number}",
                {"language": language or self.default_language},
            )
            episodes: Dict[int, TMDBEpisodeInfo] = {}
            for ep in data.get("episodes", []):
                ep_num = ep.get("episode_number", 0)
                episodes[ep_num] = TMDBEpisodeInfo(
                    episode_number=ep_num,
                    name=ep.get("name") or f"Episode {ep_num}",
                    overview=ep.get("overview") or "",
                    air_date=ep.get("air_date"),
                )
            return episodes
        except Exception as e:
            logger.warning("Failed to fetch season episodes for TV ID %s Season %s: %s", tv_id, season_number, e)
            return {}
