"""Workshop, Cooking, Shop, Market, Guild, Daily/Quest & Leaderboard Discord UI Views."""

from __future__ import annotations

import asyncio
from typing import Any

import discord

from src.rpg.engine import GameError, RPGEngine
from src.rpg.ui.embeds_core import (
    _clamp_str,
    build_bag_embed,
    build_error_embed,
    build_leaderboard_embed,
)
from src.rpg.ui.embeds_social import (
    build_quests_embed,
    build_shop_embed,
    build_workshop_embed,
)
from src.rpg.ui.views_core import BagEquipView, OwnerView

_SHOP_CATEGORIES: list[tuple[str, str, set[str]]] = [
    ("potions_crystals", "🧪 藥水與 SAO 水晶", {"potion", "crystal"}),
    ("enhance_stones", "✨ 強化結晶與魔石", {"enhance", "magic_stone"}),
    ("socket_crystals", "💠 裝備鑲嵌結晶", {"socket_crystal"}),
    ("crates_tickets", "🎁 裝備補給箱與秘寶券", {"supply_crate", "misc"}),
]


async def _send_social_error(interaction: discord.Interaction, title: str, exc: Exception) -> None:
    embed = build_error_embed(title, str(exc))
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


class _WorkshopGearSelect(discord.ui.Select[Any]):
    """Equipment selector for Lisbeth's WorkshopView."""

    def __init__(self, parent_view: WorkshopView) -> None:
        options, disabled = parent_view._build_gear_options()
        super().__init__(
            placeholder="選擇欲強化、鍛星、升階、升品、鑲嵌或洗詞綴的裝備",
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
                await self.parent_view._render_edit(interaction)
            except (ValueError, GameError) as exc:
                await _send_social_error(interaction, "選擇裝備失敗", exc)


class _WorkshopActionSelect(discord.ui.Select[Any]):
    """Unified selector for Blacksmithing Recipes, Fusion Recipes, Socket Crystals & Magic Stones."""

    def __init__(self, parent_view: WorkshopView) -> None:
        options = parent_view._build_action_options()
        super().__init__(
            placeholder="選擇鍛造配方／融合配方／鑲嵌結晶／魔石種類",
            options=options,
            row=2,
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        async with self.parent_view._ui_lock:
            self.parent_view.selected_action_target = str(self.values[0])
            try:
                await self.parent_view._render_edit(interaction)
            except GameError as exc:
                await _send_social_error(interaction, "選擇配方失敗", exc)


class WorkshopView(OwnerView):
    """Interactive Lisbeth's Workshop Dashboard (5-Axis Upgrading, Crafting, Fusion, Socketing & Salvage)."""

    def __init__(
        self,
        engine: RPGEngine,
        user_id: str,
        *,
        selected_item_uid: int | None = None,
    ) -> None:
        super().__init__(user_id, timeout=600.0)
        self.engine = engine
        self.user_id = str(user_id)
        self._ui_lock = asyncio.Lock()
        self.protection_on = False
        self.selected_item_uid: int | None = selected_item_uid
        self.selected_action_target: str = "craft:forge_t1_gear"

        self._gear_select = _WorkshopGearSelect(self)
        self._action_select = _WorkshopActionSelect(self)
        self.add_item(self._gear_select)
        self.add_item(self._action_select)

    def _safe_profile(self, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        if profile is not None:
            return profile
        try:
            return self.engine.get_profile(self.user_id)
        except GameError:
            return {"display_name": "攻略者", "current_floor": 1, "col": 0, "equipment": [], "inventory": {}}

    def get_selected_item(self, profile: dict[str, Any] | None = None) -> Any:
        prof = self._safe_profile(profile)
        eqs = list(prof.get("equipment") or [])
        if not eqs:
            return None
        for item in eqs:
            if self.selected_item_uid is not None and int(item.id) == int(self.selected_item_uid):
                return item
        self.selected_item_uid = int(eqs[0].id)
        return eqs[0]

    def _build_gear_options(self, profile: dict[str, Any] | None = None) -> tuple[list[discord.SelectOption], bool]:
        prof = self._safe_profile(profile)
        eqs = list(prof.get("equipment") or [])
        if not eqs:
            self.selected_item_uid = None
            return [discord.SelectOption(label="（目前無裝備，請先鍛造或探索取得）", value="none", default=True)], True

        ordered = sorted(
            eqs,
            key=lambda e: (not bool(getattr(e, "is_equipped", False)), -int(getattr(e, "power_score", 0)), int(e.id)),
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
            label = _clamp_str(
                f"{eq_tag}{lock_tag}{sock_tag}#{item.id} {item.name} +{item.enhance_level}{stars}",
                98,
            )
            desc = _clamp_str(
                f"T{item.tier} {item.slot}/{item.rarity}｜⚡{item.power_score}｜祝福 {item.enhance_pity}%",
                98,
            )
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(item.id),
                    description=desc,
                    default=(int(item.id) == self.selected_item_uid),
                )
            )
        return options, False

    def _build_action_options(self, profile: dict[str, Any] | None = None) -> list[discord.SelectOption]:
        prof = self._safe_profile(profile)
        inv = dict(prof.get("inventory") or {})
        floor = max(1, min(100, int(prof.get("current_floor", 1))))
        cur_tier = max(1, min(10, (floor - 1) // 10 + 1))

        bs_recipes = dict(self.engine.content.recipes.get("blacksmithing", {}))
        fu_recipes = dict(self.engine.content.recipes.get("fusion", {}))
        items_catalog = self.engine.content.items_crystals

        options: list[discord.SelectOption] = []
        seen_vals: set[str] = set()

        def _add_opt(val: str, label: str, desc: str) -> None:
            if val in seen_vals or len(options) >= 25:
                return
            seen_vals.add(val)
            options.append(
                discord.SelectOption(
                    label=_clamp_str(label, 98),
                    value=val,
                    description=_clamp_str(desc, 98),
                    default=(val == self.selected_action_target),
                )
            )

        # 1) Blacksmithing recipes (current tier + T1 + popular Named recipes, up to 8)
        bs_picks = [
            f"forge_t{cur_tier}_gear",
            "forge_t1_gear",
            "forge_anneal_blade",
            "forge_kobold_sentinel_helm",
            "forge_iron_oath_mace",
            "forge_shadow_fang_dagger",
            "forge_dark_repulser",
            "forge_lambent_light",
            "forge_wind_fleuret_rapier",
        ]
        bs_added = 0
        for rid in bs_picks:
            if bs_added >= 8:
                break
            spec = bs_recipes.get(rid)
            if not spec:
                continue
            _add_opt(
                f"craft:{rid}",
                f"🔨 鍛造：{spec.get('name', rid)}",
                f"T{spec.get('tier', 1)}｜{int(spec.get('col_cost', 0)):,} 柯爾",
            )
            bs_added += 1

        # 2) Fusion recipes (5 high-value)
        for rid in (
            "fuse_bright_crystal",
            "fuse_dark_crystal",
            "fuse_dark_crystal_pure",
            "fuse_expand_stone",
            "fuse_gear_crate_t2",
        ):
            spec = fu_recipes.get(rid)
            if not spec:
                continue
            _add_opt(
                f"fuse:{rid}",
                f"⚗️ 融合：{spec.get('name', rid)}",
                f"{int(spec.get('col_cost', 0)):,} 柯爾｜產出 {spec.get('output_item_id', '')}",
            )

        # 3) Socket crystals (up to 8)
        for iid, ispec in items_catalog.items():
            if ispec.get("category") != "socket_crystal":
                continue
            owned = int(inv.get(iid, 0))
            _add_opt(
                f"socket:{iid}",
                f"💠 鑲嵌：{ispec.get('name', iid)}（持有 {owned}）",
                str(ispec.get("description", "鑲嵌強化戰鬥結晶")),
            )

        # 4) Magic stones (4)
        for sid in ("reroll_stone", "swap_stone", "refine_stone", "expand_stone"):
            ispec = items_catalog.get(sid)
            if not ispec:
                continue
            owned = int(inv.get(sid, 0))
            _add_opt(
                f"stone:{sid}",
                f"💎 魔石：{ispec.get('name', sid)}（持有 {owned}）",
                str(ispec.get("description", "重鑄裝備詞綴")),
            )

        if not options:
            _add_opt("craft:forge_t1_gear", "🔨 鍛造：起始之鎮 T1 裝備", "基本鍛造配方")

        if self.selected_action_target not in seen_vals:
            self.selected_action_target = options[0].value
            options[0].default = True
        return options[:25]

    def refresh_options(self, profile: dict[str, Any] | None = None) -> None:
        gear_opts, disabled = self._build_gear_options(profile)
        self._gear_select.options = gear_opts
        self._gear_select.disabled = disabled
        self._action_select.options = self._build_action_options(profile)

    def _require_selected(self) -> int:
        if self.selected_item_uid is None:
            raise GameError("請先於上方下拉選單選擇一件裝備！", code="NO_ITEM_SELECTED")
        return int(self.selected_item_uid)

    async def _render_edit(
        self, interaction: discord.Interaction, notice: str | None = None
    ) -> None:
        prof = self.engine.get_profile(self.user_id)
        self.refresh_options(prof)
        sel = self.get_selected_item(prof)
        embed = build_workshop_embed(
            prof,
            prof.get("equipment") or [],
            prof.get("inventory") or {},
            selected_item=sel,
            notice=notice,
            protection_on=self.protection_on,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="✨ 強化 +1", style=discord.ButtonStyle.primary, row=1)
    async def btn_enhance(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                uid = self._require_selected()
                res = self.engine.enhance_equipment(
                    self.user_id, uid, use_protection=self.protection_on
                )
                await self._render_edit(interaction, res["message"])
            except GameError as exc:
                await _send_social_error(interaction, "裝備強化失敗", exc)

    @discord.ui.button(label="⚡ 批量 +5", style=discord.ButtonStyle.primary, row=1)
    async def btn_batch_enhance(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                uid = self._require_selected()
                sel = self.get_selected_item()
                cur_lv = int(getattr(sel, "enhance_level", 0)) if sel is not None else 0
                target_lv = min(15, cur_lv + 5) if cur_lv < 15 else 15
                res = self.engine.batch_enhance_equipment(
                    self.user_id, uid, target_level=target_lv, use_protection=self.protection_on
                )
                await self._render_edit(interaction, res["message"])
            except GameError as exc:
                await _send_social_error(interaction, "批量強化失敗", exc)

    @discord.ui.button(label="⭐ 鍛星淬鍊", style=discord.ButtonStyle.success, row=1)
    async def btn_temper(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                uid = self._require_selected()
                res = self.engine.temper_equipment(self.user_id, uid)
                await self._render_edit(interaction, res["message"])
            except GameError as exc:
                await _send_social_error(interaction, "鍛星淬鍊失敗", exc)

    @discord.ui.button(label="⬆️ 升階", style=discord.ButtonStyle.secondary, row=1)
    async def btn_evolve(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                uid = self._require_selected()
                res = self.engine.evolve_equipment_tier(self.user_id, uid)
                await self._render_edit(interaction, res["message"])
            except GameError as exc:
                await _send_social_error(interaction, "裝備升階失敗", exc)

    @discord.ui.button(label="🌟 升品", style=discord.ButtonStyle.secondary, row=1)
    async def btn_promote(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                uid = self._require_selected()
                res = self.engine.promote_equipment_rarity(self.user_id, uid)
                await self._render_edit(interaction, res["message"])
            except GameError as exc:
                await _send_social_error(interaction, "裝備升品失敗", exc)

    @discord.ui.button(label="🔨 鍛造／融合", style=discord.ButtonStyle.primary, row=3)
    async def btn_craft_or_fuse(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                target = str(self.selected_action_target or "craft:forge_t1_gear")
                if target.startswith("fuse:"):
                    res = self.engine.fuse_items(self.user_id, target.split(":", 1)[1])
                elif target.startswith("craft:"):
                    res = self.engine.forge_craft(self.user_id, target.split(":", 1)[1])
                    eq_res = res.get("equipment_result")
                    if isinstance(eq_res, dict) and eq_res.get("item_uid"):
                        self.selected_item_uid = int(eq_res["item_uid"])
                else:
                    res = self.engine.forge_craft(self.user_id, "forge_t1_gear")
                    eq_res = res.get("equipment_result")
                    if isinstance(eq_res, dict) and eq_res.get("item_uid"):
                        self.selected_item_uid = int(eq_res["item_uid"])
                await self._render_edit(interaction, res["message"])
            except GameError as exc:
                await _send_social_error(interaction, "鍛造／融合失敗", exc)

    @discord.ui.button(label="💠 鑲嵌結晶", style=discord.ButtonStyle.primary, row=3)
    async def btn_socket(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                uid = self._require_selected()
                target = str(self.selected_action_target or "")
                if target.startswith("socket:"):
                    cid = target.split(":", 1)[1]
                    res = self.engine.socket_equipment_crystal(self.user_id, uid, cid)
                else:
                    prof = self.engine.get_profile(self.user_id)
                    inv = dict(prof.get("inventory") or {})
                    owned_cid = next(
                        (
                            iid
                            for iid, qty in inv.items()
                            if int(qty) > 0
                            and self.engine.content.items_crystals.get(iid, {}).get("category") == "socket_crystal"
                        ),
                        None,
                    )
                    sel = self.get_selected_item(prof)
                    if owned_cid is not None:
                        res = self.engine.socket_equipment_crystal(self.user_id, uid, owned_cid)
                    elif sel is not None and str(getattr(sel, "socket_crystal_id", "") or ""):
                        res = self.engine.unsocket_equipment_crystal(self.user_id, uid)
                    else:
                        raise GameError(
                            "請先於下方選單選擇一種鑲嵌結晶，或於商店購買／刷菁英怪取得鑲嵌結晶！",
                            code="NO_SOCKET_CRYSTAL",
                        )
                await self._render_edit(interaction, res["message"])
            except GameError as exc:
                await _send_social_error(interaction, "結晶鑲嵌失敗", exc)

    @discord.ui.button(label="💎 魔石洗煉", style=discord.ButtonStyle.secondary, row=3)
    async def btn_magic_stone(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                uid = self._require_selected()
                target = str(self.selected_action_target or "")
                sid = target.split(":", 1)[1] if target.startswith("stone:") else "reroll_stone"
                res = self.engine.apply_magic_stone(self.user_id, uid, sid)
                await self._render_edit(interaction, res["message"])
            except GameError as exc:
                await _send_social_error(interaction, "魔石洗煉失敗", exc)

    @discord.ui.button(label="🧿 保護符：關", style=discord.ButtonStyle.secondary, row=3)
    async def btn_toggle_protection(self, interaction: discord.Interaction, btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            self.protection_on = not self.protection_on
            btn.label = "🧿 保護符：開" if self.protection_on else "🧿 保護符：關"
            btn.style = discord.ButtonStyle.success if self.protection_on else discord.ButtonStyle.secondary
            try:
                await self._render_edit(
                    interaction,
                    f"🧿 強化保護符已切換為 **{'開啟' if self.protection_on else '關閉'}**。",
                )
            except GameError as exc:
                await _send_social_error(interaction, "切換保護符失敗", exc)

    @discord.ui.button(label="♻️ 批量分解", style=discord.ButtonStyle.danger, row=3)
    async def btn_bulk_dismantle(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.bulk_dismantle_equipment(self.user_id, max_rarity="fine")
                await self._render_edit(interaction, res["message"])
            except GameError as exc:
                await _send_social_error(interaction, "批量分解失敗", exc)

    @discord.ui.button(label="🎒 切換裝備背包", style=discord.ButtonStyle.secondary, row=4)
    async def btn_to_bag(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                prof = self.engine.get_profile(self.user_id)
                bview = BagEquipView(self.engine, self.user_id)
                self.stop()
                await interaction.response.edit_message(
                    embed=build_bag_embed(prof, self.engine.content),
                    view=bview,
                )
            except GameError as exc:
                await _send_social_error(interaction, "切換背包失敗", exc)

    @discord.ui.button(label="🔄 重整工坊", style=discord.ButtonStyle.secondary, row=4)
    async def btn_refresh(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                await self._render_edit(interaction, "🔄 已重新同步莉茲貝特工坊裝備與素材庫存！")
            except GameError as exc:
                await _send_social_error(interaction, "重整工坊失敗", exc)


class _ShopCategorySelect(discord.ui.Select[Any]):
    """Category switcher for upgraded ShopView."""

    def __init__(self, parent_view: ShopView) -> None:
        options = [
            discord.SelectOption(
                label=label,
                value=key,
                default=(key == parent_view.selected_category),
            )
            for key, label, _cats in _SHOP_CATEGORIES
        ]
        super().__init__(placeholder="選擇艾恩葛朗特商會商品分類", options=options, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        async with self.parent_view._ui_lock:
            self.parent_view.selected_category = str(self.values[0])
            self.parent_view.refresh_item_select()
            try:
                await self.parent_view._render_shop(
                    interaction,
                    notice=f"🛒 已切換至【{self.parent_view.current_category_label()}】貨架！",
                )
            except GameError as exc:
                await _send_social_error(interaction, "切換商店分類失敗", exc)


class _ShopItemSelect(discord.ui.Select[Any]):
    """Item selector dynamically populated for the active shop category."""

    def __init__(self, parent_view: ShopView) -> None:
        options = parent_view._build_item_options()
        super().__init__(placeholder="選擇欲購買的商品項目", options=options, row=1)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction) -> None:
        async with self.parent_view._ui_lock:
            self.parent_view.selected_item_id = str(self.values[0])
            self.parent_view.refresh_item_select()
            try:
                spec = self.parent_view.engine.content.items_crystals.get(self.parent_view.selected_item_id, {})
                await self.parent_view._render_shop(
                    interaction,
                    notice=f"📌 已選定商品：**{spec.get('name', self.parent_view.selected_item_id)}**（{int(spec.get('buy_col') or 0):,} 柯爾）。",
                )
            except GameError as exc:
                await _send_social_error(interaction, "選定商品失敗", exc)


class ShopView(OwnerView):
    """Upgraded Multi-Category SAO Merchant, Floor Equipment & Relic Gacha View."""

    def __init__(self, engine: RPGEngine, user_id: str, *, category: str = "potions_crystals") -> None:
        super().__init__(user_id, timeout=600.0)
        self.engine = engine
        self.user_id = str(user_id)
        self._ui_lock = asyncio.Lock()
        valid_cats = {k for k, _, _ in _SHOP_CATEGORIES}
        self.selected_category = category if category in valid_cats else "potions_crystals"
        self.selected_item_id: str = "hp_potion_t1"

        self._cat_select = _ShopCategorySelect(self)
        self._item_select = _ShopItemSelect(self)
        self.add_item(self._cat_select)
        self.add_item(self._item_select)

    def current_category_label(self) -> str:
        for key, label, _cats in _SHOP_CATEGORIES:
            if key == self.selected_category:
                return label
        return "🧪 藥水與 SAO 水晶"

    def _category_items(self) -> list[tuple[str, dict[str, Any]]]:
        target_cats: set[str] = {"potion", "crystal"}
        for key, _label, cats in _SHOP_CATEGORIES:
            if key == self.selected_category:
                target_cats = cats
                break
        rows = [
            (iid, spec)
            for iid, spec in self.engine.content.items_crystals.items()
            if int(spec.get("buy_col") or 0) > 0 and str(spec.get("category", "")) in target_cats
        ]
        if not rows:
            rows = [
                (iid, spec)
                for iid, spec in self.engine.content.items_crystals.items()
                if int(spec.get("buy_col") or 0) > 0
            ]
        return rows[:25]

    def _build_item_options(self) -> list[discord.SelectOption]:
        rows = self._category_items()
        valid_ids = {iid for iid, _ in rows}
        if self.selected_item_id not in valid_ids and rows:
            self.selected_item_id = rows[0][0]
        options: list[discord.SelectOption] = []
        for iid, spec in rows:
            price = int(spec.get("buy_col") or 0)
            options.append(
                discord.SelectOption(
                    label=_clamp_str(f"{spec.get('name', iid)} — {price:,} 柯爾", 98),
                    value=iid,
                    description=_clamp_str(str(spec.get("description", iid)), 98),
                    default=(iid == self.selected_item_id),
                )
            )
        if not options:
            options.append(discord.SelectOption(label="回復藥水 (hp_potion_t1)", value="hp_potion_t1", default=True))
            self.selected_item_id = "hp_potion_t1"
        return options[:25]

    def refresh_item_select(self) -> None:
        for opt in self._cat_select.options:
            opt.default = opt.value == self.selected_category
        self._item_select.options = self._build_item_options()

    def build_catalog_lines(self) -> list[str]:
        return [
            f"• **{spec.get('name', iid)}** (`{iid}`) — `{int(spec.get('buy_col') or 0):,}` 柯爾"
            for iid, spec in self._category_items()[:10]
        ]

    async def _render_shop(
        self,
        interaction: discord.Interaction,
        res: dict[str, Any] | None = None,
        *,
        notice: str | None = None,
    ) -> None:
        prof = self.engine.get_profile(self.user_id)
        payload = dict(res or {})
        if notice and not payload.get("message"):
            payload["message"] = notice
        payload.setdefault("col_remaining", int(prof.get("col", 0)))
        payload.setdefault("tickets_remaining", int((prof.get("inventory") or {}).get("gacha_relic_ticket", 0)))
        embed = build_shop_embed(
            payload,
            category_label=self.current_category_label(),
            catalog_lines=self.build_catalog_lines(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🛒 購買 x1", style=discord.ButtonStyle.primary, row=2)
    async def btn_buy_1(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.buy_shop_item(self.user_id, self.selected_item_id, qty=1)
                await self._render_shop(interaction, res)
            except GameError as exc:
                await _send_social_error(interaction, "購買失敗", exc)

    @discord.ui.button(label="🛒 購買 x5", style=discord.ButtonStyle.primary, row=2)
    async def btn_buy_5(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.buy_shop_item(self.user_id, self.selected_item_id, qty=5)
                await self._render_shop(interaction, res)
            except GameError as exc:
                await _send_social_error(interaction, "批量購買失敗", exc)

    @discord.ui.button(label="📦 開啟補給箱", style=discord.ButtonStyle.success, row=2)
    async def btn_open_crate(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                prof = self.engine.get_profile(self.user_id)
                inv = dict(prof.get("inventory") or {})
                sel_spec = self.engine.content.items_crystals.get(self.selected_item_id, {})
                if sel_spec.get("category") == "supply_crate" and int(inv.get(self.selected_item_id, 0)) > 0:
                    crate_id = self.selected_item_id
                else:
                    crate_id = next(
                        (
                            iid
                            for iid in ("gear_supply_crate_t3", "gear_supply_crate_t2", "gear_supply_crate_t1")
                            if int(inv.get(iid, 0)) > 0
                        ),
                        "gear_supply_crate_t1",
                    )
                res = self.engine.open_supply_crate(self.user_id, crate_id)
                await self._render_shop(interaction, res)
            except GameError as exc:
                await _send_social_error(interaction, "開啟補給箱失敗", exc)

    @discord.ui.button(label="⚔️ 購買樓層武器", style=discord.ButtonStyle.secondary, row=2)
    async def btn_buy_weapon(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.buy_shop_equipment(self.user_id, slot="weapon")
                await self._render_shop(interaction, res)
            except GameError as exc:
                await _send_social_error(interaction, "購買樓層武器失敗", exc)

    @discord.ui.button(label="🛡️ 購買樓層防具", style=discord.ButtonStyle.secondary, row=2)
    async def btn_buy_armor(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.buy_shop_equipment(self.user_id, slot="armor")
                await self._render_shop(interaction, res)
            except GameError as exc:
                await _send_social_error(interaction, "購買樓層防具失敗", exc)

    @discord.ui.button(label="🎰 秘寶抽 x1", style=discord.ButtonStyle.primary, row=3)
    async def btn_gacha_1(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.gacha_pull(self.user_id, chest_type="standard", count=1)
                await self._render_shop(interaction, res)
            except GameError as exc:
                await _send_social_error(interaction, "秘寶抽取失敗", exc)

    @discord.ui.button(label="🎰 秘寶抽 x5", style=discord.ButtonStyle.primary, row=3)
    async def btn_gacha_5(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.gacha_pull(self.user_id, chest_type="standard", count=5)
                await self._render_shop(interaction, res)
            except GameError as exc:
                await _send_social_error(interaction, "秘寶五連抽失敗", exc)

    @discord.ui.button(label="🎟️ 秘寶券抽取", style=discord.ButtonStyle.success, row=3)
    async def btn_gacha_ticket(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        async with self._ui_lock:
            try:
                res = self.engine.gacha_pull(self.user_id, chest_type="standard", count=1, use_ticket=True)
                await self._render_shop(interaction, res)
            except GameError as exc:
                await _send_social_error(interaction, "秘寶券抽取失敗", exc)


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
        super().__init__(user_id, timeout=600.0)
        self.engine = engine
        self.user_id = str(user_id)

    @discord.ui.button(label="📅 立即每日簽到", style=discord.ButtonStyle.success, row=0)
    async def btn_daily(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.claim_daily(self.user_id)
            await interaction.response.send_message(res["message"], ephemeral=True)
        except GameError as exc:
            await _send_social_error(interaction, "簽到提示", exc)

    @discord.ui.button(label="📋 重整任務進度", style=discord.ButtonStyle.primary, row=0)
    async def btn_quests(self, interaction: discord.Interaction, _btn: discord.ui.Button[Any]) -> None:
        try:
            res = self.engine.get_quests(self.user_id)
            await interaction.response.edit_message(embed=build_quests_embed(res), view=self)
        except GameError as exc:
            await _send_social_error(interaction, "查詢失敗", exc)
