"""SAO Economy & Workshop System: Equipment, Loadouts, Loot Filter, Forge, Enhance, Magic Stones, Fusion, Cooking, Big Pot Stew, Shop & Gacha (ZERO discord imports)."""

from __future__ import annotations

import random
import time
from typing import Any

from src.rpg.content.loader import SAOContentBundle
from src.rpg.database import RPGDatabase
from src.rpg.models import (
    SAO_RARITY_ORDER,
    SAO_SLOT_ORDER,
    CombatSession,
    GameError,
    PlayerProfile,
    Rarity,
    ZoneType,
)
from src.rpg.systems.combat import compute_full_player_stats
from src.rpg.systems.tower import (
    generate_equipment_item,
    generate_named_equipment,
    grant_or_queue_equipment,
)


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
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Lisbeth Workshop Blacksmithing (`鍛造`): atomic material/Col validation & mastery EXP."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "工坊鍛造")

    recipes = content.recipes.get("blacksmithing", {})
    rec = recipes.get(recipe_id)
    if not isinstance(rec, dict):
        raise GameError(f"未知的鍛造配方：{recipe_id}", code="UNKNOWN_RECIPE")

    col_cost = int(rec.get("col_cost", 100))
    ingredients = {str(k): int(v) for k, v in (rec.get("ingredients") or {}).items()}

    if player.col < col_cost:
        raise GameError(f"柯爾不足！鍛造【{rec['name']}】需要 {col_cost} 柯爾（目前 {player.col}）。", code="INSUFFICIENT_COL")
    for iid, qty in ingredients.items():
        if db.get_item_qty(user_id, iid) < qty:
            iname = content.items_crystals.get(iid, {}).get("name", iid)
            raise GameError(f"鍛造素材不足！缺少【{iname}】x{qty}。", code="INSUFFICIENT_MATERIALS")

    # Atomic consumption after full validation
    with db.transaction():
        if ingredients and not db.consume_items(user_id, ingredients):
            raise GameError("鍛造素材扣除失敗！", code="INSUFFICIENT_MATERIALS")
        player.col -= col_cost
        player.updated_at = ts
        db.save_player(player)

    out_type = str(rec.get("output_type", "tiered_gear"))
    if out_type == "named_item":
        named_id = str(rec["output_named_id"])
        item = generate_named_equipment(user_id, named_id, content, now_ts=ts)
    else:
        tier = int(rec.get("output_tier", 1))
        floor = max(1, (tier - 1) * 10 + 5)
        item = generate_equipment_item(
            user_id,
            floor,
            content,
            rarity=Rarity.RARE if tier >= 3 else Rarity.FINE,
            weapon_style=player.weapon_style,
            now_ts=ts,
            rng=random.Random(ts + tier),
        )

    grant = grant_or_queue_equipment(db, player, item, source=f"工坊鍛造({recipe_id})", now_ts=ts, apply_filter=False)
    lv, _ = _level_mastery(db, user_id, "blacksmithing", int(rec.get("mastery_exp", 20)))
    return {
        "ok": True,
        "recipe_id": recipe_id,
        "col_spent": col_cost,
        "blacksmithing_level": lv,
        "equipment_result": grant,
        "item_uid": grant.get("item_uid"),
        "item": grant.get("item"),
        "message": f"🔨 莉茲貝特工坊鍛造成功！打造出【{item.name}】（鍛造熟練度 Lv.{lv}）！",
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
    """Enhance equipment from +0 up to +15 with Bright/Dark Crystals, Blessing Pity & Protection Talisman."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "裝備強化")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到欲強化的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
    if eq.enhance_level >= 15:
        raise GameError(f"裝備【{eq.name}】已達最高強化等級 +15！", code="MAX_ENHANCE_REACHED")

    next_lv = eq.enhance_level + 1
    etable = content.weapons_equipment.get("enhance_table", {})
    step = etable.get(str(next_lv))
    if not isinstance(step, dict):
        raise GameError(f"找不到強化等級 +{next_lv} 設定。", code="INVALID_ENHANCE_STEP")

    col_cost = int(step.get("col", 200))
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
    pity_triggered = eq.enhance_pity >= 100
    success = pity_triggered or (rgen.random() < base_rate)
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
    if eq.enhance_level >= 10:
        db.unlock_achievement(user_id, "sao_ach_enhance_10", ts)
    if eq.enhance_level >= 15:
        db.unlock_achievement(user_id, "sao_ach_enhance_15", ts)

    return {
        "ok": True,
        "item_uid": eq.id,
        "success": success,
        "pity_triggered": pity_triggered,
        "downgraded": downgraded,
        "protected": use_protection and not success,
        "enhance_level": eq.enhance_level,
        "enhance_pity": eq.enhance_pity,
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
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Apply Magic Stone (`翻石`/`替石`/`毛石`) on non-Named gear (STRICTLY forbidden on Named gear)."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(player, "魔石洗詞綴")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到欲使用魔石的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
    if eq.is_named or eq.rarity == Rarity.NAMED:
        raise GameError("名品裝備（Named）擁有固定傳說詞綴，禁止使用魔石洗煉！", code="NAMED_GEAR_NO_MAGIC_STONE")

    st_spec = content.items_crystals.get(stone_id)
    if not isinstance(st_spec, dict) or st_spec.get("category") != "magic_stone":
        raise GameError(f"無效的魔石種類：{stone_id}", code="INVALID_MAGIC_STONE")
    if db.get_item_qty(user_id, stone_id) <= 0:
        raise GameError(f"背包中缺少【{st_spec.get('name', stone_id)}】！", code="INSUFFICIENT_MATERIALS")

    db.consume_items(user_id, {stone_id: 1})
    rgen = random.Random(rng_seed) if rng_seed is not None else random.Random()
    affix_pool = content.chests_loot.get("affix_pool", {})
    pool_keys = list(affix_pool.keys())
    old_affixes = dict(eq.affixes)
    tier_mult = 1.0 + (eq.tier - 1) * 0.08

    if stone_id == "reroll_stone" or not eq.affixes:
        # 翻石: reroll all affixes
        count = max(1, len(eq.affixes) or 2)
        picked = rgen.sample(pool_keys, k=min(count, len(pool_keys)))
        new_affixes = {}
        for ak in picked:
            lo, hi = affix_pool[ak].get("base_range", [0.02, 0.06])
            new_affixes[ak] = round(rgen.uniform(float(lo), float(hi)) * tier_mult, 4)
        eq.affixes = new_affixes
    elif stone_id == "swap_stone":
        # 替石: replace 1 affix with a fresh different affix
        new_affixes = dict(eq.affixes)
        drop_k = next(iter(new_affixes.keys()))
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
        "message": f"💎 已對【{eq.name}】使用【{st_spec.get('name', stone_id)}】，詞綴重鑄完成！",
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
) -> dict[str, Any]:
    """Deterministic Aincrad Relic Chest gacha with pity guarantee."""
    ts = _now(now_ts)
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0 or count > 10:
        raise GameError("抽獎次數必須介於 1～10 之間。", code="INVALID_GACHA_COUNT")

    ctype = str(chest_type or "standard").strip().lower()
    if ctype not in ("standard", "relic", "premium"):
        raise GameError(f"不支援的秘寶箱類型：{chest_type}", code="INVALID_CHEST_TYPE")

    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    unit_col = 500 if ctype == "standard" else 1200
    total_cost = unit_col * count
    if player.col < total_cost:
        raise GameError(f"柯爾不足！開啟 {count} 次秘寶箱需要 {total_cost} 柯爾（目前 {player.col}）。", code="INSUFFICIENT_COL")

    player.col -= total_cost
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
            if ctype != "standard" and roll < 0.22:
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
        grant = grant_or_queue_equipment(db, player, eq, source=f"秘寶箱({ctype})", now_ts=ts, apply_filter=False)
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
    return {
        "ok": True,
        "chest_type": ctype,
        "count": count,
        "total_cost": total_cost,
        "pulls": pulls,
        "items": pulls,
        "granted_uids": granted_uids,
        "pity_legendary": player.gacha_pity_legendary,
        "message": f"🎰 已開啟 {count} 次艾恩葛朗特秘寶箱，獲得 {len(pulls)} 件裝備！",
    }
