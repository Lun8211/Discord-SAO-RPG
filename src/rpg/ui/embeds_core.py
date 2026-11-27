"""Core SAO Aincrad Discord Embed builders (Profile, Skills, Bag, Monument, Yui, Leaderboards, Help)."""

from __future__ import annotations

from typing import Any

import discord

from src.rpg import assets

SAO_COLOR_CYAN = 0x22D3EE
SAO_COLOR_GOLD = 0xF59E0B
SAO_COLOR_CRIMSON = 0xEF4444
SAO_COLOR_EMERALD = 0x10B981
SAO_COLOR_PURPLE = 0x8B5CF6
SAO_COLOR_SLATE = 0x64748B


def hp_bar(current: int, maximum: int, length: int = 12) -> str:
    if maximum <= 0:
        return "░" * length
    ratio = max(0.0, min(1.0, current / maximum))
    filled = round(ratio * length)
    return "█" * filled + "░" * (length - filled)


def _clamp_str(text: str, max_len: int) -> str:
    s = str(text or "")
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _safe_url(url: str | None) -> str:
    u = str(url or "")
    if u.startswith("https://") and ".svg" not in u.lower():
        return u
    return assets.SAO_ASSET_REGISTRY["biome_t1_plains"]


def build_error_embed(title: str, message: str) -> discord.Embed:
    embed = discord.Embed(
        title=_clamp_str(f"⚠️ {title}", 256),
        description=_clamp_str(message, 4096),
        color=SAO_COLOR_CRIMSON,
    )
    embed.set_footer(text="卡迪納爾系統通知 • Sword Art Online: Aincrad")
    return embed


def build_start_embed(result: dict[str, Any]) -> discord.Embed:
    style = str(result.get("weapon_style", "sword"))
    embed = discord.Embed(
        title="⚔️ Link Start！歡迎登入浮游城艾恩葛朗特",
        description=_clamp_str(str(result.get("message", "")), 4096),
        color=SAO_COLOR_CYAN,
    )
    embed.set_thumbnail(url=_safe_url(assets.get_weapon_style_portrait_url(style)))
    embed.set_image(url=_safe_url(assets.get_biome_banner_url(1)))
    embed.add_field(name="🗺️ 出生據點", value="第 1 層・起始之鎮（圈內安全區）", inline=True)
    embed.add_field(name="🗡️ 武器流派", value=style, inline=True)
    embed.add_field(name="💰 初始資金", value=f"{result.get('col', 500):,} 柯爾", inline=True)
    embed.set_footer(text="使用 /tower 開始爬塔，或 /party 召集真人隊友攻略頭目！")
    return embed


def build_profile_embed(profile: dict[str, Any]) -> discord.Embed:
    style = str(profile.get("weapon_style", "sword"))
    floor = int(profile.get("current_floor", 1))
    stats = profile.get("stats")
    cursor = str(profile.get("cursor_color", "green"))
    cursor_icon = {"green": "🟢 綠標", "orange": "🟠 橙標", "red": "🔴 紅標"}.get(cursor, "🟢 綠標")

    title_str = f"🪪 【{profile.get('display_name', '攻略者')}】Lv.{profile.get('level', 1)}"
    if profile.get("active_title"):
        title_str += f"｜{profile['active_title']}"

    embed = discord.Embed(
        title=_clamp_str(title_str, 256),
        description=(
            f"📍 **第 {floor} 層**（{profile.get('zone', 'town')}）｜"
            f"最高通關：**F{profile.get('highest_cleared_floor', 0)}**｜"
            f"光標：{cursor_icon}｜模式：`{profile.get('game_mode', 'standard')}`"
        ),
        color=SAO_COLOR_CYAN if cursor == "green" else SAO_COLOR_CRIMSON,
    )
    embed.set_thumbnail(url=_safe_url(assets.get_weapon_style_portrait_url(style)))
    embed.set_image(url=_safe_url(assets.get_biome_banner_url(floor)))

    max_hp = int(getattr(stats, "max_hp", profile.get("max_hp", 100)))
    max_sp = int(getattr(stats, "max_sp", profile.get("max_sp", 100)))
    hp_val = int(profile.get("hp", max_hp))
    sp_val = int(profile.get("sp", max_sp))
    atk_val = int(getattr(stats, "atk", 10))
    def_val = int(getattr(stats, "defense", 5))
    spd_val = int(getattr(stats, "spd", 100))

    embed.add_field(
        name="❤️ 狀態與資源",
        value=(
            f"HP `{hp_val}/{max_hp}` {hp_bar(hp_val, max_hp, 8)}\n"
            f"SP `{sp_val}/{max_sp}` {hp_bar(sp_val, max_sp, 8)}\n"
            f"💰 柯爾：`{int(profile.get('col', 0)):,}`｜⚡ 戰力：`{int(profile.get('combat_power', 0)):,}`"
        ),
        inline=True,
    )
    embed.add_field(
        name="⚔️ 戰鬥屬性（無魔法純物理）",
        value=(
            f"ATK `{atk_val}`｜DEF `{def_val}`｜SPD `{spd_val}`\n"
            f"STR `{profile.get('str_stat', 5)}` AGI `{profile.get('agi_stat', 5)}` "
            f"VIT `{profile.get('vit_stat', 5)}` DEX `{profile.get('dex_stat', 5)}` LUK `{profile.get('luk_stat', 5)}`\n"
            f"未分配點數：屬性 `{profile.get('stat_points', 0)}`｜天賦 `{profile.get('talent_points', 0)}`"
        ),
        inline=True,
    )
    if stats is not None:
        embed.add_field(
            name="🛡️ 四軸抗性（斬/刺/打/龍）",
            value=(
                f"斬 `{stats.res_slash * 100:.1f}%`｜刺 `{stats.res_pierce * 100:.1f}%`｜"
                f"打 `{stats.res_blunt * 100:.1f}%`｜龍 `{stats.res_dragon * 100:.1f}%`\n"
                f"瘴氣：`{profile.get('miasma_stacks', 0)}` 層｜連勝：`{profile.get('survival_streak', 0)}`｜轉生：`{profile.get('rebirth_count', 0)}`"
            ),
            inline=False,
        )
    embed.set_footer(text="SAO 艾恩葛朗特 100 層攻略系統 • 卡迪納爾終端")
    return embed


def build_skills_embed(profile: dict[str, Any], content: Any) -> discord.Embed:
    style = str(profile.get("weapon_style", "sword"))
    slots = list(profile.get("skill_slots") or [])
    uniques = list(profile.get("unique_skills") or [])
    max_slots = 4 if uniques else 3
    lines = []
    for idx, sid in enumerate(slots, 1):
        spec = content.sword_skills.get(sid, {})
        lines.append(
            f"**{idx}. {spec.get('name', sid)}**（`{sid}`）— "
            f"倍率 `{spec.get('damage_mult', 1.0)}x`｜SP `{spec.get('sp_cost', 0)}`｜CD `{spec.get('cooldown_turns', 0)}`"
        )
    embed = discord.Embed(
        title=f"⚔️ 劍技與天賦樹 — {profile.get('display_name', '攻略者')}",
        description=(
            f"目前流派：`{style}`｜獨有劍技：`{', '.join(uniques) if uniques else '尚未覺醒（第 50 層解鎖）'}`\n"
            f"已裝備劍技欄位（{len(slots)}/{max_slots}）：\n" + ("\n".join(lines) if lines else "尚未裝備劍技")
        ),
        color=SAO_COLOR_PURPLE,
    )
    embed.set_thumbnail(url=_safe_url(assets.get_weapon_style_portrait_url(style)))
    talents = profile.get("talents") or {}
    t_str = ", ".join(f"`{k}` Lv.{v}" for k, v in talents.items()) if talents else "尚未配點"
    embed.add_field(
        name=f"🌟 天賦配置（剩餘點數：{profile.get('talent_points', 0)}）",
        value=_clamp_str(t_str, 1024),
        inline=False,
    )
    embed.set_footer(text="於圈內安全區可免費重置天賦；頭目戰中禁止洗點或更換劍技。")
    return embed


def build_bag_embed(profile: dict[str, Any], content: Any) -> discord.Embed:
    eqs = list(profile.get("equipment") or [])
    inv = dict(profile.get("inventory") or {})
    equipped = [e for e in eqs if getattr(e, "is_equipped", False)]
    unequipped = [e for e in eqs if not getattr(e, "is_equipped", False)]

    def _fmt_gear(e: Any) -> str:
        stars = f" ★{e.temper_level}" if getattr(e, "temper_level", 0) > 0 else ""
        sock_id = str(getattr(e, "socket_crystal_id", "") or "")
        sock = " 💠" if sock_id else ""
        lock = " 🔒" if getattr(e, "is_locked", False) else ""
        cp = int(getattr(e, "power_score", 0))
        return f"`#{e.id}` **{e.name}** +{e.enhance_level}{stars}{sock}（T{e.tier}/{e.slot}/{e.rarity}｜⚡{cp}）{lock}"

    embed = discord.Embed(
        title=f"🎒 裝備欄與道具背包 — {profile.get('display_name', '攻略者')}",
        description=(
            f"💰 柯爾：`{int(profile.get('col', 0)):,}`｜"
            f"⚡ 綜合戰力：`{int(profile.get('combat_power', 0)):,}`｜"
            f"裝備空間：`{len(unequipped)}/80`｜待領信箱：`{profile.get('pending_loot_count', 0)}` 件"
        ),
        color=SAO_COLOR_GOLD,
    )
    eq_lines = [_fmt_gear(e) for e in equipped[:8]]
    embed.add_field(
        name="🛡️ 目前穿戴（8 欄位）",
        value=_clamp_str("\n".join(eq_lines) if eq_lines else "尚未穿戴裝備", 1024),
        inline=False,
    )
    bag_lines = [_fmt_gear(e) for e in unequipped[:10]]
    embed.add_field(
        name=f"📦 背包裝備（前 {min(len(unequipped), 10)}/{len(unequipped)} 件）",
        value=_clamp_str("\n".join(bag_lines) if bag_lines else "背包空空如也", 1024),
        inline=False,
    )

    # Prioritize crates, socket crystals, enhance crystals, magic stones, then potions/materials
    priority_cats = ("supply_crate", "socket_crystal", "enhance", "magic_stone", "crystal", "potion")
    inv_items = [(iid, qty) for iid, qty in inv.items() if int(qty) > 0]
    inv_items.sort(
        key=lambda kv: (
            priority_cats.index(str(content.items_crystals.get(kv[0], {}).get("category", "")))
            if str(content.items_crystals.get(kv[0], {}).get("category", "")) in priority_cats
            else 99,
            kv[0],
        )
    )
    inv_lines = []
    for iid, qty in inv_items[:14]:
        iname = content.items_crystals.get(iid, {}).get("name", iid)
        inv_lines.append(f"• {iname} (`{iid}`) x**{qty}**")
    embed.add_field(
        name="💎 水晶／鑲嵌石／補給箱／素材快取袋",
        value=_clamp_str("\n".join(inv_lines) if inv_lines else "尚無消耗品或素材", 1024),
        inline=False,
    )
    embed.set_footer(text="使用下方選單穿戴、一鍵最強、鎖定、分解或直接切換至莉茲貝特工坊！")
    return embed


def build_monument_embed(data: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title="🪦 黑鐵宮・生命之碑（Monument of Life）",
        description=_clamp_str(str(data.get("message", "")), 4096),
        color=SAO_COLOR_SLATE,
    )
    embed.set_image(url=_safe_url(assets.get_biome_banner_url(1)))
    entries = list(data.get("entries") or [])[:8]
    lines = [
        f"• **[{e.get('event_type')}]** {e.get('display_name')} — 第 {e.get('floor')} 層（{e.get('cause')}）"
        for e in entries
    ]
    embed.add_field(
        name="📜 近期生死紀錄",
        value=_clamp_str("\n".join(lines) if lines else "目前全體攻略者平安健在！", 1024),
        inline=False,
    )
    return embed


def build_yui_embed(data: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title=f"👧 結衣終端機 MHCP-001（{data.get('unlocked_count', 0)}/{data.get('total_count', 7)}）",
        description=_clamp_str(str(data.get("message", "")), 4096),
        color=SAO_COLOR_CYAN,
    )
    for entry in list(data.get("entries") or [])[:7]:
        status = "🔓" if entry.get("unlocked") else "🔒"
        embed.add_field(
            name=_clamp_str(f"{status} {entry.get('code')} — {entry.get('title')}", 256),
            value=_clamp_str(str(entry.get("content", "")), 500),
            inline=False,
        )
    return embed


def build_leaderboard_embed(data: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆 艾恩葛朗特・{data.get('title', '排行榜')}",
        description=_clamp_str(str(data.get("message", "")), 4096),
        color=SAO_COLOR_GOLD,
    )
    entries = list(data.get("entries") or [])[:10]
    cat = str(data.get("category", "power"))
    lines: list[str] = []
    for row in entries:
        rk = row.get("rank", 1)
        if cat == "guild":
            lines.append(
                f"**#{rk}** [{row.get('tag')}] **{row.get('name')}** — Lv.{row.get('level')}｜榮耀 `{row.get('merit_points')}`｜金庫 `{row.get('vault_col'):,}`"
            )
        else:
            lines.append(
                f"**#{rk}** **{row.get('display_name')}** — F{row.get('highest_cleared_floor')}｜Lv.{row.get('level')}｜戰力 `{row.get('combat_power'):,}`｜柯爾 `{row.get('col'):,}`"
            )
    embed.add_field(
        name="📊 排行名單",
        value=_clamp_str("\n".join(lines) if lines else "目前尚無排行資料。", 1024),
        inline=False,
    )
    return embed


def build_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⚔️ 刀劍神域（SAO）艾恩葛朗特 100 層多人共鬥 RPG 指南",
        description=(
            "歡迎進入浮游城艾恩葛朗特！本遊戲採 **JSON 資料驅動 100 層爬塔**、"
            "**14 層專屬多階段頭目（含每 10 層與 F1/25/74/75/100）**、"
            "**純物理劍技系統（無魔法）** 與 **真人即時多人共鬥／交換（Switch）**！\n"
            "✨ 擊殺怪物、開箱或通關後將直接顯示 **🧭 繼續探索／挑戰頭目／一鍵換裝** 按鈕，無須重複輸入 `/tower`！"
        ),
        color=SAO_COLOR_CYAN,
    )
    embed.set_image(url=_safe_url(assets.get_biome_banner_url(100)))
    embed.add_field(
        name="🏰 爬塔與無縫戰鬥指令",
        value=(
            "`/start` 創角（附贈流派初始武器）｜`/profile` 角色面板｜"
            "`/tower` 100 層連續探索／秘境／地下迷宮／傳送｜"
            "`/boss` 頭目戰／世界王／阿爾狗情報｜`/skills` 劍技／流派／天賦"
        ),
        inline=False,
    )
    embed.add_field(
        name="🤝 真人多人共鬥與社交",
        value=(
            "`/party` 組隊大廳／攻略團／Switch 共鬥／全員掉裝／救援｜"
            "`/guild` 公會／倉庫／集結｜`/market` 玩家交易市集｜`/duel` 圈內決鬥"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔨 5 軸裝備養成、互動工坊與終局",
        value=(
            "`/bag` `/equip` 互動式穿戴／一鍵最強／批量分解｜"
            "`/forge` 莉茲貝特互動工坊（鍛造／+15 強化／★5 鍛星／升階 T10／升品／鑲嵌結晶／強化轉移／魔石洗詞綴）｜"
            "`/shop` 分類商會（水晶／強化石／鑲嵌結晶／裝備補給箱／樓層武器裝備／秘寶抽獎）｜"
            "`/cook` `/mine` `/daily` `/expedition` `/achievements` `/leaderboard` `/rebirth`"
        ),
        inline=False,
    )
    embed.set_footer(text="提示：/p 動漫梗圖指令完整保留獨立運作 • Link Start!")
    return embed
