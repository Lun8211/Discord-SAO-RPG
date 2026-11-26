"""Tower, Exploration, Chest, Roguelike, Boss & Argo Intel Discord Embed builders."""

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


def build_tower_embed(floor_info: dict[str, Any]) -> discord.Embed:
    floor = int(floor_info.get("floor", 1))
    embed = discord.Embed(
        title=_clamp_str(
            f"🏰 第 {floor} 層【{floor_info.get('town_name', f'第 {floor} 層')}】— {floor_info.get('biome_name', '')}",
            256,
        ),
        description=_clamp_str(
            str(floor_info.get("flavor_desc") or floor_info.get("message", "")), 4096
        ),
        color=SAO_COLOR_GOLD if floor_info.get("is_milestone_boss") else SAO_COLOR_CYAN,
    )
    embed.set_image(url=_safe_url(assets.get_biome_banner_url(floor)))
    embed.set_thumbnail(url=_safe_url(assets.get_sao_boss_portrait_url(str(floor_info.get("boss_id", "")), int(floor_info.get("tier", 1)))))
    pct = int(floor_info.get("exploration_pct", 0))
    gate = "🔓 已開啟" if floor_info.get("boss_gate_unlocked") else "🔒 未開啟（需探索 100%）"
    embed.add_field(
        name="🧭 樓層進度",
        value=(
            f"探索度：`{pct}%` {hp_bar(pct, 100, 10)}\n"
            f"頭目房大門：{gate}\n"
            f"抗性穿透：`{float(floor_info.get('res_penetration', 0.0)) * 100:.1f}%`"
        ),
        inline=True,
    )
    embed.add_field(
        name="👑 守層頭目",
        value=(
            f"**{floor_info.get('boss_name', '守層頭目')}**\n"
            f"血條數：`{floor_info.get('boss_hp_bars', 4)}` 條｜"
            f"{'🚫 水晶無效化區' if floor_info.get('is_crystal_null') else '💎 水晶可用'}"
        ),
        inline=True,
    )
    fk = floor_info.get("server_first_kill")
    if isinstance(fk, dict):
        embed.add_field(
            name="🏅 全服首殺名人堂",
            value=f"隊長：{fk.get('leader_name')}｜尾刀（LA）：**{fk.get('la_user_name')}**",
            inline=False,
        )
    embed.set_footer(text="可使用下方按鈕切換區域、探索樓層、挑戰頭目或進入黑鐵宮地下迷宮！")
    return embed


def build_combat_embed(res: dict[str, Any]) -> discord.Embed:
    session = res.get("combat")
    boss = res.get("boss_state") or (getattr(session, "boss_state", None) if session else None)
    victory = bool(res.get("victory", False))
    defeat = bool(res.get("defeat", False))
    color = SAO_COLOR_EMERALD if victory else (SAO_COLOR_CRIMSON if defeat else SAO_COLOR_GOLD)

    title = getattr(session, "title", "⚔️ 艾恩葛朗特戰鬥") if session else "⚔️ 艾恩葛朗特戰鬥"
    logs = list(res.get("logs") or ([res.get("message", "")] if res.get("message") else []))
    embed = discord.Embed(
        title=_clamp_str(str(title), 256),
        description=_clamp_str("\n".join(logs[-6:]), 4096),
        color=color,
    )
    if boss is not None:
        embed.set_thumbnail(
            url=_safe_url(assets.get_sao_boss_portrait_url(boss.boss_id, max(1, (boss.floor - 1) // 10 + 1)))
        )
        bar_emoji = {"green": "🟩", "yellow": "🟨", "red": "🟥"}.get(boss.current_bar_color, "🟩")
        embed.add_field(
            name=f"👑 {boss.name}（階段 {boss.current_phase}）",
            value=(
                f"{bar_emoji} HP `{boss.current_hp:,}/{boss.max_hp:,}`（第 **{boss.current_bar}/{boss.hp_bars}** 條血）\n"
                f"{hp_bar(boss.current_hp, boss.max_hp, 14)}\n"
                f"破防槽：`{boss.stagger_current}/{boss.stagger_max}`{' 💥破防中！' if boss.is_broken else ''}"
                + (f"\n⚠️ 預告：{boss.telegraph_callout}" if boss.telegraph_active else "")
            ),
            inline=False,
        )
    elif session is not None:
        embed.add_field(
            name=f"{session.enemy_emoji} {session.enemy_name} (Lv.{session.enemy_level})",
            value=f"HP `{session.enemy_hp:,}/{session.enemy_max_hp:,}` {hp_bar(session.enemy_hp, session.enemy_max_hp, 12)}",
            inline=False,
        )

    if session is not None:
        embed.add_field(
            name="🛡️ 玩家狀態",
            value=(
                f"HP `{session.player_hp}/{session.player_max_hp}` {hp_bar(session.player_hp, session.player_max_hp, 10)}\n"
                f"SP `{session.player_sp}/{session.player_max_sp}`｜連段 `{session.combo_count}`｜第 `{session.turn}` 回合"
            ),
            inline=False,
        )
    return embed


def build_argo_intel_embed(intel: dict[str, Any]) -> discord.Embed:
    floor = int(intel.get("floor", 1))
    embed = discord.Embed(
        title=f"🐭 阿爾狗的情報屋 — 第 {floor} 層【{intel.get('boss_name', '')}】",
        description=_clamp_str(str(intel.get("message", "")), 4096),
        color=SAO_COLOR_PURPLE,
    )
    embed.set_thumbnail(
        url=_safe_url(assets.get_sao_boss_portrait_url(str(intel.get("boss_id", "")), max(1, (floor - 1) // 10 + 1)))
    )
    sk_lines = []
    for sk in list(intel.get("skills") or []):
        if sk.get("observed"):
            sk_lines.append(f"✅ **P{sk['phase']} {sk['name']}**（{sk['dmg_type']}）：{sk['telegraph']}")
        else:
            sk_lines.append(f"❓ **P{sk['phase']} ???**（尚未觀測）")
    embed.add_field(
        name=f"📖 頭目技能情報（{intel.get('observed_count', 0)}/{intel.get('total_skills', 0)}）",
        value=_clamp_str("\n".join(sk_lines) if sk_lines else "尚無情報", 1024),
        inline=False,
    )
    hof = list(intel.get("hall_of_fame") or [])[:5]
    if hof:
        hof_lines = [
            f"• **F{h['floor']}** {h['boss_name']} — 隊長 {h['leader_name']}｜尾刀 {h['la_user_name']}"
            for h in hof
        ]
        embed.add_field(name="🏆 全服首殺名人堂（近期）", value=_clamp_str("\n".join(hof_lines), 1024), inline=False)
    return embed


def build_roguelike_embed(res: dict[str, Any]) -> discord.Embed:
    run = res.get("roguelike")
    embed = discord.Embed(
        title=f"🏛️ 黑鐵宮地下迷宮（深度 {res.get('depth', getattr(run, 'depth', 1))}）",
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_PURPLE,
    )
    embed.set_image(url=_safe_url(assets.get_biome_banner_url(1)))
    embed.add_field(
        name="📊 迷宮狀態",
        value=f"積分：`{res.get('score', 0)}`｜代幣：`{res.get('tokens', 0)}`｜累計柯爾：`{res.get('col_earned', 0):,}`",
        inline=False,
    )
    nodes = list(res.get("nodes") or [])
    if nodes:
        nlines = [f"**{n['index']}. {n['name']}** — {n['desc']}" for n in nodes[:4]]
        embed.add_field(name="🔀 可選分歧路線", value=_clamp_str("\n".join(nlines), 1024), inline=False)
    return embed
