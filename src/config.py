import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _clean_env(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if val is None:
        return default
    return val.strip().strip('"').strip("'")


@dataclass
class Settings:
    discord_bot_token: str
    timezone_offset_hours: int = 8
    rpg_db_path: str = "data/rpg.db"
    rpg_backup_channel_id: str = ""
    rpg_backup_interval_minutes: int = 15

    @classmethod
    def from_env(cls) -> "Settings":
        tz_raw = _clean_env("TIMEZONE_OFFSET_HOURS", "8")
        try:
            tz_offset = int(tz_raw)
        except ValueError:
            tz_offset = 8

        backup_int_raw = _clean_env("RPG_BACKUP_INTERVAL_MINUTES", "15")
        try:
            backup_interval = max(1, int(backup_int_raw))
        except ValueError:
            backup_interval = 15

        return cls(
            discord_bot_token=_clean_env("DISCORD_BOT_TOKEN"),
            timezone_offset_hours=tz_offset,
            rpg_db_path=_clean_env("RPG_DB_PATH", "data/rpg.db") or "data/rpg.db",
            rpg_backup_channel_id=_clean_env("RPG_BACKUP_CHANNEL_ID"),
            rpg_backup_interval_minutes=backup_interval,
        )
