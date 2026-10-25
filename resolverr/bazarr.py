import logging
import requests

from .config import Config

log = logging.getLogger(__name__)


class BazarrError(Exception):
    pass


class BazarrClient:
    """Same approach as Talkarr: a bad subtitle Bazarr downloaded goes through
    Bazarr's blacklist (it deletes the file, records provider + subs_id as bad,
    and searches again). Deleting the file alone lets Bazarr fetch the same
    top-scoring subtitle straight back.

    IDs are passed as {"radarrid": n} or {"seriesid": n, "episodeid": n}.
    """

    def __init__(self):
        self.url = Config.BAZARR_URL.rstrip("/")
        self.api_key = Config.BAZARR_API_KEY
        self.session = requests.Session()
        self.session.headers["X-API-KEY"] = self.api_key

    def _request(self, method, path, **kwargs):
        try:
            resp = self.session.request(method, f"{self.url}/api{path}",
                                        timeout=30, **kwargs)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise BazarrError(f"Bazarr {method} {path}: {e}") from e
        return resp.json() if resp.content else None

    @staticmethod
    def _data(payload):
        return payload.get("data", []) if isinstance(payload, dict) else \
            (payload or [])

    @staticmethod
    def _kind(ids):
        return "movies" if "radarrid" in ids else "episodes"

    def get_movie(self, radarr_id):
        data = self._data(self._request("GET", "/movies",
                                        params={"radarrid[]": radarr_id}))
        return data[0] if data else None

    def get_series_episodes(self, sonarr_series_id):
        return self._data(self._request(
            "GET", "/episodes", params={"seriesid[]": sonarr_series_id}))

    def find_download(self, ids, subtitles_path):
        """Bazarr's latest download record for this subtitle file, or None
        (e.g. it was added by hand or Bazarr never downloaded it)."""
        if "radarrid" in ids:
            params = {"radarrid": ids["radarrid"], "length": -1}
        else:
            params = {"episodeid": ids["episodeid"], "length": -1}
        rows = self._data(self._request("GET", f"/{self._kind(ids)}/history",
                                        params=params))
        # Bazarr returns history newest first
        for row in rows:
            if row.get("subtitles_path") != subtitles_path:
                continue
            if not (row.get("provider") and row.get("subs_id")) or \
                    row.get("blacklisted"):
                continue
            language = row.get("language") or {}
            code2 = language.get("code2") if isinstance(language, dict) \
                else str(language)
            return {"provider": row["provider"],
                    "subs_id": str(row["subs_id"]),
                    "language": code2 or "en",
                    "subtitles_path": subtitles_path}
        return None

    def blacklist(self, ids, download):
        """Blacklist a downloaded subtitle; Bazarr deletes it and searches
        again for that item."""
        self._request("POST", f"/{self._kind(ids)}/blacklist",
                      data={**ids, **download})
        log.info("Blacklisted in Bazarr: %s %s %s", download["provider"],
                 download["subs_id"], download["subtitles_path"])

    def delete_subtitle(self, ids, language, forced, hi, path):
        self._request("DELETE", f"/{self._kind(ids)}/subtitles",
                      params={**ids, "language": language,
                              "forced": forced, "hi": hi, "path": path})
        log.info("Deleted subtitle: %s", path)

    def search_missing(self, ids):
        """Search for every missing subtitle on the movie or whole series."""
        if "radarrid" in ids:
            self._request("PATCH", "/movies",
                          params={"radarrid": ids["radarrid"],
                                  "action": "search-missing"})
        else:
            self._request("PATCH", "/series",
                          params={"seriesid": ids["seriesid"],
                                  "action": "search-missing"})
        log.info("Triggered missing-subtitle search: %s", ids)
