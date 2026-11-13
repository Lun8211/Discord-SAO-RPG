import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

from src.config import AccountConfig, Settings
from src.valorant_client import CookieCheckResult, DailyStoreReport


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


def format_remaining_duration(seconds: int) -> str:
    """Format a duration in seconds as human-readable Traditional Chinese text."""
    abs_sec = abs(int(seconds))
    days, rem = divmod(abs_sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    if days > 0:
        return f"{days} 天 {hours} 小時"
    if hours > 0:
        return f"{hours} 小時 {minutes} 分鐘"
    return f"{max(1, minutes)} 分鐘"


def build_cookie_status_payload(
    results: List[Tuple[AccountConfig, CookieCheckResult]],
    now_ts: Optional[int] = None,
) -> dict:
    """Build a Discord message payload summarizing Riot Cookie validity and remaining lifetime."""
    if now_ts is None:
        now_ts = int(time.time())

    valid_count = 0
    warn_count = 0
    invalid_count = 0
    fields: List[Dict] = []

    for acc, res in results:
        if not res.is_valid:
            emoji = "🔴"
            invalid_count += 1
        elif res.status_code in ("expiring_soon", "access_token"):
            emoji = "⚠️"
            warn_count += 1
        else:
            emoji = "🟢"
            valid_count += 1

        if res.player_name and res.player_name != "特戰英豪玩家":
            field_name = f"{emoji} [{acc.index}] {acc.display_label}（{res.player_name}）"
        else:
            field_name = f"{emoji} [{acc.index}] {acc.display_label}"

        lines: List[str] = []
        if acc.discord_user_id:
            lines.append(f"成員：<@{acc.discord_user_id}>")

        if res.is_valid:
            if res.status_code == "access_token":
                lines.append("狀態：**僅為短期 Access Token**（非長期 Cookie）")
            elif res.status_code == "expiring_soon":
                lines.append("狀態：**即將過期**（建議盡快更新）")
            else:
                lines.append("狀態：**正常有效**")

            if res.expires_at is not None and res.remaining_seconds is not None:
                exp_label = (
                    "估計到期" if res.expires_source == "set_cookie" else "到期時間"
                )
                if res.remaining_seconds > 0:
                    dur_text = format_remaining_duration(res.remaining_seconds)
                    lines.append(
                        f"剩餘效期：**{dur_text}**（<t:{res.expires_at}:R>）"
                    )
                    lines.append(f"{exp_label}：<t:{res.expires_at}:f>")
                else:
                    lines.append(
                        f"{exp_label}：<t:{res.expires_at}:f>（JWT 標記時間已屆，目前仍可換證，建議立即更新）"
                    )
            else:
                lines.append(
                    "剩餘效期：無法讀取（Riot 未在此 Cookie 內嵌到期時間，依經驗通常約 7～21 天）"
                )
        else:
            if res.status_code == "blocked":
                lines.append("狀態：**無法驗證**（Riot 端暫時回傳 HTTP 403）")
            elif res.status_code == "invalid_format":
                lines.append("狀態：**Cookie 格式不完整**（缺少 `ssid`）")
            elif res.status_code == "error":
                lines.append("狀態：**驗證時發生錯誤**")
            else:
                lines.append("狀態：**已失效／過期**（請重新抓取並更新 Secrets）")

            if res.expires_at is not None and res.remaining_seconds is not None:
                if res.remaining_seconds <= 0:
                    dur_text = format_remaining_duration(res.remaining_seconds)
                    lines.append(
                        f"過期時間：已於 **{dur_text}前**過期（<t:{res.expires_at}:f>）"
                    )
                else:
                    lines.append(
                        f"原定效期：<t:{res.expires_at}:f>（可能已在網頁點擊「登出」或被伺服器提前撤銷）"
                    )

            short_reason = res.message.split("診斷資訊：")[0].strip()
            if len(short_reason) > 140:
                short_reason = short_reason[:137] + "..."
            if short_reason:
                lines.append(f"說明：{short_reason}")

        if res.issued_at is not None:
            lines.append(f"簽發時間：<t:{res.issued_at}:R>")

        if res.token_source == "full_cookies":
            lines.append("類型：完整 Cookie 組")
        elif res.token_source == "ssid_only":
            lines.append("類型：僅 `ssid`（建議改貼完整 Cookie 可維持較久）")
        elif res.token_source == "access_token":
            lines.append("類型：Access Token（約 1 小時即失效，請改貼完整 Cookie）")

        field_value = "\n".join(lines)
        if len(field_value) > 1024:
            field_value = field_value[:1021] + "..."
        fields.append(
            {
                "name": field_name[:256],
                "value": field_value,
                "inline": False,
            }
        )

    if invalid_count > 0:
        color = 0xE74C3C
    elif warn_count > 0:
        color = 0xF39C12
    else:
        color = 0x2ECC71

    summary_desc = (
        f"共檢查 **{len(results)}** 個帳號："
        f"🟢 **{valid_count}** 正常 ｜ "
        f"⚠️ **{warn_count}** 需注意 ｜ "
        f"🔴 **{invalid_count}** 已失效"
    )
    iso_ts = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
    chunk_size = 10
    chunks = [fields[i : i + chunk_size] for i in range(0, len(fields), chunk_size)] or [[]]
    total_pages = len(chunks)

    embeds: List[Dict] = []
    for page_idx, chunk in enumerate(chunks[:10], start=1):
        title = "🍪 Riot Cookie 效期與狀態檢查"
        if total_pages > 1:
            title += f" ({page_idx}/{total_pages})"
        embed: Dict = {
            "title": title,
            "color": color,
            "fields": chunk,
            "footer": {
                "text": "💡 效期僅供參考；切勿在瀏覽器點擊「登出」，否則 Cookie 會立即失效"
            },
            "timestamp": iso_ts,
        }
        if page_idx == 1:
            embed["description"] = summary_desc
        embeds.append(embed)

    need_attention = invalid_count + warn_count
    content = (
        f"⚠️ 提醒：有 **{need_attention}** 個帳號的 Riot Cookie 已失效或即將過期，請留意更新！"
        if need_attention > 0
        else ""
    )

    return {
        "content": content,
        "embeds": embeds,
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
