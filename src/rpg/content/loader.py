"""Typed, thread-safe JSON content loader & strict startup/test schema validator for SAO Aincrad."""

from __future__ import annotations

import copy
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.rpg import assets

CONTENT_DIR = Path(__file__).resolve().parent

CONTENT_FILES: dict[str, str] = {
    "biomes": "biomes.json",
    "floors_override": "floors_override.json",
    "bosses": "bosses.json",
    "monsters": "monsters.json",
    "chests_loot": "chests_loot.json",
    "weapons_equipment": "weapons_equipment.json",
    "sword_skills": "sword_skills.json",
    "items_crystals": "items_crystals.json",
    "recipes": "recipes.json",
    "quests_events": "quests_events.json",
}

MILESTONE_BOSS_FLOORS: tuple[int, ...] = (1, 10, 20, 25, 30, 40, 50, 60, 70, 74, 75, 80, 90, 100)
REQUIRED_YUI_LOGS: tuple[str, ...] = (
    "yui_log_f01",
    "yui_log_f10",
    "yui_log_f25",
    "yui_log_f27_black_cats",
    "yui_log_f50",
    "yui_log_f75",
    "yui_log_f100",
)
REQUIRED_SAO_CRYSTALS: tuple[str, ...] = (
    "healing_crystal",
    "teleport_crystal",
    "antidote_crystal",
    "corridor_crystal",
)
REQUIRED_MAGIC_STONES: tuple[str, ...] = ("reroll_stone", "swap_stone", "refine_stone")
VALID_DAMAGE_TYPES: frozenset[str] = frozenset({"slash", "pierce", "blunt", "dragon"})
VALID_WEAPON_CLASSES: frozenset[str] = frozenset(
    {"sword", "rapier", "katana", "axe", "mace", "holy", "scythe", "dagger"}
)
VALID_UNIQUE_SKILLS: frozenset[str] = frozenset({"dual_blades", "holy_sword"})
VALID_SLOTS: tuple[str, ...] = (
    "weapon",
    "offhand",
    "helmet",
    "armor",
    "gloves",
    "boots",
    "ring",
    "necklace",
)
VALID_RARITIES: tuple[str, ...] = ("plain", "fine", "rare", "set", "legendary", "named")
VALID_CHEST_TIERS: tuple[str, ...] = (
    "wooden",
    "iron",
    "silver",
    "gold",
    "boss_relic",
    "mimic_trap",
)
VALID_DEBUFFS: frozenset[str] = frozenset(
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
REQUIRED_RES_AFFIXES: tuple[str, ...] = (
    "res_slash",
    "res_pierce",
    "res_blunt",
    "res_dragon",
)
_PLACEHOLDER_RE = re.compile(r"\b(TODO|TBD|PLACEHOLDER|FIXME)\b", re.IGNORECASE)
_VALID_RASTER_EXTS = (".png", ".webp", ".jpg", ".jpeg")


@dataclass(frozen=True)
class SAOContentBundle:
    """Immutable container holding all 10 validated SAO Aincrad static JSON collections."""

    biomes: dict[str, Any]
    floors_override: dict[str, Any]
    bosses: dict[str, Any]
    monsters: dict[str, Any]
    chests_loot: dict[str, Any]
    weapons_equipment: dict[str, Any]
    sword_skills: dict[str, Any]
    items_crystals: dict[str, Any]
    recipes: dict[str, Any]
    quests_events: dict[str, Any]


_CACHE_LOCK = threading.RLock()
_CACHED_BUNDLE: SAOContentBundle | None = None


def _require_dict(val: Any, msg: str) -> dict[str, Any]:
    if isinstance(val, dict):
        return val
    raise ValueError(msg)


def load_content_from_dir(content_dir: Path) -> SAOContentBundle:
    """Load all 10 SAO content JSON files from an explicit directory without mutating global cache."""
    loaded: dict[str, dict[str, Any]] = {}
    for field_name, filename in CONTENT_FILES.items():
        path = content_dir / filename
        try:
            raw_text = path.read_text(encoding="utf-8")
            parsed = json.loads(raw_text)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"{filename}: missing file or invalid JSON: {exc}") from exc
        loaded[field_name] = _require_dict(
            parsed, f"{filename}: root JSON value must be an object/dict"
        )

    # Enrich monsters with tier-scaled base_hp/hp and sword_skills with canonical alias keys
    biomes = loaded["biomes"]
    rules = biomes.get("scaling_rules", {})
    tiers_raw = biomes.get("tiers", [])
    tier_mult_by_id: dict[int, float] = {}
    if isinstance(tiers_raw, list):
        for tinfo in tiers_raw:
            if isinstance(tinfo, dict) and "tier" in tinfo:
                raw_mult = tinfo.get("tier_mult")
                if raw_mult is None:
                    raw_mult = tinfo.get("stat_mult", 1.0)
                tier_mult_by_id[int(tinfo["tier"])] = float(raw_mult)
    elif isinstance(tiers_raw, dict):
        for k, tinfo in tiers_raw.items():
            if isinstance(tinfo, dict):
                raw_mult = tinfo.get("tier_mult")
                if raw_mult is None:
                    raw_mult = tinfo.get("stat_mult", 1.0)
                tier_mult_by_id[int(k)] = float(raw_mult)
    if isinstance(rules, dict) and "monster_hp" in rules:
        elite_hp_m = float((rules.get("elite_mult") or {}).get("hp", 1.85))
        fb_hp_m = float((rules.get("field_boss_mult") or {}).get("hp", 4.2))
        for mspec in loaded["monsters"].values():
            if not isinstance(mspec, dict):
                continue
            tier = int(mspec.get("tier", 1))
            tmult = tier_mult_by_id.get(tier, 1.0)
            rep_floor = max(1, (tier - 1) * 10 + 5)
            f_hp = _scale_stat(rules["monster_hp"], rep_floor, tmult)
            kind = str(mspec.get("kind", "normal")).lower()
            mult = float(mspec.get("hp_mult", 1.0))
            if kind == "field_boss":
                mult *= fb_hp_m
            elif kind == "elite":
                mult *= elite_hp_m
            derived_hp = max(35, round(f_hp * mult))
            mspec.setdefault("base_hp", derived_hp)
            mspec.setdefault("hp", derived_hp)

    for sspec in loaded["sword_skills"].values():
        if not isinstance(sspec, dict):
            continue
        if "weapon_class" in sspec and "weapon_style" not in sspec:
            sspec["weapon_style"] = sspec["weapon_class"]
        if "cooldown_turns" in sspec and "cooldown" not in sspec:
            sspec["cooldown"] = sspec["cooldown_turns"]

    return SAOContentBundle(**loaded)


def load_content(force_reload: bool = False) -> SAOContentBundle:
    """Load and cache the SAO Aincrad JSON content bundle in a thread-safe manner."""
    global _CACHED_BUNDLE
    with _CACHE_LOCK:
        if _CACHED_BUNDLE is None or force_reload:
            _CACHED_BUNDLE = load_content_from_dir(CONTENT_DIR)
        return _CACHED_BUNDLE


def _scale_stat(rule: dict[str, Any], floor: int, tier_mult: float) -> int:
    base = float(rule["base"])
    growth = float(rule["growth"])
    linear = float(rule.get("linear", 0.0))
    val = base * (growth ** (floor - 1)) + linear * (floor - 1)
    if rule.get("use_tier_mult"):
        val *= tier_mult
    return round(val)


def _parse_special_rules(rules: list[str]) -> dict[str, Any]:
    flags: dict[str, Any] = {}
    for entry in rules:
        if ":" in entry:
            key, raw_val = entry.split(":", 1)
            key = key.strip()
            raw_val = raw_val.strip()
            try:
                flags[key] = float(raw_val)
            except ValueError:
                flags[key] = raw_val
        else:
            flags[entry.strip()] = True
    return flags


def resolve_floor_config(
    floor: int,
    bundle: SAOContentBundle | None = None,
) -> dict[str, Any]:
    """Deterministically resolve full configuration for any Aincrad floor 1..100 (zero eval)."""
    if isinstance(floor, bool) or not isinstance(floor, int) or not (1 <= floor <= 100):
        raise ValueError(f"Invalid Aincrad floor: {floor!r} (must be integer 1..100)")

    content = bundle if bundle is not None else load_content()
    tiers: list[dict[str, Any]] = content.biomes.get("tiers", [])
    matched_tier: dict[str, Any] | None = None
    for t in tiers:
        if int(t["floor_min"]) <= floor <= int(t["floor_max"]):
            matched_tier = t
            break
    if matched_tier is None:
        raise ValueError(f"biomes.json: no tier covers floor {floor}")

    rules = content.biomes["scaling_rules"]
    tier_mult = float(matched_tier["tier_mult"])
    base_hp = _scale_stat(rules["monster_hp"], floor, tier_mult)
    base_atk = _scale_stat(rules["monster_atk"], floor, tier_mult)
    base_def = _scale_stat(rules["monster_def"], floor, tier_mult)
    exp_base = _scale_stat(rules["exp_base"], floor, tier_mult)
    col_base = _scale_stat(rules["col_base"], floor, tier_mult)

    rp_rule = rules["res_penetration"]
    res_penetration = round(
        min(float(rp_rule["max"]), floor * float(rp_rule["per_floor"])),
        4,
    )

    override = _require_dict(
        content.floors_override.get(str(floor), {}),
        f"floors_override.json: entry for floor {floor} must be a dict",
    )

    town_name = str(
        override.get(
            "town_name",
            str(matched_tier["default_town_pattern"]).format(floor=floor),
        )
    )
    field_name = str(
        override.get(
            "field_name",
            str(matched_tier["field_name_pattern"]).format(floor=floor),
        )
    )
    labyrinth_name = str(
        override.get(
            "labyrinth_name",
            str(matched_tier["labyrinth_name_pattern"]).format(floor=floor),
        )
    )
    landmark = str(override.get("landmark", f"第 {floor} 層・轉移門廣場"))
    special_rules = list(override.get("special_rules", []))
    rule_flags = _parse_special_rules(special_rules)

    override_boss_id = override.get("boss_id")
    if override_boss_id:
        if override_boss_id not in content.bosses:
            raise ValueError(
                f"floors_override.json[{floor}]: dangling boss_id '{override_boss_id}'"
            )
        boss_spec = copy.deepcopy(content.bosses[override_boss_id])
        boss_id = str(override_boss_id)
        is_milestone_boss = bool(boss_spec.get("is_milestone", False))
    else:
        tpl_id = str(matched_tier["default_boss_template"])
        if tpl_id not in content.bosses:
            raise ValueError(
                f"biomes.json[tier={matched_tier['tier']}]: dangling default_boss_template '{tpl_id}'"
            )
        tpl = content.bosses[tpl_id]
        patterns = tpl.get("name_patterns") or [tpl["name"]]
        idx = (floor - int(matched_tier["floor_min"])) % len(patterns)
        boss_mult = rules["boss_template_mult"]
        boss_spec = copy.deepcopy(tpl)
        boss_id = f"floor_{floor}_guardian"
        boss_spec["id"] = boss_id
        boss_spec["name"] = f"第 {floor} 層頭目・{patterns[idx]}"
        boss_spec["floor"] = floor
        boss_spec["is_template"] = False
        boss_spec["base_hp"] = round(base_hp * float(boss_mult["hp"]))
        boss_spec["base_atk"] = round(base_atk * float(boss_mult["atk"]))
        boss_spec["base_def"] = round(base_def * float(boss_mult["def"]))
        is_milestone_boss = False

    return {
        "floor": floor,
        "tier": int(matched_tier["tier"]),
        "biome_name": str(matched_tier["name"]),
        "town_name": town_name,
        "landmark": landmark,
        "field_name": field_name,
        "labyrinth_name": labyrinth_name,
        "secret_realm_name": str(matched_tier["secret_realm_name"]),
        "explore_required": int(matched_tier.get("explore_required", 100)),
        "base_hp": base_hp,
        "base_atk": base_atk,
        "base_def": base_def,
        "exp_base": exp_base,
        "col_base": col_base,
        "res_penetration": res_penetration,
        "mob_pool_ids": list(matched_tier["mob_pool_ids"]),
        "elite_mob_ids": list(matched_tier["elite_mob_ids"]),
        "field_boss_id": str(matched_tier["field_boss_id"]),
        "chest_table_id": str(matched_tier["chest_table_id"]),
        "world_boss_id": str(matched_tier["world_boss_id"]),
        "ore_ids": list(matched_tier["ore_ids"]),
        "meat_ids": list(matched_tier["meat_ids"]),
        "banner_asset_key": str(matched_tier["banner_asset_key"]),
        "boss_id": boss_id,
        "boss": boss_spec,
        "is_milestone_boss": is_milestone_boss,
        "hidden_dungeon_id": override.get("hidden_dungeon_id"),
        "lore_unlock_id": override.get("lore_unlock_id"),
        "flavor_desc": str(override.get("flavor_desc", "")),
        "special_rules": special_rules,
        "rule_flags": rule_flags,
    }


def _scan_for_placeholders(obj: Any, path: str) -> None:
    if isinstance(obj, str):
        if _PLACEHOLDER_RE.search(obj):
            raise ValueError(f"{path}: placeholder token detected in '{obj[:60]}'")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _scan_for_placeholders(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _scan_for_placeholders(item, f"{path}[{idx}]")


def _assert_valid_asset_key(key: Any, ctx: str) -> None:
    if not isinstance(key, str) or not key.strip():
        raise ValueError(f"{ctx}: missing or empty asset key")
    if not assets.has_asset_key(key):
        raise ValueError(f"{ctx}: unknown asset key '{key}'")
    url = assets.resolve_asset_key(key)
    if url is None or not url.startswith("https://"):
        raise ValueError(f"{ctx}: asset key '{key}' resolved to invalid URL '{url}'")
    lower_url = url.lower()
    if ".svg" in lower_url or not lower_url.endswith(_VALID_RASTER_EXTS):
        raise ValueError(f"{ctx}: asset key '{key}' resolved to non-raster/SVG URL '{url}'")


def _scan_all_asset_keys(obj: Any, path: str) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("asset_key", "banner_asset_key"):
                _assert_valid_asset_key(v, f"{path}.{k}")
            else:
                _scan_all_asset_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _scan_all_asset_keys(item, f"{path}[{idx}]")


def _validate_reward_items(reward_items: Any, items_map: dict[str, Any], ctx: str) -> None:
    if reward_items is None:
        return
    checked = _require_dict(reward_items, f"{ctx}: reward_items must be a dict")
    for item_id, qty in checked.items():
        if item_id not in items_map:
            raise ValueError(f"{ctx}: dangling item_id '{item_id}'")
        if not isinstance(qty, int) or qty <= 0:
            raise ValueError(f"{ctx}: invalid quantity {qty!r} for '{item_id}'")


def validate_content_bundle(bundle: SAOContentBundle) -> SAOContentBundle:
    """Validate all 7 integrity checks across the entire SAO content bundle. Raises ValueError on defect."""
    sections = {
        "biomes": bundle.biomes,
        "floors_override": bundle.floors_override,
        "bosses": bundle.bosses,
        "monsters": bundle.monsters,
        "chests_loot": bundle.chests_loot,
        "weapons_equipment": bundle.weapons_equipment,
        "sword_skills": bundle.sword_skills,
        "items_crystals": bundle.items_crystals,
        "recipes": bundle.recipes,
        "quests_events": bundle.quests_events,
    }

    # Check 1: Non-empty collections & zero placeholders
    for name, sec in sections.items():
        if not isinstance(sec, dict) or not sec:
            raise ValueError(f"{name}.json: section must be a non-empty object")
        _scan_for_placeholders(sec, f"{name}.json")

    bosses = bundle.bosses
    monsters = bundle.monsters
    chests_loot = bundle.chests_loot
    weq = bundle.weapons_equipment
    skills = bundle.sword_skills
    items = bundle.items_crystals
    recipes = bundle.recipes
    qe = bundle.quests_events

    named_items: dict[str, Any] = weq.get("named_items", {})
    sets_map: dict[str, Any] = weq.get("sets", {})
    tier_tables: dict[str, Any] = chests_loot.get("tier_tables", {})
    yui_logs: dict[str, Any] = qe.get("yui_logs", {})

    # Check 2: Continuous F1-F100 partition & biome tier referential integrity
    tiers = bundle.biomes.get("tiers")
    if not isinstance(tiers, list) or len(tiers) != 10:
        raise ValueError("biomes.json: 'tiers' must contain exactly 10 biome tier entries")

    expected_floor = 1
    tier_world_boss_ids: list[str] = []
    for idx, tier in enumerate(tiers, start=1):
        if int(tier.get("tier", -1)) != idx:
            raise ValueError(f"biomes.json: tier index mismatch at position {idx}")
        f_min = int(tier.get("floor_min", -1))
        f_max = int(tier.get("floor_max", -1))
        if f_min != expected_floor or f_max != expected_floor + 9:
            raise ValueError(
                f"biomes.json: tier {idx} must cover floors {expected_floor}..{expected_floor + 9}, "
                f"got {f_min}..{f_max}"
            )
        expected_floor = f_max + 1

        mob_pool = tier.get("mob_pool_ids", [])
        if not isinstance(mob_pool, list) or len(mob_pool) < 4:
            raise ValueError(f"biomes.json[tier={idx}]: mob_pool_ids must have >= 4 entries")
        for mid in mob_pool:
            if mid not in monsters:
                raise ValueError(f"biomes.json[tier={idx}]: dangling mob_id '{mid}'")

        elites = tier.get("elite_mob_ids", [])
        if not isinstance(elites, list) or len(elites) < 1:
            raise ValueError(f"biomes.json[tier={idx}]: elite_mob_ids must have >= 1 entry")
        for mid in elites:
            if mid not in monsters:
                raise ValueError(f"biomes.json[tier={idx}]: dangling elite mob_id '{mid}'")

        fb_id = tier.get("field_boss_id")
        if fb_id not in monsters:
            raise ValueError(f"biomes.json[tier={idx}]: dangling field_boss_id '{fb_id}'")

        ct_id = tier.get("chest_table_id")
        if ct_id not in tier_tables:
            raise ValueError(f"biomes.json[tier={idx}]: dangling chest_table_id '{ct_id}'")

        tpl_id = tier.get("default_boss_template")
        if tpl_id not in bosses:
            raise ValueError(f"biomes.json[tier={idx}]: dangling default_boss_template '{tpl_id}'")

        wb_id = tier.get("world_boss_id")
        if wb_id not in bosses:
            raise ValueError(f"biomes.json[tier={idx}]: dangling world_boss_id '{wb_id}'")
        tier_world_boss_ids.append(str(wb_id))

        ores = tier.get("ore_ids", [])
        if not isinstance(ores, list) or not ores:
            raise ValueError(f"biomes.json[tier={idx}]: ore_ids must be non-empty")
        for oid in ores:
            if oid not in items:
                raise ValueError(f"biomes.json[tier={idx}]: dangling ore_id '{oid}'")

        meats = tier.get("meat_ids", [])
        if not isinstance(meats, list) or not meats:
            raise ValueError(f"biomes.json[tier={idx}]: meat_ids must be non-empty")
        for meat_id in meats:
            if meat_id not in items:
                raise ValueError(f"biomes.json[tier={idx}]: dangling meat_id '{meat_id}'")

        _assert_valid_asset_key(tier.get("banner_asset_key"), f"biomes.json[tier={idx}].banner_asset_key")

    for floor_key, ov in bundle.floors_override.items():
        if not floor_key.isdigit() or not (1 <= int(floor_key) <= 100):
            raise ValueError(f"floors_override.json: invalid floor key '{floor_key}'")
        if "boss_id" in ov and ov["boss_id"] not in bosses:
            raise ValueError(
                f"floors_override.json[{floor_key}]: dangling boss_id '{ov['boss_id']}'"
            )
        if "lore_unlock_id" in ov and ov["lore_unlock_id"] not in yui_logs:
            raise ValueError(
                f"floors_override.json[{floor_key}]: dangling lore_unlock_id '{ov['lore_unlock_id']}'"
            )

    # Check 3: All 100 floors resolve with strict monotonic scaling & valid res penetration
    prev_cfg: dict[str, Any] | None = None
    for floor in range(1, 101):
        cfg = resolve_floor_config(floor, bundle)
        if prev_cfg is not None:
            for stat_key in ("base_hp", "base_atk", "base_def", "exp_base", "col_base"):
                if not (cfg[stat_key] > prev_cfg[stat_key]):
                    raise ValueError(
                        f"Floor scaling non-monotonic for {stat_key}: "
                        f"F{floor - 1}={prev_cfg[stat_key]} vs F{floor}={cfg[stat_key]}"
                    )
            if cfg["res_penetration"] < prev_cfg["res_penetration"]:
                raise ValueError(
                    f"res_penetration decreased at F{floor}: "
                    f"{prev_cfg['res_penetration']} -> {cfg['res_penetration']}"
                )
        if not (0.0 <= cfg["res_penetration"] <= 0.65):
            raise ValueError(f"F{floor}: res_penetration out of bounds [0, 0.65]: {cfg['res_penetration']}")
        boss = cfg["boss"]
        if int(boss.get("hp_bars", 0)) < 3:
            raise ValueError(f"F{floor}: resolved boss '{cfg['boss_id']}' must have hp_bars >= 3")
        if len(boss.get("phases", [])) < 2:
            raise ValueError(f"F{floor}: resolved boss '{cfg['boss_id']}' must have >= 2 phases")
        prev_cfg = cfg

    # Check 4: All bosses (14 milestone + 10 tier templates + 10 world bosses) & all monsters
    for boss_id, bspec in bosses.items():
        dmg_types = bspec.get("dmg_types", [])
        if not isinstance(dmg_types, list) or not dmg_types:
            raise ValueError(f"bosses.json[{boss_id}]: dmg_types must be non-empty")
        for dt in dmg_types:
            if dt not in VALID_DAMAGE_TYPES:
                raise ValueError(f"bosses.json[{boss_id}]: invalid dmg_type '{dt}'")
        weaknesses = bspec.get("weaknesses", [])
        if not isinstance(weaknesses, list) or not weaknesses:
            raise ValueError(f"bosses.json[{boss_id}]: weaknesses must be non-empty")
        for wk in weaknesses:
            if wk not in VALID_DAMAGE_TYPES:
                raise ValueError(f"bosses.json[{boss_id}]: invalid weakness '{wk}'")

        phases = bspec.get("phases", [])
        if not isinstance(phases, list) or len(phases) < 2:
            raise ValueError(f"bosses.json[{boss_id}]: must define >= 2 phases")
        prev_min = 101
        for p_idx, phase in enumerate(phases):
            pct_min = int(phase.get("hp_pct_min", -1))
            if not (0 <= pct_min < prev_min):
                raise ValueError(
                    f"bosses.json[{boss_id}].phases[{p_idx}]: hp_pct_min must be strictly descending"
                )
            prev_min = pct_min
            if phase.get("dmg_type") not in VALID_DAMAGE_TYPES:
                raise ValueError(
                    f"bosses.json[{boss_id}].phases[{p_idx}]: invalid dmg_type '{phase.get('dmg_type')}'"
                )
            debuff = phase.get("debuff")
            if debuff is not None and debuff not in VALID_DEBUFFS:
                raise ValueError(
                    f"bosses.json[{boss_id}].phases[{p_idx}]: invalid debuff '{debuff}'"
                )
            summon_id = phase.get("summon_mob_id")
            if summon_id is not None and summon_id not in monsters:
                raise ValueError(
                    f"bosses.json[{boss_id}].phases[{p_idx}]: dangling summon_mob_id '{summon_id}'"
                )
            if not str(phase.get("on_enter_broadcast", "")).strip():
                raise ValueError(f"bosses.json[{boss_id}].phases[{p_idx}]: empty on_enter_broadcast")
            if not str(phase.get("telegraph", "")).strip():
                raise ValueError(f"bosses.json[{boss_id}].phases[{p_idx}]: empty telegraph")
        if prev_min != 0:
            raise ValueError(f"bosses.json[{boss_id}]: final phase must have hp_pct_min == 0")

        la_item = bspec.get("la_bonus_item_id")
        if la_item is not None and la_item not in named_items:
            raise ValueError(f"bosses.json[{boss_id}]: dangling la_bonus_item_id '{la_item}'")
        for mat in bspec.get("guaranteed_materials", []):
            if mat.get("item_id") not in items:
                raise ValueError(
                    f"bosses.json[{boss_id}]: dangling guaranteed material '{mat.get('item_id')}'"
                )
        _assert_valid_asset_key(bspec.get("asset_key"), f"bosses.json[{boss_id}].asset_key")

    seen_milestone_ids: set[str] = set()
    for m_floor in MILESTONE_BOSS_FLOORS:
        m_cfg = resolve_floor_config(m_floor, bundle)
        b_id = m_cfg["boss_id"]
        b_spec = bosses.get(b_id)
        if b_spec is None or not b_spec.get("is_milestone"):
            raise ValueError(f"Milestone floor {m_floor} must resolve to an is_milestone boss")
        if b_id in seen_milestone_ids:
            raise ValueError(f"Duplicate milestone boss '{b_id}' on floor {m_floor}")
        seen_milestone_ids.add(b_id)
        if int(b_spec.get("hp_bars", 0)) < 4:
            raise ValueError(f"Milestone boss '{b_id}' on floor {m_floor} must have hp_bars >= 4")
        if not b_spec.get("la_bonus_item_id"):
            raise ValueError(f"Milestone boss '{b_id}' on floor {m_floor} must define la_bonus_item_id")

    f100_boss = bosses.get("f100_incarnation_and_heathcliff")
    if not f100_boss or not f100_boss.get("dual_stage") or not f100_boss.get("anti_crystal"):
        raise ValueError("F100 boss 'f100_incarnation_and_heathcliff' must have dual_stage=True and anti_crystal=True")
    for ac_floor in (74, 75):
        ac_cfg = resolve_floor_config(ac_floor, bundle)
        if not ac_cfg["boss"].get("anti_crystal"):
            raise ValueError(f"Floor {ac_floor} milestone boss must have anti_crystal=True")

    for t_idx in range(1, 11):
        tpl_id = f"tier_{t_idx}_guardian"
        tpl = bosses.get(tpl_id)
        if not tpl or not tpl.get("is_template") or not tpl.get("name_patterns"):
            raise ValueError(f"bosses.json: missing or invalid tier guardian template '{tpl_id}'")

    for wb_id in tier_world_boss_ids:
        wb = bosses.get(wb_id)
        if not wb or not wb.get("is_world_boss") or not wb.get("world_buff_reward"):
            raise ValueError(f"bosses.json: invalid world boss '{wb_id}'")

    for mob_id, mspec in monsters.items():
        if mspec.get("dmg_type") not in VALID_DAMAGE_TYPES:
            raise ValueError(f"monsters.json[{mob_id}]: invalid dmg_type '{mspec.get('dmg_type')}'")
        wks = mspec.get("weaknesses", [])
        if not isinstance(wks, list) or not wks or any(w not in VALID_DAMAGE_TYPES for w in wks):
            raise ValueError(f"monsters.json[{mob_id}]: invalid weaknesses {wks!r}")
        deb = mspec.get("debuff")
        if deb is not None and deb not in VALID_DEBUFFS:
            raise ValueError(f"monsters.json[{mob_id}]: invalid debuff '{deb}'")
        for drop in mspec.get("drops", []):
            if drop.get("item_id") not in items:
                raise ValueError(
                    f"monsters.json[{mob_id}]: dangling drop item_id '{drop.get('item_id')}'"
                )
        if mspec.get("meat_drop_id") is not None and mspec["meat_drop_id"] not in items:
            raise ValueError(
                f"monsters.json[{mob_id}]: dangling meat_drop_id '{mspec['meat_drop_id']}'"
            )
        if mspec.get("ore_drop_id") is not None and mspec["ore_drop_id"] not in items:
            raise ValueError(
                f"monsters.json[{mob_id}]: dangling ore_drop_id '{mspec['ore_drop_id']}'"
            )
        _assert_valid_asset_key(mspec.get("asset_key"), f"monsters.json[{mob_id}].asset_key")

    # Check 5: Weapons, Unique Skills, Slots, Rarities, Sets, Named Items, Base Gear, Enhance, Sword Skills
    w_classes = weq.get("weapon_classes", {})
    if set(w_classes.keys()) != VALID_WEAPON_CLASSES:
        raise ValueError(
            f"weapons_equipment.json: weapon_classes keys mismatch: {sorted(w_classes.keys())}"
        )
    u_skills = weq.get("unique_skills", {})
    if set(u_skills.keys()) != VALID_UNIQUE_SKILLS:
        raise ValueError(
            f"weapons_equipment.json: unique_skills keys mismatch: {sorted(u_skills.keys())}"
        )
    slots_map = weq.get("slots", {})
    if tuple(weq.get("slot_order", [])) != VALID_SLOTS or set(slots_map.keys()) != set(VALID_SLOTS):
        raise ValueError("weapons_equipment.json: slots / slot_order must match exact 8 SAO slots")

    rarities_map = chests_loot.get("rarities", {})
    if tuple(chests_loot.get("rarity_order", [])) != VALID_RARITIES or set(rarities_map.keys()) != set(
        VALID_RARITIES
    ):
        raise ValueError("chests_loot.json: rarities / rarity_order must match exact 6 SAO rarities")
    if rarities_map["named"].get("allow_magic_stone") is not False:
        raise ValueError("chests_loot.json: 'named' rarity must set allow_magic_stone=False")
    if rarities_map["named"].get("tradable_default") is not False:
        raise ValueError("chests_loot.json: 'named' rarity must set tradable_default=False")
    for bypass_key in ("set", "named"):
        if rarities_map[bypass_key].get("bypass_loot_filter") is not True:
            raise ValueError(f"chests_loot.json: '{bypass_key}' rarity must set bypass_loot_filter=True")

    for wc_id, wc in w_classes.items():
        if wc.get("dmg_type") not in VALID_DAMAGE_TYPES:
            raise ValueError(f"weapons_equipment.json[{wc_id}]: invalid dmg_type '{wc.get('dmg_type')}'")
        for sid in wc.get("starter_skill_ids", []):
            if sid not in skills:
                raise ValueError(f"weapons_equipment.json[{wc_id}]: dangling starter_skill_id '{sid}'")

    for us_id, us in u_skills.items():
        for sid in us.get("skill_ids", []):
            if sid not in skills:
                raise ValueError(f"weapons_equipment.json[{us_id}]: dangling unique skill_id '{sid}'")

    skill_counts: dict[str, int] = {}
    for sid, sspec in skills.items():
        wc = sspec.get("weapon_class")
        if wc not in VALID_WEAPON_CLASSES and wc not in VALID_UNIQUE_SKILLS:
            raise ValueError(f"sword_skills.json[{sid}]: invalid weapon_class '{wc}'")
        if sspec.get("dmg_type") not in VALID_DAMAGE_TYPES:
            raise ValueError(f"sword_skills.json[{sid}]: invalid dmg_type '{sspec.get('dmg_type')}'")
        deb = sspec.get("debuff")
        if deb is not None and deb not in VALID_DEBUFFS:
            raise ValueError(f"sword_skills.json[{sid}]: invalid debuff '{deb}'")
        post_deb = sspec.get("post_delay_debuff")
        if post_deb is not None and post_deb != "rigidity":
            raise ValueError(f"sword_skills.json[{sid}]: invalid post_delay_debuff '{post_deb}'")
        if int(sspec.get("hits", 0)) < 1 or float(sspec.get("damage_mult", 0)) <= 0 or int(sspec.get("sp_cost", 0)) < 1:
            raise ValueError(f"sword_skills.json[{sid}]: hits/damage_mult/sp_cost must be positive")
        skill_counts[str(wc)] = skill_counts.get(str(wc), 0) + 1

    for wc_id in VALID_WEAPON_CLASSES | VALID_UNIQUE_SKILLS:
        if skill_counts.get(wc_id, 0) < 3:
            raise ValueError(f"sword_skills.json: '{wc_id}' must have >= 3 skills, found {skill_counts.get(wc_id, 0)}")
    if skills.get("starburst_stream", {}).get("hits") != 16:
        raise ValueError("sword_skills.json: 'starburst_stream' must have hits == 16")
    if skills.get("the_eclipse", {}).get("hits") != 27:
        raise ValueError("sword_skills.json: 'the_eclipse' must have hits == 27")
    if skills.get("mothers_rosario", {}).get("hits") != 11:
        raise ValueError("sword_skills.json: 'mothers_rosario' must have hits == 11")

    base_gear = weq.get("base_gear", {})
    for t_idx in range(1, 11):
        t_key = str(t_idx)
        bg = _require_dict(
            base_gear.get(t_key),
            f"weapons_equipment.json: missing base_gear tier '{t_key}'",
        )
        slot_names = bg.get("slot_names", {})
        for slot in VALID_SLOTS:
            if not str(slot_names.get(slot, "")).strip():
                raise ValueError(f"weapons_equipment.json: base_gear[{t_key}] missing slot '{slot}'")
        set_id = bg.get("set_id", "")
        if set_id and set_id not in sets_map:
            raise ValueError(f"weapons_equipment.json: base_gear[{t_key}] dangling set_id '{set_id}'")

    for n_id, nspec in named_items.items():
        if nspec.get("rarity") != "named" or nspec.get("tradable") is not False or nspec.get("allow_magic_stone") is not False:
            raise ValueError(f"weapons_equipment.json.named_items[{n_id}]: invalid named item flags")
        if nspec.get("slot") not in VALID_SLOTS:
            raise ValueError(f"weapons_equipment.json.named_items[{n_id}]: invalid slot '{nspec.get('slot')}'")
        dt = nspec.get("damage_type", "")
        if dt and dt not in VALID_DAMAGE_TYPES:
            raise ValueError(f"weapons_equipment.json.named_items[{n_id}]: invalid damage_type '{dt}'")

    enhance_table = weq.get("enhance_table", {})
    for lv in range(1, 16):
        e_row = _require_dict(
            enhance_table.get(str(lv)),
            f"weapons_equipment.json: enhance_table missing level '{lv}'",
        )
        if e_row.get("crystal_id") not in items:
            raise ValueError(
                f"weapons_equipment.json: enhance_table[{lv}] dangling crystal_id '{e_row.get('crystal_id')}'"
            )

    # Check 6: Items, Chests, Recipes, Quests & Yui Logs
    for req_item in (*REQUIRED_SAO_CRYSTALS, *REQUIRED_MAGIC_STONES, "protection_talisman", "crystallite_ingot"):
        if req_item not in items:
            raise ValueError(f"items_crystals.json: missing required SAO item '{req_item}'")

    chest_tiers = chests_loot.get("chest_tiers", {})
    if set(chest_tiers.keys()) != set(VALID_CHEST_TIERS):
        raise ValueError(f"chests_loot.json: chest_tiers mismatch: {sorted(chest_tiers.keys())}")
    for t_idx in range(1, 11):
        ct_key = f"tier_{t_idx}_chests"
        ct = _require_dict(
            tier_tables.get(ct_key),
            f"chests_loot.json: missing tier table '{ct_key}'",
        )
        for g_entry in ct.get("guaranteed_pool", []):
            if g_entry.get("item_id") not in items:
                raise ValueError(f"chests_loot.json[{ct_key}]: dangling item_id '{g_entry.get('item_id')}'")
        for set_id in ct.get("set_ids", []):
            if set_id not in sets_map:
                raise ValueError(f"chests_loot.json[{ct_key}]: dangling set_id '{set_id}'")

    traps = chests_loot.get("traps", {})
    mimic_mob = traps.get("mimic", {}).get("mob_id")
    if mimic_mob not in monsters:
        raise ValueError(f"chests_loot.json: dangling traps.mimic.mob_id '{mimic_mob}'")
    if "crystal_null_room" not in traps:
        raise ValueError("chests_loot.json: missing traps.crystal_null_room")

    affix_pool = chests_loot.get("affix_pool", {})
    for res_key in REQUIRED_RES_AFFIXES:
        if res_key not in affix_pool:
            raise ValueError(f"chests_loot.json: affix_pool missing required 4-axis resistance '{res_key}'")

    for cat in ("blacksmithing", "cooking", "stew", "fusion"):
        cat_recipes = recipes.get(cat)
        if not isinstance(cat_recipes, dict) or not cat_recipes:
            raise ValueError(f"recipes.json: missing or empty category '{cat}'")
        for r_id, rspec in cat_recipes.items():
            for ing_id, qty in rspec.get("ingredients", {}).items():
                if ing_id not in items:
                    raise ValueError(f"recipes.json.{cat}[{r_id}]: dangling ingredient '{ing_id}'")
                if not isinstance(qty, int) or qty <= 0:
                    raise ValueError(f"recipes.json.{cat}[{r_id}]: invalid ingredient qty for '{ing_id}'")
            out_type = rspec.get("output_type")
            if out_type == "item":
                if rspec.get("output_item_id") not in items:
                    raise ValueError(
                        f"recipes.json.{cat}[{r_id}]: dangling output_item_id '{rspec.get('output_item_id')}'"
                    )
            elif out_type == "named_item":
                if rspec.get("output_item_id") not in named_items:
                    raise ValueError(
                        f"recipes.json.{cat}[{r_id}]: dangling named output_item_id '{rspec.get('output_item_id')}'"
                    )
            elif out_type == "tiered_gear":
                if str(rspec.get("output_tier")) not in base_gear:
                    raise ValueError(
                        f"recipes.json.{cat}[{r_id}]: invalid output_tier '{rspec.get('output_tier')}'"
                    )
            else:
                raise ValueError(f"recipes.json.{cat}[{r_id}]: unknown output_type '{out_type}'")

    dark_rep_recipe = recipes["blacksmithing"].get("forge_dark_repulser")
    if (
        not dark_rep_recipe
        or "crystallite_ingot" not in dark_rep_recipe.get("ingredients", {})
        or dark_rep_recipe.get("output_item_id") != "dark_repulser"
    ):
        raise ValueError("recipes.json: 'forge_dark_repulser' must require 'crystallite_ingot' and output 'dark_repulser'")

    for log_id in REQUIRED_YUI_LOGS:
        if log_id not in yui_logs:
            raise ValueError(f"quests_events.json: missing required Yui log '{log_id}'")

    titles_map = qe.get("titles", {})
    for ch_id, ch in qe.get("story", {}).items():
        for choice in ch.get("choices", []):
            _validate_reward_items(
                choice.get("reward_items"),
                items,
                f"quests_events.json.story[{ch_id}].{choice.get('id')}",
            )
    for list_key in ("bounties", "daily_quests", "weekly_quests", "events"):
        for entry in qe.get(list_key, []):
            _validate_reward_items(
                entry.get("reward_items"),
                items,
                f"quests_events.json.{list_key}[{entry.get('id')}]",
            )
    for exp in qe.get("expeditions", []):
        for ore_id in exp.get("ore_pool", []):
            if ore_id not in items:
                raise ValueError(
                    f"quests_events.json.expeditions[{exp.get('id')}]: dangling ore_id '{ore_id}'"
                )
    for ach in qe.get("achievements", []):
        t_id = ach.get("title_id")
        if t_id not in titles_map:
            raise ValueError(
                f"quests_events.json.achievements[{ach.get('id')}]: dangling title_id '{t_id}'"
            )
        _validate_reward_items(
            ach.get("reward_items"),
            items,
            f"quests_events.json.achievements[{ach.get('id')}]",
        )

    # Check 7: Every asset_key and banner_asset_key across all 10 JSON files resolves to non-SVG raster CDN
    for name, sec in sections.items():
        _scan_all_asset_keys(sec, f"{name}.json")

    return bundle


def load_and_validate_all(force_reload: bool = False) -> SAOContentBundle:
    """Load all 10 SAO JSON files and run strict startup/test schema & referential validation."""
    bundle = load_content(force_reload=force_reload)
    return validate_content_bundle(bundle)
