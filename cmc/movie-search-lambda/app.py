import json
import os
from datetime import datetime, timezone

import boto3
import requests

from cmc_shared import ApiError, claims, handle, query_param, response


from cmc_movies import get_tmdb_token, tmdb_get, normalize_movie

def is_now_playing_request(event):
    path = event.get("path") or event.get("resourcePath") or ""
    return path.rstrip("/").endswith("/movies/now-playing")


def is_discovery_request(event):
    path = event.get("path") or event.get("resourcePath") or ""
    return path.rstrip("/").endswith("/movies/discover")


def discover_movies(mode, page):
    if mode == "now-playing":
        return tmdb_get("/movie/now_playing", {"page": page, "region": "US"})
    data = tmdb_get("/movie/upcoming", {"page": page, "region": "US"})
    today = datetime.now(timezone.utc).date().isoformat()
    # The regional theatrical feed is useful for relevance, but TMDB can keep
    # stale records in it. Enforce the user-facing promise locally.
    data["results"] = [
        movie for movie in data.get("results", [])
        if str(movie.get("release_date") or "") >= today
    ]
    return data


@handle
def handler(event, context):
    claims(event)
    page = query_param(event, "page", "1")
    if is_now_playing_request(event):
        mode = query_param(event, "mode", "now-playing")
        if mode not in {"now-playing", "coming-soon"}:
            raise ApiError(400, "mode must be now-playing or coming-soon.")
        status = "now_playing" if mode == "now-playing" else "coming_soon"
        data = discover_movies(mode, page)
        return response(200, {"results": [normalize_movie(movie, status) for movie in data.get("results", [])]})

    if is_discovery_request(event):
        mode = query_param(event, "mode", "now-playing")
        if mode not in {"now-playing", "coming-soon"}:
            raise ApiError(400, "mode must be now-playing or coming-soon.")
        status = "now_playing" if mode == "now-playing" else "coming_soon"
        data = discover_movies(mode, page)
        return response(200, {"results": [normalize_movie(movie, status) for movie in data.get("results", [])]})

    query = query_param(event, "query") or query_param(event, "q")
    if not query or len(query.strip()) < 2:
        raise ApiError(400, "query must be at least 2 characters.")
    data = tmdb_get("/search/movie", {"query": query.strip(), "page": page, "include_adult": "false"})
    return response(200, {"results": [normalize_movie(movie) for movie in data.get("results", [])]})
