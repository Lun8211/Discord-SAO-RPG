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


_RARITY_LABELS: dict[str, str] = {
    "plain": "⚪普通",
    "fine": "🟢上品",
    "rare": "🔵極品",
    "set": "🟣珍品",
    "legendary": "🟠傳說",
    "named": "🌟名品",
}


def _format_gear_drop_line(drop: dict[str, Any]) -> str:
    r_zh = _RARITY_LABELS.get(str(drop.get("rarity", "plain")).lower(), str(drop.get("rarity", "")))
    name = str(drop.get("item_name") or getattr(drop.get("item"), "name", "裝備"))
    slot = str(drop.get("slot") or getattr(drop.get("item"), "slot", ""))
    tier = drop.get("tier") or getattr(drop.get("item"), "tier", None)
    meta = f"（T{tier}/{slot}）" if (tier and slot) else (f"（{slot}）" if slot else "")
    status = str(drop.get("status", "granted"))
    if status == "pending_mailbox":
        return f"• {r_zh} **{name}**{meta} 📬 已送至待領信箱"
    if status in ("filtered", "auto_filtered"):
        scol = int(drop.get("salvage_col", 0))
        return f"• {r_zh} ~~{name}~~{meta} ♻️ 過濾折換 `{scol}` 柯爾"
    uid = drop.get("item_uid")
    uid_tag = f"`#{uid}` " if uid is not None else ""
    return f"• {uid_tag}{r_zh} **{name}**{meta}"


def _format_item_drops(items: dict[str, Any] | None) -> str:
    if not isinstance(items, dict) or not items:
        return ""
    parts = [f"`{k}` x{v}" for k, v in list(items.items())[:8] if int(v) > 0]
    return "、".join(parts)


def build_combat_embed(
    res: dict[str, Any],
    *,
    floor_info: dict[str, Any] | None = None,
) -> discord.Embed:
    session = res.get("combat")
    boss = res.get("boss_state") or (getattr(session, "boss_state", None) if session else None)
    victory = bool(res.get("victory", False))
    defeat = bool(res.get("defeat", False))
    retreated = bool(res.get("retreated", False))
    is_chest = res.get("action") in ("open", "leave", "inspect") and not res.get("in_combat")
    color = (
        SAO_COLOR_EMERALD
        if (victory or (is_chest and res.get("action") == "open"))
        else (SAO_COLOR_CRIMSON if defeat else (SAO_COLOR_CYAN if retreated else SAO_COLOR_GOLD))
    )

    if session is not None:
        title = str(getattr(session, "title", "⚔️ 艾恩葛朗特戰鬥"))
    elif res.get("chest") is not None or is_chest:
        title = f"🎁 第 {res.get('floor', 1)} 層・寶箱探索"
    else:
        title = "⚔️ 艾恩葛朗特戰鬥"

    raw_logs = [str(line) for line in (res.get("logs") or []) if line]
    msg = str(res.get("message") or "").strip()
    display_lines = raw_logs[-6:] if raw_logs else []
    if msg and msg not in display_lines:
        display_lines.append(msg)
    if not display_lines:
        display_lines = ["⚔️ 戰鬥資訊更新。"]

    embed = discord.Embed(
        title=_clamp_str(title, 256),
        description=_clamp_str("\n".join(display_lines), 4096),
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

    # Render Victory Loot & Equipment Drops!
    rewards = res.get("rewards")
    if isinstance(rewards, dict):
        rlines: list[str] = [
            f"✨ 經驗 `+{int(rewards.get('exp_gain', 0)):,}`｜💰 柯爾 `+{int(rewards.get('col_gain', 0)):,}`"
            + (f"｜⬆️ **升級 +{rewards['levels_gained']}！**" if int(rewards.get("levels_gained", 0)) > 0 else "")
        ]
        if rewards.get("is_first_kill"):
            rlines.append("👑 **【全服首殺榮譽達成！】**")
        if rewards.get("unlocked_next_floor"):
            rlines.append(f"🔓 已解鎖 **第 {rewards['unlocked_next_floor']} 層** 轉移門！")
        if rewards.get("boss_gate_unlocked") and not rewards.get("unlocked_next_floor"):
            rlines.append("🚪 本層 **頭目房大門已開啟**，可直接挑戰守層頭目！")
        item_str = _format_item_drops(rewards.get("items"))
        if item_str:
            rlines.append(f"📦 素材／道具：{item_str}")
        drops = list(rewards.get("equipment_drops") or [])
        if drops:
            rlines.append("⚔️ **掉落裝備：**")
            for d in drops[:6]:
                if isinstance(d, dict):
                    rlines.append(_format_gear_drop_line(d))
        embed.add_field(
            name="🏆 戰利品與裝備掉落",
            value=_clamp_str("\n".join(rlines), 1024),
            inline=False,
        )
    elif is_chest and res.get("action") == "open":
        clines: list[str] = [f"💰 柯爾 `+{int(res.get('col_gain', 0)):,}`"]
        item_str = _format_item_drops(res.get("items"))
        if item_str:
            clines.append(f"📦 道具：{item_str}")
        cdrops = list(res.get("equipment_drops") or [])
        if not cdrops and isinstance(res.get("equipment_result"), dict):
            cdrops = [res["equipment_result"]]
        for d in cdrops[:5]:
            if isinstance(d, dict):
                clines.append(_format_gear_drop_line(d))
        embed.add_field(
            name="🎁 開箱戰利品",
            value=_clamp_str("\n".join(clines), 1024),
            inline=False,
        )

    # Optional Floor Progress footer field for instant post-combat situational awareness
    if isinstance(floor_info, dict):
        fl = int(floor_info.get("floor", res.get("floor", 1)))
        pct = int(floor_info.get("exploration_pct", 0))
        gate_zh = "🔓 頭目房已開啟" if floor_info.get("boss_gate_unlocked") else "🔒 探索達 100% 開啟頭目房"
        embed.add_field(
            name=f"🧭 第 {fl} 層探索進度",
            value=f"`{pct}%` {hp_bar(pct, 100, 10)}｜{gate_zh}",
            inline=False,
        )

    if res.get("finished") or is_chest:
        embed.set_footer(text="可直接點擊下方按鈕繼續探索、挑戰頭目、回城休整或一鍵穿戴新裝備！")
    return embed


def build_secret_realm_embed(res: dict[str, Any]) -> discord.Embed:
    floor = int(res.get("floor", 1))
    miasma = int(res.get("miasma_stacks", 0))
    embed = discord.Embed(
        title=f"🌫️ 第 {floor} 層・秘境探索（瘴氣 {miasma} 層）",
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_PURPLE,
    )
    embed.set_image(url=_safe_url(assets.get_biome_banner_url(floor)))
    embed.add_field(
        name="⚠️ 秘境瘴氣狀態",
        value=(
            f"瘴氣層數：`{miasma}` 層｜經驗倍率：`{res.get('exp_multiplier', 1.0)}x`｜"
            f"承受傷害：`{res.get('dmg_taken_multiplier', 1.0)}x`\n"
            f"本次收益：EXP `+{int(res.get('exp_gain', 0)):,}`｜柯爾 `+{int(res.get('col_gain', 0)):,}`"
        ),
        inline=False,
    )
    drops = list(res.get("equipment_drops") or [])
    item_str = _format_item_drops(res.get("items"))
    if drops or item_str:
        lines = []
        if item_str:
            lines.append(f"💎 結晶素材：{item_str}")
        for d in drops[:4]:
            if isinstance(d, dict):
                lines.append(_format_gear_drop_line(d))
        embed.add_field(name="🎁 秘境高風險異寶", value=_clamp_str("\n".join(lines), 1024), inline=False)
    embed.set_footer(text="提示：瘴氣達 3 層以上開始掉落強化結晶與高品裝備，僅返回城鎮圈內可淨化瘴氣！")
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
    depth = res.get("depth", res.get("depth_reached", getattr(run, "depth", 1)))
    embed = discord.Embed(
        title=f"🏛️ 黑鐵宮地下迷宮（深度 {depth}）",
        description=_clamp_str(str(res.get("message", "")), 4096),
        color=SAO_COLOR_EMERALD if res.get("extracted") else SAO_COLOR_PURPLE,
    )
    embed.set_image(url=_safe_url(assets.get_biome_banner_url(1)))
    embed.add_field(
        name="📊 迷宮狀態",
        value=(
            f"積分：`{res.get('score', 0)}`｜代幣：`{res.get('tokens', getattr(run, 'tokens', 0))}`｜"
            f"累計柯爾：`{res.get('col_earned', res.get('col_gain', 0)):,}`"
        ),
        inline=False,
    )
    item_str = _format_item_drops(res.get("items"))
    drops = list(res.get("equipment_drops") or [])
    if item_str or drops:
        llines = []
        if item_str:
            llines.append(f"💎 素材：{item_str}")
        for d in drops[:4]:
            if isinstance(d, dict):
                llines.append(_format_gear_drop_line(d))
        embed.add_field(name="🎁 迷宮戰利品", value=_clamp_str("\n".join(llines), 1024), inline=False)
    nodes = list(res.get("nodes") or [])
    if nodes:
        nlines = [f"**{n['index']}. {n['name']}** — {n['desc']}" for n in nodes[:4]]
        embed.add_field(name="🔀 可選分歧路線", value=_clamp_str("\n".join(nlines), 1024), inline=False)
    return embed
