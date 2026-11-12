import argparse
import asyncio
import datetime
import logging
from typing import List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import tasks

from src.config import AccountConfig, Settings
from src.discord_notifier import (
    build_error_message_payload,
    build_store_message_payload,
)
from src.valorant_client import ValorantClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("val-dc-bot")

settings = Settings.from_env()


def _get_daily_time() -> datetime.time:
    parts = settings.daily_post_time.split(":")
    hour = int(parts[0]) if len(parts) >= 1 and parts[0].isdigit() else 8
    minute = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 5
    tz = datetime.timezone(datetime.timedelta(hours=settings.timezone_offset_hours))
    return datetime.time(hour=hour, minute=minute, tzinfo=tz)


def _dict_to_discord_embed(embed_dict: dict) -> discord.Embed:
    return discord.Embed.from_dict(embed_dict)


class ValorantStoreBot(discord.Client):
    def __init__(self, run_minutes: int = 0) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.run_minutes = run_minutes
        self._synced_guilds = False

    async def setup_hook(self) -> None:
        await self.tree.sync()
        self.daily_store_task.start()
        if self.run_minutes > 0:
            asyncio.create_task(self._auto_shutdown_after(self.run_minutes))

    async def _auto_shutdown_after(self, minutes: int) -> None:
        await self.wait_until_ready()
        logger.info("⏳ 機器人將於 %d 分鐘後自動安全下線...", minutes)
        await asyncio.sleep(minutes * 60)
        logger.info("⏹️ 已達設定執行時間 (%d 分鐘)，正在安全關閉機器人...", minutes)
        await self.close()

    async def on_ready(self) -> None:
        logger.info(
            "🤖 機器人已上線：%s (ID: %s)，共載入 %d 個帳號",
            self.user,
            self.user.id if self.user else "",
            len(settings.accounts),
        )
        if not self._synced_guilds:
            self._synced_guilds = True
            for guild in self.guilds:
                try:
                    self.tree.copy_global_to(guild=guild)
                    await self.tree.sync(guild=guild)
                    logger.info("✅ 已即時同步 /shop 斜線指令至伺服器：%s (%s)", guild.name, guild.id)
                except Exception as exc:
                    logger.warning("同步斜線指令至伺服器 %s 失敗: %s", guild.id, exc)

    async def fetch_all_payloads_async(
        self,
        target_filter: Optional[str] = None,
        caller_discord_id: Optional[str] = None,
    ) -> List[Tuple[AccountConfig, dict]]:
        def _fetch_all() -> List[Tuple[AccountConfig, dict]]:
            shared_client = ValorantClient(
                region=settings.riot_region,
                language=settings.valorant_lang,
            )
            client_version = shared_client.get_client_version()
            skin_catalog = shared_client.fetch_skin_catalog()

            results: List[Tuple[AccountConfig, dict]] = []
            q = (target_filter or "").strip().lower()
            for acc in settings.accounts:
                if q and q not in ("all", "全部", "全部帳號"):
                    if q in ("me", "我自己", "自己"):
                        if not caller_discord_id or acc.discord_user_id != caller_discord_id:
                            continue
                    elif (
                        q != str(acc.index)
                        and q not in acc.label.lower()
                        and q not in acc.display_label.lower()
                        and q.strip("<@!>") != acc.discord_user_id
                    ):
                        continue
                try:
                    client = ValorantClient(
                        riot_ssid=acc.riot_ssid,
                        riot_cookies=acc.riot_cookies,
                        region=acc.riot_region or settings.riot_region,
                        language=settings.valorant_lang,
                    )
                    report = client.fetch_daily_store_report(
                        account_label=acc.label,
                        discord_user_id=acc.discord_user_id,
                        skin_catalog=skin_catalog,
                        client_version=client_version,
                    )
                    payload = build_store_message_payload(report)
                except Exception as exc:
                    payload = build_error_message_payload(
                        str(exc),
                        account_label=acc.display_label,
                        discord_user_id=acc.discord_user_id,
                    )
                results.append((acc, payload))
            return results

        return await asyncio.to_thread(_fetch_all)

    @tasks.loop(time=_get_daily_time())
    async def daily_store_task(self) -> None:
        results = await self.fetch_all_payloads_async()
        for acc, payload in results:
            channel_id_str = acc.discord_channel_id or settings.discord_channel_id
            if not channel_id_str:
                continue
            channel = self.get_channel(int(channel_id_str))
            if channel is None:
                channel = await self.fetch_channel(int(channel_id_str))

            embeds = [_dict_to_discord_embed(e) for e in payload.get("embeds", [])]
            await channel.send(content=payload.get("content", ""), embeds=embeds)
            logger.info("✅ 每日定時商店已發送 [%s] 至頻道 %s", acc.display_label, channel_id_str)
            await asyncio.sleep(1.0)

    @daily_store_task.before_loop
    async def before_daily_store(self) -> None:
        await self.wait_until_ready()


bot = ValorantStoreBot()


@bot.tree.command(
    name="shop", description="立即手動執行一次特戰英豪 (VALORANT) 每日商店查詢與推送"
)
@app_commands.describe(account="（選填）選擇要查詢的帳號（不填則一次執行全部帳號）")
async def shop_command(
    interaction: discord.Interaction, account: Optional[str] = None
) -> None:
    await interaction.response.defer()
    caller_id = str(interaction.user.id) if interaction.user else None
    results = await bot.fetch_all_payloads_async(
        target_filter=account, caller_discord_id=caller_id
    )
    if not results:
        await interaction.followup.send("⚠️ 找不到符合條件的特戰英豪帳號設定。")
        return

    for idx, (_, payload) in enumerate(results):
        embeds = [_dict_to_discord_embed(e) for e in payload.get("embeds", [])]
        await interaction.followup.send(
            content=payload.get("content", ""), embeds=embeds
        )
        if idx + 1 < len(results):
            await asyncio.sleep(0.5)


@shop_command.autocomplete("account")
async def shop_account_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    choices: List[app_commands.Choice[str]] = [
        app_commands.Choice(name="📋 全部帳號 (執行所有人)", value="all"),
        app_commands.Choice(name="🙋 我自己 (依 Discord ID 對應)", value="me"),
    ]
    for acc in settings.accounts:
        display = f"[{acc.index}] {acc.display_label}"
        choices.append(app_commands.Choice(name=display[:100], value=str(acc.index)))
    if not current:
        return choices[:25]
    q = current.lower()
    return [c for c in choices if q in c.name.lower() or q in c.value.lower()][:25]


def parse_bot_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VALORANT 每日商店常駐型 Discord Bot")
    parser.add_argument(
        "--run-minutes",
        type=int,
        default=0,
        help="設定機器人執行幾分鐘後自動下線（0 代表持續常駐不關閉）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_bot_args()
    if not settings.discord_bot_token:
        raise SystemExit("請先設定 DISCORD_BOT_TOKEN 環境變數。")
    bot.run_minutes = args.run_minutes
    bot.run(settings.discord_bot_token)

