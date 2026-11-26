"""100-Floor Tower 2-Step Tier->Floor Selector, Exploration, Chest & Solo Combat Discord UI Views."""

from __future__ import annotations

from typing import Any

import discord

from src.rpg.engine import GameError, RPGEngine
from src.rpg.ui.embeds_core import build_error_embed
from src.rpg.ui.embeds_tower import (
    build_argo_intel_embed,
    build_combat_embed,
    build_roguelike_embed,
    build_tower_embed,
)
from src.rpg.ui.views_core import OwnerView


class TierSelect(discord.ui.Select[Any]):
    """Step 1 of 2-step 100-floor selector (10 Biome Tiers <= 25 Discord option limit)."""

    def __init__(self, parent_view: TowerFloorView) -> None:
        options = [
            discord.SelectOption(
                label=f"第 {(t - 1) * 10 + 1}～{t * 10} 層（Tier {t}）",
                value=str(t),
                default=(t == parent_view.selected_tier),
            )
            for t in range(1, 11)
        ]
        super().__init__(placeholder="選擇艾恩葛朗特樓層區間（10 大主題生態）", options=options, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        self.parent_view.selected_tier = int(self.values[0])
        self.parent_view.rebuild_floor_selector()
        first_floor = (self.parent_view.selected_tier - 1) * 10 + 1
        info = self.parent_view.engine.get_floor_info(first_floor, user_id=self.parent_view.user_id)
        await interaction.response.edit_message(embed=build_tower_embed(info), view=self.parent_view)


class FloorSelect(discord.ui.Select[Any]):
    """Step 2 of 2-step 100-floor selector (10 floors per tier <= 25 Discord option limit)."""

    def __init__(self, parent_view: TowerFloorView, tier: int) -> None:
        start_f = (tier - 1) * 10 + 1
        options = [
            discord.SelectOption(label=f"第 {fl} 層（轉移門傳送）", value=str(fl))
            for fl in range(start_f, start_f + 10)
        ]
        super().__init__(placeholder=f"選擇第 {start_f}～{start_f + 9} 層傳送目標", options=options, row=1)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        target = int(self.values[0])
        try:
            self.parent_view.engine.teleport_floor(self.parent_view.user_id, target)
            info = self.parent_view.engine.get_floor_info(target, user_id=self.parent_view.user_id)
            await interaction.response.edit_message(embed=build_tower_embed(info), view=self.parent_view)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("轉移門受阻", str(exc)), ephemeral=True)


class TowerFloorView(OwnerView):
    """Interactive 100-Floor Aincrad Hub View (2-step floor warp, explore, boss, secret realm, roguelike)."""

    def __init__(self, engine: RPGEngine, user_id: str, current_floor: int = 1) -> None:
        super().__init__(user_id)
        self.engine = engine
        self.user_id = str(user_id)
        self.selected_tier = max(1, min(10, (current_floor - 1) // 10 + 1))
        self._tier_select = TierSelect(self)
        self._floor_select = FloorSelect(self, self.selected_tier)
        self.add_item(self._tier_select)
        self.add_item(self._floor_select)

    def rebuild_floor_selector(self) -> None:
        self.remove_item(self._floor_select)
        self._floor_select = FloorSelect(self, self.selected_tier)
        self.add_item(self._floor_select)

    @discord.ui.button(label="🧭 探索樓層", style=discord.ButtonStyle.primary, row=2)
    async def btn_explore(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.explore_floor(self.user_id, steps=1)
            if res.get("in_combat"):
                await interaction.response.edit_message(
                    embed=build_combat_embed(res),
                    view=SoloCombatView(self.engine, self.user_id),
                )
            elif res.get("chest"):
                await interaction.response.edit_message(
                    embed=build_combat_embed(res),
                    view=ChestView(self.engine, self.user_id),
                )
            else:
                prof = self.engine.get_profile(self.user_id)
                info = self.engine.get_floor_info(int(prof["current_floor"]), user_id=self.user_id)
                info["flavor_desc"] = res["message"]
                await interaction.response.edit_message(embed=build_tower_embed(info), view=self)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("探索受阻", str(exc)), ephemeral=True)

    @discord.ui.button(label="👑 挑戰頭目房", style=discord.ButtonStyle.danger, row=2)
    async def btn_boss(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.start_floor_boss(self.user_id)
            await interaction.response.edit_message(
                embed=build_combat_embed(res),
                view=SoloCombatView(self.engine, self.user_id),
            )
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("無法進入頭目房", str(exc)), ephemeral=True)

    @discord.ui.button(label="🏘️ 返回城鎮圈內", style=discord.ButtonStyle.success, row=2)
    async def btn_town(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.travel_zone(self.user_id, "town")
            await interaction.response.send_message(res["message"], ephemeral=True)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("移動受阻", str(exc)), ephemeral=True)

    @discord.ui.button(label="🏛️ 黑鐵宮地下迷宮", style=discord.ButtonStyle.secondary, row=3)
    async def btn_roguelike(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.start_roguelike(self.user_id)
            await interaction.response.edit_message(
                embed=build_roguelike_embed(res),
                view=RoguelikeView(self.engine, self.user_id),
            )
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("無法進入地下迷宮", str(exc)), ephemeral=True)

    @discord.ui.button(label="🐭 阿爾狗情報", style=discord.ButtonStyle.secondary, row=3)
    async def btn_argo(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            prof = self.engine.get_profile(self.user_id)
            intel = self.engine.get_argo_intel(user_id=self.user_id, floor=int(prof["current_floor"]))
            await interaction.response.send_message(embed=build_argo_intel_embed(intel), ephemeral=True)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("情報查詢失敗", str(exc)), ephemeral=True)


class ChestView(OwnerView):
    """Interactive Chest inspection / opening / leaving View."""

    def __init__(self, engine: RPGEngine, user_id: str) -> None:
        super().__init__(user_id)
        self.engine = engine
        self.user_id = str(user_id)

    @discord.ui.button(label="👁️ 索敵鑑定", style=discord.ButtonStyle.primary, row=0)
    async def btn_inspect(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.open_chest(self.user_id, action="inspect")
            await interaction.response.send_message(res["message"], ephemeral=True)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("鑑定失敗", str(exc)), ephemeral=True)

    @discord.ui.button(label="🎁 開啟寶箱", style=discord.ButtonStyle.success, row=0)
    async def btn_open(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.open_chest(self.user_id, action="open")
            if res.get("in_combat"):
                await interaction.response.edit_message(
                    embed=build_combat_embed(res),
                    view=SoloCombatView(self.engine, self.user_id),
                )
            else:
                await interaction.response.edit_message(embed=build_combat_embed(res), view=None)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("開箱失敗", str(exc)), ephemeral=True)

    @discord.ui.button(label="🚪 謹慎離開", style=discord.ButtonStyle.secondary, row=0)
    async def btn_leave(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.open_chest(self.user_id, action="leave")
            await interaction.response.edit_message(embed=build_combat_embed(res), view=None)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("操作失敗", str(exc)), ephemeral=True)


class SoloCombatView(OwnerView):
    """Turn-based SAO solo combat tactical action bar."""

    def __init__(self, engine: RPGEngine, user_id: str) -> None:
        super().__init__(user_id)
        self.engine = engine
        self.user_id = str(user_id)

    async def _act(
        self,
        interaction: discord.Interaction,
        action: str,
        *,
        skill_id: str | None = None,
        item_id: str | None = None,
    ) -> None:
        try:
            res = self.engine.combat_action(self.user_id, action, skill_id=skill_id, item_id=item_id)
            next_view = None if res.get("finished") else self
            await interaction.response.edit_message(embed=build_combat_embed(res), view=next_view)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("戰鬥指令受阻", str(exc)), ephemeral=True)

    @discord.ui.button(label="🗡️ 斬擊", style=discord.ButtonStyle.primary, row=0)
    async def btn_attack(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._act(interaction, "attack")

    @discord.ui.button(label="⚔️ 施放劍技", style=discord.ButtonStyle.danger, row=0)
    async def btn_skill(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        prof = self.engine.get_profile(self.user_id)
        slots = list(prof.get("skill_slots") or [])
        sid = slots[0] if slots else "slant"
        await self._act(interaction, "skill", skill_id=sid)

    @discord.ui.button(label="⚡ 彈反 Parry", style=discord.ButtonStyle.success, row=0)
    async def btn_parry(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._act(interaction, "parry")

    @discord.ui.button(label="🛡️ 防禦", style=discord.ButtonStyle.secondary, row=0)
    async def btn_defend(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._act(interaction, "defend")

    @discord.ui.button(label="❤️ 回復水晶", style=discord.ButtonStyle.success, row=1)
    async def btn_crystal(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._act(interaction, "crystal", item_id="healing_crystal")

    @discord.ui.button(label="🤖 自動生存戰", style=discord.ButtonStyle.primary, row=1)
    async def btn_auto(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._act(interaction, "auto")

    @discord.ui.button(label="🏃 撤退", style=discord.ButtonStyle.secondary, row=1)
    async def btn_retreat(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._act(interaction, "retreat")


class RoguelikeView(OwnerView):
    """Black Iron Palace Underground Roguelike route & extraction View."""

    def __init__(self, engine: RPGEngine, user_id: str) -> None:
        super().__init__(user_id)
        self.engine = engine
        self.user_id = str(user_id)

    @discord.ui.button(label="🔀 前進路線 0", style=discord.ButtonStyle.primary, row=0)
    async def btn_node0(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._step(interaction, 0)

    @discord.ui.button(label="🔀 前進路線 1", style=discord.ButtonStyle.secondary, row=0)
    async def btn_node1(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._step(interaction, 1)

    @discord.ui.button(label="🏛️ 撤離結算積分", style=discord.ButtonStyle.success, row=0)
    async def btn_extract(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.extract_roguelike(self.user_id)
            await interaction.response.edit_message(embed=build_roguelike_embed(res), view=None)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("撤離失敗", str(exc)), ephemeral=True)

    async def _step(self, interaction: discord.Interaction, idx: int) -> None:
        try:
            res = self.engine.step_roguelike(self.user_id, node_index=idx)
            if res.get("in_combat"):
                await interaction.response.edit_message(
                    embed=build_combat_embed(res),
                    view=SoloCombatView(self.engine, self.user_id),
                )
            else:
                await interaction.response.edit_message(embed=build_roguelike_embed(res), view=self)
        except GameError as exc:
            await interaction.response.send_message(embed=build_error_embed("推進失敗", str(exc)), ephemeral=True)
