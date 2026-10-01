import os


class Config:
    RADARR_URL = os.environ.get("RADARR_URL", "http://radarr:7878")
    RADARR_API_KEY = os.environ.get("RADARR_API_KEY", "")
    SONARR_URL = os.environ.get("SONARR_URL", "http://sonarr:8989")
    SONARR_API_KEY = os.environ.get("SONARR_API_KEY", "")
    SEERR_URL = os.environ.get("SEERR_URL", "http://seerr:5055")
    SEERR_API_KEY = os.environ.get("SEERR_API_KEY", "")
    WEBHOOK_SECRET = os.environ.get("RESOLVERR_WEBHOOK_SECRET", "")
    DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
    DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/resolverr.db")
    AUTO_APPROVE = os.environ.get("AUTO_APPROVE", "false").lower() == "true"
    BASE_URL = os.environ.get("BASE_URL", "http://resolverr:8787")
