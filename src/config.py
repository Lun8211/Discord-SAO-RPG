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
    discord_channel_id: str
    discord_webhook_url: str
    riot_ssid: str
    riot_cookies: str
    riot_region: str
    valorant_lang: str
    daily_post_time: str
    timezone_offset_hours: int

    @classmethod
    def from_env(cls) -> "Settings":
        tz_raw = _clean_env("TIMEZONE_OFFSET_HOURS", "8")
        try:
            tz_offset = int(tz_raw)
        except ValueError:
            tz_offset = 8

        return cls(
            discord_bot_token=_clean_env("DISCORD_BOT_TOKEN"),
            discord_channel_id=_clean_env("DISCORD_CHANNEL_ID"),
            discord_webhook_url=_clean_env("DISCORD_WEBHOOK_URL"),
            riot_ssid=_clean_env("RIOT_SSID"),
            riot_cookies=_clean_env("RIOT_COOKIES"),
            riot_region=_clean_env("RIOT_REGION", "ap").lower() or "ap",
            valorant_lang=_clean_env("VALORANT_LANG", "zh-TW") or "zh-TW",
            daily_post_time=_clean_env("DAILY_POST_TIME", "08:05") or "08:05",
            timezone_offset_hours=tz_offset,
        )

    def validate_discord(self) -> None:
        has_bot = bool(self.discord_bot_token and self.discord_channel_id)
        has_webhook = bool(self.discord_webhook_url)
        if not has_bot and not has_webhook:
            raise ValueError(
                "缺少 Discord 設定：請在環境變數或 GitHub Secrets 中設定 "
                "`DISCORD_BOT_TOKEN` 與 `DISCORD_CHANNEL_ID`（或 `DISCORD_WEBHOOK_URL`）。"
            )

    def validate_riot(self) -> None:
        if not self.riot_ssid and not self.riot_cookies:
            raise ValueError(
                "缺少 Riot 驗證資訊：請在環境變數或 GitHub Secrets 中設定 "
                "`RIOT_SSID`（或 `RIOT_COOKIES`）。"
            )
