"""Interactive discord.ui.View components for the val-dc persistent RPG."""

from __future__ import annotations

from typing import Optional

import discord

from src.rpg.assets import (
    get_class_portrait_url,
    get_dungeon_boss_portrait_url,
    get_expedition_banner_url,
    get_item_icon_url,
    get_pickaxe_icon_url,
    get_shop_tab_icon_url,
    get_ui_asset_url,
)
from src.rpg.data import (
    ACHIEVEMENTS,
    CLASSES,
    DIFFICULTIES,
    DUNGEONS,
    EXPEDITIONS,
    GEAR_TIERS,
    ITEMS,
    MAX_ENHANCE_LEVEL,
    MINE_ZONES,
    RARITIES,
    SLOT_ORDER,
    SLOTS,
    SUPPLY_SHOP,
)
from src.rpg.embeds import (
    build_achievements_embed,
    build_bag_embed,
    build_class_embed,
    build_combat_embed,
    build_combat_embeds,
    build_daily_quests_embed,
    build_dungeon_list_embed,
    build_enhance_result_embed,
    build_equipment_card_embed,
    build_expedition_embed,
    build_forge_embed,
    build_leaderboard_embed,
    build_mine_result_embed,
    build_profile_embed,
    build_rebirth_embed,
    build_shop_embed,
    build_world_boss_embed,
)
from src.rpg.engine import RPGEngine, RPGError


async def _send_error(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(f"⚠️ {message}", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ {message}", ephemeral=True)


class OwnerView(discord.ui.View):
    """Base View restricting interaction to the command invoker."""

    def __init__(self, engine: RPGEngine, owner_id: int, timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.engine = engine
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "⚠️ 這是其他冒險者的操作面板，請自行輸入 `/rpg` 指令開啟你的面板！",
                ephemeral=True,
            )
            return False
        return True


# =============================================================================
# 1. Starter Class Selection
# =============================================================================
class ClassSelectView(OwnerView):
    def __init__(self, engine: RPGEngine, owner_id: int) -> None:
        super().__init__(engine, owner_id)
        for cid, cdef in CLASSES.items():
            btn = discord.ui.Button(
                label=f"選擇 {cdef['name']}",
                emoji=cdef["emoji"],
                style=discord.ButtonStyle.primary,
                custom_id=f"rpg_start_{cid}",
            )
            btn.callback = self._make_cb(cid)
            self.add_item(btn)

    def _make_cb(self, class_id: str):
        async def callback(interaction: discord.Interaction) -> None:
            try:
                player = self.engine.register_player(
                    str(interaction.user.id), interaction.user.display_name, class_id
                )
                stats = self.engine.compute_stats(player)
                equipped = self.engine.db.get_equipment(player.user_id, equipped_only=True)
                rank, total = self.engine.db.get_player_rank(player.user_id, "power")
                embed = build_profile_embed(
                    player,
                    stats,
                    equipped,
                    self.engine.next_stamina_in(player),
                    rank,
                    total,
                    avatar_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
                )
                view = ProfileHubView(self.engine, interaction.user.id)
                await interaction.response.edit_message(
                    content=(
                        f"🎉 歡迎 **{interaction.user.display_name}** 加入星界紀元！"
                        "已發放新手精良武器、5 瓶生命藥水、5 顆初級強化石與 1 瓶體力恢復劑！"
                    ),
                    embed=embed,
                    view=view,
                )
            except RPGError as exc:
                await _send_error(interaction, str(exc))

        return callback


# =============================================================================
# 2. Profile Quick Hub View
# =============================================================================
class ProfileHubView(OwnerView):
    def __init__(self, engine: RPGEngine, owner_id: int) -> None:
        super().__init__(engine, owner_id)

    @discord.ui.button(label="快速挖礦", emoji="⛏️", style=discord.ButtonStyle.success, row=0)
    async def btn_mine(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            res = self.engine.mine(str(interaction.user.id), interaction.user.display_name)
            embed = build_mine_result_embed(res)
            view = MineView(self.engine, interaction.user.id, res["zone"]["id"])
            await interaction.response.send_message(embed=embed, view=view)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    @discord.ui.button(label="副本大廳", emoji="🏰", style=discord.ButtonStyle.primary, row=0)
    async def btn_dungeon(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            player = self.engine.require_player(str(interaction.user.id), interaction.user.display_name)
            clears = self.engine.db.get_dungeon_clears(player.user_id)
            embed = build_dungeon_list_embed(player, clears)
            view = DungeonHallView(self.engine, interaction.user.id)
            await interaction.response.send_message(embed=embed, view=view)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    @discord.ui.button(label="無盡深淵", emoji="🗼", style=discord.ButtonStyle.danger, row=0)
    async def btn_abyss(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            session = self.engine.start_abyss_combat(
                str(interaction.user.id), display_name=interaction.user.display_name
            )
            player = self.engine.require_player(str(interaction.user.id))
            embed = build_combat_embed(session, player)
            view = CombatView(self.engine, interaction.user.id)
            await interaction.response.send_message(embed=embed, view=view)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    @discord.ui.button(label="世界王", emoji="🐉", style=discord.ButtonStyle.danger, row=0)
    async def btn_boss(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            player = self.engine.require_player(str(interaction.user.id), interaction.user.display_name)
            boss = self.engine.get_or_spawn_world_boss()
            ranks = self.engine.db.get_world_boss_rankings(boss.id, limit=5)
            embed = build_world_boss_embed(boss, ranks, player)
            view = WorldBossView(self.engine)
            await interaction.response.send_message(embed=embed, view=view)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    @discord.ui.button(label="鐵匠鋪", emoji="⚒️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_forge(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            player = self.engine.require_player(str(interaction.user.id), interaction.user.display_name)
            inv = self.engine.db.get_inventory(player.user_id)
            eq = self.engine.db.get_equipment(player.user_id, equipped_only=True)
            embed = build_forge_embed(player, inv, eq)
            view = ForgeView(self.engine, interaction.user.id)
            await interaction.response.send_message(embed=embed, view=view)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    @discord.ui.button(label="冒險商店", emoji="🛒", style=discord.ButtonStyle.secondary, row=1)
    async def btn_shop(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            player = self.engine.require_player(str(interaction.user.id), interaction.user.display_name)
            view = ShopView(self.engine, interaction.user.id)
            embed = view.render_embed(player)
            await interaction.response.send_message(embed=embed, view=view)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    @discord.ui.button(label="背包裝備", emoji="🎒", style=discord.ButtonStyle.secondary, row=1)
    async def btn_bag(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            player = self.engine.require_player(str(interaction.user.id), interaction.user.display_name)
            view = BagView(self.engine, interaction.user.id)
            embed = view.render_embed(player)
            await interaction.response.send_message(embed=embed, view=view)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    @discord.ui.button(label="每日簽到/任務", emoji="📅", style=discord.ButtonStyle.secondary, row=1)
    async def btn_daily(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            player = self.engine.require_player(str(interaction.user.id), interaction.user.display_name)
            qst = self.engine.get_quests_status(player.user_id)
            embed = build_daily_quests_embed(player, qst, self.engine.today_key())
            view = DailyQuestView(self.engine, interaction.user.id)
            await interaction.response.send_message(embed=embed, view=view)
        except RPGError as exc:
            await _send_error(interaction, str(exc))


# =============================================================================
# 3. Mining Interactive View
# =============================================================================
class MineView(OwnerView):
    def __init__(self, engine: RPGEngine, owner_id: int, current_zone_id: str) -> None:
        super().__init__(engine, owner_id)
        self.zone_id = current_zone_id
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        options = []
        for z in MINE_ZONES:
            options.append(
                discord.SelectOption(
                    label=f"{z['name']} (Lv.{z['min_level']} / T{z['min_pickaxe']}鎬)",
                    value=z["id"],
                    emoji=z["emoji"],
                    default=(z["id"] == self.zone_id),
                )
            )
        sel = discord.ui.Select(placeholder="選擇要前往的礦區...", options=options, row=0)
        sel.callback = self._on_select_zone
        self.add_item(sel)

        btn_again = discord.ui.Button(label="繼續挖礦 (-5 體力)", emoji="⛏️", style=discord.ButtonStyle.success, row=1)
        btn_again.callback = self._on_mine_again
        self.add_item(btn_again)

        btn_stam = discord.ui.Button(label="喝體力恢復劑 (+50)", emoji="⚡", style=discord.ButtonStyle.secondary, row=1)
        btn_stam.callback = self._on_drink_stamina
        self.add_item(btn_stam)

    async def _on_select_zone(self, interaction: discord.Interaction) -> None:
        self.zone_id = interaction.data["values"][0]
        await self._on_mine_again(interaction)

    async def _on_mine_again(self, interaction: discord.Interaction) -> None:
        try:
            res = self.engine.mine(
                str(interaction.user.id),
                display_name=interaction.user.display_name,
                zone_id=self.zone_id,
            )
            self._rebuild()
            embed = build_mine_result_embed(res)
            await interaction.response.edit_message(embed=embed, view=self)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    async def _on_drink_stamina(self, interaction: discord.Interaction) -> None:
        try:
            res = self.engine.use_consumable(str(interaction.user.id), "stamina_elixir")
            await interaction.response.send_message(
                f"⚡ 已飲用體力恢復劑，回復 **+{res['stamina_gained']} 體力**（目前 `{res['new_stamina']}`）！",
                ephemeral=True,
            )
        except RPGError as exc:
            await _send_error(interaction, str(exc))


# =============================================================================
# 4. Interactive Turn-Based Combat View
# =============================================================================
class CombatView(OwnerView):
    def __init__(self, engine: RPGEngine, owner_id: int) -> None:
        super().__init__(engine, owner_id, timeout=600.0)
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        self.clear_items()
        session = self.engine.active_combats.get(str(self.owner_id))
        if session is None or session.finished:
            if session is not None:
                if session.mode == "dungeon":
                    btn_retry = discord.ui.Button(label="再挑戰一次", emoji="🔁", style=discord.ButtonStyle.primary, row=0)
                    btn_retry.callback = self._on_rematch
                    self.add_item(btn_retry)
                elif session.mode == "abyss":
                    label = "挑戰下一層" if session.victory else "再次挑戰本層"
                    btn_next = discord.ui.Button(label=label, emoji="🗼", style=discord.ButtonStyle.danger, row=0)
                    btn_next.callback = self._on_rematch
                    self.add_item(btn_next)
            return

        actions_row0 = [
            ("普攻", "⚔️", discord.ButtonStyle.primary, "attack"),
            ("主動技能", "✨", discord.ButtonStyle.success, "skill"),
            ("終極奧義", "🌟", discord.ButtonStyle.danger, "ultimate"),
            ("防禦反擊", "🛡️", discord.ButtonStyle.secondary, "defend"),
        ]
        for label, emoji, style, act in actions_row0:
            btn = discord.ui.Button(label=label, emoji=emoji, style=style, row=0)
            btn.callback = self._make_action_cb(act)
            self.add_item(btn)

        actions_row1 = [
            ("喝生命藥水", "🧪", discord.ButtonStyle.success, "potion"),
            ("自動戰鬥", "⚡", discord.ButtonStyle.primary, "auto"),
            ("撤退 (退半體力)", "🏃", discord.ButtonStyle.secondary, "retreat"),
        ]
        for label, emoji, style, act in actions_row1:
            btn = discord.ui.Button(label=label, emoji=emoji, style=style, row=1)
            btn.callback = self._make_action_cb(act)
            self.add_item(btn)

    def _make_action_cb(self, action: str):
        async def callback(interaction: discord.Interaction) -> None:
            try:
                session = self.engine.combat_action(str(interaction.user.id), action)
                player = self.engine.require_player(str(interaction.user.id))
                self._refresh_buttons()
                embeds = build_combat_embeds(session, player)
                await interaction.response.edit_message(embeds=embeds, view=self)
            except RPGError as exc:
                await _send_error(interaction, str(exc))

        return callback

    async def _on_rematch(self, interaction: discord.Interaction) -> None:
        prev = self.engine.active_combats.get(str(self.owner_id))
        if prev is None:
            await _send_error(interaction, "找不到先前的戰鬥紀錄，請重新輸入副本或深淵指令。")
            return
        try:
            if prev.mode == "dungeon":
                session = self.engine.start_dungeon_combat(
                    str(interaction.user.id),
                    prev.target_id,
                    prev.difficulty,
                    display_name=interaction.user.display_name,
                )
            else:
                next_floor = int(prev.target_id) + (1 if prev.victory else 0)
                session = self.engine.start_abyss_combat(
                    str(interaction.user.id),
                    floor=next_floor,
                    display_name=interaction.user.display_name,
                )
            player = self.engine.require_player(str(interaction.user.id))
            self._refresh_buttons()
            embeds = build_combat_embeds(session, player)
            await interaction.response.edit_message(embeds=embeds, view=self)
        except RPGError as exc:
            await _send_error(interaction, str(exc))


# =============================================================================
# 5. Dungeon Hall Selector View
# =============================================================================
class DungeonHallView(OwnerView):
    def __init__(self, engine: RPGEngine, owner_id: int) -> None:
        super().__init__(engine, owner_id)
        self.dungeon_id = DUNGEONS[0]["id"]
        self.difficulty = "normal"
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        d_opts = [
            discord.SelectOption(
                label=f"{d['name']} (建議Lv.{d['rec_level']} / T{d['gear_tier']}裝)",
                value=d["id"],
                emoji=d["emoji"],
                default=(d["id"] == self.dungeon_id),
            )
            for d in DUNGEONS
        ]
        sel_d = discord.ui.Select(placeholder="選擇副本...", options=d_opts, row=0)
        sel_d.callback = self._on_select_dungeon
        self.add_item(sel_d)

        diff_opts = [
            discord.SelectOption(
                label=f"{cfg['name']}難度 (體力 {cfg['stamina']} / 獎勵 x{cfg['reward_mult']:.1f})",
                value=key,
                emoji=cfg["emoji"],
                default=(key == self.difficulty),
            )
            for key, cfg in DIFFICULTIES.items()
        ]
        sel_diff = discord.ui.Select(placeholder="選擇難度...", options=diff_opts, row=1)
        sel_diff.callback = self._on_select_diff
        self.add_item(sel_diff)

        btn_fight = discord.ui.Button(label="進入副本戰鬥", emoji="⚔️", style=discord.ButtonStyle.danger, row=2)
        btn_fight.callback = self._on_fight
        self.add_item(btn_fight)

        btn_sw1 = discord.ui.Button(label="快速掃蕩 x1", emoji="⚡", style=discord.ButtonStyle.success, row=2)
        btn_sw1.callback = self._make_sweep_cb(1)
        self.add_item(btn_sw1)

        btn_sw3 = discord.ui.Button(label="快速掃蕩 x3", emoji="⚡", style=discord.ButtonStyle.primary, row=2)
        btn_sw3.callback = self._make_sweep_cb(3)
        self.add_item(btn_sw3)

    async def _on_select_dungeon(self, interaction: discord.Interaction) -> None:
        self.dungeon_id = interaction.data["values"][0]
        try:
            player = self.engine.require_player(str(interaction.user.id))
            clears = self.engine.db.get_dungeon_clears(player.user_id)
            self._rebuild()
            embed = build_dungeon_list_embed(player, clears, selected_dungeon_id=self.dungeon_id)
            await interaction.response.edit_message(embed=embed, view=self)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    async def _on_select_diff(self, interaction: discord.Interaction) -> None:
        self.difficulty = interaction.data["values"][0]
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _on_fight(self, interaction: discord.Interaction) -> None:
        try:
            session = self.engine.start_dungeon_combat(
                str(interaction.user.id),
                self.dungeon_id,
                self.difficulty,
                display_name=interaction.user.display_name,
            )
            player = self.engine.require_player(str(interaction.user.id))
            embeds = build_combat_embeds(session, player)
            view = CombatView(self.engine, interaction.user.id)
            await interaction.response.edit_message(embeds=embeds, view=view)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    def _make_sweep_cb(self, times: int):
        async def callback(interaction: discord.Interaction) -> None:
            try:
                res = self.engine.sweep_dungeon(
                    str(interaction.user.id), self.dungeon_id, self.difficulty, times=times
                )
                d = res["dungeon"]
                diff = res["difficulty"]
                lines = [
                    f"⚡ 快速掃蕩 **{d['emoji']} {d['name']}（{diff['name']}）x{times}** 完成！",
                    f"🪙 金幣：**+{res['gold']:,}** ｜ ✨ 經驗：**+{res['exp']:,}**"
                    + (f" ｜ 🎉 升級 +{res['levels_gained']}！" if res["levels_gained"] else ""),
                ]
                if res["loot"]:
                    loot_s = "、".join(
                        f"{ITEMS[k]['emoji']}{ITEMS[k]['name']} x{v}"
                        for k, v in res["loot"].items()
                        if k in ITEMS
                    )
                    lines.append(f"📦 材料：{loot_s}")
                for eq in res["gear"]:
                    rdef = RARITIES[eq.rarity]
                    lines.append(f"🎁 裝備：{rdef['emoji']} **[{rdef['name']}] {eq.name}**（`#{eq.id}` 戰力 `{eq.power_score:,}`）")
                sweep_embed = discord.Embed(
                    title="⚡ 副本快速掃蕩結算",
                    description="\n".join(lines)[:4096],
                    color=0x2ECC71,
                )
                sweep_embed.set_thumbnail(url=get_dungeon_boss_portrait_url(d["id"]))
                embeds = [sweep_embed]
                if res["gear"]:
                    best_eq = max(res["gear"], key=lambda item: item.power_score)
                    rdef = RARITIES[best_eq.rarity]
                    extra_note = (
                        f"本次掃蕩共掉落 **{len(res['gear'])} 件**裝備，以下展示最高戰力戰利品："
                        if len(res["gear"]) > 1
                        else f"來自 **{d['name']}（{diff['name']}）** 快速掃蕩！"
                    )
                    embeds.append(
                        build_equipment_card_embed(
                            best_eq,
                            title=f"🎁 掃蕩戰利品 — {rdef['emoji']} [{rdef['name']}] {best_eq.name}",
                            subtitle=extra_note,
                            author_name="副本掃蕩裝備掉落",
                            author_icon_url=get_ui_asset_url("chest_open"),
                        )
                    )
                await interaction.response.send_message(embeds=embeds)
            except RPGError as exc:
                await _send_error(interaction, str(exc))

        return callback


# =============================================================================
# 6. Public Server World Boss View
# =============================================================================
class WorldBossView(discord.ui.View):
    """Public co-op view: ANY registered server player can attack the World Boss!"""

    def __init__(self, engine: RPGEngine) -> None:
        super().__init__(timeout=600.0)
        self.engine = engine

    @discord.ui.button(label="發起討伐 (-8 體力)", emoji="⚔️", style=discord.ButtonStyle.danger)
    async def btn_attack(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            res = self.engine.attack_world_boss(
                str(interaction.user.id), display_name=interaction.user.display_name
            )
            player = self.engine.require_player(str(interaction.user.id))
            display_boss = res["next_boss"] if (res["boss_killed"] and res["next_boss"]) else res["boss"]
            ranks = self.engine.db.get_world_boss_rankings(display_boss.id, limit=5)
            embed = build_world_boss_embed(display_boss, ranks, player, attack_res=res)
            await interaction.response.edit_message(embed=embed, view=self)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    @discord.ui.button(label="刷新狀態", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def btn_refresh(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            player = self.engine.require_player(str(interaction.user.id), interaction.user.display_name)
            boss = self.engine.get_or_spawn_world_boss()
            ranks = self.engine.db.get_world_boss_rankings(boss.id, limit=5)
            embed = build_world_boss_embed(boss, ranks, player)
            await interaction.response.edit_message(embed=embed, view=self)
        except RPGError as exc:
            await _send_error(interaction, str(exc))


# =============================================================================
# 7. Shop View (4 Tabs)
# =============================================================================
class ShopView(OwnerView):
    def __init__(self, engine: RPGEngine, owner_id: int, tab: str = "supply") -> None:
        super().__init__(engine, owner_id)
        self.tab = tab
        self._rebuild()

    def render_embed(self, player) -> discord.Embed:
        bucket = f"daily:{self.engine.today_key()}"
        daily_p = self.engine.db.get_shop_bucket_purchases(player.user_id, bucket)
        mshop = self.engine.get_mystery_shop(player)
        keys = self.engine.db.get_item_qty(player.user_id, "relic_key")
        return build_shop_embed(player, self.tab, daily_p, mshop, keys)

    def _rebuild(self) -> None:
        self.clear_items()
        tabs = [
            ("常駐商店", "🏪", "supply"),
            ("神秘商店", "✨", "mystery"),
            ("秘寶抽箱", "🎁", "gacha"),
            ("回收出售", "💰", "sell"),
        ]
        for label, emoji, tkey in tabs:
            btn = discord.ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.primary if self.tab == tkey else discord.ButtonStyle.secondary,
                row=0,
            )
            btn.callback = self._make_tab_cb(tkey)
            self.add_item(btn)

        player = self.engine.db.get_player(str(self.owner_id))
        if player is None:
            return

        if self.tab == "supply":
            opts = []
            for s in SUPPLY_SHOP:
                meta = ITEMS[s["item_id"]]
                cur = "金幣" if s["currency"] == "gold" else "星鑽"
                opts.append(
                    discord.SelectOption(
                        label=f"{meta['name']} x{s['qty']} ({s['price']:,} {cur})",
                        value=s["id"],
                        emoji=meta["emoji"],
                    )
                )
            sel = discord.ui.Select(placeholder="選擇要購買的商品...", options=opts, row=1)
            sel.callback = self._on_buy_supply
            self.add_item(sel)

        elif self.tab == "mystery":
            mshop = self.engine.get_mystery_shop(player)
            opts = []
            for o in mshop["offers"]:
                cur = "金幣" if o["currency"] == "gold" else "星鑽"
                sold = mshop["purchased"].get(o["key"], 0) >= 1
                opts.append(
                    discord.SelectOption(
                        label=f"{'[已購] ' if sold else ''}{o['name']} ({o['price']:,} {cur})"[:100],
                        value=o["key"],
                    )
                )
            sel = discord.ui.Select(placeholder="選擇神秘商店限時特惠...", options=opts, row=1)
            sel.callback = self._on_buy_mystery
            self.add_item(sel)

        elif self.tab == "gacha":
            b1 = discord.ui.Button(label="開啟冒險者木箱 (1,500 金幣)", emoji="🧰", style=discord.ButtonStyle.success, row=1)
            b1.callback = self._make_chest_cb("wooden")
            self.add_item(b1)

            b2 = discord.ui.Button(label="開啟星界秘寶箱 (鑰匙/100星鑽)", emoji="💎", style=discord.ButtonStyle.danger, row=1)
            b2.callback = self._make_chest_cb("astral")
            self.add_item(b2)

        elif self.tab == "sell":
            b1 = discord.ui.Button(label="出售多餘礦石 (每種保留10個)", emoji="⛏️", style=discord.ButtonStyle.success, row=1)
            b1.callback = self._on_sell_ores
            self.add_item(b1)

            b2 = discord.ui.Button(label="一鍵分解稀有以下未鎖裝備", emoji="♻️", style=discord.ButtonStyle.danger, row=1)
            b2.callback = self._on_bulk_dismantle
            self.add_item(b2)

    def _make_tab_cb(self, tkey: str):
        async def callback(interaction: discord.Interaction) -> None:
            try:
                self.tab = tkey
                player = self.engine.require_player(str(interaction.user.id))
                self._rebuild()
                await interaction.response.edit_message(embed=self.render_embed(player), view=self)
            except RPGError as exc:
                await _send_error(interaction, str(exc))

        return callback

    async def _on_buy_supply(self, interaction: discord.Interaction) -> None:
        offer_id = interaction.data["values"][0]
        try:
            res = self.engine.buy_supply_item(str(interaction.user.id), offer_id)
            player = res["player"]
            self._rebuild()
            await interaction.response.edit_message(embed=self.render_embed(player), view=self)
            item_meta = res["item"]
            buy_embed = discord.Embed(
                title=f"✅ 購買成功 — {item_meta['emoji']} {item_meta['name']} x{res['offer']['qty']}",
                description=(
                    f"剩餘餘額：🪙 **`{player.gold:,}`** 金幣 ｜ 💎 **`{player.gems:,}`** 星鑽"
                ),
                color=0x2ECC71,
            )
            buy_embed.set_thumbnail(url=get_item_icon_url(res["offer"]["item_id"]))
            await interaction.followup.send(embed=buy_embed, ephemeral=True)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    async def _on_buy_mystery(self, interaction: discord.Interaction) -> None:
        offer_key = interaction.data["values"][0]
        try:
            res = self.engine.buy_mystery_offer(str(interaction.user.id), offer_key)
            player = res["player"]
            self._rebuild()
            await interaction.response.edit_message(embed=self.render_embed(player), view=self)
            if res["gear"]:
                eq = res["gear"]
                rdef = RARITIES[eq.rarity]
                card = build_equipment_card_embed(
                    eq,
                    title=f"✨ 神秘商店購入 — {rdef['emoji']} [{rdef['name']}] {eq.name}！",
                    subtitle=f"特惠商品：**{res['offer']['name']}**",
                    author_name="限時折扣神秘商店",
                    author_icon_url=get_shop_tab_icon_url("mystery"),
                )
                await interaction.followup.send(embed=card, ephemeral=True)
            else:
                buy_embed = discord.Embed(
                    title=f"✨ 神秘商店購入 — {res['offer']['name']}",
                    description=(
                        f"剩餘餘額：🪙 **`{player.gold:,}`** 金幣 ｜ 💎 **`{player.gems:,}`** 星鑽"
                    ),
                    color=0x9B59B6,
                )
                icon_url = (
                    get_item_icon_url(res["offer"]["item_id"])
                    if res["offer"].get("type") == "item" and res["offer"].get("item_id")
                    else get_shop_tab_icon_url("mystery")
                )
                buy_embed.set_thumbnail(url=icon_url)
                await interaction.followup.send(embed=buy_embed, ephemeral=True)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    def _make_chest_cb(self, chest_type: str):
        async def callback(interaction: discord.Interaction) -> None:
            try:
                res = self.engine.open_chest(str(interaction.user.id), chest_type)
                player = self.engine.require_player(str(interaction.user.id))
                self._rebuild()
                await interaction.response.edit_message(embed=self.render_embed(player), view=self)
                eq = res["gear"]
                rdef = RARITIES[eq.rarity]
                bonus_str = "、".join(
                    f"{ITEMS[k]['emoji']}{ITEMS[k]['name']} x{v}" for k, v in res["bonus_items"].items()
                )
                extra_fields = [("📦 附贈材料", bonus_str, False)] if bonus_str else None
                embed = build_equipment_card_embed(
                    eq,
                    title=f"🎁 開箱結果 — {rdef['emoji']} [{rdef['name']}] {eq.name}！",
                    subtitle=f"消耗：{res['used_currency']}",
                    author_name="星界秘寶開箱",
                    author_icon_url=get_ui_asset_url("chest_open"),
                    extra_fields=extra_fields,
                )
                await interaction.followup.send(embed=embed)
            except RPGError as exc:
                await _send_error(interaction, str(exc))

        return callback

    async def _on_sell_ores(self, interaction: discord.Interaction) -> None:
        try:
            res = self.engine.sell_ores(str(interaction.user.id), keep_each=10)
            player = self.engine.require_player(str(interaction.user.id))
            self._rebuild()
            await interaction.response.edit_message(embed=self.render_embed(player), view=self)
            await interaction.followup.send(
                f"💰 成功出售多餘礦石，獲得 **+{res['gold']:,} 金幣**！",
                ephemeral=True,
            )
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    async def _on_bulk_dismantle(self, interaction: discord.Interaction) -> None:
        try:
            res = self.engine.bulk_dismantle(str(interaction.user.id), max_rarity="rare")
            player = self.engine.require_player(str(interaction.user.id))
            self._rebuild()
            await interaction.response.edit_message(embed=self.render_embed(player), view=self)
            await interaction.followup.send(
                f"♻️ 已分解 **{res['count']} 件**低階裝備，獲得 🔹 初級強化石 `x{res['stones']}`、🪙 金幣 `+{res['gold']:,}`！",
                ephemeral=True,
            )
        except RPGError as exc:
            await _send_error(interaction, str(exc))


# =============================================================================
# 8. Bag & Equipment Management View
# =============================================================================
class BagView(OwnerView):
    def __init__(self, engine: RPGEngine, owner_id: int, tab: str = "gear", page: int = 0) -> None:
        super().__init__(engine, owner_id)
        self.tab = tab
        self.page = page
        self._rebuild()

    def render_embed(self, player) -> discord.Embed:
        gear = self.engine.db.get_equipment(player.user_id)
        inv = self.engine.db.get_inventory(player.user_id)
        return build_bag_embed(player, gear, inv, self.tab, self.page)

    def _rebuild(self) -> None:
        self.clear_items()
        b_gear = discord.ui.Button(
            label="裝備清單",
            emoji="🛡️",
            style=discord.ButtonStyle.primary if self.tab == "gear" else discord.ButtonStyle.secondary,
            row=0,
        )
        b_gear.callback = self._make_tab_cb("gear")
        self.add_item(b_gear)

        b_mat = discord.ui.Button(
            label="礦石與材料",
            emoji="📦",
            style=discord.ButtonStyle.primary if self.tab == "materials" else discord.ButtonStyle.secondary,
            row=0,
        )
        b_mat.callback = self._make_tab_cb("materials")
        self.add_item(b_mat)

        b_auto = discord.ui.Button(label="一鍵最佳裝備", emoji="✨", style=discord.ButtonStyle.success, row=0)
        b_auto.callback = self._on_auto_equip
        self.add_item(b_auto)

        b_stam = discord.ui.Button(label="喝體力劑", emoji="⚡", style=discord.ButtonStyle.secondary, row=0)
        b_stam.callback = self._on_use_stamina
        self.add_item(b_stam)

        if self.tab == "gear":
            gear = self.engine.db.get_equipment(str(self.owner_id))
            per_page = 6
            total_pages = max(1, (len(gear) + per_page - 1) // per_page)
            self.page = max(0, min(self.page, total_pages - 1))
            chunk = gear[self.page * per_page : (self.page + 1) * per_page]

            if chunk:
                eq_opts = [
                    discord.SelectOption(
                        label=f"#{e.id} [{RARITIES[e.rarity]['name']}] {e.name} +{e.enhance_level} (戰力{e.power_score:,})"[:100],
                        value=str(e.id),
                        emoji=SLOTS[e.slot]["emoji"],
                    )
                    for e in chunk
                ]
                sel_eq = discord.ui.Select(placeholder="選擇本頁裝備立即穿戴...", options=eq_opts, row=1)
                sel_eq.callback = self._on_equip
                self.add_item(sel_eq)

                lock_opts = [
                    discord.SelectOption(
                        label=f"{'解鎖' if e.is_locked else '鎖定'} #{e.id} {e.name}"[:100],
                        value=str(e.id),
                        emoji="🔓" if e.is_locked else "🔒",
                    )
                    for e in chunk
                ]
                sel_lock = discord.ui.Select(placeholder="鎖定/解鎖裝備（防止誤分解）...", options=lock_opts, row=2)
                sel_lock.callback = self._on_lock
                self.add_item(sel_lock)

                inspect_opts = [
                    discord.SelectOption(
                        label=f"檢視 #{e.id} [{RARITIES[e.rarity]['name']}] {e.name} +{e.enhance_level}"[:100],
                        value=str(e.id),
                        emoji=RARITIES[e.rarity]["emoji"],
                    )
                    for e in chunk
                ]
                sel_inspect = discord.ui.Select(
                    placeholder="🔍 查看本頁裝備圖片與詳細卡片...",
                    options=inspect_opts,
                    row=3,
                )
                sel_inspect.callback = self._on_inspect
                self.add_item(sel_inspect)

            if total_pages > 1:
                b_prev = discord.ui.Button(label="上一頁", emoji="◀️", style=discord.ButtonStyle.secondary, row=4, disabled=(self.page <= 0))
                b_prev.callback = self._make_page_cb(-1)
                self.add_item(b_prev)

                b_next = discord.ui.Button(label="下一頁", emoji="▶️", style=discord.ButtonStyle.secondary, row=4, disabled=(self.page >= total_pages - 1))
                b_next.callback = self._make_page_cb(1)
                self.add_item(b_next)

    def _make_tab_cb(self, tab: str):
        async def callback(interaction: discord.Interaction) -> None:
            self.tab = tab
            self.page = 0
            player = self.engine.require_player(str(interaction.user.id))
            self._rebuild()
            await interaction.response.edit_message(embed=self.render_embed(player), view=self)

        return callback

    def _make_page_cb(self, delta: int):
        async def callback(interaction: discord.Interaction) -> None:
            self.page = max(0, self.page + delta)
            player = self.engine.require_player(str(interaction.user.id))
            self._rebuild()
            await interaction.response.edit_message(embed=self.render_embed(player), view=self)

        return callback

    async def _on_auto_equip(self, interaction: discord.Interaction) -> None:
        try:
            equipped, stats = self.engine.auto_equip_best(str(interaction.user.id))
            player = self.engine.require_player(str(interaction.user.id))
            self._rebuild()
            await interaction.response.edit_message(embed=self.render_embed(player), view=self)
            if equipped:
                best_eq = max(equipped, key=lambda item: item.power_score)
                card = build_equipment_card_embed(
                    best_eq,
                    title=f"✨ 已自動穿戴 {len(equipped)} 件最強裝備！",
                    subtitle=(
                        f"🏆 目前角色總戰力：**`{stats.combat_power:,}`**\n"
                        f"以下展示目前最高戰力裝備：**{best_eq.name}**"
                    ),
                    author_name="一鍵配裝完成",
                    author_icon_url=get_ui_asset_url("bag_icon"),
                )
                await interaction.followup.send(embed=card, ephemeral=True)
            else:
                await interaction.followup.send(
                    f"✨ 已自動穿戴各部位最強裝備！目前總戰力：**`{stats.combat_power:,}`**",
                    ephemeral=True,
                )
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    async def _on_equip(self, interaction: discord.Interaction) -> None:
        item_id = int(interaction.data["values"][0])
        try:
            item, stats = self.engine.equip_item(str(interaction.user.id), item_id)
            player = self.engine.require_player(str(interaction.user.id))
            self._rebuild()
            await interaction.response.edit_message(embed=self.render_embed(player), view=self)
            card = build_equipment_card_embed(
                item,
                title=f"🛡️ 已成功穿戴 {item.name}！",
                subtitle=f"🏆 目前角色總戰力：**`{stats.combat_power:,}`**",
            )
            await interaction.followup.send(embed=card, ephemeral=True)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    async def _on_inspect(self, interaction: discord.Interaction) -> None:
        item_id = int(interaction.data["values"][0])
        item = self.engine.db.get_equipment_by_id(str(interaction.user.id), item_id)
        if item is None:
            await _send_error(interaction, f"找不到編號 `#{item_id}` 的裝備，可能已被分解。")
            return
        card = build_equipment_card_embed(item)
        await interaction.response.send_message(embed=card, ephemeral=True)

    async def _on_lock(self, interaction: discord.Interaction) -> None:
        item_id = int(interaction.data["values"][0])
        try:
            item = self.engine.toggle_lock_equipment(str(interaction.user.id), item_id)
            player = self.engine.require_player(str(interaction.user.id))
            self._rebuild()
            await interaction.response.edit_message(embed=self.render_embed(player), view=self)
            await interaction.followup.send(
                f"{'🔒 已鎖定' if item.is_locked else '🔓 已解鎖'} `#{item.id}` **{item.name}**。",
                ephemeral=True,
            )
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    async def _on_use_stamina(self, interaction: discord.Interaction) -> None:
        try:
            res = self.engine.use_consumable(str(interaction.user.id), "stamina_elixir")
            await interaction.response.send_message(
                f"⚡ 回復 **+{res['stamina_gained']} 體力**（目前 `{res['new_stamina']}`）！",
                ephemeral=True,
            )
        except RPGError as exc:
            await _send_error(interaction, str(exc))


# =============================================================================
# 9. Blacksmith Forge View
# =============================================================================
class ForgeView(OwnerView):
    def __init__(self, engine: RPGEngine, owner_id: int) -> None:
        super().__init__(engine, owner_id)
        self.use_protect = False
        self.forge_slot: Optional[str] = None
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        equipped = self.engine.db.get_equipment(str(self.owner_id), equipped_only=True)

        # Row 0: Target Slot Selector for forging
        slot_opts = [
            discord.SelectOption(
                label="鍛造部位：隨機部位",
                value="random",
                emoji="🎲",
                default=(self.forge_slot is None),
            )
        ] + [
            discord.SelectOption(
                label=f"指定鍛造部位：{SLOTS[s]['name']}",
                value=s,
                emoji=SLOTS[s]["emoji"],
                default=(self.forge_slot == s),
            )
            for s in SLOT_ORDER
        ]
        sel_slot = discord.ui.Select(placeholder="選擇鍛造部位（預設隨機）...", options=slot_opts, row=0)
        sel_slot.callback = self._on_select_slot
        self.add_item(sel_slot)

        # Row 1: Forge Gear Tier Selector
        slot_label = SLOTS[self.forge_slot]["name"] if self.forge_slot else "隨機部位"
        forge_opts = [
            discord.SelectOption(
                label=f"鍛造 T{t} {cfg['name']}・{slot_label} ({cfg['forge_gold']:,} 金幣)"[:100],
                value=str(t),
                emoji="🔨",
            )
            for t, cfg in GEAR_TIERS.items()
        ]
        sel_forge = discord.ui.Select(placeholder="🔨 選擇階級立即鍛造裝備...", options=forge_opts, row=1)
        sel_forge.callback = self._on_forge_gear
        self.add_item(sel_forge)

        # Row 2: Enhance Equipped Gear Selector
        enh_opts = [
            discord.SelectOption(
                label=f"強化 #{e.id} {e.name} (+{e.enhance_level} → +{e.enhance_level + 1})"[:100],
                value=str(e.id),
                emoji=SLOTS[e.slot]["emoji"],
            )
            for e in equipped
            if e.enhance_level < MAX_ENHANCE_LEVEL
        ]
        if enh_opts:
            sel_enh = discord.ui.Select(placeholder="✨ 選擇穿戴中裝備立即強化...", options=enh_opts, row=2)
            sel_enh.callback = self._on_enhance_gear
            self.add_item(sel_enh)

        # Row 3: Action buttons
        b_pick = discord.ui.Button(label="升級礦鎬", emoji="⛏️", style=discord.ButtonStyle.success, row=3)
        b_pick.callback = self._on_upgrade_pickaxe
        self.add_item(b_pick)

        b_prot = discord.ui.Button(
            label=f"保護卷軸：{'開啟' if self.use_protect else '關閉'}",
            emoji="📜",
            style=discord.ButtonStyle.primary if self.use_protect else discord.ButtonStyle.secondary,
            row=3,
        )
        b_prot.callback = self._on_toggle_protect
        self.add_item(b_prot)

        b_dis = discord.ui.Button(label="一鍵分解低階裝備", emoji="♻️", style=discord.ButtonStyle.danger, row=3)
        b_dis.callback = self._on_bulk_dismantle
        self.add_item(b_dis)

    async def _refresh(self, interaction: discord.Interaction) -> None:
        player = self.engine.require_player(str(interaction.user.id))
        inv = self.engine.db.get_inventory(player.user_id)
        eq = self.engine.db.get_equipment(player.user_id, equipped_only=True)
        self._rebuild()
        await interaction.response.edit_message(embed=build_forge_embed(player, inv, eq), view=self)

    async def _on_select_slot(self, interaction: discord.Interaction) -> None:
        val = interaction.data["values"][0]
        self.forge_slot = None if val == "random" else val
        await self._refresh(interaction)

    async def _on_forge_gear(self, interaction: discord.Interaction) -> None:
        tier = int(interaction.data["values"][0])
        try:
            res = self.engine.forge_equipment(str(interaction.user.id), tier, slot=self.forge_slot)
            await self._refresh(interaction)
            eq = res["item"]
            rdef = RARITIES[eq.rarity]
            embed = build_equipment_card_embed(
                eq,
                title=f"🔨 鍛造成功！誕生了 {rdef['emoji']} [{rdef['name']}] {eq.name}！",
                author_name="星界鐵匠鋪・裝備鍛造",
                author_icon_url=get_ui_asset_url("anvil_icon"),
            )
            await interaction.followup.send(embed=embed)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    async def _on_enhance_gear(self, interaction: discord.Interaction) -> None:
        item_id = int(interaction.data["values"][0])
        try:
            res = self.engine.enhance_equipment(
                str(interaction.user.id), item_id, use_protect=self.use_protect
            )
            await self._refresh(interaction)
            await interaction.followup.send(embed=build_enhance_result_embed(res), ephemeral=True)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    async def _on_upgrade_pickaxe(self, interaction: discord.Interaction) -> None:
        try:
            res = self.engine.upgrade_pickaxe(str(interaction.user.id))
            await self._refresh(interaction)
            p = res["pickaxe"]
            pick_embed = discord.Embed(
                title=f"⛏️ 礦鎬升級成功 — T{res['new_tier']} {p['name']}！",
                description=(
                    f"新礦鎬：{p['emoji']} **T{res['new_tier']} {p['name']}**\n"
                    f"採礦產量倍率：**`x{p['yield_mult']:.2f}`** ｜ 雙倍暴擊礦率：**`{p['double_chance'] * 100:.0f}%`**"
                ),
                color=0x2ECC71,
            )
            pick_embed.set_author(name="星界鐵匠鋪・礦鎬鍛造", icon_url=get_ui_asset_url("anvil_icon"))
            pick_embed.set_thumbnail(url=get_pickaxe_icon_url(res["new_tier"]))
            await interaction.followup.send(embed=pick_embed, ephemeral=True)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    async def _on_toggle_protect(self, interaction: discord.Interaction) -> None:
        self.use_protect = not self.use_protect
        await self._refresh(interaction)

    async def _on_bulk_dismantle(self, interaction: discord.Interaction) -> None:
        try:
            res = self.engine.bulk_dismantle(str(interaction.user.id), max_rarity="rare")
            await self._refresh(interaction)
            await interaction.followup.send(
                f"♻️ 已分解 **{res['count']} 件**低階未鎖裝備，獲得 🔹 初級強化石 `x{res['stones']}`、🪙 金幣 `+{res['gold']:,}`！",
                ephemeral=True,
            )
        except RPGError as exc:
            await _send_error(interaction, str(exc))


# =============================================================================
# 10. Daily Check-in & Quests View
# =============================================================================
class DailyQuestView(OwnerView):
    @discord.ui.button(label="每日簽到", emoji="📅", style=discord.ButtonStyle.success)
    async def btn_checkin(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            res = self.engine.daily_checkin(str(interaction.user.id), interaction.user.display_name)
            player = self.engine.require_player(str(interaction.user.id))
            qst = self.engine.get_quests_status(player.user_id)
            embed = build_daily_quests_embed(player, qst, self.engine.today_key())
            await interaction.response.edit_message(embed=embed, view=self)
            items_s = "、".join(
                f"{ITEMS[k]['emoji']}{ITEMS[k]['name']} x{v}" for k, v in res["items"].items()
            )
            await interaction.followup.send(
                f"📅 **簽到成功（連簽第 {res['streak']} 天 / 第 {res['cycle_day']} 日獎勵）！**\n"
                f"獲得 🪙 `+{res['gold']:,}` 金幣 ｜ 💎 `+{res['gems']}` 星鑽 ｜ {items_s}",
                ephemeral=True,
            )
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    @discord.ui.button(label="一鍵領取完成任務", emoji="🎁", style=discord.ButtonStyle.primary)
    async def btn_claim_quests(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            res = self.engine.claim_all_quests(str(interaction.user.id))
            player = self.engine.require_player(str(interaction.user.id))
            qst = self.engine.get_quests_status(player.user_id)
            embed = build_daily_quests_embed(player, qst, self.engine.today_key())
            await interaction.response.edit_message(embed=embed, view=self)
            items_s = "、".join(
                f"{ITEMS[k]['emoji']}{ITEMS[k]['name']} x{v}" for k, v in res["items"].items()
            )
            await interaction.followup.send(
                f"🎁 已領取 **{res['claimed_count']} 項任務獎勵**（{'、'.join(res['claimed_names'])}）！\n"
                f"🪙 `+{res['gold']:,}` ｜ 💎 `+{res['gems']}` ｜ ✨ `+{res['exp']:,} EXP` ｜ {items_s}",
                ephemeral=True,
            )
        except RPGError as exc:
            await _send_error(interaction, str(exc))


# =============================================================================
# 11. Timed Expedition View
# =============================================================================
class ExpeditionView(OwnerView):
    def __init__(self, engine: RPGEngine, owner_id: int) -> None:
        super().__init__(engine, owner_id)
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        active = self.engine.db.get_expedition(str(self.owner_id))
        if active is None:
            opts = [
                discord.SelectOption(
                    label=f"{e['name']} ({e['duration_sec'] // 3600} 小時 / Lv.{e['min_level']})",
                    value=e["id"],
                    emoji=e["emoji"],
                )
                for e in EXPEDITIONS
            ]
            sel = discord.ui.Select(placeholder="選擇派遣遠征路線...", options=opts, row=0)
            sel.callback = self._on_start
            self.add_item(sel)
        else:
            ready = self.engine.now() >= active.ends_at
            btn = discord.ui.Button(
                label="領取派遣戰利品" if ready else "刷新派遣進度",
                emoji="🎁" if ready else "🔄",
                style=discord.ButtonStyle.success if ready else discord.ButtonStyle.secondary,
                row=0,
            )
            btn.callback = self._on_claim_or_refresh
            self.add_item(btn)

    async def _on_start(self, interaction: discord.Interaction) -> None:
        eid = interaction.data["values"][0]
        try:
            exp_obj = self.engine.start_expedition(str(interaction.user.id), eid)
            player = self.engine.require_player(str(interaction.user.id))
            self._rebuild()
            embed = build_expedition_embed(player, exp_obj, self.engine.now())
            await interaction.response.edit_message(embed=embed, view=self)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    async def _on_claim_or_refresh(self, interaction: discord.Interaction) -> None:
        active = self.engine.db.get_expedition(str(interaction.user.id))
        now_ts = self.engine.now()
        if active and now_ts < active.ends_at:
            player = self.engine.require_player(str(interaction.user.id))
            self._rebuild()
            await interaction.response.edit_message(
                embed=build_expedition_embed(player, active, now_ts), view=self
            )
            return
        try:
            res = self.engine.claim_expedition(str(interaction.user.id))
            player = self.engine.require_player(str(interaction.user.id))
            self._rebuild()
            await interaction.response.edit_message(
                embed=build_expedition_embed(player, None, self.engine.now()), view=self
            )
            loot_s = "、".join(
                f"{ITEMS[k]['emoji']}{ITEMS[k]['name']} x{v}" for k, v in res["loot"].items()
            )
            exp_embed = discord.Embed(
                title=f"🧭 派遣【{res['expedition']['name']}】凱旋歸來！",
                description=(
                    f"🪙 金幣：**+{res['gold']:,}** ｜ ✨ 經驗：**+{res['exp']:,}**\n"
                    f"📦 帶回物資：{loot_s or '*無*'}"
                ),
                color=0x1ABC9C,
            )
            exp_embed.set_thumbnail(url=get_ui_asset_url("chest_open"))
            exp_embed.set_image(url=get_expedition_banner_url(res["expedition"]["id"]))
            embeds = [exp_embed]
            if res["gear"]:
                eq = res["gear"]
                rdef = RARITIES[eq.rarity]
                embeds.append(
                    build_equipment_card_embed(
                        eq,
                        title=f"🎁 遠征帶回裝備 — {rdef['emoji']} [{rdef['name']}] {eq.name}！",
                        subtitle=f"來自派遣路線：**{res['expedition']['name']}**",
                        author_name="離線冒險戰利品",
                        author_icon_url=get_ui_asset_url("chest_open"),
                    )
                )
            await interaction.followup.send(embeds=embeds)
        except RPGError as exc:
            await _send_error(interaction, str(exc))


# =============================================================================
# 12. Public Leaderboard Switcher View
# =============================================================================
class LeaderboardView(discord.ui.View):
    def __init__(self, engine: RPGEngine, category: str = "power") -> None:
        super().__init__(timeout=300.0)
        self.engine = engine
        self.category = category
        self._rebuild()

    def _rebuild(self) -> None:
        self.clear_items()
        cats = [
            ("戰力排行榜", "⚔️", "power"),
            ("等級與轉生榜", "⭐", "level"),
            ("無盡深淵榜", "🗼", "abyss"),
            ("富豪財富榜", "💰", "gold"),
            ("傳奇礦神榜", "⛏️", "mining"),
            ("世界王貢獻榜", "🐉", "boss"),
        ]
        opts = [
            discord.SelectOption(label=lbl, emoji=em, value=val, default=(val == self.category))
            for lbl, em, val in cats
        ]
        sel = discord.ui.Select(placeholder="切換排行榜類別...", options=opts)
        sel.callback = self._on_switch
        self.add_item(sel)

    async def _on_switch(self, interaction: discord.Interaction) -> None:
        self.category = interaction.data["values"][0]
        entries = self.engine.db.get_leaderboard(self.category, limit=10)
        rank, total = self.engine.db.get_player_rank(str(interaction.user.id), self.category)
        self._rebuild()
        embed = build_leaderboard_embed(self.category, entries, rank, total)
        await interaction.response.edit_message(embed=embed, view=self)


# =============================================================================
# 13. Achievements Title Picker View
# =============================================================================
class AchievementView(OwnerView):
    def __init__(self, engine: RPGEngine, owner_id: int) -> None:
        super().__init__(engine, owner_id)
        unlocked = self.engine.db.get_achievements(str(owner_id))
        opts = [discord.SelectOption(label="隱藏稱號（不顯示）", value="none", emoji="✖️")]
        for a in ACHIEVEMENTS:
            if a["id"] in unlocked:
                opts.append(
                    discord.SelectOption(
                        label=f"{a['title']} ({a['name']})"[:100],
                        value=a["id"],
                    )
                )
        sel = discord.ui.Select(placeholder="選擇要配戴顯示的成就稱號...", options=opts[:25])
        sel.callback = self._on_select_title
        self.add_item(sel)

    async def _on_select_title(self, interaction: discord.Interaction) -> None:
        aid = interaction.data["values"][0]
        try:
            title = self.engine.set_active_title(str(interaction.user.id), aid)
            player = self.engine.require_player(str(interaction.user.id))
            unlocked = self.engine.db.get_achievements(player.user_id)
            embed = build_achievements_embed(player, unlocked)
            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send(
                f"🏅 已切換配戴稱號為：**{title or '（無）'}**", ephemeral=True
            )
        except RPGError as exc:
            await _send_error(interaction, str(exc))


# =============================================================================
# 14. Class Promotion & Switch View
# =============================================================================
class ClassHallView(OwnerView):
    def __init__(self, engine: RPGEngine, owner_id: int) -> None:
        super().__init__(engine, owner_id)
        btn_promo = discord.ui.Button(label="進行職業進階轉職", emoji="✨", style=discord.ButtonStyle.success, row=0)
        btn_promo.callback = self._on_promote
        self.add_item(btn_promo)

        opts = [
            discord.SelectOption(label=f"轉換為 {cdef['name']}", value=cid, emoji=cdef["emoji"])
            for cid, cdef in CLASSES.items()
        ]
        sel = discord.ui.Select(placeholder="消耗轉職徽章自由切換職業...", options=opts, row=1)
        sel.callback = self._on_change_class
        self.add_item(sel)

    async def _on_promote(self, interaction: discord.Interaction) -> None:
        try:
            res = self.engine.promote_class(str(interaction.user.id))
            player = self.engine.require_player(str(interaction.user.id))
            inv = self.engine.db.get_inventory(player.user_id)
            await interaction.response.edit_message(embed=build_class_embed(player, inv), view=self)
            promo_embed = discord.Embed(
                title=f"🎊 轉職覺醒成功 — {res['new_title']}！",
                description=(
                    f"`{res['old_title']}` ➔ **`{res['new_title']}`**（{player.promo_tier} 階覺醒）\n"
                    f"🏆 目前總戰力：**`{res['stats'].combat_power:,}`**"
                ),
                color=0x9B59B6,
            )
            promo_embed.set_thumbnail(url=get_class_portrait_url(player.class_id, player.promo_tier))
            await interaction.followup.send(embed=promo_embed)
        except RPGError as exc:
            await _send_error(interaction, str(exc))

    async def _on_change_class(self, interaction: discord.Interaction) -> None:
        new_cid = interaction.data["values"][0]
        try:
            res = self.engine.change_class(str(interaction.user.id), new_cid)
            player = self.engine.require_player(str(interaction.user.id))
            inv = self.engine.db.get_inventory(player.user_id)
            await interaction.response.edit_message(embed=build_class_embed(player, inv), view=self)
            cls_embed = discord.Embed(
                title=f"🎖️ 轉換職業成功 — {res['new_title']}！",
                description=(
                    f"`{res['old_title']}` ➔ **`{res['new_title']}`**\n"
                    f"🏆 目前總戰力：**`{res['stats'].combat_power:,}`**"
                ),
                color=0x3498DB,
            )
            cls_embed.set_thumbnail(url=get_class_portrait_url(player.class_id, player.promo_tier))
            await interaction.followup.send(embed=cls_embed, ephemeral=True)
        except RPGError as exc:
            await _send_error(interaction, str(exc))


# =============================================================================
# 15. Rebirth Confirmation View
# =============================================================================
class RebirthView(OwnerView):
    @discord.ui.button(label="確認進行星界轉生飛升", emoji="🌟", style=discord.ButtonStyle.danger)
    async def btn_rebirth(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        try:
            res = self.engine.rebirth(str(interaction.user.id))
            player = self.engine.require_player(str(interaction.user.id))
            embed = build_rebirth_embed(player)
            await interaction.response.edit_message(embed=embed, view=self)
            rb_embed = discord.Embed(
                title=f"✨ 星界飛升成功 — ★{res['rebirth_count']} 轉冒險者！",
                description=(
                    f"恭喜 **{player.display_name}** 突破極限完成第 **{res['rebirth_count']} 次轉生**！\n"
                    f"💎 獲得獎勵：**+{res['bonus_gems']:,} 星鑽** 與永久全屬性倍率提升！"
                ),
                color=0xF1C40F,
            )
            rb_embed.set_thumbnail(url=get_ui_asset_url("achievement_laurel"))
            rb_embed.set_image(url=get_ui_asset_url("rebirth_banner"))
            await interaction.followup.send(embed=rb_embed)
        except RPGError as exc:
            await _send_error(interaction, str(exc))
