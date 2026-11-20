"""Discord `/p` slash command, Embed builder, and interactive reroll View for anime memes."""

from __future__ import annotations

from typing import List, Optional

import discord
from discord import app_commands

from src.memes.catalog import (
    THEME_COLORS,
    THEME_LABELS,
    AnimeMemeService,
    MemeEntry,
)


def build_meme_embed(
    meme: MemeEntry,
    *,
    total_count: int,
    match_count: Optional[int] = None,
    category: str = "all",
    keyword: Optional[str] = None,
    using_fallback: bool = False,
) -> discord.Embed:
    """Build a crisp Discord Embed showcasing a random anime meme image."""
    color = THEME_COLORS.get("gif" if category == "gif" else meme.theme, 0xFF6B9D)
    title_text = f"🎭 {meme.title}" if meme.title else f"🎭 {meme.source_name}"
    if len(title_text) > 256:
        title_text = title_text[:255] + "…"

    embed = discord.Embed(title=title_text, color=color)
    embed.set_image(url=meme.url)

    footer_parts: List[str] = [f"來源：{meme.source_name}（{meme.source_repo}）"]
    if keyword:
        shown_matches = match_count if match_count is not None else 1
        footer_parts.append(f"🔍「{keyword}」命中 {shown_matches:,} 張")
    elif category and category != "all":
        cat_label = THEME_LABELS.get(category, category)
        shown_matches = match_count if match_count is not None else total_count
        footer_parts.append(f"{cat_label}（{shown_matches:,} 張）")
    else:
        footer_parts.append(f"線上圖庫共 {total_count:,} 張")

    if using_fallback:
        footer_parts.append("備援模式")

    embed.set_footer(text=" ｜ ".join(footer_parts)[:2048])
    return embed


class AnimeMemeView(discord.ui.View):
    """Interactive controls under a `/p` meme embed: reroll in place, draw new, or open original."""

    def __init__(
        self,
        service: AnimeMemeService,
        invoker_id: int,
        *,
        category: str = "all",
        keyword: Optional[str] = None,
        meme_url: str = "",
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.service = service
        self.invoker_id = invoker_id
        self.category = category
        self.keyword = keyword

        if meme_url and meme_url.startswith("https://") and len(meme_url) <= 512:
            self.add_item(
                discord.ui.Button(
                    label="原圖",
                    emoji="🔗",
                    style=discord.ButtonStyle.link,
                    url=meme_url,
                    row=0,
                )
            )

    async def _draw_meme(
        self, interaction: discord.Interaction
    ) -> tuple[Optional[MemeEntry], int, int]:
        await self.service.ensure_loaded()
        channel_key = str(interaction.channel_id or "global")
        return self.service.pick_random(
            category=self.category,
            keyword=self.keyword,
            history_key=channel_key,
        )

    @discord.ui.button(label="換一張", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def reroll_in_place(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                "💡 只有原本召喚這張梗圖的人才能直接覆蓋換圖，你可以點旁邊的 **🎲 再來一張** 或輸入 `/p` 自己抽一張！",
                ephemeral=True,
            )
            return

        meme, match_count, total_count = await self._draw_meme(interaction)
        if meme is None:
            await interaction.response.send_message(
                "⚠️ 找不到更多符合條件的梗圖，請重新輸入 `/p` 試試！",
                ephemeral=True,
            )
            return

        embed = build_meme_embed(
            meme,
            total_count=total_count,
            match_count=match_count,
            category=self.category,
            keyword=self.keyword,
            using_fallback=self.service.using_fallback,
        )
        new_view = AnimeMemeView(
            self.service,
            self.invoker_id,
            category=self.category,
            keyword=self.keyword,
            meme_url=meme.url,
        )
        await interaction.response.edit_message(embed=embed, view=new_view)

    @discord.ui.button(label="再來一張", emoji="🎲", style=discord.ButtonStyle.secondary, row=0)
    async def draw_another(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        meme, match_count, total_count = await self._draw_meme(interaction)
        if meme is None:
            await interaction.response.send_message(
                "⚠️ 找不到更多符合條件的梗圖，請重新輸入 `/p` 試試！",
                ephemeral=True,
            )
            return

        embed = build_meme_embed(
            meme,
            total_count=total_count,
            match_count=match_count,
            category=self.category,
            keyword=self.keyword,
            using_fallback=self.service.using_fallback,
        )
        new_view = AnimeMemeView(
            self.service,
            interaction.user.id,
            category=self.category,
            keyword=self.keyword,
            meme_url=meme.url,
        )
        await interaction.response.send_message(embed=embed, view=new_view)


def create_meme_commands(service: AnimeMemeService) -> List[app_commands.Command]:
    """Create and return the top-level `/p` anime meme slash command."""

    @app_commands.command(
        name="p",
        description="隨機產生一張二次元梗圖／表情包（支援分類篩選與關鍵字搜尋）",
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
        deferred = False

        if not service.is_loaded:
            await interaction.response.defer()
            deferred = True
            await service.ensure_loaded()
        else:
            service.trigger_background_refresh_if_stale()

        channel_key = str(interaction.channel_id or "global")
        meme, match_count, total_count = service.pick_random(
            category=cat,
            keyword=kw,
            history_key=channel_key,
        )

        if meme is None:
            hint = (
                f"🔍 找不到符合「**{kw}**」的二次元梗圖！\n"
                "試試其他關鍵字（例如：`吃飯`、`下班`、`原神`、`芙莉蓮`、`大肥魚`、`貓娘`、`生氣`），或直接輸入 `/p` 隨機抽選。"
                if kw
                else "⚠️ 目前該分類暫無可用梗圖，請稍後再試或改選「隨機全部」。"
            )
            if deferred:
                await interaction.followup.send(hint, ephemeral=True)
            else:
                await interaction.response.send_message(hint, ephemeral=True)
            return

        embed = build_meme_embed(
            meme,
            total_count=total_count,
            match_count=match_count,
            category=cat,
            keyword=kw,
            using_fallback=service.using_fallback,
        )
        view = AnimeMemeView(
            service,
            interaction.user.id,
            category=cat,
            keyword=kw,
            meme_url=meme.url,
        )

        if deferred:
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

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
