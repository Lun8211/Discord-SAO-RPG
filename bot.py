import asyncio
import datetime
import logging

import discord
from discord import app_commands
from discord.ext import tasks

from src.config import Settings
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
    embed = discord.Embed.from_dict(embed_dict)
    return embed


class ValorantStoreBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        await self.tree.sync()
        self.daily_store_task.start()

    async def on_ready(self) -> None:
        logger.info("🤖 機器人已上線：%s (ID: %s)", self.user, self.user.id if self.user else "")

    async def fetch_payload_async(self) -> dict:
        def _fetch() -> dict:
            client = ValorantClient(
                riot_ssid=settings.riot_ssid,
                riot_cookies=settings.riot_cookies,
                region=settings.riot_region,
                language=settings.valorant_lang,
            )
            report = client.fetch_daily_store_report()
            return build_store_message_payload(report)

        return await asyncio.to_thread(_fetch)

    @tasks.loop(time=_get_daily_time())
    async def daily_store_task(self) -> None:
        if not settings.discord_channel_id:
            return
        channel = self.get_channel(int(settings.discord_channel_id))
        if channel is None:
            channel = await self.fetch_channel(int(settings.discord_channel_id))

        try:
            payload = await self.fetch_payload_async()
            embeds = [_dict_to_discord_embed(e) for e in payload.get("embeds", [])]
            await channel.send(content=payload.get("content", ""), embeds=embeds)
            logger.info("✅ 每日定時商店已發送至頻道 %s", settings.discord_channel_id)
        except Exception as exc:
            logger.error("❌ 每日定時發送失敗: %s", exc)
            err_payload = build_error_message_payload(str(exc))
            embeds = [_dict_to_discord_embed(e) for e in err_payload.get("embeds", [])]
            await channel.send(content=err_payload.get("content", ""), embeds=embeds)

    @daily_store_task.before_loop
    async def before_daily_store(self) -> None:
        await self.wait_until_ready()


bot = ValorantStoreBot()


@bot.tree.command(name="shop", description="立即查看今日的特戰英豪 (VALORANT) 每日商店 4 個刷新物品")
async def shop_command(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    try:
        payload = await bot.fetch_payload_async()
        embeds = [_dict_to_discord_embed(e) for e in payload.get("embeds", [])]
        await interaction.followup.send(
            content=payload.get("content", ""), embeds=embeds
        )
    except Exception as exc:
        err_payload = build_error_message_payload(str(exc))
        embeds = [_dict_to_discord_embed(e) for e in err_payload.get("embeds", [])]
        await interaction.followup.send(
            content=err_payload.get("content", ""), embeds=embeds
        )


if __name__ == "__main__":
    if not settings.discord_bot_token:
        raise SystemExit("請先設定 DISCORD_BOT_TOKEN 環境變數。")
    bot.run(settings.discord_bot_token)
