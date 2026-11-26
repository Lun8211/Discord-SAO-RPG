"""All 22 SAO Aincrad top-level Discord Slash Commands (preserving /p in src/memes/ untouched)."""

from __future__ import annotations

import discord
from discord import app_commands

from src.rpg.engine import GameError, RPGEngine
from src.rpg.ui.embeds_core import (
    build_bag_embed,
    build_error_embed,
    build_help_embed,
    build_leaderboard_embed,
    build_monument_embed,
    build_profile_embed,
    build_skills_embed,
    build_start_embed,
    build_yui_embed,
)
from src.rpg.ui.embeds_party import (
    build_coop_raid_embed,
    build_duel_embed,
    build_party_lobby_embed,
    build_world_boss_embed,
)
from src.rpg.ui.embeds_social import (
    build_cooking_embed,
    build_guild_embed,
    build_market_embed,
    build_quests_embed,
    build_shop_embed,
    build_workshop_embed,
)
from src.rpg.ui.embeds_tower import (
    build_argo_intel_embed,
    build_combat_embed,
    build_roguelike_embed,
    build_tower_embed,
)
from src.rpg.ui.views_core import ProfileView
from src.rpg.ui.views_party import CoopRaidView, DuelView, PartyLobbyView, WorldBossView
from src.rpg.ui.views_social import DailyQuestView, LeaderboardView, ShopView
from src.rpg.ui.views_tower import (
    ChestView,
    RoguelikeView,
    SoloCombatView,
    TowerFloorView,
)


async def _send_error(interaction: discord.Interaction, title: str, exc: Exception) -> None:
    embed = build_error_embed(title, str(exc))
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


def register_rpg_commands(tree: app_commands.CommandTree, engine: RPGEngine) -> None:
    """Register all 22 top-level SAO Aincrad slash commands on the Discord CommandTree."""

    @tree.command(name="start", description="Link Start！登入艾恩葛朗特第 1 層起始之鎮並創建角色")
    @app_commands.choices(
        weapon_style=[
            app_commands.Choice(name="⚔️ 單手直劍 (sword)", value="sword"),
            app_commands.Choice(name="🗡️ 細劍 (rapier)", value="rapier"),
            app_commands.Choice(name="🗾 太刀 (katana)", value="katana"),
            app_commands.Choice(name="🪓 雙手斧 (axe)", value="axe"),
            app_commands.Choice(name="🔨 單手槌盾 (mace)", value="mace"),
            app_commands.Choice(name="✝️ 單手劍盾 (holy)", value="holy"),
            app_commands.Choice(name="🌙 鐮刀 (scythe)", value="scythe"),
            app_commands.Choice(name="🔪 雙短刀 (dagger)", value="dagger"),
        ],
        mode=[
            app_commands.Choice(name="🛡️ 標準模式（Standard：倒地可救援）", value="standard"),
            app_commands.Choice(name="💀 硬派死亡遊戲（Hardcore：一命殞落）", value="hardcore"),
        ],
    )
    async def cmd_start(
        interaction: discord.Interaction,
        weapon_style: str = "sword",
        mode: str = "standard",
        name: str | None = None,
    ) -> None:
        try:
            display = name or interaction.user.display_name
            res = engine.create_character(
                str(interaction.user.id), display, weapon_style=weapon_style, mode=mode
            )
            await interaction.response.send_message(
                embed=build_start_embed(res),
                view=ProfileView(engine, str(interaction.user.id)),
            )
        except GameError as exc:
            await _send_error(interaction, "Link Start 失敗", exc)

    @tree.command(name="profile", description="檢視角色狀態、四軸抗性、生命之碑與結衣終端機")
    @app_commands.choices(
        panel=[
            app_commands.Choice(name="🪪 角色面板", value="profile"),
            app_commands.Choice(name="🪦 黑鐵宮生命之碑", value="monument"),
            app_commands.Choice(name="👧 結衣終端機紀錄", value="yui"),
        ]
    )
    async def cmd_profile(interaction: discord.Interaction, panel: str = "profile") -> None:
        uid = str(interaction.user.id)
        try:
            if panel == "monument":
                data = engine.get_monument_of_life(limit=10)
                await interaction.response.send_message(embed=build_monument_embed(data))
            elif panel == "yui":
                data = engine.get_yui_logs(uid)
                await interaction.response.send_message(embed=build_yui_embed(data))
            else:
                prof = engine.get_profile(uid)
                await interaction.response.send_message(
                    embed=build_profile_embed(prof),
                    view=ProfileView(engine, uid),
                )
        except GameError as exc:
            await _send_error(interaction, "角色資訊查詢失敗", exc)

    @tree.command(name="tower", description="艾恩葛朗特 100 層爬塔總覽、轉移門、探索、秘境與地下迷宮")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="🏰 樓層總覽與轉移門", value="info"),
            app_commands.Choice(name="🧭 探索目前樓層", value="explore"),
            app_commands.Choice(name="🌀 傳送至指定樓層", value="teleport"),
            app_commands.Choice(name="🏘️ 返回圈內安全區", value="town"),
            app_commands.Choice(name="🌫️ 進入／探索秘境（瘴氣）", value="secret_realm"),
            app_commands.Choice(name="🏛️ 黑鐵宮地下迷宮 Roguelike", value="roguelike"),
        ]
    )
    async def cmd_tower(
        interaction: discord.Interaction,
        action: str = "info",
        floor: int | None = None,
        steps: int = 1,
    ) -> None:
        uid = str(interaction.user.id)
        try:
            if action == "teleport":
                target = floor or 1
                engine.teleport_floor(uid, target)
                info = engine.get_floor_info(target, user_id=uid)
                await interaction.response.send_message(
                    embed=build_tower_embed(info),
                    view=TowerFloorView(engine, uid, target),
                )
            elif action == "town":
                res = engine.travel_zone(uid, "town")
                await interaction.response.send_message(res["message"])
            elif action == "explore":
                res = engine.explore_floor(uid, steps=steps)
                if res.get("in_combat"):
                    await interaction.response.send_message(
                        embed=build_combat_embed(res),
                        view=SoloCombatView(engine, uid),
                    )
                elif res.get("chest"):
                    await interaction.response.send_message(
                        embed=build_combat_embed(res),
                        view=ChestView(engine, uid),
                    )
                else:
                    info = engine.get_floor_info(int(res["floor"]), user_id=uid)
                    info["flavor_desc"] = res["message"]
                    await interaction.response.send_message(
                        embed=build_tower_embed(info),
                        view=TowerFloorView(engine, uid, int(res["floor"])),
                    )
            elif action == "secret_realm":
                prof = engine.get_profile(uid)
                if prof["zone"] != "secret_realm":
                    engine.enter_secret_realm(uid, action="enter")
                res = engine.enter_secret_realm(uid, action="explore")
                await interaction.response.send_message(res["message"])
            elif action == "roguelike":
                res = engine.start_roguelike(uid)
                await interaction.response.send_message(
                    embed=build_roguelike_embed(res),
                    view=RoguelikeView(engine, uid),
                )
            else:
                prof = engine.get_profile(uid)
                target_f = floor if floor is not None else int(prof["current_floor"])
                info = engine.get_floor_info(target_f, user_id=uid)
                await interaction.response.send_message(
                    embed=build_tower_embed(info),
                    view=TowerFloorView(engine, uid, target_f),
                )
        except GameError as exc:
            await _send_error(interaction, "爬塔指令受阻", exc)

    @tree.command(name="party", description="真人多人組隊大廳、大型攻略團、Switch 共鬥、集體傳送與瀕死救援")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="🚩 建立真人隊伍／攻略團", value="create"),
            app_commands.Choice(name="🤝 加入指定隊伍", value="join"),
            app_commands.Choice(name="🚪 進入頭目房", value="enter_room"),
            app_commands.Choice(name="⚔️ 全員開戰（多人同步）", value="start_raid"),
            app_commands.Choice(name="🌀 隊伍集體傳送", value="group_teleport"),
            app_commands.Choice(name="💎 轉移水晶救援瀕死隊友", value="rescue"),
        ],
        boss_mode=[
            app_commands.Choice(name="⚔️ 普通模式 (normal)", value="normal"),
            app_commands.Choice(name="👑 首殺挑戰 (first_kill)", value="first_kill"),
            app_commands.Choice(name="🔥 團隊首領 (team_boss)", value="team_boss"),
        ],
        role=[
            app_commands.Choice(name="🛡️ 前排坦 (tank)", value="tank"),
            app_commands.Choice(name="⚔️ 輸出 (dps)", value="dps"),
            app_commands.Choice(name="💥 破防 (breaker)", value="breaker"),
            app_commands.Choice(name="💚 輔助 (support)", value="support"),
        ],
    )
    async def cmd_party(
        interaction: discord.Interaction,
        action: str = "create",
        floor: int = 1,
        boss_mode: str = "normal",
        party_id: str | None = None,
        role: str = "dps",
        raid_alliance: bool = False,
        target_user: discord.User | None = None,
    ) -> None:
        uid = str(interaction.user.id)
        try:
            if action == "create":
                max_sz = 12 if raid_alliance else 6
                res = engine.create_party(
                    uid, floor=floor, boss_mode=boss_mode, max_size=max_sz, is_raid_alliance=raid_alliance
                )
                await interaction.response.send_message(
                    embed=build_party_lobby_embed(res),
                    view=PartyLobbyView(engine, str(res["party_id"])),
                )
            elif action == "join":
                if not party_id:
                    raise GameError("請輸入欲加入的隊伍編號 party_id。", code="MISSING_PARTY_ID")
                res = engine.join_party(party_id, uid, role=role)
                await interaction.response.send_message(
                    embed=build_party_lobby_embed(res),
                    view=PartyLobbyView(engine, party_id),
                )
            elif action == "enter_room":
                active_p = engine.db.get_user_active_party(uid)
                pid = party_id or (active_p.party_id if active_p is not None else "")
                res = engine.enter_boss_room(pid, uid)
                await interaction.response.send_message(
                    embed=build_party_lobby_embed(res),
                    view=PartyLobbyView(engine, pid),
                )
            elif action == "start_raid":
                active_p = engine.db.get_user_active_party(uid)
                pid = party_id or (active_p.party_id if active_p is not None else "")
                res = engine.start_party_raid(pid, uid)
                await interaction.response.send_message(
                    embed=build_coop_raid_embed(res),
                    view=CoopRaidView(engine, str(res["raid_id"])),
                )
            elif action == "group_teleport":
                active_p = engine.db.get_user_active_party(uid)
                pid = party_id or (active_p.party_id if active_p is not None else "")
                res = engine.party_group_teleport(pid, uid, floor)
                await interaction.response.send_message(res["message"])
            elif action == "rescue":
                if target_user is None:
                    raise GameError("請指定欲使用轉移水晶救援的瀕死隊友！", code="MISSING_TARGET_USER")
                res = engine.rescue_downed_player(uid, str(target_user.id))
                await interaction.response.send_message(res["message"])
        except GameError as exc:
            await _send_error(interaction, "多人組隊操作失敗", exc)

    @tree.command(name="boss", description="挑戰樓層守關頭目、全服世界王、英雄連戰、夢魘層或查閱阿爾狗情報")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="👑 單人頭目房 (normal)", value="normal"),
            app_commands.Choice(name="🏆 首殺版頭目 (first_kill)", value="first_kill"),
            app_commands.Choice(name="🌍 攻擊全服世界王", value="world_boss"),
            app_commands.Choice(name="🐭 阿爾狗頭目情報屋", value="argo"),
            app_commands.Choice(name="🔥 英雄頭目連戰 (Boss Rush)", value="boss_rush"),
            app_commands.Choice(name="🌑 艾恩葛朗特夢魘 F101+", value="nightmare"),
        ]
    )
    async def cmd_boss(
        interaction: discord.Interaction,
        mode: str = "normal",
        floor: int | None = None,
    ) -> None:
        uid = str(interaction.user.id)
        try:
            if mode == "world_boss":
                res = engine.attack_floor_world_boss(uid)
                await interaction.response.send_message(
                    embed=build_world_boss_embed(res),
                    view=WorldBossView(engine),
                )
            elif mode == "argo":
                intel = engine.get_argo_intel(user_id=uid, floor=floor)
                await interaction.response.send_message(embed=build_argo_intel_embed(intel))
            elif mode == "boss_rush":
                res = engine.start_boss_rush(uid)
                await interaction.response.send_message(
                    embed=build_combat_embed(res),
                    view=SoloCombatView(engine, uid),
                )
            elif mode == "nightmare":
                nf = floor if (floor is not None and floor > 100) else 101
                res = engine.enter_nightmare_floor(uid, nf)
                await interaction.response.send_message(
                    embed=build_combat_embed(res),
                    view=SoloCombatView(engine, uid),
                )
            else:
                res = engine.start_floor_boss(uid, floor=floor, mode=mode)
                await interaction.response.send_message(
                    embed=build_combat_embed(res),
                    view=SoloCombatView(engine, uid),
                )
        except GameError as exc:
            await _send_error(interaction, "頭目挑戰受阻", exc)

    @tree.command(name="skills", description="檢視／切換武器流派、配置劍技欄位、分配屬性與天賦或覺醒獨有劍技")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="📜 檢視劍技與天賦", value="view"),
            app_commands.Choice(name="⚔️ 切換武器流派", value="style"),
            app_commands.Choice(name="✨ 覺醒獨有劍技（二刀流／神聖劍）", value="unique"),
            app_commands.Choice(name="🌟 強化武器天賦節點", value="talent"),
            app_commands.Choice(name="🔄 城鎮免費重置天賦", value="respec"),
            app_commands.Choice(name="📈 分配基礎屬性點", value="stat"),
        ]
    )
    async def cmd_skills(
        interaction: discord.Interaction,
        action: str = "view",
        target: str | None = None,
        amount: int = 1,
    ) -> None:
        uid = str(interaction.user.id)
        try:
            if action == "style" and target:
                res = engine.switch_weapon_style(uid, target)
                await interaction.response.send_message(res["message"])
            elif action == "unique" and target:
                res = engine.unlock_unique_skill(uid, target)
                await interaction.response.send_message(res["message"])
            elif action == "talent" and target:
                res = engine.allocate_talent(uid, target)
                await interaction.response.send_message(res["message"])
            elif action == "respec":
                res = engine.respec_talents(uid)
                await interaction.response.send_message(res["message"])
            elif action == "stat" and target:
                res = engine.allocate_stats(uid, {target: amount})
                await interaction.response.send_message(res["message"])
            else:
                prof = engine.get_profile(uid)
                await interaction.response.send_message(embed=build_skills_embed(prof, engine.content))
        except GameError as exc:
            await _send_error(interaction, "劍技／天賦操作失敗", exc)

    @tree.command(name="bag", description="開啟裝備背包、消耗品快取袋、待領取信箱與戰利品過濾設定")
    async def cmd_bag(interaction: discord.Interaction, claim_mailbox: bool = False) -> None:
        uid = str(interaction.user.id)
        try:
            if claim_mailbox:
                res = engine.claim_pending_loot(uid)
                await interaction.response.send_message(res["message"])
                return
            prof = engine.get_profile(uid)
            await interaction.response.send_message(
                embed=build_bag_embed(prof, engine.content),
                view=ProfileView(engine, uid),
            )
        except GameError as exc:
            await _send_error(interaction, "背包開啟失敗", exc)

    @tree.command(name="equip", description="穿戴裝備、鎖定裝備、儲存或一鍵套用裝備方案（1～5）")
    async def cmd_equip(
        interaction: discord.Interaction,
        item_uid: int | None = None,
        toggle_lock: bool = False,
        loadout_slot: int | None = None,
        save_name: str | None = None,
    ) -> None:
        uid = str(interaction.user.id)
        try:
            if loadout_slot is not None:
                res = (
                    engine.save_loadout(uid, loadout_slot, save_name)
                    if save_name
                    else engine.apply_loadout(uid, loadout_slot)
                )
                await interaction.response.send_message(res["message"])
            elif item_uid is not None:
                res = engine.toggle_lock_item(uid, item_uid) if toggle_lock else engine.equip_item(uid, item_uid)
                await interaction.response.send_message(res["message"])
            else:
                prof = engine.get_profile(uid)
                await interaction.response.send_message(embed=build_bag_embed(prof, engine.content))
        except GameError as exc:
            await _send_error(interaction, "裝備操作失敗", exc)

    @tree.command(name="inspect", description="檢視其他攻略者的艾恩葛朗特角色面板與戰力配置")
    async def cmd_inspect(interaction: discord.Interaction, target: discord.User | None = None) -> None:
        target_uid = str((target or interaction.user).id)
        try:
            prof = engine.get_profile(target_uid)
            await interaction.response.send_message(embed=build_profile_embed(prof))
        except GameError as exc:
            await _send_error(interaction, "檢視玩家失敗", exc)

    @tree.command(name="forge", description="莉茲貝特工坊：鍛造裝備、強化 +1～+15、魔石洗詞綴與結晶融合")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="🔨 鍛造配方 (craft)", value="craft"),
            app_commands.Choice(name="✨ 強化裝備 +1~+15 (enhance)", value="enhance"),
            app_commands.Choice(name="💎 魔石重鑄詞綴 (stone)", value="stone"),
            app_commands.Choice(name="⚗️ 結晶與素材融合 (fuse)", value="fuse"),
        ]
    )
    async def cmd_forge(
        interaction: discord.Interaction,
        action: str = "craft",
        recipe_id: str | None = None,
        item_uid: int | None = None,
        stone_id: str = "reroll_stone",
        use_protection: bool = False,
    ) -> None:
        uid = str(interaction.user.id)
        try:
            if action == "enhance":
                if item_uid is None:
                    raise GameError("請輸入欲強化的裝備編號 item_uid。", code="MISSING_ITEM_UID")
                res = engine.enhance_equipment(uid, item_uid, use_protection=use_protection)
                await interaction.response.send_message(embed=build_workshop_embed("裝備強化", res))
            elif action == "stone":
                if item_uid is None:
                    raise GameError("請輸入欲使用魔石的裝備編號 item_uid。", code="MISSING_ITEM_UID")
                res = engine.apply_magic_stone(uid, item_uid, stone_id)
                await interaction.response.send_message(embed=build_workshop_embed("魔石洗煉", res))
            elif action == "fuse":
                rid = recipe_id or "fuse_bright_crystal"
                res = engine.fuse_items(uid, rid)
                await interaction.response.send_message(embed=build_workshop_embed("結晶融合", res))
            else:
                rid = recipe_id or "forge_t1_gear"
                res = engine.forge_craft(uid, rid)
                await interaction.response.send_message(embed=build_workshop_embed("鍛造打造", res))
        except GameError as exc:
            await _send_error(interaction, "工坊操作失敗", exc)

    @tree.command(name="cook", description="烹調艾恩葛朗特增益料理、燉煮隊伍／公會一大鍋或領取大鍋料理")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="🍳 烹調個人增益料理", value="dish"),
            app_commands.Choice(name="🥘 架起共享一大鍋", value="stew"),
            app_commands.Choice(name="🥣 領取共享一大鍋", value="claim"),
        ]
    )
    async def cmd_cook(
        interaction: discord.Interaction,
        action: str = "dish",
        recipe_id: str = "cook_boar_roast",
        scope_or_stew_id: str = "",
        timing_perfect: bool = False,
    ) -> None:
        uid = str(interaction.user.id)
        try:
            if action == "stew":
                res = engine.start_big_pot_stew(uid, recipe_id, scope_or_stew_id)
            elif action == "claim":
                res = engine.claim_stew(uid, scope_or_stew_id)
            else:
                res = engine.cook_dish(uid, recipe_id, timing_perfect=timing_perfect)
            await interaction.response.send_message(embed=build_cooking_embed(res))
        except GameError as exc:
            await _send_error(interaction, "料理操作失敗", exc)

    @tree.command(name="mine", description="前往解鎖樓層礦脈採集鍛造礦材（含第 55 層水晶石英鑄塊）")
    async def cmd_mine(interaction: discord.Interaction, floor: int | None = None) -> None:
        uid = str(interaction.user.id)
        try:
            res = engine.mine_gather(uid, floor=floor)
            await interaction.response.send_message(res["message"])
        except GameError as exc:
            await _send_error(interaction, "採礦受阻", exc)

    @tree.command(name="shop", description="起始之鎮補給商店：購買回復藥水、四大 SAO 水晶或抽取秘寶箱")
    async def cmd_shop(
        interaction: discord.Interaction,
        item_id: str | None = None,
        qty: int = 1,
        gacha_count: int = 0,
    ) -> None:
        uid = str(interaction.user.id)
        try:
            if gacha_count > 0:
                res = engine.gacha_pull(uid, chest_type="standard", count=gacha_count)
                await interaction.response.send_message(embed=build_shop_embed(res), view=ShopView(engine, uid))
            elif item_id:
                res = engine.buy_shop_item(uid, item_id, qty=qty)
                await interaction.response.send_message(embed=build_shop_embed(res), view=ShopView(engine, uid))
            else:
                prof = engine.get_profile(uid)
                res = {"message": f"歡迎光臨艾恩葛朗特補給商店！點擊下方按鈕快速購買回復藥水或四大水晶（目前持有 {prof['col']:,} 柯爾）。", "col_remaining": prof["col"]}
                await interaction.response.send_message(embed=build_shop_embed(res), view=ShopView(engine, uid))
        except GameError as exc:
            await _send_error(interaction, "商店交易失敗", exc)

    @tree.command(name="market", description="艾恩葛朗特玩家交易市集（檢索雙詞綴、原子託管上架／購買／下架）")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="🔎 搜尋市集商品", value="search"),
            app_commands.Choice(name="📤 上架裝備或道具", value="list"),
            app_commands.Choice(name="🤝 購買上架商品", value="buy"),
            app_commands.Choice(name="↩️ 取消下架商品", value="cancel"),
        ]
    )
    async def cmd_market(
        interaction: discord.Interaction,
        action: str = "search",
        listing_id: int | None = None,
        item_uid: int | None = None,
        item_id: str | None = None,
        qty: int = 1,
        price_col: int = 100,
        rarity: str | None = None,
        affix1: str | None = None,
        affix2: str | None = None,
    ) -> None:
        uid = str(interaction.user.id)
        try:
            if action == "list":
                res = engine.list_market_item(
                    uid, item_uid=item_uid, item_id=item_id, qty=qty, price_col=price_col
                )
            elif action == "buy":
                if listing_id is None:
                    raise GameError("請輸入欲購買的商品編號 listing_id。", code="MISSING_LISTING_ID")
                res = engine.buy_market_item(uid, listing_id)
            elif action == "cancel":
                if listing_id is None:
                    raise GameError("請輸入欲下架的商品編號 listing_id。", code="MISSING_LISTING_ID")
                res = engine.cancel_market_listing(uid, listing_id)
            else:
                res = engine.search_market(rarity=rarity, affix1=affix1, affix2=affix2)
            await interaction.response.send_message(embed=build_market_embed(res))
        except GameError as exc:
            await _send_error(interaction, "市集交易失敗", exc)

    @tree.command(name="guild", description="公會系統：創立／加入、5 階級管理、金庫貢獻、公會倉庫、集結增益與討伐戰")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="🏰 創立公會", value="create"),
            app_commands.Choice(name="🤝 加入公會", value="join"),
            app_commands.Choice(name="🚪 退出公會", value="leave"),
            app_commands.Choice(name="💰 捐獻柯爾至金庫", value="contribute"),
            app_commands.Choice(name="🚩 啟動公會集結增益", value="buff"),
            app_commands.Choice(name="⚔️ 發起限時公會討伐戰", value="raid"),
            app_commands.Choice(name="📦 存入裝備至倉庫", value="deposit"),
            app_commands.Choice(name="📤 提領倉庫裝備", value="withdraw"),
        ]
    )
    async def cmd_guild(
        interaction: discord.Interaction,
        action: str = "buff",
        name: str = "",
        tag: str = "",
        guild_or_item_id: int = 0,
        col_amount: int = 100,
    ) -> None:
        uid = str(interaction.user.id)
        try:
            if action == "create":
                res = engine.create_guild(uid, name, tag)
            elif action == "join":
                res = engine.join_guild(uid, guild_or_item_id)
            elif action == "leave":
                res = engine.leave_guild(uid)
            elif action == "contribute":
                res = engine.guild_contribute(uid, col_amount)
            elif action == "deposit":
                res = engine.guild_warehouse_deposit(uid, guild_or_item_id)
            elif action == "withdraw":
                res = engine.guild_warehouse_withdraw(uid, guild_or_item_id)
            elif action == "raid":
                res = engine.start_guild_raid(uid)
            else:
                res = engine.guild_activate_buff(uid, "rally")
            await interaction.response.send_message(embed=build_guild_embed(res))
        except GameError as exc:
            await _send_error(interaction, "公會操作失敗", exc)

    @tree.command(name="duel", description="向真人攻略者發起圈內安全決鬥（初擊勝負 50% HP 或完全勝負 1 HP）")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="⚔️ 初擊勝負（50% HP 判定）", value="first_strike"),
            app_commands.Choice(name="🔥 完全勝負（1 HP 不致死判定）", value="full_duel"),
        ]
    )
    async def cmd_duel(
        interaction: discord.Interaction,
        opponent: discord.User,
        mode: str = "first_strike",
        wager_col: int = 0,
    ) -> None:
        uid = str(interaction.user.id)
        try:
            res = engine.challenge_duel(uid, str(opponent.id), mode=mode, wager_col=wager_col)
            await interaction.response.send_message(
                embed=build_duel_embed(res),
                view=DuelView(engine, str(res["duel_id"])),
            )
        except GameError as exc:
            await _send_error(interaction, "決鬥發起失敗", exc)

    @tree.command(name="daily", description="艾恩葛朗特每日 7 日連簽與每日／每週／樓層懸賞任務總覽")
    async def cmd_daily(interaction: discord.Interaction, claim_quest_id: str | None = None) -> None:
        uid = str(interaction.user.id)
        try:
            if claim_quest_id:
                res = engine.claim_quest(uid, claim_quest_id)
                await interaction.response.send_message(res["message"])
                return
            try:
                daily_res = engine.claim_daily(uid)
                quests = engine.get_quests(uid)
                quests["message"] = daily_res["message"]
            except GameError:
                quests = engine.get_quests(uid)
            await interaction.response.send_message(
                embed=build_quests_embed(quests),
                view=DailyQuestView(engine, uid),
            )
        except GameError as exc:
            await _send_error(interaction, "每日任務失敗", exc)

    @tree.command(name="expedition", description="派遣或領取艾恩葛朗特離線偵查遠征（跨重啟時間戳計時）")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="🗺️ 派遣離線遠征", value="start"),
            app_commands.Choice(name="🎁 領取遠征獎勵", value="claim"),
        ]
    )
    async def cmd_expedition(
        interaction: discord.Interaction,
        action: str = "start",
        expedition_id: str = "exp_tolbana_patrol",
    ) -> None:
        uid = str(interaction.user.id)
        try:
            res = (
                engine.claim_expedition(uid)
                if action == "claim"
                else engine.start_expedition(uid, expedition_id)
            )
            await interaction.response.send_message(res["message"])
        except GameError as exc:
            await _send_error(interaction, "離線遠征失敗", exc)

    @tree.command(name="achievements", description="成就領取、稱號穿戴與多餘裝備永久屬性上繳（成就殿堂）")
    async def cmd_achievements(
        interaction: discord.Interaction,
        achievement_id: str | None = None,
        title_id: str | None = None,
        turnin_item_uid: int | None = None,
    ) -> None:
        uid = str(interaction.user.id)
        try:
            if turnin_item_uid is not None:
                res = engine.turn_in_achievement_gear(uid, turnin_item_uid)
            elif achievement_id:
                res = engine.claim_achievement(uid, achievement_id)
            elif title_id:
                res = engine.equip_title(uid, title_id)
            else:
                prof = engine.get_profile(uid)
                res = {
                    "message": f"🏅 目前穿戴稱號：`{prof.get('active_title') or '無'}`｜最高通關 F{prof.get('highest_cleared_floor', 0)}。"
                }
            await interaction.response.send_message(res["message"])
        except GameError as exc:
            await _send_error(interaction, "成就系統失敗", exc)

    @tree.command(name="leaderboard", description="查閱艾恩葛朗特 7 大即時排行榜（樓層／戰力／等級／世界王／公會／柯爾／連勝）")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="🏰 樓層攻略榜", value="floor"),
            app_commands.Choice(name="⚡ 綜合戰力榜", value="power"),
            app_commands.Choice(name="⭐ 等級威望榜", value="level"),
            app_commands.Choice(name="🌍 世界王傷害榜", value="world_boss"),
            app_commands.Choice(name="🛡️ 公會榮耀榜", value="guild"),
            app_commands.Choice(name="💰 柯爾富豪榜", value="col"),
            app_commands.Choice(name="🔥 生存連勝榜", value="survival"),
        ]
    )
    async def cmd_leaderboard(interaction: discord.Interaction, category: str = "floor") -> None:
        try:
            data = engine.get_leaderboard(category, limit=10)
            await interaction.response.send_message(
                embed=build_leaderboard_embed(data),
                view=LeaderboardView(engine),
            )
        except GameError as exc:
            await _send_error(interaction, "排行榜查詢失敗", exc)

    @tree.command(name="rebirth", description="通關第 100 層或達 Lv.100 後執行二周目威望轉生（保留名品、稱號與永久加成）")
    async def cmd_rebirth(interaction: discord.Interaction, confirm: bool = False) -> None:
        uid = str(interaction.user.id)
        try:
            res = engine.rebirth_player(uid, confirm=confirm)
            await interaction.response.send_message(res["message"])
        except GameError as exc:
            await _send_error(interaction, "轉生條件未達成", exc)

    @tree.command(name="help", description="開啟《刀劍神域 SAO》艾恩葛朗特 100 層爬塔與多人共鬥完整指南")
    async def cmd_help(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_help_embed())
