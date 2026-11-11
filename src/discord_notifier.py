import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from src.config import Settings
from src.valorant_client import DailyStoreReport


class DiscordNotifyError(Exception):
    """Raised when sending a message to Discord fails."""


def build_store_message_payload(
    report: DailyStoreReport, now_ts: Optional[int] = None
) -> dict:
    """Build a Discord message payload with 4 separate Embed cards for the 4 daily store items."""
    if now_ts is None:
        now_ts = int(time.time())

    reset_ts = now_ts + max(0, report.remaining_seconds)

    label_prefix = f"【{report.account_label}】" if report.account_label else ""
    mention_suffix = (
        f" (<@{report.discord_user_id}>)" if report.discord_user_id else ""
    )
    display_identity = f"**{label_prefix}{report.player_name}**{mention_suffix}"

    header_lines = [
        f"🛒 {display_identity} 的 **VALORANT 每日商店** 已刷新！",
        f"⏳ 距離下次刷新：<t:{reset_ts}:R>（<t:{reset_ts}:t>）",
    ]
    if report.wallet is not None:
        header_lines.append(
            f"💎 **VP：** `{report.wallet.vp:,}` ｜ "
            f"✨ **輻能點數：** `{report.wallet.radianite:,}` ｜ "
            f"🪙 **王國幣：** `{report.wallet.kingdom_credits:,}`"
        )

    embeds: List[Dict] = []
    total_items = len(report.items)
    footer_owner = (
        f"{report.account_label} ({report.player_name})"
        if report.account_label
        else report.player_name
    )

    for idx, item in enumerate(report.items[:4], start=1):
        embed: Dict = {
            "title": item.name,
            "color": item.tier_color,
            "fields": [
                {
                    "name": "💎 造型價格",
                    "value": f"**`{item.price_vp:,} VP`**"
                    if item.price_vp > 0
                    else "`未知`",
                    "inline": True,
                },
                {
                    "name": "🏷️ 稀有度等級",
                    "value": f"**{item.tier_name}**",
                    "inline": True,
                },
            ],
            "footer": {
                "text": f"VALORANT 每日商店 • {footer_owner} • 欄位 {idx}/{total_items}"
            },
            "timestamp": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
        }

        author_obj: Dict[str, str] = {"name": f"每日商店 #{idx} ｜ {item.tier_name}"}
        if item.tier_icon_url:
            author_obj["icon_url"] = item.tier_icon_url
        embed["author"] = author_obj

        if item.video_url:
            embed["url"] = item.video_url
            embed["fields"].append(
                {
                    "name": "🎬 特效預覽",
                    "value": f"[點此觀看造型展示影片]({item.video_url})",
                    "inline": True,
                }
            )

        if item.icon_url:
            embed["image"] = {"url": item.icon_url}

        embeds.append(embed)

    return {
        "content": "\n".join(header_lines),
        "embeds": embeds,
    }


def build_error_message_payload(
    error_message: str,
    account_label: str = "",
    discord_user_id: str = "",
) -> dict:
    """Build an alert embed payload when Riot authentication or API fails for an account."""
    target_title = f"（{account_label}）" if account_label else ""
    mention_str = f" <@{discord_user_id}>" if discord_user_id else ""
    return {
        "content": f"⚠️ **VALORANT 每日商店機器人執行提醒{target_title}**{mention_str}",
        "embeds": [
            {
                "title": f"❌ 無法取得{target_title}今日特戰英豪商店",
                "description": (
                    f"{error_message}\n\n"
                    "💡 **解決方式：**\n"
                    "若為 `ssid` Cookie 過期，請該帳號重新在瀏覽器登入 Riot 帳號取得最新的 `ssid` Cookie，"
                    "並更新至 `.env` 或 GitHub Repository Secrets。"
                ),
                "color": 0xE74C3C,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }


def send_via_bot_token(
    bot_token: str, channel_id: str, payload: dict, timeout: int = 20
) -> dict:
    """Send message payload to a Discord channel using a Bot Token via Discord REST API v10."""
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if resp.status_code not in (200, 201):
        raise DiscordNotifyError(
            f"透過 Discord Bot 發送訊息失敗 (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    return resp.json()


def send_via_webhook(
    webhook_url: str, payload: dict, timeout: int = 20
) -> dict:
    """Send message payload to a Discord channel using a Webhook URL."""
    sep = "&" if "?" in webhook_url else "?"
    url = f"{webhook_url}{sep}wait=true"
    resp = requests.post(url, json=payload, timeout=timeout)
    if resp.status_code not in (200, 201, 204):
        raise DiscordNotifyError(
            f"透過 Discord Webhook 發送訊息失敗 (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    return resp.json() if resp.text else {}


def send_discord_payload(
    settings: Settings, payload: dict, target_channel_id: Optional[str] = None
) -> None:
    """Send payload using configured Discord Bot Token + Channel ID, or Webhook URL."""
    channel_id = target_channel_id or settings.discord_channel_id
    settings.validate_discord(target_channel_id=channel_id)
    if settings.discord_bot_token and channel_id:
        send_via_bot_token(settings.discord_bot_token, channel_id, payload)
    elif settings.discord_webhook_url:
        send_via_webhook(settings.discord_webhook_url, payload)
