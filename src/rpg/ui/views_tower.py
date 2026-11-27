"""100-Floor Tower Hub, Post-Combat Continue-Exploring State Machine, Chest, Secret Realm, Roguelike & Solo Combat Views."""

from __future__ import annotations

import asyncio
from typing import Any

import discord

from src.rpg.engine import GameError, RPGEngine
from src.rpg.systems.combat import _find_best_potion
from src.rpg.ui.embeds_core import (
    build_bag_embed,
    build_error_embed,
    build_monument_embed,
)
from src.rpg.ui.embeds_tower import (
    build_argo_intel_embed,
    build_combat_embed,
    build_roguelike_embed,
    build_secret_realm_embed,
    build_tower_embed,
)
from src.rpg.ui.views_core import OwnerView


async def _send_view_error(interaction: discord.Interaction, title: str, exc: Exception) -> None:
    embed = build_error_embed(title, str(exc))
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


def _safe_floor_info(engine: RPGEngine, user_id: str, floor: int | None = None) -> dict[str, Any] | None:
    try:
        prof = engine.get_profile(user_id)
        target_f = int(floor if floor is not None else prof.get("current_floor", 1))
        target_f = max(1, min(100, target_f))
        return engine.get_floor_info(target_f, user_id=user_id)
    except GameError:
        return None


def _build_post_combat_view_for_player(
    engine: RPGEngine,
    user_id: str,
    *,
    combat_mode: str = "field",
    floor: int | None = None,
    outcome: str = "victory",
    unlocked_next_floor: int | None = None,
    dropped_equipment: bool = False,
) -> PostCombatView:
    """Inspect live player & floor state to assemble a context-aware PostCombatView."""
    prof = engine.get_profile(user_id)
    cur_floor = max(1, min(100, int(floor if floor is not None else prof.get("current_floor", 1))))
    finfo = _safe_floor_info(engine, user_id, cur_floor) or {}
    max_hp = max(1, int(prof.get("max_hp", 100)))
    cur_hp = int(prof.get("hp", max_hp))
    hp_ratio = max(0.0, min(1.0, cur_hp / max_hp))
    has_miasma = int(prof.get("miasma_stacks", 0)) > 0
    is_hc_dead = bool(prof.get("is_dead", False))
    run = engine.active_roguelikes.get(user_id)
    has_active_rl = bool(run is not None and not run.finished)
    boss_gate = bool(finfo.get("boss_gate_unlocked", False))

    return PostCombatView(
        engine,
        user_id,
        combat_mode=combat_mode,
        floor=cur_floor,
        outcome=outcome,
        boss_gate_unlocked=boss_gate,
        unlocked_next_floor=unlocked_next_floor,
        is_hardcore_dead=is_hc_dead,
        has_active_roguelike=has_active_rl,
        hp_ratio=hp_ratio,
        has_miasma=has_miasma,
        dropped_equipment=dropped_equipment,
    )


async def _dispatch_explore_edit(
    interaction: discord.Interaction,
    engine: RPGEngine,
    user_id: str,
    *,
    old_view: discord.ui.View | None = None,
) -> None:
    """Shared exploration dispatcher transitioning seamlessly into Combat, Chest, or Post-Event continuation."""
    res = engine.explore_floor(user_id, steps=1)
    if old_view is not None:
        old_view.stop()
    if res.get("in_combat"):
        await interaction.response.edit_message(
            embed=build_combat_embed(res),
            view=SoloCombatView(engine, user_id),
        )
    elif res.get("chest"):
        await interaction.response.edit_message(
            embed=build_combat_embed(res),
            view=ChestView(engine, user_id),
        )
    else:
        fl = int(res.get("floor", 1))
        finfo = _safe_floor_info(engine, user_id, fl)
        post_view = _build_post_combat_view_for_player(
            engine,
            user_id,
            combat_mode="field",
            floor=fl,
            outcome="event",
            dropped_equipment=bool(res.get("equipment_drops")),
        )
        await interaction.response.edit_message(
            embed=build_combat_embed(res, floor_info=finfo),
            view=post_view,
        )


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
        async with self.parent_view._ui_lock:
            if self.parent_view._transitioned:
                return
            try:
                self.parent_view.selected_tier = int(self.values[0])
                self.parent_view.rebuild_floor_selector()
                first_floor = (self.parent_view.selected_tier - 1) * 10 + 1
                info = self.parent_view.engine.get_floor_info(first_floor, user_id=self.parent_view.user_id)
                await interaction.response.edit_message(embed=build_tower_embed(info), view=self.parent_view)
            except GameError as exc:
                await _send_view_error(interaction, "切換樓層區間失敗", exc)


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
        async with self.parent_view._ui_lock:
            if self.parent_view._transitioned:
                return
            target = int(self.values[0])
            try:
                self.parent_view.engine.teleport_floor(self.parent_view.user_id, target)
                info = self.parent_view.engine.get_floor_info(target, user_id=self.parent_view.user_id)
                await interaction.response.edit_message(embed=build_tower_embed(info), view=self.parent_view)
            except GameError as exc:
                await _send_view_error(interaction, "轉移門受阻", exc)


class TowerFloorView(OwnerView):
    """Interactive 100-Floor Aincrad Hub View (2-step floor warp, explore, boss, secret realm, roguelike)."""

    def __init__(self, engine: RPGEngine, user_id: str, current_floor: int = 1) -> None:
        super().__init__(user_id, timeout=600.0)
        self.engine = engine
        self.user_id = str(user_id)
        self._ui_lock = asyncio.Lock()
        self._transitioned = False
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
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                await _dispatch_explore_edit(interaction, self.engine, self.user_id, old_view=self)
                self._transitioned = True
            except GameError as exc:
                await _send_view_error(interaction, "探索受阻", exc)

    @discord.ui.button(label="👑 挑戰頭目房", style=discord.ButtonStyle.danger, row=2)
    async def btn_boss(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.start_floor_boss(self.user_id)
                self._transitioned = True
                self.stop()
                await interaction.response.edit_message(
                    embed=build_combat_embed(res),
                    view=SoloCombatView(self.engine, self.user_id),
                )
            except GameError as exc:
                await _send_view_error(interaction, "無法進入頭目房", exc)

    @discord.ui.button(label="🏘️ 返回城鎮圈內", style=discord.ButtonStyle.success, row=2)
    async def btn_town(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.travel_zone(self.user_id, "town")
                finfo = _safe_floor_info(self.engine, self.user_id, int(res.get("floor", 1)))
                if finfo is not None:
                    finfo["flavor_desc"] = res["message"]
                    await interaction.response.edit_message(embed=build_tower_embed(finfo), view=self)
                else:
                    await interaction.response.send_message(res["message"], ephemeral=True)
            except GameError as exc:
                await _send_view_error(interaction, "移動受阻", exc)

    @discord.ui.button(label="🏛️ 黑鐵宮地下迷宮", style=discord.ButtonStyle.secondary, row=3)
    async def btn_roguelike(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.start_roguelike(self.user_id)
                self._transitioned = True
                self.stop()
                await interaction.response.edit_message(
                    embed=build_roguelike_embed(res),
                    view=RoguelikeView(self.engine, self.user_id, nodes=res.get("nodes")),
                )
            except GameError as exc:
                await _send_view_error(interaction, "無法進入地下迷宮", exc)

    @discord.ui.button(label="🌫️ 秘境（瘴氣）", style=discord.ButtonStyle.secondary, row=3)
    async def btn_secret_realm(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                prof = self.engine.get_profile(self.user_id)
                if prof["zone"] != "secret_realm":
                    self.engine.enter_secret_realm(self.user_id, action="enter")
                res = self.engine.enter_secret_realm(self.user_id, action="explore")
                self._transitioned = True
                self.stop()
                await interaction.response.edit_message(
                    embed=build_secret_realm_embed(res),
                    view=SecretRealmView(self.engine, self.user_id),
                )
            except GameError as exc:
                await _send_view_error(interaction, "秘境探索失敗", exc)

    @discord.ui.button(label="🐭 阿爾狗情報", style=discord.ButtonStyle.secondary, row=3)
    async def btn_argo(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                prof = self.engine.get_profile(self.user_id)
                intel = self.engine.get_argo_intel(user_id=self.user_id, floor=int(prof["current_floor"]))
                await interaction.response.send_message(embed=build_argo_intel_embed(intel), ephemeral=True)
            except GameError as exc:
                await _send_view_error(interaction, "情報查詢失敗", exc)


class _CallbackButton(discord.ui.Button[Any]):
    """Typed dynamic Button avoiding mypy method-assign errors."""

    def __init__(
        self,
        *,
        label: str,
        style: discord.ButtonStyle,
        custom_id: str,
        row: int,
        on_click: Any,
    ) -> None:
        super().__init__(label=label, style=style, custom_id=custom_id, row=row)
        self._on_click = on_click

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._on_click(interaction)


class PostCombatView(OwnerView):
    """Context-aware post-combat / post-chest / post-event continuation toolbar with 1-click Continue Exploring."""

    def __init__(
        self,
        engine: RPGEngine,
        user_id: str,
        *,
        combat_mode: str = "field",
        floor: int = 1,
        outcome: str = "victory",
        boss_gate_unlocked: bool = False,
        unlocked_next_floor: int | None = None,
        is_hardcore_dead: bool = False,
        has_active_roguelike: bool = False,
        hp_ratio: float = 1.0,
        has_miasma: bool = False,
        dropped_equipment: bool = False,
        timeout: float = 600.0,
    ) -> None:
        super().__init__(user_id, timeout=timeout)
        self.engine = engine
        self.user_id = str(user_id)
        self.combat_mode = str(combat_mode)
        self.floor = max(1, int(floor))
        self.outcome = str(outcome)
        self.boss_gate_unlocked = bool(boss_gate_unlocked)
        self.unlocked_next_floor = unlocked_next_floor
        self.is_hardcore_dead = bool(is_hardcore_dead)
        self.has_active_roguelike = bool(has_active_roguelike)
        self.hp_ratio = float(hp_ratio)
        self.has_miasma = bool(has_miasma)
        self.dropped_equipment = bool(dropped_equipment)
        self._ui_lock = asyncio.Lock()
        self._transitioned = False

        self._build_buttons()

    def _add_btn(
        self,
        label: str,
        style: discord.ButtonStyle,
        custom_id: str,
        row: int,
        callback: Any,
    ) -> None:
        self.add_item(
            _CallbackButton(
                label=label,
                style=style,
                custom_id=custom_id,
                row=row,
                on_click=callback,
            )
        )

    def _build_buttons(self) -> None:
        # Case 1: Hardcore Permadeath — strictly omit explore/combat buttons!
        if self.is_hardcore_dead:
            self._add_btn(
                "🪦 黑鐵宮生命之碑",
                discord.ButtonStyle.danger,
                "sao_post:monument",
                0,
                self._on_monument,
            )
            self._add_btn(
                "🎒 檢視背包",
                discord.ButtonStyle.secondary,
                "sao_post:bag",
                0,
                self._on_bag,
            )
            return

        # Case 2: Active Roguelike continuation
        if self.has_active_roguelike:
            self._add_btn(
                "🏛️ 繼續深入迷宮",
                discord.ButtonStyle.primary,
                "sao_post:rl_continue",
                0,
                self._on_rl_continue,
            )
            self._add_btn(
                "🏛️ 撤離結算積分",
                discord.ButtonStyle.success,
                "sao_post:rl_extract",
                0,
                self._on_rl_extract,
            )
            self._add_btn(
                "⚡ 一鍵裝備最強",
                discord.ButtonStyle.success if self.dropped_equipment else discord.ButtonStyle.secondary,
                "sao_post:auto_equip",
                1,
                self._on_auto_equip,
            )
            self._add_btn(
                "🎒 檢視背包",
                discord.ButtonStyle.secondary,
                "sao_post:bag",
                1,
                self._on_bag,
            )
            return

        # Case 3: Standard Defeat — prioritize Town Rest to prevent 1-HP suicide loop!
        if self.outcome == "defeat":
            self._add_btn(
                "🏘️ 回城鎮休整（回復滿血）",
                discord.ButtonStyle.primary,
                "sao_post:town",
                0,
                self._on_town,
            )
            self._add_btn(
                "🏰 爬塔總覽",
                discord.ButtonStyle.secondary,
                "sao_post:hub",
                0,
                self._on_hub,
            )
            self._add_btn(
                "🎒 檢視背包",
                discord.ButtonStyle.secondary,
                "sao_post:bag",
                0,
                self._on_bag,
            )
            return

        # Case 4: Standard Victory / Chest / Event / Retreat / Boss Clear
        row0_count = 0
        if self.unlocked_next_floor and self.floor < 100 and self.unlocked_next_floor > self.floor:
            self._add_btn(
                f"⬆️ 前往第 {self.unlocked_next_floor} 層",
                discord.ButtonStyle.success,
                "sao_post:next_floor",
                0,
                self._on_next_floor,
            )
            row0_count += 1
        elif self.combat_mode in ("boss", "nightmare_boss") and self.floor >= 100 and self.outcome == "victory":
            nf = max(101, self.floor + 1)
            self._add_btn(
                f"🌑 挑戰夢魘 F{nf}",
                discord.ButtonStyle.danger,
                f"sao_post:nightmare:{nf}",
                0,
                self._make_nightmare_cb(nf),
            )
            row0_count += 1

        # Primary Continue Exploring button — always right here after killing a mob/chest/boss!
        self._add_btn(
            "🧭 繼續探索",
            discord.ButtonStyle.primary,
            "sao_post:explore",
            0,
            self._on_explore,
        )
        row0_count += 1

        if self.boss_gate_unlocked and not self.unlocked_next_floor and row0_count < 5:
            self._add_btn(
                f"👑 挑戰第 {self.floor} 層頭目",
                discord.ButtonStyle.danger,
                "sao_post:boss",
                0,
                self._on_boss,
            )
            row0_count += 1

        town_style = (
            discord.ButtonStyle.success
            if (self.hp_ratio < 0.60 or self.has_miasma)
            else discord.ButtonStyle.secondary
        )
        if row0_count < 5:
            self._add_btn("🏘️ 回城休整", town_style, "sao_post:town", 0, self._on_town)
            row0_count += 1
        if row0_count < 5:
            self._add_btn("🏰 爬塔總覽", discord.ButtonStyle.secondary, "sao_post:hub", 0, self._on_hub)
            row0_count += 1

        # Row 1: Quick Equipment Lifecycle buttons (non-destructive, keep PostCombatView active!)
        self._add_btn(
            "⚡ 一鍵裝備最強",
            discord.ButtonStyle.success if self.dropped_equipment else discord.ButtonStyle.secondary,
            "sao_post:auto_equip",
            1,
            self._on_auto_equip,
        )
        self._add_btn(
            "🎒 檢視背包",
            discord.ButtonStyle.secondary,
            "sao_post:bag",
            1,
            self._on_bag,
        )
        if row0_count >= 5 and "sao_post:hub" not in {
            getattr(c, "custom_id", "") for c in self.children
        }:
            self._add_btn("🏰 爬塔總覽", discord.ButtonStyle.secondary, "sao_post:hub", 1, self._on_hub)

    async def _on_explore(self, interaction: discord.Interaction) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                await _dispatch_explore_edit(interaction, self.engine, self.user_id, old_view=self)
                self._transitioned = True
            except GameError as exc:
                await _send_view_error(interaction, "繼續探索受阻", exc)

    async def _on_boss(self, interaction: discord.Interaction) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.start_floor_boss(self.user_id, floor=self.floor)
                self._transitioned = True
                self.stop()
                await interaction.response.edit_message(
                    embed=build_combat_embed(res),
                    view=SoloCombatView(self.engine, self.user_id),
                )
            except GameError as exc:
                await _send_view_error(interaction, "無法挑戰頭目", exc)

    async def _on_next_floor(self, interaction: discord.Interaction) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                target = int(self.unlocked_next_floor or min(100, self.floor + 1))
                self.engine.teleport_floor(self.user_id, target)
                info = self.engine.get_floor_info(target, user_id=self.user_id)
                self._transitioned = True
                self.stop()
                await interaction.response.edit_message(
                    embed=build_tower_embed(info),
                    view=TowerFloorView(self.engine, self.user_id, target),
                )
            except GameError as exc:
                await _send_view_error(interaction, "無法前往下一層", exc)

    def _make_nightmare_cb(self, nf: int) -> Any:
        async def _cb(interaction: discord.Interaction) -> None:
            async with self._ui_lock:
                if self._transitioned:
                    return
                try:
                    res = self.engine.enter_nightmare_floor(self.user_id, nf)
                    self._transitioned = True
                    self.stop()
                    await interaction.response.edit_message(
                        embed=build_combat_embed(res),
                        view=SoloCombatView(self.engine, self.user_id),
                    )
                except GameError as exc:
                    await _send_view_error(interaction, "無法進入夢魘層", exc)

        return _cb

    async def _on_town(self, interaction: discord.Interaction) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.travel_zone(self.user_id, "town")
                fl = int(res.get("floor", self.floor))
                info = self.engine.get_floor_info(fl, user_id=self.user_id)
                info["flavor_desc"] = res["message"]
                self._transitioned = True
                self.stop()
                await interaction.response.edit_message(
                    embed=build_tower_embed(info),
                    view=TowerFloorView(self.engine, self.user_id, fl),
                )
            except GameError as exc:
                await _send_view_error(interaction, "回城休整失敗", exc)

    async def _on_hub(self, interaction: discord.Interaction) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                prof = self.engine.get_profile(self.user_id)
                fl = int(prof.get("current_floor", self.floor))
                info = self.engine.get_floor_info(fl, user_id=self.user_id)
                self._transitioned = True
                self.stop()
                await interaction.response.edit_message(
                    embed=build_tower_embed(info),
                    view=TowerFloorView(self.engine, self.user_id, fl),
                )
            except GameError as exc:
                await _send_view_error(interaction, "開啟爬塔總覽失敗", exc)

    async def _on_auto_equip(self, interaction: discord.Interaction) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.auto_equip_best(self.user_id)
                await interaction.response.send_message(res["message"], ephemeral=True)
            except GameError as exc:
                await _send_view_error(interaction, "一鍵裝備失敗", exc)

    async def _on_bag(self, interaction: discord.Interaction) -> None:
        async with self._ui_lock:
            try:
                from src.rpg.ui.views_core import BagEquipView

                prof = self.engine.get_profile(self.user_id)
                await interaction.response.send_message(
                    embed=build_bag_embed(prof, self.engine.content),
                    view=BagEquipView(self.engine, self.user_id),
                    ephemeral=True,
                )
            except GameError as exc:
                await _send_view_error(interaction, "檢視背包失敗", exc)

    async def _on_monument(self, interaction: discord.Interaction) -> None:
        async with self._ui_lock:
            try:
                data = self.engine.get_monument_of_life(limit=10)
                await interaction.response.edit_message(embed=build_monument_embed(data), view=None)
                self._transitioned = True
                self.stop()
            except GameError as exc:
                await _send_view_error(interaction, "查詢生命之碑失敗", exc)

    async def _on_rl_continue(self, interaction: discord.Interaction) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            run = self.engine.active_roguelikes.get(self.user_id)
            if run is None or run.finished:
                await _send_view_error(interaction, "迷宮已結束", GameError("目前沒有進行中的地下迷宮。"))
                return
            res = {
                "roguelike": run,
                "depth": run.depth,
                "score": run.score,
                "tokens": run.tokens,
                "col_earned": run.col_earned,
                "nodes": run.pending_nodes,
                "message": f"🏛️ 準備深入黑鐵宮地下迷宮第 {run.depth} 層，請選擇下一條路線！",
            }
            self._transitioned = True
            self.stop()
            await interaction.response.edit_message(
                embed=build_roguelike_embed(res),
                view=RoguelikeView(self.engine, self.user_id, nodes=run.pending_nodes),
            )

    async def _on_rl_extract(self, interaction: discord.Interaction) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.extract_roguelike(self.user_id)
                post_view = _build_post_combat_view_for_player(
                    self.engine,
                    self.user_id,
                    combat_mode="roguelike",
                    floor=int(res.get("floor", self.floor)),
                    outcome="victory",
                    dropped_equipment=bool(res.get("equipment_drops")),
                )
                self._transitioned = True
                self.stop()
                await interaction.response.edit_message(
                    embed=build_roguelike_embed(res),
                    view=post_view,
                )
            except GameError as exc:
                await _send_view_error(interaction, "撤離結算失敗", exc)


class SecretRealmView(OwnerView):
    """Interactive Secret Realm (Miasma) exploration & purification toolbar."""

    def __init__(self, engine: RPGEngine, user_id: str) -> None:
        super().__init__(user_id, timeout=600.0)
        self.engine = engine
        self.user_id = str(user_id)
        self._ui_lock = asyncio.Lock()
        self._transitioned = False

    @discord.ui.button(label="🌫️ 繼續探索秘境", style=discord.ButtonStyle.primary, custom_id="sao_sr:explore", row=0)
    async def btn_explore_sr(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                prof = self.engine.get_profile(self.user_id)
                if prof["zone"] != "secret_realm":
                    self.engine.enter_secret_realm(self.user_id, action="enter")
                res = self.engine.enter_secret_realm(self.user_id, action="explore")
                await interaction.response.edit_message(embed=build_secret_realm_embed(res), view=self)
            except GameError as exc:
                await _send_view_error(interaction, "秘境探索失敗", exc)

    @discord.ui.button(label="🏘️ 回城淨化瘴氣", style=discord.ButtonStyle.success, custom_id="sao_sr:town", row=0)
    async def btn_town(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.travel_zone(self.user_id, "town")
                fl = int(res.get("floor", 1))
                info = self.engine.get_floor_info(fl, user_id=self.user_id)
                info["flavor_desc"] = res["message"]
                self._transitioned = True
                self.stop()
                await interaction.response.edit_message(
                    embed=build_tower_embed(info),
                    view=TowerFloorView(self.engine, self.user_id, fl),
                )
            except GameError as exc:
                await _send_view_error(interaction, "淨化回城失敗", exc)

    @discord.ui.button(label="🏰 爬塔總覽", style=discord.ButtonStyle.secondary, custom_id="sao_sr:hub", row=0)
    async def btn_hub(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                prof = self.engine.get_profile(self.user_id)
                fl = int(prof.get("current_floor", 1))
                info = self.engine.get_floor_info(fl, user_id=self.user_id)
                self._transitioned = True
                self.stop()
                await interaction.response.edit_message(
                    embed=build_tower_embed(info),
                    view=TowerFloorView(self.engine, self.user_id, fl),
                )
            except GameError as exc:
                await _send_view_error(interaction, "開啟爬塔總覽失敗", exc)


class ChestView(OwnerView):
    """Interactive Chest inspection / opening / leaving View transitioning cleanly into PostCombatView or Combat."""

    def __init__(self, engine: RPGEngine, user_id: str) -> None:
        super().__init__(user_id, timeout=600.0)
        self.engine = engine
        self.user_id = str(user_id)
        self._ui_lock = asyncio.Lock()
        self._transitioned = False

    @discord.ui.button(label="👁️ 索敵鑑定", style=discord.ButtonStyle.primary, row=0)
    async def btn_inspect(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.open_chest(self.user_id, action="inspect")
                await interaction.response.send_message(res["message"], ephemeral=True)
            except GameError as exc:
                await _send_view_error(interaction, "鑑定失敗", exc)

    @discord.ui.button(label="🎁 開啟寶箱", style=discord.ButtonStyle.success, row=0)
    async def btn_open(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.open_chest(self.user_id, action="open")
                self._transitioned = True
                self.stop()
                if res.get("in_combat"):
                    await interaction.response.edit_message(
                        embed=build_combat_embed(res),
                        view=SoloCombatView(self.engine, self.user_id),
                    )
                else:
                    fl = int(res.get("floor", 1))
                    finfo = _safe_floor_info(self.engine, self.user_id, fl)
                    post_view = _build_post_combat_view_for_player(
                        self.engine,
                        self.user_id,
                        combat_mode="chest",
                        floor=fl,
                        outcome="chest",
                        dropped_equipment=bool(res.get("equipment_drops") or res.get("equipment_result")),
                    )
                    await interaction.response.edit_message(
                        embed=build_combat_embed(res, floor_info=finfo),
                        view=post_view,
                    )
            except GameError as exc:
                await _send_view_error(interaction, "開箱失敗", exc)

    @discord.ui.button(label="🚪 謹慎離開", style=discord.ButtonStyle.secondary, row=0)
    async def btn_leave(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.open_chest(self.user_id, action="leave")
                fl = int(res.get("floor", 1))
                finfo = _safe_floor_info(self.engine, self.user_id, fl)
                post_view = _build_post_combat_view_for_player(
                    self.engine,
                    self.user_id,
                    combat_mode="chest",
                    floor=fl,
                    outcome="chest",
                )
                self._transitioned = True
                self.stop()
                await interaction.response.edit_message(
                    embed=build_combat_embed(res, floor_info=finfo),
                    view=post_view,
                )
            except GameError as exc:
                await _send_view_error(interaction, "操作失敗", exc)


class SoloCombatView(OwnerView):
    """Turn-based SAO solo combat tactical action bar with Potion button, smart off-CD Skill & PostCombatView transition."""

    def __init__(self, engine: RPGEngine, user_id: str) -> None:
        super().__init__(user_id, timeout=600.0)
        self.engine = engine
        self.user_id = str(user_id)
        self._ui_lock = asyncio.Lock()
        self._transitioned = False

    def _pick_ready_skill(self) -> str:
        prof = self.engine.get_profile(self.user_id)
        slots = list(prof.get("skill_slots") or [])
        if not slots:
            return "slant"
        session = self.engine.active_combats.get(self.user_id)
        if session is not None:
            for sid in slots:
                spec = self.engine.content.sword_skills.get(sid)
                if (
                    isinstance(spec, dict)
                    and int(session.skill_cooldowns.get(sid, 0)) <= 0
                    and session.player_sp >= int(spec.get("sp_cost", 15))
                ):
                    return sid
        return slots[0]

    async def _act(
        self,
        interaction: discord.Interaction,
        action: str,
        *,
        skill_id: str | None = None,
        item_id: str | None = None,
    ) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.combat_action(self.user_id, action, skill_id=skill_id, item_id=item_id)
                if res.get("finished"):
                    fl = int(res.get("floor", getattr(res.get("combat"), "floor", 1)))
                    mode = str(res.get("mode", getattr(res.get("combat"), "mode", "field")))
                    outcome = (
                        "victory"
                        if res.get("victory")
                        else ("defeat" if res.get("defeat") else "retreat")
                    )
                    rewards = res.get("rewards") or {}
                    next_fl = rewards.get("unlocked_next_floor") if isinstance(rewards, dict) else None
                    dropped_eq = bool(
                        isinstance(rewards, dict)
                        and any(
                            isinstance(d, dict) and d.get("status") != "filtered"
                            for d in (rewards.get("equipment_drops") or [])
                        )
                    )
                    finfo = _safe_floor_info(self.engine, self.user_id, fl)
                    next_view: discord.ui.View = _build_post_combat_view_for_player(
                        self.engine,
                        self.user_id,
                        combat_mode=mode,
                        floor=fl,
                        outcome=outcome,
                        unlocked_next_floor=int(next_fl) if next_fl is not None else None,
                        dropped_equipment=dropped_eq,
                    )
                    self._transitioned = True
                    self.stop()
                    await interaction.response.edit_message(
                        embed=build_combat_embed(res, floor_info=finfo),
                        view=next_view,
                    )
                else:
                    await interaction.response.edit_message(embed=build_combat_embed(res), view=self)
            except GameError as exc:
                await _send_view_error(interaction, "戰鬥指令受阻", exc)

    @discord.ui.button(label="🗡️ 斬擊", style=discord.ButtonStyle.primary, row=0)
    async def btn_attack(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._act(interaction, "attack")

    @discord.ui.button(label="⚔️ 施放劍技", style=discord.ButtonStyle.danger, row=0)
    async def btn_skill(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            sid = self._pick_ready_skill()
        except GameError:
            sid = "slant"
        await self._act(interaction, "skill", skill_id=sid)

    @discord.ui.button(label="⚡ 彈反 Parry", style=discord.ButtonStyle.success, row=0)
    async def btn_parry(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._act(interaction, "parry")

    @discord.ui.button(label="🛡️ 防禦", style=discord.ButtonStyle.secondary, row=0)
    async def btn_defend(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        await self._act(interaction, "defend")

    @discord.ui.button(label="🧪 回復藥水", style=discord.ButtonStyle.success, row=1)
    async def btn_potion(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        pid = _find_best_potion(self.engine.db, self.engine.content, self.user_id)
        if not pid:
            await _send_view_error(
                interaction,
                "藥水耗盡",
                GameError("背包中目前沒有任何回復藥水，可回城於 /shop 補貨！", code="INSUFFICIENT_ITEM"),
            )
            return
        await self._act(interaction, "item", item_id=pid)

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
    """Black Iron Palace Underground Roguelike dynamic route & extraction View."""

    def __init__(
        self,
        engine: RPGEngine,
        user_id: str,
        *,
        nodes: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(user_id, timeout=600.0)
        self.engine = engine
        self.user_id = str(user_id)
        self._ui_lock = asyncio.Lock()
        self._transitioned = False
        if nodes is None:
            run = self.engine.active_roguelikes.get(self.user_id)
            nodes = list(run.pending_nodes) if run is not None else []
        self._rebuild_route_buttons(nodes)

    def _rebuild_route_buttons(self, nodes: list[dict[str, Any]]) -> None:
        self.clear_items()
        route_nodes = list(nodes)[:3] if nodes else [{"index": 0, "kind": "battle", "name": "路線 0"}]
        kind_icons = {"battle": "⚔️", "warden": "🛡️", "chest": "🎁", "merchant": "🛒", "shrine": "✨"}
        for i, node in enumerate(route_nodes):
            idx = int(node.get("index", i))
            kind = str(node.get("kind", "battle"))
            icon = kind_icons.get(kind, "🔀")
            nname = str(node.get("name", f"路線 {idx}"))[:20]
            style = (
                discord.ButtonStyle.danger
                if kind == "warden"
                else (discord.ButtonStyle.primary if i == 0 else discord.ButtonStyle.secondary)
            )
            self.add_item(
                _CallbackButton(
                    label=f"{icon} {nname}",
                    style=style,
                    custom_id=f"sao_rl:node:{idx}",
                    row=0,
                    on_click=self._make_step_cb(idx),
                )
            )

        self.add_item(
            _CallbackButton(
                label="🏛️ 撤離結算積分",
                style=discord.ButtonStyle.success,
                custom_id="sao_rl:extract",
                row=1,
                on_click=self._on_extract,
            )
        )

    def _make_step_cb(self, idx: int) -> Any:
        async def _cb(interaction: discord.Interaction) -> None:
            await self._step(interaction, idx)

        return _cb

    async def _on_extract(self, interaction: discord.Interaction) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.extract_roguelike(self.user_id)
                post_view = _build_post_combat_view_for_player(
                    self.engine,
                    self.user_id,
                    combat_mode="roguelike",
                    floor=int(res.get("floor", 1)),
                    outcome="victory",
                    dropped_equipment=bool(res.get("equipment_drops")),
                )
                self._transitioned = True
                self.stop()
                await interaction.response.edit_message(embed=build_roguelike_embed(res), view=post_view)
            except GameError as exc:
                await _send_view_error(interaction, "撤離失敗", exc)

    async def _step(self, interaction: discord.Interaction, idx: int) -> None:
        async with self._ui_lock:
            if self._transitioned:
                return
            try:
                res = self.engine.step_roguelike(self.user_id, node_index=idx)
                if res.get("in_combat"):
                    self._transitioned = True
                    self.stop()
                    await interaction.response.edit_message(
                        embed=build_combat_embed(res),
                        view=SoloCombatView(self.engine, self.user_id),
                    )
                else:
                    self._rebuild_route_buttons(list(res.get("nodes") or []))
                    await interaction.response.edit_message(embed=build_roguelike_embed(res), view=self)
            except GameError as exc:
                await _send_view_error(interaction, "推進失敗", exc)
