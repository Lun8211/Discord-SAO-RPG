"""Workshop, Cooking, Shop, Marketplace, Guild, Quests, Expeditions & Achievements Embed builders."""

from __future__ import annotations

from typing import Any

import discord

from src.rpg import assets
from src.rpg.ui.embeds_core import (
    SAO_COLOR_CYAN,
    SAO_COLOR_EMERALD,
    SAO_COLOR_GOLD,
    SAO_COLOR_PURPLE,
    _clamp_str,
    _safe_url,
)


def build_workshop_embed(
    title_or_profile: str | dict[str, Any],
    res_or_gear: Any = None,
    materials: dict[str, int] | None = None,
    *,
    selected_item: Any = None,
    notice: str | None = None,
    protection_on: bool = False,
) -> discord.Embed:
    """Build either a Lisbeth Workshop action result embed `(title, res)` or interactive dashboard `(profile, gear, materials)`."""
    if isinstance(title_or_profile, dict):
        profile = title_or_profile
        gear_list = list(res_or_gear if isinstance(res_or_gear, (list, tuple)) else (profile.get("equipment") or []))
        inv = dict(materials if isinstance(materials, dict) else (profile.get("inventory") or {}))
        col = int(profile.get("col", 0))
        floor = int(profile.get("current_floor", 1))
        bs_lv = int((profile.get("life_skills") or {}).get("blacksmithing", {}).get("level", 1))
        f48_note = "｜🔥 **第 48 層林達斯加成生效**" if floor == 48 else ""
        desc = (
            f"💰 持有柯爾：**{col:,}**｜🔨 鍛造熟練度：**Lv.{bs_lv}**{f48_note}\n"
            f"🧿 保護符（陽壽籤）：**{'已開啟' if protection_on else '關閉'}**（持有 `{inv.get('protection_talisman', 0)}` 張）"
        )
        if notice:
            desc = f"{notice}\n\n{desc}"
        embed = discord.Embed(
            title=f"🔨 莉茲貝特工坊 — {profile.get('display_name', '攻略者')}",
            description=_clamp_str(desc, 4096),
            color=SAO_COLOR_GOLD,
        )
        embed.set_thumbnail(url=_safe_url(assets.SAO_ASSET_REGISTRY.get("item_bright_crystal")))

        target = selected_item if selected_item is not None else (gear_list[0] if gear_list else None)
        if target is not None:
            stars = f" ★{getattr(target, 'temper_level', 0)}" if getattr(target, "temper_level", 0) else ""
            sock = getattr(target, "socket_crystal_id", "") or "無"
            lock_tag = " 🔒已鎖定" if getattr(target, "is_locked", False) else ""
            eq_tag = " 🛡️穿戴中" if getattr(target, "is_equipped", False) else ""
            aff_str = (
                "、".join(f"`{k}` +{v}" for k, v in (getattr(target, "affixes", {}) or {}).items())
                or "無詞綴"
            )
            embed.add_field(
                name=f"⚔️ 選定裝備 #{target.id} — {target.name} +{target.enhance_level}{stars}",
                value=_clamp_str(
                    f"階級：`T{target.tier}`｜品質：`{target.rarity}`｜欄位：`{target.slot}`{eq_tag}{lock_tag}\n"
                    f"屬性：ATK `{target.atk}`｜DEF `{target.def_}`｜HP `{target.hp}`｜戰力 `{target.power_score}`\n"
                    f"保底祝福：`{target.enhance_pity}%`｜鑲嵌結晶：`{sock}`\n"
                    f"詞綴：{aff_str}",
                    1024,
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="⚔️ 選定裝備",
                value="背包中尚無裝備，可透過下方鍛造、探索爬塔或城鎮商店取得！",
                inline=False,
            )

        mat_summary = (
            f"🔩 精鐵碎塊：`{inv.get('forge_scrap', 0)}`｜"
            f"✨ 輝石碎/晶：`{inv.get('bright_crystal_shard', 0)}/{inv.get('bright_crystal', 0)}`\n"
            f"🌑 暗石碎/晶/純：`{inv.get('dark_crystal_shard', 0)}/{inv.get('dark_crystal', 0)}/{inv.get('dark_crystal_pure', 0)}`\n"
            f"💎 魔石(翻/替/毛/擴)：`{inv.get('reroll_stone', 0)}/{inv.get('swap_stone', 0)}/{inv.get('refine_stone', 0)}/{inv.get('expand_stone', 0)}`"
        )
        embed.add_field(name="📦 工坊素材庫存", value=_clamp_str(mat_summary, 1024), inline=False)
        embed.set_footer(text="支援 5 軸強化：強化(+15) • 鍛星(★5) • 升階(T10) • 升品 • 結晶鑲嵌 • 魔石洗詞綴 • 裝備分解")
        return embed

    # Action result embed mode: build_workshop_embed(title: str, res: dict)
    res = res_or_gear if isinstance(res_or_gear, dict) else {}
    embed = discord.Embed(
        title=_clamp_str(f"🔨 莉茲貝特工坊 — {title_or_profile}", 256),
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_GOLD,
    )
    embed.set_thumbnail(url=_safe_url(assets.SAO_ASSET_REGISTRY.get("item_bright_crystal")))
    if "enhance_level" in res:
        embed.add_field(
            name="✨ 強化結果",
            value=f"目前等級：**+{res['enhance_level']}**｜保底祝福：`{res.get('enhance_pity', 0)}%`",
            inline=False,
        )
    elif "end_level" in res:
        embed.add_field(
            name="⚡ 批量強化結果",
            value=f"強化：`+{res.get('start_level', 0)} → +{res['end_level']}`｜嘗試 `{res.get('attempts', 0)}` 次｜花費 `{int(res.get('col_spent', 0)):,}` 柯爾",
            inline=False,
        )
    if "temper_level" in res:
        embed.add_field(
            name="⭐ 鍛星淬鍊結果",
            value=f"目前星級：**★{res['temper_level']}/5**｜花費 `{int(res.get('col_spent', 0)):,}` 柯爾",
            inline=False,
        )
    if "new_tier" in res:
        embed.add_field(
            name="⬆️ 裝備升階結果",
            value=f"階級晉升：**T{res.get('old_tier')} → T{res['new_tier']}**",
            inline=False,
        )
    if "new_rarity" in res:
        embed.add_field(
            name="🌟 裝備升品結果",
            value=f"品質晉升：**{res.get('old_rarity')} → {res['new_rarity']}**",
            inline=False,
        )
    if "crystal_id" in res or "returned_crystal_id" in res:
        embed.add_field(
            name="💠 結晶插槽狀態",
            value=f"目前鑲嵌：`{res.get('crystal_id') or '無'}`｜退還結晶：`{res.get('returned_crystal_id') or '無'}`",
            inline=False,
        )
    return embed


def build_cooking_embed(res: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title="🍲 艾恩葛朗特料理與一大鍋",
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_EMERALD,
    )
    embed.set_thumbnail(url=_safe_url(assets.SAO_ASSET_REGISTRY.get("item_dish")))
    if res.get("stew_id"):
        embed.add_field(
            name="🥘 共享一大鍋編號",
            value=f"`{res['stew_id']}`（剩餘份數：`{res.get('servings', res.get('remaining_charges', 0))}`）",
            inline=False,
        )
    return embed


def build_shop_embed(
    res: dict[str, Any],
    *,
    category_label: str | None = None,
    catalog_lines: list[str] | None = None,
) -> discord.Embed:
    title = f"🛒 艾恩葛朗特商會商店 — {category_label}" if category_label else "🛒 起始之鎮水晶、裝備與補給商店"
    embed = discord.Embed(
        title=_clamp_str(title, 256),
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_CYAN,
    )
    embed.set_thumbnail(url=_safe_url(assets.SAO_ASSET_REGISTRY.get("item_crystal_blue")))
    if "col_remaining" in res:
        embed.add_field(name="💰 剩餘柯爾", value=f"{int(res['col_remaining']):,} 柯爾", inline=True)
    if "tickets_remaining" in res:
        embed.add_field(name="🎟️ 秘寶抽取券", value=f"{int(res['tickets_remaining'])} 張", inline=True)
    if "pity_legendary" in res:
        embed.add_field(name="✨ 傳說保底進度", value=f"{int(res['pity_legendary'])}/10", inline=True)
    pulls = list(res.get("pulls") or [])
    if pulls:
        plines = [f"• **{p.get('name')}**（T{p.get('tier', 1)}／{p.get('slot')}／{p.get('rarity')}）" for p in pulls[:8]]
        embed.add_field(name="🎰 秘寶箱開出裝備", value=_clamp_str("\n".join(plines), 1024), inline=False)
    eq_res = res.get("equipment_result")
    if isinstance(eq_res, dict) and eq_res.get("item_name"):
        embed.add_field(
            name="🛡️ 獲得裝備",
            value=f"`#{eq_res.get('item_uid', '-')}` **{eq_res['item_name']}**（T{eq_res.get('tier', 1)}／{eq_res.get('slot', '')}／{eq_res.get('rarity', '')}）",
            inline=False,
        )
    if catalog_lines:
        embed.add_field(name="📋 商會貨架目錄", value=_clamp_str("\n".join(catalog_lines[:10]), 1024), inline=False)
    embed.set_footer(text="支援購買藥水水晶、強化魔石、鑲嵌結晶、裝備補給箱、樓層武器裝備與秘寶抽獎！")
    return embed


def build_market_embed(res: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title="🏪 艾恩葛朗特玩家交易市集（原子託管）",
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_GOLD,
    )
    listings = list(res.get("listings") or [])[:10]
    if listings:
        lines = [
            f"`#{lt.id}` **{lt.item_name}**（{lt.rarity}／{lt.slot}）— **{lt.price_col:,} 柯爾**（賣家：{lt.seller_name}）"
            for lt in listings
        ]
        embed.add_field(name="📋 上架商品列表", value=_clamp_str("\n".join(lines), 1024), inline=False)
    return embed


def build_guild_embed(res: dict[str, Any]) -> discord.Embed:
    g = res.get("guild")
    title = f"🏰 公會系統 — [{g.tag}] {g.name}" if g is not None else "🏰 艾恩葛朗特公會總部"
    embed = discord.Embed(
        title=_clamp_str(title, 256),
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_PURPLE,
    )
    if g is not None:
        embed.add_field(
            name="📊 公會資訊",
            value=(
                f"等級：`Lv.{g.level}`｜成員：`{g.member_count}/{g.max_members}`\n"
                f"公會金庫：`{g.vault_col:,} 柯爾`｜榮耀值：`{g.merit_points:,}`"
            ),
            inline=False,
        )
    logs = list(res.get("logs") or [])[:5]
    if logs:
        embed.add_field(
            name="📜 近期公會紀錄",
            value=_clamp_str("\n".join(f"• {lg.get('detail', '')}" for lg in logs), 1024),
            inline=False,
        )
    return embed


def build_quests_embed(res: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title="📋 任務、主線劇情與離線遠征",
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_CYAN,
    )
    daily = list(res.get("daily") or [])[:5]
    if daily:
        dlines = [
            f"{'✅' if q.get('claimed') else '📌'} **{q.get('name')}** (`{q.get('id')}`) — `{q.get('progress', 0)}/{q.get('target', 1)}`"
            for q in daily
        ]
        embed.add_field(name="📅 每日任務", value=_clamp_str("\n".join(dlines), 1024), inline=False)
    weekly = list(res.get("weekly") or [])[:4]
    if weekly:
        wlines = [
            f"{'✅' if q.get('claimed') else '📌'} **{q.get('name')}** (`{q.get('id')}`) — `{q.get('progress', 0)}/{q.get('target', 1)}`"
            for q in weekly
        ]
        embed.add_field(name="🗓️ 每週任務", value=_clamp_str("\n".join(wlines), 1024), inline=False)
    return embed
