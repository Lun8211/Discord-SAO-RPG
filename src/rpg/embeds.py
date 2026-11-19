"""Discord Embed builders for the val-dc persistent RPG."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import discord

from src.rpg.assets import (
    ASSET_CREDITS,
    get_abyss_guardian_portrait_url,
    get_class_icon_url,
    get_class_portrait_url,
    get_dungeon_boss_portrait_url,
    get_equipment_image_url,
    get_expedition_banner_url,
    get_item_icon_url,
    get_leaderboard_icon_url,
    get_mine_zone_banner_url,
    get_pickaxe_icon_url,
    get_shop_tab_icon_url,
    get_slot_icon_url,
    get_ui_asset_url,
    get_world_boss_portrait_url,
)
from src.rpg.data import (
    ACHIEVEMENTS,
    CLASSES,
    DIFFICULTIES,
    DUNGEONS,
    DUNGEONS_BY_ID,
    ENHANCE_TABLE,
    EQUIPMENT_SETS,
    EXPEDITIONS,
    EXPEDITIONS_BY_ID,
    GEAR_TIERS,
    ITEMS,
    MAX_ENHANCE_LEVEL,
    MAX_EQUIPMENT_CAPACITY,
    MAX_LEVEL,
    MINE_ZONES,
    PICKAXES,
    PROMOTION_REQUIREMENTS,
    RARITIES,
    SLOT_ORDER,
    SLOTS,
    SUPPLY_SHOP,
    exp_needed_for_level,
    format_affix,
    get_class_title,
    max_stamina_for_player,
)
from src.rpg.models import (
    ActiveExpedition,
    CombatSession,
    ComputedStats,
    EquipmentItem,
    PlayerProfile,
    WorldBossState,
)


def progress_bar(current: int, maximum: int, length: int = 12, fill: str = "█", empty: str = "░") -> str:
    if maximum <= 0:
        return fill * length
    ratio = max(0.0, min(1.0, current / maximum))
    filled = int(round(ratio * length))
    return f"{fill * filled}{empty * (length - filled)}"


def format_gear_line(eq: EquipmentItem, show_stats: bool = True) -> str:
    rdef = RARITIES[eq.rarity]
    slot_emoji = SLOTS[eq.slot]["emoji"]
    enh = f" `+{eq.enhance_level}`" if eq.enhance_level > 0 else ""
    lock = " 🔒" if eq.is_locked else ""
    eq_tag = " **[穿戴中]**" if eq.is_equipped else ""
    set_tag = f" ({EQUIPMENT_SETS[eq.set_id]['emoji']}{EQUIPMENT_SETS[eq.set_id]['name'][:3]})" if eq.set_id in EQUIPMENT_SETS else ""
    header = f"`#{eq.id}` {rdef['emoji']} {slot_emoji} **[{rdef['name']}] {eq.name}**{enh}{set_tag}{lock}{eq_tag}"
    if not show_stats:
        return header
    stat_parts = []
    if eq.atk:
        stat_parts.append(f"攻 {eq.atk}")
    if eq.def_:
        stat_parts.append(f"防 {eq.def_}")
    if eq.hp:
        stat_parts.append(f"血 {eq.hp}")
    if eq.mp:
        stat_parts.append(f"魔 {eq.mp}")
    affix_text = "、".join(format_affix(k, v) for k, v in eq.affixes.items())
    detail = f"　└ 戰力 `{eq.power_score:,}` ｜ {' / '.join(stat_parts)}"
    if affix_text:
        detail += f"\n　└ ✨ {affix_text}"
    return f"{header}\n{detail}"


def build_equipment_card_embed(
    eq: EquipmentItem,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    author_name: Optional[str] = None,
    author_icon_url: Optional[str] = None,
    extra_fields: Optional[List[Tuple[str, str, bool]]] = None,
) -> discord.Embed:
    """Build a visual Equipment Showcase Card with hand-painted RPG gear artwork."""
    rdef = RARITIES[eq.rarity]
    smeta = SLOTS[eq.slot]
    tdef = GEAR_TIERS.get(eq.tier, GEAR_TIERS[1])
    enh = f" +{eq.enhance_level}" if eq.enhance_level > 0 else ""

    status_badges = [f"編號 `#{eq.id}`", f"戰力 **`{eq.power_score:,}`**"]
    if eq.is_equipped:
        status_badges.append("✅ **穿戴中**")
    if eq.is_locked:
        status_badges.append("🔒 已鎖定")

    desc_lines = []
    if subtitle:
        desc_lines.append(subtitle)
    desc_lines.append(" ｜ ".join(status_badges))

    embed = discord.Embed(
        title=title or f"{rdef['emoji']} [{rdef['name']}] {eq.name}{enh}",
        description="\n".join(desc_lines),
        color=rdef["color"],
    )
    embed.set_author(
        name=author_name or f"T{eq.tier} {tdef['name']}・{smeta['name']}圖鑑",
        icon_url=author_icon_url or get_slot_icon_url(eq.slot),
    )
    embed.set_thumbnail(url=get_equipment_image_url(eq.tier, eq.slot))

    stat_lines = []
    if eq.atk:
        stat_lines.append(f"⚔️ 攻擊：`+{eq.atk:,}`")
    if eq.def_:
        stat_lines.append(f"🛡️ 防禦：`+{eq.def_:,}`")
    if eq.hp:
        stat_lines.append(f"❤️ 生命：`+{eq.hp:,}`")
    if eq.mp:
        stat_lines.append(f"💙 魔力：`+{eq.mp:,}`")
    embed.add_field(
        name="📊 基礎屬性",
        value="\n".join(stat_lines) if stat_lines else "*無*",
        inline=True,
    )

    info_lines = [
        f"🏷️ 階級：`T{eq.tier} {tdef['name']}`",
        f"📍 部位：{smeta['emoji']} {smeta['name']}",
        f"✨ 強化：`+{eq.enhance_level} / +{MAX_ENHANCE_LEVEL}`",
    ]
    if eq.enhance_pity > 0:
        info_lines.append(f"🌟 保底祝福：`{eq.enhance_pity}%`")
    embed.add_field(
        name="🔖 裝備資訊",
        value="\n".join(info_lines),
        inline=True,
    )

    if eq.affixes:
        affix_lines = [f"• ✨ {format_affix(k, v)}" for k, v in eq.affixes.items()]
        embed.add_field(
            name="🎲 隨機詞條",
            value="\n".join(affix_lines)[:1024],
            inline=False,
        )

    if eq.set_id and eq.set_id in EQUIPMENT_SETS:
        sdef = EQUIPMENT_SETS[eq.set_id]
        embed.add_field(
            name=f"{sdef['emoji']} 套裝：{sdef['name']}",
            value=f"• **2 件套**：{sdef['desc_2']}\n• **4 件套**：{sdef['desc_4']}",
            inline=False,
        )

    if extra_fields:
        for fname, fval, finline in extra_fields:
            embed.add_field(name=fname, value=fval[:1024], inline=finline)

    embed.set_footer(
        text=f"裝備 #{eq.id} ｜ /equip {eq.id} 穿戴 ｜ /forge enhance_id:{eq.id} 強化"
    )
    return embed


def build_enhance_result_embed(res: Dict[str, Any]) -> discord.Embed:
    """Build a visual feedback card for equipment enhancement outcomes."""
    eq: EquipmentItem = res["item"]
    rdef = RARITIES[eq.rarity]
    if res["success"]:
        title = f"🎉 強化成功！{eq.name} 提升至 +{res['new_level']}！"
        subtitle = (
            f"強化階級：`+{res['old_level']}` ➔ **`+{res['new_level']}`**\n"
            f"🏆 目前角色總戰力：**`{res['stats'].combat_power:,}`**"
        )
        color = 0x2ECC71
    else:
        down_note = (
            "🛡️ 保護卷軸已觸發，裝備未掉階！"
            if res["used_protect"]
            else (
                f"強化等級降至 `+{res['new_level']}`"
                if res["downgraded"]
                else "未掉階，裝備完好無損"
            )
        )
        title = f"💨 強化未成功 — {eq.name} (+{res['new_level']})"
        subtitle = (
            f"{down_note}\n"
            f"🌟 保底祝福值提升至：**`{eq.enhance_pity}%`**（達 100% 下次必成功！）"
        )
        color = 0xE67E22

    embed = build_equipment_card_embed(
        eq,
        title=title,
        subtitle=subtitle,
        author_name=f"星界鐵匠鋪・裝備強化（{rdef['name']}）",
        author_icon_url=get_ui_asset_url("anvil_icon"),
    )
    embed.color = color
    return embed


def build_welcome_class_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🌟 歡迎來到星界紀元 RPG！請選擇你的初始職業",
        description=(
            "所有角色進度、裝備、礦石、副本與排行榜都會**永久保存**，即使機器人重啟也絕不遺失！\n"
            "選擇下方四種職業之一踏上冒險之旅（日後也可透過商店的轉職徽章自由切換）："
        ),
        color=0x5865F2,
    )
    embed.set_thumbnail(url=get_ui_asset_url("combat_swords"))
    embed.set_image(url=get_ui_asset_url("welcome_banner"))
    for cid, cdef in CLASSES.items():
        embed.add_field(
            name=f"{cdef['emoji']} {cdef['name']}（{cdef['tiers'][1]}）",
            value=(
                f"{cdef['desc']}\n"
                f"• 主技能：**{cdef['skill']['name']}** — {cdef['skill']['desc']}\n"
                f"• 終極奧義：**{cdef['ultimate']['name']}**（Lv.15 解鎖）"
            ),
            inline=False,
        )
    embed.set_footer(text="點擊下方對應職業按鈕立即建立角色並獲得新手裝備包！")
    return embed


def build_profile_embed(
    player: PlayerProfile,
    stats: ComputedStats,
    equipped: List[EquipmentItem],
    next_stam_sec: int,
    rank_power: Optional[int],
    total_players: int,
    avatar_url: Optional[str] = None,
) -> discord.Embed:
    cls_def = CLASSES.get(player.class_id, CLASSES["swordsman"])
    cls_title = get_class_title(player.class_id, player.promo_tier)
    rebirth_badge = f" ★{player.rebirth_count}轉" if player.rebirth_count > 0 else ""
    title_prefix = f"【{player.active_title}】 " if player.active_title else ""

    needed = exp_needed_for_level(player.level)
    exp_text = (
        "**MAX（已滿級，可使用 `/rebirth` 飛升轉生！）**"
        if player.level >= MAX_LEVEL
        else f"`{player.exp:,} / {needed:,}` ({progress_bar(player.exp, needed, 10)})"
    )
    max_stam = max_stamina_for_player(player.level, player.rebirth_count)
    stam_regen_note = (
        "（已回滿）"
        if next_stam_sec <= 0
        else f"（約 {next_stam_sec // 60}m{next_stam_sec % 60}s +1）"
    )
    pick = PICKAXES[player.pickaxe_tier]
    rank_str = f"第 **{rank_power}** / {total_players} 名" if rank_power else "未上榜"

    embed = discord.Embed(
        title=f"{cls_def['emoji']} {title_prefix}{player.display_name}{rebirth_badge}",
        description=(
            f"職業：**{cls_title}**（{player.promo_tier} 階）｜ 等級：**Lv.{player.level}** ｜ 戰力排行：{rank_str}\n"
            f"✨ 經驗：{exp_text}\n"
            f"⚡ 體力：**`{player.stamina} / {max_stam}`** {stam_regen_note}"
        ),
        color=0xF1C40F if player.rebirth_count > 0 else 0x3498DB,
    )
    embed.set_author(
        name=f"{cls_title}（{player.promo_tier} 階）｜星界冒險者檔案",
        icon_url=avatar_url or get_class_icon_url(player.class_id),
    )
    embed.set_thumbnail(url=get_class_portrait_url(player.class_id, player.promo_tier))

    embed.add_field(
        name="⚔️ 戰鬥屬性",
        value=(
            f"🏆 總戰力：**`{stats.combat_power:,}`**\n"
            f"❤️ 生命：`{stats.max_hp:,}` ｜ 💙 魔力：`{stats.max_mp:,}`\n"
            f"⚔️ 攻擊：`{stats.atk:,}` ｜ 🛡️ 防禦：`{stats.def_:,}`\n"
            f"💥 暴擊：`{stats.crit_rate * 100:.1f}%`（爆傷 `{stats.crit_dmg * 100:.0f}%`）\n"
            f"💨 閃避：`{stats.dodge * 100:.1f}%` ｜ 🩸 吸血：`{stats.lifesteal * 100:.1f}%`"
        ),
        inline=True,
    )

    embed.add_field(
        name="💰 資產與冒險紀錄",
        value=(
            f"🪙 金幣：**`{player.gold:,}`**\n"
            f"💎 星鑽：**`{player.gems:,}`**\n"
            f"{pick['emoji']} 礦鎬：**T{player.pickaxe_tier} {pick['name']}**\n"
            f"🗼 無盡深淵：最高第 **`{player.abyss_highest}`** 層\n"
            f"⛏️ 挖礦 `{player.total_mines:,}` 次 ｜ 🏰 副本 `{player.total_dungeons:,}` 次"
        ),
        inline=True,
    )

    eq_by_slot = {e.slot: e for e in equipped}
    eq_lines = []
    for slot in SLOT_ORDER:
        smeta = SLOTS[slot]
        eq = eq_by_slot.get(slot)
        if eq:
            rdef = RARITIES[eq.rarity]
            enh = f" `+{eq.enhance_level}`" if eq.enhance_level > 0 else ""
            eq_lines.append(f"{smeta['emoji']} {smeta['name']}：{rdef['emoji']} **{eq.name}**{enh}（戰力 `{eq.power_score:,}`）")
        else:
            eq_lines.append(f"{smeta['emoji']} {smeta['name']}：*未穿戴*")

    if stats.active_sets:
        eq_lines.append("✨ **套裝啟動**：" + "、".join(stats.active_sets))

    embed.add_field(
        name="🛡️ 穿戴裝備總覽",
        value="\n".join(eq_lines)[:1024],
        inline=False,
    )

    bonus_parts = []
    if stats.gold_bonus > 0:
        bonus_parts.append(f"金幣 +{stats.gold_bonus * 100:.0f}%")
    if stats.exp_bonus > 0:
        bonus_parts.append(f"經驗 +{stats.exp_bonus * 100:.0f}%")
    if stats.mine_bonus > 0:
        bonus_parts.append(f"挖礦 +{stats.mine_bonus * 100:.0f}%")
    if stats.drop_bonus > 0:
        bonus_parts.append(f"掉寶 +{stats.drop_bonus * 100:.0f}%")
    footer_extra = (" ｜ 加成：" + " / ".join(bonus_parts)) if bonus_parts else ""
    embed.set_footer(text=f"💾 所有資料已即時寫入 SQLite 永久存檔{footer_extra}")
    return embed


def build_mine_result_embed(res: Dict[str, Any]) -> discord.Embed:
    player: PlayerProfile = res["player"]
    zone = res["zone"]
    pick = res["pickaxe"]
    max_stam = max_stamina_for_player(player.level, player.rebirth_count)

    title = f"{zone['emoji']} 挖礦成果 — {zone['name']}"
    if res["is_double"]:
        title += " 💥雙倍暴擊！"

    loot_lines = []
    best_item_id: Optional[str] = None
    best_tier = -1
    for iid, qty in res["loot"].items():
        meta = ITEMS.get(iid, {"emoji": "📦", "name": iid, "tier": 0})
        loot_lines.append(f"{meta['emoji']} **{meta['name']}** `x{qty}`")
        if meta.get("tier", 0) >= best_tier:
            best_tier = meta.get("tier", 0)
            best_item_id = iid

    desc_lines = [
        f"使用礦鎬：{pick['emoji']} **T{player.pickaxe_tier} {pick['name']}** ｜ 🔥 採礦熱度：**{res['combo']}/10 層**（+{res['combo'] * 2}% 產量）",
        f"🪙 金幣：**+{res['gold_gain']:,}** ｜ ✨ 經驗：**+{res['exp_gain']:,}**"
        + (f" ｜ 🎉 **升級至 Lv.{player.level}！(+{res['levels_gained'] * 30} 體力)**" if res["levels_gained"] > 0 else ""),
    ]
    if res["event_text"]:
        desc_lines.append("")
        desc_lines.append(res["event_text"])

    embed = discord.Embed(
        title=title,
        description="\n".join(desc_lines),
        color=0xF39C12 if (res["is_double"] or res["event_text"]) else 0x2ECC71,
    )
    embed.set_author(
        name=f"T{player.pickaxe_tier} {pick['name']}・礦區採掘",
        icon_url=get_pickaxe_icon_url(player.pickaxe_tier),
    )
    embed.set_thumbnail(
        url=get_item_icon_url(best_item_id) if best_item_id else get_pickaxe_icon_url(player.pickaxe_tier)
    )
    embed.set_image(url=get_mine_zone_banner_url(zone["id"]))

    embed.add_field(
        name="⛏️ 本次採集礦石與材料",
        value="\n".join(loot_lines) if loot_lines else "（空手而歸）",
        inline=False,
    )
    if res["achievements"]:
        ach_text = "\n".join(f"🏅 解鎖成就 **{a['name']}**（+{a['gems']} 💎）" for a in res["achievements"])
        embed.add_field(name="🎊 新成就解鎖！", value=ach_text, inline=False)

    embed.set_footer(
        text=f"⚡ 剩餘體力：{player.stamina}/{max_stam} ｜ 🪙 總金幣：{player.gold:,} ｜ 累計挖礦：{player.total_mines:,} 次"
    )
    return embed


def build_combat_embed(session: CombatSession, player: PlayerProfile) -> discord.Embed:
    cls_def = CLASSES[player.class_id]
    cls_title = get_class_title(player.class_id, player.promo_tier)
    enemy_bar = progress_bar(session.enemy_hp, session.enemy_max_hp, 14, "🟥", "⬛")
    player_bar = progress_bar(session.player_hp, session.player_max_hp, 14, "🟩", "⬛")
    mp_bar = progress_bar(session.player_mp, session.player_max_mp, 10, "🟦", "⬛")

    if session.finished:
        color = 0x2ECC71 if session.victory else (0x95A5A6 if session.retreated else 0xE74C3C)
    elif session.enemy_telegraph:
        color = 0xE67E22
    else:
        color = 0x5865F2

    embed = discord.Embed(
        title=session.title,
        color=color,
    )
    embed.set_author(
        name=f"{player.display_name}（{cls_title}）",
        icon_url=get_class_icon_url(player.class_id),
    )
    if session.mode == "dungeon":
        enemy_art = get_dungeon_boss_portrait_url(session.target_id)
    else:
        try:
            floor_num = int(session.target_id)
        except (TypeError, ValueError):
            floor_num = 1
        enemy_art = get_abyss_guardian_portrait_url(floor_num)
    embed.set_thumbnail(url=enemy_art)

    enemy_status = []
    if session.enemy_telegraph:
        enemy_status.append(f"⚠️ **蓄力【{session.enemy_telegraph_name}】**")
    if session.enemy_shred_turns > 0:
        enemy_status.append(f"💔 破甲({session.enemy_shred_turns}回合)")
    if session.enemy_burn_turns > 0:
        enemy_status.append(f"🔥 灼燒({session.enemy_burn_turns}回合)")

    embed.add_field(
        name=f"{session.enemy_emoji} {session.enemy_name}（Lv.{session.enemy_level}）",
        value=(
            f"HP：`{session.enemy_hp:,} / {session.enemy_max_hp:,}`\n"
            f"{enemy_bar}"
            + (f"\n{' ｜ '.join(enemy_status)}" if enemy_status else "")
        ),
        inline=False,
    )

    shield_str = f" ｜ 🛡️ 護盾：`{session.player_shield:,}`" if session.player_shield > 0 else ""
    ult_str = (
        "🌟 奧義：**就緒**"
        if (player.level >= 15 or player.rebirth_count > 0) and session.ult_cooldown == 0
        else (f"🌟 奧義：CD `{session.ult_cooldown}` 回合" if (player.level >= 15 or player.rebirth_count > 0) else "🌟 奧義：Lv.15 解鎖")
    )
    embed.add_field(
        name=f"{cls_def['emoji']} {player.display_name}（第 {session.turn} 回合）",
        value=(
            f"HP：`{session.player_hp:,} / {session.player_max_hp:,}`{shield_str}\n"
            f"{player_bar}\n"
            f"MP：`{session.player_mp:,} / {session.player_max_mp:,}` {mp_bar} ｜ {ult_str}"
        ),
        inline=False,
    )

    embed.add_field(
        name="📜 戰鬥紀錄",
        value="\n".join(session.logs[-8:])[:1024] or "戰鬥開始！",
        inline=False,
    )

    if session.finished and session.victory and session.rewards_summary:
        rw = session.rewards_summary
        rw_lines = [
            f"🪙 金幣：**+{rw['gold']:,}** ｜ ✨ 經驗：**+{rw['exp']:,}**"
            + (f" ｜ 💎 星鑽：**+{rw['gems']:,}**" if rw["gems"] > 0 else "")
        ]
        if rw.get("first_clear"):
            rw_lines.append("🌟 **首通獎勵已發放！**" + (f"（退還 +{rw['stamina_refund']} 體力）" if rw.get("stamina_refund") else ""))
        if rw.get("levels_gained", 0) > 0:
            rw_lines.append(f"🎉 **等級提升至 Lv.{player.level}！**")
        if rw.get("loot"):
            loot_str = "、".join(
                f"{ITEMS[k]['emoji']}{ITEMS[k]['name']} x{v}" for k, v in rw["loot"].items() if k in ITEMS
            )
            rw_lines.append(f"📦 掉落材料：{loot_str}")
        for eq in rw.get("gear", []):
            rdef = RARITIES[eq.rarity]
            rw_lines.append(f"🎁 獲得裝備：{rdef['emoji']} **[{rdef['name']}] {eq.name}**（`#{eq.id}` 戰力 `{eq.power_score:,}`）")
        for a in rw.get("achievements", []):
            rw_lines.append(f"🏅 解鎖成就：**{a['name']}**（+{a['gems']} 💎）")
        embed.add_field(name="🎁 勝利戰利品", value="\n".join(rw_lines)[:1024], inline=False)

    return embed


def build_combat_embeds(session: CombatSession, player: PlayerProfile) -> List[discord.Embed]:
    """Return combat embed plus visual Equipment Showcase Card(s) when victory drops gear."""
    embeds = [build_combat_embed(session, player)]
    if session.finished and session.victory and session.rewards_summary:
        dropped_gear: List[EquipmentItem] = session.rewards_summary.get("gear", [])
        if dropped_gear:
            best_eq = max(dropped_gear, key=lambda item: item.power_score)
            rdef = RARITIES[best_eq.rarity]
            extra_note = (
                f"本次戰鬥共掉落 **{len(dropped_gear)} 件**裝備，以下為最高戰力戰利品："
                if len(dropped_gear) > 1
                else "恭喜擊敗首領並獲得全新裝備！"
            )
            embeds.append(
                build_equipment_card_embed(
                    best_eq,
                    title=f"🎁 戰利品掉落 — {rdef['emoji']} [{rdef['name']}] {best_eq.name}",
                    subtitle=extra_note,
                    author_name="副本／深淵裝備掉落",
                    author_icon_url=get_ui_asset_url("chest_open"),
                )
            )
    return embeds


def build_dungeon_list_embed(
    player: PlayerProfile,
    clears: Dict[Tuple[str, str], int],
    selected_dungeon_id: Optional[str] = None,
) -> discord.Embed:
    embed = discord.Embed(
        title="🏰 副本征討大廳",
        description=(
            "選擇下方副本與難度開戰！通關「普通」解鎖「困難」，通關「困難」解鎖「地獄」。\n"
            "已通關的難度可直接點選 **⚡ 快速掃蕩** 省時刷裝！"
        ),
        color=0x9B59B6,
    )
    selected = DUNGEONS_BY_ID.get(selected_dungeon_id or "") if selected_dungeon_id else DUNGEONS[0]
    if selected:
        embed.set_author(
            name=f"預覽副本首領：{selected['boss_name']}（掉落 T{selected['gear_tier']} 裝備）",
            icon_url=get_equipment_image_url(selected["gear_tier"], "weapon"),
        )
        embed.set_thumbnail(url=get_dungeon_boss_portrait_url(selected["id"]))
    else:
        embed.set_thumbnail(url=get_ui_asset_url("combat_swords"))
    embed.set_image(url=get_ui_asset_url("dungeon_hall_banner"))

    for d in DUNGEONS:
        n_clr = clears.get((d["id"], "normal"), 0)
        h_clr = clears.get((d["id"], "hard"), 0)
        e_clr = clears.get((d["id"], "hell"), 0)
        status = f"🟢普:{n_clr} ｜ 🟠困:{h_clr} ｜ 🔴獄:{e_clr}"
        marker = "▶ " if (selected and d["id"] == selected["id"]) else ""
        embed.add_field(
            name=f"{marker}{d['emoji']} {d['name']}（建議 Lv.{d['rec_level']} ｜ T{d['gear_tier']} 裝）",
            value=f"首領：{d['boss_emoji']} {d['boss_name']}\n通關紀錄：{status}",
            inline=True,
        )
    embed.set_footer(text=f"⚡ 目前體力：{player.stamina} ｜ 體力消耗：普通 12 / 困難 16 / 地獄 20")
    return embed


def build_world_boss_embed(
    boss: WorldBossState,
    rankings: List[Dict[str, Any]],
    player: PlayerProfile,
    attack_res: Optional[Dict[str, Any]] = None,
) -> discord.Embed:
    hp_pct = (boss.current_hp / boss.max_hp * 100.0) if boss.max_hp > 0 else 0.0
    bar = progress_bar(boss.current_hp, boss.max_hp, 16, "🟥", "⬛")

    embed = discord.Embed(
        title=f"🐉 伺服器世界王 — {boss.name}",
        description=(
            f"全伺服器玩家共同討伐！即使機器人重啟，世界王血量與所有人的傷害貢獻也會**完整保留**。\n\n"
            f"❤️ 剩餘血量：**`{boss.current_hp:,} / {boss.max_hp:,}`**（`{hp_pct:.1f}%`）\n"
            f"{bar}\n"
            f"⚔️ 攻擊：`{boss.atk:,}` ｜ 🛡️ 防禦：`{boss.def_:,}` ｜ 消耗：`8` 體力"
        ),
        color=0xE74C3C,
    )
    embed.set_author(
        name=f"世界王 Lv.{boss.tier}・全服共鬥討伐戰",
        icon_url=get_ui_asset_url("combat_swords"),
    )
    embed.set_image(url=get_world_boss_portrait_url(boss.boss_id))

    if attack_res:
        res_lines = [
            f"💥 你對世界王發起 5 回合猛攻（撐過 `{attack_res['turns_survived']}` 回合，暴擊 `{attack_res['crits']}` 次）！",
            f"⚔️ 本次造成傷害：**`{attack_res['dealt']:,}`**",
            f"🎁 即時獎勵：🪙 `+{attack_res['gold']:,}` 金幣 ｜ ✨ `+{attack_res['exp']:,}` 經驗 ｜ 💀 首領魂晶 `x{attack_res['essence']}`",
        ]
        if attack_res.get("boss_killed"):
            res_lines.append("")
            res_lines.append("🎊 **世界王已被全服聯手擊殺！！所有參與者均已自動領取討伐大獎！**")
            for mvp in attack_res.get("mvp_rewards", [])[:3]:
                medal = ["🥇", "🥈", "🥉"][mvp["rank"] - 1]
                res_lines.append(
                    f"{medal} **{mvp['display_name']}**（總傷 `{mvp['damage']:,}`）→ 💎 +{mvp['gems']} 星鑽"
                    + (f" + 🗝️ x{mvp['keys']}" if mvp["keys"] else "")
                )
            if attack_res.get("next_boss"):
                res_lines.append(f"\n🔥 新的世界王 **{attack_res['next_boss'].name}** 已降臨！")
        embed.add_field(name="⚔️ 討伐戰報", value="\n".join(res_lines)[:1024], inline=False)

    if rankings:
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        rank_lines = []
        for idx, r in enumerate(rankings[:5]):
            m = medals[idx] if idx < len(medals) else f"`#{idx + 1}`"
            rank_lines.append(
                f"{m} **{r['display_name']}** — 傷害 **`{r['total_damage']:,}`**（出擊 {r['attacks_count']} 次）"
            )
        embed.add_field(name="🏆 本輪傷害貢獻榜", value="\n".join(rank_lines), inline=False)
    else:
        embed.add_field(name="🏆 本輪傷害貢獻榜", value="*尚無人發起挑戰，快來搶下首刀！*", inline=False)

    embed.set_footer(text=f"⚡ 你的體力：{player.stamina} ｜ 你的生涯世界王總傷害：{player.total_boss_damage:,}")
    return embed


def build_shop_embed(
    player: PlayerProfile,
    tab: str,
    daily_purchases: Dict[str, int],
    mystery_shop: Dict[str, Any],
    relic_keys: int,
) -> discord.Embed:
    if tab == "supply":
        embed = discord.Embed(
            title="🏪 RPG 冒險物資商店",
            description=f"🪙 金幣：**`{player.gold:,}`** ｜ 💎 星鑽：**`{player.gems:,}`**\n選擇下方商品立即購買：",
            color=0x2ECC71,
        )
        embed.set_thumbnail(url=get_shop_tab_icon_url("supply"))
        lines = []
        for s in SUPPLY_SHOP:
            item = ITEMS[s["item_id"]]
            cur_sym = "🪙" if s["currency"] == "gold" else "💎"
            bought = daily_purchases.get(s["id"], 0)
            lim = f"（今日 `{bought}/{s['daily_limit']}`）" if s["daily_limit"] > 0 else "（無限購）"
            lines.append(
                f"{item['emoji']} **{item['name']} x{s['qty']}** — {cur_sym} `{s['price']:,}` {lim}\n　└ {item['desc']}"
            )
        embed.add_field(name="📦 常駐商品清單", value="\n".join(lines)[:1024], inline=False)
        return embed

    if tab == "mystery":
        embed = discord.Embed(
            title="✨ 限時折扣神秘商店",
            description=(
                f"🪙 金幣：**`{player.gold:,}`** ｜ 💎 星鑽：**`{player.gems:,}`**\n"
                f"⏳ 下次進貨刷新：<t:{mystery_shop['resets_at']}:R>（每 6 小時全服同步刷新）"
            ),
            color=0x9B59B6,
        )
        embed.set_thumbnail(url=get_shop_tab_icon_url("mystery"))
        lines = []
        for idx, o in enumerate(mystery_shop["offers"], start=1):
            cur_sym = "🪙" if o["currency"] == "gold" else "💎"
            sold = mystery_shop["purchased"].get(o["key"], 0) >= 1
            tag = " ✅ **[已購]**" if sold else f" 🏷️ `{o['discount']}`"
            lines.append(f"`{idx}.` **{o['name']}** — {cur_sym} `{o['price']:,}`{tag}")
        embed.add_field(name="🎁 本輪精選特惠", value="\n".join(lines)[:1024], inline=False)
        return embed

    if tab == "gacha":
        embed = discord.Embed(
            title="🎁 星界秘寶抽箱",
            description=(
                f"🪙 金幣：**`{player.gold:,}`** ｜ 💎 星鑽：**`{player.gems:,}`** ｜ 🗝️ 鑰匙：**`{relic_keys}`**\n\n"
                "🧰 **冒險者木箱**（`1,500 金幣`）\n"
                "└ 隨機獲得 **精良 ~ 傳說** 裝備 + 強化石\n\n"
                "💎 **星界秘寶箱**（優先消耗 `🗝️ 鑰匙 x1` 或 `100 星鑽`）\n"
                "└ 必得 **稀有以上**，高機率 **史詩 / 傳說 / 神話** 裝備！\n"
                f"└ 🎯 傳說保底進度：**`{player.gacha_pity_legendary} / 10`**\n"
                f"└ 🌟 神話保底進度：**`{player.gacha_pity_mythic} / 30`**"
            ),
            color=0xF39C12,
        )
        embed.set_author(
            name="星界秘寶抽箱（開箱即顯示專屬裝備圖鑑卡片！）",
            icon_url=get_ui_asset_url("chest_open"),
        )
        embed.set_thumbnail(url=get_shop_tab_icon_url("gacha"))
        return embed

    embed = discord.Embed(
        title="💰 回收與出售大廳",
        description=(
            f"🪙 金幣：**`{player.gold:,}`** ｜ 💎 星鑽：**`{player.gems:,}`**\n\n"
            "• **出售多餘礦石**：自動為每種礦石保留 `10` 個供鍛造使用，其餘換取金幣。\n"
            "• **一鍵分解低階裝備**：分解所有未穿戴且未鎖定的「稀有以下」裝備，換取大量 **初級強化石 + 金幣**！"
        ),
        color=0xE67E22,
    )
    embed.set_thumbnail(url=get_shop_tab_icon_url("sell"))
    return embed


def build_bag_embed(
    player: PlayerProfile,
    gear: List[EquipmentItem],
    inventory: Dict[str, int],
    tab: str = "gear",
    page: int = 0,
) -> discord.Embed:
    if tab == "gear":
        per_page = 6
        total_pages = max(1, (len(gear) + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))
        chunk = gear[page * per_page : (page + 1) * per_page]

        embed = discord.Embed(
            title=f"🎒 裝備背包（{len(gear)} / {MAX_EQUIPMENT_CAPACITY} 件）",
            description=(
                "使用下方選單 **穿戴**、**鎖定/解鎖** 或 **檢視裝備圖片卡片**，也可點 **✨ 一鍵最佳裝備**！\n\n"
                + ("\n\n".join(format_gear_line(eq) for eq in chunk) if chunk else "*背包目前沒有裝備。*")
            )[:4096],
            color=0x3498DB,
        )
        embed.set_author(name="冒險者裝備庫", icon_url=get_ui_asset_url("bag_icon"))
        if chunk:
            featured = max(chunk, key=lambda item: (item.is_equipped, item.power_score))
            embed.set_thumbnail(url=get_equipment_image_url(featured.tier, featured.slot))
        else:
            embed.set_thumbnail(url=get_ui_asset_url("bag_icon"))
        embed.set_footer(text=f"第 {page + 1} / {total_pages} 頁 ｜ 🪙 金幣：{player.gold:,} ｜ 💎 星鑽：{player.gems:,}")
        return embed

    embed = discord.Embed(
        title="📦 材料、礦石與消耗品背包",
        description=f"🪙 金幣：**`{player.gold:,}`** ｜ 💎 星鑽：**`{player.gems:,}`**",
        color=0x1ABC9C,
    )
    embed.set_thumbnail(url=get_ui_asset_url("materials_icon"))
    categories = [
        ("⛏️ 礦石原材", "ore"),
        ("🔨 強化與首領材料", "material"),
        ("🧪 藥水與鑰匙", ("consumable", "key")),
    ]
    for title, cat in categories:
        cats = (cat,) if isinstance(cat, str) else cat
        lines = []
        for iid, qty in sorted(inventory.items()):
            meta = ITEMS.get(iid)
            if not meta or meta["category"] not in cats:
                continue
            lines.append(f"{meta['emoji']} **{meta['name']}** `x{qty:,}`")
        embed.add_field(
            name=title,
            value="\n".join(lines)[:1024] if lines else "*無*",
            inline=True,
        )
    return embed


def build_forge_embed(
    player: PlayerProfile,
    inventory: Dict[str, int],
    equipped: List[EquipmentItem],
) -> discord.Embed:
    cur_pick = PICKAXES[player.pickaxe_tier]
    next_pick = PICKAXES.get(player.pickaxe_tier + 1)

    embed = discord.Embed(
        title="⚒️ 星界鐵匠鋪 — 強化・鍛造・礦鎬升級",
        description=(
            f"🪙 金幣：**`{player.gold:,}`** ｜ 🔹 初級強化石：**`{inventory.get('enhance_stone', 0):,}`** ｜ "
            f"🌟 星輝強化石：**`{inventory.get('adv_enhance_stone', 0):,}`** ｜ 📜 保護卷軸：**`{inventory.get('protect_scroll', 0):,}`**"
        ),
        color=0xE67E22,
    )
    embed.set_author(name="星界鐵匠鋪", icon_url=get_ui_asset_url("anvil_icon"))
    embed.set_thumbnail(url=get_pickaxe_icon_url(player.pickaxe_tier))
    embed.set_image(url=get_ui_asset_url("forge_banner"))

    # Pickaxe upgrade preview
    if next_pick:
        req_str = "、".join(
            f"{ITEMS[k]['emoji']}{ITEMS[k]['name']} `{inventory.get(k, 0)}/{v}`"
            for k, v in next_pick["materials"].items()
        )
        pick_val = (
            f"目前：{cur_pick['emoji']} **T{player.pickaxe_tier} {cur_pick['name']}**（產量 `x{cur_pick['yield_mult']:.2f}`）\n"
            f"下一階：{next_pick['emoji']} **T{player.pickaxe_tier + 1} {next_pick['name']}**（產量 `x{next_pick['yield_mult']:.2f}`、雙倍率 `{next_pick['double_chance'] * 100:.0f}%`）\n"
            f"需求：🪙 `{next_pick['gold']:,}` ｜ {req_str}"
        )
    else:
        pick_val = f"目前：{cur_pick['emoji']} **T8 {cur_pick['name']}**（已達最高神階！）"
    embed.add_field(name="⛏️ 礦鎬鍛造升級", value=pick_val[:1024], inline=False)

    # Gear forging tiers overview
    forge_lines = []
    for tier, tdef in GEAR_TIERS.items():
        reqs = "、".join(f"{ITEMS[k]['name']}x{v}" for k, v in tdef["forge_materials"].items())
        locked_str = "" if (player.level >= tdef["min_level"] or player.rebirth_count > 0) else f" 🔒Lv.{tdef['min_level']}"
        forge_lines.append(
            f"**T{tier} {tdef['name']}**{locked_str} — 🪙 `{tdef['forge_gold']:,}` + {reqs}"
        )
    embed.add_field(name="🔨 裝備鍛造配方", value="\n".join(forge_lines)[:1024], inline=False)

    # Equipped enhancement preview
    enh_lines = []
    for eq in equipped[:6]:
        if eq.enhance_level >= MAX_ENHANCE_LEVEL:
            enh_lines.append(f"`#{eq.id}` **{eq.name}** `+{eq.enhance_level}` ✨已滿階")
        else:
            nxt = eq.enhance_level + 1
            cfg = ENHANCE_TABLE[nxt]
            gcost = int(round(cfg["gold"] * (1.0 + 0.25 * (eq.tier - 1))))
            eff_rate = 1.0 if eq.enhance_pity >= 100 else min(1.0, cfg["rate"] + (eq.enhance_pity / 100.0) * 0.35)
            enh_lines.append(
                f"`#{eq.id}` **{eq.name}** `+{eq.enhance_level}→+{nxt}`（成功率 `{eff_rate * 100:.0f}%`、保底 `{eq.enhance_pity}%`、🪙 `{gcost:,}`、{ITEMS[cfg['stone']]['emoji']}x{cfg['stone_qty']}）"
            )
    embed.add_field(
        name="✨ 穿戴中裝備強化一覽（絕不碎裝・失敗累積保底）",
        value="\n".join(enh_lines)[:1024] if enh_lines else "*目前沒有穿戴任何裝備*",
        inline=False,
    )
    return embed


def build_daily_quests_embed(
    player: PlayerProfile, quests_status: Dict[str, Any], today_key: str
) -> discord.Embed:
    checked = player.last_checkin_date == today_key
    next_cycle_day = ((player.checkin_streak) % 7) + 1 if not checked else ((player.checkin_streak - 1) % 7) + 1
    embed = discord.Embed(
        title="📅 每日簽到與任務中心",
        description=(
            f"簽到狀態：{'✅ **今日已簽到**' if checked else '🔔 **尚未簽到（快點下方按鈕領獎！）**'}\n"
            f"連續簽到：**`{player.checkin_streak}` 天**（累計 `{player.total_checkins}` 天 ｜ 7 日循環第 `{next_cycle_day}` 天）"
        ),
        color=0x2ECC71 if checked else 0xF1C40F,
    )
    embed.set_thumbnail(url=get_ui_asset_url("quest_scroll"))

    def _fmt_q(qlist: List[Dict[str, Any]]) -> str:
        lines = []
        for q in qlist:
            done = q["progress"] >= q["target"]
            icon = "✅" if q["claimed"] else ("🎁" if done else "▫️")
            status = "已領取" if q["claimed"] else ("可領獎！" if done else f"`{q['progress']}/{q['target']}`")
            lines.append(
                f"{icon} **{q['name']}**（{q['desc']}）— {status}\n"
                f"　└ 獎勵：🪙 `{q['gold']:,}` ｜ 💎 `{q['gems']}` ｜ ✨ `{q['exp']:,} EXP`"
            )
        return "\n".join(lines)[:1024]

    embed.add_field(name="📌 每日任務（每日重置）", value=_fmt_q(quests_status["daily"]), inline=False)
    embed.add_field(name="🌟 每週任務（每週一重置）", value=_fmt_q(quests_status["weekly"]), inline=False)
    return embed


def build_expedition_embed(
    player: PlayerProfile, active: Optional[ActiveExpedition], now_ts: int
) -> discord.Embed:
    embed = discord.Embed(
        title="🧭 離線冒險派遣（重啟亦持續計時！）",
        color=0x1ABC9C,
    )
    embed.set_thumbnail(url=get_class_icon_url(player.class_id))
    if active:
        edef = EXPEDITIONS_BY_ID[active.expedition_id]
        ready = now_ts >= active.ends_at
        embed.description = (
            f"目前派遣：{edef['emoji']} **{edef['name']}**\n"
            f"狀態：{'🎉 **已完成！立即點擊下方按鈕領取戰利品！**' if ready else f'⏳ 探索中，預計歸來：<t:{active.ends_at}:R>（<t:{active.ends_at}:t>）'}"
        )
        embed.set_image(url=get_expedition_banner_url(active.expedition_id))
    else:
        embed.description = "目前閒置中！選擇下方遠征路線出發，即使離線或機器人重啟也會持續計時並帶回豐厚資源："
        embed.set_image(url=get_ui_asset_url("expedition_default_banner"))

    lines = []
    for e in EXPEDITIONS:
        hrs = e["duration_sec"] // 3600
        lock = "" if (player.level >= e["min_level"] or player.rebirth_count > 0) else f" 🔒需 Lv.{e['min_level']}"
        lines.append(
            f"{e['emoji']} **{e['name']}**（`{hrs} 小時`）{lock}\n"
            f"　└ 基礎收益：🪙 `{e['base_gold']:,}+` ｜ ✨ `{e['base_exp']:,}+ EXP` ｜ 裝備機率 `{int(e['gear_chance'] * 100)}%`"
        )
    embed.add_field(name="🗺️ 可選派遣路線", value="\n".join(lines)[:1024], inline=False)
    return embed


def build_leaderboard_embed(
    category: str,
    entries: List[PlayerProfile],
    caller_rank: Optional[int],
    total_players: int,
) -> discord.Embed:
    cat_meta = {
        "power": ("⚔️ 伺服器戰力排行榜", 0xF1C40F),
        "level": ("⭐ 等級與轉生排行榜", 0x9B59B6),
        "abyss": ("🗼 無盡深淵層數排行榜", 0xE74C3C),
        "gold": ("💰 富豪金幣排行榜", 0x2ECC71),
        "mining": ("⛏️ 傳奇礦神排行榜", 0xE67E22),
        "boss": ("🐉 世界王總傷害貢獻榜", 0xC0392B),
    }
    title, color = cat_meta.get(category, cat_meta["power"])
    medals = ["🥇", "🥈", "🥉"]

    lines = []
    for idx, p in enumerate(entries, start=1):
        prefix = medals[idx - 1] if idx <= 3 else f"`#{idx:02d}`"
        cls_emoji = CLASSES.get(p.class_id, CLASSES["swordsman"])["emoji"]
        rb = f" ★{p.rebirth_count}" if p.rebirth_count > 0 else ""
        title_str = f"[{p.active_title}] " if p.active_title else ""

        if category == "power":
            val = f"戰力 **`{p.combat_power:,}`**（Lv.{p.level}{rb}）"
        elif category == "level":
            val = f"**{p.rebirth_count} 轉 Lv.{p.level}**（戰力 `{p.combat_power:,}`）"
        elif category == "abyss":
            val = f"最高第 **`{p.abyss_highest}`** 層（戰力 `{p.combat_power:,}`）"
        elif category == "gold":
            val = f"🪙 **`{p.gold:,}`** 金幣"
        elif category == "mining":
            val = f"⛏️ **`{p.total_mines:,}`** 次（T{p.pickaxe_tier} 鎬）"
        else:
            val = f"💥 **`{p.total_boss_damage:,}`** 傷害（參與擊殺 `{p.boss_kills_participated}` 次）"

        lines.append(f"{prefix} {cls_emoji} {title_str}**{p.display_name}** — {val}")

    embed = discord.Embed(
        title=title,
        description="\n".join(lines) if lines else "*目前還沒有冒險者上榜，快輸入 `/start` 搶下第一名！*",
        color=color,
    )
    embed.set_thumbnail(url=get_leaderboard_icon_url(category))
    rank_text = f"你的排名：第 {caller_rank} / {total_players} 名" if caller_rank else f"總註冊冒險者：{total_players} 人"
    embed.set_footer(text=rank_text)
    return embed


def build_achievements_embed(
    player: PlayerProfile, unlocked: Dict[str, int]
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏅 成就與稱號圖鑑（已解鎖 {len(unlocked)} / {len(ACHIEVEMENTS)}）",
        description=(
            f"目前配戴稱號：**{player.active_title or '無'}**\n"
            "💡 所有已解鎖成就的屬性加成皆為**永久帳號生效**（不需配戴即可疊加）！"
        ),
        color=0xF1C40F,
    )
    embed.set_thumbnail(url=get_ui_asset_url("achievement_laurel"))
    lines = []
    for a in ACHIEVEMENTS:
        is_ok = a["id"] in unlocked
        mark = "✅" if is_ok else "🔒"
        bonus_str = "、".join(format_affix(k, v) for k, v in a["bonus"].items())
        lines.append(f"{mark} **{a['name']}**（{a['title']}）— {a['desc']}｜`{bonus_str}`")
    # Split into 2 fields so we never exceed 1024 chars per field
    mid = (len(lines) + 1) // 2
    embed.add_field(name="📜 成就列表（上）", value="\n".join(lines[:mid])[:1024], inline=False)
    embed.add_field(name="📜 成就列表（下）", value="\n".join(lines[mid:])[:1024], inline=False)
    return embed


def build_class_embed(player: PlayerProfile, inventory: Dict[str, int]) -> discord.Embed:
    cls_def = CLASSES[player.class_id]
    cur_title = get_class_title(player.class_id, player.promo_tier)
    next_tier = player.promo_tier + 1
    req = PROMOTION_REQUIREMENTS.get(next_tier)

    embed = discord.Embed(
        title=f"{cls_def['emoji']} 職業殿堂 — {cur_title}（{player.promo_tier} 階）",
        description=(
            f"{cls_def['desc']}\n\n"
            f"• 主技能：**{cls_def['skill']['name']}**（`{cls_def['skill']['mp']} MP`）— {cls_def['skill']['desc']}\n"
            f"• 終極奧義：**{cls_def['ultimate']['name']}**（`{cls_def['ultimate']['mp']} MP`，CD `{cls_def['ultimate']['cooldown']}` 回合）— {cls_def['ultimate']['desc']}"
        ),
        color=0x9B59B6,
    )
    embed.set_author(name=f"{cls_def['name']}職業殿堂", icon_url=get_class_icon_url(player.class_id))
    embed.set_image(url=get_class_portrait_url(player.class_id, player.promo_tier))

    if req:
        next_title = get_class_title(player.class_id, next_tier)
        mats = "、".join(
            f"{ITEMS[k]['emoji']}{ITEMS[k]['name']} `{inventory.get(k, 0)}/{v}`"
            for k, v in req["materials"].items()
        )
        embed.add_field(
            name=f"✨ {next_tier} 轉進階：{next_title}",
            value=f"需求：**Lv.{req['min_level']}** ｜ 🪙 `{req['gold']:,}` 金幣 ｜ {mats}",
            inline=False,
        )
    else:
        embed.add_field(
            name="👑 職業階級已達巔峰",
            value="你已覺醒三轉終極稱號，獲得全部職業被動加成！",
            inline=False,
        )

    emblems = inventory.get("class_emblem", 0)
    embed.add_field(
        name="🎖️ 自由轉職（保留進階階級）",
        value=f"持有轉職徽章：**`{emblems}`** 個（可於 `/shop` 購買，點擊下方選單即可切換其他職業）。",
        inline=False,
    )
    return embed


def build_rebirth_embed(player: PlayerProfile) -> discord.Embed:
    next_rb = player.rebirth_count + 1
    next_mult = 100 + next_rb * 18
    next_bonus = next_rb * 12
    bonus_gems = 200 + 50 * next_rb

    embed = discord.Embed(
        title="✨ 星界轉生 / 飛升系統（長線無限成長）",
        description=(
            f"目前狀態：**{player.rebirth_count} 轉 Lv.{player.level} / {MAX_LEVEL}**\n\n"
            "**轉生條件**：角色達到滿級 **Lv.100**\n"
            "**轉生保留**：✅ 全部裝備、強化等級、礦鎬、金幣、星鑽、背包材料、副本通關、深淵紀錄、成就與稱號！\n"
            "**轉生重置**：等級重置為 `Lv.1`（保留所有已解鎖礦區與鍛造權限！）\n\n"
            f"🌟 **第 {next_rb} 次轉生永久加成**：\n"
            f"• 全戰鬥屬性倍率提升至 **`{next_mult}%`**（每次 +18%）\n"
            f"• 金幣與經驗獲取提升至 **`+{next_bonus}%`**（每次 +12%）\n"
            f"• 體力上限永久 **+5**，並立即獲得 **💎 +{bonus_gems:,} 星鑽**！"
        ),
        color=0xF1C40F,
    )
    embed.set_thumbnail(url=get_ui_asset_url("achievement_laurel"))
    embed.set_image(url=get_ui_asset_url("rebirth_banner"))
    return embed


def build_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📖 星界紀元 RPG 完整指南",
        description=(
            "一款專為 Discord 打造的長線養成 RPG！支援 **SQLite 即時自動存檔**，重啟永不掉檔，並全面搭配**免費開源奇幻圖庫插圖與裝備展示卡片**。\n"
            "所有指令皆可直接輸入 **`/`** 觸發，並支援按鈕快速操作："
        ),
        color=0x5865F2,
    )
    embed.set_thumbnail(url=get_ui_asset_url("combat_swords"))
    embed.set_image(url=get_ui_asset_url("help_banner"))
    embed.add_field(
        name="🌱 新手起步與日常",
        value=(
            "`/start` — 建立角色、選擇職業並領取新手禮包\n"
            "`/profile` — 查看角色面板、戰力、裝備與主城快捷按鈕\n"
            "`/daily` — 每日連續簽到 + 領取每日／每週任務獎勵\n"
            "`/expedition` — 派遣離線冒險（重啟亦持續計時領獎）"
        ),
        inline=False,
    )
    embed.add_field(
        name="⛏️ 挖礦、鍛造與裝備",
        value=(
            "`/mine` — 進入 6 大階梯礦區採礦（含礦區場景圖、連擊熱度與隨機奇遇）\n"
            "`/forge` — 升級 T1~T8 礦鎬、鍛造 T1~T6 套裝、強化裝備 `+1~+15`（絕不碎裝+保底）\n"
            "`/bag` / `/equip` — 管理裝備與材料背包，支援穿戴／鎖定／一鍵最強配裝\n"
            "`/inspect` — 公開展示指定裝備的圖鑑與詳細詞條卡片\n"
            "`/shop` — 物資店、6 小時限時折扣神秘商店、星界抽箱（含保底）與礦石出售"
        ),
        inline=False,
    )
    embed.add_field(
        name="⚔️ 副本、深淵、世界王與排行",
        value=(
            "`/dungeon` — 挑戰 8 大副本 × 3 種難度（首領立繪、回合制戰鬥／自動戰鬥／掃蕩）\n"
            "`/abyss` — 挑戰無限層數「無盡深淵」爬塔（每 5 層守門王大獎）\n"
            "`/boss` — 全伺服器共鬥「世界王」，全服共享血條、擊殺全員發獎\n"
            "`/class` / `/rebirth` — 二轉三轉覺醒（立繪進階）& 滿級轉生飛升\n"
            "`/achievements` / `/leaderboard` — 成就稱號永久加成 & 6 大排行榜"
        ),
        inline=False,
    )
    embed.set_footer(text=ASSET_CREDITS)
    return embed
