"""SAO Progression System: Stats, Talent Trees, Mining, Daily, Story, Quests, Expeditions, Turn-Ins, Rebirth & Endgame (ZERO discord imports)."""

from __future__ import annotations

import random
import time
import zlib
from typing import Any

from src.rpg.content.loader import SAOContentBundle, resolve_floor_config
from src.rpg.database import RPGDatabase
from src.rpg.models import (
    CombatSession,
    CursorColor,
    GameError,
    PlayerProfile,
    Rarity,
    ZoneType,
)
from src.rpg.systems.combat import (
    apply_exp_and_level_up,
    compute_full_player_stats,
    start_floor_boss,
)
from src.rpg.systems.tower import (
    enhance_crystal_for_tier,
    generate_equipment_item,
    grant_or_queue_equipment,
)

VALID_STAT_KEYS: dict[str, str] = {
    "str": "str_stat",
    "str_stat": "str_stat",
    "agi": "agi_stat",
    "agi_stat": "agi_stat",
    "vit": "vit_stat",
    "vit_stat": "vit_stat",
    "dex": "dex_stat",
    "dex_stat": "dex_stat",
    "luk": "luk_stat",
    "luk_stat": "luk_stat",
}
VALID_LEADERBOARD_CATEGORIES: frozenset[str] = frozenset(
    {"floor", "power", "level", "world_boss", "guild", "col", "survival"}
)
MINE_COOLDOWN_SEC = 10
MINE_STAMINA_COST = 5
MAX_STAMINA = 100
STAMINA_REGEN_SEC = 180


def _now(now_ts: int | None) -> int:
    return int(now_ts if now_ts is not None else time.time())


def _refresh_stamina(player: PlayerProfile, ts: int) -> None:
    if player.stamina_updated_at <= 0:
        player.stamina_updated_at = ts
        return
    elapsed = max(0, ts - player.stamina_updated_at)
    gained = elapsed // STAMINA_REGEN_SEC
    if gained > 0:
        player.stamina = min(MAX_STAMINA, player.stamina + int(gained))
        player.stamina_updated_at += int(gained) * STAMINA_REGEN_SEC


def _update_cursor_from_karma(player: PlayerProfile) -> None:
    if player.karma <= -25:
        player.cursor_color = CursorColor.RED
    elif player.karma < 0:
        player.cursor_color = CursorColor.ORANGE
    else:
        player.cursor_color = CursorColor.GREEN


def allocate_stats(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    stat_deltas: dict[str, int],
) -> dict[str, Any]:
    """Allocate unspent STR/AGI/VIT/DEX/LUK stat points (strictly zero magic/int/mana)."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if not isinstance(stat_deltas, dict) or not stat_deltas:
        raise GameError("請提供至少一項欲分配的基礎屬性點數。", code="EMPTY_STAT_DELTAS")

    normalized: dict[str, int] = {}
    total_spend = 0
    for raw_k, raw_v in stat_deltas.items():
        k = str(raw_k).strip().lower()
        if k not in VALID_STAT_KEYS:
            raise GameError(
                f"艾恩葛朗特不存在魔法屬性或無效屬性名稱：{raw_k}（僅限 STR/AGI/VIT/DEX/LUK）。",
                code="INVALID_STAT_NAME",
            )
        if isinstance(raw_v, bool) or not isinstance(raw_v, int) or raw_v <= 0:
            raise GameError(f"屬性配點數值必須為正整數：{raw_k}={raw_v}", code="INVALID_STAT_DELTA")
        attr = VALID_STAT_KEYS[k]
        normalized[attr] = normalized.get(attr, 0) + raw_v
        total_spend += raw_v

    if total_spend > player.stat_points:
        raise GameError(
            f"剩餘屬性點不足！需要 {total_spend} 點，但目前僅剩 {player.stat_points} 點。",
            code="INSUFFICIENT_STAT_POINTS",
        )

    for attr, delta in normalized.items():
        setattr(player, attr, int(getattr(player, attr)) + delta)
    player.stat_points -= total_spend

    stats = compute_full_player_stats(db, content, player)
    player.combat_power = stats.combat_power
    db.save_player(player)
    return {
        "ok": True,
        "allocated": stat_deltas,
        "stat_points": player.stat_points,
        "unspent_stat_points": player.stat_points,
        "str_stat": player.str_stat,
        "agi_stat": player.agi_stat,
        "vit_stat": player.vit_stat,
        "dex_stat": player.dex_stat,
        "luk_stat": player.luk_stat,
        "combat_power": stats.combat_power,
        "stats": stats,
        "message": f"📈 屬性配點完成！已消耗 {total_spend} 點（剩餘 {player.stat_points} 點），目前戰力 {stats.combat_power}。",
    }


def _find_talent_node(content: SAOContentBundle, talent_id: str) -> tuple[str, dict[str, Any], int] | None:
    w_classes = content.weapons_equipment.get("weapon_classes", {})
    for wkey, wspec in w_classes.items():
        tree = list(wspec.get("talent_tree", []))
        for idx, node in enumerate(tree):
            if str(node.get("id")) == talent_id:
                return str(wkey), node, idx
    return None


def allocate_talent(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    talent_id: str,
) -> dict[str, Any]:
    """Allocate 1 talent point into a weapon style's branching talent tree."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.talent_points <= 0:
        raise GameError("目前沒有剩餘的天賦點數！", code="INSUFFICIENT_TALENT_POINTS")

    found = _find_talent_node(content, str(talent_id))
    if found is None:
        raise GameError(f"未知的武器天賦節點：{talent_id}", code="UNKNOWN_TALENT")
    wkey, node, _idx = found

    ranks = db.get_talents(user_id)
    # Enforce prerequisite if specified explicitly in JSON or if tier>0 node requires prerequisite
    prereq = node.get("prerequisite") or node.get("prereq")
    if prereq and int(ranks.get(str(prereq), 0)) <= 0:
        raise GameError(f"前置天賦【{prereq}】尚未點亮，無法學習此天賦！", code="TALENT_PREREQ_LOCKED")

    cur_rank = int(ranks.get(talent_id, 0))
    max_rank = int(node.get("max_rank", 5))
    if cur_rank >= max_rank:
        raise GameError(f"天賦【{node.get('name', talent_id)}】已達上限（{max_rank}/{max_rank}）！", code="TALENT_MAXED")

    new_rank = cur_rank + 1
    db.set_talent_rank(user_id, talent_id, new_rank)
    player.talent_points -= 1
    stats = compute_full_player_stats(db, content, player)
    player.combat_power = stats.combat_power
    db.save_player(player)

    return {
        "ok": True,
        "talent_id": talent_id,
        "weapon_class": wkey,
        "rank": new_rank,
        "max_rank": max_rank,
        "talent_points": player.talent_points,
        "unspent_talent_points": player.talent_points,
        "combat_power": stats.combat_power,
        "stats": stats,
        "message": f"🌟 已強化天賦【{node.get('name', talent_id)}】至 Lv.{new_rank}/{max_rank}（剩餘天賦點 {player.talent_points}）！",
    }


def respec_talents(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
) -> dict[str, Any]:
    """Free Town talent respec (STRICTLY blocked outside Town and mid-Boss battle)."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.in_boss_battle or (user_id in active_combats and not active_combats[user_id].finished):
        raise GameError("頭目戰中不能退點！請結束戰鬥並返回城鎮安全區後再洗點。", code="RESPEC_BLOCKED_IN_BOSS")
    if player.zone != ZoneType.TOWN:
        raise GameError("天賦退點僅能在城鎮安全區（圈內）免費執行！", code="TOWN_ONLY_ACTION")

    refunded = db.clear_talents(user_id)
    player.talent_points += refunded
    stats = compute_full_player_stats(db, content, player)
    player.combat_power = stats.combat_power
    db.save_player(player)
    return {
        "ok": True,
        "refunded_points": refunded,
        "talent_points": player.talent_points,
        "unspent_talent_points": player.talent_points,
        "combat_power": stats.combat_power,
        "message": f"🔄 已於安全區免費重置天賦，退還 {refunded} 點天賦點（目前共有 {player.talent_points} 點）！",
    }


def mine_gather(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
    *,
    floor: int | None = None,
    now_ts: int | None = None,
    rng_seed: int | None = None,
) -> dict[str, Any]:
    """Mine Aincrad mineral veins (e.g. F55 Crystallite Ingot) & level up mining life skill."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.is_dead:
        raise GameError("硬派角色已陣亡，無法進行採集挖礦。", code="HARDCORE_DEAD")
    if player.in_boss_battle or (user_id in active_combats and not active_combats[user_id].finished):
        raise GameError("頭目戰或戰鬥進行中無法採集挖礦！", code="MINING_BLOCKED_IN_COMBAT")

    target_floor = int(floor if floor is not None else player.current_floor)
    if isinstance(target_floor, bool) or not (1 <= target_floor <= 100):
        raise GameError(f"無效的採礦樓層：{target_floor}（必須為 1～100）", code="INVALID_FLOOR")
    if target_floor > player.max_unlocked_floor:
        raise GameError(
            f"第 {target_floor} 層尚未解鎖，無法前往該層礦脈採集！（目前最高可至第 {player.max_unlocked_floor} 層）",
            code="FLOOR_LOCKED",
        )

    _refresh_stamina(player, ts)
    if player.last_mine_at > 0 and (ts - player.last_mine_at) < MINE_COOLDOWN_SEC:
        wait = MINE_COOLDOWN_SEC - (ts - player.last_mine_at)
        raise GameError(f"採礦工具冷卻中，請等待 {wait} 秒後再挖掘！", code="MINE_COOLDOWN")
    if player.stamina < MINE_STAMINA_COST:
        raise GameError(
            f"體力不足！採礦需要 {MINE_STAMINA_COST} 體力（目前 {player.stamina}/{MAX_STAMINA}）。",
            code="INSUFFICIENT_STAMINA",
        )

    fcfg = resolve_floor_config(target_floor, content)
    rgen = random.Random(rng_seed) if rng_seed is not None else random.Random()
    ore_pool = list(fcfg.get("ore_ids") or ["copper_vein_ore"])

    mastery = db.get_mastery(user_id)
    m_info = mastery.get("mining", {"level": 1, "exp": 0})
    m_lv = int(m_info["level"])
    m_exp = int(m_info["exp"]) + 18

    ores_gained: dict[str, int] = {}
    # Floor 55 special iconic Crystallite Ingot vein guarantee
    if target_floor == 55 and "crystallite_ingot" in content.items_crystals:
        ores_gained["crystallite_ingot"] = 1
    primary_ore = rgen.choice(ore_pool)
    bonus_qty = 1 + (1 if m_lv >= 10 and rgen.random() < 0.35 else 0)
    ores_gained[primary_ore] = ores_gained.get(primary_ore, 0) + bonus_qty

    for oid, qty in ores_gained.items():
        db.add_item(user_id, oid, qty)

    while m_exp >= max(25, m_lv * 25):
        m_exp -= max(25, m_lv * 25)
        m_lv += 1
    db.upsert_mastery(user_id, "mining", m_lv, m_exp)

    col_gain = max(15, round(int(fcfg["col_base"]) * 0.8))
    exp_gain = max(8, round(int(fcfg["exp_base"]) * 0.45))
    apply_exp_and_level_up(player, exp_gain)
    player.col += col_gain
    player.stamina = max(0, player.stamina - MINE_STAMINA_COST)
    player.last_mine_at = ts
    player.total_mines += 1
    player.mine_combo += 1
    player.updated_at = ts
    db.save_player(player)

    today_key = time.strftime("%Y-%m-%d", time.gmtime(ts))
    db.increment_quest(user_id, "daily", today_key, "dq_mine_3", 3, delta=1)

    names = ", ".join(
        f"{content.items_crystals.get(oid, {}).get('name', oid)} x{q}" for oid, q in ores_gained.items()
    )
    return {
        "ok": True,
        "floor": target_floor,
        "ores": ores_gained,
        "col_gain": col_gain,
        "exp_gain": exp_gain,
        "stamina": player.stamina,
        "mining_level": m_lv,
        "message": f"⛏️ 在第 {target_floor} 層礦脈採得【{names}】，另獲 {col_gain} 柯爾（採集挖礦 Lv.{m_lv}）！",
    }


def claim_daily(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Daily & 7-Day streak login check-in using injectable UTC `now_ts`."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    today = time.strftime("%Y-%m-%d", time.gmtime(ts))
    if player.last_checkin_date == today:
        raise GameError("今日已完成艾恩葛朗特每日簽到，請明日再來領取！", code="DAILY_ALREADY_CLAIMED")

    yesterday = time.strftime("%Y-%m-%d", time.gmtime(ts - 86400))
    if player.last_checkin_date == yesterday:
        player.checkin_streak = (player.checkin_streak % 7) + 1
    else:
        player.checkin_streak = 1

    day_num = player.checkin_streak
    col_gain = 300 + day_num * 150 + player.current_floor * 20
    exp_gain = 120 + day_num * 60
    items_gained: dict[str, int] = {"hp_potion_t1": 2, "bright_crystal_shard": 2}
    if day_num == 3:
        items_gained["teleport_crystal"] = 1
    elif day_num == 5:
        items_gained["healing_crystal"] = 1
    elif day_num == 7:
        items_gained["gacha_relic_ticket"] = 1
        items_gained["protection_talisman"] = 1

    for iid, qty in items_gained.items():
        if iid in content.items_crystals:
            db.add_item(user_id, iid, qty)

    apply_exp_and_level_up(player, exp_gain)
    player.col += col_gain
    player.last_checkin_date = today
    player.total_checkins += 1
    player.updated_at = ts
    db.save_player(player)

    return {
        "ok": True,
        "date": today,
        "streak": day_num,
        "total_checkins": player.total_checkins,
        "col_gain": col_gain,
        "exp_gain": exp_gain,
        "items": items_gained,
        "message": f"📅 艾恩葛朗特第 {day_num}/7 天簽到成功！獲得 {col_gain} 柯爾、{exp_gain} EXP 與補給水晶道具！",
    }


def get_quests(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Return Main Story chapters, Floor Bounties, Daily Quests, and Weekly Quests with live progress."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    today = time.strftime("%Y-%m-%d", time.gmtime(ts))
    week = time.strftime("%Y-W%W", time.gmtime(ts))
    tier = max(1, min(10, (player.current_floor - 1) // 10 + 1))

    daily_state = db.get_quests(user_id, "daily", today)
    weekly_state = db.get_quests(user_id, "weekly", week)
    bounty_cache: dict[int, dict[str, Any]] = {}

    daily_list = []
    for q in content.quests_events.get("daily_quests", []):
        qid = str(q["id"])
        st = daily_state.get(qid, {"progress": 0, "target": int(q["target"]), "claimed": False})
        daily_list.append({**q, **st})

    weekly_list = []
    for q in content.quests_events.get("weekly_quests", []):
        qid = str(q["id"])
        st = weekly_state.get(qid, {"progress": 0, "target": int(q["target"]), "claimed": False})
        weekly_list.append({**q, **st})

    bounty_list = []
    for q in content.quests_events.get("bounties", []):
        qid = str(q["id"])
        q_tier = int(q.get("tier", tier))
        if q_tier not in bounty_cache:
            bounty_cache[q_tier] = db.get_quests(user_id, "bounty", f"tier_{q_tier}")
        st = bounty_cache[q_tier].get(qid, {"progress": 0, "target": int(q["target"]), "claimed": False})
        bounty_list.append({**q, **st})

    story_list = []
    for cid, ch in content.quests_events.get("story", {}).items():
        chosen = (player.story_choices or {}).get(cid)
        story_list.append({**ch, "chosen_option": chosen, "completed": chosen is not None})

    return {
        "ok": True,
        "story": story_list,
        "daily": daily_list,
        "weekly": weekly_list,
        "bounties": bounty_list,
        "message": f"📋 已載入主線劇情（{len(story_list)} 章）、每日／每週任務與第 {tier} 階段樓層懸賞。",
    }


def choose_story_option(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    chapter_id: str,
    choice_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Make a branching Main Story choice updating Color Cursor (`光標顏色`) & Karma."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    story = content.quests_events.get("story", {})
    chapter = story.get(chapter_id)
    if not isinstance(chapter, dict):
        raise GameError(f"未知的主線劇情章節：{chapter_id}", code="UNKNOWN_STORY_CHAPTER")

    choices = {str(c["id"]): c for c in chapter.get("choices", []) if isinstance(c, dict)}
    choice = choices.get(choice_id)
    if choice is None:
        raise GameError(f"章節【{chapter.get('title', chapter_id)}】不存在選項：{choice_id}", code="UNKNOWN_STORY_CHOICE")

    if chapter_id in (player.story_choices or {}):
        raise GameError(f"你已完成主線章節【{chapter.get('title', chapter_id)}】的抉擇！", code="STORY_ALREADY_CHOSEN")

    cursor_delta = int(choice.get("cursor_delta", 0))
    # Clamp karma cleanly to [-100, 100]
    player.karma = max(-100, min(100, player.karma + cursor_delta))
    _update_cursor_from_karma(player)

    col_gain = int(choice.get("reward_col", 300))
    exp_gain = int(choice.get("reward_exp", 150))
    apply_exp_and_level_up(player, exp_gain)
    player.col += col_gain
    for iid, qty in (choice.get("reward_items") or {}).items():
        if iid in content.items_crystals:
            db.add_item(user_id, str(iid), int(qty))

    choices_map = dict(player.story_choices or {})
    choices_map[chapter_id] = choice_id
    player.story_choices = choices_map
    player.updated_at = ts
    db.save_player(player)

    return {
        "ok": True,
        "chapter_id": chapter_id,
        "choice_id": choice_id,
        "karma": player.karma,
        "cursor_color": player.cursor_color,
        "col_gain": col_gain,
        "exp_gain": exp_gain,
        "message": (
            f"📖 【{chapter.get('title', chapter_id)}】完成抉擇！業力 {player.karma:+d}（光標顏色：{player.cursor_color}），"
            f"獲得 {col_gain} 柯爾與 {exp_gain} EXP！"
        ),
    }


def claim_quest(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    quest_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Claim rewards for a completed Daily, Weekly, or Floor Bounty quest."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    today = time.strftime("%Y-%m-%d", time.gmtime(ts))
    week = time.strftime("%Y-W%W", time.gmtime(ts))
    tier = max(1, min(10, (player.current_floor - 1) // 10 + 1))

    qspec: dict[str, Any] | None = None
    period_type = ""
    period_key = ""
    for q in content.quests_events.get("daily_quests", []):
        if str(q["id"]) == quest_id:
            qspec, period_type, period_key = q, "daily", today
            break
    if qspec is None:
        for q in content.quests_events.get("weekly_quests", []):
            if str(q["id"]) == quest_id:
                qspec, period_type, period_key = q, "weekly", week
                break
    if qspec is None:
        for q in content.quests_events.get("bounties", []):
            if str(q["id"]) == quest_id:
                qspec, period_type, period_key = q, "bounty", f"tier_{q.get('tier', tier)}"
                break
    if qspec is None:
        raise GameError(f"找不到指定的任務編號：{quest_id}", code="UNKNOWN_QUEST")

    qmap = db.get_quests(user_id, period_type, period_key)
    state = qmap.get(quest_id)
    target = int(qspec.get("target", 1))
    if not state or int(state.get("progress", 0)) < target:
        cur_p = int(state.get("progress", 0)) if state else 0
        raise GameError(
            f"任務【{qspec.get('name', quest_id)}】尚未完成（目前進度 {cur_p}/{target}）！",
            code="QUEST_NOT_COMPLETED",
        )
    if state.get("claimed"):
        raise GameError(f"任務【{qspec.get('name', quest_id)}】獎勵已經領取過了！", code="QUEST_ALREADY_CLAIMED")

    db.mark_quest_claimed(user_id, period_type, period_key, quest_id)
    col_gain = int(qspec.get("reward_col", 300))
    exp_gain = int(qspec.get("reward_exp", 150))
    apply_exp_and_level_up(player, exp_gain)
    player.col += col_gain
    items_gained: dict[str, int] = {}
    for iid, qty in (qspec.get("reward_items") or {}).items():
        if iid in content.items_crystals:
            db.add_item(user_id, str(iid), int(qty))
            items_gained[str(iid)] = int(qty)

    player.updated_at = ts
    db.save_player(player)
    return {
        "ok": True,
        "quest_id": quest_id,
        "col_gain": col_gain,
        "exp_gain": exp_gain,
        "items": items_gained,
        "message": f"🎁 已領取任務【{qspec.get('name', quest_id)}】獎勵：{col_gain} 柯爾、{exp_gain} EXP！",
    }


def start_expedition(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    expedition_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Dispatch a timestamped offline Aincrad expedition (persists across bot restarts)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.is_dead:
        raise GameError("硬派角色已陣亡，無法派遣遠征。", code="HARDCORE_DEAD")

    existing = db.get_expedition(user_id)
    if existing is not None and not existing.claimed:
        raise GameError("你目前已有一支遠征隊正在執行任務，請先領取完成後再重新派遣！", code="EXPEDITION_ALREADY_ACTIVE")

    espec = next(
        (e for e in content.quests_events.get("expeditions", []) if str(e.get("id")) == expedition_id),
        None,
    )
    if espec is None:
        raise GameError(f"未知的遠征路線：{expedition_id}", code="UNKNOWN_EXPEDITION")

    min_floor = int(espec.get("min_floor", 1))
    if player.max_unlocked_floor < min_floor:
        raise GameError(
            f"遠征【{espec.get('name', expedition_id)}】需先解鎖第 {min_floor} 層！",
            code="FLOOR_LOCKED",
        )

    duration = max(60, int(espec.get("duration_sec", 1800)))
    ends_at = ts + duration
    db.set_expedition(user_id, expedition_id, ts, ends_at)
    return {
        "ok": True,
        "expedition_id": expedition_id,
        "name": str(espec.get("name", expedition_id)),
        "started_at": ts,
        "ends_at": ends_at,
        "duration_sec": duration,
        "message": f"🗺️ 已派遣偵查小隊執行【{espec.get('name', expedition_id)}】（預計 {duration // 60} 分鐘後歸隊）！",
    }


def claim_expedition(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Claim completed offline expedition rewards once `now_ts >= ends_at`."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    exp_rec = db.get_expedition(user_id)
    if exp_rec is None or exp_rec.claimed:
        raise GameError("目前沒有可領取的離線遠征任務。", code="NO_ACTIVE_EXPEDITION")
    if ts < exp_rec.ends_at:
        rem = exp_rec.ends_at - ts
        raise GameError(f"遠征隊尚未歸返，還需等待 {rem} 秒！", code="EXPEDITION_NOT_READY")

    espec = next(
        (e for e in content.quests_events.get("expeditions", []) if str(e.get("id")) == exp_rec.expedition_id),
        None,
    )
    rgen = random.Random(exp_rec.started_at + zlib.crc32(str(user_id).encode("utf-8")) % 997)
    if espec is not None:
        cmin, cmax = espec.get("col_range", [300, 600])
        emin, emax = espec.get("exp_range", [120, 240])
        ore_pool = list(espec.get("ore_pool") or ["copper_vein_ore"])
        ename = str(espec.get("name", exp_rec.expedition_id))
        exp_floor = max(1, int(espec.get("min_floor", player.current_floor)))
    else:
        # Support legacy v1 migrated expeditions cleanly
        cmin, cmax = 350, 650
        emin, emax = 150, 280
        ore_pool = ["copper_vein_ore", "iron_vein_ore"]
        ename = exp_rec.expedition_id
        exp_floor = max(1, player.current_floor)

    col_gain = rgen.randint(int(cmin), int(cmax))
    exp_gain = rgen.randint(int(emin), int(emax))
    ore_id = rgen.choice(ore_pool)
    ore_qty = rgen.randint(2, 4)

    db.clear_expedition(user_id)
    items_gained: dict[str, int] = {ore_id: ore_qty}
    db.add_item(user_id, ore_id, ore_qty)
    tier = max(1, min(10, (exp_floor - 1) // 10 + 1))
    crys_id = enhance_crystal_for_tier(tier)
    if crys_id in content.items_crystals:
        crys_qty = 1 + (1 if exp_floor >= 45 else 0)
        db.add_item(user_id, crys_id, crys_qty)
        items_gained[crys_id] = items_gained.get(crys_id, 0) + crys_qty

    apply_exp_and_level_up(player, exp_gain)
    player.col += col_gain
    player.updated_at = ts
    db.save_player(player)

    # 45%–100% tier-scaled equipment drop on offline expedition completion!
    equipment_drops: list[dict[str, Any]] = []
    drop_chance = min(1.0, 0.45 + (tier - 1) * 0.08)
    if rgen.random() < drop_chance:
        roll = rgen.random()
        if exp_floor >= 80:
            ex_rarity = Rarity.LEGENDARY if roll < 0.25 else (Rarity.SET if roll < 0.70 else Rarity.RARE)
        elif exp_floor >= 45:
            ex_rarity = Rarity.SET if roll < 0.35 else (Rarity.RARE if roll < 0.80 else Rarity.FINE)
        else:
            ex_rarity = Rarity.RARE if roll < 0.35 else Rarity.FINE
        eq = generate_equipment_item(
            user_id,
            max(exp_floor, player.current_floor),
            content,
            rarity=ex_rarity,
            weapon_style=player.weapon_style,
            now_ts=ts,
            rng=rgen,
        )
        equipment_drops.append(
            grant_or_queue_equipment(db, player, eq, source=f"離線遠征({ename})", now_ts=ts, apply_filter=True)
        )

    gear_note = f"、裝備【{equipment_drops[0]['item_name']}】" if equipment_drops else ""
    return {
        "ok": True,
        "expedition_id": exp_rec.expedition_id,
        "col_gain": col_gain,
        "exp_gain": exp_gain,
        "items": items_gained,
        "equipment_drops": equipment_drops,
        "message": f"🏕️ 遠征【{ename}】凱旋歸來！獲得 {col_gain} 柯爾、{exp_gain} EXP、礦材 {ore_id} x{ore_qty}{gear_note}！",
    }


def turn_in_achievement_gear(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    item_uid: int,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Turn in spare unequipped unlocked equipment for permanent Achievement Turn-In (`成就上繳`) buffs."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=True)
    if eq is None:
        raise GameError(f"找不到欲上繳的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
    if eq.is_equipped:
        raise GameError("裝備中物品無法進行成就上繳，請先卸下裝備！", code="CANNOT_TURNIN_EQUIPPED")
    if eq.is_locked:
        raise GameError("已鎖定的裝備受保護無法上繳，請先解鎖！", code="CANNOT_TURNIN_LOCKED")
    if eq.escrow_state:
        raise GameError("託管於市集或公會倉庫的裝備無法上繳！", code="CANNOT_TURNIN_ESCROWED")

    tcfg = content.quests_events.get("turnins", {})
    rpoints = tcfg.get("rarity_points", {})
    pts = int(rpoints.get(eq.rarity, 1))
    turnin_key = f"{eq.template_id}_{eq.id}"

    db.delete_equipment(user_id, [eq.id])
    db.record_achievement_turnin(
        user_id,
        turnin_key=turnin_key,
        item_name=eq.name,
        rarity=eq.rarity,
        bonus={"points": float(pts)},
        now_ts=ts,
    )
    all_turnins = db.get_achievement_turnins(user_id)
    total_pts = sum(int(rpoints.get(str(t.get("rarity", "plain")), 1)) for t in all_turnins)

    stats = compute_full_player_stats(db, content, player, now_ts=ts)
    player.combat_power = stats.combat_power
    player.updated_at = ts
    db.save_player(player)
    return {
        "ok": True,
        "item_uid": eq.id,
        "item_name": eq.name,
        "points_gained": pts,
        "total_points": total_pts,
        "combat_power": stats.combat_power,
        "stats": stats,
        "message": f"🏛️ 已將【{eq.name}】上繳至艾恩葛朗特成就殿堂（+{pts} 點，累計 {total_pts} 收藏點），永久屬性已更新！",
    }


def _check_achievement_condition(
    db: RPGDatabase, player: PlayerProfile, ach_id: str
) -> bool:
    unlocked = db.get_achievements(player.user_id)
    if ach_id in unlocked:
        return True
    floor_req = {
        "sao_ach_f01": 1,
        "sao_ach_f10": 10,
        "sao_ach_f25": 25,
        "sao_ach_f50": 50,
        "sao_ach_f74": 74,
        "sao_ach_f75": 75,
        "sao_ach_f100": 100,
    }
    if ach_id in floor_req:
        return player.highest_cleared_floor >= floor_req[ach_id]
    if ach_id == "sao_ach_dual_blades":
        return "dual_blades" in player.unique_skills
    if ach_id == "sao_ach_holy_sword":
        return "holy_sword" in player.unique_skills
    if ach_id == "sao_ach_enhance_10":
        return db.get_max_enhance_level(player.user_id) >= 10
    if ach_id == "sao_ach_enhance_15":
        return db.get_max_enhance_level(player.user_id) >= 15
    if ach_id == "sao_ach_forge_master":
        m = db.get_mastery(player.user_id)
        return int(m.get("blacksmithing", {}).get("level", 1)) >= 40 or db.get_max_enhance_level(player.user_id) >= 15
    if ach_id == "sao_ach_cook_master":
        m = db.get_mastery(player.user_id)
        return int(m.get("cooking", {}).get("level", 1)) >= 40
    if ach_id in ("sao_ach_guild", "sao_ach_guild_leader"):
        return player.guild_id is not None
    if ach_id == "sao_ach_rebirth":
        return player.rebirth_count >= 1
    if ach_id == "sao_ach_mine_50":
        return player.total_mines >= 50
    if ach_id in ("sao_ach_roguelike", "sao_ach_roguelike_boss"):
        return player.roguelike_best_score >= 180
    if ach_id == "sao_ach_turnin":
        return len(db.get_achievement_turnins(player.user_id)) >= 1
    if ach_id == "sao_ach_first_step":
        return True
    # Any first-tier starter achievement if player cleared at least 1 floor or created char
    return bool("start" in ach_id or "link" in ach_id or "first" in ach_id)


def claim_achievement(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    achievement_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Unlock and claim an earned SAO Achievement and its Title."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    ach = next(
        (a for a in content.quests_events.get("achievements", []) if str(a.get("id")) == achievement_id),
        None,
    )
    if ach is None:
        raise GameError(f"找不到指定的成就編號：{achievement_id}", code="UNKNOWN_ACHIEVEMENT")

    if not _check_achievement_condition(db, player, achievement_id):
        raise GameError(
            f"尚未達成成就【{ach.get('name', achievement_id)}】的條件：{ach.get('desc', '')}",
            code="ACHIEVEMENT_NOT_UNLOCKED",
        )

    newly = db.unlock_achievement(user_id, achievement_id, ts)
    col_gain = int(ach.get("reward_col", 500)) if newly else 0
    if col_gain > 0:
        player.col += col_gain
    for iid, qty in (ach.get("reward_items") or {}).items():
        if newly and iid in content.items_crystals:
            db.add_item(user_id, str(iid), int(qty))

    title_id = str(ach.get("title_id") or "")
    stats = compute_full_player_stats(db, content, player, now_ts=ts)
    player.combat_power = stats.combat_power
    player.updated_at = ts
    db.save_player(player)
    return {
        "ok": True,
        "achievement_id": achievement_id,
        "name": str(ach.get("name", achievement_id)),
        "title_id": title_id,
        "newly_claimed": newly,
        "col_gain": col_gain,
        "combat_power": stats.combat_power,
        "message": f"🏅 成就【{ach.get('name', achievement_id)}】已領取！解鎖稱號：{title_id or '無'}。",
    }


def _unlocked_titles_for_player(
    db: RPGDatabase, content: SAOContentBundle, player: PlayerProfile
) -> set[str]:
    titles: set[str] = set()
    unlocked_ach = db.get_achievements(player.user_id)
    for ach in content.quests_events.get("achievements", []):
        if str(ach.get("id")) in unlocked_ach and ach.get("title_id"):
            titles.add(str(ach["title_id"]))
    # Also grant milestone titles cleanly if floor already cleared
    if player.highest_cleared_floor >= 1:
        titles.add("kobold_slayer")
    if player.highest_cleared_floor >= 10:
        titles.add("samurai_breaker")
    if player.highest_cleared_floor >= 25:
        titles.add("clearer")
    if player.highest_cleared_floor >= 50:
        titles.add("algade_vanguard_title")
    if player.highest_cleared_floor >= 74:
        titles.add("black_swordsman")
    if player.highest_cleared_floor >= 100:
        titles.add("aincrad_liberator")
    if "dual_blades" in player.unique_skills:
        titles.add("dual_blade_master")
    if "holy_sword" in player.unique_skills:
        titles.add("blood_oath_paladin")
    return titles


def equip_title(
    db: RPGDatabase,
    content: SAOContentBundle,
    user_id: str,
    title_id: str,
) -> dict[str, Any]:
    """Equip an unlocked SAO Title."""
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")

    all_titles = content.quests_events.get("titles", {})
    if title_id not in all_titles:
        raise GameError(f"未知的稱號編號：{title_id}", code="UNKNOWN_TITLE")

    unlocked = _unlocked_titles_for_player(db, content, player)
    if title_id not in unlocked:
        tname = str(all_titles[title_id].get("name", title_id))
        raise GameError(f"尚未解鎖稱號【{tname}】，無法裝備！", code="TITLE_LOCKED")

    player.active_title = title_id
    db.save_player(player)
    tspec = all_titles[title_id]
    return {
        "ok": True,
        "title_id": title_id,
        "active_title": title_id,
        "title_name": str(tspec.get("name", title_id)),
        "message": f"🏷️ 已裝備稱號【{tspec.get('emoji', '')} {tspec.get('name', title_id)}】！",
    }


def rebirth_player(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
    *,
    confirm: bool = False,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Post-F100 New Game+ Rebirth (`轉生`): preserves Named gear, Titles, Yui logs & Achievement Turn-Ins."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.in_boss_battle or (user_id in active_combats and not active_combats[user_id].finished):
        raise GameError("戰鬥中無法執行轉生！", code="REBIRTH_BLOCKED_IN_COMBAT")
    if player.highest_cleared_floor < 100 and player.level < 100:
        raise GameError(
            f"尚未達成轉生資格！需通關第 100 層或達 Lv.100（目前通關 F{player.highest_cleared_floor}／Lv.{player.level}）。",
            code="REBIRTH_REQUIREMENT_UNMET",
        )

    if not confirm:
        return {
            "ok": True,
            "confirmed": False,
            "rebirth_count": player.rebirth_count,
            "level": player.level,
            "preview_bonus_pct": (player.rebirth_count + 1) * 18,
            "message": (
                f"⚠️ 【二周目轉生確認】轉生將重置等級至 Lv.1 並回到第 1 層，但完整保留所有名品裝備、稱號、結衣終端機與成就上繳永久加成，"
                f"並獲得全屬性 +{(player.rebirth_count + 1) * 18}% 威望倍率！請傳入 confirm=True 執行轉生。"
            ),
        }

    player.rebirth_count += 1
    player.level = 1
    player.exp = 0
    player.current_floor = 1
    player.zone = ZoneType.TOWN
    player.miasma_stacks = 0
    player.miasma_exp_stacks = 0
    player.stat_points += 15 * player.rebirth_count
    player.talent_points += 5
    stats = compute_full_player_stats(db, content, player, floor=1, now_ts=ts)
    player.hp = stats.max_hp
    player.sp = stats.max_sp
    player.max_sp = stats.max_sp
    player.combat_power = stats.combat_power
    player.updated_at = ts
    db.save_player(player)
    db.unlock_achievement(user_id, "sao_ach_rebirth", ts)

    return {
        "ok": True,
        "confirmed": True,
        "rebirth_count": player.rebirth_count,
        "level": player.level,
        "current_floor": player.current_floor,
        "prestige_multiplier": round(1.0 + 0.18 * player.rebirth_count, 2),
        "combat_power": stats.combat_power,
        "message": (
            f"♻️ 【艾恩葛朗特轉生完成！】第 {player.rebirth_count} 次轉生啟動，"
            f"全屬性永久倍率提升至 {1.0 + 0.18 * player.rebirth_count:.2f}x（保留名品、稱號、結衣紀錄與成就上繳）！"
        ),
    }


def start_boss_rush(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Post-F100 Heroic Boss Rush (`頭目連戰`) challenge."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.highest_cleared_floor < 100 and player.rebirth_count <= 0:
        raise GameError("需先通關第 100 層紅玉宮方可解鎖【英雄頭目連戰（Boss Rush）】！", code="BOSS_RUSH_LOCKED")

    res = start_floor_boss(
        db, content, active_combats, user_id, floor=10, mode="normal", now_ts=ts, bypass_cooldown=True
    )
    if user_id in active_combats:
        active_combats[user_id].mode = "boss_rush"
    res["boss_rush"] = True
    res["rush_stage"] = 1
    res["rush_floors"] = [10, 25, 50, 74, 75, 100]
    res["message"] = "🔥 【英雄頭目連戰 Boss Rush 啟動！】第 1 關：第 10 層武士領主・加賀智！"
    return res


def enter_nightmare_floor(
    db: RPGDatabase,
    content: SAOContentBundle,
    active_combats: dict[str, CombatSession],
    user_id: str,
    nightmare_floor: int,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Post-F100 Aincrad Nightmare (`夢魘` F101+) endless scaled challenge."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if isinstance(nightmare_floor, bool) or not isinstance(nightmare_floor, int) or nightmare_floor <= 100:
        raise GameError(f"艾恩葛朗特夢魘樓層必須大於 100（輸入：{nightmare_floor}）！", code="INVALID_NIGHTMARE_FLOOR")
    if player.highest_cleared_floor < 100 and player.rebirth_count <= 0:
        raise GameError("需先通關第 100 層紅玉宮方可進入【艾恩葛朗特夢魘 F101+】！", code="NIGHTMARE_LOCKED")

    if user_id in active_combats and active_combats[user_id].mode in ("nightmare_boss", "boss_rush"):
        active_combats.pop(user_id, None)
    mapped_floor = ((nightmare_floor - 101) % 10 + 1) * 10
    res = start_floor_boss(
        db,
        content,
        active_combats,
        user_id,
        floor=mapped_floor,
        mode="normal",
        now_ts=ts,
        nightmare_floor=nightmare_floor,
        bypass_cooldown=True,
    )
    res["nightmare"] = True
    res["nightmare_floor"] = nightmare_floor
    res["message"] = f"🌑 【艾恩葛朗特夢魘第 {nightmare_floor} 層】超限頭目降臨！（抗性穿透達上限 65%）"
    return res


def get_leaderboard(
    db: RPGDatabase,
    category: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Query any of the 7 SAO Leaderboards: `floor`, `power`, `level`, `world_boss`, `guild`, `col`, `survival`."""
    cat = str(category or "").strip().lower()
    if cat not in VALID_LEADERBOARD_CATEGORIES:
        raise GameError(
            f"未知的排行榜類別：{category}（支援：floor / power / level / world_boss / guild / col / survival）",
            code="INVALID_LEADERBOARD_CATEGORY",
        )
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise GameError("排行榜顯示筆數 limit 必須為正整數。", code="INVALID_LIMIT")
    safe_limit = min(50, limit)

    if cat == "guild":
        guilds = db.get_guild_leaderboard(safe_limit)
        entries = [
            {
                "rank": idx + 1,
                "guild_id": g.id,
                "name": g.name,
                "tag": g.tag,
                "level": g.level,
                "merit_points": g.merit_points,
                "vault_col": g.vault_col,
                "member_count": g.member_count,
                "score": g.merit_points,
            }
            for idx, g in enumerate(guilds)
        ]
    else:
        players = db.get_leaderboard(cat, safe_limit)
        score_attr_map = {
            "floor": "highest_cleared_floor",
            "power": "combat_power",
            "level": "level",
            "world_boss": "total_boss_damage",
            "col": "col",
            "survival": "survival_streak",
        }
        score_attr = score_attr_map.get(cat, "combat_power")
        def _entry_score(p: Any) -> int:
            if cat == "level":
                return int(p.rebirth_count) * 1000 + int(p.level)
            return int(getattr(p, score_attr, 0))

        entries = [
            {
                "rank": idx + 1,
                "user_id": p.user_id,
                "display_name": p.display_name,
                "level": p.level,
                "highest_cleared_floor": p.highest_cleared_floor,
                "combat_power": p.combat_power,
                "col": p.col,
                "total_boss_damage": p.total_boss_damage,
                "survival_streak": p.survival_streak,
                "rebirth_count": p.rebirth_count,
                "score": _entry_score(p),
            }
            for idx, p in enumerate(players)
        ]

    cat_names = {
        "floor": "樓層攻略榜",
        "power": "綜合戰力榜",
        "level": "等級威望榜",
        "world_boss": "世界王傷害榜",
        "guild": "公會榮耀榜",
        "col": "柯爾富豪榜",
        "survival": "生存連勝榜",
    }
    return {
        "ok": True,
        "category": cat,
        "title": cat_names[cat],
        "entries": entries,
        "count": len(entries),
        "message": f"🏆 【艾恩葛朗特・{cat_names[cat]}】共列出前 {len(entries)} 名紀錄。",
    }
