"""Top-level Discord Slash Commands wiring for the persistent RPG."""

from __future__ import annotations

from typing import List, Optional

import discord
from discord import app_commands

from src.rpg.assets import get_ui_asset_url
from src.rpg.data import DUNGEONS, MINE_ZONES, RARITIES, SLOTS
from src.rpg.embeds import (
    build_achievements_embed,
    build_class_embed,
    build_combat_embed,
    build_daily_quests_embed,
    build_dungeon_list_embed,
    build_enhance_result_embed,
    build_equipment_card_embed,
    build_expedition_embed,
    build_forge_embed,
    build_help_embed,
    build_leaderboard_embed,
    build_mine_result_embed,
    build_profile_embed,
    build_rebirth_embed,
    build_welcome_class_embed,
    build_world_boss_embed,
)
from src.rpg.engine import RPGEngine, RPGError
from src.rpg.views import (
    AchievementView,
    BagView,
    ClassHallView,
    ClassSelectView,
    CombatView,
    DailyQuestView,
    DungeonHallView,
    ExpeditionView,
    ForgeView,
    LeaderboardView,
    MineView,
    ProfileHubView,
    RebirthView,
    ShopView,
    WorldBossView,
)


def create_rpg_commands(engine: RPGEngine) -> List[app_commands.Command]:
    """Create and return all top-level RPG slash commands bound to `engine`."""

    @app_commands.command(name="start", description="踏上冒險旅程！建立你的 RPG 角色並選擇職業")
    async def rpg_start(interaction: discord.Interaction) -> None:
        existing = engine.db.get_player(str(interaction.user.id))
        if existing is not None:
            player = engine.require_player(str(interaction.user.id), interaction.user.display_name)
            stats = engine.compute_stats(player)
            equipped = engine.db.get_equipment(player.user_id, equipped_only=True)
            rank, total = engine.db.get_player_rank(player.user_id, "power")
            embed = build_profile_embed(
                player,
                stats,
                equipped,
                engine.next_stamina_in(player),
                rank,
                total,
                avatar_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
            )
            await interaction.response.send_message(
                content="✨ 你已經擁有冒險者檔案，以下為你的最新角色面板：",
                embed=embed,
                view=ProfileHubView(engine, interaction.user.id),
            )
            return

        embed = build_welcome_class_embed()
        view = ClassSelectView(engine, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="profile", description="查看自己或隊友的 RPG 角色面板、戰力、裝備與主城按鈕")
    @app_commands.describe(member="（選填）選擇想查看的 Discord 成員，不填則看自己")
    async def rpg_profile(
        interaction: discord.Interaction, member: Optional[discord.User] = None
    ) -> None:
        target = member or interaction.user
        try:
            player = engine.require_player(str(target.id), target.display_name)
        except RPGError as exc:
            msg = (
                f"⚠️ **{target.display_name}** 還沒建立 RPG 角色！"
                if target.id != interaction.user.id
                else f"⚠️ {exc}"
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        stats = engine.compute_stats(player)
        equipped = engine.db.get_equipment(player.user_id, equipped_only=True)
        rank, total = engine.db.get_player_rank(player.user_id, "power")
        embed = build_profile_embed(
            player,
            stats,
            equipped,
            engine.next_stamina_in(player),
            rank,
            total,
            avatar_url=target.display_avatar.url if target.display_avatar else None,
        )
        view = ProfileHubView(engine, interaction.user.id) if target.id == interaction.user.id else None
        if view is not None:
            await interaction.response.send_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mine", description="前往礦場挖礦採集礦石、強化石與隨機奇遇")
    @app_commands.describe(zone="（選填）選擇礦區，不填則自動前往目前解鎖的最高礦區")
    async def rpg_mine(
        interaction: discord.Interaction, zone: Optional[str] = None
    ) -> None:
        try:
            res = engine.mine(
                str(interaction.user.id),
                display_name=interaction.user.display_name,
                zone_id=zone,
            )
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        embed = build_mine_result_embed(res)
        view = MineView(engine, interaction.user.id, res["zone"]["id"])
        await interaction.response.send_message(embed=embed, view=view)

    @rpg_mine.autocomplete("zone")
    async def mine_zone_autocomplete(
        _interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        q = current.lower()
        choices = []
        for z in MINE_ZONES:
            label = f"{z['emoji']} {z['name']} (Lv.{z['min_level']} / T{z['min_pickaxe']}鎬)"
            if not q or q in label.lower() or q in z["id"].lower():
                choices.append(app_commands.Choice(name=label[:100], value=z["id"]))
        return choices[:25]

    @app_commands.command(name="dungeon", description="開啟副本大廳，或直接進入指定副本與難度展開戰鬥")
    @app_commands.describe(
        dungeon="（選填）選擇要挑戰的副本，不填則開啟副本大廳",
        difficulty="（選填）選擇難度：普通 / 困難 / 地獄",
    )
    @app_commands.choices(
        difficulty=[
            app_commands.Choice(name="🟢 普通 (體力 12 / 獎勵 x1.0)", value="normal"),
            app_commands.Choice(name="🟠 困難 (體力 16 / 獎勵 x1.9)", value="hard"),
            app_commands.Choice(name="🔴 地獄 (體力 20 / 獎勵 x3.3)", value="hell"),
        ]
    )
    async def rpg_dungeon(
        interaction: discord.Interaction,
        dungeon: Optional[str] = None,
        difficulty: Optional[str] = None,
    ) -> None:
        try:
            player = engine.require_player(str(interaction.user.id), interaction.user.display_name)
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        if not dungeon:
            clears = engine.db.get_dungeon_clears(player.user_id)
            embed = build_dungeon_list_embed(player, clears)
            view = DungeonHallView(engine, interaction.user.id)
            await interaction.response.send_message(embed=embed, view=view)
            return

        try:
            session = engine.start_dungeon_combat(
                str(interaction.user.id),
                dungeon_id=dungeon,
                difficulty=difficulty or "normal",
                display_name=interaction.user.display_name,
            )
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        player = engine.require_player(str(interaction.user.id))
        embed = build_combat_embed(session, player)
        view = CombatView(engine, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @rpg_dungeon.autocomplete("dungeon")
    async def dungeon_autocomplete(
        _interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        q = current.lower()
        choices = []
        for d in DUNGEONS:
            label = f"{d['emoji']} {d['name']} (建議 Lv.{d['rec_level']} / T{d['gear_tier']} 裝)"
            if not q or q in label.lower() or q in d["id"].lower():
                choices.append(app_commands.Choice(name=label[:100], value=d["id"]))
        return choices[:25]

    @app_commands.command(name="abyss", description="挑戰無限爬塔「無盡深淵」（每 5 層守門王大獎與排行榜）")
    @app_commands.describe(floor="（選填）指定要挑戰的層數，不填則自動挑戰目前下一層")
    async def rpg_abyss(
        interaction: discord.Interaction, floor: Optional[int] = None
    ) -> None:
        try:
            session = engine.start_abyss_combat(
                str(interaction.user.id),
                floor=floor,
                display_name=interaction.user.display_name,
            )
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        player = engine.require_player(str(interaction.user.id))
        embed = build_combat_embed(session, player)
        view = CombatView(engine, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="boss", description="查看並共同討伐「伺服器世界王」（全服共享血條、全員領獎）")
    async def rpg_boss(interaction: discord.Interaction) -> None:
        try:
            player = engine.require_player(str(interaction.user.id), interaction.user.display_name)
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        boss = engine.get_or_spawn_world_boss()
        ranks = engine.db.get_world_boss_rankings(boss.id, limit=5)
        embed = build_world_boss_embed(boss, ranks, player)
        view = WorldBossView(engine)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="shop", description="開啟 RPG 冒險商店（常駐物資、限時神秘商店、秘寶抽箱、出售）")
    @app_commands.choices(
        tab=[
            app_commands.Choice(name="🏪 常駐物資商店", value="supply"),
            app_commands.Choice(name="✨ 限時折扣神秘商店", value="mystery"),
            app_commands.Choice(name="🎁 星界秘寶抽箱", value="gacha"),
            app_commands.Choice(name="💰 回收與礦石出售", value="sell"),
        ]
    )
    async def rpg_shop(
        interaction: discord.Interaction, tab: Optional[str] = "supply"
    ) -> None:
        try:
            player = engine.require_player(str(interaction.user.id), interaction.user.display_name)
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        view = ShopView(engine, interaction.user.id, tab=tab or "supply")
        embed = view.render_embed(player)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="bag", description="開啟背包裝備與礦石材料庫（支援穿戴、鎖定、一鍵最佳裝備）")
    @app_commands.choices(
        tab=[
            app_commands.Choice(name="🛡️ 裝備清單", value="gear"),
            app_commands.Choice(name="📦 礦石與材料", value="materials"),
        ]
    )
    async def rpg_bag(
        interaction: discord.Interaction, tab: Optional[str] = "gear"
    ) -> None:
        try:
            player = engine.require_player(str(interaction.user.id), interaction.user.display_name)
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        view = BagView(engine, interaction.user.id, tab=tab or "gear")
        embed = view.render_embed(player)
        await interaction.response.send_message(embed=embed, view=view)

    def _owned_gear_choices(user_id: str, current: str) -> List[app_commands.Choice[int]]:
        gear = engine.db.get_equipment(user_id)
        gear_sorted = sorted(gear, key=lambda e: (e.is_equipped, e.power_score), reverse=True)
        q = current.strip().lower()
        choices: List[app_commands.Choice[int]] = []
        for eq in gear_sorted:
            rdef = RARITIES[eq.rarity]
            smeta = SLOTS[eq.slot]
            enh = f" +{eq.enhance_level}" if eq.enhance_level > 0 else ""
            eq_tag = "★" if eq.is_equipped else ""
            label = f"#{eq.id} {eq_tag}{smeta['emoji']}[{rdef['name']}] {eq.name}{enh} (戰力{eq.power_score:,})"
            if not q or q in label.lower() or q == str(eq.id):
                choices.append(app_commands.Choice(name=label[:100], value=eq.id))
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(name="equip", description="穿戴指定編號裝備，不填則一鍵自動穿戴各部位最強裝備")
    @app_commands.describe(item_id="（選填）背包內的裝備數字編號，留空則自動穿戴最佳裝備")
    async def rpg_equip(
        interaction: discord.Interaction, item_id: Optional[int] = None
    ) -> None:
        try:
            if item_id is None:
                equipped, stats = engine.auto_equip_best(str(interaction.user.id))
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
                    await interaction.response.send_message(embed=card)
                else:
                    await interaction.response.send_message(
                        f"✨ 已自動為你穿戴 **{len(equipped)} 件**各部位最強裝備！目前總戰力：**`{stats.combat_power:,}`**"
                    )
            else:
                item, stats = engine.equip_item(str(interaction.user.id), item_id)
                card = build_equipment_card_embed(
                    item,
                    title=f"🛡️ 已成功穿戴 {item.name}！",
                    subtitle=f"🏆 目前角色總戰力：**`{stats.combat_power:,}`**",
                )
                await interaction.response.send_message(embed=card)
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)

    @rpg_equip.autocomplete("item_id")
    async def equip_item_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[int]]:
        return _owned_gear_choices(str(interaction.user.id), current)

    @app_commands.command(name="inspect", description="檢視並公開展示裝備圖片卡片、基礎屬性、隨機詞條與套裝效果")
    @app_commands.describe(item_id="（選填）裝備數字編號，不填則展示你目前戰力最高的穿戴裝備")
    async def rpg_inspect(
        interaction: discord.Interaction, item_id: Optional[int] = None
    ) -> None:
        try:
            player = engine.require_player(str(interaction.user.id), interaction.user.display_name)
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        if item_id is not None:
            item = engine.db.get_equipment_by_id(player.user_id, item_id)
            if item is None:
                await interaction.response.send_message(
                    f"⚠️ 在你的背包中找不到編號 `#{item_id}` 的裝備。", ephemeral=True
                )
                return
        else:
            equipped = engine.db.get_equipment(player.user_id, equipped_only=True)
            pool = equipped if equipped else engine.db.get_equipment(player.user_id)
            if not pool:
                await interaction.response.send_message(
                    "⚠️ 你目前還沒有任何裝備，快去 `/dungeon`、`/forge` 或 `/shop` 獲取裝備吧！",
                    ephemeral=True,
                )
                return
            item = max(pool, key=lambda eq: eq.power_score)

        card = build_equipment_card_embed(
            item,
            author_name=f"{player.display_name} 的裝備圖鑑",
        )
        await interaction.response.send_message(embed=card)

    @rpg_inspect.autocomplete("item_id")
    async def inspect_item_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[int]]:
        return _owned_gear_choices(str(interaction.user.id), current)

    @app_commands.command(name="forge", description="進入鐵匠鋪（鍛造套裝、升級礦鎬、裝備強化 +1~+15、分解裝備）")
    @app_commands.describe(
        enhance_id="（選填）直接強化指定裝備編號",
        use_protect="（選填）+10 以上強化失敗時是否消耗強化保護卷軸防止掉階",
    )
    async def rpg_forge(
        interaction: discord.Interaction,
        enhance_id: Optional[int] = None,
        use_protect: bool = False,
    ) -> None:
        try:
            player = engine.require_player(str(interaction.user.id), interaction.user.display_name)
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        if enhance_id is not None:
            try:
                res = engine.enhance_equipment(
                    player.user_id, enhance_id, use_protect=use_protect
                )
            except RPGError as exc:
                await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
                return

            await interaction.response.send_message(embed=build_enhance_result_embed(res))
            return

        inv = engine.db.get_inventory(player.user_id)
        eq = engine.db.get_equipment(player.user_id, equipped_only=True)
        embed = build_forge_embed(player, inv, eq)
        view = ForgeView(engine, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @rpg_forge.autocomplete("enhance_id")
    async def forge_enhance_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[int]]:
        return _owned_gear_choices(str(interaction.user.id), current)

    @app_commands.command(name="daily", description="每日連續簽到與領取每日／每週任務獎勵")
    async def rpg_daily(interaction: discord.Interaction) -> None:
        try:
            player = engine.require_player(str(interaction.user.id), interaction.user.display_name)
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        qst = engine.get_quests_status(player.user_id)
        embed = build_daily_quests_embed(player, qst, engine.today_key())
        view = DailyQuestView(engine, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="expedition", description="派遣角色進行離線冒險探索（重啟亦持續計時領取豐厚收益）")
    async def rpg_expedition(interaction: discord.Interaction) -> None:
        try:
            player = engine.require_player(str(interaction.user.id), interaction.user.display_name)
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        active = engine.db.get_expedition(player.user_id)
        embed = build_expedition_embed(player, active, engine.now())
        view = ExpeditionView(engine, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="leaderboard", description="查看伺服器 6 大 RPG 排行榜（戰力、等級轉生、深淵、財富、礦神、世界王）")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="⚔️ 戰力排行榜", value="power"),
            app_commands.Choice(name="⭐ 等級與轉生榜", value="level"),
            app_commands.Choice(name="🗼 無盡深淵層數榜", value="abyss"),
            app_commands.Choice(name="💰 富豪財富榜", value="gold"),
            app_commands.Choice(name="⛏️ 傳奇礦神榜", value="mining"),
            app_commands.Choice(name="🐉 世界王傷害貢獻榜", value="boss"),
        ]
    )
    async def rpg_leaderboard(
        interaction: discord.Interaction, category: Optional[str] = "power"
    ) -> None:
        cat = category or "power"
        entries = engine.db.get_leaderboard(cat, limit=10)
        rank, total = engine.db.get_player_rank(str(interaction.user.id), cat)
        embed = build_leaderboard_embed(cat, entries, rank, total)
        view = LeaderboardView(engine, category=cat)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="achievements", description="查看成就與永久屬性加成圖鑑，並切換顯示稱號")
    async def rpg_achievements(interaction: discord.Interaction) -> None:
        try:
            player = engine.require_player(str(interaction.user.id), interaction.user.display_name)
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        engine.check_achievements(player)
        engine.db.save_player(player)
        unlocked = engine.db.get_achievements(player.user_id)
        embed = build_achievements_embed(player, unlocked)
        view = AchievementView(engine, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="class", description="職業殿堂：進行 Lv.30 二轉 / Lv.70 三轉覺醒，或使用轉職徽章切換職業")
    async def rpg_class(interaction: discord.Interaction) -> None:
        try:
            player = engine.require_player(str(interaction.user.id), interaction.user.display_name)
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        inv = engine.db.get_inventory(player.user_id)
        embed = build_class_embed(player, inv)
        view = ClassHallView(engine, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="rebirth", description="滿級 Lv.100 星界轉生／飛升（保留裝備與進度，永久獲得全屬性倍率加成）")
    async def rpg_rebirth(interaction: discord.Interaction) -> None:
        try:
            player = engine.require_player(str(interaction.user.id), interaction.user.display_name)
        except RPGError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return

        embed = build_rebirth_embed(player)
        view = RebirthView(engine, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="help", description="查看星界紀元 RPG 完整玩法與指令介紹")
    async def rpg_help(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_help_embed())

    return [
        rpg_start,
        rpg_profile,
        rpg_mine,
        rpg_dungeon,
        rpg_abyss,
        rpg_boss,
        rpg_shop,
        rpg_bag,
        rpg_equip,
        rpg_inspect,
        rpg_forge,
        rpg_daily,
        rpg_expedition,
        rpg_leaderboard,
        rpg_achievements,
        rpg_class,
        rpg_rebirth,
        rpg_help,
    ]


def register_rpg_commands(
    tree: app_commands.CommandTree, engine: RPGEngine
) -> List[app_commands.Command]:
    """Attach all top-level RPG slash commands onto a Discord CommandTree."""
    if tree.get_command("rpg") is not None:
        tree.remove_command("rpg")
    commands = create_rpg_commands(engine)
    for cmd in commands:
        if tree.get_command(cmd.name) is not None:
            tree.remove_command(cmd.name)
        tree.add_command(cmd)
    return commands
