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


def build_workshop_embed(title: str, res: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title=_clamp_str(f"🔨 莉茲貝特工坊 — {title}", 256),
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_GOLD,
    )
    embed.set_thumbnail(url=_safe_url(assets.SAO_ASSET_REGISTRY.get("item_enhance_bright")))
    if "enhance_level" in res:
        embed.add_field(
            name="✨ 強化結果",
            value=f"目前等級：**+{res['enhance_level']}**｜保底祝福：`{res.get('enhance_pity', 0)}%`",
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


def build_shop_embed(res: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title="🛒 起始之鎮水晶與補給商店",
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_CYAN,
    )
    embed.set_thumbnail(url=_safe_url(assets.SAO_ASSET_REGISTRY.get("crystal_teleport")))
    if "col_remaining" in res:
        embed.add_field(name="💰 剩餘柯爾", value=f"{int(res['col_remaining']):,} 柯爾", inline=True)
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
