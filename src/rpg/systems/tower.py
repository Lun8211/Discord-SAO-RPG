"""SAO Aincrad 100-Floor Tower, Exploration, Chests, Secret Realm/Miasma & Roguelike (ZERO discord imports)."""

from __future__ import annotations

import copy
import random
import time
import uuid
import zlib
from typing import Any

from src.rpg.content.loader import SAOContentBundle, resolve_floor_config
from src.rpg.database import RPGDatabase
from src.rpg.models import (
    SAO_RARITY_ORDER,
    SAO_SLOT_ORDER,
    CombatSession,
    DamageType,
    EquipmentItem,
    GameError,
    PlayerProfile,
    Rarity,
    RoguelikeRun,
    ZoneType,
)
from src.rpg.systems.boss_engine import get_all_boss_skill_specs
from src.rpg.systems.stats import compute_player_stats

MAX_BAG_CAPACITY = 80
MAX_MIASMA_STACKS = 20
VALID_TRAVEL_ZONES: frozenset[str] = frozenset(
    {ZoneType.TOWN, ZoneType.FIELD, ZoneType.LABYRINTH, ZoneType.SECRET_REALM}
)


def _now(now_ts: int | None) -> int:
    return int(now_ts if now_ts is not None else time.time())


def _rng(rng_seed: int | None) -> random.Random:
    return random.Random(rng_seed) if rng_seed is not None else random.Random()


def _tier_for_floor(floor: int) -> int:
    return max(1, min(10, (int(floor) - 1) // 10 + 1))


def enhance_crystal_for_tier(tier: int) -> str:
    """Return the tier-appropriate SAO enhancement crystal item ID."""
    t = max(1, int(tier))
    if t <= 2:
        return "bright_crystal_shard"
    if t <= 4:
        return "bright_crystal"
    if t <= 6:
        return "dark_crystal_shard"
    if t <= 8:
        return "dark_crystal"
    return "dark_crystal_pure"


SOCKET_CRYSTAL_IDS: tuple[str, ...] = (
    "socket_crystal_crimson",
    "socket_crystal_azure",
    "socket_crystal_gale",
    "socket_crystal_vampiric",
    "socket_crystal_breaker",
    "socket_crystal_aegis",
    "socket_crystal_fortune",
    "socket_crystal_starlight",
)


def _rarity_index(rarity: str) -> int:
    r = str(rarity or Rarity.PLAIN).lower()
    if r in SAO_RARITY_ORDER:
        return SAO_RARITY_ORDER.index(r)
    return 0


def generate_named_equipment(
    user_id: str,
    named_id: str,
    bundle: SAOContentBundle,
    *,
    now_ts: int,
) -> EquipmentItem:
    """Instantiate an authentic SAO Named (`名品`) EquipmentItem from weapons_equipment.json."""
    nspec = bundle.weapons_equipment.get("named_items", {}).get(named_id)
    if not isinstance(nspec, dict):
        raise GameError(f"找不到名品裝備資料：{named_id}", code="UNKNOWN_NAMED_ITEM")
    slot = str(nspec.get("slot", "weapon"))
    tier = int(nspec.get("tier", 1))
    stats = nspec.get("base_stats") or {}
    affixes = dict(nspec.get("affixes") or {})
    return EquipmentItem(
        id=0,
        user_id=str(user_id),
        template_id=str(named_id),
        name=str(nspec.get("name", named_id)),
        slot=slot,
        rarity=Rarity.NAMED,
        tier=tier,
        set_id=str(nspec.get("set_id") or ""),
        enhance_level=0,
        enhance_pity=0,
        base_hp=int(stats.get("hp") or nspec.get("base_hp") or 0),
        base_mp=int(stats.get("sp") or nspec.get("base_sp") or 0),
        base_atk=int(stats.get("atk") or nspec.get("base_atk") or 0),
        base_def=int(stats.get("def") or nspec.get("base_def") or 0),
        affixes={str(k): float(v) for k, v in affixes.items() if isinstance(v, (int, float))},
        is_equipped=False,
        is_locked=False,
        created_at=int(now_ts),
        weapon_style=str(nspec.get("weapon_style") or nspec.get("weapon_class") or ""),
        damage_type=str(nspec.get("dmg_type") or nspec.get("damage_type") or ""),
        named_passive=str(nspec.get("passive_desc") or nspec.get("named_passive") or ""),
        is_bound=True,
        min_level=max(1, int(nspec.get("min_level") or max(1, (tier - 1) * 10 + 1))),
        escrow_state="",
        base_sp=int(stats.get("sp") or nspec.get("base_sp") or 0),
        base_spd=int(stats.get("spd") or nspec.get("base_spd") or 0),
    )


def generate_equipment_item(
    user_id: str,
    floor: int,
    bundle: SAOContentBundle,
    *,
    rarity: str | None = None,
    slot: str | None = None,
    weapon_style: str = "sword",
    set_id: str = "",
    now_ts: int = 0,
    rng: random.Random | None = None,
) -> EquipmentItem:
    """Deterministically generate a scaled SAO 8-slot EquipmentItem for any floor 1..100."""
    rgen = rng or random.Random()
    tier = _tier_for_floor(floor)
    base_gear_map = bundle.weapons_equipment.get("base_gear", {})
    tier_cfg = base_gear_map.get(str(tier)) or base_gear_map.get("1") or {}
    scale = float(tier_cfg.get("scale", 1.0 + (tier - 1) * 0.8))

    rarities_cfg = bundle.chests_loot.get("rarities", {})
    chosen_rarity = str(rarity or "").lower()
    if chosen_rarity not in SAO_RARITY_ORDER:
        weights = [
            float(rarities_cfg.get(r, {}).get("base_weight", 1))
            for r in ("plain", "fine", "rare", "set", "legendary")
        ]
        chosen_rarity = rgen.choices(("plain", "fine", "rare", "set", "legendary"), weights=weights, k=1)[0]

    rcfg = rarities_cfg.get(chosen_rarity, {"stat_mult": 1.0, "affix_range": [1, 2]})
    rmult = float(rcfg.get("stat_mult", 1.0))

    chosen_slot = str(slot or rgen.choice(SAO_SLOT_ORDER)).lower()
    if chosen_slot not in SAO_SLOT_ORDER:
        chosen_slot = "weapon"

    norm_style = str(weapon_style or "sword").strip().lower()
    style_name_key = (
        "sword" if norm_style == "dual_blades" else ("holy" if norm_style == "holy_sword" else norm_style)
    )
    slot_names = tier_cfg.get("slot_names") or {}
    wstyle_names = tier_cfg.get("weapon_style_names") or {}
    is_offhand_weapon = False
    if chosen_slot == "weapon":
        base_name = str(wstyle_names.get(style_name_key) or slot_names.get("weapon") or f"T{tier} weapon")
    elif chosen_slot == "offhand":
        off_raw = tier_cfg.get("offhand_weapon_names")
        prefer_offhand_blade = norm_style in ("dagger", "dual_blades") or (
            norm_style not in ("mace", "holy", "holy_sword") and rgen.random() < 0.35
        )
        if prefer_offhand_blade and off_raw:
            is_offhand_weapon = True
            if isinstance(off_raw, list):
                base_name = str(rgen.choice(off_raw))
            else:
                base_name = str(off_raw)
        else:
            base_name = str(slot_names.get("offhand") or f"T{tier} offhand")
    else:
        base_name = str(slot_names.get(chosen_slot) or f"T{tier} {chosen_slot}")

    prefix = str(rarities_cfg.get(chosen_rarity, {}).get("name") or "")
    chosen_set = set_id or (str(tier_cfg.get("set_id") or "") if chosen_rarity == Rarity.SET else "")
    full_name = f"【{prefix}】{base_name}" if prefix else base_name

    # Slot-appropriate stat distributions
    atk, defense, hp, sp, spd = 0, 0, 0, 0, 0
    if chosen_slot == "weapon":
        atk = round((28 + floor * 7.5) * rmult * (0.9 + scale * 0.12))
        sp = round((12 + floor * 1.0) * rmult)
        spd = round((4 + tier * 2) * rmult)
    elif chosen_slot == "offhand":
        if is_offhand_weapon:
            atk = round((18 + floor * 4.2) * rmult)
            defense = round((10 + floor * 2.5) * rmult)
            hp = round((50 + floor * 12) * rmult)
            spd = round((6 + tier * 2) * rmult)
        else:
            atk = round((12 + floor * 3.0) * rmult)
            defense = round((16 + floor * 4.2) * rmult)
            hp = round((65 + floor * 16) * rmult)
    elif chosen_slot in ("helmet", "armor"):
        defense = round((18 + floor * 5.0) * rmult * (1.25 if chosen_slot == "armor" else 0.85))
        hp = round((95 + floor * 26) * rmult * (1.3 if chosen_slot == "armor" else 0.85))
    elif chosen_slot in ("gloves", "boots"):
        atk = round((10 + floor * 2.4) * rmult)
        defense = round((12 + floor * 3.2) * rmult)
        hp = round((55 + floor * 14) * rmult)
        spd = round((6 + tier * 3) * rmult)
    else:  # ring / necklace
        atk = round((12 + floor * 2.8) * rmult)
        hp = round((70 + floor * 18) * rmult)
        sp = round((16 + floor * 1.4) * rmult)

    # Roll random affixes from chests_loot.json affix_pool
    affix_pool = bundle.chests_loot.get("affix_pool", {})
    aff_min, aff_max = rcfg.get("affix_range", [1, 2])
    aff_count = rgen.randint(int(aff_min), int(aff_max))
    affixes: dict[str, float] = {}
    pool_keys = list(affix_pool.keys())
    if pool_keys and aff_count > 0:
        picked = rgen.sample(pool_keys, k=min(aff_count, len(pool_keys)))
        for ak in picked:
            lo, hi = affix_pool[ak].get("base_range", [0.02, 0.05])
            val = rgen.uniform(float(lo), float(hi)) * (1.0 + (tier - 1) * 0.08)
            affixes[str(ak)] = round(val, 4)

    w_classes = bundle.weapons_equipment.get("weapon_classes", {})
    wstyle = norm_style if chosen_slot == "weapon" else ""
    dtype = (
        str(w_classes.get(style_name_key, {}).get("dmg_type", DamageType.SLASH))
        if chosen_slot == "weapon"
        else ""
    )
    tpl_slot = "offhand_blade" if is_offhand_weapon else chosen_slot

    return EquipmentItem(
        id=0,
        user_id=str(user_id),
        template_id=f"t{tier}_{tpl_slot}_{chosen_rarity}",
        name=full_name,
        slot=chosen_slot,
        rarity=chosen_rarity,
        tier=tier,
        set_id=chosen_set,
        enhance_level=0,
        enhance_pity=0,
        base_hp=hp,
        base_mp=sp,
        base_atk=atk,
        base_def=defense,
        affixes=affixes,
        is_equipped=False,
        is_locked=False,
        created_at=int(now_ts),
        weapon_style=wstyle,
        damage_type=dtype,
        named_passive="",
        is_bound=(chosen_rarity == Rarity.NAMED),
        min_level=max(1, (tier - 1) * 10 + 1),
        escrow_state="",
        base_sp=sp,
        base_spd=spd,
    )


def passes_loot_filter(player: PlayerProfile, item: EquipmentItem) -> bool:
    """Evaluate player's Loot Filter. Set (`珍品`) and Named (`名品`) NEVER get skipped!"""
    if item.rarity in (Rarity.SET, Rarity.NAMED) or item.is_named or item.is_set_piece:
        return True
    flt = player.loot_filter or {}
    min_rarity = str(flt.get("min_rarity") or Rarity.PLAIN).lower()
    if _rarity_index(item.rarity) < _rarity_index(min_rarity):
        return False
    min_level = int(flt.get("min_level", 1))
    if item.min_level < min_level:
        return False
    blocked_slots = {str(s).lower() for s in flt.get("blocked_slots", [])}
    return item.slot.lower() not in blocked_slots


def count_unequipped_bag_items(db: RPGDatabase, user_id: str) -> int:
    eqs = db.get_equipment(user_id, equipped_only=False, include_escrowed=False)
    return sum(1 for e in eqs if not e.is_equipped)


def grant_or_queue_equipment(
    db: RPGDatabase,
    player: PlayerProfile,
    item: EquipmentItem,
    *,
    source: str,
    now_ts: int,
    apply_filter: bool = True,
) -> dict[str, Any]:
    """Grant equipment into bag, filter to Col if filtered out, or overflow to Pending Loot Mailbox."""
    if apply_filter and not passes_loot_filter(player, item):
        salvage_col = max(15, item.tier * 25)
        player.col += salvage_col
        db.save_player(player)
        return {
            "status": "filtered",
            "salvage_col": salvage_col,
            "item_uid": None,
            "item_name": item.name,
            "rarity": item.rarity,
            "slot": item.slot,
            "tier": item.tier,
        }

    bag_used = count_unequipped_bag_items(db, player.user_id)
    if bag_used >= MAX_BAG_CAPACITY:
        payload = {
            "template_id": item.template_id,
            "name": item.name,
            "slot": item.slot,
            "rarity": item.rarity,
            "tier": item.tier,
            "set_id": item.set_id,
            "enhance_level": item.enhance_level,
            "temper_level": item.temper_level,
            "socket_crystal_id": item.socket_crystal_id,
            "base_hp": item.base_hp,
            "base_mp": item.base_mp,
            "base_atk": item.base_atk,
            "base_def": item.base_def,
            "affixes": item.affixes,
            "weapon_style": item.weapon_style,
            "damage_type": item.damage_type,
            "named_passive": item.named_passive,
            "is_bound": item.is_bound,
            "min_level": item.min_level,
            "base_sp": item.base_sp,
            "base_spd": item.base_spd,
        }
        loot_id = db.enqueue_pending_loot(
            player.user_id, source=source, item_type="equipment", payload=payload, now_ts=now_ts
        )
        return {
            "status": "pending_mailbox",
            "pending_loot_id": loot_id,
            "item_uid": None,
            "item_name": item.name,
            "rarity": item.rarity,
            "slot": item.slot,
            "tier": item.tier,
        }

    created = db.add_equipment(item)
    return {
        "status": "granted",
        "item_uid": created.id,
        "item": created,
        "item_name": created.name,
        "rarity": created.rarity,
        "slot": created.slot,
        "tier": created.tier,
    }


def claim_pending_loot(
    db: RPGDatabase,
    user_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Claim pending mailbox items into bag (prioritizing Named/Legendary/Set gear when bag space is limited)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    pending = db.get_pending_loot(user_id, unclaimed_only=True)
    if not pending:
        return {
            "ok": True,
            "claimed": 0,
            "claimed_count": 0,
            "claimed_items": [],
            "remaining_count": 0,
            "message": "📬 待領取戰利品信箱目前沒有物品。",
        }

    # Claim highest-rarity equipment first so LA Named/Legendary drops are never stuck behind low-tier trash
    def _claim_priority(entry: dict[str, Any]) -> tuple[int, int, int]:
        if entry["item_type"] == "equipment":
            r = str((entry.get("payload") or {}).get("rarity", Rarity.PLAIN)).lower()
            return (0, -_rarity_index(r), int(entry["id"]))
        return (1, 0, int(entry["id"]))

    ordered_pending = sorted(pending, key=_claim_priority)

    claimed_items: list[dict[str, Any]] = []
    remaining = 0
    bag_used = count_unequipped_bag_items(db, user_id)

    for entry in ordered_pending:
        if entry["item_type"] == "equipment":
            if bag_used >= MAX_BAG_CAPACITY:
                remaining += 1
                continue
            claimed_row = db.claim_pending_loot_entry(user_id, int(entry["id"]), ts)
            if claimed_row is None:
                continue
            p = claimed_row["payload"]
            eq = EquipmentItem(
                id=0,
                user_id=user_id,
                template_id=str(p.get("template_id", "mailbox_gear")),
                name=str(p.get("name", "待領裝備")),
                slot=str(p.get("slot", "weapon")),
                rarity=str(p.get("rarity", Rarity.RARE)),
                tier=int(p.get("tier", 1)),
                set_id=str(p.get("set_id", "")),
                enhance_level=int(p.get("enhance_level", 0)),
                enhance_pity=0,
                base_hp=int(p.get("base_hp", 0)),
                base_mp=int(p.get("base_mp", 0)),
                base_atk=int(p.get("base_atk", 0)),
                base_def=int(p.get("base_def", 0)),
                affixes=dict(p.get("affixes") or {}),
                is_equipped=False,
                is_locked=False,
                created_at=ts,
                weapon_style=str(p.get("weapon_style", "")),
                damage_type=str(p.get("damage_type", "")),
                named_passive=str(p.get("named_passive", "")),
                is_bound=bool(p.get("is_bound", False)),
                min_level=int(p.get("min_level", 1)),
                escrow_state="",
                base_sp=int(p.get("base_sp", 0)),
                base_spd=int(p.get("base_spd", 0)),
                temper_level=int(p.get("temper_level", 0)),
                socket_crystal_id=str(p.get("socket_crystal_id", "")),
            )
            created = db.add_equipment(eq)
            bag_used += 1
            claimed_items.append({"item_uid": created.id, "name": created.name, "rarity": created.rarity})
        else:
            claimed_row = db.claim_pending_loot_entry(user_id, int(entry["id"]), ts)
            if claimed_row is None:
                continue
            p = claimed_row["payload"]
            iid = str(p.get("item_id", ""))
            qty = max(1, int(p.get("qty", 1)))
            if iid:
                db.add_item(user_id, iid, qty)
                claimed_items.append({"item_id": iid, "qty": qty})

    if not claimed_items and remaining > 0:
        msg = f"⚠️ 背包空間仍已滿（{bag_used}/{MAX_BAG_CAPACITY}），已為你完整保留信箱內的 {remaining} 件戰利品，請先清理或上繳裝備再領取！"
    else:
        msg = f"📬 已從待領取信箱領取 {len(claimed_items)} 件戰利品！（尚餘 {remaining} 件）"
    return {
        "ok": True,
        "claimed": len(claimed_items),
        "claimed_count": len(claimed_items),
        "claimed_items": claimed_items,
        "remaining_count": remaining,
        "bag_full": remaining > 0 and not claimed_items,
        "message": msg,
    }


def get_floor_info(
    db: RPGDatabase,
    content: SAOContentBundle,
    floor: int,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Return full resolved info for Aincrad floor 1..100 including exploration & server clear state."""
    if isinstance(floor, bool) or not isinstance(floor, int) or not (1 <= floor <= 100):
        raise GameError(f"無效的艾恩葛朗特樓層：{floor}（必須為 1～100）", code="INVALID_FLOOR")

    cfg = resolve_floor_config(floor, content)
    server_clear = db.get_server_floor_clear(floor)
    exploration = (
        db.get_floor_exploration(user_id, floor)
        if user_id
        else {"progress_pct": 0, "field_boss_cleared": False, "boss_gate_unlocked": False, "pending_chest": None}
    )
    is_crystal_null = bool(cfg["boss"].get("anti_crystal", False)) or bool(
        cfg.get("rule_flags", {}).get("crystal_null_trap")
    )
    player = db.get_player(user_id) if user_id else None
    is_unlocked = (floor <= player.max_unlocked_floor) if player is not None else (floor == 1)
    return {
        "ok": True,
        "floor": floor,
        "unlocked": is_unlocked,
        "is_unlocked": is_unlocked,
        "tier": cfg["tier"],
        "biome_name": cfg["biome_name"],
        "town_name": cfg["town_name"],
        "landmark": cfg["landmark"],
        "field_name": cfg["field_name"],
        "labyrinth_name": cfg["labyrinth_name"],
        "secret_realm_name": cfg["secret_realm_name"],
        "recommended_level": max(1, floor),
        "res_penetration": cfg["res_penetration"],
        "is_milestone_boss": cfg["is_milestone_boss"],
        "is_crystal_null": is_crystal_null,
        "boss_id": cfg["boss_id"],
        "boss_name": cfg["boss"]["name"],
        "boss_hp": int(cfg["boss"].get("base_hp", cfg["base_hp"])),
        "hp_scale": int(cfg["base_hp"]),
        "stat_multiplier": round(float(cfg.get("tier_mult", 1.0)), 4),
        "boss_hp_bars": int(cfg["boss"].get("hp_bars", 4)),
        "field_boss_id": cfg["field_boss_id"],
        "mob_pool_ids": cfg["mob_pool_ids"],
        "elite_mob_ids": cfg["elite_mob_ids"],
        "ore_ids": cfg["ore_ids"],
        "chest_table_id": cfg["chest_table_id"],
        "world_boss_id": cfg["world_boss_id"],
        "banner_asset_key": cfg["banner_asset_key"],
        "flavor_desc": cfg["flavor_desc"],
        "special_rules": cfg["special_rules"],
        "exploration_pct": int(exploration.get("progress_pct") or 0),
        "field_boss_cleared": bool(exploration.get("field_boss_cleared")),
        "boss_gate_unlocked": bool(exploration.get("boss_gate_unlocked")),
        "pending_chest": exploration.get("pending_chest"),
        "server_first_kill": server_clear,
        "message": f"🏰 第 {floor} 層【{cfg['town_name']}】— {cfg['biome_name']}（頭目：{cfg['boss']['name']}）",
    }


def travel_zone(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    zone: str,
    *,
    now_ts: int | None = None,
    in_active_combat: bool = False,
) -> dict[str, Any]:
    """Transition player between Town (`圈內`), Field (`野外區`), Labyrinth (`迷宮區`), Secret Realm (`秘境`)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.is_dead:
        raise GameError("此硬派角色已在生命之碑刻下殞落紀錄，無法再行動。", code="HARDCORE_DEAD")
    if in_active_combat or player.in_boss_battle:
        raise GameError("戰鬥或頭目戰進行中無法自由切換區域！請先結束戰鬥或使用撤退／轉移水晶。", code="IN_COMBAT_TRAVEL_BLOCKED")

    z = str(zone or "").strip().lower()
    if z in (ZoneType.BOSS_ROOM, ZoneType.ROGUELIKE):
        raise GameError("無法直接透過區域移動進入頭目房或地下迷宮，請使用專用入口指令。", code="DIRECT_ZONE_JUMP_BLOCKED")
    if z not in VALID_TRAVEL_ZONES:
        raise GameError(f"未知的艾恩葛朗特區域：{zone}", code="INVALID_ZONE")

    prev_zone = player.zone
    player.zone = z
    cleared_miasma = 0
    if z == ZoneType.TOWN:
        cleared_miasma = player.miasma_stacks
        player.miasma_stacks = 0
        player.miasma_exp_stacks = 0
        player.downed_until = 0
        eqs = db.get_equipment(user_id, equipped_only=True)
        stats = compute_player_stats(player, eqs, content, floor=player.current_floor)
        player.hp = stats.max_hp
        player.sp = stats.max_sp
        player.max_sp = stats.max_sp
    elif prev_zone == ZoneType.SECRET_REALM and z != ZoneType.SECRET_REALM:
        # Leaving Secret Realm clears EXP multiplier while preserving Miasma until Town!
        player.miasma_exp_stacks = 0

    player.updated_at = ts
    db.save_player(player)
    fcfg = resolve_floor_config(player.current_floor, content)
    zone_labels: dict[str, str] = {
        str(ZoneType.TOWN): f"圈內安全區【{fcfg['town_name']}】",
        str(ZoneType.FIELD): f"野外探索區【{fcfg['field_name']}】",
        str(ZoneType.LABYRINTH): f"迷宮區【{fcfg['labyrinth_name']}】",
        str(ZoneType.SECRET_REALM): f"秘境【{fcfg['secret_realm_name']}】",
    }
    extra = f"（已淨化 {cleared_miasma} 層瘴氣並回復體力！）" if cleared_miasma > 0 else ""
    return {
        "ok": True,
        "zone": player.zone,
        "previous_zone": prev_zone,
        "floor": player.current_floor,
        "miasma_stacks": player.miasma_stacks,
        "miasma_exp_stacks": player.miasma_exp_stacks,
        "message": f"🚶 已移動至第 {player.current_floor} 層 {zone_labels[z]}{extra}",
    }


def teleport_floor(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    target_floor: int,
    *,
    now_ts: int | None = None,
    in_active_combat: bool = False,
) -> dict[str, Any]:
    """Use the Aincrad Teleport Gate (`轉移門`) to warp to any unlocked floor's Safe Zone town."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.is_dead:
        raise GameError("硬派角色已陣亡，無法啟動轉移門。", code="HARDCORE_DEAD")
    if in_active_combat or player.in_boss_battle:
        raise GameError("戰鬥或頭目戰中無法啟動城鎮轉移門！", code="TELEPORT_BLOCKED_IN_COMBAT")
    if isinstance(target_floor, bool) or not isinstance(target_floor, int) or not (1 <= target_floor <= 100):
        raise GameError(f"無效的目標樓層：{target_floor}（必須為 1～100）", code="INVALID_FLOOR")

    max_unlocked = player.max_unlocked_floor
    if target_floor > max_unlocked:
        raise GameError(
            f"第 {target_floor} 層轉移門尚未解鎖！你目前最高可傳送至第 {max_unlocked} 層（需先擊破前一層頭目）。",
            code="FLOOR_LOCKED",
        )

    player.current_floor = int(target_floor)
    player.zone = ZoneType.TOWN
    player.miasma_stacks = 0
    player.miasma_exp_stacks = 0
    eqs = db.get_equipment(user_id, equipped_only=True)
    stats = compute_player_stats(player, eqs, content, floor=target_floor)
    player.hp = stats.max_hp
    player.sp = stats.max_sp
    player.max_sp = stats.max_sp
    player.updated_at = ts
    db.save_player(player)

    fcfg = resolve_floor_config(target_floor, content)
    return {
        "ok": True,
        "floor": target_floor,
        "current_floor": target_floor,
        "max_unlocked_floor": max_unlocked,
        "zone": player.zone,
        "town_name": fcfg["town_name"],
        "message": f"🌀 轉移門啟動！已抵達第 {target_floor} 層安全區【{fcfg['town_name']}】。",
    }


def _spawn_road_combat(
    player: PlayerProfile,
    content: SAOContentBundle,
    fcfg: dict[str, Any],
    mob_id: str,
    *,
    is_elite: bool = False,
    is_field_boss: bool = False,
    anti_crystal_zone: bool = False,
    stats: Any,
) -> CombatSession:
    mspec = content.monsters[mob_id]
    rules = content.biomes["scaling_rules"]
    hp_m = float(mspec.get("hp_mult", 1.0))
    atk_m = float(mspec.get("atk_mult", 1.0))
    def_m = float(mspec.get("def_mult", 1.0))
    if is_field_boss:
        fb = rules["field_boss_mult"]
        hp_m *= float(fb["hp"])
        atk_m *= float(fb["atk"])
        def_m *= float(fb["def"])
    elif is_elite:
        el = rules["elite_mult"]
        hp_m *= float(el["hp"])
        atk_m *= float(el["atk"])
        def_m *= float(el["def"])

    enemy_hp = max(35, round(int(fcfg["base_hp"]) * hp_m))
    enemy_atk = max(8, round(int(fcfg["base_atk"]) * atk_m))
    enemy_def = max(2, round(int(fcfg["base_def"]) * def_m))
    cur_hp = player.hp if player.hp > 0 else stats.max_hp
    cur_sp = player.sp if player.sp > 0 else stats.max_sp
    w_classes = content.weapons_equipment.get("weapon_classes", {})
    p_dmg_type = str(w_classes.get(player.weapon_style, {}).get("dmg_type", DamageType.SLASH))
    kind = "field_boss" if is_field_boss else ("elite" if is_elite else "field")
    emoji = "👹" if is_field_boss else ("💀" if is_elite else "🐺")

    return CombatSession(
        user_id=player.user_id,
        mode=kind,
        target_id=mob_id,
        difficulty="normal",
        title=f"第 {fcfg['floor']} 層・{fcfg['field_name']}",
        enemy_name=str(mspec["name"]),
        enemy_emoji=emoji,
        enemy_max_hp=enemy_hp,
        enemy_hp=enemy_hp,
        enemy_atk=enemy_atk,
        enemy_def=enemy_def,
        enemy_level=max(1, int(fcfg["floor"])),
        player_max_hp=stats.max_hp,
        player_hp=min(cur_hp, stats.max_hp),
        player_max_mp=stats.max_sp,
        player_mp=min(cur_sp, stats.max_sp),
        floor=int(fcfg["floor"]),
        zone=player.zone,
        weapon_style=player.weapon_style,
        damage_type=p_dmg_type,
        enemy_damage_type=str(mspec.get("dmg_type", DamageType.SLASH)),
        enemy_weaknesses=[str(w) for w in mspec.get("weaknesses", [DamageType.SLASH])],
        player_sp=min(cur_sp, stats.max_sp),
        player_max_sp=stats.max_sp,
        anti_crystal_zone=anti_crystal_zone,
        logs=[
            f"{emoji} 在第 {fcfg['floor']} 層遭遇了【{mspec['name']}】（HP {enemy_hp}／攻擊類型：{mspec.get('dmg_type', 'slash')}）！"
        ],
    )


def explore_floor(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
    *,
    steps: int = 1,
    now_ts: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Explore current floor (Field -> Labyrinth -> Boss Gate), triggering mobs, elites, chests, or events."""
    ts = _now(now_ts)
    if isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0:
        raise GameError("探索步數必須為正整數（至少 1 步）。", code="INVALID_STEPS")
    if steps > 20:
        raise GameError("單次探索步數上限為 20 步，請分批推進以確保安全！", code="STEPS_TOO_LARGE")

    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.is_dead:
        raise GameError("此硬派角色已陣亡，無法探索樓層。", code="HARDCORE_DEAD")
    if user_id in active_combats and not active_combats[user_id].finished:
        raise GameError("你目前仍在戰鬥中，請先完成當前戰鬥再繼續探索！", code="ALREADY_IN_COMBAT")
    if player.in_boss_battle:
        raise GameError("頭目戰進行中無法探索野外！", code="IN_BOSS_BATTLE")

    if player.zone == ZoneType.TOWN:
        player.zone = ZoneType.FIELD

    floor = player.current_floor
    fcfg = resolve_floor_config(floor, content)
    exp_state = db.get_floor_exploration(user_id, floor)
    progress = int(exp_state["progress_pct"])
    fb_cleared = bool(exp_state["field_boss_cleared"])
    gate_unlocked = bool(exp_state["boss_gate_unlocked"])

    rgen = _rng(rng_seed)
    eqs = db.get_equipment(user_id, equipped_only=True)
    stats = compute_player_stats(player, eqs, content, floor=floor)

    logs: list[str] = []
    event_type = "explore"
    chest_info: dict[str, Any] | None = None
    combat_session: CombatSession | None = None
    col_gain = 0
    exp_gain = 0
    items_gained: dict[str, int] = {}
    equipment_drops: list[dict[str, Any]] = []

    for _ in range(steps):
        gain = rgen.randint(14, 24)
        progress = min(100, progress + gain)
        if progress >= 50 and player.zone == ZoneType.FIELD:
            player.zone = ZoneType.LABYRINTH
            logs.append(f"🧭 探索度達 {progress}%，已深入【{fcfg['labyrinth_name']}】！")

        roll = rgen.random()
        # Trigger Field Boss when nearing 100% if not yet cleared
        if progress >= 85 and not fb_cleared and roll < 0.45:
            combat_session = _spawn_road_combat(
                player, content, fcfg, fcfg["field_boss_id"], is_field_boss=True, stats=stats
            )
            active_combats[user_id] = combat_session
            event_type = "field_boss"
            logs.append(f"👹 發現樓層野外頭目【{combat_session.enemy_name}】！擊敗後將敞開頭目房大門！")
            break
        if roll < 0.30:
            # Treasure chest (parse chests_loot.json `weights` list cleanly!)
            ctable = content.chests_loot["tier_tables"].get(fcfg["chest_table_id"], {})
            raw_weights = ctable.get("weights")
            if isinstance(raw_weights, list) and raw_weights:
                c_tiers = [str(entry["chest_tier"]) for entry in raw_weights]
                c_w = [max(0.01, float(entry.get("weight", 1))) for entry in raw_weights]
            else:
                tier_weights = ctable.get("tier_weights", {"wooden": 50, "iron": 30, "silver": 15, "gold": 5})
                c_tiers = list(tier_weights.keys())
                c_w = [max(0.01, float(tier_weights[k])) for k in c_tiers]
            chosen_tier = rgen.choices(c_tiers, weights=c_w, k=1)[0]
            trap_type = "none"
            if floor == 27:
                if chosen_tier == "mimic_trap" or rgen.random() < 0.65:
                    trap_type = "crystal_null_room"
            elif chosen_tier == "mimic_trap" or rgen.random() < 0.18:
                trap_type = "mimic"
            chest_info = {
                "chest_id": f"chest_{floor}_{rgen.randint(1000, 9999)}",
                "chest_tier": chosen_tier,
                "floor": floor,
                "trap_type": trap_type,
                "inspected": False,
                "detected_trap": False,
            }
            event_type = "chest"
            cname = content.chests_loot["chest_tiers"].get(chosen_tier, {}).get("name", chosen_tier)
            logs.append(f"🎁 發現一只【{cname}】！可使用「索敵鑑定（inspect）」、「開啟（open）」或「離開（leave）」。")
            break
        if roll < 0.78:
            is_elite = progress >= 50 and rgen.random() < 0.30
            pool = fcfg["elite_mob_ids"] if (is_elite and fcfg["elite_mob_ids"]) else fcfg["mob_pool_ids"]
            mob_id = rgen.choice(pool)
            combat_session = _spawn_road_combat(
                player, content, fcfg, mob_id, is_elite=is_elite, stats=stats
            )
            active_combats[user_id] = combat_session
            event_type = "elite_combat" if is_elite else "monster_combat"
            logs.append(combat_session.logs[0])
            break
        # Road event / safe discovery (grants JSON reward_items + shrine heal + equipment chance!)
        ev_list = content.quests_events.get("events", [])
        evt = rgen.choice(ev_list) if ev_list else {"name": "前進偵查", "reward_col": 60}
        bonus_col = max(20, round(int(fcfg["col_base"]) * 1.4))
        bonus_exp = max(10, round(int(fcfg["exp_base"]) * 0.8))
        col_gain += bonus_col
        exp_gain += bonus_exp
        ev_item_labels: list[str] = []
        raw_reward_items = evt.get("reward_items")
        if isinstance(raw_reward_items, dict):
            for riid, rqty in raw_reward_items.items():
                if str(riid) in content.items_crystals and int(rqty) > 0:
                    db.add_item(user_id, str(riid), int(rqty))
                    items_gained[str(riid)] = items_gained.get(str(riid), 0) + int(rqty)
                    iname = content.items_crystals[str(riid)].get("name", riid)
                    ev_item_labels.append(f"{iname}x{rqty}")
        if str(evt.get("type", "")) == "shrine":
            player.hp = stats.max_hp
            player.sp = stats.max_sp
        ev_gear_chance = min(0.65, 0.25 + stats.drop_bonus)
        ev_gear_note = ""
        if rgen.random() < ev_gear_chance:
            ev_rarity = Rarity.RARE if rgen.random() < 0.38 else Rarity.FINE
            ev_gear = generate_equipment_item(
                user_id, floor, content, rarity=ev_rarity, weapon_style=player.weapon_style, now_ts=ts, rng=rgen
            )
            gres = grant_or_queue_equipment(
                db, player, ev_gear, source=f"第{floor}層路途事件({evt.get('id', 'event')})", now_ts=ts, apply_filter=True
            )
            equipment_drops.append(gres)
            ev_gear_note = f"、裝備【{ev_gear.name}】"
        item_note = f"、道具 {', '.join(ev_item_labels)}" if ev_item_labels else ""
        event_type = "event"
        logs.append(
            f"✨ 觸發事件【{evt.get('name', '前沿巡查')}】：獲得 {bonus_col} 柯爾、{bonus_exp} 經驗{item_note}{ev_gear_note}！"
        )

    if progress >= 100:
        gate_unlocked = True
        fb_cleared = True
        logs.append(f"🚪 第 {floor} 層探索度達 100%！頭目房大門【{fcfg['boss']['name']}】已解鎖！")

    if col_gain > 0 or exp_gain > 0:
        player.col += col_gain
        player.exp += exp_gain
    player.updated_at = ts
    db.save_player(player)
    db.save_floor_exploration(
        user_id,
        floor,
        progress,
        field_boss_cleared=fb_cleared,
        boss_gate_unlocked=gate_unlocked,
        pending_chest=chest_info,
        now_ts=ts,
    )
    # Track daily exploration quest progress
    today_key = time.strftime("%Y-%m-%d", time.gmtime(ts))
    db.increment_quest(user_id, "daily", today_key, "dq_explore_5", 5, delta=1)

    return {
        "ok": True,
        "floor": floor,
        "zone": player.zone,
        "event_type": event_type,
        "exploration_pct": progress,
        "field_boss_cleared": fb_cleared,
        "boss_gate_unlocked": gate_unlocked,
        "in_combat": combat_session is not None,
        "combat": combat_session,
        "chest": chest_info,
        "col_gain": col_gain,
        "exp_gain": exp_gain,
        "items": items_gained,
        "equipment_drops": equipment_drops,
        "logs": logs,
        "message": logs[-1] if logs else f"🧭 第 {floor} 層探索度推進至 {progress}%。",
    }


def open_chest(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
    *,
    action: str = "open",
    now_ts: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Handle pending treasure chest: `inspect` (索敵), `open` (loot/Mimic/Crystal-Null Trap), or `leave`."""
    ts = _now(now_ts)
    act = str(action or "open").strip().lower()
    if act not in ("inspect", "open", "leave"):
        raise GameError(f"無效的寶箱操作：{action}（僅支援 inspect / open / leave）", code="INVALID_CHEST_ACTION")

    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    floor = player.current_floor
    exp_state = db.get_floor_exploration(user_id, floor)
    chest = exp_state.get("pending_chest")
    if not isinstance(chest, dict):
        raise GameError("目前面前沒有待開啟的寶箱，請先探索樓層！", code="NO_PENDING_CHEST")

    rgen = _rng(rng_seed)
    mastery = db.get_mastery(user_id)
    searching_lv = int(mastery.get("searching", {}).get("level", 1))

    if act == "leave":
        db.save_floor_exploration(
            user_id,
            floor,
            int(exp_state["progress_pct"]),
            bool(exp_state["field_boss_cleared"]),
            bool(exp_state["boss_gate_unlocked"]),
            pending_chest=None,
            now_ts=ts,
        )
        return {
            "ok": True,
            "action": "leave",
            "floor": floor,
            "exploration_pct": int(exp_state["progress_pct"]),
            "boss_gate_unlocked": bool(exp_state["boss_gate_unlocked"]),
            "in_combat": False,
            "message": "🚪 你謹慎地離開了寶箱所在房間。",
        }

    if act == "inspect":
        detect_chance = min(0.98, 0.45 + searching_lv * 0.04)
        trap_type = str(chest.get("trap_type", "none"))
        detected = trap_type != "none" and (searching_lv >= 15 or rgen.random() < detect_chance)
        chest = dict(chest)
        chest["inspected"] = True
        chest["detected_trap"] = detected
        # Gain searching mastery EXP
        new_exp = int(mastery.get("searching", {}).get("exp", 0)) + 15
        new_lv = searching_lv + (1 if new_exp >= searching_lv * 40 else 0)
        if new_lv > searching_lv:
            new_exp = 0
        db.upsert_mastery(user_id, "searching", new_lv, new_exp)
        db.save_floor_exploration(
            user_id,
            floor,
            int(exp_state["progress_pct"]),
            bool(exp_state["field_boss_cleared"]),
            bool(exp_state["boss_gate_unlocked"]),
            pending_chest=chest,
            now_ts=ts,
        )
        if detected:
            trap_zh = "水晶無效化陷阱房" if trap_type == "crystal_null_room" else "擬態寶箱怪（Mimic）"
            msg = f"👁️ 【索敵 Lv.{new_lv}】偵測到危險！這只寶箱暗藏【{trap_zh}】！"
        else:
            msg = f"👁️ 【索敵 Lv.{new_lv}】探查完畢，周圍未發現明顯異常波動（陷阱偵測率 {round(detect_chance * 100)}%）。"
        return {
            "ok": True,
            "action": "inspect",
            "floor": floor,
            "trap_detected": detected,
            "trap_type": trap_type if detected else "unknown",
            "searching_level": new_lv,
            "detect_chance": round(detect_chance, 3),
            "chest": chest,
            "in_combat": False,
            "message": msg,
        }

    # act == "open"
    fcfg = resolve_floor_config(floor, content)
    trap_type = str(chest.get("trap_type", "none"))
    # Clear pending chest once opened
    db.save_floor_exploration(
        user_id,
        floor,
        int(exp_state["progress_pct"]),
        bool(exp_state["field_boss_cleared"]),
        bool(exp_state["boss_gate_unlocked"]),
        pending_chest=None,
        now_ts=ts,
    )

    eqs = db.get_equipment(user_id, equipped_only=True)
    stats = compute_player_stats(player, eqs, content, floor=floor)

    c_tier = str(chest.get("chest_tier", "wooden"))
    if trap_type == "crystal_null_room":
        mob_id = fcfg["elite_mob_ids"][0] if fcfg["elite_mob_ids"] else fcfg["mob_pool_ids"][0]
        session = _spawn_road_combat(
            player,
            content,
            fcfg,
            mob_id,
            is_elite=True,
            anti_crystal_zone=True,
            stats=stats,
        )
        session.logs.insert(
            0,
            "🚨 【水晶無效化陷阱房發動！】大門轟然關閉，空間內所有轉移／回復水晶暫時失效！",
        )
        active_combats[user_id] = session
        return {
            "ok": True,
            "action": "open",
            "floor": floor,
            "chest_tier": c_tier,
            "outcome": "crystal_null_room",
            "trap_triggered": "crystal_null_room",
            "crystal_null": True,
            "anti_crystal_zone": True,
            "ambush": True,
            "in_combat": True,
            "combat": session,
            "message": session.logs[0],
        }

    if trap_type == "mimic":
        f27_anti = floor == 27
        session = _spawn_road_combat(
            player,
            content,
            fcfg,
            "mimic_chest",
            is_elite=True,
            anti_crystal_zone=f27_anti,
            stats=stats,
        )
        session.logs.insert(0, "🦷 【寶箱怪伏擊！】寶箱猛然張開血盆大口咬了過來！")
        active_combats[user_id] = session
        return {
            "ok": True,
            "action": "open",
            "floor": floor,
            "chest_tier": c_tier,
            "outcome": "mimic",
            "trap_triggered": "mimic",
            "is_mimic": True,
            "crystal_null": f27_anti,
            "anti_crystal_zone": f27_anti,
            "ambush": True,
            "in_combat": True,
            "combat": session,
            "message": session.logs[0],
        }

    # Genuine chest loot!
    c_spec = content.chests_loot["chest_tiers"].get(c_tier, {})
    col_mult = float(c_spec.get("col_mult", 1.5))
    col_reward = max(40, round(int(fcfg["col_base"]) * col_mult * rgen.uniform(0.9, 1.3)))
    player.col += col_reward
    player.updated_at = ts
    db.save_player(player)

    ctable = content.chests_loot["tier_tables"].get(fcfg["chest_table_id"], {})
    guaranteed = list(ctable.get("guaranteed_pool") or [])
    items_gained: dict[str, int] = {}
    if guaranteed:
        g_weights = [max(0.01, float(p.get("weight", 1))) for p in guaranteed]
        pick = rgen.choices(guaranteed, weights=g_weights, k=1)[0]
        iid = str(pick["item_id"])
        qty = rgen.randint(int(pick.get("min", 1)), int(pick.get("max", 1)))
        if iid in content.items_crystals:
            db.add_item(user_id, iid, qty)
            items_gained[iid] = items_gained.get(iid, 0) + qty

    # Bonus crystal/shard roll driven by chest_tiers[c_tier]["crystal_chance"]
    tier = _tier_for_floor(floor)
    crys_chance = min(1.0, float(c_spec.get("crystal_chance", 0.25)) + stats.drop_bonus * 0.5)
    if rgen.random() < crys_chance:
        bonus_crys = enhance_crystal_for_tier(tier)
        if bonus_crys in content.items_crystals:
            bqty = 2 if c_tier in ("gold", "boss_relic") else 1
            db.add_item(user_id, bonus_crys, bqty)
            items_gained[bonus_crys] = items_gained.get(bonus_crys, 0) + bqty

    # Chest gear drop (respects loot filter & overflows to pending mailbox when bag full)
    tier_to_rarity = {
        "wooden": Rarity.PLAIN,
        "iron": Rarity.FINE,
        "silver": Rarity.RARE,
        "gold": Rarity.SET,
        "boss_relic": Rarity.LEGENDARY,
    }
    set_ids = list(ctable.get("set_ids") or [])
    chosen_rarity = tier_to_rarity.get(c_tier, Rarity.FINE)
    chosen_set = rgen.choice(set_ids) if (chosen_rarity == Rarity.SET and set_ids) else ""
    gear = generate_equipment_item(
        user_id,
        floor,
        content,
        rarity=chosen_rarity,
        weapon_style=player.weapon_style,
        set_id=chosen_set,
        now_ts=ts,
        rng=rgen,
    )
    gear_res = grant_or_queue_equipment(
        db, player, gear, source=f"第{floor}層寶箱({c_tier})", now_ts=ts, apply_filter=True
    )
    equipment_drops: list[dict[str, Any]] = [gear_res]

    # Gold & Boss Relic chests yield an extra socket crystal or bonus Rare/Set equipment roll!
    if c_tier in ("gold", "boss_relic"):
        if rgen.random() < 0.55:
            sock_id = rgen.choice(SOCKET_CRYSTAL_IDS)
            if sock_id in content.items_crystals:
                db.add_item(user_id, sock_id, 1)
                items_gained[sock_id] = items_gained.get(sock_id, 0) + 1
        else:
            bonus_rarity = Rarity.SET if c_tier == "boss_relic" else Rarity.RARE
            bonus_gear = generate_equipment_item(
                user_id,
                floor,
                content,
                rarity=bonus_rarity,
                weapon_style=player.weapon_style,
                set_id=rgen.choice(set_ids) if (bonus_rarity == Rarity.SET and set_ids) else "",
                now_ts=ts,
                rng=rgen,
            )
            equipment_drops.append(
                grant_or_queue_equipment(
                    db, player, bonus_gear, source=f"第{floor}層寶箱追加({c_tier})", now_ts=ts, apply_filter=True
                )
            )

    cname = str(c_spec.get("name", c_tier))
    return {
        "ok": True,
        "action": "open",
        "floor": floor,
        "chest_tier": c_tier,
        "exploration_pct": int(exp_state["progress_pct"]),
        "boss_gate_unlocked": bool(exp_state["boss_gate_unlocked"]),
        "in_combat": False,
        "col_gain": col_reward,
        "items": items_gained,
        "equipment_result": gear_res,
        "equipment_drops": equipment_drops,
        "message": f"🎁 開啟【{cname}】獲得 {col_reward} 柯爾與裝備【{gear.name}】！",
    }


def enter_secret_realm(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    *,
    action: str = "explore",
    now_ts: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Secret Realm & Miasma (`秘境與瘴氣`): enter, explore (stack Miasma + EXP + high-miasma gear), or leave."""
    ts = _now(now_ts)
    act = str(action or "explore").strip().lower()
    if act not in ("enter", "explore", "leave"):
        raise GameError(f"無效的秘境操作：{action}（僅支援 enter / explore / leave）", code="INVALID_SECRET_REALM_ACTION")

    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.is_dead:
        raise GameError("硬派角色已陣亡，無法進入秘境。", code="HARDCORE_DEAD")
    if player.in_boss_battle:
        raise GameError("頭目戰中無法切換至秘境！", code="IN_BOSS_BATTLE")

    fcfg = resolve_floor_config(player.current_floor, content)

    if act == "enter":
        player.zone = ZoneType.SECRET_REALM
        player.updated_at = ts
        db.save_player(player)
        return {
            "ok": True,
            "action": "enter",
            "floor": player.current_floor,
            "zone": player.zone,
            "miasma_stacks": player.miasma_stacks,
            "miasma_exp_stacks": player.miasma_exp_stacks,
            "exp_multiplier": round(1.0 + player.miasma_exp_stacks * 0.15, 2),
            "dmg_taken_multiplier": round(1.0 + player.miasma_stacks * 0.12, 2),
            "message": f"🌫️ 你踏入了第 {player.current_floor} 層【{fcfg['secret_realm_name']}】！秘境瘴氣將大幅提升經驗收益與受傷風險。",
        }

    if act == "leave":
        if player.zone != ZoneType.SECRET_REALM:
            raise GameError("你目前不在秘境中。", code="NOT_IN_SECRET_REALM")
        player.zone = ZoneType.FIELD
        # Leaving secret realm drops EXP bonus while keeping Miasma until returning to Town!
        player.miasma_exp_stacks = 0
        player.updated_at = ts
        db.save_player(player)
        return {
            "ok": True,
            "action": "leave",
            "floor": player.current_floor,
            "zone": player.zone,
            "miasma_stacks": player.miasma_stacks,
            "miasma_exp_stacks": 0,
            "exp_multiplier": 1.0,
            "dmg_taken_multiplier": round(1.0 + player.miasma_stacks * 0.12, 2),
            "message": f"🌫️ 你離開了秘境並回到野外區。經驗加成已消散，但身上仍殘留 {player.miasma_stacks} 層瘴氣（僅回城鎮圈內可清除）！",
        }

    # act == "explore"
    if player.zone != ZoneType.SECRET_REALM:
        raise GameError("請先進入秘境（enter）才能進行秘境深入探索！", code="NOT_IN_SECRET_REALM")

    rgen = _rng(rng_seed)
    eqs = db.get_equipment(user_id, equipped_only=True)
    stats = compute_player_stats(player, eqs, content, floor=player.current_floor)

    player.miasma_stacks = min(MAX_MIASMA_STACKS, player.miasma_stacks + 1)
    player.miasma_exp_stacks = min(MAX_MIASMA_STACKS, player.miasma_exp_stacks + 1)
    exp_mult = 1.0 + player.miasma_exp_stacks * 0.15
    dmg_taken_mult = 1.0 + player.miasma_stacks * 0.12

    exp_gain = max(15, round(int(fcfg["exp_base"]) * 1.6 * exp_mult))
    col_gain = max(25, round(int(fcfg["col_base"]) * 1.4 * rgen.uniform(0.9, 1.25)))
    player.exp += exp_gain
    player.col += col_gain
    player.updated_at = ts
    db.save_player(player)

    items_gained: dict[str, int] = {}
    equipment_drops: list[dict[str, Any]] = []
    loot_note = ""
    if player.miasma_stacks >= 3:
        tier = _tier_for_floor(player.current_floor)
        crys_id = enhance_crystal_for_tier(tier)
        if crys_id in content.items_crystals:
            db.add_item(user_id, crys_id, 1)
            items_gained[crys_id] = 1
        gear_chance = min(0.85, 0.20 + player.miasma_stacks * 0.05 + stats.drop_bonus)
        if rgen.random() < gear_chance:
            if player.miasma_stacks >= 10:
                sr_rarity = Rarity.LEGENDARY if rgen.random() < 0.30 else Rarity.SET
            elif player.miasma_stacks >= 6:
                sr_rarity = Rarity.SET if rgen.random() < 0.45 else Rarity.RARE
            else:
                sr_rarity = Rarity.RARE if rgen.random() < 0.45 else Rarity.FINE
            sr_gear = generate_equipment_item(
                user_id,
                player.current_floor,
                content,
                rarity=sr_rarity,
                weapon_style=player.weapon_style,
                now_ts=ts,
                rng=rgen,
            )
            gres = grant_or_queue_equipment(
                db, player, sr_gear, source=f"第{player.current_floor}層秘境(瘴氣{player.miasma_stacks})", now_ts=ts, apply_filter=True
            )
            equipment_drops.append(gres)
            loot_note = f"、秘境異寶【{sr_gear.name}】"
        if player.miasma_stacks >= 6 and rgen.random() < 0.25:
            sock_id = rgen.choice(SOCKET_CRYSTAL_IDS)
            if sock_id in content.items_crystals:
                db.add_item(user_id, sock_id, 1)
                items_gained[sock_id] = items_gained.get(sock_id, 0) + 1

    return {
        "ok": True,
        "action": "explore",
        "floor": player.current_floor,
        "zone": player.zone,
        "miasma_stacks": player.miasma_stacks,
        "miasma_exp_stacks": player.miasma_exp_stacks,
        "exp_multiplier": round(exp_mult, 2),
        "dmg_taken_multiplier": round(dmg_taken_mult, 2),
        "exp_gain": exp_gain,
        "col_gain": col_gain,
        "items": items_gained,
        "equipment_drops": equipment_drops,
        "message": (
            f"🌫️ 深入【{fcfg['secret_realm_name']}】！瘴氣疊至 {player.miasma_stacks} 層"
            f"（經驗 {exp_mult:.2f}x／受傷 {dmg_taken_mult:.2f}x），獲得 {exp_gain} EXP、{col_gain} 柯爾{loot_note}！"
        ),
    }


def _generate_roguelike_nodes(depth: int, rgen: random.Random) -> list[dict[str, Any]]:
    if depth % 4 == 0:
        return [
            {
                "index": 0,
                "kind": "warden",
                "name": f"深層第 {depth} 層・迷宮守衛者",
                "desc": "鎮守地下迷宮的強力守衛，擊敗後獲得大量積分與代幣！",
            }
        ]
    battle_node = {"kind": "battle", "name": "黑鐵迴廊遭遇戰", "desc": "討伐地下迷宮魔物獲取分數與柯爾。"}
    other_pool = [
        {"kind": "chest", "name": "古代遺跡寶箱", "desc": "開啟寶箱取得裝備或強化素材（可能遭遇擬態怪）。"},
        {"kind": "merchant", "name": "地下迷宮行商", "desc": "以迷宮代幣換取回復藥水與強化祝福。"},
        {"kind": "shrine", "name": "卡迪納爾修復祭壇", "desc": "回復生命與 SP 並獲得迷宮攻擊祝福。"},
    ]
    picked = [battle_node, *rgen.sample(other_pool, k=2)]
    return [{"index": i, **copy.deepcopy(node)} for i, node in enumerate(picked)]


def start_roguelike(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_runs: dict[str, RoguelikeRun],
    user_id: str,
    *,
    now_ts: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Start a Black Iron Palace Underground Roguelike run (Town-only entry, non-permadeath)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.is_dead:
        raise GameError("硬派角色已陣亡，無法進入黑鐵宮地下迷宮。", code="HARDCORE_DEAD")
    if player.zone != ZoneType.TOWN:
        raise GameError("黑鐵宮地下迷宮僅能從城鎮安全區（圈內）進入！", code="TOWN_ONLY_ACTION")
    if user_id in active_runs and not active_runs[user_id].finished:
        raise GameError("你已在進行一場黑鐵宮地下迷宮挑戰，請先推進或撤離結算！", code="ROGUELIKE_ALREADY_ACTIVE")

    rgen = _rng(rng_seed)
    eqs = db.get_equipment(user_id, equipped_only=True)
    stats = compute_player_stats(player, eqs, content, floor=player.current_floor)
    nodes = _generate_roguelike_nodes(1, rgen)
    run = RoguelikeRun(
        run_id=f"rl_{uuid.uuid4().hex[:10]}",
        user_id=user_id,
        depth=1,
        score=0,
        hp=stats.max_hp,
        max_hp=stats.max_hp,
        sp=stats.max_sp,
        max_sp=stats.max_sp,
        tokens=10,
        col_earned=0,
        buffs=[],
        pending_nodes=nodes,
        logs=["🏛️ 踏入黑鐵宮地下迷宮（Roguelike）！此處落敗不會觸發硬派死亡。"],
        finished=False,
        extracted=False,
        started_at=ts,
    )
    active_runs[user_id] = run
    player.zone = ZoneType.ROGUELIKE
    player.updated_at = ts
    db.save_player(player)
    return {
        "ok": True,
        "run_id": run.run_id,
        "roguelike": run,
        "depth": run.depth,
        "score": run.score,
        "nodes": run.pending_nodes,
        "message": run.logs[0],
    }


def step_roguelike(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_runs: dict[str, RoguelikeRun],
    active_combats: dict[str, CombatSession],
    user_id: str,
    *,
    node_index: int = 0,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Choose a node in the active Underground Roguelike run."""
    _now(now_ts)
    run = active_runs.get(user_id)
    if run is None or run.finished:
        raise GameError("目前沒有進行中的黑鐵宮地下迷宮挑戰。", code="NO_ACTIVE_ROGUELIKE")
    if user_id in active_combats and not active_combats[user_id].finished:
        raise GameError("請先完成當前地下迷宮戰鬥！", code="ALREADY_IN_COMBAT")
    if isinstance(node_index, bool) or not isinstance(node_index, int) or not (0 <= node_index < len(run.pending_nodes)):
        raise GameError(f"無效的迷宮路線節點編號：{node_index}", code="INVALID_NODE_INDEX")

    player = db.get_player(user_id)
    if player is None:
        raise GameError("找不到角色資料。", code="PLAYER_NOT_FOUND")
    eqs = db.get_equipment(user_id, equipped_only=True)
    stats = compute_player_stats(player, eqs, content, floor=player.current_floor)

    node = run.pending_nodes[node_index]
    kind = str(node["kind"])
    rgen = random.Random(zlib.crc32(f"{run.run_id}:{run.depth}:{node_index}".encode()))
    in_combat = False
    combat_session: CombatSession | None = None
    items_gained: dict[str, int] = {}
    msg = ""

    if kind in ("battle", "warden"):
        is_warden = kind == "warden"
        mob_id = "labyrinth_warden" if is_warden else "ruin_kobold_trooper"
        mspec = content.monsters.get(mob_id, {"name": "地下迷宮魔物", "dmg_type": "slash", "weaknesses": ["slash"]})
        enemy_hp = max(240, round((220 + run.depth * 65) * (1.8 if is_warden else 1.0)))
        enemy_atk = max(55, round((52 + run.depth * 14) * (1.5 if is_warden else 1.0)))
        enemy_def = max(10, round(10 + run.depth * 4))
        combat_session = CombatSession(
            user_id=user_id,
            mode="roguelike",
            target_id=mob_id,
            difficulty="warden" if is_warden else "normal",
            title=f"黑鐵宮地下迷宮・深層 {run.depth}",
            enemy_name=str(mspec["name"]),
            enemy_emoji="🛡️" if is_warden else "⚔️",
            enemy_max_hp=enemy_hp,
            enemy_hp=enemy_hp,
            enemy_atk=enemy_atk,
            enemy_def=enemy_def,
            enemy_level=max(6, 5 + run.depth * 2),
            player_max_hp=run.max_hp,
            player_hp=max(1, run.hp),
            player_max_mp=run.max_sp,
            player_mp=max(0, run.sp),
            floor=player.current_floor,
            zone=ZoneType.ROGUELIKE,
            weapon_style=player.weapon_style,
            damage_type=str(stats.active_passives.get("dmg_type", DamageType.SLASH)),
            enemy_damage_type=str(mspec.get("dmg_type", DamageType.SLASH)),
            enemy_weaknesses=[str(w) for w in mspec.get("weaknesses", [DamageType.SLASH])],
            player_sp=max(0, run.sp),
            player_max_sp=run.max_sp,
            logs=[f"⚔️ 地下迷宮深層 {run.depth} 遭遇【{mspec['name']}】！"],
        )
        active_combats[user_id] = combat_session
        in_combat = True
        run.score += 180 if is_warden else 80
        run.tokens += 12 if is_warden else 5
        run.col_earned += 250 * run.depth if is_warden else 90 * run.depth
        msg = combat_session.logs[0]
    elif kind == "chest":
        bonus_col = 120 * run.depth
        run.score += 100
        run.tokens += 8
        run.col_earned += bonus_col
        crys_id = enhance_crystal_for_tier(_tier_for_floor(player.current_floor))
        if crys_id in content.items_crystals:
            db.add_item(user_id, crys_id, 2)
            items_gained[crys_id] = 2
        if rgen.random() < 0.35:
            sock_id = rgen.choice(SOCKET_CRYSTAL_IDS)
            if sock_id in content.items_crystals:
                db.add_item(user_id, sock_id, 1)
                items_gained[sock_id] = 1
        extra_lbl = "、".join(
            f"{content.items_crystals.get(k, {}).get('name', k)}x{v}" for k, v in items_gained.items()
        )
        msg = f"🎁 開啟地下迷宮遺跡寶箱！獲得 {bonus_col} 柯爾、8 迷宮代幣、100 積分" + (
            f"與【{extra_lbl}】。" if extra_lbl else "。"
        )
    elif kind == "merchant":
        spent = min(run.tokens, 5)
        run.tokens -= spent
        run.hp = min(run.max_hp, run.hp + round(run.max_hp * 0.35))
        run.buffs.append({"name": "行商磨刀油", "atk_pct": 0.10})
        run.score += 70
        msg = "🛒 迷宮行商交易完成！回復生命並獲得攻擊 +10% 祝福（積分 +70）。"
    else:  # shrine
        run.hp = run.max_hp
        run.sp = run.max_sp
        run.buffs.append({"name": "修復祭壇庇護", "def_pct": 0.12})
        run.score += 65
        msg = "✨ 卡迪納爾修復祭壇光芒籠罩，生命與 SP 全滿且防禦 +12%（積分 +65）！"

    run.depth += 1
    run.pending_nodes = _generate_roguelike_nodes(run.depth, rgen)
    run.logs.append(msg)
    return {
        "ok": True,
        "run_id": run.run_id,
        "node_kind": kind,
        "depth": run.depth,
        "score": run.score,
        "tokens": run.tokens,
        "col_earned": run.col_earned,
        "nodes": run.pending_nodes,
        "items": items_gained,
        "in_combat": in_combat,
        "combat": combat_session,
        "roguelike": run,
        "message": msg,
    }


def extract_roguelike(
    db: RPGDatabase,
    active_runs: dict[str, RoguelikeRun],
    active_combats: dict[str, CombatSession],
    user_id: str,
    *,
    content: SAOContentBundle | None = None,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Safely extract from Underground Roguelike, settling score, Col, depth-scaled equipment, and quests."""
    ts = _now(now_ts)
    run = active_runs.get(user_id)
    if run is None or run.finished:
        raise GameError("目前沒有可撤離結算的地下迷宮進度。", code="NO_ACTIVE_ROGUELIKE")

    player = db.get_player(user_id)
    if player is None:
        raise GameError("找不到角色資料。", code="PLAYER_NOT_FOUND")

    active_combats.pop(user_id, None)
    run.finished = True
    run.extracted = True
    total_col = run.col_earned + run.score * 2 + run.tokens * 15
    exp_gain = max(20, run.score * 2)
    player.col += total_col
    player.exp += exp_gain
    player.roguelike_best_score = max(player.roguelike_best_score, run.score)
    player.zone = ZoneType.TOWN
    player.updated_at = ts
    db.save_player(player)
    active_runs.pop(user_id, None)

    items_gained: dict[str, int] = {}
    equipment_drops: list[dict[str, Any]] = []
    if content is not None:
        rgen = random.Random(zlib.crc32(f"extract:{run.run_id}:{run.depth}:{run.score}".encode()))
        crys_id = enhance_crystal_for_tier(_tier_for_floor(player.current_floor))
        crys_qty = max(1, min(6, run.depth))
        if crys_id in content.items_crystals:
            db.add_item(user_id, crys_id, crys_qty)
            items_gained[crys_id] = crys_qty
        if "forge_scrap" in content.items_crystals:
            scrap_qty = max(1, run.depth)
            db.add_item(user_id, "forge_scrap", scrap_qty)
            items_gained["forge_scrap"] = scrap_qty
        if run.depth >= 2 or run.score >= 60:
            if run.depth >= 8 or run.score >= 800:
                ext_rarity = Rarity.LEGENDARY
            elif run.depth >= 5 or run.score >= 350:
                ext_rarity = Rarity.SET
            elif run.depth >= 3 or run.score >= 150:
                ext_rarity = Rarity.RARE
            else:
                ext_rarity = Rarity.FINE
            ext_gear = generate_equipment_item(
                user_id,
                max(1, player.current_floor),
                content,
                rarity=ext_rarity,
                weapon_style=player.weapon_style,
                now_ts=ts,
                rng=rgen,
            )
            equipment_drops.append(
                grant_or_queue_equipment(
                    db, player, ext_gear, source=f"黑鐵宮迷宮撤離(深層{run.depth})", now_ts=ts, apply_filter=False
                )
            )

    week_key = time.strftime("%Y-W%W", time.gmtime(ts))
    db.increment_quest(user_id, "weekly", week_key, "wq_roguelike_3", 3, delta=1)

    gear_note = f"、裝備【{equipment_drops[0]['item_name']}】" if equipment_drops else ""
    return {
        "ok": True,
        "run_id": run.run_id,
        "floor": player.current_floor,
        "extracted": True,
        "depth_reached": run.depth,
        "score": run.score,
        "best_score": player.roguelike_best_score,
        "col_gain": total_col,
        "exp_gain": exp_gain,
        "items": items_gained,
        "equipment_drops": equipment_drops,
        "zone": player.zone,
        "message": (
            f"🏛️ 成功撤離黑鐵宮地下迷宮！結算積分 {run.score}（最高 {player.roguelike_best_score}），"
            f"獲得 {total_col} 柯爾、{exp_gain} EXP{gear_note}！"
        ),
    }


def get_monument_of_life(
    db: RPGDatabase,
    *,
    limit: int = 10,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Read F1 Black Iron Palace Monument of Life (`生命之碑`) survival summary."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise GameError("查詢筆數 limit 必須為正整數。", code="INVALID_LIMIT")
    safe_limit = min(50, limit)
    summary = db.get_monument_summary(limit=safe_limit, now_ts=now_ts)
    if summary["total"] == 0:
        msg = "🪦 【黑鐵宮・生命之碑】目前尚未有任何玩家登錄於艾恩葛朗特。"
    else:
        msg = (
            f"🪦 【黑鐵宮・生命之碑】總玩家：{summary['total']}｜存活：{summary['alive']}｜"
            f"瀕死待援：{summary['downed']}｜殞落：{summary['fallen']}"
        )
    return {
        "ok": True,
        "total": summary["total"],
        "alive": summary["alive"],
        "downed": summary["downed"],
        "fallen": summary["fallen"],
        "entries": summary["entries"],
        "monument": summary,
        "message": msg,
    }


def get_argo_intel(
    db: RPGDatabase,
    content: SAOContentBundle,
    *,
    user_id: str | None = None,
    floor: int | None = None,
) -> dict[str, Any]:
    """Argo's Info (`阿爾狗的情報`): frontline floor, Hall of Fame, & masked/observed boss skills."""
    if user_id is not None and db.get_player(user_id) is None:
        raise GameError(f"找不到指定玩家的情報紀錄：{user_id}", code="PLAYER_NOT_FOUND")
    if floor is not None and (isinstance(floor, bool) or not isinstance(floor, int) or not (1 <= floor <= 100)):
        raise GameError(f"無效的情報樓層：{floor}（必須為 1～100）", code="INVALID_FLOOR")

    frontline = db.get_server_frontline_floor()
    hall_of_fame = db.get_all_server_floor_clears()
    target_floor = floor if floor is not None else frontline
    fcfg = resolve_floor_config(target_floor, content)
    boss_spec = fcfg["boss"]
    boss_id = str(boss_spec["id"])
    seen_map = db.get_boss_intel_seen(user_id, boss_id) if user_id else {}
    seen_ids = set(seen_map.get(boss_id, []))

    raw_skills = get_all_boss_skill_specs(boss_spec)
    skills_view: list[dict[str, Any]] = []
    for sk in raw_skills:
        observed = sk["skill_id"] in seen_ids
        skills_view.append(
            {
                "skill_id": sk["skill_id"] if observed else "???",
                "phase": sk["phase"],
                "name": sk["name"] if observed else "???",
                "dmg_type": sk["dmg_type"] if observed else "???",
                "telegraph": sk["telegraph"] if observed else "尚未觀測（遭遇頭目階段後解鎖情報）",
                "observed": observed,
            }
        )

    return {
        "ok": True,
        "frontline_floor": frontline,
        "floor": target_floor,
        "boss_id": boss_id,
        "boss_name": boss_spec["name"],
        "hp_bars": int(boss_spec.get("hp_bars", 4)),
        "weaknesses": list(boss_spec.get("weaknesses", [])),
        "skills": skills_view,
        "observed_count": sum(1 for s in skills_view if s["observed"]),
        "total_skills": len(skills_view),
        "hall_of_fame": hall_of_fame,
        "first_kill": db.get_server_floor_clear(target_floor),
        "message": f"🐭 【阿爾狗的情報屋】全服前線：第 {frontline} 層｜第 {target_floor} 層頭目【{boss_spec['name']}】已觀測 {sum(1 for s in skills_view if s['observed'])}/{len(skills_view)} 項階段情報。",
    }


def get_yui_logs(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
) -> dict[str, Any]:
    """Yui Console (`結衣終端機`): unlockable Cardinal system lore archives across milestone floors."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色，無法存取結衣終端機。", code="PLAYER_NOT_FOUND")

    unlocked_map = db.get_yui_logs(user_id)
    all_logs = content.quests_events.get("yui_logs", {})
    entries: list[dict[str, Any]] = []
    unlocked_count = 0
    for log_id, spec in sorted(all_logs.items(), key=lambda kv: int(kv[1].get("unlock_floor", 1))):
        req_floor = int(spec.get("unlock_floor", 1))
        reached = player.highest_cleared_floor >= req_floor if req_floor >= 100 else (
            player.highest_cleared_floor >= req_floor or player.max_unlocked_floor >= req_floor
        )
        is_unlocked = log_id in unlocked_map or req_floor <= 1 or reached
        if is_unlocked and log_id not in unlocked_map:
            db.unlock_yui_log(user_id, log_id, player.updated_at or int(time.time()))
        if is_unlocked:
            unlocked_count += 1
            entries.append(
                {
                    "id": log_id,
                    "unlock_floor": req_floor,
                    "code": str(spec.get("code", log_id)),
                    "title": str(spec.get("title", "")),
                    "content": str(spec.get("content", "")),
                    "unlocked": True,
                }
            )
        else:
            entries.append(
                {
                    "id": log_id,
                    "unlock_floor": req_floor,
                    "code": str(spec.get("code", log_id)),
                    "title": f"【權限不足】需通關第 {req_floor} 層解鎖",
                    "content": "權限不足：尚未取得卡迪納爾系統對應樓層授權。",
                    "unlocked": False,
                }
            )

    return {
        "ok": True,
        "unlocked_count": unlocked_count,
        "total_count": len(entries),
        "logs": entries,
        "entries": entries,
        "message": f"👧 【結衣終端機 MHCP-001】已解鎖 {unlocked_count}/{len(entries)} 份卡迪納爾核心紀錄。",
    }


def set_survival_config(
    db: RPGDatabase,
    user_id: str,
    *,
    auto_potion_pct: float | None = None,
    auto_crystal_pct: float | None = None,
    auto_retreat_pct: float | None = None,
    stop_on_no_potion: bool | None = None,
) -> dict[str, Any]:
    """Configure auto-battle survival HP% thresholds (accepts 0..100 percent or 0..1 fraction)."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    def _norm_pct(val: Any, name: str) -> int | float:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise GameError(f"生存設定 {name} 必須為數字百分比（0～100）。", code="INVALID_SURVIVAL_CONFIG")
        f = float(val)
        if f < 0 or f > 100:
            raise GameError(f"生存設定 {name} 超出有效範圍（0～100）：{val}", code="SURVIVAL_PCT_OUT_OF_RANGE")
        return int(val) if isinstance(val, int) else round(f, 4)

    cfg = dict(player.survival_config or {})
    if auto_potion_pct is not None:
        cfg["auto_potion_pct"] = _norm_pct(auto_potion_pct, "auto_potion_pct")
    if auto_crystal_pct is not None:
        cfg["auto_crystal_pct"] = _norm_pct(auto_crystal_pct, "auto_crystal_pct")
    if auto_retreat_pct is not None:
        cfg["auto_retreat_pct"] = _norm_pct(auto_retreat_pct, "auto_retreat_pct")
    if stop_on_no_potion is not None:
        if not isinstance(stop_on_no_potion, bool):
            raise GameError("stop_on_no_potion 必須為布林值。", code="INVALID_SURVIVAL_CONFIG")
        cfg["stop_on_no_potion"] = stop_on_no_potion

    player.survival_config = cfg
    db.save_player(player)

    def _disp(v: Any, default: float) -> int:
        fv = float(v if v is not None else default)
        return round(fv * 100) if 0 < fv <= 1.0 else round(fv)

    return {
        "ok": True,
        "survival_config": cfg,
        "message": (
            f"🛡️ 生存設定已更新！自動喝藥：{_disp(cfg.get('auto_potion_pct'), 40)}%｜"
            f"自動水晶：{_disp(cfg.get('auto_crystal_pct'), 20)}%｜"
            f"自動撤退：{_disp(cfg.get('auto_retreat_pct'), 15)}%｜"
            f"無藥暫停：{'開啟' if cfg.get('stop_on_no_potion', True) else '關閉'}"
        ),
    }
