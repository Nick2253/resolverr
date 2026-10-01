import logging
import requests

from .config import Config

log = logging.getLogger(__name__)


class RadarrClient:
    def __init__(self):
        self.url = Config.RADARR_URL.rstrip("/")
        self.api_key = Config.RADARR_API_KEY
        self.session = requests.Session()
        self.session.headers["X-Api-Key"] = self.api_key

    def _get(self, path, **kwargs):
        resp = self.session.get(f"{self.url}/api/v3{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path, json=None, **kwargs):
        resp = self.session.post(f"{self.url}/api/v3{path}", json=json,
                                 **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path, **kwargs):
        resp = self.session.delete(f"{self.url}/api/v3{path}", **kwargs)
        resp.raise_for_status()

    def find_movie_by_tmdb(self, tmdb_id):
        movies = self._get("/movie", params={"tmdbId": tmdb_id})
        return movies[0] if movies else None

    def get_movie(self, movie_id):
        return self._get(f"/movie/{movie_id}")

    def get_movie_file(self, movie_id):
        files = self._get("/moviefile", params={"movieId": movie_id})
        return files[0] if files else None

    def delete_movie_file(self, file_id):
        self._delete(f"/moviefile/{file_id}")
        log.info("Deleted movie file %d", file_id)

    def get_history(self, movie_id, event_type="grabbed"):
        records = self._get("/history/movie",
                            params={"movieId": movie_id,
                                    "eventType": event_type})
        return records

    def blacklist_by_history(self, history_id):
        self._post(f"/history/failed/{history_id}")
        log.info("Blacklisted via history record %d", history_id)

    def add_to_blocklist(self, movie_id, file_path):
        history = self.get_history(movie_id, "grabbed")
        if history:
            most_recent = sorted(history, key=lambda h: h.get("date", ""),
                                 reverse=True)[0]
            self.blacklist_by_history(most_recent["id"])
            return True
        log.warning("No grab history for movie %d — cannot blacklist",
                    movie_id)
        return False

    def search_movie(self, movie_id):
        result = self._post("/command",
                            json={"name": "MoviesSearch",
                                  "movieIds": [movie_id]})
        log.info("Triggered search for movie %d: command %s",
                 movie_id, result.get("id"))
        return result
