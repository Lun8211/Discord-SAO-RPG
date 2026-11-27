"""Pure UI-agnostic SAO combat stat engine (ZERO discord imports).

Computes derived stats, 4-axis resistances (`slash`/`pierce`/`blunt`/`dragon`) with 75% hard cap,
progressive floor resistance penetration (`min(0.65, floor * 0.0065)`), 2pc/4pc Set bonuses,
all 8 weapon style passives + 2 Unique Skills (`dual_blades`/`holy_sword`), active buffs,
guild rally buff, Achievement Turn-In permanent bonuses, and rebirth scaling.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from src.rpg.models import ComputedStats

MAX_RESISTANCE = 0.75
MAX_FLOOR_RES_PEN = 0.65
FLOOR_RES_PEN_STEP = 0.0065
VALID_DAMAGE_TYPES: frozenset[str] = frozenset({"slash", "pierce", "blunt", "dragon"})

_SHIELD_KEYWORDS: tuple[str, ...] = ("shield", "aegis", "buckler", "盾")

_STYLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "sword": {
        "dmg_type": "slash",
        "mods": {"atk_pct": 0.05, "crit_rate": 0.03},
        "flags": {},
    },
    "rapier": {
        "dmg_type": "pierce",
        "mods": {"spd_flat": 18.0, "crit_rate": 0.08, "evasion": 0.04},
        "flags": {"final_hit_crit_bonus": 0.25},
    },
    "katana": {
        "dmg_type": "slash",
        "mods": {"atk_pct": 0.10, "armor_pen": 0.15, "crit_dmg": 0.20},
        "flags": {"can_sheathe": True},
    },
    "axe": {
        "dmg_type": "blunt",
        "mods": {"atk_pct": 0.16, "hp_pct": 0.08, "spd_flat": -10.0, "break_bonus": 0.20},
        "flags": {"cleave_aoe": True},
    },
    "mace": {
        "dmg_type": "blunt",
        "mods": {"hp_pct": 0.15, "def_pct": 0.15},
        "flags": {"aggro_mult": 1.50, "shield_spd_penalty": 0.0},
        "shield_bonus": {"def_pct": 0.08, "dmg_reduction": 0.05},
    },
    "holy": {
        "dmg_type": "slash",
        "mods": {"def_pct": 0.18, "dmg_reduction": 0.08},
        "flags": {"aggro_mult": 1.35, "shield_spd_penalty": 0.0, "counter_on_block": True},
        "shield_bonus": {"def_pct": 0.06, "dmg_reduction": 0.04},
    },
    "scythe": {
        "dmg_type": "slash",
        "mods": {"atk_pct": 0.08, "lifesteal": 0.06},
        "flags": {"execute_threshold": 0.20, "cleave_aoe": True},
    },
    "dagger": {
        "dmg_type": "pierce",
        "mods": {"spd_flat": 22.0, "evasion": 0.08, "crit_rate": 0.06},
        "flags": {"dual_hit_chance": 0.30},
        "offhand_weapon_bonus": {"atk_pct": 0.06},
    },
}


def _get_section(content: Any, section_name: str) -> dict[str, Any]:
    if content is None:
        return {}
    if isinstance(content, Mapping):
        val = content.get(section_name, {})
        return dict(val) if isinstance(val, Mapping) else {}
    val = getattr(content, section_name, {})
    return dict(val) if isinstance(val, Mapping) else {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return num if math.isfinite(num) else default


def _read_attr_or_key(obj: Any, primary: str, fallback: str | None = None, default: Any = 0) -> Any:
    if isinstance(obj, Mapping):
        if primary in obj and obj[primary] is not None:
            return obj[primary]
        if fallback and fallback in obj and obj[fallback] is not None:
            return obj[fallback]
        return default
    val = getattr(obj, primary, None)
    if val is not None:
        return val
    if fallback:
        val2 = getattr(obj, fallback, None)
        if val2 is not None:
            return val2
    return default


def _is_shield_item(item: Any) -> bool:
    slot = str(_read_attr_or_key(item, "slot", default="")).lower()
    if slot != "offhand":
        return False
    sub_type = str(_read_attr_or_key(item, "sub_type", default="")).lower()
    if sub_type == "shield":
        return True
    tags = _read_attr_or_key(item, "tags", default=())
    if isinstance(tags, (list, tuple, set, frozenset)) and "shield" in {
        str(t).lower() for t in tags
    }:
        return True
    tpl = str(_read_attr_or_key(item, "template_id", default="")).lower()
    name = str(_read_attr_or_key(item, "name", default="")).lower()
    return any(kw in tpl or kw in name for kw in _SHIELD_KEYWORDS)


def floor_resistance_penetration(floor: int) -> float:
    """Compute progressive Aincrad floor resistance penetration, capped at 65% (F100+)."""
    return min(MAX_FLOOR_RES_PEN, max(0, int(floor)) * FLOOR_RES_PEN_STEP)


def effective_resistance(raw_res: float, floor: int) -> float:
    """Clamp raw resistance to 75% BEFORE applying multiplicative floor penetration."""
    safe_raw = _safe_float(raw_res, 0.0)
    capped = min(MAX_RESISTANCE, max(0.0, safe_raw))
    pen = floor_resistance_penetration(floor)
    return max(0.0, round(capped * (1.0 - pen), 6))


def compute_set_bonuses(
    equipped_items: Sequence[Any], content: Any
) -> tuple[list[str], dict[str, float]]:
    """Compute active 2pc/4pc equipment Set descriptions and accumulated stat modifiers."""
    counts: dict[str, int] = {}
    for eq in equipped_items:
        set_id = str(_read_attr_or_key(eq, "set_id", default="") or "").strip()
        if set_id:
            counts[set_id] = counts.get(set_id, 0) + 1

    weq = _get_section(content, "weapons_equipment")
    sets_table = weq.get("sets") or weq.get("equipment_sets") or {}
    if not isinstance(sets_table, Mapping):
        return [], {}

    active_sets: list[str] = []
    bonuses: dict[str, float] = {}
    for set_id in sorted(counts):
        piece_count = counts[set_id]
        sdef = sets_table.get(set_id)
        if not isinstance(sdef, Mapping):
            continue
        raw_bonuses = sdef.get("bonuses", {})
        if not isinstance(raw_bonuses, Mapping):
            continue
        emoji = str(sdef.get("emoji", "")).strip()
        name = str(sdef.get("name", set_id)).strip()
        for req in (2, 4):
            if piece_count < req:
                continue
            tier_bonus = raw_bonuses.get(str(req))
            if tier_bonus is None:
                tier_bonus = raw_bonuses.get(req)
            if not isinstance(tier_bonus, Mapping):
                continue
            label = f"{emoji} {name} ({req}件)".strip()
            active_sets.append(label)
            for k, v in tier_bonus.items():
                bonuses[str(k)] = bonuses.get(str(k), 0.0) + _safe_float(v)
    return active_sets, bonuses


def compute_weapon_style_passives(
    weapon_style: str,
    equipped_items: Sequence[Any],
    content: Any,
    *,
    unique_skills: Sequence[str] = (),
) -> dict[str, Any]:
    """Resolve passive modifiers and combat flags for all 8 weapon styles and 2 Unique Skills."""
    style = str(weapon_style or "sword").strip().lower()
    unique_set = {str(u).strip().lower() for u in unique_skills if u}
    if style in ("dual_blades", "holy_sword"):
        unique_set.add(style)

    has_shield = False
    has_offhand_weapon = False
    for eq in equipped_items:
        slot = str(_read_attr_or_key(eq, "slot", default="")).lower()
        if slot == "offhand":
            if _is_shield_item(eq):
                has_shield = True
            else:
                has_offhand_weapon = True

    weq = _get_section(content, "weapons_equipment")
    w_classes = weq.get("weapon_classes", {})
    u_defs = weq.get("unique_skills", {})

    base_key = style if style in _STYLE_DEFAULTS else ("holy" if style == "holy_sword" else "sword")
    default_entry = _STYLE_DEFAULTS[base_key]
    dmg_type = str(default_entry["dmg_type"])
    mods: dict[str, float] = {k: float(v) for k, v in default_entry["mods"].items()}
    flags: dict[str, Any] = dict(default_entry["flags"])

    # Overlay JSON weapon_class passives if present (keeping built-in defaults authoritative if JSON absent)
    if isinstance(w_classes, Mapping) and isinstance(w_classes.get(base_key), Mapping):
        wc_json = w_classes[base_key]
        if wc_json.get("dmg_type") in VALID_DAMAGE_TYPES:
            dmg_type = str(wc_json["dmg_type"])
        json_passives = wc_json.get("passives")
        if isinstance(json_passives, Mapping):
            for k, v in json_passives.items():
                mods[str(k)] = _safe_float(v)

    if has_shield:
        if style in ("mace", "holy", "holy_sword") or "holy_sword" in unique_set:
            flags["shield_spd_penalty"] = 0.0
            for k, v in default_entry.get("shield_bonus", {}).items():
                mods[str(k)] = mods.get(str(k), 0.0) + float(v)
        else:
            flags["shield_spd_penalty"] = -8.0
            mods["spd_flat"] = mods.get("spd_flat", 0.0) - 8.0

    if has_offhand_weapon and base_key == "dagger":
        for k, v in default_entry.get("offhand_weapon_bonus", {}).items():
            mods[str(k)] = mods.get(str(k), 0.0) + float(v)

    max_skill_slots = 3
    if "dual_blades" in unique_set:
        max_skill_slots = 4
        flags["unique_dual_blades"] = True
        u_mods = {"atk_pct": 0.18, "spd_flat": 15.0, "crit_rate": 0.08, "crit_dmg": 0.25}
        if isinstance(u_defs, Mapping) and isinstance(u_defs.get("dual_blades"), Mapping):
            jp = u_defs["dual_blades"].get("passives")
            if isinstance(jp, Mapping):
                u_mods = {str(k): _safe_float(v) for k, v in jp.items()}
        for k, v in u_mods.items():
            mods[k] = mods.get(k, 0.0) + v
        if has_offhand_weapon:
            mods["atk_pct"] = mods.get("atk_pct", 0.0) + 0.10
            mods["crit_rate"] = mods.get("crit_rate", 0.0) + 0.05

    if "holy_sword" in unique_set:
        max_skill_slots = 4
        flags["unique_holy_sword"] = True
        flags["shield_spd_penalty"] = 0.0
        flags["parry_counter_mult"] = 1.50
        u_mods = {"def_pct": 0.22, "atk_pct": 0.12, "dmg_reduction": 0.12, "res_all": 0.08}
        if isinstance(u_defs, Mapping) and isinstance(u_defs.get("holy_sword"), Mapping):
            jp = u_defs["holy_sword"].get("passives")
            if isinstance(jp, Mapping):
                u_mods = {str(k): _safe_float(v) for k, v in jp.items()}
        for k, v in u_mods.items():
            mods[k] = mods.get(k, 0.0) + v

    return {
        "style": style,
        "dmg_type": dmg_type,
        "max_skill_slots": max_skill_slots,
        "has_shield": has_shield,
        "has_offhand_weapon": has_offhand_weapon,
        "flags": flags,
        "mods": mods,
    }


def _merge_mod_bucket(bucket: dict[str, float], source: Mapping[str, Any] | None) -> None:
    if not source:
        return
    key_aliases = {
        "dodge": "evasion",
        "gold_bonus": "col_bonus",
        "skill_dmg": "skill_dmg_bonus",
        "break_power": "break_bonus",
        "def_pen": "armor_pen",
        "spd": "spd_flat",
    }
    for raw_k, raw_v in source.items():
        if isinstance(raw_v, bool) or not isinstance(raw_v, (int, float)):
            continue
        k = key_aliases.get(str(raw_k), str(raw_k))
        bucket[k] = bucket.get(k, 0.0) + _safe_float(raw_v)


def compute_player_stats(
    player: Any,
    equipped_items: Sequence[Any],
    content: Any,
    *,
    floor: int = 1,
    active_buffs: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    guild_buff: Mapping[str, Any] | None = None,
    turnin_bonuses: Mapping[str, float] | None = None,
) -> ComputedStats:
    """Compute complete SAO combat stats without mutating any caller inputs."""
    level = max(1, int(_read_attr_or_key(player, "level", default=1)))
    rebirth_count = max(0, int(_read_attr_or_key(player, "rebirth_count", default=0)))
    stat_str = max(0, int(_read_attr_or_key(player, "str_stat", "stat_str", default=0)))
    stat_agi = max(0, int(_read_attr_or_key(player, "agi_stat", "stat_agi", default=0)))
    stat_vit = max(0, int(_read_attr_or_key(player, "vit_stat", "stat_vit", default=0)))
    stat_dex = max(0, int(_read_attr_or_key(player, "dex_stat", "stat_dex", default=0)))
    stat_luk = max(0, int(_read_attr_or_key(player, "luk_stat", "stat_luk", default=0)))
    weapon_style = str(_read_attr_or_key(player, "weapon_style", default="sword") or "sword")
    raw_uniques = _read_attr_or_key(player, "unique_skills", default=())
    unique_skills = list(raw_uniques) if isinstance(raw_uniques, (list, tuple, set)) else []

    lv_delta = max(0, level - 1)
    raw_hp = 160.0 + lv_delta * 26.0 + stat_vit * 18.0 + stat_str * 3.0
    raw_sp = 60.0 + lv_delta * 4.0 + stat_dex * 2.0 + stat_vit * 1.0
    raw_atk = 22.0 + lv_delta * 4.5 + stat_str * 3.2 + stat_dex * 1.0
    raw_def = 12.0 + lv_delta * 2.5 + stat_vit * 2.2 + stat_agi * 0.5
    raw_spd = 100.0 + lv_delta * 0.6 + stat_agi * 2.0 + stat_dex * 0.6

    mods: dict[str, float] = {
        "hp_flat": 0.0,
        "sp_flat": 0.0,
        "atk_flat": 0.0,
        "def_flat": 0.0,
        "spd_flat": 0.0,
        "hp_pct": 0.0,
        "sp_pct": 0.0,
        "atk_pct": 0.0,
        "def_pct": 0.0,
        "spd_pct": 0.0,
        "crit_rate": 0.08 + stat_dex * 0.004 + stat_luk * 0.005,
        "crit_dmg": 1.50 + stat_str * 0.005 + stat_dex * 0.004,
        "evasion": 0.04 + stat_agi * 0.004 + stat_luk * 0.002,
        "lifesteal": 0.0,
        "col_bonus": 0.12 * rebirth_count + stat_luk * 0.003,
        "exp_bonus": 0.12 * rebirth_count,
        "drop_bonus": stat_luk * 0.005,
        "mine_bonus": 0.0,
        "skill_dmg_bonus": 0.0,
        "dmg_reduction": 0.0,
        "armor_pen": 0.0,
        "break_bonus": 0.0,
        "potion_bonus": 0.0,
        "healing_bonus": 0.0,
        "battle_regen_pct": 0.0,
        "res_slash": 0.0,
        "res_pierce": 0.0,
        "res_blunt": 0.0,
        "res_dragon": 0.0,
        "res_all": 0.0,
    }

    weq = _get_section(content, "weapons_equipment")
    named_items = weq.get("named_items", {})
    items_catalog = _get_section(content, "items_crystals")

    for eq in equipped_items:
        raw_hp += _safe_float(_read_attr_or_key(eq, "hp", "base_hp", default=0))
        raw_atk += _safe_float(_read_attr_or_key(eq, "atk", "base_atk", default=0))
        raw_def += _safe_float(_read_attr_or_key(eq, "def_", "defense", default=0))
        eq_sp = _read_attr_or_key(eq, "sp", "mp", default=0)
        raw_sp += _safe_float(eq_sp)
        raw_spd += _safe_float(_read_attr_or_key(eq, "spd", "base_spd", default=0))

        affixes = _read_attr_or_key(eq, "affixes", default={})
        if isinstance(affixes, Mapping):
            _merge_mod_bucket(mods, affixes)

        tpl_id = str(_read_attr_or_key(eq, "template_id", default="") or "")
        if tpl_id and isinstance(named_items, Mapping):
            nspec = named_items.get(tpl_id)
            if isinstance(nspec, Mapping) and isinstance(nspec.get("passive_bonuses"), Mapping):
                _merge_mod_bucket(mods, nspec["passive_bonuses"])

        # Tempering / Awakening milestone passives (★3 & ★5)
        t_lv = int(_safe_float(_read_attr_or_key(eq, "temper_level", default=0), 0.0))
        if t_lv >= 3:
            _merge_mod_bucket(
                mods,
                {
                    "crit_rate": 0.03,
                    "res_slash": 0.03,
                    "res_pierce": 0.03,
                    "res_blunt": 0.03,
                    "res_dragon": 0.03,
                },
            )
        if t_lv >= 5:
            _merge_mod_bucket(mods, {"skill_dmg_bonus": 0.08, "dmg_reduction": 0.05})

        # Socketed Combat Crystal bonuses
        sock_id = str(_read_attr_or_key(eq, "socket_crystal_id", default="") or "").strip()
        if sock_id and isinstance(items_catalog, Mapping):
            cspec = items_catalog.get(sock_id)
            if isinstance(cspec, Mapping):
                eff = cspec.get("effect")
                if isinstance(eff, Mapping) and isinstance(eff.get("socket_bonuses"), Mapping):
                    _merge_mod_bucket(mods, eff["socket_bonuses"])

    # 2pc / 4pc Equipment Set bonuses
    active_sets, set_bonuses = compute_set_bonuses(equipped_items, content)
    _merge_mod_bucket(mods, set_bonuses)

    # Weapon Style & Unique Skill passives
    passives = compute_weapon_style_passives(
        weapon_style, equipped_items, content, unique_skills=unique_skills
    )
    _merge_mod_bucket(mods, passives["mods"])

    # Active Buffs (cooking dishes, stew, miasma penalties, world buffs)
    if isinstance(active_buffs, Mapping):
        if any(isinstance(v, Mapping) for v in active_buffs.values()):
            for val in active_buffs.values():
                if isinstance(val, Mapping):
                    inner = val.get("bonuses") or val.get("buff") or val
                    if isinstance(inner, Mapping):
                        _merge_mod_bucket(mods, inner)
        else:
            _merge_mod_bucket(mods, active_buffs)
    elif isinstance(active_buffs, Sequence) and not isinstance(active_buffs, (str, bytes)):
        for entry in active_buffs:
            if isinstance(entry, Mapping):
                inner = entry.get("bonuses") or entry.get("buff") or entry
                if isinstance(inner, Mapping):
                    _merge_mod_bucket(mods, inner)

    # Guild Rally Buff
    if isinstance(guild_buff, Mapping) and guild_buff.get("active", True) is not False:
        inner_gb = guild_buff.get("bonuses") if isinstance(guild_buff.get("bonuses"), Mapping) else guild_buff
        if isinstance(inner_gb, Mapping):
            _merge_mod_bucket(mods, inner_gb)

    # Achievement Turn-In Permanent Bonuses
    if isinstance(turnin_bonuses, Mapping):
        _merge_mod_bucket(mods, turnin_bonuses)

    rebirth_mult = 1.0 + 0.18 * rebirth_count
    max_hp = max(50, round((raw_hp + mods["hp_flat"]) * max(0.2, 1.0 + mods["hp_pct"]) * rebirth_mult))
    max_sp = max(
        30,
        round((raw_sp + mods["sp_flat"]) * max(0.2, 1.0 + mods["sp_pct"]) * (1.0 + 0.06 * rebirth_count)),
    )
    atk = max(10, round((raw_atk + mods["atk_flat"]) * max(0.2, 1.0 + mods["atk_pct"]) * rebirth_mult))
    defense = max(5, round((raw_def + mods["def_flat"]) * max(0.2, 1.0 + mods["def_pct"]) * rebirth_mult))
    spd = max(30, round((raw_spd + mods["spd_flat"]) * max(0.3, 1.0 + mods["spd_pct"])))

    crit_rate = min(0.85, max(0.05, mods["crit_rate"]))
    crit_dmg = min(4.50, max(1.50, mods["crit_dmg"]))
    evasion = min(0.45, max(0.01, mods["evasion"]))
    lifesteal = min(0.35, max(0.0, mods["lifesteal"]))
    dmg_reduction = min(0.45, max(0.0, mods["dmg_reduction"]))
    armor_pen = min(0.60, max(0.0, mods["armor_pen"]))

    res_all = mods["res_all"]
    res_slash = min(MAX_RESISTANCE, max(0.0, mods["res_slash"] + res_all))
    res_pierce = min(MAX_RESISTANCE, max(0.0, mods["res_pierce"] + res_all))
    res_blunt = min(MAX_RESISTANCE, max(0.0, mods["res_blunt"] + res_all))
    res_dragon = min(MAX_RESISTANCE, max(0.0, mods["res_dragon"] + res_all))

    avg_res = (res_slash + res_pierce + res_blunt + res_dragon) / 4.0
    combat_power = round(
        atk * 5.5
        + defense * 4.2
        + max_hp * 0.65
        + max_sp * 1.1
        + spd * 2.5
        + (crit_rate * 100.0) * 14.0
        + ((crit_dmg - 1.50) * 100.0) * 8.0
        + (evasion * 100.0) * 12.0
        + (lifesteal * 100.0) * 18.0
        + (dmg_reduction * 100.0) * 20.0
        + (avg_res * 100.0) * 16.0
        + (armor_pen * 100.0) * 12.0
    )

    aggro_mult = float(passives["flags"].get("aggro_mult", 1.0))

    return ComputedStats(
        max_hp=max_hp,
        max_mp=max_sp,
        atk=atk,
        def_=defense,
        crit_rate=round(crit_rate, 6),
        crit_dmg=round(crit_dmg, 6),
        dodge=round(evasion, 6),
        lifesteal=round(lifesteal, 6),
        gold_bonus=round(mods["col_bonus"], 6),
        exp_bonus=round(mods["exp_bonus"], 6),
        drop_bonus=round(mods["drop_bonus"], 6),
        mine_bonus=round(mods["mine_bonus"], 6),
        skill_dmg_bonus=round(mods["skill_dmg_bonus"], 6),
        dmg_reduction=round(dmg_reduction, 6),
        combat_power=combat_power,
        active_sets=active_sets,
        max_sp=max_sp,
        defense=defense,
        spd=spd,
        evasion=round(evasion, 6),
        res_slash=round(res_slash, 6),
        res_pierce=round(res_pierce, 6),
        res_blunt=round(res_blunt, 6),
        res_dragon=round(res_dragon, 6),
        col_bonus=round(mods["col_bonus"], 6),
        healing_bonus=round(mods["healing_bonus"] + mods["potion_bonus"], 6),
        armor_pen=round(armor_pen, 6),
        break_bonus=round(mods["break_bonus"], 6),
        aggro_mult=aggro_mult,
        potion_bonus=round(mods["potion_bonus"], 6),
        battle_regen_pct=round(mods["battle_regen_pct"], 6),
        active_passives=passives,
        set_bonuses=set_bonuses,
        floor=int(floor),
    )
