"""Core SAO Discord UI Views (OwnerView, ProfileView, BagEquipView)."""

from __future__ import annotations

import asyncio
from typing import Any

import discord

from src.rpg.engine import GameError, RPGEngine
from src.rpg.ui.embeds_core import (
    _clamp_str,
    build_bag_embed,
    build_error_embed,
    build_monument_embed,
    build_profile_embed,
    build_skills_embed,
    build_yui_embed,
)
from src.rpg.ui.embeds_social import build_workshop_embed


async def _send_core_error(interaction: discord.Interaction, title: str, exc: Exception) -> None:
    embed = build_error_embed(title, str(exc))
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


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
        super().__init__(user_id, timeout=600.0)
        self.engine = engine
        self.user_id = str(user_id)

    @discord.ui.button(label="🪪 角色面板", style=discord.ButtonStyle.primary, row=0)
    async def btn_profile(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            prof = self.engine.get_profile(self.user_id)
            await interaction.response.edit_message(embed=build_profile_embed(prof), view=self)
        except GameError as exc:
            await _send_core_error(interaction, "查詢失敗", exc)

    @discord.ui.button(label="⚔️ 劍技天賦", style=discord.ButtonStyle.secondary, row=0)
    async def btn_skills(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            prof = self.engine.get_profile(self.user_id)
            await interaction.response.edit_message(embed=build_skills_embed(prof, self.engine.content), view=self)
        except GameError as exc:
            await _send_core_error(interaction, "查詢失敗", exc)

    @discord.ui.button(label="🎒 裝備背包", style=discord.ButtonStyle.secondary, row=0)
    async def btn_bag(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            prof = self.engine.get_profile(self.user_id)
            bag_view = BagEquipView(self.engine, self.user_id)
            self.stop()
            await interaction.response.edit_message(
                embed=build_bag_embed(prof, self.engine.content),
                view=bag_view,
            )
        except GameError as exc:
            await _send_core_error(interaction, "查詢失敗", exc)

    @discord.ui.button(label="🪦 生命之碑", style=discord.ButtonStyle.secondary, row=1)
    async def btn_monument(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            data = self.engine.get_monument_of_life(limit=8)
            await interaction.response.edit_message(embed=build_monument_embed(data), view=self)
        except GameError as exc:
            await _send_core_error(interaction, "查詢失敗", exc)

    @discord.ui.button(label="👧 結衣終端機", style=discord.ButtonStyle.success, row=1)
    async def btn_yui(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            data = self.engine.get_yui_logs(self.user_id)
            await interaction.response.edit_message(embed=build_yui_embed(data), view=self)
        except GameError as exc:
            await _send_core_error(interaction, "查詢失敗", exc)

    @discord.ui.button(label="📬 領取待領信箱", style=discord.ButtonStyle.primary, row=1)
    async def btn_claim_mail(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.claim_pending_loot(self.user_id)
            await interaction.response.send_message(res["message"], ephemeral=True)
        except GameError as exc:
            await _send_core_error(interaction, "領取失敗", exc)


class _BagGearSelect(discord.ui.Select[Any]):
    """Equipment selector for BagEquipView displaying CP delta vs currently equipped gear in same slot."""

    def __init__(self, parent_view: BagEquipView) -> None:
        options, disabled = parent_view._build_gear_options()
        super().__init__(
            placeholder="選擇欲穿戴、鎖定或分解的裝備（顯示同欄位戰力差）",
            options=options,
            disabled=disabled,
            row=0,
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        async with self.parent_view._ui_lock:
            raw = str(self.values[0])
            if raw == "none":
                await interaction.response.defer()
                return
            try:
                self.parent_view.selected_item_uid = int(raw)
                prof = self.parent_view.engine.get_profile(self.parent_view.user_id)
                self.parent_view.refresh_options(prof)
                embed = build_bag_embed(prof, self.parent_view.engine.content)
                await interaction.response.edit_message(embed=embed, view=self.parent_view)
            except (ValueError, GameError) as exc:
                await _send_core_error(interaction, "選擇裝備失敗", exc)


class BagEquipView(OwnerView):
    """Interactive Bag & Equipment Management Panel (Equip, Auto-Best, Lock, Dismantle, Workshop)."""

    def __init__(self, engine: RPGEngine, user_id: str) -> None:
        super().__init__(user_id, timeout=600.0)
        self.engine = engine
        self.user_id = str(user_id)
        self._ui_lock = asyncio.Lock()
        self.selected_item_uid: int | None = None
        self._gear_select = _BagGearSelect(self)
        self.add_item(self._gear_select)

    def _load_equipment(self, profile: dict[str, Any] | None = None) -> list[Any]:
        try:
            prof = profile if profile is not None else self.engine.get_profile(self.user_id)
            return list(prof.get("equipment") or [])
        except GameError:
            return []

    def _build_gear_options(self, profile: dict[str, Any] | None = None) -> tuple[list[discord.SelectOption], bool]:
        eqs = self._load_equipment(profile)
        if not eqs:
            self.selected_item_uid = None
            return [discord.SelectOption(label="（目前背包尚無裝備）", value="none", default=True)], True

        equipped_by_slot: dict[str, Any] = {}
        for item in eqs:
            if getattr(item, "is_equipped", False):
                equipped_by_slot[str(item.slot)] = item

        # Order: unequipped highest CP first (most likely upgrade targets), then equipped
        ordered = sorted(
            eqs,
            key=lambda e: (bool(getattr(e, "is_equipped", False)), -int(getattr(e, "power_score", 0)), int(e.id)),
        )[:25]
        valid_ids = {int(e.id) for e in ordered}
        if self.selected_item_uid not in valid_ids:
            self.selected_item_uid = int(ordered[0].id)

        options: list[discord.SelectOption] = []
        for item in ordered:
            stars = f" ★{item.temper_level}" if getattr(item, "temper_level", 0) > 0 else ""
            eq_tag = "🛡️" if getattr(item, "is_equipped", False) else ""
            lock_tag = "🔒" if getattr(item, "is_locked", False) else ""
            sock_tag = "💠" if getattr(item, "socket_crystal_id", "") else ""
            cur_slot = equipped_by_slot.get(str(item.slot))
            if getattr(item, "is_equipped", False):
                diff_str = "穿戴中"
            elif cur_slot is not None:
                diff = int(item.power_score) - int(cur_slot.power_score)
                diff_str = f"CP {diff:+d}"
            else:
                diff_str = f"空欄 +{int(item.power_score)}"
            label = _clamp_str(
                f"{eq_tag}{lock_tag}{sock_tag}#{item.id} {item.name} +{item.enhance_level}{stars}",
                98,
            )
            desc = _clamp_str(f"T{item.tier} {item.slot}/{item.rarity}｜⚡{item.power_score}（{diff_str}）", 98)
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(item.id),
                    description=desc,
                    default=(int(item.id) == self.selected_item_uid),
                )
            )
        return options, False

    def refresh_options(self, profile: dict[str, Any] | None = None) -> None:
        options, disabled = self._build_gear_options(profile)
        self._gear_select.options = options
        self._gear_select.disabled = disabled

    def _require_selected(self) -> int:
        if self.selected_item_uid is None:
            raise GameError("請先於上方下拉選單選擇一件裝備！", code="NO_ITEM_SELECTED")
        return int(self.selected_item_uid)

    async def _render_bag_edit(
        self, interaction: discord.Interaction, notice: str | None = None
    ) -> None:
        prof = self.engine.get_profile(self.user_id)
        self.refresh_options(prof)
        embed = build_bag_embed(prof, self.engine.content)
        if notice:
            embed.description = _clamp_str(f"{notice}\n\n{embed.description or ''}", 4096)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🛡️ 穿戴選定", style=discord.ButtonStyle.primary, row=1)
    async def btn_equip(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                uid = self._require_selected()
                res = self.engine.equip_item(self.user_id, uid)
                await self._render_bag_edit(interaction, res["message"])
            except GameError as exc:
                await _send_core_error(interaction, "穿戴失敗", exc)

    @discord.ui.button(label="⚡ 一鍵裝備最強", style=discord.ButtonStyle.success, row=1)
    async def btn_auto_best(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.auto_equip_best(self.user_id)
                await self._render_bag_edit(interaction, res["message"])
            except GameError as exc:
                await _send_core_error(interaction, "一鍵換裝失敗", exc)

    @discord.ui.button(label="🔒 鎖定／解鎖", style=discord.ButtonStyle.secondary, row=1)
    async def btn_lock(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                uid = self._require_selected()
                res = self.engine.toggle_lock_item(self.user_id, uid)
                await self._render_bag_edit(interaction, res["message"])
            except GameError as exc:
                await _send_core_error(interaction, "鎖定操作失敗", exc)

    @discord.ui.button(label="♻️ 分解選定", style=discord.ButtonStyle.danger, row=1)
    async def btn_dismantle(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                uid = self._require_selected()
                res = self.engine.dismantle_equipment(self.user_id, uid)
                self.selected_item_uid = None
                await self._render_bag_edit(interaction, res["message"])
            except GameError as exc:
                await _send_core_error(interaction, "分解失敗", exc)

    @discord.ui.button(label="🧹 批量分解", style=discord.ButtonStyle.danger, row=1)
    async def btn_bulk_dismantle(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.bulk_dismantle_equipment(self.user_id, max_rarity="fine")
                await self._render_bag_edit(interaction, res["message"])
            except GameError as exc:
                await _send_core_error(interaction, "批量分解失敗", exc)

    @discord.ui.button(label="🔨 開啟莉茲貝特工坊", style=discord.ButtonStyle.primary, row=2)
    async def btn_workshop(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                from src.rpg.ui.views_social import WorkshopView

                prof = self.engine.get_profile(self.user_id)
                wview = WorkshopView(self.engine, self.user_id, selected_item_uid=self.selected_item_uid)
                sel = wview.get_selected_item(prof)
                embed = build_workshop_embed(
                    prof,
                    prof.get("equipment") or [],
                    prof.get("inventory") or {},
                    selected_item=sel,
                    protection_on=wview.protection_on,
                )
                self.stop()
                await interaction.response.edit_message(embed=embed, view=wview)
            except GameError as exc:
                await _send_core_error(interaction, "開啟工坊失敗", exc)

    @discord.ui.button(label="📬 領取待領信箱", style=discord.ButtonStyle.secondary, row=2)
    async def btn_claim_mail(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.claim_pending_loot(self.user_id)
                await self._render_bag_edit(interaction, res["message"])
            except GameError as exc:
                await _send_core_error(interaction, "領取信箱失敗", exc)

    @discord.ui.button(label="🪪 角色面板", style=discord.ButtonStyle.secondary, row=2)
    async def btn_profile(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                prof = self.engine.get_profile(self.user_id)
                pview = ProfileView(self.engine, self.user_id)
                self.stop()
                await interaction.response.edit_message(embed=build_profile_embed(prof), view=pview)
            except GameError as exc:
                await _send_core_error(interaction, "開啟角色面板失敗", exc)
