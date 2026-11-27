"""SAO Tactical Combat Engine: 8 Weapon Styles, 2 Unique Skills, Sword Skills, 14 Debuffs & Survival (ZERO discord imports)."""

from __future__ import annotations

import random
import time
import zlib
from typing import Any

from src.rpg.content.loader import SAOContentBundle, resolve_floor_config
from src.rpg.database import RPGDatabase
from src.rpg.models import (
    BASE_WEAPON_STYLES,
    UNIQUE_WEAPON_STYLES,
    BossMode,
    CombatSession,
    ComputedStats,
    DamageType,
    GameError,
    GameMode,
    PlayerProfile,
    Rarity,
    RoguelikeRun,
    ZoneType,
)
from src.rpg.systems.boss_engine import (
    apply_damage_to_boss,
    build_boss_state,
    get_boss_skill_id,
    get_current_phase_spec,
    step_boss_turn,
)
from src.rpg.systems.stats import compute_player_stats
from src.rpg.systems.tower import (
    SOCKET_CRYSTAL_IDS,
    enhance_crystal_for_tier,
    generate_equipment_item,
    generate_named_equipment,
    grant_or_queue_equipment,
)

ALL_SAO_DEBUFFS: frozenset[str] = frozenset(
    {
        "sunder",
        "sap",
        "wound",
        "resonance",
        "shred",
        "doom",
        "purged",
        "burn",
        "bleed",
        "poison",
        "weaken",
        "stun",
        "provoke",
        "rigidity",
        "slow",
    }
)
CRYSTAL_IDS: frozenset[str] = frozenset(
    {"healing_crystal", "teleport_crystal", "antidote_crystal", "corridor_crystal"}
)
VALID_COMBAT_ACTIONS: frozenset[str] = frozenset(
    {"attack", "skill", "defend", "parry", "item", "crystal", "sheathe", "retreat", "auto", "switch"}
)


def _now(now_ts: int | None) -> int:
    return int(now_ts if now_ts is not None else time.time())


def exp_needed_for_level(level: int) -> int:
    lv = max(1, int(level))
    return round(100 * (lv**1.45) + 40 * lv)


def apply_exp_and_level_up(player: PlayerProfile, exp_gain: int) -> int:
    """Grant EXP and level up player (granting 3 stat points & 1 talent point per level)."""
    if exp_gain <= 0:
        return 0
    player.exp += int(exp_gain)
    levels_gained = 0
    while player.level < 200:
        need = exp_needed_for_level(player.level)
        if player.exp < need:
            break
        player.exp -= need
        player.level += 1
        player.stat_points += 3
        player.talent_points += 1
        levels_gained += 1
    return levels_gained


def compute_player_turnin_bonuses(
    db: RPGDatabase, content: SAOContentBundle, user_id: str
) -> dict[str, float]:
    """Sum permanent Achievement Turn-In milestone bonuses + claimed achievement bonuses."""
    turnins = db.get_achievement_turnins(user_id)
    cfg = content.quests_events.get("turnins", {})
    rpoints = cfg.get("rarity_points", {})
    total_pts = sum(int(rpoints.get(str(t.get("rarity", "plain")), 1)) for t in turnins)
    bonuses: dict[str, float] = {}
    if total_pts > 0:
        bonuses["atk_flat"] = float(total_pts * 2)
        bonuses["hp_flat"] = float(total_pts * 8)
        bonuses["def_flat"] = float(total_pts)
    for ms in cfg.get("milestones", []):
        if total_pts >= int(ms.get("points", 0)):
            for k, v in (ms.get("bonus") or {}).items():
                if isinstance(v, (int, float)):
                    bonuses[str(k)] = bonuses.get(str(k), 0.0) + float(v)
    # Also add unlocked achievement permanent bonuses
    unlocked_ach = db.get_achievements(user_id)
    for ach in content.quests_events.get("achievements", []):
        if str(ach.get("id")) in unlocked_ach:
            for k, v in (ach.get("bonus") or {}).items():
                if isinstance(v, (int, float)):
                    bonuses[str(k)] = bonuses.get(str(k), 0.0) + float(v)
    return bonuses


def compute_player_talent_bonuses(
    db: RPGDatabase, content: SAOContentBundle, user_id: str, weapon_style: str
) -> dict[str, float]:
    """Sum allocated branching weapon talent bonuses."""
    ranks = db.get_talents(user_id)
    if not ranks:
        return {}
    w_classes = content.weapons_equipment.get("weapon_classes", {})
    bonuses: dict[str, float] = {}
    for wkey, wspec in w_classes.items():
        # Active weapon style talents always apply; other trees only if matching style
        if wkey != weapon_style and weapon_style not in UNIQUE_WEAPON_STYLES:
            continue
        for node in wspec.get("talent_tree", []):
            tid = str(node.get("id"))
            rk = int(ranks.get(tid, 0))
            if rk <= 0:
                continue
            for k, v in (node.get("bonus_per_rank") or {}).items():
                if isinstance(v, (int, float)):
                    bonuses[str(k)] = bonuses.get(str(k), 0.0) + float(v) * rk
    return bonuses


def compute_full_player_stats(
    db: RPGDatabase,
    content: SAOContentBundle,
    player: PlayerProfile,
    *,
    floor: int | None = None,
    now_ts: int | None = None,
) -> ComputedStats:
    """Compute player stats including equipped gear, talents, active buffs, guild rally, world buffs & turn-ins."""
    ts = _now(now_ts)
    target_floor = int(floor if floor is not None else player.current_floor)
    eqs = db.get_equipment(player.user_id, equipped_only=True)

    # Combine active buffs (dishes, stew, talents, world buffs)
    buff_list: list[dict[str, Any]] = []
    talents = compute_player_talent_bonuses(db, content, player.user_id, player.weapon_style)
    if talents:
        buff_list.append(talents)

    for bval in (player.active_buffs or {}).values():
        if isinstance(bval, dict):
            exp_at = int(bval.get("expires_at", 0))
            if exp_at == 0 or exp_at >= ts:
                buff_list.append(bval)

    # Global Accelerated World buffs
    for wb in db.get_active_world_buffs("server", "global", ts):
        buff_list.append(wb.get("payload") or {})

    guild_buff: dict[str, Any] | None = None
    if player.guild_id is not None:
        g = db.get_guild(player.guild_id)
        if g and g.active_buff_id and g.active_buff_expires_at >= ts:
            guild_buff = {"active": True, "atk_pct": 0.10, "def_pct": 0.10, "exp_bonus": 0.15}

    turnins = compute_player_turnin_bonuses(db, content, player.user_id)
    stats = compute_player_stats(
        player,
        eqs,
        content,
        floor=target_floor,
        active_buffs=buff_list,
        guild_buff=guild_buff,
        turnin_bonuses=turnins,
    )
    return stats


def max_skill_slots_for_player(player: PlayerProfile) -> int:
    return 4 if player.unique_skills else 3


def switch_weapon_style(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
    weapon_style: str,
) -> dict[str, Any]:
    """Switch active weapon class (`sword`..`dagger` or unlocked `dual_blades`/`holy_sword`)."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.in_boss_battle or (user_id in active_combats and not active_combats[user_id].finished):
        raise GameError("戰鬥或頭目戰進行中無法切換武器流派！", code="SWITCH_STYLE_BLOCKED_IN_COMBAT")

    style = str(weapon_style or "").strip().lower()
    if style in UNIQUE_WEAPON_STYLES:
        if style not in player.unique_skills:
            raise GameError(f"尚未解鎖獨有劍技【{style}】，無法切換！", code="UNIQUE_SKILL_LOCKED")
    elif style not in BASE_WEAPON_STYLES:
        raise GameError(f"不支援的武器流派：{weapon_style}", code="INVALID_WEAPON_STYLE")

    player.weapon_style = style
    # Equip starter skills for the new weapon style cleanly
    wspec = content.weapons_equipment.get("weapon_classes", {}).get(style)
    if isinstance(wspec, dict):
        starters = list(wspec.get("starter_skill_ids") or [])
        player.skill_slots = starters[: max_skill_slots_for_player(player)]
    elif style in UNIQUE_WEAPON_STYLES:
        uspec = content.weapons_equipment.get("unique_skills", {}).get(style, {})
        starters = list(uspec.get("skill_ids") or [])
        player.skill_slots = starters[: max_skill_slots_for_player(player)]

    stats = compute_full_player_stats(db, content, player)
    player.combat_power = stats.combat_power
    db.save_player(player)
    return {
        "ok": True,
        "weapon_style": player.weapon_style,
        "skill_slots": list(player.skill_slots),
        "max_skill_slots": max_skill_slots_for_player(player),
        "stats": stats,
        "message": f"⚔️ 已切換武器流派為【{player.weapon_style}】（目前可裝備 {max_skill_slots_for_player(player)} 個劍技欄位）。",
    }


def _skill_compatible_with_player(player: PlayerProfile, skill_spec: dict[str, Any]) -> bool:
    wcls = str(skill_spec.get("weapon_class") or "").lower()
    is_unique = bool(skill_spec.get("unique_skill", False))
    if is_unique or wcls in UNIQUE_WEAPON_STYLES:
        return wcls in set(player.unique_skills) or player.weapon_style == wcls
    if player.weapon_style == "dual_blades":
        return wcls in ("sword", "dual_blades")
    if player.weapon_style == "holy_sword":
        return wcls in ("holy", "mace", "sword", "holy_sword")
    return wcls == player.weapon_style


def set_skill_slots(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
    skill_ids: list[str],
) -> dict[str, Any]:
    """Equip Sword Skills into the player's 3 (or 4 with Unique Skill) active slots."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.in_boss_battle or (user_id in active_combats and not active_combats[user_id].finished):
        raise GameError("戰鬥中無法更換劍技欄位（防止重置冷卻）！", code="SKILL_SWAP_BLOCKED_IN_COMBAT")

    if not isinstance(skill_ids, list):
        raise GameError("劍技清單格式錯誤。", code="INVALID_SKILL_SLOTS")

    max_slots = max_skill_slots_for_player(player)
    if len(skill_ids) > max_slots:
        raise GameError(
            f"超過劍技欄位上限！目前最多可裝備 {max_slots} 個劍技（解鎖獨有劍技可擴充至 4 格）。",
            code="SKILL_SLOTS_EXCEEDED",
        )
    if len(set(skill_ids)) != len(skill_ids):
        raise GameError("劍技欄位不可重複裝備相同劍技！", code="DUPLICATE_SKILL_SLOT")

    for sid in skill_ids:
        spec = content.sword_skills.get(sid)
        if not isinstance(spec, dict):
            raise GameError(f"未知的劍技編號：{sid}", code="UNKNOWN_SKILL")
        if not _skill_compatible_with_player(player, spec):
            raise GameError(
                f"劍技【{spec.get('name', sid)}】與目前武器流派【{player.weapon_style}】不相容！",
                code="INCOMPATIBLE_WEAPON_SKILL",
            )

    player.skill_slots = list(skill_ids)
    db.save_player(player)
    return {
        "ok": True,
        "skill_slots": list(player.skill_slots),
        "max_skill_slots": max_slots,
        "message": f"📜 劍技欄位已更新（{len(player.skill_slots)}/{max_slots}）。",
    }


def unlock_unique_skill(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    unique_skill_id: str,
) -> dict[str, Any]:
    """Unlock hidden SAO Unique Skill (`dual_blades` or `holy_sword`) when floor/level/mastery gates are met."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    uid_key = str(unique_skill_id or "").strip().lower()
    uspecs = content.weapons_equipment.get("unique_skills", {})
    spec = uspecs.get(uid_key)
    if not isinstance(spec, dict):
        raise GameError(f"未知的獨有劍技：{unique_skill_id}", code="UNKNOWN_UNIQUE_SKILL")

    req_floor = int(spec.get("unlock_floor", 50))
    req_level = int(spec.get("unlock_level", 50))
    req_mastery = int(spec.get("unlock_mastery", 300))
    req_classes = [str(c).lower() for c in spec.get("required_weapon_classes", [])]

    if player.max_unlocked_floor < req_floor and player.highest_cleared_floor < req_floor:
        raise GameError(
            f"尚未抵達解鎖條件：需突破或解鎖第 {req_floor} 層方可觸發【{spec['name']}】試煉！",
            code="UNIQUE_SKILL_FLOOR_LOCKED",
        )
    if player.level < req_level:
        raise GameError(
            f"等級不足：解鎖【{spec['name']}】需要等級 Lv.{req_level}（目前 Lv.{player.level}）。",
            code="UNIQUE_SKILL_LEVEL_LOCKED",
        )
    mastery = db.get_mastery(user_id)
    style_m = max(
        int(mastery.get(player.weapon_style, {}).get("level", 0)),
        max((int(mastery.get(c, {}).get("level", 0)) for c in req_classes), default=0),
    )
    if style_m < req_mastery:
        raise GameError(
            f"武器熟練度不足：需要 {req_mastery} 熟練度（目前 {style_m}）才能覺醒【{spec['name']}】！",
            code="UNIQUE_SKILL_MASTERY_LOCKED",
        )

    if req_classes and player.weapon_style not in req_classes and player.weapon_style != uid_key:
        player.weapon_style = req_classes[0]
        db.upsert_mastery(user_id, player.weapon_style, style_m, 0)

    if uid_key not in player.unique_skills:
        player.unique_skills.append(uid_key)
    stats = compute_full_player_stats(db, content, player)
    player.combat_power = stats.combat_power
    db.save_player(player)
    return {
        "ok": True,
        "unique_skill_id": uid_key,
        "unique_skills": list(player.unique_skills),
        "max_skill_slots": max_skill_slots_for_player(player),
        "unlocked_skills": list(spec.get("skill_ids", [])),
        "message": f"✨ 【卡迪納爾獨有技能覺醒！】你成功解鎖了傳說獨有劍技【{spec['name']}】，已開啟第 4 個劍技欄位！",
    }


def calculate_player_hit(
    stats: ComputedStats,
    target_def: int,
    *,
    dmg_type: str,
    target_weaknesses: list[str],
    skill_mult: float = 1.0,
    combo_count: int = 0,
    is_sheathed: bool = False,
    is_backstab: bool = False,
    switch_chain: int = 0,
    target_debuffs: dict[str, Any] | None = None,
    rng: random.Random | None = None,
) -> tuple[int, bool, bool]:
    """Compute physical/sword-skill hit damage with 4-axis weakness, armor pen, combo, sheathe & backstab."""
    rgen = rng or random.Random()
    debuffs = target_debuffs or {}
    eff_def = float(target_def)
    if "sunder" in debuffs or "shred" in debuffs:
        eff_def *= 0.72
    armor_pen = min(0.75, stats.armor_pen + (0.25 if is_sheathed else 0.0))
    eff_def *= max(0.0, 1.0 - armor_pen)

    base = max(8.0, stats.atk * skill_mult - eff_def * 0.42)
    # Skill damage bonus when using sword skills
    if skill_mult > 1.01:
        base *= 1.0 + stats.skill_dmg_bonus
    # Weakness bonus (+30%)
    weak = str(dmg_type).lower() in {str(w).lower() for w in target_weaknesses}
    if weak:
        base *= 1.30
    # Combo multiplier (+6% per stack up to +60%)
    base *= 1.0 + min(0.60, max(0, combo_count) * 0.06)
    # Katana Sheathe (居合)
    if is_sheathed:
        base *= 1.65
    # Backstab (+40% when ally holds aggro)
    if is_backstab:
        base *= 1.40
    # Switch chain bonus (+25% per chain up to +75%)
    if switch_chain > 0:
        base *= 1.0 + min(0.75, switch_chain * 0.25)
    # Resonance debuff increases incoming damage
    if "resonance" in debuffs:
        base *= 1.18

    crit = rgen.random() < stats.crit_rate
    if crit:
        base *= stats.crit_dmg
    variance = rgen.uniform(0.95, 1.06)
    return max(1, round(base * variance)), crit, weak


def calculate_enemy_hit(
    raw_atk: int,
    dmg_type: str,
    stats: ComputedStats,
    *,
    floor: int,
    miasma_stacks: int = 0,
    is_defending: bool = False,
    is_parrying: bool = False,
    player_debuffs: dict[str, Any] | None = None,
    rng: random.Random | None = None,
) -> tuple[int, bool]:
    """Compute incoming enemy damage after 4-axis effective_res (w/ floor penetration), defense, parry & miasma."""
    rgen = rng or random.Random()
    if not is_defending and not is_parrying and rgen.random() < min(0.35, stats.evasion * 0.65):
        return 0, True

    debuffs = player_debuffs or {}
    eff_def = float(stats.defense) * (0.75 if "sunder" in debuffs else 1.0)
    base = max(6.5, float(raw_atk) - eff_def * 0.45)

    # 4-axis resistance with 75% cap and progressive floor resistance penetration (up to 65%)
    safe_dtype = str(dmg_type).lower()
    if safe_dtype not in (DamageType.SLASH, DamageType.PIERCE, DamageType.BLUNT, DamageType.DRAGON):
        safe_dtype = DamageType.SLASH
    eff_res = stats.effective_res(safe_dtype, floor=floor)
    if "purged" in debuffs:
        eff_res *= 0.5
    base *= max(0.15, 1.0 - eff_res)
    base *= max(0.35, 1.0 - stats.dmg_reduction)

    # Miasma amplifies incoming damage (+12% per stack)
    if miasma_stacks > 0:
        base *= 1.0 + miasma_stacks * 0.12

    if is_parrying:
        base *= 0.25
    elif is_defending:
        base *= 0.48
    if "rigidity" in debuffs:
        base *= 1.20

    return max(1, round(base * rgen.uniform(0.94, 1.06))), False


def apply_debuff(
    target_debuffs: dict[str, dict[str, Any]],
    debuff_name: str | None,
    *,
    turns: int = 3,
    dmg: int = 0,
    is_boss: bool = False,
    stun_immune_turns: int = 0,
) -> str | None:
    """Apply a valid SAO debuff; enforces Boss Stun Immunity (`抗暈`)."""
    if not debuff_name:
        return None
    d = str(debuff_name).strip().lower()
    if d not in ALL_SAO_DEBUFFS:
        return None
    if d == "stun" and is_boss and stun_immune_turns > 0:
        return f"🛡️ 頭目正處於【抗暈】免疫狀態（尚餘 {stun_immune_turns} 回合），無法再次暈眩！"
    target_debuffs[d] = {"turns": max(1, int(turns)), "dmg": max(0, int(dmg))}
    return f"🧪 附加異常狀態【{d}】（{turns} 回合）！"


_BOSS_RESPAWN_COOLDOWN_SEC = 180
_LAST_SOLO_BOSS_CLEAR: dict[tuple[str, str, int], int] = {}
_ROAD_MOB_DROP_PITY: dict[tuple[str, str], int] = {}


def _db_key(db: RPGDatabase) -> str:
    return str(getattr(db, "db_path", id(db)))


def start_floor_boss(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
    *,
    floor: int | None = None,
    mode: str = BossMode.NORMAL,
    now_ts: int | None = None,
    nightmare_floor: int | None = None,
    bypass_cooldown: bool = False,
) -> dict[str, Any]:
    """Enter the Floor Boss Room for solo challenge (requires unlocked floor & Boss Gate)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.is_dead:
        raise GameError("硬派角色已陣亡，無法挑戰樓層頭目。", code="HARDCORE_DEAD")
    if user_id in active_combats and not active_combats[user_id].finished:
        raise GameError("你目前仍在戰鬥中，請先結束當前戰鬥！", code="ALREADY_IN_COMBAT")

    target_floor = int(floor if floor is not None else player.current_floor)
    if isinstance(target_floor, bool) or not (1 <= target_floor <= 100):
        raise GameError(f"無效的頭目樓層：{target_floor}（必須為 1～100）", code="INVALID_FLOOR")
    if target_floor > player.max_unlocked_floor:
        raise GameError(
            f"第 {target_floor} 層尚未解鎖！你目前最高可挑戰第 {player.max_unlocked_floor} 層。",
            code="FLOOR_LOCKED",
        )

    # Require Boss Gate unlocked unless player already cleared this floor previously
    exp_state = db.get_floor_exploration(user_id, target_floor)
    already_cleared = target_floor <= player.highest_cleared_floor
    if not exp_state["boss_gate_unlocked"] and not already_cleared and nightmare_floor is None:
        raise GameError(
            f"第 {target_floor} 層頭目房大門尚未開啟！請先探索野外區達 100% 並擊破野外頭目（目前 {exp_state['progress_pct']}%）。",
            code="BOSS_GATE_LOCKED",
        )

    # Enforce floor boss respawn cooldown for repeat solo normal/first_kill clears
    if nightmare_floor is None and not bypass_cooldown and mode in (BossMode.NORMAL, BossMode.FIRST_KILL):
        last_clear = _LAST_SOLO_BOSS_CLEAR.get((_db_key(db), user_id, target_floor))
        if last_clear is not None:
            elapsed = ts - last_clear
            if 0 <= elapsed < _BOSS_RESPAWN_COOLDOWN_SEC:
                wait_sec = _BOSS_RESPAWN_COOLDOWN_SEC - elapsed
                raise GameError(
                    f"第 {target_floor} 層頭目正在重生冷卻中，請於 {wait_sec} 秒後再重新挑戰！",
                    code="BOSS_RESPAWN_COOLDOWN",
                )

    nm_scale = 1.0 + max(0, int(nightmare_floor) - 100) * 0.25 if nightmare_floor else 1.0
    boss = build_boss_state(target_floor, mode=mode, party_size=1, bundle=content, nightmare_scale=nm_scale)
    stats = compute_full_player_stats(db, content, player, floor=target_floor, now_ts=ts)
    p1 = get_current_phase_spec(boss)
    p1_sid = get_boss_skill_id(boss, p1)
    boss.observed_skills.append(p1_sid)
    db.record_boss_intel_seen(user_id, boss.boss_id, p1_sid, ts)

    w_classes = content.weapons_equipment.get("weapon_classes", {})
    p_dmg_type = str(w_classes.get(player.weapon_style, {}).get("dmg_type", DamageType.SLASH))
    cur_hp = stats.max_hp
    cur_sp = stats.max_sp
    intro = str(p1.get("on_enter_broadcast") or f"⚔️ 進入第 {target_floor} 層頭目房！【{boss.name}】現身！")
    init_logs = [intro]
    if player.miasma_stacks > 0:
        miasma_warn = f"⚠️ 【秘境瘴氣警告】你身上仍帶有 {player.miasma_stacks} 層秘境瘴氣，頭目戰承受傷害將會提高（僅回城鎮圈內可淨化）！"
        init_logs.append(miasma_warn)
        intro = f"{intro}\n{miasma_warn}"

    session = CombatSession(
        user_id=user_id,
        mode="nightmare_boss" if nightmare_floor else "boss",
        target_id=boss.boss_id,
        difficulty=str(mode),
        title=f"第 {nightmare_floor or target_floor} 層頭目房・{boss.name}",
        enemy_name=boss.name,
        enemy_emoji="👑",
        enemy_max_hp=boss.max_hp,
        enemy_hp=boss.current_hp,
        enemy_atk=boss.atk,
        enemy_def=boss.defense,
        enemy_level=max(1, nightmare_floor or target_floor),
        player_max_hp=stats.max_hp,
        player_hp=min(cur_hp, stats.max_hp),
        player_max_mp=stats.max_sp,
        player_mp=min(cur_sp, stats.max_sp),
        floor=target_floor,
        zone=ZoneType.BOSS_ROOM,
        weapon_style=player.weapon_style,
        damage_type=p_dmg_type,
        enemy_damage_type=boss.damage_type,
        enemy_weaknesses=list(boss.weaknesses),
        player_sp=min(cur_sp, stats.max_sp),
        player_max_sp=stats.max_sp,
        anti_crystal_zone=boss.anti_crystal_zone,
        boss_state=boss,
        logs=init_logs,
    )
    active_combats[user_id] = session
    player.current_floor = target_floor
    player.zone = ZoneType.BOSS_ROOM
    player.in_boss_battle = True
    player.updated_at = ts
    db.save_player(player)

    return {
        "ok": True,
        "in_combat": True,
        "floor": target_floor,
        "boss_mode": boss.mode,
        "boss_id": boss.boss_id,
        "boss_name": boss.name,
        "anti_crystal_zone": boss.anti_crystal_zone,
        "miasma_stacks": player.miasma_stacks,
        "miasma": player.miasma_stacks,
        "boss_state": boss,
        "combat": session,
        "message": intro,
    }


def _find_best_potion(db: RPGDatabase, content: SAOContentBundle, user_id: str) -> str | None:
    inv = db.get_inventory(user_id)
    for pid in ("hp_potion_t4", "hp_potion_t3", "hp_potion_t2", "hp_potion_t1"):
        if inv.get(pid, 0) > 0:
            return pid
    for iid, qty in inv.items():
        if qty <= 0:
            continue
        spec = content.items_crystals.get(iid, {})
        if spec.get("category") == "potion" and "heal_hp_pct" in (spec.get("effect") or {}):
            return iid
    return None


def _use_consumable_in_combat(
    db: RPGDatabase,
    content: SAOContentBundle,
    session: CombatSession,
    player: PlayerProfile,
    item_id: str,
    *,
    is_crystal_action: bool = False,
) -> tuple[list[str], bool]:
    """Use a potion or SAO Crystal in solo combat. Returns (logs, retreated)."""
    spec = content.items_crystals.get(item_id)
    if not isinstance(spec, dict):
        raise GameError(f"未知的道具或水晶：{item_id}", code="UNKNOWN_ITEM")
    is_crystal = item_id in CRYSTAL_IDS or spec.get("category") == "crystal"
    if is_crystal_action and not is_crystal:
        raise GameError(f"【{spec.get('name', item_id)}】不是 SAO 水晶！", code="NOT_A_CRYSTAL")

    if db.get_item_qty(player.user_id, item_id) <= 0:
        raise GameError(f"背包中沒有【{spec.get('name', item_id)}】！", code="INSUFFICIENT_ITEM")

    # Crystal-Null Room / F100 blocks ALL crystals WITHOUT consuming them!
    if is_crystal and (session.anti_crystal_zone or session.floor == 100):
        raise GameError(
            "🚨 此區域處於【水晶無效化空間】，水晶無法發動（未消耗任何水晶）！",
            code="CRYSTAL_NULL_BLOCKED",
        )

    eff = spec.get("effect") or {}
    logs: list[str] = []
    if item_id == "teleport_crystal" or eff.get("teleport_town"):
        db.consume_items(player.user_id, {item_id: 1})
        session.finished = True
        session.retreated = True
        player.zone = ZoneType.TOWN
        player.in_boss_battle = False
        player.miasma_stacks = 0
        player.miasma_exp_stacks = 0
        logs.append("💎 喊出「轉移・起始之鎮！」藍色轉移水晶光芒爆發，安全撤離至城鎮圈內！")
        return logs, True

    if item_id == "antidote_crystal" or eff.get("cleanse_all"):
        db.consume_items(player.user_id, {item_id: 1})
        session.player_debuffs.clear()
        logs.append("💚 綠色解毒水晶碎裂，淨化了身上所有中毒、燃燒與死宣異常狀態！")
        return logs, False

    if item_id == "healing_crystal" or eff.get("full_heal"):
        db.consume_items(player.user_id, {item_id: 1})
        session.player_hp = session.player_max_hp
        session.player_debuffs.pop("doom", None)
        logs.append(f"❤️ 紅色回復水晶瞬間發動！生命值完全回復至 {session.player_hp}/{session.player_max_hp} 並淨化死宣！")
        return logs, False

    # Potions (HP / SP)
    db.consume_items(player.user_id, {item_id: 1})
    hp_pct = float(eff.get("heal_hp_pct", 0.0))
    hp_flat = int(eff.get("heal_hp_flat", 0))
    sp_pct = float(eff.get("heal_sp_pct", 0.0))
    sp_flat = int(eff.get("heal_sp_flat", 0))
    if hp_pct > 0 or hp_flat > 0:
        heal = max(1, round(session.player_max_hp * hp_pct) + hp_flat)
        session.player_hp = min(session.player_max_hp, session.player_hp + heal)
        logs.append(f"🧪 使用【{spec.get('name', item_id)}】，回復 {heal} 點生命（{session.player_hp}/{session.player_max_hp}）！")
    if sp_pct > 0 or sp_flat > 0:
        sp_heal = max(1, round(session.player_max_sp * sp_pct) + sp_flat)
        session.player_sp = min(session.player_max_sp, session.player_sp + sp_heal)
        session.player_mp = session.player_sp
        logs.append(f"🔷 使用【{spec.get('name', item_id)}】，回復 {sp_heal} 點 SP！")
    return logs, False


def settle_solo_victory(
    db: RPGDatabase,
    content: SAOContentBundle,
    session: CombatSession,
    player: PlayerProfile,
    *,
    now_ts: int,
    active_runs: dict[str, RoguelikeRun] | None = None,
) -> dict[str, Any]:
    """Settle EXP (>=1), Col, materials/meats, multi-channel equipment drops, Named LA drops, First-Kill, Yui logs & quests."""
    floor = session.floor
    fcfg = resolve_floor_config(floor, content)
    tier = int(fcfg["tier"])
    stats = compute_full_player_stats(db, content, player, floor=floor, now_ts=now_ts)
    rgen = random.Random(
        now_ts
        + floor * 17
        + session.turn * 31
        + zlib.crc32(str(player.user_id).encode("utf-8")) % 997
        + player.survival_streak * 13
    )

    is_boss = session.boss_state is not None
    exp_mult = 1.0 + stats.exp_bonus + (player.miasma_exp_stacks * 0.15 if player.zone == ZoneType.SECRET_REALM else 0.0)
    col_mult = 1.0 + stats.col_bonus

    if is_boss:
        raw_exp = int(fcfg["exp_base"]) * 6
        raw_col = int(fcfg["col_base"]) * 8
    elif session.mode == "field_boss":
        raw_exp = int(fcfg["exp_base"]) * 3
        raw_col = int(fcfg["col_base"]) * 4
    elif session.mode == "elite":
        raw_exp = round(int(fcfg["exp_base"]) * 1.8)
        raw_col = round(int(fcfg["col_base"]) * 2.0)
    else:
        raw_exp = int(fcfg["exp_base"])
        raw_col = int(fcfg["col_base"])

    # Over-level attenuation but ALWAYS minimum 1 EXP per kill!
    lv_diff = player.level - session.enemy_level
    if lv_diff > 15:
        raw_exp = max(1, round(raw_exp * max(0.10, 1.0 - (lv_diff - 15) * 0.04)))
    exp_gain = max(1, round(raw_exp * exp_mult))
    col_gain = max(5, round(raw_col * col_mult))

    levels_gained = apply_exp_and_level_up(player, exp_gain)
    player.col += col_gain
    player.survival_streak += 1
    player.hp = max(1, session.player_hp)
    player.sp = max(0, session.player_sp)

    # Weapon style mastery progression
    mastery = db.get_mastery(player.user_id)
    cur_m = mastery.get(player.weapon_style, {"level": 1, "exp": 0})
    m_exp = int(cur_m["exp"]) + (40 if is_boss else 14)
    m_lv = int(cur_m["level"])
    while m_exp >= max(20, m_lv * 25):
        m_exp -= max(20, m_lv * 25)
        m_lv += 1
    db.upsert_mastery(player.user_id, player.weapon_style, m_lv, m_exp)

    items_gained: dict[str, int] = {}
    equipment_drops: list[dict[str, Any]] = []
    la_reward: dict[str, Any] | None = None
    is_first_kill = False
    yui_unlocked: str | None = None
    today_key = time.strftime("%Y-%m-%d", time.gmtime(now_ts))
    week_key = time.strftime("%Y-W%W", time.gmtime(now_ts))
    crys_id = enhance_crystal_for_tier(tier)
    boss_gate_unlocked = bool(db.get_floor_exploration(player.user_id, floor).get("boss_gate_unlocked", False))

    if is_boss and session.boss_state is not None:
        boss = session.boss_state
        was_personal_first = floor > player.highest_cleared_floor
        player.in_boss_battle = False
        player.zone = ZoneType.TOWN
        player.boss_kills_participated += 1
        player.total_dungeons += 1
        if session.mode == "nightmare_boss":
            player.nightmare_highest = max(player.nightmare_highest, session.enemy_level)

        # Record tower clear & unlock next floor
        db.record_tower_clear(
            player.user_id,
            floor,
            now_ts,
            turns=session.turn,
            is_team_boss=(boss.mode == BossMode.TEAM_BOSS),
            today_key=today_key,
        )
        if session.mode == "boss":
            _LAST_SOLO_BOSS_CLEAR[(_db_key(db), player.user_id, floor)] = now_ts
        player.highest_cleared_floor = max(player.highest_cleared_floor, floor)

        # Atomic server First-Kill Hall of Fame claim
        is_first_kill = db.claim_server_floor_first_kill(
            floor=floor,
            boss_id=boss.boss_id,
            boss_name=boss.name,
            leader_id=player.user_id,
            leader_name=player.display_name,
            la_user_id=player.user_id,
            la_user_name=player.display_name,
            participant_ids=[player.user_id],
            cleared_at=now_ts,
        )

        # Guaranteed boss crests + enhance crystals + forge scraps
        for mat in fcfg["boss"].get("guaranteed_materials", []):
            mid = str(mat["item_id"])
            qty = rgen.randint(int(mat.get("min", 1)), int(mat.get("max", 1)))
            db.add_item(player.user_id, mid, qty)
            items_gained[mid] = items_gained.get(mid, 0) + qty
        if crys_id in content.items_crystals:
            cqty = rgen.randint(2, 3)
            db.add_item(player.user_id, crys_id, cqty)
            items_gained[crys_id] = items_gained.get(crys_id, 0) + cqty
        if "forge_scrap" in content.items_crystals:
            db.add_item(player.user_id, "forge_scrap", 2)
            items_gained["forge_scrap"] = items_gained.get("forge_scrap", 0) + 2

        # Last Attack (LA) Named Bonus drop (bypasses filter; overflows to pending mailbox if bag full!)
        if boss.la_bonus_item_id and boss.la_bonus_item_id in content.weapons_equipment.get("named_items", {}):
            named_eq = generate_named_equipment(
                player.user_id, boss.la_bonus_item_id, content, now_ts=now_ts
            )
            la_reward = grant_or_queue_equipment(
                db, player, named_eq, source=f"第{floor}層頭目尾刀獎勵(LA)", now_ts=now_ts, apply_filter=False
            )
            equipment_drops.append(la_reward)
        else:
            boss_gear = generate_equipment_item(
                player.user_id, floor, content, rarity=Rarity.LEGENDARY, weapon_style=player.weapon_style, now_ts=now_ts, rng=rgen
            )
            la_reward = grant_or_queue_equipment(
                db, player, boss_gear, source=f"第{floor}層頭目尾刀獎勵(LA)", now_ts=now_ts, apply_filter=False
            )
            equipment_drops.append(la_reward)

        # Personal First-Clear Set (`珍品`) bonus gear!
        if was_personal_first:
            fc_gear = generate_equipment_item(
                player.user_id, floor, content, rarity=Rarity.SET, weapon_style=player.weapon_style, now_ts=now_ts, rng=rgen
            )
            equipment_drops.append(
                grant_or_queue_equipment(
                    db, player, fc_gear, source=f"第{floor}層首通珍品獎勵", now_ts=now_ts, apply_filter=False
                )
            )

        # Unlock Yui lore archives up to cleared floor
        for log_id, lspec in content.quests_events.get("yui_logs", {}).items():
            if int(lspec.get("unlock_floor", 999)) <= floor and db.unlock_yui_log(player.user_id, log_id, now_ts):
                yui_unlocked = log_id

        # Milestone Achievements
        ach_map = {1: "sao_ach_f01", 10: "sao_ach_f10", 25: "sao_ach_f25", 50: "sao_ach_f50", 74: "sao_ach_f74", 75: "sao_ach_f75", 100: "sao_ach_f100"}
        if floor in ach_map:
            db.unlock_achievement(player.user_id, ach_map[floor], now_ts)

        db.increment_quest(player.user_id, "daily", today_key, "dq_boss_1", 1, delta=1)
        db.increment_quest(player.user_id, "weekly", week_key, "wq_boss_10", 10, delta=1)
    else:
        # Road mob / elite / field boss / roguelike drops
        mspec = content.monsters.get(session.target_id, {})
        meat_id = mspec.get("meat_drop_id")
        if meat_id and meat_id in content.items_crystals:
            db.add_item(player.user_id, str(meat_id), 1)
            items_gained[str(meat_id)] = items_gained.get(str(meat_id), 0) + 1
        ore_id = mspec.get("ore_drop_id")
        if ore_id and ore_id in content.items_crystals:
            if session.mode in ("elite", "field_boss"):
                oqty = 2 if session.mode == "field_boss" else 1
                db.add_item(player.user_id, str(ore_id), oqty)
                items_gained[str(ore_id)] = items_gained.get(str(ore_id), 0) + oqty
            elif rgen.random() < min(0.85, 0.35 + stats.drop_bonus * 0.5):
                db.add_item(player.user_id, str(ore_id), 1)
                items_gained[str(ore_id)] = items_gained.get(str(ore_id), 0) + 1
        for drop in mspec.get("drops", []):
            chance = min(1.0, float(drop.get("chance", 0.3)) + stats.drop_bonus * 0.35)
            if rgen.random() <= chance:
                iid = str(drop["item_id"])
                if iid in content.items_crystals:
                    qty = rgen.randint(int(drop.get("min", 1)), int(drop.get("max", 1)))
                    db.add_item(player.user_id, iid, qty)
                    items_gained[iid] = items_gained.get(iid, 0) + qty

        if session.mode == "field_boss":
            exp_state = db.get_floor_exploration(player.user_id, floor)
            boss_gate_unlocked = True
            db.save_floor_exploration(
                player.user_id,
                floor,
                100,
                field_boss_cleared=True,
                boss_gate_unlocked=True,
                pending_chest=exp_state.get("pending_chest"),
                now_ts=now_ts,
            )
            fb_roll = rgen.random()
            fb_rarity = Rarity.LEGENDARY if fb_roll < 0.20 else (Rarity.SET if fb_roll < 0.55 else Rarity.RARE)
            gear = generate_equipment_item(
                player.user_id, floor, content, rarity=fb_rarity, weapon_style=player.weapon_style, now_ts=now_ts, rng=rgen
            )
            equipment_drops.append(
                grant_or_queue_equipment(db, player, gear, source=f"第{floor}層野外頭目", now_ts=now_ts, apply_filter=True)
            )
            if crys_id in content.items_crystals:
                db.add_item(player.user_id, crys_id, 2)
                items_gained[crys_id] = items_gained.get(crys_id, 0) + 2
        elif session.mode == "roguelike":
            if active_runs and player.user_id in active_runs:
                run = active_runs[player.user_id]
                run.hp = max(1, session.player_hp)
                run.sp = max(0, session.player_sp)
            if session.difficulty == "warden":
                w_roll = rgen.random()
                w_rarity = Rarity.LEGENDARY if w_roll < 0.25 else (Rarity.SET if w_roll < 0.60 else Rarity.RARE)
                w_gear = generate_equipment_item(
                    player.user_id, floor, content, rarity=w_rarity, weapon_style=player.weapon_style, now_ts=now_ts, rng=rgen
                )
                equipment_drops.append(
                    grant_or_queue_equipment(db, player, w_gear, source="黑鐵宮迷宮守衛者", now_ts=now_ts, apply_filter=True)
                )
                if crys_id in content.items_crystals:
                    db.add_item(player.user_id, crys_id, 2)
                    items_gained[crys_id] = items_gained.get(crys_id, 0) + 2
                db.unlock_achievement(player.user_id, "sao_ach_roguelike_boss", now_ts)
            else:
                if "forge_scrap" in content.items_crystals:
                    db.add_item(player.user_id, "forge_scrap", 1)
                    items_gained["forge_scrap"] = items_gained.get("forge_scrap", 0) + 1
                if rgen.random() < min(0.85, 0.35 + stats.drop_bonus):
                    rl_rarity = Rarity.RARE if rgen.random() < 0.40 else Rarity.FINE
                    rl_gear = generate_equipment_item(
                        player.user_id, floor, content, rarity=rl_rarity, weapon_style=player.weapon_style, now_ts=now_ts, rng=rgen
                    )
                    equipment_drops.append(
                        grant_or_queue_equipment(db, player, rl_gear, source="黑鐵宮迷宮戰鬥", now_ts=now_ts, apply_filter=True)
                    )
        elif session.mode == "elite":
            if crys_id in content.items_crystals:
                db.add_item(player.user_id, crys_id, 1)
                items_gained[crys_id] = items_gained.get(crys_id, 0) + 1
            if rgen.random() < min(0.95, 0.75 + stats.drop_bonus):
                e_roll = rgen.random()
                e_rarity = Rarity.SET if e_roll < 0.20 else (Rarity.RARE if e_roll < 0.65 else Rarity.FINE)
                e_gear = generate_equipment_item(
                    player.user_id, floor, content, rarity=e_rarity, weapon_style=player.weapon_style, now_ts=now_ts, rng=rgen
                )
                equipment_drops.append(
                    grant_or_queue_equipment(db, player, e_gear, source=f"第{floor}層菁英魔物", now_ts=now_ts, apply_filter=True)
                )
            if rgen.random() < 0.25:
                sock_id = rgen.choice(SOCKET_CRYSTAL_IDS)
                if sock_id in content.items_crystals:
                    db.add_item(player.user_id, sock_id, 1)
                    items_gained[sock_id] = items_gained.get(sock_id, 0) + 1
        else:
            # Normal road mob: 28%+ equipment drop with 4-kill pity + occasional scrap/crystal!
            pity_key = (_db_key(db), player.user_id)
            pity_cnt = _ROAD_MOB_DROP_PITY.get(pity_key, 0) + 1
            drop_chance = min(0.85, 0.28 + stats.drop_bonus)
            if pity_cnt >= 4 or rgen.random() < drop_chance:
                _ROAD_MOB_DROP_PITY[pity_key] = 0
                m_roll = rgen.random()
                m_rarity = Rarity.RARE if m_roll < 0.17 else (Rarity.FINE if m_roll < 0.65 else Rarity.PLAIN)
                m_gear = generate_equipment_item(
                    player.user_id, floor, content, rarity=m_rarity, weapon_style=player.weapon_style, now_ts=now_ts, rng=rgen
                )
                equipment_drops.append(
                    grant_or_queue_equipment(db, player, m_gear, source=f"第{floor}層野外魔物", now_ts=now_ts, apply_filter=True)
                )
            else:
                _ROAD_MOB_DROP_PITY[pity_key] = pity_cnt
            if rgen.random() < min(0.60, 0.22 + stats.drop_bonus * 0.5):
                bonus_mat = crys_id if rgen.random() < 0.55 else "forge_scrap"
                if bonus_mat in content.items_crystals:
                    db.add_item(player.user_id, bonus_mat, 1)
                    items_gained[bonus_mat] = items_gained.get(bonus_mat, 0) + 1

    # Update tier bounty using actual JSON bounty target
    bounty_id = f"bounty_t{tier}"
    bounty_spec = next(
        (b for b in content.quests_events.get("bounties", []) if str(b.get("id")) == bounty_id),
        None,
    )
    bounty_target = int(bounty_spec.get("target", 10)) if isinstance(bounty_spec, dict) else 10
    db.increment_quest(player.user_id, "bounty", f"tier_{tier}", bounty_id, bounty_target, delta=1)

    new_stats = compute_full_player_stats(db, content, player, floor=floor, now_ts=now_ts)
    player.combat_power = new_stats.combat_power
    player.updated_at = now_ts
    db.save_player(player)

    summary = {
        "victory": True,
        "exp_gain": exp_gain,
        "col_gain": col_gain,
        "levels_gained": levels_gained,
        "items": items_gained,
        "equipment_drops": equipment_drops,
        "is_first_kill": is_first_kill,
        "la_user_id": player.user_id if is_boss else None,
        "la_reward": la_reward,
        "yui_unlocked": yui_unlocked,
        "unlocked_next_floor": min(100, floor + 1) if is_boss else None,
        "boss_gate_unlocked": boss_gate_unlocked,
    }
    session.rewards_summary = summary
    return summary


def settle_solo_defeat(
    db: RPGDatabase,
    session: CombatSession,
    player: PlayerProfile,
    *,
    now_ts: int,
    active_runs: dict[str, RoguelikeRun] | None = None,
) -> dict[str, Any]:
    """Handle defeat: Roguelike non-lethal vs Hardcore Permadeath vs Standard Downed/Rescue."""
    session.finished = True
    session.victory = False
    player.in_boss_battle = False
    player.survival_streak = 0
    last_logs = list(session.logs[-5:])
    player.last_death_log = " | ".join(last_logs)

    # Roguelike NEVER causes Hardcore permadeath!
    if session.mode == "roguelike":
        if active_runs and player.user_id in active_runs:
            run = active_runs.pop(player.user_id)
            run.finished = True
            consolation_col = max(30, run.col_earned // 2)
            player.col += consolation_col
        player.zone = ZoneType.TOWN
        player.hp = max(1, session.player_max_hp // 2)
        player.updated_at = now_ts
        db.save_player(player)
        return {
            "defeat": True,
            "permadeath": False,
            "roguelike_safe_settlement": True,
            "message": "🏛️ 你在黑鐵宮地下迷宮力竭倒下，被安全傳送回城鎮（不觸發硬派死亡）。",
        }

    if player.game_mode == GameMode.HARDCORE:
        player.is_dead = True
        player.hp = 0
        player.zone = ZoneType.TOWN
        player.updated_at = now_ts
        db.save_player(player)
        db.record_monument_event(
            user_id=player.user_id,
            display_name=player.display_name,
            event_type="fallen",
            floor=session.floor,
            game_mode=GameMode.HARDCORE,
            cause=f"敗於第 {session.floor} 層【{session.enemy_name}】",
            last_log=last_logs,
            now_ts=now_ts,
        )
        return {
            "defeat": True,
            "permadeath": True,
            "is_dead": True,
            "message": f"🪦 【死亡遊戲・殞落】{player.display_name} 在第 {session.floor} 層敗於【{session.enemy_name}】，名字已永遠劃去於黑鐵宮生命之碑。",
        }

    # Standard Mode: Downed (can be rescued by teammate with Teleport Crystal!)
    player.downed_until = now_ts + 300
    player.hp = 1
    player.updated_at = now_ts
    db.save_player(player)
    db.record_monument_event(
        user_id=player.user_id,
        display_name=player.display_name,
        event_type="downed",
        floor=session.floor,
        game_mode=GameMode.STANDARD,
        cause=f"重傷倒地於第 {session.floor} 層【{session.enemy_name}】",
        last_log=last_logs,
        now_ts=now_ts,
    )
    return {
        "defeat": True,
        "permadeath": False,
        "downed": True,
        "downed_until": player.downed_until,
        "message": f"🩸 你在第 {session.floor} 層重傷倒地（瀕死狀態），可等待隊友使用轉移水晶救援或返回城鎮休整！",
    }


def combat_action(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    active_runs: dict[str, RoguelikeRun],
    user_id: str,
    action: str,
    *,
    skill_id: str | None = None,
    item_id: str | None = None,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Execute one solo combat turn (`attack`, `skill`, `defend`, `parry`, `item`, `crystal`, `sheathe`, `retreat`, `auto`)."""
    ts = _now(now_ts)
    act = str(action or "").strip().lower()
    if act not in VALID_COMBAT_ACTIONS:
        raise GameError(f"無效的戰鬥指令：{action}", code="INVALID_COMBAT_ACTION")

    session = active_combats.get(user_id)
    if session is None or session.finished:
        raise GameError("目前沒有進行中的戰鬥。", code="NOT_IN_COMBAT")

    if act == "switch":
        raise GameError("單人作戰沒有存活隊友可供交換（Switch），請組隊進行多人共鬥！", code="SOLO_SWITCH_FORBIDDEN")

    player = db.get_player(user_id)
    if player is None:
        raise GameError("找不到角色資料。", code="PLAYER_NOT_FOUND")

    stats = compute_full_player_stats(db, content, player, floor=session.floor, now_ts=ts)
    rgen = random.Random(ts + session.turn * 31 + zlib.crc32(str(user_id).encode("utf-8")) % 997)
    turn_logs: list[str] = []

    # Handle Auto-Battle Survival loop (`action="auto"`)
    if act == "auto":
        return _run_auto_battle(db, content, active_combats, active_runs, session, player, stats, ts)

    # Tick down skill cooldowns at start of new action
    for sk in list(session.skill_cooldowns.keys()):
        if session.skill_cooldowns[sk] > 0:
            session.skill_cooldowns[sk] -= 1
            if session.skill_cooldowns[sk] <= 0:
                session.skill_cooldowns.pop(sk, None)

    is_defending = False
    is_parrying = False
    enemy_defeated = False
    dealt_dmg = 0
    level_gap = max(0, session.enemy_level - player.level - 3)
    gap_player_mult = max(0.30, 1.0 - level_gap * 0.08) if level_gap > 0 else 1.0
    gap_enemy_mult = 1.0 + level_gap * 0.28 if level_gap > 0 else 1.0

    if act == "retreat":
        if session.anti_crystal_zone or session.floor == 100:
            raise GameError(
                "🚨 此區域處於水晶無效化／最終王座封鎖，無法撤退！",
                code="RETREAT_BLOCKED",
            )
        session.finished = True
        session.retreated = True
        if session.mode == "roguelike" and active_runs and user_id in active_runs:
            run = active_runs.pop(user_id)
            run.finished = True
        player.in_boss_battle = False
        player.zone = ZoneType.TOWN
        player.miasma_stacks = 0
        player.miasma_exp_stacks = 0
        player.updated_at = ts
        db.save_player(player)
        active_combats.pop(user_id, None)
        msg = "🏃 你成功脫離戰鬥並撤回安全區城鎮！"
        session.logs.append(msg)
        return {
            "ok": True,
            "finished": True,
            "retreated": True,
            "victory": False,
            "defeat": False,
            "mode": session.mode,
            "floor": session.floor,
            "in_combat": False,
            "damage_dealt": 0,
            "damage": 0,
            "rewards": None,
            "defeat_info": None,
            "boss_state": session.boss_state,
            "logs": [msg],
            "combat": session,
            "message": msg,
        }

    if act in ("item", "crystal"):
        if not item_id:
            raise GameError("請指定要使用的道具或水晶編號。", code="MISSING_ITEM_ID")
        use_logs, retreated = _use_consumable_in_combat(
            db, content, session, player, item_id, is_crystal_action=(act == "crystal")
        )
        turn_logs.extend(use_logs)
        if retreated:
            if session.mode == "roguelike" and active_runs and user_id in active_runs:
                run = active_runs.pop(user_id)
                run.finished = True
            active_combats.pop(user_id, None)
            player.updated_at = ts
            db.save_player(player)
            session.logs.extend(turn_logs)
            return {
                "ok": True,
                "finished": True,
                "retreated": True,
                "victory": False,
                "defeat": False,
                "mode": session.mode,
                "floor": session.floor,
                "in_combat": False,
                "damage_dealt": 0,
                "damage": 0,
                "rewards": None,
                "defeat_info": None,
                "boss_state": session.boss_state,
                "logs": turn_logs,
                "combat": session,
                "message": turn_logs[-1],
            }
    elif act == "sheathe":
        if player.weapon_style != "katana":
            raise GameError("僅太刀流派可發動【納刀居合（sheathe）】！", code="KATANA_ONLY_SHEATHE")
        session.is_sheathed = True
        session.player_sp = min(session.player_max_sp, session.player_sp + 15)
        turn_logs.append("🗡️ 【太刀納刀】你將太刀收入鞘中蓄勢待發，下一次攻擊傷害 +65% 並無視 25% 防禦！")
    elif act == "defend":
        is_defending = True
        session.player_sp = min(session.player_max_sp, session.player_sp + 18)
        turn_logs.append("🛡️ 你擺出穩固防禦架勢（傷害大幅減免並回復 18 SP）。")
    elif act == "parry":
        is_parrying = True
        session.parry_active = True
        session.player_sp = min(session.player_max_sp, session.player_sp + 12)
        turn_logs.append("⚡ 你凝神準備精準彈反（Parry），迎擊敵人蓄力招式！")
    elif act == "skill":
        if not skill_id:
            raise GameError("請指定要施放的劍技編號。", code="MISSING_SKILL_ID")
        spec = content.sword_skills.get(skill_id)
        if not isinstance(spec, dict):
            raise GameError(f"未知的劍技編號：{skill_id}", code="UNKNOWN_SKILL")
        if not _skill_compatible_with_player(player, spec):
            raise GameError(f"目前流派無法施放劍技【{spec.get('name', skill_id)}】！", code="INCOMPATIBLE_WEAPON_SKILL")
        cd_left = int(session.skill_cooldowns.get(skill_id, 0))
        if cd_left > 0:
            raise GameError(f"劍技【{spec['name']}】仍在冷卻中（尚餘 {cd_left} 回合）！", code="SKILL_ON_COOLDOWN")
        sp_cost = int(spec.get("sp_cost", 15))
        if session.player_sp < sp_cost:
            raise GameError(
                f"SP 不足！施放【{spec['name']}】需要 {sp_cost} SP（目前 {session.player_sp} SP）。",
                code="INSUFFICIENT_SP",
            )
        session.player_sp -= sp_cost
        session.player_mp = session.player_sp
        cd_turns = int(spec.get("cooldown_turns", 0))
        if cd_turns > 0:
            session.skill_cooldowns[skill_id] = cd_turns + 1  # +1 so next turn decrements to cd_turns

        # Immediate weapon mastery progression on every Sword Skill cast!
        m_map = db.get_mastery(user_id)
        cur_m = m_map.get(player.weapon_style, {"level": 1, "exp": 0})
        m_exp = int(cur_m["exp"]) + 12
        m_lv = int(cur_m["level"])
        while m_exp >= max(20, m_lv * 25):
            m_exp -= max(20, m_lv * 25)
            m_lv += 1
        db.upsert_mastery(user_id, player.weapon_style, m_lv, m_exp)

        dmg_type = str(spec.get("dmg_type") or session.damage_type).lower()
        mult = float(spec.get("damage_mult", 1.5))
        break_pwr = int(spec.get("break_power", 20))
        tags = list(spec.get("tags") or [])
        is_unique = bool(spec.get("unique_skill", False))

        dmg, crit, weak = calculate_player_hit(
            stats,
            session.enemy_def,
            dmg_type=dmg_type,
            target_weaknesses=session.enemy_weaknesses,
            skill_mult=mult,
            combo_count=session.combo_count,
            is_sheathed=session.is_sheathed,
            target_debuffs=session.boss_state.debuffs if session.boss_state else session.enemy_debuffs,
            rng=rgen,
        )
        dmg = max(1, round(dmg * gap_player_mult))
        session.is_sheathed = False
        session.combo_count += 1

        # Chase spillover damage on `chase` or multi-hit skills
        chase_dmg = 0
        if "chase" in tags or int(spec.get("hits", 1)) >= 4:
            chase_dmg = max(1, round(dmg * 0.25))
            dmg += chase_dmg

        # Post-skill rigidity penalty on heavy skills
        post_delay = spec.get("post_delay_debuff")
        if post_delay:
            apply_debuff(session.player_debuffs, str(post_delay), turns=1)

        if session.boss_state is not None:
            bres = apply_damage_to_boss(
                session.boss_state,
                dmg,
                attacker_id=user_id,
                dmg_type=dmg_type,
                break_power=break_pwr,
                is_unique_skill=is_unique,
                bundle=content,
            )
            dealt_dmg = int(bres["damage"])
            session.enemy_hp = session.boss_state.current_hp
            turn_logs.append(
                f"⚔️ 發動劍技【{spec['name']}】（{spec.get('hits', 1)} 連擊）造成 {dealt_dmg} 傷害"
                f"{' 💥暴擊！' if crit else ''}{' 🎯弱點！' if weak else ''}"
                f"{f'（含追擊 +{chase_dmg}）' if chase_dmg else ''}！"
            )
            turn_logs.extend(bres["logs"])
            # Apply skill debuff to boss
            deb = spec.get("debuff")
            if deb and not bres["killed"] and rgen.random() <= max(0.5, float(spec.get("debuff_chance", 0.5))):
                dmsg = apply_debuff(
                    session.boss_state.debuffs,
                    str(deb),
                    turns=2,
                    dmg=max(10, round(stats.atk * 0.35)),
                    is_boss=True,
                    stun_immune_turns=session.boss_state.stun_immune_turns,
                )
                if dmsg:
                    turn_logs.append(dmsg)
            enemy_defeated = bool(bres["killed"])
        else:
            dealt_dmg = min(session.enemy_hp, dmg)
            session.enemy_hp = max(0, session.enemy_hp - dmg)
            turn_logs.append(
                f"⚔️ 發動劍技【{spec['name']}】對【{session.enemy_name}】造成 {dmg} 傷害"
                f"{' 💥暴擊！' if crit else ''}{' 🎯弱點！' if weak else ''}！"
            )
            enemy_defeated = session.enemy_hp <= 0

        if stats.lifesteal > 0 and dealt_dmg > 0:
            ls_heal = max(1, round(dealt_dmg * stats.lifesteal))
            session.player_hp = min(session.player_max_hp, session.player_hp + ls_heal)
    else:  # act == "attack"
        dmg, crit, weak = calculate_player_hit(
            stats,
            session.enemy_def,
            dmg_type=session.damage_type,
            target_weaknesses=session.enemy_weaknesses,
            skill_mult=1.0,
            combo_count=session.combo_count,
            is_sheathed=session.is_sheathed,
            target_debuffs=session.boss_state.debuffs if session.boss_state else session.enemy_debuffs,
            rng=rgen,
        )
        dmg = max(1, round(dmg * gap_player_mult))
        session.is_sheathed = False
        session.combo_count += 1
        session.player_sp = min(session.player_max_sp, session.player_sp + 10)
        session.player_mp = session.player_sp
        if session.boss_state is not None:
            bres = apply_damage_to_boss(
                session.boss_state,
                dmg,
                attacker_id=user_id,
                dmg_type=session.damage_type,
                break_power=14,
                bundle=content,
            )
            dealt_dmg = int(bres["damage"])
            session.enemy_hp = session.boss_state.current_hp
            turn_logs.append(
                f"🗡️ 普通斬擊對【{session.enemy_name}】造成 {dealt_dmg} 傷害"
                f"{' 💥暴擊！' if crit else ''}{' 🎯弱點！' if weak else ''}！"
            )
            turn_logs.extend(bres["logs"])
            enemy_defeated = bool(bres["killed"])
        else:
            dealt_dmg = min(session.enemy_hp, dmg)
            session.enemy_hp = max(0, session.enemy_hp - dmg)
            turn_logs.append(
                f"🗡️ 攻擊【{session.enemy_name}】造成 {dmg} 傷害"
                f"{' 💥暴擊！' if crit else ''}{' 🎯弱點！' if weak else ''}！"
            )
            enemy_defeated = session.enemy_hp <= 0

    # Check Victory
    if enemy_defeated:
        session.finished = True
        session.victory = True
        if session.boss_state is not None:
            for obs in session.boss_state.observed_skills:
                db.record_boss_intel_seen(user_id, session.boss_state.boss_id, obs, ts)
        summary = settle_solo_victory(db, content, session, player, now_ts=ts, active_runs=active_runs)
        active_combats.pop(user_id, None)
        session.logs.extend(turn_logs)
        return {
            "ok": True,
            "finished": True,
            "victory": True,
            "defeat": False,
            "retreated": False,
            "mode": session.mode,
            "floor": session.floor,
            "in_combat": False,
            "damage_dealt": dealt_dmg,
            "damage": dealt_dmg,
            "rewards": summary,
            "defeat_info": None,
            "boss_state": session.boss_state,
            "combat": session,
            "logs": turn_logs,
            "message": f"🏆 擊破【{session.enemy_name}】！獲得 {summary['exp_gain']} EXP 與 {summary['col_gain']} 柯爾！",
        }

    # Enemy / Boss Turn
    if session.boss_state is not None:
        bturn = step_boss_turn(session.boss_state)
        turn_logs.extend(bturn["logs"])
        if bturn.get("observed_skill_id"):
            db.record_boss_intel_seen(user_id, session.boss_state.boss_id, str(bturn["observed_skill_id"]), ts)
        if bturn["acted"]:
            edmg, dodged = calculate_enemy_hit(
                round(int(bturn["raw_atk"]) * gap_enemy_mult),
                str(bturn["damage_type"]),
                stats,
                floor=session.floor,
                miasma_stacks=player.miasma_stacks,
                is_defending=is_defending,
                is_parrying=is_parrying,
                player_debuffs=session.player_debuffs,
                rng=rgen,
            )
            if dodged:
                turn_logs.append(f"💨 你靈巧閃避了【{session.enemy_name}】的攻擊！")
            else:
                session.player_hp = max(0, session.player_hp - edmg)
                turn_logs.append(f"🩸 【{session.enemy_name}】造成 {edmg} 點（{bturn['damage_type']}）傷害！（剩餘 HP {session.player_hp}/{session.player_max_hp}）")
                if is_parrying and session.player_hp > 0:
                    counter = max(1, round(stats.atk * 1.15))
                    cres = apply_damage_to_boss(
                        session.boss_state,
                        counter,
                        attacker_id=user_id,
                        dmg_type=session.damage_type,
                        break_power=26,
                        bundle=content,
                    )
                    dealt_dmg += int(cres["damage"])
                    session.enemy_hp = session.boss_state.current_hp
                    turn_logs.append(f"⚡ 【彈反成功！】反擊造成 {cres['damage']} 傷害並大幅累積破防槽！")
                    turn_logs.extend(cres["logs"])
                    if cres["killed"]:
                        session.finished = True
                        session.victory = True
                        summary = settle_solo_victory(db, content, session, player, now_ts=ts, active_runs=active_runs)
                        active_combats.pop(user_id, None)
                        session.logs.extend(turn_logs)
                        return {
                            "ok": True,
                            "finished": True,
                            "victory": True,
                            "defeat": False,
                            "retreated": False,
                            "mode": session.mode,
                            "floor": session.floor,
                            "in_combat": False,
                            "damage_dealt": dealt_dmg,
                            "damage": dealt_dmg,
                            "rewards": summary,
                            "defeat_info": None,
                            "boss_state": session.boss_state,
                            "combat": session,
                            "logs": turn_logs,
                            "message": f"🏆 彈反終結【{session.enemy_name}】！獲得 {summary['exp_gain']} EXP 與 {summary['col_gain']} 柯爾！",
                        }
                if bturn.get("inflict_debuff") and not is_parrying:
                    dmsg = apply_debuff(session.player_debuffs, str(bturn["inflict_debuff"]), turns=3, dmg=max(5, round(edmg * 0.15)))
                    if dmsg:
                        turn_logs.append(dmsg)
    else:
        edmg, dodged = calculate_enemy_hit(
            round(session.enemy_atk * gap_enemy_mult),
            session.enemy_damage_type,
            stats,
            floor=session.floor,
            miasma_stacks=player.miasma_stacks,
            is_defending=is_defending,
            is_parrying=is_parrying,
            player_debuffs=session.player_debuffs,
            rng=rgen,
        )
        if dodged:
            turn_logs.append(f"💨 成功閃避【{session.enemy_name}】的突襲！")
        else:
            session.player_hp = max(0, session.player_hp - edmg)
            turn_logs.append(f"🩸 【{session.enemy_name}】反擊造成 {edmg} 傷害！（剩餘 HP {session.player_hp}/{session.player_max_hp}）")

    # Tick player debuffs (DoT & Doom countdown)
    for dname, dinfo in list(session.player_debuffs.items()):
        tleft = int(dinfo.get("turns", 1)) - 1
        if dname in ("burn", "bleed", "poison") and session.player_hp > 0:
            dot = max(1, int(dinfo.get("dmg", 8)))
            session.player_hp = max(0, session.player_hp - dot)
            turn_logs.append(f"☠️ 異常狀態【{dname}】造成 {dot} 點持續傷害。")
        if dname == "doom" and tleft <= 0 and session.player_hp > 0:
            doom_dmg = max(1, round(session.player_max_hp * 0.65))
            session.player_hp = max(0, session.player_hp - doom_dmg)
            turn_logs.append(f"💀 【死宣倒數歸零！】遭受 {doom_dmg} 點致命靈魂傷害！")
        if tleft <= 0:
            session.player_debuffs.pop(dname, None)
        else:
            dinfo["turns"] = tleft

    # Battle regen passive
    if session.player_hp > 0 and stats.battle_regen_pct > 0:
        regen = max(1, round(session.player_max_hp * stats.battle_regen_pct))
        session.player_hp = min(session.player_max_hp, session.player_hp + regen)

    session.turn += 1
    session.parry_active = False

    # Check Defeat
    if session.player_hp <= 0:
        session.logs.extend(turn_logs)
        defeat_info = settle_solo_defeat(db, session, player, now_ts=ts, active_runs=active_runs)
        active_combats.pop(user_id, None)
        return {
            "ok": True,
            "finished": True,
            "victory": False,
            "defeat": True,
            "retreated": False,
            "mode": session.mode,
            "floor": session.floor,
            "in_combat": False,
            "damage_dealt": dealt_dmg,
            "damage": dealt_dmg,
            "rewards": None,
            "defeat_info": defeat_info,
            "boss_state": session.boss_state,
            "combat": session,
            "logs": turn_logs,
            "message": defeat_info["message"],
        }

    player.hp = session.player_hp
    player.sp = session.player_sp
    player.updated_at = ts
    db.save_player(player)
    session.logs.extend(turn_logs)
    return {
        "ok": True,
        "finished": False,
        "victory": False,
        "defeat": False,
        "retreated": False,
        "mode": session.mode,
        "floor": session.floor,
        "in_combat": True,
        "damage_dealt": dealt_dmg,
        "damage": dealt_dmg,
        "player_hp": session.player_hp,
        "player_sp": session.player_sp,
        "enemy_hp": session.enemy_hp,
        "boss_state": session.boss_state,
        "combat": session,
        "logs": turn_logs,
        "message": turn_logs[-1] if turn_logs else "⚔️ 戰鬥持續進行中！",
    }


def _run_auto_battle(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    active_runs: dict[str, RoguelikeRun],
    session: CombatSession,
    player: PlayerProfile,
    stats: ComputedStats,
    ts: int,
) -> dict[str, Any]:
    """Run automated combat wave respecting player's `survival_config` thresholds."""
    cfg = player.survival_config or {}

    def _ratio(raw: Any, default: float) -> float:
        v = float(raw if raw is not None else default)
        return (v / 100.0) if v > 1.0 else v

    pot_pct = _ratio(cfg.get("auto_potion_pct"), 0.40)
    crys_pct = _ratio(cfg.get("auto_crystal_pct"), 0.20)
    ret_pct = _ratio(cfg.get("auto_retreat_pct"), 0.15)
    stop_no_pot = bool(cfg.get("stop_on_no_potion", True))

    all_logs: list[str] = []
    used_potion = False
    used_crystal = False
    paused_no_potion = False
    last_res: dict[str, Any] = {}

    for _ in range(30):
        hp_ratio = session.player_hp / max(1, session.player_max_hp)
        # 1. Auto retreat check
        if ret_pct > 0 and hp_ratio <= ret_pct:
            if session.anti_crystal_zone or session.floor == 100:
                all_logs.append("🚨 水晶無效化空間阻擋了自動撤退，必須繼續應戰！")
            elif db.get_item_qty(player.user_id, "teleport_crystal") > 0:
                last_res = combat_action(
                    db, content, active_combats, active_runs, player.user_id, "crystal", item_id="teleport_crystal", now_ts=ts
                )
                all_logs.extend(last_res.get("logs", []))
                break
            else:
                last_res = combat_action(
                    db, content, active_combats, active_runs, player.user_id, "retreat", now_ts=ts
                )
                all_logs.extend(last_res.get("logs", []))
                break

        # 2. Auto healing crystal check
        if (
            crys_pct > 0
            and hp_ratio <= crys_pct
            and not session.anti_crystal_zone
            and session.floor != 100
            and db.get_item_qty(player.user_id, "healing_crystal") > 0
        ):
            last_res = combat_action(
                db, content, active_combats, active_runs, player.user_id, "crystal", item_id="healing_crystal", now_ts=ts
            )
            used_crystal = True
            all_logs.extend(last_res.get("logs", []))
            if last_res.get("finished"):
                break
            continue

        # 3. Auto recovery potion check
        if pot_pct > 0 and hp_ratio <= pot_pct:
            pid = _find_best_potion(db, content, player.user_id)
            if pid:
                last_res = combat_action(
                    db, content, active_combats, active_runs, player.user_id, "item", item_id=pid, now_ts=ts
                )
                used_potion = True
                all_logs.extend(last_res.get("logs", []))
                if last_res.get("finished"):
                    break
                continue
            if stop_no_pot:
                paused_no_potion = True
                all_logs.append("⚠️ 【生存設定觸發】回復藥水已耗盡，自動戰鬥安全暫停！")
                break

        # 4. Cast an equipped ready Sword Skill or attack
        chosen_skill: str | None = None
        for sid in player.skill_slots:
            spec = content.sword_skills.get(sid)
            if (
                isinstance(spec, dict)
                and int(session.skill_cooldowns.get(sid, 0)) == 0
                and session.player_sp >= int(spec.get("sp_cost", 15))
                and _skill_compatible_with_player(player, spec)
            ):
                chosen_skill = sid
                break

        if chosen_skill:
            last_res = combat_action(
                db, content, active_combats, active_runs, player.user_id, "skill", skill_id=chosen_skill, now_ts=ts
            )
        else:
            last_res = combat_action(
                db, content, active_combats, active_runs, player.user_id, "attack", now_ts=ts
            )
        all_logs.extend(last_res.get("logs", []))
        if last_res.get("finished"):
            break

    final_msg = str(last_res.get("message") or (all_logs[-1] if all_logs else "🤖 自動戰鬥回合完成。"))
    return {
        "ok": True,
        "auto_battle": True,
        "used_potion": used_potion,
        "used_crystal": used_crystal,
        "paused_no_potion": paused_no_potion,
        "finished": bool(last_res.get("finished", False)),
        "victory": bool(last_res.get("victory", False)),
        "defeat": bool(last_res.get("defeat", False)),
        "retreated": bool(last_res.get("retreated", False)),
        "mode": session.mode,
        "floor": session.floor,
        "in_combat": not bool(last_res.get("finished", False)),
        "rewards": last_res.get("rewards"),
        "defeat_info": last_res.get("defeat_info"),
        "boss_state": last_res.get("boss_state", session.boss_state),
        "logs": all_logs,
        "combat": session,
        "message": final_msg,
    }
