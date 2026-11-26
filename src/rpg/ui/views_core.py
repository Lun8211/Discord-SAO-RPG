"""Core SAO Discord UI Views (OwnerView, ProfileView, BagView, SkillView)."""

from __future__ import annotations

from typing import Any

import discord

from src.rpg.engine import GameError, RPGEngine
from src.rpg.ui.embeds_core import (
    build_bag_embed,
    build_error_embed,
    build_monument_embed,
    build_profile_embed,
    build_skills_embed,
    build_yui_embed,
)


class OwnerView(discord.ui.View):
    """Base interactive View restricted to the invoking player."""

    def __init__(self, owner_id: int | str, *, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = str(owner_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.owner_id:
            await interaction.response.send_message(
                embed=build_error_embed("權限限制", "此操作介面屬於其他攻略者，請自行輸入指令開啟！"),
                ephemeral=True,
            )
            return False
        return True


class ProfileView(OwnerView):
    """Interactive character panel switching between Profile, Skills, Bag, Monument & Yui Console."""

    def __init__(self, engine: RPGEngine, user_id: str) -> None:
        super().__init__(user_id)
        self.engine = engine
        self.user_id = str(user_id)

    @discord.ui.button(label="🪪 角色面板", style=discord.ButtonStyle.primary, row=0)
    async def btn_profile(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            prof = self.engine.get_profile(self.user_id)
            await interaction.response.edit_message(embed=build_profile_embed(prof), view=self)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("查詢失敗", str(exc)), ephemeral=True)

    @discord.ui.button(label="⚔️ 劍技天賦", style=discord.ButtonStyle.secondary, row=0)
    async def btn_skills(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            prof = self.engine.get_profile(self.user_id)
            await interaction.response.edit_message(embed=build_skills_embed(prof, self.engine.content), view=self)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("查詢失敗", str(exc)), ephemeral=True)

    @discord.ui.button(label="🎒 裝備背包", style=discord.ButtonStyle.secondary, row=0)
    async def btn_bag(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            prof = self.engine.get_profile(self.user_id)
            await interaction.response.edit_message(embed=build_bag_embed(prof, self.engine.content), view=self)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("查詢失敗", str(exc)), ephemeral=True)

    @discord.ui.button(label="🪦 生命之碑", style=discord.ButtonStyle.secondary, row=1)
    async def btn_monument(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            data = self.engine.get_monument_of_life(limit=8)
            await interaction.response.edit_message(embed=build_monument_embed(data), view=self)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("查詢失敗", str(exc)), ephemeral=True)

    @discord.ui.button(label="👧 結衣終端機", style=discord.ButtonStyle.success, row=1)
    async def btn_yui(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            data = self.engine.get_yui_logs(self.user_id)
            await interaction.response.edit_message(embed=build_yui_embed(data), view=self)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("查詢失敗", str(exc)), ephemeral=True)

    @discord.ui.button(label="📬 領取待領信箱", style=discord.ButtonStyle.primary, row=1)
    async def btn_claim_mail(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.claim_pending_loot(self.user_id)
            await interaction.response.send_message(res["message"], ephemeral=True)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("領取失敗", str(exc)), ephemeral=True)
