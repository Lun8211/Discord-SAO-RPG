"""SAO Economy & Workshop System: Equipment, Loadouts, Loot Filter, Forge, Enhance, Magic Stones, Fusion, Cooking, Big Pot Stew, Shop & Gacha (ZERO discord imports)."""

from __future__ import annotations

import random
import re
import time
from typing import Any

from src.rpg.content.loader import SAOContentBundle
from src.rpg.database import RPGDatabase
from src.rpg.models import (
    MAX_ENHANCE_LEVEL,
    SAO_RARITY_ORDER,
    SAO_SLOT_ORDER,
    CombatSession,
    EquipmentItem,
    GameError,
    PlayerProfile,
    Rarity,
    ZoneType,
)
from src.rpg.systems.combat import compute_full_player_stats
from src.rpg.systems.stats import _is_shield_item
from src.rpg.systems.tower import (
    _rarity_index,
    _tier_for_floor,
    enhance_crystal_for_tier,
    generate_equipment_item,
    generate_named_equipment,
    grant_or_queue_equipment,
)

MAX_TEMPER_LEVEL = 5
MAX_AFFIX_COUNT = 4
_PROMOTE_CHAIN: tuple[str, ...] = (
    Rarity.PLAIN,
    Rarity.FINE,
    Rarity.RARE,
    Rarity.SET,
    Rarity.LEGENDARY,
)
_RARITY_PREFIX_RE = re.compile(r"^【[^】]+】")


def _now(now_ts: int | None) -> int:
    return int(now_ts if now_ts is not None else time.time())


def _require_town(player: PlayerProfile, action_label: str) -> None:
    if player.in_boss_battle:
        raise GameError(f"頭目戰進行中無法執行{action_label}！", code="ACTION_BLOCKED_IN_BOSS")
    if player.zone != ZoneType.TOWN:
        raise GameError(f"{action_label}僅能在城鎮安全區（圈內）執行！", code="TOWN_ONLY_ACTION")


def _level_mastery(db: RPGDatabase, user_id: str, skill_key: str, exp_gain: int) -> tuple[int, int]:
    mastery = db.get_mastery(user_id)
    cur = mastery.get(skill_key, {"level": 1, "exp": 0})
    lv = int(cur["level"])
    exp = int(cur["exp"]) + max(1, int(exp_gain))
    while exp >= max(25, lv * 25):
        exp -= max(25, lv * 25)
        lv += 1
    db.upsert_mastery(user_id, skill_key, lv, exp)
    return lv, exp


def equip_item(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
    item_uid: int,
) -> dict[str, Any]:
    """Equip an owned non-escrowed equipment piece into one of the 8 SAO slots."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.in_boss_battle or (user_id in active_combats and not active_combats[user_id].finished):
        raise GameError("戰鬥或頭目戰中無法更換裝備！", code="EQUIP_BLOCKED_IN_COMBAT")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到屬於你的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")

    equipped = db.equip_item(user_id, eq.id)
    if equipped is None:
        raise GameError("裝備穿戴失敗，請確認物品狀態。", code="EQUIP_FAILED")

    stats = compute_full_player_stats(db, content, player)
    player.combat_power = stats.combat_power
    db.save_player(player)
    return {
        "ok": True,
        "item_uid": equipped.id,
        "slot": equipped.slot,
        "item": equipped,
        "combat_power": stats.combat_power,
        "active_sets": list(stats.active_sets),
        "stats": stats,
        "message": f"🛡️ 已裝備【{equipped.name}】（欄位：{equipped.slot}），目前戰力 {stats.combat_power}！",
    }


def toggle_lock_item(
    db: RPGDatabase,
    user_id: str,
    item_uid: int,
) -> dict[str, Any]:
    """Toggle protection lock on an owned equipment piece (blocks market/fusion/turn-in)."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")

    eq.is_locked = not eq.is_locked
    db.update_equipment(eq)
    state_zh = "已鎖定保護" if eq.is_locked else "已解除鎖定"
    return {
        "ok": True,
        "item_uid": eq.id,
        "is_locked": eq.is_locked,
        "item": eq,
        "message": f"🔒 裝備【{eq.name}】{state_zh}。",
    }


def save_loadout(
    db: RPGDatabase,
    user_id: str,
    slot_index: int,
    name: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Save current equipped gear into Loadout slot 1..5 (`裝備方案`)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if isinstance(slot_index, bool) or not isinstance(slot_index, int) or not (1 <= slot_index <= 5):
        raise GameError(f"無效的裝備方案格位：{slot_index}（必須為 1～5）", code="INVALID_LOADOUT_SLOT")
    clean_name = str(name or f"方案 {slot_index}").strip()[:32]
    if not clean_name:
        raise GameError("裝備方案名稱不可為空。", code="INVALID_LOADOUT_NAME")

    equipped = db.get_equipment(user_id, equipped_only=True)
    gear_ids = [eq.id for eq in equipped]
    db.save_gear_loadout(user_id, slot_index, clean_name, gear_ids, ts)
    return {
        "ok": True,
        "slot_index": slot_index,
        "name": clean_name,
        "gear_ids": gear_ids,
        "message": f"💾 已將目前 {len(gear_ids)} 件穿戴裝備儲存至方案 #{slot_index}【{clean_name}】！",
    }


def apply_loadout(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
    slot_index: int,
) -> dict[str, Any]:
    """Apply saved Loadout slot 1..5 (blocked during active combat/boss)."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.in_boss_battle or (user_id in active_combats and not active_combats[user_id].finished):
        raise GameError("戰鬥或頭目戰中無法切換裝備方案！", code="LOADOUT_BLOCKED_IN_COMBAT")
    if isinstance(slot_index, bool) or not isinstance(slot_index, int) or not (1 <= slot_index <= 5):
        raise GameError(f"無效的裝備方案格位：{slot_index}（必須為 1～5）", code="INVALID_LOADOUT_SLOT")

    loadouts = db.get_gear_loadouts(user_id)
    lo = loadouts.get(slot_index)
    if lo is None:
        raise GameError(f"裝備方案 #{slot_index} 尚未儲存任何配置！", code="EMPTY_LOADOUT")

    for sl in SAO_SLOT_ORDER:
        db.unequip_slot(user_id, sl)

    equipped_count = 0
    for gid in lo.get("gear_ids", []):
        if db.equip_item(user_id, int(gid)) is not None:
            equipped_count += 1

    stats = compute_full_player_stats(db, content, player)
    player.combat_power = stats.combat_power
    db.save_player(player)
    return {
        "ok": True,
        "slot_index": slot_index,
        "name": lo["name"],
        "equipped_count": equipped_count,
        "combat_power": stats.combat_power,
        "stats": stats,
        "message": f"⚡ 已一鍵切換至裝備方案 #{slot_index}【{lo['name']}】（穿戴 {equipped_count} 件，戰力 {stats.combat_power}）！",
    }


def set_loot_filter(
    db: RPGDatabase,
    user_id: str,
    *,
    min_rarity: str | None = None,
    min_level: int | None = None,
    blocked_slots: list[str] | None = None,
) -> dict[str, Any]:
    """Configure Loot Filter (`戰利品過濾`); Set (`珍品`) & Named (`名品`) ALWAYS bypass filter."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    flt = dict(player.loot_filter or {"min_rarity": "plain", "min_level": 1, "blocked_slots": []})
    if min_rarity is not None:
        r = str(min_rarity).strip().lower()
        if r not in SAO_RARITY_ORDER:
            raise GameError(f"無效的過濾品質：{min_rarity}", code="INVALID_RARITY")
        flt["min_rarity"] = r
    if min_level is not None:
        if isinstance(min_level, bool) or not isinstance(min_level, int) or min_level < 1 or min_level > 200:
            raise GameError(f"無效的最低過濾等級：{min_level}", code="INVALID_MIN_LEVEL")
        flt["min_level"] = min_level
    if blocked_slots is not None:
        if not isinstance(blocked_slots, list):
            raise GameError("過濾欄位必須為清單格式。", code="INVALID_SLOTS")
        clean_slots: list[str] = []
        for s in blocked_slots:
            sl = str(s).strip().lower()
            if sl not in SAO_SLOT_ORDER:
                raise GameError(f"未知的裝備欄位：{s}", code="INVALID_SLOT")
            if sl not in clean_slots:
                clean_slots.append(sl)
        flt["blocked_slots"] = clean_slots

    player.loot_filter = flt
    db.save_player(player)
    return {
        "ok": True,
        "loot_filter": flt,
        "message": f"🔍 戰利品過濾已更新（最低品質：{flt['min_rarity']}／最低等級：{flt['min_level']}；珍品套裝與名品永不過濾）！",
    }


def forge_craft(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    recipe_id: str,
    *,
    slot: str | None = None,
    now_ts: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Lisbeth Workshop Blacksmithing (`鍛造`): atomic validation, slot targeting, F48 crit-forging & mastery EXP."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "工坊鍛造")

    recipes = content.recipes.get("blacksmithing", {})
    rec = recipes.get(recipe_id)
    if not isinstance(rec, dict):
        raise GameError(f"未知的鍛造配方：{recipe_id}", code="UNKNOWN_RECIPE")

    chosen_slot: str | None = None
    if slot is not None and str(slot).strip():
        chosen_slot = str(slot).strip().lower()
        if chosen_slot not in SAO_SLOT_ORDER:
            raise GameError(f"無效的指定鍛造裝備欄位：{slot}", code="INVALID_SLOT")

    out_type = str(rec.get("output_type", "tiered_gear"))
    named_id = ""
    if out_type == "named_item":
        named_id = str(rec.get("output_item_id") or rec.get("output_named_id") or "")
        if not named_id or named_id not in content.weapons_equipment.get("named_items", {}):
            raise GameError(f"鍛造配方對應的名品裝備不存在：{named_id or recipe_id}", code="UNKNOWN_NAMED_ITEM")

    col_cost = int(rec.get("col_cost", 100))
    ingredients = {str(k): int(v) for k, v in (rec.get("ingredients") or {}).items()}

    if player.col < col_cost:
        raise GameError(f"柯爾不足！鍛造【{rec['name']}】需要 {col_cost} 柯爾（目前 {player.col}）。", code="INSUFFICIENT_COL")
    for iid, qty in ingredients.items():
        if db.get_item_qty(user_id, iid) < qty:
            iname = content.items_crystals.get(iid, {}).get("name", iid)
            raise GameError(f"鍛造素材不足！缺少【{iname}】x{qty}。", code="INSUFFICIENT_MATERIALS")

    # Atomic consumption AFTER full output & material validation
    with db.transaction():
        if ingredients and not db.consume_items(user_id, ingredients):
            raise GameError("鍛造素材扣除失敗！", code="INSUFFICIENT_MATERIALS")
        player.col -= col_cost
        player.updated_at = ts
        db.save_player(player)

    rgen = random.Random(rng_seed) if rng_seed is not None else random.Random(ts + player.col + len(recipe_id))
    mastery = db.get_mastery(user_id)
    bs_lv = int(mastery.get("blacksmithing", {}).get("level", 1))
    crit_forge = False

    if out_type == "named_item":
        item = generate_named_equipment(user_id, named_id, content, now_ts=ts)
    else:
        tier = int(rec.get("output_tier", 1))
        floor = max(1, (tier - 1) * 10 + 5)
        base_rarity = Rarity.RARE if tier >= 3 else Rarity.FINE
        f48_bonus = 0.10 if player.current_floor == 48 else (0.04 if player.max_unlocked_floor >= 48 else 0.0)
        crit_chance = min(0.45, 0.08 + max(0, bs_lv - 1) * 0.008 + f48_bonus)
        if rgen.random() < crit_chance:
            crit_forge = True
            if base_rarity == Rarity.RARE:
                base_rarity = Rarity.LEGENDARY if rgen.random() < 0.35 else Rarity.SET
            else:
                base_rarity = Rarity.SET if rgen.random() < 0.45 else Rarity.RARE
        item = generate_equipment_item(
            user_id,
            floor,
            content,
            rarity=base_rarity,
            slot=chosen_slot,
            weapon_style=player.weapon_style,
            now_ts=ts,
            rng=rgen,
        )

    grant = grant_or_queue_equipment(db, player, item, source=f"工坊鍛造({recipe_id})", now_ts=ts, apply_filter=False)
    lv, _ = _level_mastery(db, user_id, "blacksmithing", int(rec.get("mastery_exp", 20)))
    today_key = time.strftime("%Y-%m-%d", time.gmtime(ts))
    db.increment_quest(user_id, "daily", today_key, "dq_enhance_1", 1, delta=1)
    if lv >= 40:
        db.unlock_achievement(user_id, "sao_ach_forge_master", ts)

    crit_banner = "🌟【名匠大成功！】" if crit_forge else ""
    return {
        "ok": True,
        "recipe_id": recipe_id,
        "slot": item.slot,
        "crit_forge": crit_forge,
        "col_spent": col_cost,
        "blacksmithing_level": lv,
        "equipment_result": grant,
        "item_uid": grant.get("item_uid"),
        "item": grant.get("item"),
        "message": f"🔨 {crit_banner}莉茲貝特工坊鍛造成功！打造出【{item.name}】（鍛造熟練度 Lv.{lv}）！",
    }


def enhance_equipment(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    item_uid: int,
    *,
    use_protection: bool = False,
    now_ts: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Enhance equipment from +0 up to +15 with Bright/Dark Crystals, Lisbeth Mastery Perks, Blessing Pity & Protection."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "裝備強化")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到欲強化的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
    if eq.enhance_level >= MAX_ENHANCE_LEVEL:
        raise GameError(f"裝備【{eq.name}】已達最高強化等級 +{MAX_ENHANCE_LEVEL}！", code="MAX_ENHANCE_REACHED")

    next_lv = eq.enhance_level + 1
    etable = content.weapons_equipment.get("enhance_table", {})
    step = etable.get(str(next_lv))
    if not isinstance(step, dict):
        raise GameError(f"找不到強化等級 +{next_lv} 設定。", code="INVALID_ENHANCE_STEP")

    mastery = db.get_mastery(user_id)
    bs_lv = int(mastery.get("blacksmithing", {}).get("level", 1))
    f48_workshop = player.current_floor == 48
    col_discount = min(0.25, max(0, bs_lv - 1) * 0.005 + (0.08 if f48_workshop else 0.0))
    rate_bonus = min(0.12, max(0, bs_lv - 1) * 0.003 + (0.05 if f48_workshop else 0.0))

    raw_col_cost = int(step.get("col", 200))
    col_cost = max(1, round(raw_col_cost * (1.0 - col_discount)))
    crys_id = str(step.get("crystal_id", "bright_crystal_shard"))
    crys_qty = int(step.get("crystal_qty", 1))
    req_items: dict[str, int] = {crys_id: crys_qty}
    if use_protection:
        req_items["protection_talisman"] = 1

    if player.col < col_cost:
        raise GameError(f"柯爾不足！強化 +{next_lv} 需要 {col_cost} 柯爾。", code="INSUFFICIENT_COL")
    for iid, qty in req_items.items():
        if db.get_item_qty(user_id, iid) < qty:
            iname = content.items_crystals.get(iid, {}).get("name", iid)
            raise GameError(f"強化材料不足！缺少【{iname}】x{qty}。", code="INSUFFICIENT_MATERIALS")

    with db.transaction():
        if not db.consume_items(user_id, req_items):
            raise GameError("強化材料扣除失敗！", code="INSUFFICIENT_MATERIALS")
        player.col -= col_cost

    rgen = random.Random(rng_seed) if rng_seed is not None else random.Random()
    base_rate = float(step.get("rate", 1.0))
    eff_rate = 1.0 if base_rate >= 1.0 else min(0.95, base_rate + rate_bonus)
    pity_triggered = eq.enhance_pity >= 100
    success = pity_triggered or (rgen.random() < eff_rate)
    downgraded = False

    if success:
        eq.enhance_level = next_lv
        eq.enhance_pity = 0
        msg = (
            f"✨ 【{'祝福保底！' if pity_triggered else ''}強化成功】"
            f"【{eq.name}】強化至 +{eq.enhance_level}！"
        )
    else:
        pity_gain = max(20, int(step.get("pity_gain", 25)))
        eq.enhance_pity = min(100, eq.enhance_pity + pity_gain)
        can_down = bool(step.get("downgrade", False))
        if can_down and not use_protection and eq.enhance_level > 0:
            eq.enhance_level -= 1
            downgraded = True
            msg = f"💥 強化失敗！【{eq.name}】降至 +{eq.enhance_level}（保底祝福累積至 {eq.enhance_pity}%）。"
        elif can_down and use_protection:
            msg = f"🧿 強化失敗，但【陽壽籤】保護了裝備等級不降級！（維持 +{eq.enhance_level}，祝福 {eq.enhance_pity}%）"
        else:
            msg = f"⚠️ 強化失敗，裝備等級維持 +{eq.enhance_level}（保底祝福累積至 {eq.enhance_pity}%）。"

    db.update_equipment(eq)
    player.total_enhances += 1
    stats = compute_full_player_stats(db, content, player, now_ts=ts)
    player.combat_power = stats.combat_power
    player.updated_at = ts
    db.save_player(player)
    today_key = time.strftime("%Y-%m-%d", time.gmtime(ts))
    db.increment_quest(user_id, "daily", today_key, "dq_enhance_1", 1, delta=1)
    if eq.enhance_level >= 10:
        db.unlock_achievement(user_id, "sao_ach_enhance_10", ts)
    if eq.enhance_level >= 15:
        db.unlock_achievement(user_id, "sao_ach_enhance_15", ts)
        db.unlock_achievement(user_id, "sao_ach_forge_master", ts)

    return {
        "ok": True,
        "item_uid": eq.id,
        "success": success,
        "pity_triggered": pity_triggered,
        "downgraded": downgraded,
        "protected": use_protection and not success,
        "enhance_level": eq.enhance_level,
        "enhance_pity": eq.enhance_pity,
        "col_spent": col_cost,
        "materials_spent": dict(req_items),
        "effective_rate": round(eff_rate, 4),
        "item": eq,
        "message": msg,
    }


def apply_magic_stone(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    item_uid: int,
    stone_id: str,
    *,
    target_affix_key: str | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Apply Magic Stone (`翻石`/`替石`/`毛石`/`擴石`) on non-Named gear (STRICTLY forbidden on Named gear)."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "魔石洗詞綴")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到欲使用魔石的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
    if eq.is_named or eq.rarity == Rarity.NAMED:
        raise GameError("名品裝備（Named）擁有固定傳說詞綴，禁止使用魔石洗煉或擴孔！", code="NAMED_GEAR_NO_MAGIC_STONE")

    st_spec = content.items_crystals.get(stone_id)
    if not isinstance(st_spec, dict) or st_spec.get("category") != "magic_stone":
        raise GameError(f"無效的魔石種類：{stone_id}", code="INVALID_MAGIC_STONE")
    if db.get_item_qty(user_id, stone_id) <= 0:
        raise GameError(f"背包中缺少【{st_spec.get('name', stone_id)}】！", code="INSUFFICIENT_MATERIALS")

    affix_pool = content.chests_loot.get("affix_pool", {})
    pool_keys = list(affix_pool.keys())
    old_affixes = dict(eq.affixes)
    tier_mult = 1.0 + (eq.tier - 1) * 0.08

    # Validate expand_stone & targeted swap_stone BEFORE consuming the stone!
    if stone_id == "expand_stone":
        if len(eq.affixes) >= MAX_AFFIX_COUNT:
            raise GameError(
                f"裝備【{eq.name}】詞綴數量已達上限（{MAX_AFFIX_COUNT} 條），無法再使用擴孔魔石！",
                code="AFFIX_SLOTS_MAXED",
            )
        candidates = [k for k in pool_keys if k not in eq.affixes]
        if not candidates:
            raise GameError("已無可供擴充的新詞綴類型！", code="NO_AVAILABLE_AFFIX")
    elif stone_id == "swap_stone" and target_affix_key is not None and str(target_affix_key).strip():
        tk = str(target_affix_key).strip()
        if tk not in eq.affixes:
            raise GameError(f"裝備【{eq.name}】目前沒有詞綴【{tk}】，無法指定替換！", code="AFFIX_NOT_FOUND")

    db.consume_items(user_id, {stone_id: 1})
    rgen = random.Random(rng_seed) if rng_seed is not None else random.Random()

    if stone_id == "expand_stone":
        # 擴石: add 1 fresh affix up to MAX_AFFIX_COUNT (4)
        new_affixes = dict(eq.affixes)
        candidates = [k for k in pool_keys if k not in new_affixes]
        add_k = rgen.choice(candidates)
        lo, hi = affix_pool[add_k].get("base_range", [0.02, 0.06])
        new_affixes[add_k] = round(rgen.uniform(float(lo), float(hi)) * tier_mult, 4)
        eq.affixes = new_affixes
    elif stone_id == "reroll_stone" or not eq.affixes:
        # 翻石: reroll all affixes
        count = max(1, len(eq.affixes) or 2)
        picked = rgen.sample(pool_keys, k=min(count, len(pool_keys)))
        new_affixes = {}
        for ak in picked:
            lo, hi = affix_pool[ak].get("base_range", [0.02, 0.06])
            new_affixes[ak] = round(rgen.uniform(float(lo), float(hi)) * tier_mult, 4)
        eq.affixes = new_affixes
    elif stone_id == "swap_stone":
        # 替石: replace targeted affix (or first affix by default) with a fresh different affix
        new_affixes = dict(eq.affixes)
        drop_k = (
            str(target_affix_key).strip()
            if (target_affix_key is not None and str(target_affix_key).strip() in new_affixes)
            else next(iter(new_affixes.keys()))
        )
        new_affixes.pop(drop_k, None)
        candidates = [k for k in pool_keys if k not in new_affixes] or pool_keys
        add_k = rgen.choice(candidates)
        lo, hi = affix_pool[add_k].get("base_range", [0.02, 0.06])
        new_affixes[add_k] = round(rgen.uniform(float(lo), float(hi)) * tier_mult, 4)
        eq.affixes = new_affixes
    else:
        # 毛石 (refine_stone): refine numeric rolls upward within upper range
        new_affixes = {}
        for ak, cur_v in eq.affixes.items():
            if ak in affix_pool:
                lo, hi = affix_pool[ak].get("base_range", [0.02, 0.06])
                boosted = max(float(cur_v), rgen.uniform((float(lo) + float(hi)) / 2.0, float(hi)) * tier_mult)
                new_affixes[ak] = round(boosted, 4)
            else:
                new_affixes[ak] = round(float(cur_v) * 1.05, 4)
        eq.affixes = new_affixes

    db.update_equipment(eq)
    stats = compute_full_player_stats(db, content, player)
    player.combat_power = stats.combat_power
    db.save_player(player)
    return {
        "ok": True,
        "item_uid": eq.id,
        "stone_id": stone_id,
        "old_affixes": old_affixes,
        "affixes": dict(eq.affixes),
        "item": eq,
        "message": f"💎 已對【{eq.name}】使用【{st_spec.get('name', stone_id)}】，詞綴重鑄完成（共 {len(eq.affixes)} 條詞綴）！",
    }


def fuse_items(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    recipe_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Workshop Fusion (`融合`): combine crystal shards, ores, or essences into higher-tier materials."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "工坊融合")

    rec = content.recipes.get("fusion", {}).get(recipe_id)
    if not isinstance(rec, dict):
        raise GameError(f"未知的融合配方：{recipe_id}", code="UNKNOWN_RECIPE")

    col_cost = int(rec.get("col_cost", 100))
    ingredients = {str(k): int(v) for k, v in (rec.get("ingredients") or {}).items()}
    if player.col < col_cost:
        raise GameError(f"柯爾不足！融合需要 {col_cost} 柯爾。", code="INSUFFICIENT_COL")
    for iid, qty in ingredients.items():
        if db.get_item_qty(user_id, iid) < qty:
            iname = content.items_crystals.get(iid, {}).get("name", iid)
            raise GameError(f"融合材料不足！缺少【{iname}】x{qty}。", code="INSUFFICIENT_MATERIALS")

    out_id = str(rec["output_item_id"])
    out_qty = max(1, int(rec.get("output_qty", 1)))
    with db.transaction():
        if ingredients and not db.consume_items(user_id, ingredients):
            raise GameError("融合材料扣除失敗！", code="INSUFFICIENT_MATERIALS")
        player.col -= col_cost
        player.updated_at = ts
        db.save_player(player)
        db.add_item(user_id, out_id, out_qty)

    lv, _ = _level_mastery(db, user_id, "blacksmithing", int(rec.get("mastery_exp", 15)))
    oname = content.items_crystals.get(out_id, {}).get("name", out_id)
    return {
        "ok": True,
        "recipe_id": recipe_id,
        "output_item_id": out_id,
        "output_qty": out_qty,
        "blacksmithing_level": lv,
        "message": f"⚗️ 融合成功！獲得【{oname}】x{out_qty}！",
    }


def cook_dish(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    recipe_id: str,
    *,
    timing_perfect: bool = False,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Cook an Aincrad dish with optional `timing_perfect` bonus + Cooking mastery EXP."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    rec = content.recipes.get("cooking", {}).get(recipe_id)
    if not isinstance(rec, dict):
        raise GameError(f"未知的料理食譜：{recipe_id}", code="UNKNOWN_RECIPE")

    col_cost = int(rec.get("col_cost", 30))
    ingredients = {str(k): int(v) for k, v in (rec.get("ingredients") or {}).items()}
    if player.col < col_cost:
        raise GameError(f"柯爾不足！烹調【{rec['name']}】需要 {col_cost} 柯爾。", code="INSUFFICIENT_COL")
    for iid, qty in ingredients.items():
        if db.get_item_qty(user_id, iid) < qty:
            iname = content.items_crystals.get(iid, {}).get("name", iid)
            raise GameError(f"料理食材不足！缺少【{iname}】x{qty}。", code="INSUFFICIENT_MATERIALS")

    out_id = str(rec["output_item_id"])
    base_qty = max(1, int(rec.get("output_qty", 1)))
    final_qty = base_qty + (1 if timing_perfect else 0)
    with db.transaction():
        if ingredients and not db.consume_items(user_id, ingredients):
            raise GameError("食材扣除失敗！", code="INSUFFICIENT_MATERIALS")
        player.col -= col_cost
        db.add_item(user_id, out_id, final_qty)
        # Also apply active dish buff immediately for smooth combat readiness
        dish_spec = content.items_crystals.get(out_id, {})
        dish_eff = dict(dish_spec.get("effect") or {})
        if dish_eff:
            mult = 1.25 if timing_perfect else 1.0
            scaled_buff = {
                k: round(float(v) * mult, 4)
                for k, v in dish_eff.items()
                if isinstance(v, (int, float)) and k != "duration_sec"
            }
            dur = int(dish_eff.get("duration_sec", 3600))
            buffs = dict(player.active_buffs or {})
            buffs["cooking_dish"] = {
                "name": str(dish_spec.get("name", out_id)),
                "bonuses": scaled_buff,
                "expires_at": ts + dur,
                "timing_perfect": bool(timing_perfect),
            }
            player.active_buffs = buffs
        player.updated_at = ts
        db.save_player(player)

    exp_gain = int(rec.get("mastery_exp", 15)) * (2 if timing_perfect else 1)
    lv, _ = _level_mastery(db, user_id, "cooking", exp_gain)
    today_key = time.strftime("%Y-%m-%d", time.gmtime(ts))
    db.increment_quest(user_id, "daily", today_key, "dq_cook_1", 1, delta=1)
    if lv >= 40 or out_id == "dish_ragout_stew":
        db.unlock_achievement(user_id, "sao_ach_cook_master", ts)
    dname = content.items_crystals.get(out_id, {}).get("name", out_id)
    return {
        "ok": True,
        "recipe_id": recipe_id,
        "output_item_id": out_id,
        "output_qty": final_qty,
        "timing_perfect": bool(timing_perfect),
        "cooking_level": lv,
        "message": (
            f"🍲 {'🌟完美火候！' if timing_perfect else ''}烹調完成：【{dname}】x{final_qty}"
            f"（料理熟練度 Lv.{lv}）！"
        ),
    }


def start_big_pot_stew(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    recipe_id: str,
    party_or_guild_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Start a shared Party/Guild Big Pot Stew (`一大鍋`) so teammates can claim buff servings."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if not str(party_or_guild_id or "").strip():
        raise GameError("請指定共享一大鍋的隊伍或公會編號。", code="INVALID_STEW_SCOPE")

    rec = content.recipes.get("stew", {}).get(recipe_id)
    if not isinstance(rec, dict):
        raise GameError(f"未知的一大鍋燉煮配方：{recipe_id}", code="UNKNOWN_RECIPE")

    col_cost = int(rec.get("col_cost", 400))
    ingredients = {str(k): int(v) for k, v in (rec.get("ingredients") or {}).items()}
    if player.col < col_cost:
        raise GameError(f"柯爾不足！燉煮一大鍋需要 {col_cost} 柯爾。", code="INSUFFICIENT_COL")
    for iid, qty in ingredients.items():
        if db.get_item_qty(user_id, iid) < qty:
            iname = content.items_crystals.get(iid, {}).get("name", iid)
            raise GameError(f"一大鍋食材不足！缺少【{iname}】x{qty}。", code="INSUFFICIENT_MATERIALS")

    servings = max(2, int(rec.get("servings", 6)))
    dur = int(rec.get("buff_duration_sec", 3600))
    scope_str = str(party_or_guild_id).strip()
    scope_type = "party" if db.get_party(scope_str) is not None else "guild"

    with db.transaction():
        if ingredients and not db.consume_items(user_id, ingredients):
            raise GameError("一大鍋食材扣除失敗！", code="INSUFFICIENT_MATERIALS")
        player.col -= col_cost
        player.updated_at = ts
        db.save_player(player)
        stew_id = db.create_world_buff(
            buff_key=recipe_id,
            scope_type=scope_type,
            scope_id=scope_str,
            name=str(rec.get("name", recipe_id)),
            payload={
                "bonuses": dict(rec.get("party_buff") or {"atk_pct": 0.10, "hp_pct": 0.10}),
                "scope_id": scope_str,
                "scope_type": scope_type,
                "duration_sec": dur,
            },
            expires_at=ts + dur,
            now_ts=ts,
            created_by=user_id,
            charges=servings,
        )

    lv, _ = _level_mastery(db, user_id, "cooking", int(rec.get("mastery_exp", 60)))
    today_key = time.strftime("%Y-%m-%d", time.gmtime(ts))
    db.increment_quest(user_id, "daily", today_key, "dq_cook_1", 1, delta=1)
    if lv >= 40:
        db.unlock_achievement(user_id, "sao_ach_cook_master", ts)
    return {
        "ok": True,
        "stew_id": str(stew_id),
        "recipe_id": recipe_id,
        "scope_type": scope_type,
        "scope_id": scope_str,
        "servings": servings,
        "cooking_level": lv,
        "message": f"🥘 【一大鍋開煮！】已為團隊（{scope_str}）架起【{rec.get('name', recipe_id)}】，共 {servings} 份可供隊友領取！",
    }


def claim_stew(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    stew_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Claim 1 serving from a shared Party/Guild Big Pot Stew (validates membership & prevents double-claim)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    try:
        numeric_id = int(str(stew_id))
    except ValueError as exc:
        raise GameError(f"無效的一大鍋編號：{stew_id}", code="INVALID_STEW_ID") from exc

    # Verify scope membership before consuming charge
    with db._lock:
        row = db._conn.execute("SELECT * FROM world_buffs WHERE id = ?", (numeric_id,)).fetchone()
    if row is None:
        raise GameError("找不到這鍋料理或已失效。", code="STEW_NOT_FOUND")

    scope_type = str(row["scope_type"])
    scope_id = str(row["scope_id"])
    if scope_type == "party":
        party = db.get_party(scope_id)
        if party is None or user_id not in party.members:
            raise GameError("你不是此隊伍成員，無法領取這鍋隊伍一大鍋！", code="STEW_WRONG_SCOPE")
    elif scope_type == "guild" and (player.guild_id is None or str(player.guild_id) != scope_id):
        raise GameError("你不是此公會成員，無法領取這鍋公會一大鍋！", code="STEW_WRONG_SCOPE")

    claimed = db.claim_world_buff_charge(numeric_id, user_id, ts)
    payload = claimed.get("payload") or {}
    bonuses = dict(payload.get("bonuses") or {"atk_pct": 0.10, "hp_pct": 0.10})
    dur = int(payload.get("duration_sec", 3600))

    buffs = dict(player.active_buffs or {})
    buffs["big_pot_stew"] = {
        "name": str(claimed.get("name", "一大鍋料理")),
        "bonuses": bonuses,
        "expires_at": ts + dur,
    }
    player.active_buffs = buffs
    stats = compute_full_player_stats(db, content, player, now_ts=ts)
    player.combat_power = stats.combat_power
    player.updated_at = ts
    db.save_player(player)
    today_key = time.strftime("%Y-%m-%d", time.gmtime(ts))
    db.increment_quest(user_id, "daily", today_key, "dq_cook_1", 1, delta=1)
    return {
        "ok": True,
        "stew_id": str(numeric_id),
        "remaining_charges": int(claimed.get("remaining_charges", 0)),
        "bonuses": bonuses,
        "combat_power": stats.combat_power,
        "message": f"🥣 已享用【{claimed.get('name', '一大鍋')}】獲得團隊料理加成！（剩餘 {claimed.get('remaining_charges', 0)} 份）",
    }


def buy_shop_item(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    item_id: str,
    *,
    qty: int = 1,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Purchase potions, all 4 SAO Crystals, spices, or supplies from the Aincrad Town Shop."""
    ts = _now(now_ts)
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        raise GameError("購買數量必須為正整數。", code="INVALID_QUANTITY")

    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    spec = content.items_crystals.get(item_id)
    if not isinstance(spec, dict):
        raise GameError(f"商店找不到此商品：{item_id}", code="UNKNOWN_ITEM")

    unit_price = int(spec.get("buy_col") or 0)
    if unit_price <= 0:
        raise GameError(f"【{spec.get('name', item_id)}】為非賣品，無法直接於商店購買！", code="ITEM_NOT_FOR_SALE")

    total_cost = unit_price * qty
    if player.col < total_cost:
        raise GameError(
            f"柯爾不足！購買【{spec.get('name', item_id)}】x{qty} 需要 {total_cost} 柯爾（目前 {player.col}）。",
            code="INSUFFICIENT_COL",
        )

    with db.transaction():
        player.col -= total_cost
        player.updated_at = ts
        db.save_player(player)
        new_qty = db.add_item(user_id, item_id, qty)
        db.record_shop_purchase(user_id, "sao_shop", item_id, qty)

    return {
        "ok": True,
        "item_id": item_id,
        "item_name": str(spec.get("name", item_id)),
        "qty": qty,
        "total_cost": total_cost,
        "owned_qty": new_qty,
        "col_remaining": player.col,
        "message": f"🛒 已花費 {total_cost} 柯爾購買【{spec.get('name', item_id)}】x{qty}（現有 {new_qty} 個）！",
    }


def gacha_pull(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    *,
    chest_type: str = "standard",
    count: int = 1,
    now_ts: int | None = None,
    rng_seed: int | None = None,
    use_ticket: bool = False,
) -> dict[str, Any]:
    """Deterministic Aincrad Relic Chest gacha with pity guarantee & optional `gacha_relic_ticket` consumption."""
    ts = _now(now_ts)
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0 or count > 10:
        raise GameError("抽獎次數必須介於 1～10 之間。", code="INVALID_GACHA_COUNT")

    ctype = str(chest_type or "standard").strip().lower()
    if ctype not in ("standard", "relic", "premium"):
        raise GameError(f"不支援的秘寶箱類型：{chest_type}", code="INVALID_CHEST_TYPE")

    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    tickets_used = 0
    if use_ticket:
        if db.get_item_qty(user_id, "gacha_relic_ticket") < count:
            raise GameError(
                f"秘寶庫抽取券不足！需要 {count} 張（目前 {db.get_item_qty(user_id, 'gacha_relic_ticket')} 張）。",
                code="INSUFFICIENT_MATERIALS",
            )
        if not db.consume_items(user_id, {"gacha_relic_ticket": count}):
            raise GameError("秘寶庫抽取券扣除失敗！", code="INSUFFICIENT_MATERIALS")
        tickets_used = count
        total_cost = 0
        eff_ctype = "relic" if ctype == "standard" else ctype
    else:
        unit_col = 500 if ctype == "standard" else 1200
        total_cost = unit_col * count
        if player.col < total_cost:
            raise GameError(f"柯爾不足！開啟 {count} 次秘寶箱需要 {total_cost} 柯爾（目前 {player.col}）。", code="INSUFFICIENT_COL")
        player.col -= total_cost
        eff_ctype = ctype

    rgen = random.Random(rng_seed) if rng_seed is not None else random.Random()
    pulls: list[dict[str, Any]] = []
    granted_uids: list[int | None] = []

    for _ in range(count):
        player.gacha_pity_legendary += 1
        if player.gacha_pity_legendary >= 10:
            rarity = Rarity.LEGENDARY
            player.gacha_pity_legendary = 0
        else:
            roll = rgen.random()
            if eff_ctype != "standard" and roll < 0.22:
                rarity = Rarity.LEGENDARY
                player.gacha_pity_legendary = 0
            elif roll < 0.35:
                rarity = Rarity.SET
            elif roll < 0.70:
                rarity = Rarity.RARE
            else:
                rarity = Rarity.FINE
        eq = generate_equipment_item(
            user_id,
            max(1, player.current_floor),
            content,
            rarity=rarity,
            weapon_style=player.weapon_style,
            now_ts=ts,
            rng=rgen,
        )
        grant = grant_or_queue_equipment(db, player, eq, source=f"秘寶箱({eff_ctype})", now_ts=ts, apply_filter=False)
        granted_uids.append(grant.get("item_uid"))
        pulls.append(
            {
                "template_id": eq.template_id,
                "name": eq.name,
                "slot": eq.slot,
                "rarity": eq.rarity,
                "tier": eq.tier,
                "base_atk": eq.base_atk,
                "base_def": eq.base_def,
                "base_hp": eq.base_hp,
                "affixes": dict(eq.affixes),
            }
        )

    player.updated_at = ts
    db.save_player(player)
    cost_note = f"（消耗秘寶券 x{tickets_used}）" if tickets_used else f"（花費 {total_cost} 柯爾）"
    return {
        "ok": True,
        "chest_type": eff_ctype,
        "count": count,
        "total_cost": total_cost,
        "tickets_used": tickets_used,
        "pulls": pulls,
        "items": pulls,
        "granted_uids": granted_uids,
        "pity_legendary": player.gacha_pity_legendary,
        "message": f"🎰 已開啟 {count} 次艾恩葛朗特秘寶箱{cost_note}，獲得 {len(pulls)} 件裝備！",
    }


# =============================================================================
# Round 2 Multi-Dimensional Equipment Upgrading, Salvage & Acquisition APIs
# =============================================================================
def batch_enhance_equipment(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    item_uid: int,
    *,
    target_level: int = 5,
    use_protection: bool = False,
    now_ts: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Safely batch-enhance an equipment item up to `target_level` (1..15), stopping cleanly on target or shortage."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "批量強化")

    if isinstance(target_level, bool) or not isinstance(target_level, int) or not (1 <= target_level <= MAX_ENHANCE_LEVEL):
        raise GameError(f"目標強化等級必須介於 1～{MAX_ENHANCE_LEVEL} 之間。", code="INVALID_TARGET_LEVEL")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到欲強化的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
    if eq.enhance_level >= target_level:
        raise GameError(
            f"裝備【{eq.name}】目前已達 +{eq.enhance_level}（已達或超過目標 +{target_level}）！",
            code="ALREADY_AT_OR_ABOVE_TARGET",
        )

    start_level = eq.enhance_level
    attempts = 0
    successes = 0
    col_spent = 0
    materials_spent: dict[str, int] = {}
    stop_reason = ""
    latest_item = eq

    for step_idx in range(30):
        cur_eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
        if cur_eq is None or cur_eq.enhance_level >= target_level or cur_eq.enhance_level >= MAX_ENHANCE_LEVEL:
            break
        derived_seed = (rng_seed + step_idx * 17) if rng_seed is not None else None
        try:
            res = enhance_equipment(
                db,
                content,
                user_id,
                item_uid,
                use_protection=use_protection,
                now_ts=ts,
                rng_seed=derived_seed,
            )
        except GameError as exc:
            if attempts == 0:
                raise
            stop_reason = f"（因資源不足提前停止：{exc.message}）"
            break
        attempts += 1
        if res.get("success"):
            successes += 1
        col_spent += int(res.get("col_spent", 0))
        for mid, mqty in (res.get("materials_spent") or {}).items():
            materials_spent[mid] = materials_spent.get(mid, 0) + int(mqty)
        latest_item = res["item"]
        if latest_item.enhance_level >= target_level:
            break

    return {
        "ok": True,
        "item_uid": latest_item.id,
        "item": latest_item,
        "start_level": start_level,
        "end_level": latest_item.enhance_level,
        "attempts": attempts,
        "successes": successes,
        "col_spent": col_spent,
        "materials_spent": materials_spent,
        "message": (
            f"⚡ 批量強化完成：【{latest_item.name}】+{start_level} → +{latest_item.enhance_level}"
            f"（共嘗試 {attempts} 次、成功 {successes} 次、花費 {col_spent} 柯爾）{stop_reason}"
        ),
    }


def _compute_dismantle_yield(eq: EquipmentItem, content: SAOContentBundle) -> tuple[int, dict[str, int], int]:
    """Compute (col_gain, items_gained, blacksmithing_exp) for dismantling a single EquipmentItem."""
    r_idx = _rarity_index(eq.rarity)
    scrap_base = {0: 1, 1: 2, 2: 4, 3: 8, 4: 14, 5: 20}.get(r_idx, 1)
    scrap_qty = max(1, scrap_base * max(1, (eq.tier + 1) // 2) + eq.temper_level * 2)
    col_gain = max(25, eq.tier * 45 * (r_idx + 1) + eq.enhance_level * 40 + eq.temper_level * 80)

    items: dict[str, int] = {"forge_scrap": scrap_qty}
    crys_id = enhance_crystal_for_tier(eq.tier)
    if crys_id in content.items_crystals and (r_idx >= 1 or eq.tier >= 3):
        items[crys_id] = items.get(crys_id, 0) + max(1, r_idx)

    # 50% enhancement crystal refund so upgrading old gear is never wasted!
    if eq.enhance_level > 0:
        etable = content.weapons_equipment.get("enhance_table", {})
        spent_crystals: dict[str, int] = {}
        for lv in range(1, min(eq.enhance_level, MAX_ENHANCE_LEVEL) + 1):
            st = etable.get(str(lv), {})
            cid = str(st.get("crystal_id", "bright_crystal_shard"))
            cqty = int(st.get("crystal_qty", 1))
            spent_crystals[cid] = spent_crystals.get(cid, 0) + cqty
        for cid, total_q in spent_crystals.items():
            if cid in content.items_crystals:
                refund = max(1, total_q // 2)
                items[cid] = items.get(cid, 0) + refund

    # Safely recover any socketed combat crystal instead of destroying it!
    if eq.socket_crystal_id and eq.socket_crystal_id in content.items_crystals:
        items[eq.socket_crystal_id] = items.get(eq.socket_crystal_id, 0) + 1

    bs_exp = max(8, eq.tier * 4 + r_idx * 6 + eq.enhance_level * 2)
    return col_gain, items, bs_exp


def dismantle_equipment(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    item_uid: int,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Dismantle an unequipped, unlocked, non-escrowed equipment piece into Forge Scrap, Crystals, Col & Mastery EXP."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "裝備分解")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=True)
    if eq is None:
        raise GameError(f"找不到欲分解的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
    if eq.is_equipped:
        raise GameError("穿戴中的裝備無法分解，請先卸下！", code="CANNOT_DISMANTLE_EQUIPPED")
    if eq.is_locked:
        raise GameError("已鎖定的裝備受保護無法分解，請先解鎖！", code="CANNOT_DISMANTLE_LOCKED")
    if eq.escrow_state:
        raise GameError("託管於市集或公會倉庫的裝備無法分解！", code="CANNOT_DISMANTLE_ESCROWED")

    col_gain, items_gained, bs_exp = _compute_dismantle_yield(eq, content)
    with db.transaction():
        deleted = db.delete_equipment(user_id, [eq.id])
        if deleted <= 0:
            raise GameError("裝備分解失敗（物品已不存在）。", code="EQUIPMENT_NOT_FOUND")
        player.col += col_gain
        player.updated_at = ts
        db.save_player(player)
        for iid, qty in items_gained.items():
            if iid in content.items_crystals and qty > 0:
                db.add_item(user_id, iid, qty)

    lv, _ = _level_mastery(db, user_id, "blacksmithing", bs_exp)
    if lv >= 40:
        db.unlock_achievement(user_id, "sao_ach_forge_master", ts)
    mat_desc = "、".join(
        f"{content.items_crystals.get(k, {}).get('name', k)}x{v}" for k, v in items_gained.items()
    )
    return {
        "ok": True,
        "dismantled_uid": eq.id,
        "item_name": eq.name,
        "col_gain": col_gain,
        "items_gained": items_gained,
        "blacksmithing_exp": bs_exp,
        "blacksmithing_level": lv,
        "message": f"♻️ 已分解【{eq.name}】，回收 {col_gain} 柯爾與【{mat_desc}】（鍛造 Lv.{lv}）！",
    }


def bulk_dismantle_equipment(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    *,
    max_rarity: str = "fine",
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Bulk-dismantle low-tier spare gear (`plain`/`fine`/`rare` max), strictly protecting equipped/locked/Set+/+5+/tempered."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "批量裝備分解")

    norm_max = str(max_rarity or "fine").strip().lower()
    if norm_max not in (Rarity.PLAIN, Rarity.FINE, Rarity.RARE):
        raise GameError(
            f"批量分解最高僅支援至極品（rare），禁止批量分解珍品／傳說／名品裝備：{max_rarity}",
            code="BULK_DISMANTLE_RARITY_FORBIDDEN",
        )
    max_idx = _rarity_index(norm_max)

    all_gear = db.get_equipment(user_id, equipped_only=False, include_escrowed=False)
    targets: list[EquipmentItem] = []
    for eq in all_gear:
        if eq.is_equipped or eq.is_locked or eq.escrow_state:
            continue
        if eq.is_named or eq.is_set_piece or eq.rarity in (Rarity.SET, Rarity.LEGENDARY, Rarity.NAMED):
            continue
        if eq.enhance_level >= 5 or eq.temper_level > 0 or eq.socket_crystal_id:
            continue
        if _rarity_index(eq.rarity) <= max_idx:
            targets.append(eq)

    if not targets:
        return {
            "ok": True,
            "count": 0,
            "dismantled_uids": [],
            "col_gain": 0,
            "items_gained": {},
            "blacksmithing_exp": 0,
            "message": "🧹 背包中沒有符合條件的可批量分解裝備（已自動保護穿戴中、鎖定、珍品以上與 +5 以上裝備）。",
        }

    total_col = 0
    total_items: dict[str, int] = {}
    total_exp = 0
    uids: list[int] = []
    for eq in targets:
        c, its, be = _compute_dismantle_yield(eq, content)
        total_col += c
        total_exp += be
        uids.append(eq.id)
        for iid, qty in its.items():
            total_items[iid] = total_items.get(iid, 0) + qty

    with db.transaction():
        db.delete_equipment(user_id, uids)
        player.col += total_col
        player.updated_at = ts
        db.save_player(player)
        for iid, qty in total_items.items():
            if iid in content.items_crystals and qty > 0:
                db.add_item(user_id, iid, qty)

    lv, _ = _level_mastery(db, user_id, "blacksmithing", total_exp)
    if lv >= 40:
        db.unlock_achievement(user_id, "sao_ach_forge_master", ts)
    return {
        "ok": True,
        "count": len(uids),
        "dismantled_uids": uids,
        "col_gain": total_col,
        "items_gained": total_items,
        "blacksmithing_exp": total_exp,
        "blacksmithing_level": lv,
        "message": (
            f"♻️ 批量分解完成！共拆解 {len(uids)} 件多餘裝備，獲得 {total_col} 柯爾、"
            f"精鐵碎塊 x{total_items.get('forge_scrap', 0)}（鍛造 Lv.{lv}）！"
        ),
    }


def temper_equipment(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    item_uid: int,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Temper / Star-Awaken (`淬鍊鍛星`, ★0 → ★5) ANY owned non-escrowed gear including Named items."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "裝備鍛星淬鍊")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到欲鍛星的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
    if eq.temper_level >= MAX_TEMPER_LEVEL:
        raise GameError(f"裝備【{eq.name}】已達最高鍛星覺醒 ★{MAX_TEMPER_LEVEL}！", code="MAX_TEMPER_REACHED")

    next_star = eq.temper_level + 1
    col_cost = (300 + eq.tier * 220) * next_star
    scrap_qty = 2 * next_star
    crys_id = enhance_crystal_for_tier(eq.tier)
    crys_qty = next_star
    req_items: dict[str, int] = {"forge_scrap": scrap_qty, crys_id: crys_qty}

    if player.col < col_cost:
        raise GameError(f"柯爾不足！鍛星至 ★{next_star} 需要 {col_cost} 柯爾（目前 {player.col}）。", code="INSUFFICIENT_COL")
    for iid, qty in req_items.items():
        if db.get_item_qty(user_id, iid) < qty:
            iname = content.items_crystals.get(iid, {}).get("name", iid)
            raise GameError(f"鍛星材料不足！缺少【{iname}】x{qty}。", code="INSUFFICIENT_MATERIALS")

    with db.transaction():
        if not db.consume_items(user_id, req_items):
            raise GameError("鍛星材料扣除失敗！", code="INSUFFICIENT_MATERIALS")
        player.col -= col_cost
        eq.temper_level = next_star
        db.update_equipment(eq)
        stats = compute_full_player_stats(db, content, player, now_ts=ts)
        player.combat_power = stats.combat_power
        player.updated_at = ts
        db.save_player(player)

    _level_mastery(db, user_id, "blacksmithing", 18 * next_star)
    today_key = time.strftime("%Y-%m-%d", time.gmtime(ts))
    db.increment_quest(user_id, "daily", today_key, "dq_enhance_1", 1, delta=1)

    milestone = ""
    if next_star == 3:
        milestone = "（覺醒 ★3 被動：暴擊率 +3%、全四軸抗性 +3%！）"
    elif next_star == 5:
        milestone = "（覺醒 ★5 終極被動：劍技傷害 +8%、減傷 +5%！）"
    return {
        "ok": True,
        "item_uid": eq.id,
        "item": eq,
        "temper_level": eq.temper_level,
        "col_spent": col_cost,
        "materials_spent": req_items,
        "message": f"⭐ 鍛星淬鍊成功！【{eq.name}】升星至 ★{eq.temper_level}/{MAX_TEMPER_LEVEL}（倍率 {eq.temper_multiplier():.2f}x）{milestone}",
    }


def evolve_equipment_tier(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    item_uid: int,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Evolve equipment tier (`裝備升階`, T1 → T10), scaling base stats while preserving enhance/temper/affixes/socket."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "裝備升階")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到欲升階的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
    if eq.tier >= 10:
        raise GameError(f"裝備【{eq.name}】已達最高階級 T10！", code="MAX_TIER_REACHED")

    old_tier = eq.tier
    new_tier = old_tier + 1
    col_cost = 600 * new_tier
    scrap_qty = 3 * new_tier
    crys_id = enhance_crystal_for_tier(new_tier)
    crys_qty = 2
    req_items: dict[str, int] = {"forge_scrap": scrap_qty, crys_id: crys_qty}

    if player.col < col_cost:
        raise GameError(f"柯爾不足！升階至 T{new_tier} 需要 {col_cost} 柯爾（目前 {player.col}）。", code="INSUFFICIENT_COL")
    for iid, qty in req_items.items():
        if db.get_item_qty(user_id, iid) < qty:
            iname = content.items_crystals.get(iid, {}).get("name", iid)
            raise GameError(f"升階材料不足！缺少【{iname}】x{qty}。", code="INSUFFICIENT_MATERIALS")

    base_gear = content.weapons_equipment.get("base_gear", {})
    old_scale = float(base_gear.get(str(old_tier), {}).get("scale", 1.0 + (old_tier - 1) * 0.8))
    new_scale = float(base_gear.get(str(new_tier), {}).get("scale", 1.0 + (new_tier - 1) * 0.8))
    ratio = max(1.22, min(1.55, new_scale / max(0.5, old_scale)))

    def _scale_stat(val: int) -> int:
        if val <= 0:
            return val
        return max(val + 1, round(val * ratio))

    with db.transaction():
        if not db.consume_items(user_id, req_items):
            raise GameError("升階材料扣除失敗！", code="INSUFFICIENT_MATERIALS")
        player.col -= col_cost
        eq.tier = new_tier
        eq.min_level = max(1, (new_tier - 1) * 10 + 1)
        eq.base_hp = _scale_stat(eq.base_hp)
        eq.base_mp = _scale_stat(eq.base_mp)
        eq.base_sp = _scale_stat(eq.base_sp)
        eq.base_atk = _scale_stat(eq.base_atk)
        eq.base_def = _scale_stat(eq.base_def)
        eq.base_spd = _scale_stat(eq.base_spd) if eq.base_spd > 0 else eq.base_spd
        if not eq.is_named and eq.rarity != Rarity.NAMED:
            new_cfg = base_gear.get(str(new_tier), {})
            new_prefix = str(new_cfg.get("prefix") or f"T{new_tier}")
            eq.template_id = f"t{new_tier}_{eq.slot}_{eq.rarity}"
            if f"({new_prefix}T{new_tier})" not in eq.name:
                clean_nm = re.sub(r"\s*\([^)]*T\d+\)$", "", eq.name)
                eq.name = f"{clean_nm} ({new_prefix}T{new_tier})"
        db.update_equipment(eq)
        stats = compute_full_player_stats(db, content, player, now_ts=ts)
        player.combat_power = stats.combat_power
        player.updated_at = ts
        db.save_player(player)

    _level_mastery(db, user_id, "blacksmithing", 22 * new_tier)
    today_key = time.strftime("%Y-%m-%d", time.gmtime(ts))
    db.increment_quest(user_id, "daily", today_key, "dq_enhance_1", 1, delta=1)
    return {
        "ok": True,
        "item_uid": eq.id,
        "item": eq,
        "old_tier": old_tier,
        "new_tier": new_tier,
        "col_spent": col_cost,
        "materials_spent": req_items,
        "message": f"⬆️ 裝備升階成功！【{eq.name}】自 T{old_tier} 晉升至 T{new_tier}，基礎屬性全面躍升（強化／鍛星／詞綴完整保留）！",
    }


def promote_equipment_rarity(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    item_uid: int,
    *,
    now_ts: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Promote non-Named equipment rarity (`裝備升品`: plain → fine → rare → set → legendary)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "裝備升品")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到欲升品的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
    if eq.is_named or eq.rarity == Rarity.NAMED:
        raise GameError("名品裝備（Named）已為專屬傳說品質，無法再進行升品！", code="NAMED_GEAR_CANNOT_PROMOTE")
    if eq.rarity == Rarity.LEGENDARY or eq.rarity not in _PROMOTE_CHAIN:
        raise GameError(f"裝備【{eq.name}】已達最高升品品質（傳說 Legendary）！", code="MAX_RARITY_REACHED")

    old_rarity = eq.rarity
    old_idx = _PROMOTE_CHAIN.index(old_rarity)
    new_rarity = _PROMOTE_CHAIN[old_idx + 1]
    step = old_idx + 1

    col_cost = 500 * step * max(1, eq.tier)
    scrap_qty = 3 * step
    crys_id = enhance_crystal_for_tier(eq.tier)
    crys_qty = step + 1
    req_items: dict[str, int] = {"forge_scrap": scrap_qty, crys_id: crys_qty}

    if player.col < col_cost:
        raise GameError(f"柯爾不足！升品至【{new_rarity}】需要 {col_cost} 柯爾（目前 {player.col}）。", code="INSUFFICIENT_COL")
    for iid, qty in req_items.items():
        if db.get_item_qty(user_id, iid) < qty:
            iname = content.items_crystals.get(iid, {}).get("name", iid)
            raise GameError(f"升品材料不足！缺少【{iname}】x{qty}。", code="INSUFFICIENT_MATERIALS")

    rarities_cfg = content.chests_loot.get("rarities", {})
    old_mult = float(rarities_cfg.get(old_rarity, {}).get("stat_mult", 1.0))
    new_mult = float(rarities_cfg.get(new_rarity, {}).get("stat_mult", old_mult * 1.25))
    ratio = max(1.15, new_mult / max(0.5, old_mult))
    rgen = random.Random(rng_seed) if rng_seed is not None else random.Random(ts + eq.id)

    def _scale(v: int) -> int:
        return max(v + 1, round(v * ratio)) if v > 0 else v

    with db.transaction():
        if not db.consume_items(user_id, req_items):
            raise GameError("升品材料扣除失敗！", code="INSUFFICIENT_MATERIALS")
        player.col -= col_cost
        eq.rarity = new_rarity
        eq.base_hp = _scale(eq.base_hp)
        eq.base_mp = _scale(eq.base_mp)
        eq.base_sp = _scale(eq.base_sp)
        eq.base_atk = _scale(eq.base_atk)
        eq.base_def = _scale(eq.base_def)
        eq.base_spd = _scale(eq.base_spd) if eq.base_spd > 0 else eq.base_spd
        if new_rarity == Rarity.SET and not eq.set_id:
            tier_cfg = content.weapons_equipment.get("base_gear", {}).get(str(eq.tier), {})
            eq.set_id = str(tier_cfg.get("set_id") or "")
        # Update rarity label prefix in name
        new_prefix = str(rarities_cfg.get(new_rarity, {}).get("name") or new_rarity)
        if _RARITY_PREFIX_RE.match(eq.name):
            eq.name = _RARITY_PREFIX_RE.sub(f"【{new_prefix}】", eq.name, count=1)
        else:
            eq.name = f"【{new_prefix}】{eq.name}"
        # Grant bonus affix if below new rarity's minimum affix count
        aff_min = int((rarities_cfg.get(new_rarity, {}).get("affix_range") or [1, 2])[0])
        affix_pool = content.chests_loot.get("affix_pool", {})
        if len(eq.affixes) < min(MAX_AFFIX_COUNT, aff_min):
            candidates = [k for k in affix_pool if k not in eq.affixes]
            if candidates:
                ak = rgen.choice(candidates)
                lo, hi = affix_pool[ak].get("base_range", [0.02, 0.05])
                eq.affixes[ak] = round(rgen.uniform(float(lo), float(hi)) * (1.0 + (eq.tier - 1) * 0.08), 4)
        db.update_equipment(eq)
        stats = compute_full_player_stats(db, content, player, now_ts=ts)
        player.combat_power = stats.combat_power
        player.updated_at = ts
        db.save_player(player)

    _level_mastery(db, user_id, "blacksmithing", 25 * step)
    today_key = time.strftime("%Y-%m-%d", time.gmtime(ts))
    db.increment_quest(user_id, "daily", today_key, "dq_enhance_1", 1, delta=1)
    return {
        "ok": True,
        "item_uid": eq.id,
        "item": eq,
        "old_rarity": old_rarity,
        "new_rarity": new_rarity,
        "col_spent": col_cost,
        "materials_spent": req_items,
        "message": f"🌟 裝備升品成功！【{eq.name}】品質自 {old_rarity} 晉升為 {new_rarity}！",
    }


def socket_equipment_crystal(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    item_uid: int,
    crystal_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Socket a Combat Crystal into any owned non-escrowed equipment item with zero-destruction swap."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "結晶鑲嵌")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到欲鑲嵌結晶的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")

    cspec = content.items_crystals.get(crystal_id)
    if not isinstance(cspec, dict) or cspec.get("category") != "socket_crystal":
        raise GameError(f"無效的戰鬥鑲嵌結晶：{crystal_id}", code="INVALID_SOCKET_CRYSTAL")
    if eq.socket_crystal_id == crystal_id:
        raise GameError(f"裝備【{eq.name}】已鑲嵌相同的【{cspec.get('name', crystal_id)}】！", code="SAME_CRYSTAL_ALREADY_SOCKETED")
    if db.get_item_qty(user_id, crystal_id) <= 0:
        raise GameError(f"背包中缺少【{cspec.get('name', crystal_id)}】！", code="INSUFFICIENT_MATERIALS")

    prev_cid = eq.socket_crystal_id or None
    with db.transaction():
        if not db.consume_items(user_id, {crystal_id: 1}):
            raise GameError("鑲嵌結晶扣除失敗！", code="INSUFFICIENT_MATERIALS")
        if prev_cid and prev_cid in content.items_crystals:
            db.add_item(user_id, prev_cid, 1)
        eq.socket_crystal_id = crystal_id
        db.update_equipment(eq)
        stats = compute_full_player_stats(db, content, player, now_ts=ts)
        player.combat_power = stats.combat_power
        player.updated_at = ts
        db.save_player(player)

    swap_note = ""
    if prev_cid:
        prev_name = content.items_crystals.get(prev_cid, {}).get("name", prev_cid)
        swap_note = f"（已無損退還原鑲嵌的【{prev_name}】至背包）"
    return {
        "ok": True,
        "item_uid": eq.id,
        "item": eq,
        "crystal_id": crystal_id,
        "returned_crystal_id": prev_cid,
        "message": f"💠 已於【{eq.name}】鑲嵌【{cspec.get('name', crystal_id)}】{swap_note}！",
    }


def unsocket_equipment_crystal(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    item_uid: int,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Remove a socketed Combat Crystal from an owned non-escrowed equipment piece, returning it intact to inventory."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "結晶卸除")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
    if not eq.socket_crystal_id:
        raise GameError(f"裝備【{eq.name}】目前沒有鑲嵌任何結晶。", code="NO_SOCKETED_CRYSTAL")

    prev_cid = eq.socket_crystal_id
    with db.transaction():
        if prev_cid in content.items_crystals:
            db.add_item(user_id, prev_cid, 1)
        eq.socket_crystal_id = ""
        db.update_equipment(eq)
        stats = compute_full_player_stats(db, content, player, now_ts=ts)
        player.combat_power = stats.combat_power
        player.updated_at = ts
        db.save_player(player)

    prev_name = content.items_crystals.get(prev_cid, {}).get("name", prev_cid)
    return {
        "ok": True,
        "item_uid": eq.id,
        "item": eq,
        "returned_crystal_id": prev_cid,
        "message": f"💠 已從【{eq.name}】無損卸除【{prev_name}】並退還至背包！",
    }


def transfer_enhance(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    source_uid: int,
    target_uid: int,
    *,
    include_temper: bool = True,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Transfer enhancement (and optionally temper stars) from an unequipped/unlocked source item to a target item."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "強化繼承轉移")

    if int(source_uid) == int(target_uid):
        raise GameError("來源裝備與目標裝備不可為同一件！", code="SAME_EQUIPMENT_TRANSFER")

    src = db.get_equipment_by_id(user_id, int(source_uid), include_escrowed=True)
    tgt = db.get_equipment_by_id(user_id, int(target_uid), include_escrowed=True)
    if src is None or tgt is None:
        raise GameError("找不到指定的來源或目標裝備。", code="EQUIPMENT_NOT_FOUND")
    if src.is_equipped:
        raise GameError("來源裝備正處於穿戴狀態，請先卸下再進行繼承！", code="CANNOT_TRANSFER_EQUIPPED_SOURCE")
    if src.is_locked:
        raise GameError("來源裝備已鎖定保護，請先解鎖再進行繼承！", code="CANNOT_TRANSFER_LOCKED_SOURCE")
    if src.escrow_state or tgt.escrow_state:
        raise GameError("託管於市集或公會倉庫的裝備無法進行強化繼承！", code="CANNOT_TRANSFER_ESCROWED")

    can_transfer_enh = src.enhance_level > tgt.enhance_level
    can_transfer_tmp = bool(include_temper) and src.temper_level > tgt.temper_level
    if not can_transfer_enh and not can_transfer_tmp:
        raise GameError("來源裝備的強化／鍛星等級並未高於目標裝備，無需繼承！", code="NOTHING_TO_TRANSFER")

    col_cost = max(200, src.enhance_level * 120 + (src.temper_level * 150 if include_temper else 0))
    if player.col < col_cost:
        raise GameError(f"柯爾不足！強化繼承需要 {col_cost} 柯爾（目前 {player.col}）。", code="INSUFFICIENT_COL")

    with db.transaction():
        player.col -= col_cost
        if can_transfer_enh:
            tgt.enhance_level = min(MAX_ENHANCE_LEVEL, src.enhance_level)
            src.enhance_level = 0
            src.enhance_pity = 0
        if can_transfer_tmp:
            tgt.temper_level = min(MAX_TEMPER_LEVEL, src.temper_level)
            src.temper_level = 0
        db.update_equipment(src)
        db.update_equipment(tgt)
        stats = compute_full_player_stats(db, content, player, now_ts=ts)
        player.combat_power = stats.combat_power
        player.updated_at = ts
        db.save_player(player)

    return {
        "ok": True,
        "source_item": src,
        "target_item": tgt,
        "col_spent": col_cost,
        "message": (
            f"🔄 強化繼承完成！已將【{src.name}】的強化／鍛星完整轉移至【{tgt.name}】"
            f"（目標現為 +{tgt.enhance_level} ★{tgt.temper_level}，花費 {col_cost} 柯爾）！"
        ),
    }


def auto_equip_best(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Automatically equip the highest-power owned equipment across all 8 SAO slots respecting weapon style."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.in_boss_battle or (user_id in active_combats and not active_combats[user_id].finished):
        raise GameError("戰鬥或頭目戰中無法一鍵更換裝備！", code="EQUIP_BLOCKED_IN_COMBAT")

    stats_before = compute_full_player_stats(db, content, player, now_ts=ts)
    cp_before = stats_before.combat_power

    all_gear = db.get_equipment(user_id, equipped_only=False, include_escrowed=False)
    style = str(player.weapon_style or "sword").lower()
    pref_wstyle = "sword" if style == "dual_blades" else ("holy" if style == "holy_sword" else style)

    def _slot_score(eq: EquipmentItem) -> tuple[float, int, int]:
        base = float(eq.power_score)
        if eq.slot == "weapon" and eq.weapon_style:
            if eq.weapon_style.lower() in (style, pref_wstyle):
                base *= 1.12
        elif eq.slot == "offhand":
            is_sh = _is_shield_item(eq)
            if style in ("dagger", "dual_blades") and not is_sh or style in ("mace", "holy", "holy_sword") and is_sh:
                base *= 1.15
        return (base, eq.power_score, eq.id)

    changed_count = 0
    equipped_by_slot: dict[str, EquipmentItem] = {}
    for slot in SAO_SLOT_ORDER:
        candidates = [eq for eq in all_gear if eq.slot == slot]
        if not candidates:
            continue
        best = max(candidates, key=_slot_score)
        if not best.is_equipped:
            updated = db.equip_item(user_id, best.id)
            if updated is not None:
                changed_count += 1
                equipped_by_slot[slot] = updated
            else:
                equipped_by_slot[slot] = best
        else:
            equipped_by_slot[slot] = best

    stats_after = compute_full_player_stats(db, content, player, now_ts=ts)
    player.combat_power = stats_after.combat_power
    player.updated_at = ts
    db.save_player(player)
    diff = stats_after.combat_power - cp_before
    diff_str = f"{diff:+d}" if diff != 0 else "±0"
    msg = (
        f"⚡ 一鍵裝備最強完成！共更換 {changed_count} 件裝備，戰力 {cp_before} → {stats_after.combat_power}（{diff_str}）！"
        if changed_count > 0
        else f"⚡ 目前已穿戴各欄位最強裝備（戰力 {stats_after.combat_power}）！"
    )
    return {
        "ok": True,
        "equipped": equipped_by_slot,
        "changed_count": changed_count,
        "combat_power_before": cp_before,
        "combat_power_after": stats_after.combat_power,
        "stats": stats_after,
        "message": msg,
    }


def open_supply_crate(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    crate_item_id: str,
    *,
    slot: str | None = None,
    now_ts: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Open an Equipment Supply Crate (`gear_supply_crate_t1..t3`) with optional slot targeting."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.zone == "boss_room":
        raise GameError("頭目戰中禁止開啟裝備補給箱，請於戰鬥結束後再開啟！", code="BOSS_COMBAT_LOCKED")

    spec = content.items_crystals.get(crate_item_id)
    if not isinstance(spec, dict) or spec.get("category") != "supply_crate":
        raise GameError(f"無效的裝備補給箱：{crate_item_id}", code="INVALID_SUPPLY_CRATE")

    chosen_slot: str | None = None
    if slot is not None and str(slot).strip():
        chosen_slot = str(slot).strip().lower()
        if chosen_slot not in SAO_SLOT_ORDER:
            raise GameError(f"無效的指定裝備欄位：{slot}", code="INVALID_SLOT")

    if db.get_item_qty(user_id, crate_item_id) <= 0:
        raise GameError(f"背包中缺少【{spec.get('name', crate_item_id)}】！", code="INSUFFICIENT_MATERIALS")

    if not db.consume_items(user_id, {crate_item_id: 1}):
        raise GameError("補給箱消耗失敗！", code="INSUFFICIENT_MATERIALS")

    eff = spec.get("effect") or {}
    min_rarity = str(eff.get("crate_min_rarity", Rarity.FINE)).lower()
    tier_cap = int(eff.get("crate_tier_cap", 4))
    set_chance = float(eff.get("crate_set_chance", 0.25))
    rgen = random.Random(rng_seed) if rng_seed is not None else random.Random(ts + player.col + tier_cap)

    floor = min(tier_cap * 10, max(1, player.max_unlocked_floor, player.current_floor))
    roll = rgen.random()
    if min_rarity == Rarity.SET:
        rarity = Rarity.LEGENDARY if roll < 0.28 else Rarity.SET
    elif min_rarity == Rarity.RARE:
        rarity = Rarity.LEGENDARY if roll < 0.12 else (Rarity.SET if roll < 0.12 + set_chance else Rarity.RARE)
    else:
        rarity = Rarity.SET if roll < set_chance else (Rarity.RARE if roll < set_chance + 0.35 else Rarity.FINE)

    eq = generate_equipment_item(
        user_id,
        floor,
        content,
        rarity=rarity,
        slot=chosen_slot,
        weapon_style=player.weapon_style,
        now_ts=ts,
        rng=rgen,
    )
    grant = grant_or_queue_equipment(db, player, eq, source=f"裝備補給箱({crate_item_id})", now_ts=ts, apply_filter=False)
    return {
        "ok": True,
        "crate_item_id": crate_item_id,
        "equipment_result": grant,
        "item_uid": grant.get("item_uid"),
        "item": grant.get("item"),
        "message": f"🎁 開啟【{spec.get('name', crate_item_id)}】獲得裝備【{eq.name}】（T{eq.tier}／{eq.slot}）！",
    }


def buy_shop_equipment(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    *,
    slot: str = "weapon",
    tier: int | None = None,
    now_ts: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Purchase a floor-tier equipment piece directly from the Town Weapon/Armor Shop for Col."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "商店購買裝備")

    chosen_slot = str(slot or "weapon").strip().lower()
    if chosen_slot not in SAO_SLOT_ORDER:
        raise GameError(f"無效的裝備欄位：{slot}", code="INVALID_SLOT")

    max_tier = _tier_for_floor(player.max_unlocked_floor)
    if tier is None:
        target_tier = _tier_for_floor(player.current_floor)
    else:
        if isinstance(tier, bool) or not isinstance(tier, int) or not (1 <= tier <= 10):
            raise GameError(f"無效的裝備階級：{tier}（必須為 1～10）", code="INVALID_TIER")
        if tier > max_tier:
            raise GameError(
                f"尚未解鎖 T{tier} 樓層商會裝備（目前最高可購買 T{max_tier}）！",
                code="TIER_LOCKED",
            )
        target_tier = tier

    col_cost = round(350 * (1.7 ** (target_tier - 1)))
    if player.col < col_cost:
        raise GameError(
            f"柯爾不足！購買 T{target_tier} 商會裝備（{chosen_slot}）需要 {col_cost} 柯爾（目前 {player.col}）。",
            code="INSUFFICIENT_COL",
        )

    rgen = random.Random(rng_seed) if rng_seed is not None else random.Random(ts + player.col + target_tier)
    roll = rgen.random()
    rarity = Rarity.SET if roll < 0.12 else (Rarity.RARE if roll < 0.48 else Rarity.FINE)
    floor = min(100, (target_tier - 1) * 10 + 5)

    with db.transaction():
        player.col -= col_cost
        player.updated_at = ts
        db.save_player(player)

    eq = generate_equipment_item(
        user_id,
        floor,
        content,
        rarity=rarity,
        slot=chosen_slot,
        weapon_style=player.weapon_style,
        now_ts=ts,
        rng=rgen,
    )
    grant = grant_or_queue_equipment(db, player, eq, source=f"城鎮裝備商會(T{target_tier})", now_ts=ts, apply_filter=False)
    return {
        "ok": True,
        "equipment_result": grant,
        "item_uid": grant.get("item_uid"),
        "item": grant.get("item"),
        "col_spent": col_cost,
        "col_remaining": player.col,
        "message": f"🛡️ 花費 {col_cost} 柯爾向城鎮武器防具商購入【{eq.name}】（T{eq.tier}／{eq.slot}）！",
    }
