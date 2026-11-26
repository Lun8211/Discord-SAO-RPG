"""Public Real-Human Multiplayer PartyLobbyView, CoopRaidView (w/ asyncio.Lock), WorldBossView & DuelView."""

from __future__ import annotations

import asyncio
from typing import Any

import discord

from src.rpg.engine import GameError, RPGEngine
from src.rpg.ui.embeds_core import build_error_embed
from src.rpg.ui.embeds_party import (
    build_coop_raid_embed,
    build_duel_embed,
    build_party_lobby_embed,
    build_world_boss_embed,
)


class PartyLobbyView(discord.ui.View):
    """PUBLIC multiplayer party lobby — ANY real Discord human can join, pick role, toggle ready & engage!"""

    def __init__(self, engine: RPGEngine, party_id: str, *, timeout: float = 600.0) -> None:
        super().__init__(timeout=timeout)
        self.engine = engine
        self.party_id = str(party_id)
        self._ui_lock = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Public view: all real Discord humans are permitted to interact!
        return True

    @discord.ui.button(label="🤝 加入隊伍", style=discord.ButtonStyle.success, row=0)
    async def btn_join(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.join_party(self.party_id, str(interaction.user.id))
                await interaction.response.edit_message(embed=build_party_lobby_embed(res), view=self)
            except GameError as exc:
                await interaction.response.send_message(embed=build_error_embed("無法加入隊伍", str(exc)), ephemeral=True)

    @discord.ui.button(label="✅ 切換準備", style=discord.ButtonStyle.primary, row=0)
    async def btn_ready(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                uid = str(interaction.user.id)
                lobby = self.engine.db.get_party(self.party_id)
                cur_ready = lobby.members[uid].is_ready if (lobby and uid in lobby.members) else False
                res = self.engine.set_party_ready(self.party_id, uid, not cur_ready)
                await interaction.response.edit_message(embed=build_party_lobby_embed(res), view=self)
            except GameError as exc:
                await interaction.response.send_message(embed=build_error_embed("切換準備失敗", str(exc)), ephemeral=True)

    @discord.ui.button(label="🧪 我要出藥", style=discord.ButtonStyle.secondary, row=0)
    async def btn_potion_share(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                uid = str(interaction.user.id)
                lobby = self.engine.db.get_party(self.party_id)
                cur = lobby.members[uid].potion_sharing if (lobby and uid in lobby.members) else False
                res = self.engine.toggle_potion_sharing(self.party_id, uid, not cur)
                await interaction.response.send_message(res["message"], ephemeral=True)
            except GameError as exc:
                await interaction.response.send_message(embed=build_error_embed("設定失敗", str(exc)), ephemeral=True)

    @discord.ui.button(label="🚪 進入頭目房", style=discord.ButtonStyle.primary, row=1)
    async def btn_enter_room(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.enter_boss_room(self.party_id, str(interaction.user.id))
                await interaction.response.edit_message(embed=build_party_lobby_embed(res), view=self)
            except GameError as exc:
                await interaction.response.send_message(embed=build_error_embed("進入頭目房失敗", str(exc)), ephemeral=True)

    @discord.ui.button(label="⚔️ 全員開戰！", style=discord.ButtonStyle.danger, row=1)
    async def btn_start_raid(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.start_party_raid(self.party_id, str(interaction.user.id))
                raid_view = CoopRaidView(self.engine, str(res["raid_id"]))
                await interaction.response.edit_message(embed=build_coop_raid_embed(res), view=raid_view)
            except GameError as exc:
                await interaction.response.send_message(embed=build_error_embed("開戰失敗", str(exc)), ephemeral=True)

    @discord.ui.button(label="🏃 離開隊伍", style=discord.ButtonStyle.secondary, row=1)
    async def btn_leave(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.leave_party(self.party_id, str(interaction.user.id))
                next_view = None if res.get("disbanded") else self
                await interaction.response.edit_message(embed=build_party_lobby_embed(res), view=next_view)
            except GameError as exc:
                await interaction.response.send_message(embed=build_error_embed("離隊失敗", str(exc)), ephemeral=True)


class CoopRaidView(discord.ui.View):
    """PUBLIC synchronized multi-human co-op Boss Raid HUD with per-raid `asyncio.Lock`."""

    def __init__(self, engine: RPGEngine, raid_id: str, *, timeout: float = 900.0) -> None:
        super().__init__(timeout=timeout)
        self.engine = engine
        self.raid_id = str(raid_id)
        self._ui_lock = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def _submit(
        self,
        interaction: discord.Interaction,
        action: str,
        *,
        skill_id: str | None = None,
        item_id: str | None = None,
    ) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.submit_raid_action(
                    self.raid_id,
                    str(interaction.user.id),
                    action,
                    skill_id=skill_id,
                    item_id=item_id,
                )
                next_view = None if res.get("finished") else self
                await interaction.response.edit_message(embed=build_coop_raid_embed(res), view=next_view)
            except GameError as exc:
                await interaction.response.send_message(embed=build_error_embed("行動受阻", str(exc)), ephemeral=True)

    @discord.ui.button(label="🗡️ 普通斬擊", style=discord.ButtonStyle.primary, row=0)
    async def btn_attack(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._submit(interaction, "attack")

    @discord.ui.button(label="⚔️ 劍技", style=discord.ButtonStyle.danger, row=0)
    async def btn_skill(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        uid = str(interaction.user.id)
        try:
            prof = self.engine.get_profile(uid)
            slots = list(prof.get("skill_slots") or [])
            sid = slots[0] if slots else "slant"
        except GameError:
            sid = "slant"
        await self._submit(interaction, "skill", skill_id=sid)

    @discord.ui.button(label="⇄ 交換 Switch", style=discord.ButtonStyle.success, row=0)
    async def btn_switch(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._submit(interaction, "switch")

    @discord.ui.button(label="⚡ 彈反 Parry", style=discord.ButtonStyle.secondary, row=0)
    async def btn_parry(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._submit(interaction, "parry")

    @discord.ui.button(label="🛡️ 防禦", style=discord.ButtonStyle.secondary, row=0)
    async def btn_defend(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._submit(interaction, "defend")

    @discord.ui.button(label="❤️ 回復水晶", style=discord.ButtonStyle.success, row=1)
    async def btn_crystal(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._submit(interaction, "crystal", item_id="healing_crystal")

    @discord.ui.button(label="⏱️ 立即／逾時結算", style=discord.ButtonStyle.primary, row=1)
    async def btn_resolve(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.resolve_raid_round(
                    self.raid_id, requester_id=str(interaction.user.id), force_timeout=True
                )
                next_view = None if res.get("finished") else self
                await interaction.response.edit_message(embed=build_coop_raid_embed(res), view=next_view)
            except GameError as exc:
                await interaction.response.send_message(embed=build_error_embed("無法結算回合", str(exc)), ephemeral=True)


class WorldBossView(discord.ui.View):
    """Public Floor World Boss attack view."""

    def __init__(self, engine: RPGEngine) -> None:
        super().__init__(timeout=300.0)
        self.engine = engine

    @discord.ui.button(label="🌍 挑戰全服世界王", style=discord.ButtonStyle.danger, row=0)
    async def btn_hit(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.attack_floor_world_boss(str(interaction.user.id))
            await interaction.response.edit_message(embed=build_world_boss_embed(res), view=self)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("挑戰失敗", str(exc)), ephemeral=True)


class DuelView(discord.ui.View):
    """Public consent-gated PvP Duel View (Accept + Combat actions)."""

    def __init__(self, engine: RPGEngine, duel_id: str) -> None:
        super().__init__(timeout=300.0)
        self.engine = engine
        self.duel_id = str(duel_id)

    @discord.ui.button(label="🤝 接受決鬥", style=discord.ButtonStyle.success, row=0)
    async def btn_accept(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.accept_duel(self.duel_id, str(interaction.user.id))
            await interaction.response.edit_message(embed=build_duel_embed(res), view=self)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("無法接受決鬥", str(exc)), ephemeral=True)

    @discord.ui.button(label="⚔️ 決鬥出擊", style=discord.ButtonStyle.danger, row=0)
    async def btn_attack(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.duel_action(self.duel_id, str(interaction.user.id), "attack")
            next_view = None if res.get("finished") else self
            await interaction.response.edit_message(embed=build_duel_embed(res), view=next_view)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("決鬥行動失敗", str(exc)), ephemeral=True)
