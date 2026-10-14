import logging
import requests

from .config import Config

log = logging.getLogger(__name__)


class BazarrClient:
    def __init__(self):
        self.url = Config.BAZARR_URL.rstrip("/")
        self.api_key = Config.BAZARR_API_KEY
        self.session = requests.Session()
        self.session.headers["X-API-KEY"] = self.api_key

    def _get(self, path, **kwargs):
        resp = self.session.get(f"{self.url}/api{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path, **kwargs):
        resp = self.session.delete(f"{self.url}/api{path}", **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def _patch(self, path, json=None, **kwargs):
        resp = self.session.patch(f"{self.url}/api{path}", json=json,
                                  **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def _post(self, path, json=None, **kwargs):
        resp = self.session.post(f"{self.url}/api{path}", json=json,
                                 **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def get_episode_subtitles(self, sonarr_episode_id):
        data = self._get("/episodes",
                         params={"episodeid[]": sonarr_episode_id})
        return data.get("data", [])

    def get_movie_subtitles(self, radarr_id):
        data = self._get("/movies", params={"radarrid[]": radarr_id})
        return data.get("data", [])

    def delete_episode_subtitle(self, sonarr_series_id, sonarr_episode_id,
                                language, forced, hi, path):
        self._delete("/episodes/subtitles",
                     params={
                         "seriesid": sonarr_series_id,
                         "episodeid": sonarr_episode_id,
                         "language": language,
                         "forced": forced,
                         "hi": hi,
                         "path": path,
                     })
        log.info("Deleted episode subtitle: %s", path)

    def delete_movie_subtitle(self, radarr_id, language, forced, hi, path):
        self._delete("/movies/subtitles",
                     params={
                         "radarrid": radarr_id,
                         "language": language,
                         "forced": forced,
                         "hi": hi,
                         "path": path,
                     })
        log.info("Deleted movie subtitle: %s", path)

    def search_episode_subtitles(self, sonarr_episode_id):
        self._post("/episodes/subtitles",
                   json={"episodeid": sonarr_episode_id})
        log.info("Triggered subtitle search for episode %s",
                 sonarr_episode_id)

    def search_movie_subtitles(self, radarr_id):
        self._post("/movies/subtitles", json={"radarrid": radarr_id})
        log.info("Triggered subtitle search for movie %s", radarr_id)

    def blacklist_episode_subtitle(self, provider, subs_id,
                                   language, forced):
        self._post("/episodes/subtitles/blacklist",
                   json={
                       "provider": provider,
                       "subs_id": subs_id,
                       "language": language,
                       "forced": forced,
                   })
        log.info("Blacklisted subtitle: %s/%s", provider, subs_id)

    def blacklist_movie_subtitle(self, provider, subs_id,
                                 language, forced):
        self._post("/movies/subtitles/blacklist",
                   json={
                       "provider": provider,
                       "subs_id": subs_id,
                       "language": language,
                       "forced": forced,
                   })
        log.info("Blacklisted movie subtitle: %s/%s", provider, subs_id)
