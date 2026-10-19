import json
import os
import boto3
import requests
from cmc_shared import ApiError, normalize_movie_snapshot

secretsmanager = boto3.client("secretsmanager")
_cached_token = None


def get_tmdb_token():
    global _cached_token
    if _cached_token:
        return _cached_token
    secret_id = os.environ.get("TMDB_SECRET_ARN")
    if not secret_id:
        raise ApiError(500, "TMDB_SECRET_ARN is not configured.")
    secret = secretsmanager.get_secret_value(SecretId=secret_id)
    secret_string = secret.get("SecretString")
    if not secret_string:
        raise ApiError(500, "TMDB secret value is empty.")
    try:
        parsed = json.loads(secret_string)
    except json.JSONDecodeError:
        _cached_token = secret_string
        return _cached_token
    if isinstance(parsed, str):
        _cached_token = parsed
    else:
        _cached_token = parsed.get("access_token") or parsed.get("apiKey") or parsed.get("api_key") or parsed.get("token")
    if not _cached_token:
        raise ApiError(500, "TMDB secret does not contain a supported token field.")
    return _cached_token


def tmdb_get(path, params):
    base_url = os.environ.get("TMDB_BASE_URL", "https://api.themoviedb.org/3").rstrip("/")
    result = requests.get(
        f"{base_url}{path}",
        params=params,
        headers={"Authorization": f"Bearer {get_tmdb_token()}", "Accept": "application/json"},
        timeout=10,
    )
    if result.status_code == 401 or result.status_code == 403:
        raise ApiError(502, "TMDB credentials were rejected.")
    if result.status_code >= 400:
        raise ApiError(502, "TMDB movie search failed.")
    return result.json()


def normalize_movie(movie, status=None):
    release_date = movie.get("release_date") or ""
    poster_path = movie.get("poster_path") or ""
    normalized_status = status or ""
    return {
        "externalProvider": "tmdb",
        "externalMovieId": str(movie.get("id")),
        "provider": "tmdb",
        "externalId": str(movie.get("id")),
        "title": movie.get("title") or movie.get("name") or "",
        "overview": movie.get("overview") or "",
        "posterPath": poster_path,
        "posterUrl": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else "",
        "releaseDate": release_date,
        "releaseYear": release_date[:4] if release_date else "",
        "runtime": movie.get("runtime"),
        "genres": movie.get("genres") or movie.get("genre_ids") or [],
        "rating": movie.get("vote_average"),
        "popularity": movie.get("popularity"),
        "status": normalized_status,
        "metadataSnapshot": movie,
    }



def resolve_movie(provider, external_id):
    if provider != "tmdb" or not isinstance(external_id, (str, int)) or isinstance(external_id, bool) or not str(external_id).isdigit() or int(external_id) <= 0:
        raise ApiError(400, "A tmdb provider and positive externalId are required.")
    try:
        data = tmdb_get(f"/movie/{int(external_id)}", {})
    except (requests.RequestException, ValueError) as exc:
        raise ApiError(502, "Movie provider is unavailable.") from exc
    if not isinstance(data, dict) or not data.get("id") or not data.get("title"):
        raise ApiError(502, "Movie provider returned invalid movie details.")
    if str(data["id"]) != str(int(external_id)):
        raise ApiError(502, "Movie provider returned mismatched movie details.")
    return normalize_movie_snapshot({"movie": normalize_movie(data)})
