import logging
import requests

from .config import Config

log = logging.getLogger(__name__)


class SonarrClient:
    def __init__(self):
        self.url = Config.SONARR_URL.rstrip("/")
        self.api_key = Config.SONARR_API_KEY
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

    def find_series_by_tvdb(self, tvdb_id):
        series = self._get("/series", params={"tvdbId": tvdb_id})
        return series[0] if series else None

    def get_series(self, series_id):
        return self._get(f"/series/{series_id}")

    def get_episodes(self, series_id, season_number=None):
        params = {"seriesId": series_id}
        if season_number is not None:
            params["seasonNumber"] = season_number
        return self._get("/episode", params=params)

    def get_episode_file(self, episode_file_id):
        return self._get(f"/episodefile/{episode_file_id}")

    def delete_episode_file(self, file_id):
        self._delete(f"/episodefile/{file_id}")
        log.info("Deleted episode file %d", file_id)

    def get_history(self, episode_id, event_type="grabbed"):
        records = self._get("/history",
                            params={"episodeId": episode_id,
                                    "eventType": event_type})
        if isinstance(records, dict):
            records = records.get("records", [])
        return records

    def blacklist_by_history(self, history_id):
        self._post(f"/history/failed/{history_id}")
        log.info("Blacklisted via history record %d", history_id)

    def add_to_blocklist(self, episode_id):
        history = self.get_history(episode_id, "grabbed")
        if history:
            most_recent = sorted(history, key=lambda h: h.get("date", ""),
                                 reverse=True)[0]
            self.blacklist_by_history(most_recent["id"])
            return True
        log.warning("No grab history for episode %d — cannot blacklist",
                    episode_id)
        return False

    def search_episode(self, episode_ids):
        if isinstance(episode_ids, int):
            episode_ids = [episode_ids]
        result = self._post("/command",
                            json={"name": "EpisodeSearch",
                                  "episodeIds": episode_ids})
        log.info("Triggered search for episodes %s: command %s",
                 episode_ids, result.get("id"))
        return result

    def search_season(self, series_id, season_number):
        result = self._post("/command",
                            json={"name": "SeasonSearch",
                                  "seriesId": series_id,
                                  "seasonNumber": season_number})
        log.info("Triggered season search: series %d season %d",
                 series_id, season_number)
        return result
