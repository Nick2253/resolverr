import logging
import requests

from .config import Config

log = logging.getLogger(__name__)


class SeerrClient:
    def __init__(self):
        self.url = Config.SEERR_URL.rstrip("/")
        self.api_key = Config.SEERR_API_KEY
        self.session = requests.Session()
        self.session.headers["X-Api-Key"] = self.api_key

    def _get(self, path, **kwargs):
        resp = self.session.get(f"{self.url}/api/v1{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path, json=None, **kwargs):
        resp = self.session.post(f"{self.url}/api/v1{path}", json=json,
                                 **kwargs)
        resp.raise_for_status()
        return resp.json()

    def get_issue(self, issue_id):
        return self._get(f"/issue/{issue_id}")

    def comment_on_issue(self, issue_id, message):
        self._post(f"/issue/{issue_id}/comment",
                   json={"message": message})
        log.info("Commented on issue %s", issue_id)

    def resolve_issue(self, issue_id):
        self._post(f"/issue/{issue_id}/resolved")
        log.info("Resolved issue %s", issue_id)

    def get_media(self, media_id):
        return self._get(f"/media/{media_id}")

    def get_movie(self, media_id):
        media = self.get_media(media_id)
        tmdb_id = media.get("tmdbId")
        if tmdb_id:
            return self._get(f"/movie/{tmdb_id}")
        return None

    def get_tv(self, media_id):
        media = self.get_media(media_id)
        tmdb_id = media.get("tmdbId")
        if tmdb_id:
            return self._get(f"/tv/{tmdb_id}")
        return None
