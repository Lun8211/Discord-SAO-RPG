"""Discord `/p` slash command outputting pure anime meme images without any text."""

from __future__ import annotations

import io
import logging
from typing import List, Optional

import discord
from discord import app_commands

from src.memes.catalog import AnimeMemeService, MemeEntry

logger = logging.getLogger("rpg-dc-bot")


def build_meme_embed(meme: MemeEntry) -> discord.Embed:
    """Build a pure image-only Discord Embed with no title, description, footer, or fields."""
    embed = discord.Embed()
    embed.set_image(url=meme.url)
    return embed


def create_meme_commands(service: AnimeMemeService) -> List[app_commands.Command]:
    """Create and return the top-level `/p` anime meme slash command."""

    @app_commands.command(
        name="p",
        description="隨機發送一張二次元梗圖／表情包（純圖片輸出，支援分類與關鍵字搜尋）",
    )
    @app_commands.describe(
        category="（選填）選擇梗圖分類，不填則從全圖庫平衡隨機抽選",
        keyword="（選填）輸入關鍵字搜尋梗圖（例：吃飯、下班、原神、芙莉蓮、大肥魚、生氣）",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="🎲 隨機全部（綜合平衡）", value="all"),
            app_commands.Choice(name="🎀 二次元綜合梗圖（貓娘／萌系表情包）", value="acg_mix"),
            app_commands.Choice(name="✨ 經典動漫梗圖（原神／芙莉蓮／北方栖姬等）", value="anime_classic"),
            app_commands.Choice(name="🐋 藍色大肥魚／DeepSeek娘", value="deepseek"),
            app_commands.Choice(name="🎞️ 二次元動態 GIF 梗圖", value="gif"),
        ]
    )
    async def anime_meme_p(
        interaction: discord.Interaction,
        category: Optional[str] = "all",
        keyword: Optional[str] = None,
    ) -> None:
        cat = category or "all"
        kw = (keyword or "").strip() or None

        await interaction.response.defer()
        if not service.is_loaded:
            await service.ensure_loaded()
        else:
            service.trigger_background_refresh_if_stale()

        channel_key = str(interaction.channel_id or "global")
        meme, _, _ = service.pick_random(
            category=cat,
            keyword=kw,
            history_key=channel_key,
        )

        if meme is None:
            hint = (
                f"🔍 找不到符合「**{kw}**」的二次元梗圖！"
                if kw
                else "⚠️ 目前該分類暫無可用梗圖，請稍後再試。"
            )
            await interaction.followup.send(hint, ephemeral=True)
            return

        downloaded = await service.download_image(meme.url)
        if downloaded is not None:
            img_bytes, filename = downloaded
            try:
                await interaction.followup.send(
                    file=discord.File(io.BytesIO(img_bytes), filename=filename)
                )
                return
            except discord.HTTPException as exc:
                logger.warning("上傳梗圖附件失敗，改用純圖片 Embed 備援發送: %s", exc)

        await interaction.followup.send(embed=build_meme_embed(meme))

    return [anime_meme_p]


def register_meme_commands(
    tree: app_commands.CommandTree, service: AnimeMemeService
) -> List[app_commands.Command]:
    """Attach the `/p` anime meme slash command onto a Discord CommandTree."""
    commands = create_meme_commands(service)
    for cmd in commands:
        if tree.get_command(cmd.name) is not None:
            tree.remove_command(cmd.name)
        tree.add_command(cmd)
    return commands
