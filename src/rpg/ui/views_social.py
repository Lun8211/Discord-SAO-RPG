"""Workshop, Cooking, Shop, Market, Guild, Daily/Quest & Leaderboard Discord UI Views."""

from __future__ import annotations

from typing import Any

import discord

from src.rpg.engine import GameError, RPGEngine
from src.rpg.ui.embeds_core import build_error_embed, build_leaderboard_embed
from src.rpg.ui.embeds_social import build_quests_embed, build_shop_embed
from src.rpg.ui.views_core import OwnerView


class ShopView(OwnerView):
    """Quick shop buttons for SAO Crystals and Recovery Potions."""

    def __init__(self, engine: RPGEngine, user_id: str) -> None:
        super().__init__(user_id)
        self.engine = engine
        self.user_id = str(user_id)

    async def _buy(self, interaction: discord.Interaction, item_id: str) -> None:
        try:
            res = self.engine.buy_shop_item(self.user_id, item_id, qty=1)
            await interaction.response.edit_message(embed=build_shop_embed(res), view=self)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("購買失敗", str(exc)), ephemeral=True)

    @discord.ui.button(label="🧪 回復藥水", style=discord.ButtonStyle.primary, row=0)
    async def btn_pot(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._buy(interaction, "hp_potion_t1")

    @discord.ui.button(label="❤️ 回復水晶", style=discord.ButtonStyle.danger, row=0)
    async def btn_heal(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._buy(interaction, "healing_crystal")

    @discord.ui.button(label="💎 轉移水晶", style=discord.ButtonStyle.primary, row=0)
    async def btn_tp(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._buy(interaction, "teleport_crystal")

    @discord.ui.button(label="💚 解毒水晶", style=discord.ButtonStyle.success, row=0)
    async def btn_anti(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._buy(interaction, "antidote_crystal")


class LeaderboardView(discord.ui.View):
    """Public 7-Category SAO Leaderboard switcher."""

    def __init__(self, engine: RPGEngine) -> None:
        super().__init__(timeout=300.0)
        self.engine = engine

    @discord.ui.select(
        placeholder="選擇艾恩葛朗特排行榜類別（7 大榜單）",
        options=[
            discord.SelectOption(label="🏰 樓層攻略榜", value="floor"),
            discord.SelectOption(label="⚡ 綜合戰力榜", value="power"),
            discord.SelectOption(label="⭐ 等級威望榜", value="level"),
            discord.SelectOption(label="🌍 世界王傷害榜", value="world_boss"),
            discord.SelectOption(label="🛡️ 公會榮耀榜", value="guild"),
            discord.SelectOption(label="💰 柯爾富豪榜", value="col"),
            discord.SelectOption(label="🔥 生存連勝榜", value="survival"),
        ],
        row=0,
    )
    async def sel_category(self, interaction: discord.Interaction, select: discord.ui.Select[Any]) -> None:
        cat = str(select.values[0])
        data = self.engine.get_leaderboard(cat, limit=10)
        await interaction.response.edit_message(embed=build_leaderboard_embed(data), view=self)


class DailyQuestView(OwnerView):
    """Quick Daily check-in and Quest list refresh View."""

    def __init__(self, engine: RPGEngine, user_id: str) -> None:
        super().__init__(user_id)
        self.engine = engine
        self.user_id = str(user_id)

    @discord.ui.button(label="📅 立即每日簽到", style=discord.ButtonStyle.success, row=0)
    async def btn_daily(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.claim_daily(self.user_id)
            await interaction.response.send_message(res["message"], ephemeral=True)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("簽到提示", str(exc)), ephemeral=True)

    @discord.ui.button(label="📋 重整任務進度", style=discord.ButtonStyle.primary, row=0)
    async def btn_quests(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.get_quests(self.user_id)
            await interaction.response.edit_message(embed=build_quests_embed(res), view=self)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("查詢失敗", str(exc)), ephemeral=True)
