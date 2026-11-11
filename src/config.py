import json
import os
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()


def _clean_env(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    if val is None:
        return default
    return val.strip().strip('"').strip("'")


@dataclass
class AccountConfig:
    """Configuration for a single Riot / VALORANT account."""

    index: int
    label: str = ""
    riot_ssid: str = ""
    riot_cookies: str = ""
    riot_region: str = "ap"
    discord_user_id: str = ""
    discord_channel_id: str = ""

    @property
    def display_label(self) -> str:
        return self.label or f"帳號 #{self.index}"


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
    accounts: List[AccountConfig] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "Settings":
        tz_raw = _clean_env("TIMEZONE_OFFSET_HOURS", "8")
        try:
            tz_offset = int(tz_raw)
        except ValueError:
            tz_offset = 8

        default_region = _clean_env("RIOT_REGION", "ap").lower() or "ap"
        default_channel_id = _clean_env("DISCORD_CHANNEL_ID")
        riot_ssid = _clean_env("RIOT_SSID")
        riot_cookies = _clean_env("RIOT_COOKIES")
        riot_accounts_raw = (
            os.getenv("RIOT_ACCOUNTS") or os.getenv("RIOT_ACCOUNTS_JSON") or ""
        ).strip()

        accounts = cls._parse_accounts(
            riot_ssid=riot_ssid,
            riot_cookies=riot_cookies,
            riot_accounts_raw=riot_accounts_raw,
            default_region=default_region,
            default_channel_id=default_channel_id,
        )

        return cls(
            discord_bot_token=_clean_env("DISCORD_BOT_TOKEN"),
            discord_channel_id=default_channel_id,
            discord_webhook_url=_clean_env("DISCORD_WEBHOOK_URL"),
            riot_ssid=riot_ssid,
            riot_cookies=riot_cookies,
            riot_region=default_region,
            valorant_lang=_clean_env("VALORANT_LANG", "zh-TW") or "zh-TW",
            daily_post_time=_clean_env("DAILY_POST_TIME", "08:05") or "08:05",
            timezone_offset_hours=tz_offset,
            accounts=accounts,
        )

    @classmethod
    def _parse_accounts(
        cls,
        riot_ssid: str,
        riot_cookies: str,
        riot_accounts_raw: str,
        default_region: str,
        default_channel_id: str,
    ) -> List[AccountConfig]:
        accounts: List[AccountConfig] = []
        seen_keys = set()

        def _add_account(
            label: str = "",
            ssid: str = "",
            cookies: str = "",
            region: str = "",
            discord_user_id: str = "",
            channel_id: str = "",
        ) -> None:
            ssid = ssid.strip().strip('"').strip("'")
            cookies = cookies.strip().strip('"').strip("'")
            if not ssid and not cookies:
                return
            dedup_key = (ssid or cookies, channel_id or default_channel_id)
            if dedup_key in seen_keys:
                return
            seen_keys.add(dedup_key)
            accounts.append(
                AccountConfig(
                    index=len(accounts) + 1,
                    label=label.strip(),
                    riot_ssid=ssid,
                    riot_cookies=cookies,
                    riot_region=(region.strip().lower() or default_region),
                    discord_user_id=discord_user_id.strip(),
                    discord_channel_id=channel_id.strip() or default_channel_id,
                )
            )

        # 1. Check RIOT_ACCOUNTS / RIOT_ACCOUNTS_JSON (supports JSON array or multi-line text)
        if riot_accounts_raw:
            cls._parse_accounts_blob(
                riot_accounts_raw, default_region, default_channel_id, _add_account
            )

        # 2. Check RIOT_SSID / RIOT_COOKIES (also supports multi-line or JSON if user put multiple in RIOT_SSID)
        if riot_ssid or riot_cookies:
            if (
                "\n" in riot_ssid
                or "|" in riot_ssid
                or riot_ssid.startswith("[")
            ):
                cls._parse_accounts_blob(
                    riot_ssid, default_region, default_channel_id, _add_account
                )
            else:
                _add_account(
                    label=_clean_env("ACCOUNT_NAME") or _clean_env("ACCOUNT_NAME_1"),
                    ssid=riot_ssid,
                    cookies=riot_cookies,
                    region=default_region,
                    discord_user_id=_clean_env("DISCORD_USER_ID")
                    or _clean_env("DISCORD_USER_ID_1"),
                    channel_id=_clean_env("DISCORD_CHANNEL_ID_1") or default_channel_id,
                )

        # 3. Check numbered environment variables: RIOT_SSID_1..20 or RIOT_COOKIES_1..20
        for i in range(1, 21):
            ssid_i = _clean_env(f"RIOT_SSID_{i}")
            cookies_i = _clean_env(f"RIOT_COOKIES_{i}")
            if ssid_i or cookies_i:
                _add_account(
                    label=_clean_env(f"ACCOUNT_NAME_{i}"),
                    ssid=ssid_i,
                    cookies=cookies_i,
                    region=_clean_env(f"RIOT_REGION_{i}", default_region),
                    discord_user_id=_clean_env(f"DISCORD_USER_ID_{i}"),
                    channel_id=_clean_env(f"DISCORD_CHANNEL_ID_{i}")
                    or default_channel_id,
                )

        return accounts

    @staticmethod
    def _parse_accounts_blob(
        raw_blob: str,
        default_region: str,
        default_channel_id: str,
        add_fn,
    ) -> None:
        stripped = raw_blob.strip()
        if stripped.startswith("["):
            try:
                items = json.loads(stripped)
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, str):
                            add_fn(ssid=item)
                        elif isinstance(item, dict):
                            add_fn(
                                label=str(
                                    item.get("name")
                                    or item.get("label")
                                    or ""
                                ),
                                ssid=str(
                                    item.get("ssid")
                                    or item.get("riot_ssid")
                                    or ""
                                ),
                                cookies=str(
                                    item.get("cookies")
                                    or item.get("riot_cookies")
                                    or ""
                                ),
                                region=str(
                                    item.get("region")
                                    or item.get("riot_region")
                                    or default_region
                                ),
                                discord_user_id=str(
                                    item.get("discord_user_id")
                                    or item.get("user_id")
                                    or ""
                                ),
                                channel_id=str(
                                    item.get("channel_id")
                                    or item.get("discord_channel_id")
                                    or default_channel_id
                                ),
                            )
                    return
            except json.JSONDecodeError:
                pass

        # Multi-line or comma-separated format:
        # Each line can be:
        #   ssid
        #   名稱|ssid
        #   名稱|ssid|discord_user_id
        #   名稱|ssid|discord_user_id|channel_id|region
        for raw_line in stripped.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                parts = [p.strip() for p in line.split("|")]
                label = parts[0] if len(parts) > 0 else ""
                token_part = parts[1] if len(parts) > 1 else ""
                discord_user_id = parts[2] if len(parts) > 2 else ""
                channel_id = parts[3] if len(parts) > 3 else default_channel_id
                region = parts[4] if len(parts) > 4 else default_region
                if ";" in token_part and "ssid=" in token_part:
                    add_fn(
                        label=label,
                        cookies=token_part,
                        discord_user_id=discord_user_id,
                        channel_id=channel_id,
                        region=region,
                    )
                else:
                    add_fn(
                        label=label,
                        ssid=token_part,
                        discord_user_id=discord_user_id,
                        channel_id=channel_id,
                        region=region,
                    )
            else:
                # Support comma-separated simple SSIDs on a single line if no semicolons
                if "," in line and "ssid=" not in line and ";" not in line:
                    for sub_ssid in line.split(","):
                        if sub_ssid.strip():
                            add_fn(ssid=sub_ssid.strip())
                elif ";" in line and "ssid=" in line:
                    add_fn(cookies=line)
                else:
                    add_fn(ssid=line)

    def validate_discord(
        self, target_channel_id: Optional[str] = None
    ) -> None:
        channel_to_check = target_channel_id or self.discord_channel_id
        has_bot = bool(self.discord_bot_token and channel_to_check)
        has_webhook = bool(self.discord_webhook_url)
        if not has_bot and not has_webhook:
            raise ValueError(
                "缺少 Discord 設定：請在環境變數或 GitHub Secrets 中設定 "
                "`DISCORD_BOT_TOKEN` 與 `DISCORD_CHANNEL_ID`（或 `DISCORD_WEBHOOK_URL`）。"
            )

    def validate_riot(self) -> None:
        if not self.accounts:
            raise ValueError(
                "缺少 Riot 驗證資訊：請設定 `RIOT_ACCOUNTS`、`RIOT_SSID` 或 `RIOT_SSID_1`, `RIOT_SSID_2` 等。"
            )
