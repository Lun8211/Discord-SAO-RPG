"""Multiplayer Party Lobby, Co-op Raid HUD, World Boss, and PvP Duel Discord Embed builders."""

from __future__ import annotations

from typing import Any

import discord

from src.rpg import assets
from src.rpg.ui.embeds_core import (
    SAO_COLOR_CRIMSON,
    SAO_COLOR_CYAN,
    SAO_COLOR_EMERALD,
    SAO_COLOR_GOLD,
    SAO_COLOR_PURPLE,
    _clamp_str,
    _safe_url,
    hp_bar,
)


def build_party_lobby_embed(res: dict[str, Any]) -> discord.Embed:
    lobby = res.get("party") or res.get("lobby")
    floor = int(getattr(lobby, "floor", res.get("floor", 1)))
    pid = str(getattr(lobby, "party_id", res.get("party_id", "")))
    is_alliance = bool(getattr(lobby, "is_raid_alliance", False))
    title = f"🚩 {'大型攻略團大廳' if is_alliance else '真人組隊大廳'} — 第 {floor} 層（`{pid}`）"
    embed = discord.Embed(
        title=_clamp_str(title, 256),
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_CYAN,
    )
    embed.set_image(url=_safe_url(assets.get_biome_banner_url(floor)))
    if lobby is not None:
        lines = []
        for uid, m in list(lobby.members.items())[:15]:
            crown = "👑 " if uid == lobby.leader_id else ""
            rdy = "✅" if m.is_ready else "⏳"
            pot = " 🧪出藥" if m.potion_sharing else ""
            lines.append(f"{rdy} {crown}**{m.display_name}**（`{m.role}`／{m.weapon_style}／戰力 {m.combat_power:,}{pot}）")
        embed.add_field(
            name=f"👥 成員名單（{len(lobby.members)}/{lobby.max_size}｜模式：{lobby.boss_mode}）",
            value=_clamp_str("\n".join(lines) if lines else "尚無成員", 1024),
            inline=False,
        )
    embed.set_footer(text="所有真人玩家皆可直接點擊下方按鈕加入、切換職責、準備與開戰！")
    return embed


def build_coop_raid_embed(res: dict[str, Any]) -> discord.Embed:
    raid = res.get("raid")
    boss = res.get("boss_state") or res.get("boss") or (getattr(raid, "boss", None) if raid else None)
    victory = bool(res.get("victory", False))
    defeat = bool(res.get("defeat", False))
    color = SAO_COLOR_EMERALD if victory else (SAO_COLOR_CRIMSON if defeat else SAO_COLOR_GOLD)

    floor = int(getattr(raid, "floor", res.get("floor", 1)))
    turn = int(getattr(raid, "turn", res.get("turn", 1)))
    logs = list(res.get("logs") or ([res.get("message", "")] if res.get("message") else []))

    embed = discord.Embed(
        title=_clamp_str(
            f"⚔️ 第 {floor} 層多人共鬥頭目戰 — 第 {turn} 回合（Switch 連攜 x{getattr(raid, 'switch_chain', 0)}）",
            256,
        ),
        description=_clamp_str("\n".join(logs[-7:]), 4096),
        color=color,
    )
    if boss is not None:
        embed.set_thumbnail(
            url=_safe_url(assets.get_sao_boss_portrait_url(boss.boss_id, max(1, (boss.floor - 1) // 10 + 1)))
        )
        bar_e = {"green": "🟩", "yellow": "🟨", "red": "🟥"}.get(boss.current_bar_color, "🟩")
        embed.add_field(
            name=f"👑 {boss.name}（階段 {boss.current_phase}｜第 {boss.current_bar}/{boss.hp_bars} 條血）",
            value=(
                f"{bar_e} HP `{boss.current_hp:,}/{boss.max_hp:,}`\n"
                f"{hp_bar(boss.current_hp, boss.max_hp, 14)}\n"
                f"破防槽 `{boss.stagger_current}/{boss.stagger_max}`{' 💥BREAK!' if boss.is_broken else ''}"
                + (f"\n⚠️ {boss.telegraph_callout}" if boss.telegraph_active else "")
            ),
            inline=False,
        )
    if raid is not None:
        mlines = []
        for uid, m in list(raid.members.items())[:12]:
            vg = "🛡️前排 " if uid == raid.vanguard_user_id else ""
            acted = "✅" if uid in raid.pending_actions else ("💤" if m.is_sleeping else "⏳")
            st = "💀倒地" if m.is_downed else ("🏃撤退" if m.is_retreated else f"HP {m.hp}/{m.max_hp} SP {m.sp}/{m.max_sp}")
            mlines.append(f"{acted} {vg}**{m.display_name}**（{m.role}）：{st}｜輸出 `{m.damage_dealt:,}`")
        embed.add_field(name="👥 真人攻略團狀態", value=_clamp_str("\n".join(mlines), 1024), inline=False)
    embed.set_footer(text="全員鎖定指令後立即結算；25 秒逾時自動防禦不卡死！")
    return embed


def build_world_boss_embed(res: dict[str, Any]) -> discord.Embed:
    wb = res.get("world_boss")
    embed = discord.Embed(
        title=_clamp_str(f"🌍 全服樓層世界王 — {getattr(wb, 'name', '世界王')}", 256),
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_PURPLE if res.get("defeated") else SAO_COLOR_CRIMSON,
    )
    if wb is not None:
        embed.set_thumbnail(url=_safe_url(assets.get_sao_boss_portrait_url(wb.boss_id, wb.tier)))
        embed.add_field(
            name=f"第 {wb.floor} 層世界王血量",
            value=f"HP `{wb.current_hp:,}/{wb.max_hp:,}`\n{hp_bar(wb.current_hp, wb.max_hp, 14)}",
            inline=False,
        )
    rankings = list(res.get("rankings") or [])[:5]
    if rankings:
        rlines = [f"**#{i + 1}** {r['display_name']} — 總傷害 `{int(r['total_damage']):,}`" for i, r in enumerate(rankings)]
        embed.add_field(name="🏆 傷害貢獻前 5 名", value=_clamp_str("\n".join(rlines), 1024), inline=False)
    return embed


def build_duel_embed(res: dict[str, Any]) -> discord.Embed:
    duel = res.get("duel")
    embed = discord.Embed(
        title=f"⚔️ 艾恩葛朗特決鬥（{getattr(duel, 'mode', 'first_strike')}）",
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_GOLD if res.get("finished") else SAO_COLOR_CYAN,
    )
    if duel is not None:
        embed.add_field(
            name=f"🗡️ {duel.challenger_name}",
            value=f"HP `{duel.challenger_hp}/{duel.challenger_max_hp}` {hp_bar(duel.challenger_hp, duel.challenger_max_hp, 10)}",
            inline=True,
        )
        embed.add_field(
            name=f"🛡️ {duel.target_name}",
            value=f"HP `{duel.target_hp}/{duel.target_max_hp}` {hp_bar(duel.target_hp, duel.target_max_hp, 10)}",
            inline=True,
        )
    embed.set_footer(text="圈內安全決鬥不致死、不變色（保持綠色光標）！")
    return embed
