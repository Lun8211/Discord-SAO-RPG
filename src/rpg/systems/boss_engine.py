"""Multi-bar, multi-phase SAO Aincrad Boss state machine (ZERO discord imports).

Supports all 14 bespoke Milestone Bosses (F1, F10, F20, F25, F30, F40, F50, F60,
F70, F74, F75, F80, F90, F100 Dual-Stage Radius -> Heathcliff), 10 Tier Guardian
templates, and 10 Floor World Bosses with health-gated phase transitions, Stagger/Break
gauge, telegraphs, Argo observed-skill recording, Enrage, and deterministic LA attribution.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from src.rpg.content.loader import SAOContentBundle, load_content, resolve_floor_config
from src.rpg.models import BossCombatState, BossMode, DamageType, GameError

VALID_BOSS_MODES: frozenset[str] = frozenset(
    {BossMode.FIRST_KILL, BossMode.NORMAL, BossMode.TEAM_BOSS, BossMode.WORLD_BOSS}
)
TRI_SHIELD_ROTATION: tuple[str, str, str] = (
    DamageType.SLASH,
    DamageType.PIERCE,
    DamageType.BLUNT,
)


def _normalize_boss_mode(mode: str) -> str:
    m = str(mode or BossMode.NORMAL).strip().lower()
    if m not in VALID_BOSS_MODES:
        raise GameError(f"不支援的頭目挑戰模式：{mode}", code="INVALID_BOSS_MODE")
    return m


def _sorted_phases(raw_phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phases = [copy.deepcopy(p) for p in raw_phases if isinstance(p, dict)]
    phases.sort(key=lambda p: int(p.get("phase", 1)))
    if not phases:
        phases = [
            {
                "phase": 1,
                "name": "狂暴姿態",
                "hp_pct_min": 0,
                "dmg_type": DamageType.SLASH,
                "atk_mult": 1.0,
                "spd_mult": 1.0,
                "mechanic": "standard_strike",
                "on_enter_broadcast": "⚔️ 頭目進入戰鬥狀態！",
                "telegraph": "⚠️ 頭目正在蓄力發動重擊，請準備防禦或交換（Switch）！",
            }
        ]
    return phases


def build_boss_state(
    floor: int,
    *,
    mode: str = BossMode.NORMAL,
    party_size: int = 1,
    bundle: SAOContentBundle | None = None,
    nightmare_scale: float = 1.0,
) -> BossCombatState:
    """Construct an initialized multi-bar BossCombatState for any floor 1..100."""
    norm_mode = _normalize_boss_mode(mode)
    content = bundle if bundle is not None else load_content()
    if floor < 1 or floor > 100:
        raise GameError(f"無效的艾恩葛朗特樓層：{floor}（必須為 1～100）", code="INVALID_FLOOR")

    fcfg = resolve_floor_config(floor, content)
    spec = copy.deepcopy(fcfg["boss"])
    phases = _sorted_phases(list(spec.get("phases", [])))
    p1 = phases[0]

    # Mode + party scaling (solo scales down high-party raid bosses; multi-human scales up smoothly)
    psize = max(1, int(party_size))
    rec_party = max(1, int(spec.get("recommended_party", 2)))
    if psize == 1 and rec_party >= 4:
        # Solo mode scaling for 4-6 person raid bosses (e.g. F50-F100)
        hp_mult = 0.22 if floor >= 80 else 0.45
        atk_mult = 0.40 if floor >= 80 else 0.65
    else:
        hp_mult = 1.0 + max(0, psize - 1) * 0.28
        atk_mult = 1.0 + max(0, psize - 1) * 0.04
    if norm_mode == BossMode.FIRST_KILL:
        hp_mult *= 1.12
        atk_mult *= 1.06
    elif norm_mode == BossMode.TEAM_BOSS:
        tmult = spec.get("team_boss_mult") or {}
        hp_mult *= float(tmult.get("hp", 2.0))
        atk_mult *= float(tmult.get("atk", 1.15))

    hp_mult *= max(1.0, float(nightmare_scale))
    atk_mult *= max(1.0, 1.0 + (float(nightmare_scale) - 1.0) * 0.45)

    max_hp = max(100, round(int(spec["base_hp"]) * hp_mult))
    atk = max(10, round(int(spec["base_atk"]) * atk_mult))
    defense = max(4, round(int(spec["base_def"]) * max(1.0, float(nightmare_scale) * 0.85)))

    anti_crystal = bool(spec.get("anti_crystal", False)) or bool(
        fcfg.get("rule_flags", {}).get("anti_crystal")
    )
    weaknesses = [str(w).lower() for w in spec.get("weaknesses", [DamageType.SLASH])]
    dmg_type = str(p1.get("dmg_type") or (spec.get("dmg_types") or [DamageType.SLASH])[0]).lower()
    stagger_max = max(50, int(spec.get("break_gauge_max", 100)))
    enrage_turn = max(10, int(spec.get("enrage_turn", 25)))
    hp_bars = max(3, int(spec.get("hp_bars", 4)))

    # Initial boss resistances (non-weak axes have mild resistance)
    resistances: dict[str, float] = {
        DamageType.SLASH: 0.12,
        DamageType.PIERCE: 0.12,
        DamageType.BLUNT: 0.12,
        DamageType.DRAGON: 0.15,
    }
    for w in weaknesses:
        if w in resistances:
            resistances[w] = 0.0

    # Attach runtime mechanic metadata cleanly inside phases[0] / state fields
    boss = BossCombatState(
        boss_id=str(spec["id"]),
        name=str(spec["name"]),
        floor=int(floor),
        mode=norm_mode,
        max_hp=max_hp,
        current_hp=max_hp,
        hp_bars=hp_bars,
        atk=atk,
        defense=defense,
        spd=max(70, int(90 + floor * 1.1)),
        damage_type=dmg_type,
        weaknesses=weaknesses,
        resistances=resistances,
        current_phase=int(p1.get("phase", 1)),
        triggered_phases=[int(p1.get("phase", 1))],
        phases=phases,
        stagger_max=stagger_max,
        stagger_current=0,
        is_broken=False,
        break_turns_left=0,
        telegraph_active=False,
        telegraph_skill_id="",
        telegraph_skill_name="",
        telegraph_damage_type=dmg_type,
        telegraph_requires_switch=False,
        telegraph_requires_parry=False,
        telegraph_callout="",
        debuffs={},
        stun_immune_turns=0,
        adds=[],
        shield_hp=0,
        anti_crystal_zone=anti_crystal,
        enrage_turn=enrage_turn,
        enraged=False,
        turn=1,
        observed_skills=[],
        la_bonus_item_id=str(spec.get("la_bonus_item_id") or ""),
        last_attacker_id=None,
    )
    # Seed initial mechanic state if phase 1 has rotating shield
    if p1.get("mechanic") == "rotating_tri_shield":
        boss.shield_hp = max(200, round(boss.max_hp * 0.08))
        boss.debuffs["_tri_shield_axis"] = {"axis": TRI_SHIELD_ROTATION[0], "turns": 99}
    return boss


def get_current_phase_spec(boss: BossCombatState) -> dict[str, Any]:
    for p in boss.phases:
        if int(p.get("phase", 1)) == boss.current_phase:
            return p
    return boss.phases[-1]


def get_boss_skill_id(boss: BossCombatState, phase_spec: dict[str, Any]) -> str:
    explicit = phase_spec.get("skill_id")
    if explicit:
        return str(explicit)
    mech = str(phase_spec.get("mechanic") or "strike")
    return f"{boss.boss_id}_p{phase_spec.get('phase', 1)}_{mech}"


def get_all_boss_skill_specs(boss_spec: dict[str, Any]) -> list[dict[str, str]]:
    """Return ordered list of boss skills derived from JSON phases for Argo's Info."""
    bid = str(boss_spec.get("id", "boss"))
    phases = _sorted_phases(list(boss_spec.get("phases", [])))
    out: list[dict[str, str]] = []
    for p in phases:
        mech = str(p.get("mechanic") or "strike")
        sid = str(p.get("skill_id") or f"{bid}_p{p.get('phase', 1)}_{mech}")
        out.append(
            {
                "skill_id": sid,
                "phase": str(p.get("phase", 1)),
                "name": str(p.get("name") or mech),
                "dmg_type": str(p.get("dmg_type") or DamageType.SLASH),
                "telegraph": str(p.get("telegraph") or ""),
            }
        )
    return out


def _next_untriggered_phase(boss: BossCombatState) -> dict[str, Any] | None:
    for p in boss.phases:
        pnum = int(p.get("phase", 1))
        if pnum > boss.current_phase and pnum not in boss.triggered_phases:
            return p
    return None


def _phase_trigger_threshold_hp(boss: BossCombatState, cur_phase: dict[str, Any]) -> int:
    """HP floor where `cur_phase` ends and the next phase begins."""
    pct_min = float(cur_phase.get("hp_pct_min", 0))
    if pct_min <= 0:
        return 0
    return max(1, math.ceil(boss.max_hp * (pct_min / 100.0)))


def _enter_phase(
    boss: BossCombatState,
    new_phase: dict[str, Any],
    bundle: SAOContentBundle | None = None,
) -> list[str]:
    """Activate a newly entered boss phase and emit its canonical zh-TW broadcast."""
    logs: list[str] = []
    pnum = int(new_phase.get("phase", boss.current_phase + 1))
    boss.current_phase = pnum
    if pnum not in boss.triggered_phases:
        boss.triggered_phases.append(pnum)

    new_dmg_type = str(new_phase.get("dmg_type") or boss.damage_type).lower()
    if new_dmg_type in (DamageType.SLASH, DamageType.PIERCE, DamageType.BLUNT, DamageType.DRAGON):
        boss.damage_type = new_dmg_type

    broadcast = str(new_phase.get("on_enter_broadcast") or f"🔥 {boss.name} 進入第 {pnum} 階段！")
    logs.append(broadcast)

    mech = str(new_phase.get("mechanic") or "")
    if mech == "weapon_swap_nodachi":
        boss.damage_type = DamageType.SLASH
        boss.telegraph_active = True
        boss.telegraph_skill_id = get_boss_skill_id(boss, new_phase)
        boss.telegraph_skill_name = "野太刀・居合橫掃"
        boss.telegraph_damage_type = DamageType.SLASH
        boss.telegraph_requires_parry = True
        boss.telegraph_requires_switch = True
        boss.telegraph_callout = str(new_phase.get("telegraph") or "")
    elif mech == "sword_formation_regen":
        boss.debuffs["_serpent_regen"] = {"turns": 5, "heal_pct": 0.06}
        boss.telegraph_active = True
        boss.telegraph_skill_id = get_boss_skill_id(boss, new_phase)
        boss.telegraph_skill_name = "千蛇劍陣回復"
        boss.telegraph_requires_switch = True
        boss.telegraph_callout = str(new_phase.get("telegraph") or "")
    elif mech == "twin_mouth_callout":
        boss.telegraph_active = True
        boss.telegraph_skill_id = get_boss_skill_id(boss, new_phase)
        boss.telegraph_skill_name = "雙口呼名吞噬"
        boss.telegraph_requires_parry = True
        boss.telegraph_requires_switch = True
        boss.telegraph_callout = str(new_phase.get("telegraph") or "")
    elif mech == "zero_frost_armor":
        boss.shield_hp = max(boss.shield_hp, round(boss.max_hp * 0.12))
    elif mech == "rotating_tri_shield":
        boss.shield_hp = max(boss.shield_hp, round(boss.max_hp * 0.12))
        boss.debuffs["_tri_shield_axis"] = {"axis": TRI_SHIELD_ROTATION[0], "turns": 99}
    elif mech == "holy_sword_counter_stance":
        boss.debuffs["_holy_counter"] = {"turns": 4}
        boss.telegraph_active = True
        boss.telegraph_skill_id = get_boss_skill_id(boss, new_phase)
        boss.telegraph_skill_name = "神聖劍・反擊姿態"
        boss.telegraph_requires_parry = True
        boss.telegraph_requires_switch = True
        boss.telegraph_callout = str(new_phase.get("telegraph") or "")
    elif mech == "immortal_system_shield":
        boss.shield_hp = max(boss.shield_hp, round(boss.max_hp * 0.18))
        boss.debuffs["_immortal_shield"] = {
            "turns": 6,
            "break_switch_chain": int(new_phase.get("break_switch_chain", 2)),
        }
        boss.telegraph_active = True
        boss.telegraph_skill_id = get_boss_skill_id(boss, new_phase)
        boss.telegraph_skill_name = "系統防壁・Immortal Shield"
        boss.telegraph_requires_switch = True
        boss.telegraph_callout = str(new_phase.get("telegraph") or "")
    elif mech in ("on_bar_break_summon", "add_wipe_timer"):
        _spawn_phase_adds(boss, new_phase, bundle)

    sid = get_boss_skill_id(boss, new_phase)
    if sid not in boss.observed_skills:
        boss.observed_skills.append(sid)
    return logs


def _spawn_phase_adds(
    boss: BossCombatState,
    phase_spec: dict[str, Any],
    bundle: SAOContentBundle | None = None,
) -> None:
    mob_id = str(phase_spec.get("summon_mob_id") or "")
    count = int(phase_spec.get("summon_count", 0))
    if not mob_id or count <= 0:
        return
    content = bundle if bundle is not None else load_content()
    mspec = content.monsters.get(mob_id, {})
    mname = str(mspec.get("name") or "遺跡護衛")
    add_hp = max(60, round(boss.max_hp * 0.08))
    add_atk = max(10, round(boss.atk * 0.45))
    for i in range(count):
        boss.adds.append(
            {
                "id": f"{mob_id}_{boss.turn}_{i + 1}",
                "mob_id": mob_id,
                "name": mname,
                "hp": add_hp,
                "max_hp": add_hp,
                "atk": add_atk,
                "dmg_type": str(mspec.get("dmg_type") or DamageType.SLASH),
            }
        )


def apply_break_damage(
    boss: BossCombatState,
    break_power: int,
    *,
    switch_chain: int = 0,
    is_unique_skill: bool = False,
) -> list[str]:
    """Add Break Gauge progress; shatter Boss stance & shields when threshold reached."""
    logs: list[str] = []
    if break_power <= 0 and switch_chain <= 0:
        return logs

    # F100 Immortal System Shield shatter check
    if "_immortal_shield" in boss.debuffs:
        req_chain = int(boss.debuffs["_immortal_shield"].get("break_switch_chain", 2))
        if switch_chain >= req_chain or is_unique_skill:
            boss.shield_hp = 0
            boss.debuffs.pop("_immortal_shield", None)
            logs.append("🌟 【規則粉碎】交換連攜／獨有劍技貫穿了希茲克利夫的「Immortal Shield」！")

    # F10 Kagachi Serpent Stance regen cancel on 2+ switch chain
    if "_serpent_regen" in boss.debuffs and switch_chain >= 2:
        boss.debuffs.pop("_serpent_regen", None)
        boss.telegraph_active = False
        logs.append("⚡ 【千蛇破陣】雙人交換連攜成功中斷了加賀智的千蛇劍陣回復！")

    if boss.is_broken:
        return logs

    bonus = round(break_power * (1.0 + 0.25 * min(3, max(0, switch_chain))))
    boss.stagger_current = min(boss.stagger_max, boss.stagger_current + max(1, bonus))
    if boss.stagger_current >= boss.stagger_max:
        boss.is_broken = True
        boss.break_turns_left = 2
        boss.stagger_current = 0
        boss.telegraph_active = False
        boss.shield_hp = 0
        boss.debuffs.pop("_serpent_regen", None)
        boss.debuffs.pop("_holy_counter", None)
        boss.debuffs.pop("_immortal_shield", None)
        logs.append(f"💥 【破防 BREAK！】{boss.name} 姿態崩潰，2 回合內陷入暈眩且受到傷害 +35%！")
    return logs


def apply_damage_to_boss(
    boss: BossCombatState,
    raw_damage: int,
    *,
    attacker_id: str,
    dmg_type: str = DamageType.SLASH,
    break_power: int = 0,
    switch_chain: int = 0,
    is_unique_skill: bool = False,
    bundle: SAOContentBundle | None = None,
) -> dict[str, Any]:
    """Apply damage to boss with shields, tri-shield axis check, health-gated phase transitions & LA tracking."""
    logs: list[str] = []
    dmg = max(1, int(raw_damage))
    dtype = str(dmg_type or DamageType.SLASH).lower()

    # Broken boss takes +35% bonus damage
    if boss.is_broken:
        dmg = round(dmg * 1.35)

    # F90 Rotating Tri-Shield handling
    if boss.shield_hp > 0 and "_tri_shield_axis" in boss.debuffs:
        req_axis = str(boss.debuffs["_tri_shield_axis"].get("axis", DamageType.SLASH))
        if dtype == req_axis:
            dmg = round(dmg * 1.5)
            logs.append(f"🎯 命中三色護盾弱點（{req_axis}），對護盾造成 1.5 倍貫穿傷害！")
        else:
            dmg = max(1, round(dmg * 0.45))

    # F100 Immortal Shield mitigates non-unique / low-chain hits until broken
    if boss.shield_hp > 0 and "_immortal_shield" in boss.debuffs:
        req_chain = int(boss.debuffs["_immortal_shield"].get("break_switch_chain", 2))
        if switch_chain >= req_chain or is_unique_skill:
            boss.shield_hp = 0
            boss.debuffs.pop("_immortal_shield", None)
            logs.append("🌟 【規則粉碎】獨有劍技／連攜交換粉碎了系統防壁！")
        else:
            dmg = max(1, round(dmg * 0.35))

    # Shield absorption
    shield_absorbed = 0
    if boss.shield_hp > 0:
        shield_absorbed = min(boss.shield_hp, dmg)
        boss.shield_hp -= shield_absorbed
        dmg -= shield_absorbed
        if boss.shield_hp == 0:
            if "_tri_shield_axis" in boss.debuffs:
                old_axis = str(boss.debuffs["_tri_shield_axis"].get("axis", DamageType.SLASH))
                idx = (TRI_SHIELD_ROTATION.index(old_axis) + 1) % len(TRI_SHIELD_ROTATION)
                boss.debuffs["_tri_shield_axis"]["axis"] = TRI_SHIELD_ROTATION[idx]
            logs.append(f"🛡️ {boss.name} 的防禦護盾被擊碎！")

    # Check Boss HP bar drop for Illfang P1 summon
    prev_bar = boss.current_bar
    cur_phase = get_current_phase_spec(boss)
    next_phase = _next_untriggered_phase(boss)
    gate_hp = _phase_trigger_threshold_hp(boss, cur_phase) if next_phase is not None else 0

    phase_triggered = False
    actual_hp_dmg = 0
    if dmg > 0 and boss.current_hp > 0:
        boss.last_attacker_id = str(attacker_id)
        projected_hp = boss.current_hp - dmg
        if next_phase is not None and gate_hp > 0 and projected_hp <= gate_hp:
            # Health-gate: clamp at phase boundary so phase mechanics ALWAYS fire
            actual_hp_dmg = max(1, boss.current_hp - gate_hp)
            boss.current_hp = gate_hp
            phase_triggered = True
            logs.extend(_enter_phase(boss, next_phase, bundle))
        else:
            actual_hp_dmg = min(boss.current_hp, dmg)
            boss.current_hp = max(0, boss.current_hp - actual_hp_dmg)

    # Summon adds on bar break in P1 if applicable
    if (
        not phase_triggered
        and boss.current_hp > 0
        and boss.current_bar < prev_bar
        and str(cur_phase.get("mechanic") or "") == "on_bar_break_summon"
        and len(boss.adds) < 2
    ):
        _spawn_phase_adds(boss, cur_phase, bundle)
        logs.append(f"📢 {boss.name} 血條減少，召喚出遺跡狗頭人衛兵支援！")

    # Apply break gauge progress
    if boss.current_hp > 0:
        logs.extend(
            apply_break_damage(
                boss,
                break_power,
                switch_chain=switch_chain,
                is_unique_skill=is_unique_skill,
            )
        )

    killed = boss.current_hp <= 0
    la_user_id = boss.last_attacker_id if killed else None
    if killed:
        boss.adds.clear()
        boss.telegraph_active = False
        logs.append(f"🏆 【頭目討伐成功！】{boss.name} 化為藍色光點消散！")

    return {
        "damage": actual_hp_dmg + shield_absorbed,
        "hp_damage": actual_hp_dmg,
        "shield_absorbed": shield_absorbed,
        "phase_triggered": phase_triggered,
        "current_phase": boss.current_phase,
        "killed": killed,
        "la_user_id": la_user_id,
        "logs": logs,
    }


def step_boss_turn(
    boss: BossCombatState,
    *,
    party_members: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Advance Boss turn: tick debuffs/break/enrage, resolve telegraphed attack or prime next telegraph."""
    logs: list[str] = []
    phase = get_current_phase_spec(boss)
    sid = get_boss_skill_id(boss, phase)
    if sid not in boss.observed_skills:
        boss.observed_skills.append(sid)

    # Tick stun immunity
    if boss.stun_immune_turns > 0:
        boss.stun_immune_turns -= 1

    # Tick boss DoTs (burn/bleed/poison)
    dot_total = 0
    expired: list[str] = []
    for dname, dinfo in list(boss.debuffs.items()):
        if dname.startswith("_"):
            continue
        turns_left = int(dinfo.get("turns", 0))
        if dname in ("burn", "bleed", "poison"):
            dot_dmg = max(1, int(dinfo.get("dmg", round(boss.max_hp * 0.015))))
            dot_dmg = min(dot_dmg, max(0, boss.current_hp - 1))  # DoT never steals LA kill
            if dot_dmg > 0:
                boss.current_hp -= dot_dmg
                dot_total += dot_dmg
        turns_left -= 1
        if turns_left <= 0:
            expired.append(dname)
        else:
            dinfo["turns"] = turns_left
    for dname in expired:
        boss.debuffs.pop(dname, None)
    if dot_total > 0:
        logs.append(f"🔥 {boss.name} 受到持續異常狀態傷害 {dot_total} 點。")

    # Enrage check
    if boss.turn >= boss.enrage_turn and not boss.enraged:
        boss.enraged = True
        logs.append(f"💢 【狂暴時間到！】{boss.name} 進入狂暴狀態，攻擊力大幅提升 60%！")

    # Kagachi Serpent Stance regen if not broken
    if "_serpent_regen" in boss.debuffs and not boss.is_broken:
        heal_pct = float(boss.debuffs["_serpent_regen"].get("heal_pct", 0.06))
        heal_amt = max(1, round(boss.max_hp * heal_pct))
        boss.current_hp = min(boss.max_hp, boss.current_hp + heal_amt)
        boss.debuffs["_serpent_regen"]["turns"] = int(boss.debuffs["_serpent_regen"]["turns"]) - 1
        if boss.debuffs["_serpent_regen"]["turns"] <= 0:
            boss.debuffs.pop("_serpent_regen", None)
        logs.append(f"🐍 【千蛇劍陣】{boss.name} 回復了 {heal_amt} 點生命！（需雙人 Switch 破陣）")

    # Broken state skips Boss action
    if boss.is_broken:
        boss.break_turns_left -= 1
        if boss.break_turns_left <= 0:
            boss.is_broken = False
            logs.append(f"⚡ {boss.name} 從破防狀態恢復行動！")
        else:
            logs.append(f"💫 {boss.name} 處於破防暈眩中，本回合無法攻擊！")
        boss.turn += 1
        return {
            "acted": False,
            "raw_atk": 0,
            "damage_type": boss.damage_type,
            "is_aoe": False,
            "is_telegraphed_burst": False,
            "inflict_debuff": None,
            "observed_skill_id": sid,
            "logs": logs,
        }

    # Stunned Boss skips attack and gains 3 turns of Stun Immunity (抗暈)
    if "stun" in boss.debuffs:
        boss.debuffs.pop("stun", None)
        boss.stun_immune_turns = 3
        logs.append(f"💫 {boss.name} 因暈眩無法行動，並獲得 3 回合【抗暈】免疫！")
        boss.turn += 1
        return {
            "acted": False,
            "raw_atk": 0,
            "damage_type": boss.damage_type,
            "is_aoe": False,
            "is_telegraphed_burst": False,
            "inflict_debuff": None,
            "observed_skill_id": sid,
            "logs": logs,
        }

    atk_mult = float(phase.get("atk_mult", 1.0))
    if boss.enraged:
        atk_mult *= 1.60
    if "weaken" in boss.debuffs:
        atk_mult *= 0.80

    mech = str(phase.get("mechanic") or "")
    is_burst = boss.telegraph_active
    if is_burst:
        atk_mult *= 1.45
        boss.telegraph_active = False
        logs.append(f"💥 {boss.name} 釋放蓄力絕技【{boss.telegraph_skill_name or phase.get('name', '必殺技')}】！")
    else:
        # Prime telegraph every 2nd turn for tactical Parry/Switch counterplay
        if boss.turn % 2 == 0:
            boss.telegraph_active = True
            boss.telegraph_skill_id = sid
            boss.telegraph_skill_name = str(phase.get("name") or "重擊蓄力")
            boss.telegraph_damage_type = boss.damage_type
            boss.telegraph_requires_parry = mech in (
                "weapon_swap_nodachi",
                "twin_mouth_callout",
                "dual_tank_front_cleave",
                "holy_sword_counter_stance",
            )
            boss.telegraph_requires_switch = mech in (
                "sword_formation_regen",
                "twin_mouth_callout",
                "dual_tank_front_cleave",
                "immortal_system_shield",
                "cleaver_and_purple_breath",
            )
            boss.telegraph_callout = str(
                phase.get("telegraph")
                or f"⚠️ {boss.name} 正在蓄力發動強襲，請把握彈反或 Switch 時機！"
            )
            logs.append(boss.telegraph_callout)

    is_aoe = is_burst or mech in (
        "iaido_aoe_bleed",
        "miasma_spores",
        "dragon_breath_burn",
        "cleaver_and_purple_breath",
        "crimson_frenzy",
        "dual_tank_front_cleave",
        "echo_legacy_bosses",
    )
    inflict_debuff = str(phase.get("debuff") or "") or None
    if mech == "doom_countdown":
        inflict_debuff = "doom"

    # Extra pressure from alive adds
    add_atk_bonus = sum(int(a.get("atk", 0)) for a in boss.adds if int(a.get("hp", 0)) > 0)
    raw_atk = max(10, round(boss.atk * atk_mult) + add_atk_bonus)

    boss.turn += 1
    return {
        "acted": True,
        "raw_atk": raw_atk,
        "damage_type": boss.damage_type,
        "is_aoe": is_aoe,
        "is_telegraphed_burst": is_burst,
        "inflict_debuff": inflict_debuff,
        "mechanic": mech,
        "observed_skill_id": sid,
        "logs": logs,
    }
