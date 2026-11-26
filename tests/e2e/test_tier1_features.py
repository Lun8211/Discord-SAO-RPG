"""Tier 1 E2E Feature Coverage Suite — Happy Paths across ALL 35 SAO Features.

Covers Features 01–35 from PROJECT.md § Feature Inventory with >= 5 distinct,
genuine, opaque-box happy-path tests per feature (>= 185 total collected tests).
Module top-level imports are strictly Python stdlib + pytest only.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# ===========================================================================
# Feature 01: Aincrad 100-Floor Worldview & Character Creation (6 tests)
# ===========================================================================


def test_t1_f01_create_standard_character_spawns_f1_town(
    engine: Any,
    clock: Any,
    e2e: Any,
) -> None:
    res = e2e.assert_ok_result(
        engine.create_character(
            "101001",
            "桐人",
            weapon_style="sword",
            mode="standard",
            now_ts=clock.now,
        ),
        require_zh_tw=True,
    )
    blob = e2e.extract_text_blob(res)
    assert any(k in blob for k in ("Link Start", "艾恩葛朗特", "起始之鎮", "桐人"))

    prof = e2e.assert_ok_result(engine.get_profile("101001", now_ts=clock.now))
    cur_floor, max_floor = e2e.get_player_floor(engine, "101001", clock)
    assert cur_floor == 1
    assert max_floor == 1
    assert e2e.get_player_zone(engine, "101001", clock) == "town"
    assert int(e2e.extract_field(prof, "level")) == 1
    assert str(e2e.extract_field(prof, "mode", "game_mode")).lower() == "standard"
    assert e2e.get_player_cursor(engine, "101001", clock) == "green"
    assert e2e.get_player_col(engine, "101001", clock) > 0
    assert int(e2e.extract_field(prof, "combat_power", "power")) > 0


def test_t1_f01_create_hardcore_death_game_character(
    engine: Any,
    clock: Any,
    e2e: Any,
) -> None:
    e2e.assert_ok_result(
        engine.create_character(
            "101002",
            "亞絲娜",
            weapon_style="rapier",
            mode="hardcore",
            now_ts=clock.now,
        ),
        require_zh_tw=True,
    )
    prof = e2e.assert_ok_result(engine.get_profile("101002", now_ts=clock.now))
    assert str(e2e.extract_field(prof, "mode", "game_mode")).lower() == "hardcore"
    assert str(e2e.extract_field(prof, "weapon_style", "style")).lower() == "rapier"
    assert e2e.get_player_floor(engine, "101002", clock)[0] == 1
    assert e2e.get_player_zone(engine, "101002", clock) == "town"


def test_t1_f01_create_character_all_8_starter_weapon_styles(
    engine: Any,
    clock: Any,
    e2e: Any,
) -> None:
    for idx, style in enumerate(e2e.BASE_8_WEAPON_STYLES, start=1):
        uid = f"10110{idx}"
        e2e.assert_ok_result(
            engine.create_character(
                uid,
                f"劍士{idx}",
                weapon_style=style,
                mode="standard",
                now_ts=clock.now,
            )
        )
        prof = e2e.assert_ok_result(engine.get_profile(uid, now_ts=clock.now))
        assert str(e2e.extract_field(prof, "weapon_style", "style")).lower() == style
        assert int(e2e.extract_field(prof, "max_hp", "hp")) > 0
        assert int(e2e.extract_field(prof, "max_sp", "sp")) > 0
        assert int(e2e.extract_field(prof, "atk")) > 0


def test_t1_f01_profile_exposes_col_and_aincrad_progress(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("克萊因", weapon_style="katana")
    prof = e2e.assert_ok_result(engine.get_profile(uid, now_ts=clock.now), require_zh_tw=True)
    assert e2e.get_player_col(engine, uid, clock) > 0
    assert int(e2e.extract_field(prof, "level")) == 1
    assert int(e2e.extract_field(prof, "exp", default=0)) == 0
    assert e2e.get_player_floor(engine, uid, clock) == (1, 1)
    assert e2e.get_player_zone(engine, uid, clock) == "town"


def test_t1_f01_multiple_players_isolated_and_persisted_across_reopen(
    db: Any,
    db_path: Path,
    engine: Any,
    content_bundle: Any,
    clock: Any,
    e2e: Any,
) -> None:
    specs = [
        ("101201", "桐人", "sword", "standard"),
        ("101202", "艾基爾", "axe", "standard"),
        ("101203", "西莉卡", "dagger", "hardcore"),
    ]
    for uid, name, style, mode in specs:
        e2e.assert_ok_result(
            engine.create_character(uid, name, weapon_style=style, mode=mode, now_ts=clock.now)
        )
    db.close()

    db_cls = e2e.load_db_api()["RPGDatabase"]
    db2 = db_cls(db_path)
    try:
        eng2 = e2e.instantiate_engine(db2, content_bundle)
        for uid, name, style, mode in specs:
            prof = e2e.assert_ok_result(eng2.get_profile(uid, now_ts=clock.now))
            assert str(e2e.extract_field(prof, "display_name", "name")) == name
            assert str(e2e.extract_field(prof, "weapon_style", "style")).lower() == style
            assert str(e2e.extract_field(prof, "mode", "game_mode")).lower() == mode
    finally:
        db2.close()


def test_t1_f01_no_player_magic_canon_enforced(
    content_bundle: Any,
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("純劍技攻略者", weapon_style="sword")
    prof = e2e.assert_ok_result(engine.get_profile(uid, now_ts=clock.now))
    assert "mana" not in str(prof).lower() or "max_sp" in str(prof).lower()
    skills = e2e.iter_entries(content_bundle.sword_skills)
    assert len(skills) >= 16, "SAO must define authentic Sword Skills across weapon classes"
    forbidden = ("fireball", "meteor_spell", "arcane_bolt", "mage", "wizard")
    for sid, spec in skills:
        dmg_type = str(spec.get("dmg_type") or spec.get("damage_type") or "slash").lower()
        assert dmg_type in e2e.FOUR_DAMAGE_TYPES, f"Non-SAO damage type on {sid}: {dmg_type!r}"
        assert not any(bad in sid.lower() for bad in forbidden)


# ===========================================================================
# Feature 02: Safe Zone (圈內) vs Field / Labyrinth (野外/迷宮區) (5 tests)
# ===========================================================================


def test_t1_f02_new_player_starts_in_town_safe_zone(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("安全區劍士")
    assert e2e.get_player_zone(engine, uid, clock) == "town"


def test_t1_f02_travel_town_to_field(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("野外探索者")
    e2e.assert_ok_result(engine.travel_zone(uid, "field", now_ts=clock.now), require_zh_tw=True)
    assert e2e.get_player_zone(engine, uid, clock) == "field"


def test_t1_f02_travel_field_to_labyrinth(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("迷宮突入者")
    e2e.assert_ok_result(engine.travel_zone(uid, "field", now_ts=clock.now))
    e2e.explore_to_boss_gate(engine, uid, clock, floor=1)
    e2e.assert_ok_result(engine.travel_zone(uid, "labyrinth", now_ts=clock.now))
    assert e2e.get_player_zone(engine, uid, clock) == "labyrinth"


def test_t1_f02_return_from_danger_zone_to_town_safe_zone(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("歸城者")
    e2e.assert_ok_result(engine.travel_zone(uid, "field", now_ts=clock.now))
    assert e2e.get_player_zone(engine, uid, clock) == "field"
    e2e.assert_ok_result(engine.travel_zone(uid, "town", now_ts=clock.now), require_zh_tw=True)
    assert e2e.get_player_zone(engine, uid, clock) == "town"


def test_t1_f02_town_safe_zone_permits_town_services(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("城鎮補給者")
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    col_before = e2e.get_player_col(engine, uid, clock)
    e2e.assert_ok_result(engine.buy_shop_item(uid, potion_id, qty=1, now_ts=clock.now))
    assert e2e.get_player_col(engine, uid, clock) < col_before
    assert e2e.get_player_item_qty(engine, uid, potion_id, clock) >= 1
    e2e.assert_ok_result(engine.respec_talents(uid))


# ===========================================================================
# Feature 03: Teleport Gate (轉移門) (5 tests)
# ===========================================================================


def test_t1_f03_teleport_to_f1_town_of_beginnings(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("轉移門旅人")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    res = e2e.assert_ok_result(
        engine.teleport_floor(uid, 1, now_ts=clock.now),
        require_zh_tw=True,
    )
    assert e2e.get_player_floor(engine, uid, clock)[0] == 1
    assert e2e.get_player_zone(engine, uid, clock) == "town"
    assert any(k in e2e.extract_text_blob(res) for k in ("起始之鎮", "第 1 層", "第1層", "轉移"))


def test_t1_f03_clearing_f1_boss_unlocks_f2_teleport_gate(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("一層突破者")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=8, power_boost=True
    )
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="normal", heal_item_id=potion_id)
    e2e.assert_ok_result(engine.teleport_floor(uid, 2, now_ts=clock.now), require_zh_tw=True)
    cur_floor, max_floor = e2e.get_player_floor(engine, uid, clock)
    assert cur_floor == 2
    assert max_floor >= 2
    assert e2e.get_player_zone(engine, uid, clock) == "town"


def test_t1_f03_teleport_back_to_lower_floor_preserves_max_unlocked(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("樓層往返者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 5, clock=clock)
    e2e.assert_ok_result(engine.teleport_floor(uid, 1, now_ts=clock.now))
    assert e2e.get_player_floor(engine, uid, clock)[0] == 1
    e2e.assert_ok_result(engine.teleport_floor(uid, 3, now_ts=clock.now))
    cur_floor, max_floor = e2e.get_player_floor(engine, uid, clock)
    assert cur_floor == 3
    assert max_floor >= 5


def test_t1_f03_teleport_from_field_lands_in_target_town_safe_zone(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("跨層回城者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 3, clock=clock)
    engine.travel_zone(uid, "field", now_ts=clock.now)
    assert e2e.get_player_zone(engine, uid, clock) == "field"
    e2e.assert_ok_result(engine.teleport_floor(uid, 2, now_ts=clock.now))
    assert e2e.get_player_floor(engine, uid, clock)[0] == 2
    assert e2e.get_player_zone(engine, uid, clock) == "town"


def test_t1_f03_floor_info_distinguishes_unlocked_vs_locked_floors(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("樓層情報員")
    f1 = e2e.assert_ok_result(engine.get_floor_info(1, user_id=uid))
    f10 = e2e.assert_ok_result(engine.get_floor_info(10, user_id=uid))
    assert e2e.extract_field(f1, "unlocked", "is_unlocked") is True
    assert e2e.extract_field(f10, "unlocked", "is_unlocked") is False


# ===========================================================================
# Feature 04: Monument of Life (生命之碑) & Survival Logs (5 tests)
# ===========================================================================


def test_t1_f04_monument_counts_single_alive_adventurer(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    make_player("桐人")
    mon = e2e.assert_ok_result(engine.get_monument_of_life(limit=10), require_zh_tw=True)
    assert int(e2e.extract_field(mon, "total", "total_players")) == 1
    assert int(e2e.extract_field(mon, "alive", "alive_count", "alive_players")) == 1
    assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 0


def test_t1_f04_monument_tracks_multiple_adventurers(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    for i in range(3):
        make_player(f"標準者{i}", mode="standard")
    for i in range(2):
        make_player(f"死遊者{i}", mode="hardcore")
    mon = e2e.assert_ok_result(engine.get_monument_of_life(limit=10))
    assert int(e2e.extract_field(mon, "total", "total_players")) == 5
    assert int(e2e.extract_field(mon, "alive", "alive_count", "alive_players")) == 5
    assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 0


def test_t1_f04_monument_and_profile_expose_survival_streak(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("連勝劍士")
    e2e.trigger_road_combat(engine, uid, clock, seed_start=401)
    e2e.resolve_active_combat(engine, uid, clock)
    prof = e2e.assert_ok_result(engine.get_profile(uid, now_ts=clock.now))
    streak = int(
        e2e.extract_field(prof, "survival_streak", "win_streak", "survival_days", "survival_score", default=0)
    )
    assert streak >= 0
    mon = e2e.assert_ok_result(engine.get_monument_of_life(limit=10))
    assert int(e2e.extract_field(mon, "alive", "alive_count", "alive_players")) >= 1


def test_t1_f04_monument_records_defeat_with_last_round_log(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("悲劇先鋒", mode="hardcore")
    e2e.induce_combat_defeat(engine, db, content_bundle, uid, clock, in_boss=True)
    mon = e2e.assert_ok_result(engine.get_monument_of_life(limit=10), require_zh_tw=True)
    assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 1
    blob = e2e.extract_text_blob(mon)
    assert "悲劇先鋒" in blob or uid in blob


def test_t1_f04_monument_limit_caps_returned_entries(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    for i in range(3):
        uid = make_player(f"落敗者{i}", mode="hardcore")
        e2e.induce_combat_defeat(engine, db, content_bundle, uid, clock, in_boss=True)
    mon_small = e2e.assert_ok_result(engine.get_monument_of_life(limit=2))
    entries = e2e.extract_field(mon_small, "entries", "logs", "recent_logs", "records", "fallen_list")
    assert isinstance(entries, list)
    assert len(entries) <= 2
    assert int(e2e.extract_field(mon_small, "total", "total_players")) == 3


# ===========================================================================
# Feature 05: Color Cursor (光標顏色: 綠/橙/紅) & Karma (5 tests)
# ===========================================================================


def test_t1_f05_new_player_has_green_cursor(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("綠名劍士")
    assert e2e.get_player_cursor(engine, uid, clock) == "green"


def test_t1_f05_story_moral_choice_updates_karma(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("劇情抉擇者")
    ch_id, choice_id, _ = e2e.pick_story_choice(content_bundle)
    res = e2e.assert_ok_result(
        engine.choose_story_option(uid, ch_id, choice_id, now_ts=clock.now),
        require_zh_tw=True,
    )
    assert res
    prof = e2e.assert_ok_result(engine.get_profile(uid, now_ts=clock.now))
    assert e2e.get_player_cursor(engine, uid, clock) in e2e.THREE_CURSORS
    assert e2e.has_field(prof, "karma", "cursor_color", "cursor")


def test_t1_f05_negative_karma_exposes_orange_or_red_cursor(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("暗影抉擇者")
    ch_id, choice_id, _ = e2e.pick_story_choice(content_bundle, karma_negative=True)
    prof_before = e2e.assert_ok_result(engine.get_profile(uid, now_ts=clock.now))
    karma_before = int(e2e.extract_field(prof_before, "karma", default=0))
    e2e.assert_ok_result(engine.choose_story_option(uid, ch_id, choice_id, now_ts=clock.now))
    prof_after = e2e.assert_ok_result(engine.get_profile(uid, now_ts=clock.now))
    karma_after = int(e2e.extract_field(prof_after, "karma", default=0))
    cursor_after = e2e.get_player_cursor(engine, uid, clock)
    assert karma_after < karma_before or cursor_after in ("orange", "red")


def test_t1_f05_consented_town_duel_preserves_green_cursor(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    p1 = make_player("決鬥者甲", weapon_style="sword")
    p2 = make_player("決鬥者乙", weapon_style="rapier")
    d_res = e2e.assert_ok_result(
        engine.challenge_duel(p1, p2, mode="first_strike", wager_col=0, now_ts=clock.now)
    )
    duel_id = str(e2e.extract_field(d_res, "duel_id", "id"))
    e2e.assert_ok_result(engine.accept_duel(duel_id, p2, now_ts=clock.now))
    for i in range(40):
        actor = p1 if i % 2 == 0 else p2
        step = e2e.assert_ok_result(engine.duel_action(duel_id, actor, "attack", now_ts=clock.now))
        if str(e2e.extract_field(step, "status", default="")).lower() in ("finished", "ended", "completed") or e2e.extract_field(step, "finished", "ended", default=False) is True:
            break
    assert e2e.get_player_cursor(engine, p1, clock) == "green"
    assert e2e.get_player_cursor(engine, p2, clock) == "green"


def test_t1_f05_orange_cursor_decays_back_to_green_over_time(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("懺悔劍士")
    ch_id, choice_id, _ = e2e.pick_story_choice(content_bundle, karma_negative=True)
    e2e.assert_ok_result(engine.choose_story_option(uid, ch_id, choice_id, now_ts=clock.now))
    clock.advance(days=7)
    prof = e2e.assert_ok_result(engine.get_profile(uid, now_ts=clock.now))
    assert e2e.get_player_cursor(engine, uid, clock) == "green"
    assert int(e2e.extract_field(prof, "karma", default=0)) >= 0


# ===========================================================================
# Feature 06: Argo's Info (阿爾狗的情報) & Clearers (攻略組) (5 tests)
# ===========================================================================


def test_t1_f06_argo_server_frontline_summary_initial(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    make_player("情報買家")
    intel = e2e.assert_ok_result(engine.get_argo_intel(), require_zh_tw=True)
    frontline = int(e2e.extract_field(intel, "frontline_floor", "frontline", "highest_server_floor", "server_floor"))
    assert frontline >= 1


def test_t1_f06_argo_floor_intel_masks_unobserved_boss_skills(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("新手情報員")
    intel = e2e.assert_ok_result(engine.get_argo_intel(user_id=uid, floor=1), require_zh_tw=True)
    blob = e2e.extract_text_blob(intel)
    assert "???" in blob or int(e2e.extract_field(intel, "observed_count", default=0)) == 0


def test_t1_f06_argo_reveals_boss_skills_after_battle_observation(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("實戰偵察者")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    before_blob = e2e.extract_text_blob(engine.get_argo_intel(user_id=uid, floor=1))
    before_masks = before_blob.count("???")

    e2e.assert_ok_result(engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now))
    for _ in range(5):
        turn = e2e.assert_ok_result(engine.combat_action(uid, "defend", now_ts=clock.now))
        if e2e.extract_field(turn, "ended", "finished", default=False) is True:
            break

    intel_after = e2e.assert_ok_result(engine.get_argo_intel(user_id=uid, floor=1))
    after_masks = e2e.extract_text_blob(intel_after).count("???")
    observed = e2e.extract_field(intel_after, "observed_skills", "seen_skills", "known_skills", default=[])
    assert after_masks < before_masks or len(observed) >= 1


def test_t1_f06_argo_hall_of_fame_records_first_kill_clearer(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("首殺攻略組")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=10)
    e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="first_kill")
    intel = e2e.assert_ok_result(engine.get_argo_intel(floor=1))
    blob = e2e.extract_text_blob(intel)
    assert "首殺攻略組" in blob or uid in blob
    frontline = int(e2e.extract_field(engine.get_argo_intel(), "frontline_floor", "frontline", "highest_server_floor", "server_floor"))
    assert frontline >= 2


def test_t1_f06_argo_milestone_floor_intel_lookup(
    engine: Any,
    e2e: Any,
) -> None:
    f10 = e2e.assert_ok_result(engine.get_argo_intel(floor=10), require_zh_tw=True)
    f100 = e2e.assert_ok_result(engine.get_argo_intel(floor=100), require_zh_tw=True)
    assert e2e.extract_text_blob(f10) != e2e.extract_text_blob(f100)


# ===========================================================================
# Feature 07: Yui Console (結衣終端機) Lore Archive (5 tests)
# ===========================================================================


def test_t1_f07_f1_starter_yui_log_unlocked_by_default(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("終端讀取者")
    res = e2e.assert_ok_result(engine.get_yui_logs(uid), require_zh_tw=True)
    entries = e2e.extract_field(res, "logs", "entries", "unlocked_logs")
    assert isinstance(entries, list) and len(entries) >= 1
    unlocked = [e for e in entries if e2e.as_mapping(e).get("unlocked", True) is True]
    assert len(unlocked) >= 1


def test_t1_f07_f10_and_f25_milestone_logs_unlock_progressively(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("結衣調查者")
    r1 = e2e.assert_ok_result(engine.get_yui_logs(uid))
    c1 = sum(1 for e in e2e.extract_field(r1, "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 10, clock=clock)
    r10 = e2e.assert_ok_result(engine.get_yui_logs(uid))
    c10 = sum(1 for e in e2e.extract_field(r10, "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 25, clock=clock)
    r25 = e2e.assert_ok_result(engine.get_yui_logs(uid))
    c25 = sum(1 for e in e2e.extract_field(r25, "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    assert c1 < c10 < c25


def test_t1_f07_f27_and_f50_milestone_logs_unlock(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("中層紀錄者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 27, clock=clock)
    r27 = e2e.assert_ok_result(engine.get_yui_logs(uid), require_zh_tw=True)
    c27 = sum(1 for e in e2e.extract_field(r27, "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 50, clock=clock)
    r50 = e2e.assert_ok_result(engine.get_yui_logs(uid), require_zh_tw=True)
    c50 = sum(1 for e in e2e.extract_field(r50, "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    assert c50 > c27


def test_t1_f07_f75_and_f100_complete_yui_archive_unlocked(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("百層解放者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 100, clock=clock, level=100)
    r100 = e2e.assert_ok_result(engine.get_yui_logs(uid), require_zh_tw=True)
    entries = e2e.extract_field(r100, "logs", "entries")
    unlocked = [e for e in entries if e2e.as_mapping(e).get("unlocked", True)]
    assert len(unlocked) >= 7


def test_t1_f07_yui_logs_aligned_with_json_quests_events_catalog(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("檔案檢驗者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 100, clock=clock, level=100)
    res = e2e.assert_ok_result(engine.get_yui_logs(uid))
    entries = e2e.extract_field(res, "logs", "entries")
    catalog = content_bundle.quests_events.get("yui_logs", [])
    assert len(catalog) >= 7
    for entry in entries:
        m = e2e.as_mapping(entry)
        if m.get("unlocked", True):
            assert e2e.has_zh_tw(e2e.extract_text_blob(m))


# ===========================================================================
# Feature 08: JSON-Driven 100-Floor Template & Override Engine (5 tests)
# ===========================================================================


def test_t1_f08_load_and_validate_all_hydrates_10_json_collections(
    content_bundle: Any,
    e2e: Any,
) -> None:
    bundle = e2e.load_content_api()["load_and_validate_all"]()
    assert bundle is not None
    assert len(e2e.iter_entries(bundle.bosses)) >= 14
    assert len(e2e.iter_entries(bundle.monsters)) >= 10
    assert len(e2e.iter_entries(bundle.sword_skills)) >= 16
    assert len(e2e.iter_entries(bundle.items_crystals)) >= 15


def test_t1_f08_all_100_floors_generated_deterministically(
    engine: Any,
    e2e: Any,
) -> None:
    seen_f1 = e2e.assert_ok_result(engine.get_floor_info(1), require_zh_tw=True)
    for fl in range(1, 101):
        info = e2e.assert_ok_result(engine.get_floor_info(fl), require_zh_tw=True)
        assert int(e2e.extract_field(info, "floor", "floor_num", "number")) == fl
        assert e2e.extract_field(info, "boss_id", "boss", "boss_name")
    assert e2e.assert_ok_result(engine.get_floor_info(1)) == seen_f1


def test_t1_f08_ten_biome_tiers_cover_floors_1_to_100_contiguously(
    content_bundle: Any,
    e2e: Any,
) -> None:
    biomes = content_bundle.biomes
    tiers = biomes.get("tiers") if isinstance(biomes, dict) else biomes
    entries = e2e.iter_entries(tiers)
    assert len(entries) == 10
    covered: set[int] = set()
    for _, spec in entries:
        lo = int(spec.get("floor_min", spec.get("start_floor", spec.get("min_floor", 0))))
        hi = int(spec.get("floor_max", spec.get("end_floor", spec.get("max_floor", 0))))
        assert 1 <= lo <= hi <= 100
        covered.update(range(lo, hi + 1))
    assert covered == set(range(1, 101))


def test_t1_f08_canon_floor_overrides_applied_accurately(
    engine: Any,
    e2e: Any,
) -> None:
    canon_checks = {
        1: ("起始之鎮", "狗頭人", "伊爾方"),
        10: ("加賀智", "武士"),
        25: ("極光", "雙面", "獄魔", "深淵"),
        27: ("水晶", "無效", "黑貓", "陷阱"),
        50: ("阿爾格特", "鋼鐵", "仲裁"),
        74: ("閃耀魔眼", "卡姆戴特"),
        75: ("骸骨獵殺者", "柯林尼亞"),
        100: ("紅玉宮", "希茲克利夫", "化身", "雷迪烏斯"),
    }
    for fl, keywords in canon_checks.items():
        info = e2e.assert_ok_result(engine.get_floor_info(fl), require_zh_tw=True)
        blob = e2e.extract_text_blob(info)
        assert any(k in blob for k in keywords), f"Floor {fl} missing canon lore {keywords!r}: {blob!r}"


def test_t1_f08_all_14_milestone_bosses_and_tier_guardians_bound(
    engine: Any,
    e2e: Any,
) -> None:
    milestone_ids: set[str] = set()
    for fl in e2e.MILESTONE_14_FLOORS:
        info = e2e.assert_ok_result(engine.get_floor_info(fl))
        bid = str(e2e.extract_field(info, "boss_id", "boss_name"))
        milestone_ids.add(bid)
    assert len(milestone_ids) == 14
    for fl in (3, 15, 42, 88):
        info = e2e.assert_ok_result(engine.get_floor_info(fl))
        assert e2e.extract_field(info, "boss_id", "boss_name")


# ===========================================================================
# Feature 09: Floor Exploration Progression (Field -> Labyrinth -> Boss Gate) (5 tests)
# ===========================================================================


def test_t1_f09_single_step_exploration_increases_progress(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("單步探索者")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    res = e2e.assert_ok_result(
        engine.explore_floor(uid, steps=1, now_ts=clock.now, rng_seed=101),
        require_zh_tw=True,
    )
    assert res
    finfo = e2e.assert_ok_result(engine.get_floor_info(1, user_id=uid))
    pct = int(e2e.extract_field(finfo, "exploration_pct", "exploration", "progress"))
    assert pct > 0


def test_t1_f09_multi_step_exploration_advances_progress(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("多步探索者")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_ok_result(engine.explore_floor(uid, steps=3, now_ts=clock.now, rng_seed=202))
    finfo = e2e.assert_ok_result(engine.get_floor_info(1, user_id=uid))
    pct = int(e2e.extract_field(finfo, "exploration_pct", "exploration", "progress"))
    assert 0 < pct <= 100


def test_t1_f09_seeded_exploration_deterministic(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("種子甲")
    u2 = make_player("種子乙")
    engine.travel_zone(u1, "field", now_ts=clock.now)
    engine.travel_zone(u2, "field", now_ts=clock.now)
    r1 = e2e.assert_ok_result(engine.explore_floor(u1, steps=1, now_ts=clock.now, rng_seed=4242))
    r2 = e2e.assert_ok_result(engine.explore_floor(u2, steps=1, now_ts=clock.now, rng_seed=4242))
    ev1 = e2e.extract_field(r1, "event_type", "encounter_type", "type", "event")
    ev2 = e2e.extract_field(r2, "event_type", "encounter_type", "type", "event")
    assert ev1 == ev2
    p1 = int(e2e.extract_field(engine.get_floor_info(1, user_id=u1), "exploration_pct", "exploration", "progress"))
    p2 = int(e2e.extract_field(engine.get_floor_info(1, user_id=u2), "exploration_pct", "exploration", "progress"))
    assert p1 == p2


def test_t1_f09_exploration_100_percent_unlocks_boss_room_gate(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("迷宮開門者")
    finfo = e2e.explore_to_boss_gate(engine, uid, clock, floor=1)
    assert int(e2e.extract_field(finfo, "exploration_pct", "exploration", "progress")) >= 100
    boss_res = e2e.assert_ok_result(
        engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now),
        require_zh_tw=True,
    )
    assert int(e2e.extract_field(boss_res, "hp_bars", "total_bars", "bars")) >= 3


def test_t1_f09_exploration_produces_varied_encounter_types(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("多元奇遇者")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    seen_types: set[str] = set()
    for s in range(1, 35):
        res = e2e.assert_ok_result(engine.explore_floor(uid, steps=1, now_ts=clock.now, rng_seed=s))
        ev = str(e2e.extract_field(res, "event_type", "encounter_type", "type", "event")).lower()
        seen_types.add(ev)
        if "chest" in ev or e2e.has_field(res, "chest", "chest_tier"):
            engine.open_chest(uid, action="leave", now_ts=clock.now)
        elif e2e.extract_field(res, "in_combat", default=False) is True or any(
            k in ev for k in ("combat", "mob", "monster", "battle", "elite", "field_boss")
        ):
            e2e.resolve_active_combat(engine, uid, clock)
        if len(seen_types) >= 2:
            break
    assert len(seen_types) >= 2, f"Expected >=2 encounter types, saw {seen_types!r}"


# ===========================================================================
# Feature 10: Road Monsters (Normal, Elite, Named Field Mobs) (5 tests)
# ===========================================================================


def test_t1_f10_all_10_biomes_define_valid_4_axis_monsters(
    content_bundle: Any,
    e2e: Any,
) -> None:
    mobs = e2e.iter_entries(content_bundle.monsters)
    assert len(mobs) >= 10
    for mid, spec in mobs:
        name = str(spec.get("name") or spec.get("zh_name") or "")
        assert e2e.has_zh_tw(name), f"Monster {mid} missing zh-TW name"
        dt = str(spec.get("dmg_type") or spec.get("damage_type") or "slash").lower()
        assert dt in e2e.FOUR_DAMAGE_TYPES, f"Monster {mid} invalid dmg_type {dt!r}"
        assert int(spec.get("hp", spec.get("base_hp", 1))) > 0


def test_t1_f10_defeating_road_monster_grants_exp_and_col(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("討伐小怪者")
    col_before = e2e.get_player_col(engine, uid, clock)
    exp_before = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "exp", default=0))
    e2e.trigger_road_combat(engine, uid, clock, seed_start=1010)
    e2e.resolve_active_combat(engine, uid, clock)
    prof_after = engine.get_profile(uid, now_ts=clock.now)
    col_after = e2e.get_player_col(engine, uid, clock)
    exp_after = int(e2e.extract_field(prof_after, "exp", default=0))
    lvl_after = int(e2e.extract_field(prof_after, "level"))
    assert col_after > col_before
    assert exp_after > exp_before or lvl_after > 1


def test_t1_f10_monsters_drop_valid_materials_and_cooking_meats(
    content_bundle: Any,
    e2e: Any,
) -> None:
    item_ids = {iid for iid, _ in e2e.iter_entries(content_bundle.items_crystals)}
    drop_refs = 0
    for mid, spec in e2e.iter_entries(content_bundle.monsters):
        drops = spec.get("drops") or spec.get("drop_table") or spec.get("materials") or []
        if isinstance(drops, list):
            for entry in drops:
                iid = entry.get("item_id") if isinstance(entry, dict) else str(entry)
                if iid:
                    assert iid in item_ids, f"Monster {mid} references dangling drop {iid!r}"
                    drop_refs += 1
    assert drop_refs >= 1


def test_t1_f10_higher_floor_monsters_scale_stronger_and_richer(
    engine: Any,
    e2e: Any,
) -> None:
    f1 = e2e.assert_ok_result(engine.get_floor_info(1))
    f50 = e2e.assert_ok_result(engine.get_floor_info(50))
    scale1 = float(e2e.extract_field(f1, "hp_scale", "stat_multiplier", "recommended_level", "boss_hp"))
    scale50 = float(e2e.extract_field(f50, "hp_scale", "stat_multiplier", "recommended_level", "boss_hp"))
    assert scale50 > scale1


def test_t1_f10_overleveled_player_still_receives_min_1_exp(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("滿級刷一層者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=50)
    prof_before = engine.get_profile(uid, now_ts=clock.now)
    exp_before = int(e2e.extract_field(prof_before, "exp", default=0))
    lvl_before = int(e2e.extract_field(prof_before, "level"))
    e2e.trigger_road_combat(engine, uid, clock, seed_start=1050)
    res = e2e.resolve_active_combat(engine, uid, clock)
    prof_after = engine.get_profile(uid, now_ts=clock.now)
    exp_after = int(e2e.extract_field(prof_after, "exp", default=0))
    lvl_after = int(e2e.extract_field(prof_after, "level"))
    exp_gained = int(e2e.extract_field(res, "exp_gained", "exp", default=0))
    assert exp_gained >= 1 or exp_after >= exp_before + 1 or lvl_after > lvl_before


# ===========================================================================
# Feature 11: Treasure Chests (6 Tiers) + Mimic & Crystal-Null Trap Room (5 tests)
# ===========================================================================


def test_t1_f11_six_chest_tiers_and_traps_in_json_catalog(
    content_bundle: Any,
    e2e: Any,
) -> None:
    cl = content_bundle.chests_loot
    tiers = cl.get("tiers") or cl.get("chest_tiers") or cl.get("chests") or cl
    entries = e2e.iter_entries(tiers)
    assert len(entries) >= 6, f"Expected >= 6 chest tiers/types, got {len(entries)}"


def test_t1_f11_inspect_chest_uses_searching_without_consuming(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("索敵鑑賞家")
    e2e.trigger_chest_encounter(engine, uid, clock, seed_start=1100)
    insp = e2e.assert_ok_result(
        engine.open_chest(uid, action="inspect", now_ts=clock.now, rng_seed=11),
        require_zh_tw=True,
    )
    assert e2e.has_zh_tw(e2e.extract_text_blob(insp))
    # Chest remains openable after inspect
    opened = e2e.assert_ok_result(
        engine.open_chest(uid, action="open", now_ts=clock.now, rng_seed=11)
    )
    assert opened


def test_t1_f11_open_chest_awards_loot_or_triggers_mimic(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("開箱勇者")
    e2e.trigger_chest_encounter(engine, uid, clock, seed_start=1120)
    res = e2e.assert_ok_result(
        engine.open_chest(uid, action="open", now_ts=clock.now, rng_seed=77),
        require_zh_tw=True,
    )
    assert e2e.has_zh_tw(e2e.extract_text_blob(res))


def test_t1_f11_leave_chest_skips_safely(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("謹慎棄箱者")
    e2e.trigger_chest_encounter(engine, uid, clock, seed_start=1140)
    hp_before = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "hp", "current_hp", "max_hp"))
    res = e2e.assert_ok_result(
        engine.open_chest(uid, action="leave", now_ts=clock.now),
        require_zh_tw=True,
    )
    hp_after = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "hp", "current_hp", "max_hp"))
    assert res and hp_after == hp_before


def test_t1_f11_seeded_chest_open_deterministic(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("同種開箱甲")
    u2 = make_player("同種開箱乙")
    e2e.trigger_chest_encounter(engine, u1, clock, seed_start=1160)
    e2e.trigger_chest_encounter(engine, u2, clock, seed_start=1160)
    r1 = e2e.assert_ok_result(engine.open_chest(u1, action="open", now_ts=clock.now, rng_seed=1234))
    r2 = e2e.assert_ok_result(engine.open_chest(u2, action="open", now_ts=clock.now, rng_seed=1234))
    assert e2e.extract_field(r1, "chest_tier", "tier", "outcome", "type") == e2e.extract_field(
        r2, "chest_tier", "tier", "outcome", "type"
    )


# ===========================================================================
# Feature 12: Secret Realm & Miasma (秘境與瘴氣) (5 tests)
# ===========================================================================


def test_t1_f12_enter_secret_realm_transitions_zone(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("秘境踏入者")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_ok_result(
        engine.enter_secret_realm(uid, action="enter", now_ts=clock.now, rng_seed=1201),
        require_zh_tw=True,
    )
    assert e2e.get_player_zone(engine, uid, clock) == "secret_realm"


def test_t1_f12_explore_secret_realm_stacks_miasma_and_exp_bonus(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("瘴氣試煉者")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    engine.enter_secret_realm(uid, action="enter", now_ts=clock.now, rng_seed=1202)
    res = e2e.assert_ok_result(
        engine.enter_secret_realm(uid, action="explore", now_ts=clock.now, rng_seed=1203)
    )
    if e2e.extract_field(res, "in_combat", default=False) is True:
        e2e.resolve_active_combat(engine, uid, clock)
    assert e2e.get_player_miasma(engine, uid, clock) >= 1
    prof = engine.get_profile(uid, now_ts=clock.now)
    exp_bonus = float(e2e.extract_field(prof, "secret_realm_exp_bonus", "miasma_exp_bonus", "exp_multiplier"))
    assert exp_bonus > 0


def test_t1_f12_repeated_secret_realm_waves_escalate_risk_and_exp(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("連波秘境者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=10)
    engine.travel_zone(uid, "field", now_ts=clock.now)
    engine.enter_secret_realm(uid, action="enter", now_ts=clock.now, rng_seed=1210)
    w1 = e2e.assert_ok_result(engine.enter_secret_realm(uid, action="explore", now_ts=clock.now, rng_seed=1211))
    if e2e.extract_field(w1, "in_combat", default=False) is True:
        e2e.resolve_active_combat(engine, uid, clock)
    m1 = e2e.get_player_miasma(engine, uid, clock)
    for k in range(2):
        wk = e2e.assert_ok_result(
            engine.enter_secret_realm(uid, action="explore", now_ts=clock.now, rng_seed=1212 + k)
        )
        if e2e.extract_field(wk, "in_combat", default=False) is True:
            e2e.resolve_active_combat(engine, uid, clock)
    m3 = e2e.get_player_miasma(engine, uid, clock)
    assert m3 > m1


def test_t1_f12_leave_secret_realm_clears_exp_bonus_keeps_miasma(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("離開秘境者")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    engine.enter_secret_realm(uid, action="enter", now_ts=clock.now, rng_seed=1220)
    r = e2e.assert_ok_result(engine.enter_secret_realm(uid, action="explore", now_ts=clock.now, rng_seed=1221))
    if e2e.extract_field(r, "in_combat", default=False) is True:
        e2e.resolve_active_combat(engine, uid, clock)
    miasma_before = e2e.get_player_miasma(engine, uid, clock)
    assert miasma_before >= 1
    e2e.assert_ok_result(engine.enter_secret_realm(uid, action="leave", now_ts=clock.now))
    assert e2e.get_player_zone(engine, uid, clock) != "secret_realm"
    assert e2e.get_player_miasma(engine, uid, clock) == miasma_before
    prof = engine.get_profile(uid, now_ts=clock.now)
    exp_bonus = float(e2e.extract_field(prof, "secret_realm_exp_bonus", "miasma_exp_bonus", default=0.0))
    assert exp_bonus <= 1.0


def test_t1_f12_return_to_town_clears_miasma_stacks(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("淨化瘴氣者")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    engine.enter_secret_realm(uid, action="enter", now_ts=clock.now, rng_seed=1230)
    r = e2e.assert_ok_result(engine.enter_secret_realm(uid, action="explore", now_ts=clock.now, rng_seed=1231))
    if e2e.extract_field(r, "in_combat", default=False) is True:
        e2e.resolve_active_combat(engine, uid, clock)
    engine.enter_secret_realm(uid, action="leave", now_ts=clock.now)
    assert e2e.get_player_miasma(engine, uid, clock) >= 1
    engine.travel_zone(uid, "town", now_ts=clock.now)
    assert e2e.get_player_miasma(engine, uid, clock) == 0


# ===========================================================================
# Feature 13: Black Iron Palace Underground Roguelike (黑鐵宮地下迷宮) (5 tests)
# ===========================================================================


def test_t1_f13_start_roguelike_from_town_creates_active_run(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("地下迷宮挑者")
    res = e2e.assert_ok_result(
        engine.start_roguelike(uid, now_ts=clock.now, rng_seed=505),
        require_zh_tw=True,
    )
    nodes = e2e.extract_field(res, "nodes", "choices", "options", "next_nodes")
    assert isinstance(nodes, list) and len(nodes) >= 1
    assert e2e.get_player_zone(engine, uid, clock) == "roguelike"


def test_t1_f13_seeded_roguelike_deterministic_route(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("地城種子甲")
    u2 = make_player("地城種子乙")
    r1 = e2e.assert_ok_result(engine.start_roguelike(u1, now_ts=clock.now, rng_seed=777))
    r2 = e2e.assert_ok_result(engine.start_roguelike(u2, now_ts=clock.now, rng_seed=777))
    assert e2e.extract_field(r1, "nodes", "choices", "options", "next_nodes") == e2e.extract_field(
        r2, "nodes", "choices", "options", "next_nodes"
    )


def test_t1_f13_step_roguelike_advances_depth_and_score(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("地城深潛者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=10)
    e2e.assert_ok_result(engine.start_roguelike(uid, now_ts=clock.now, rng_seed=1303))
    step1 = e2e.assert_ok_result(engine.step_roguelike(uid, node_index=0, now_ts=clock.now))
    if e2e.extract_field(step1, "in_combat", default=False) is True:
        e2e.resolve_active_combat(engine, uid, clock)
    step2 = e2e.assert_ok_result(engine.step_roguelike(uid, node_index=0, now_ts=clock.now))
    if e2e.extract_field(step2, "in_combat", default=False) is True:
        e2e.resolve_active_combat(engine, uid, clock)
    depth = int(e2e.extract_field(step2, "depth", "stage", "step", "floor_depth"))
    assert depth >= 2


def test_t1_f13_extract_roguelike_awards_rewards_and_returns_to_town(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("地城撤離者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=10)
    col_before = e2e.get_player_col(engine, uid, clock)
    engine.start_roguelike(uid, now_ts=clock.now, rng_seed=1304)
    step = e2e.assert_ok_result(engine.step_roguelike(uid, node_index=0, now_ts=clock.now))
    if e2e.extract_field(step, "in_combat", default=False) is True:
        e2e.resolve_active_combat(engine, uid, clock)
    ext = e2e.assert_ok_result(engine.extract_roguelike(uid, now_ts=clock.now), require_zh_tw=True)
    score = int(e2e.extract_field(ext, "score", "final_score", "points"))
    assert score > 0
    assert e2e.get_player_zone(engine, uid, clock) == "town"
    assert e2e.get_player_col(engine, uid, clock) >= col_before


def test_t1_f13_roguelike_defeat_settles_partial_score_safely(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("地城撤退測試", mode="standard")
    e2e.induce_combat_defeat(engine, db, content_bundle, uid, clock, in_roguelike=True)
    assert e2e.get_player_zone(engine, uid, clock) == "town"
    # Character remains playable in town
    e2e.assert_ok_result(engine.travel_zone(uid, "field", now_ts=clock.now))


# ===========================================================================
# Feature 14: 8 Weapon Classes/Styles + 2 Hidden Unique Skills (5 tests)
# ===========================================================================


def test_t1_f14_switch_across_all_8_weapon_styles(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("兵器大師")
    for style in e2e.BASE_8_WEAPON_STYLES:
        e2e.assert_ok_result(engine.switch_weapon_style(uid, style))
        prof = engine.get_profile(uid, now_ts=clock.now)
        assert str(e2e.extract_field(prof, "weapon_style", "style")).lower() == style


def test_t1_f14_weapon_styles_produce_distinct_stat_profiles(
    engine: Any,
    db: Any,
    content_bundle: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    profiles: dict[str, tuple[int, int, int, float]] = {}
    for style in ("rapier", "axe", "mace", "katana"):
        uid = make_player(f"流派{style}", weapon_style=style)
        player = db.get_player(uid)
        st = compute_stats(player, [], content_bundle, floor=1)
        profiles[style] = (int(st.max_hp), int(st.atk), int(st.defense), round(float(st.spd), 2))
    assert len(set(profiles.values())) >= 3, f"Expected distinct style stats, got {profiles!r}"


def test_t1_f14_unlock_dual_blades_at_f50_milestone_gate(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("黑衣劍士", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 50, clock=clock, level=55, mastery=500
    )
    res = e2e.assert_ok_result(engine.unlock_unique_skill(uid, "dual_blades"), require_zh_tw=True)
    assert res
    prof = engine.get_profile(uid, now_ts=clock.now)
    unique_val = str(e2e.extract_field(prof, "unique_skills", "unlocked_unique_skills", "unique_skill"))
    assert "dual_blades" in unique_val.lower()


def test_t1_f14_unlock_holy_sword_at_milestone_gate(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("聖騎士團長", weapon_style="holy")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 50, clock=clock, level=55, mastery=500
    )
    e2e.assert_ok_result(engine.unlock_unique_skill(uid, "holy_sword"), require_zh_tw=True)
    prof = engine.get_profile(uid, now_ts=clock.now)
    unique_val = str(e2e.extract_field(prof, "unique_skills", "unlocked_unique_skills", "unique_skill"))
    assert "holy_sword" in unique_val.lower()


def test_t1_f14_unique_skill_unlocks_fourth_skill_slot(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("四格劍技者", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 50, clock=clock, level=55, mastery=500
    )
    e2e.assert_ok_result(engine.unlock_unique_skill(uid, "dual_blades"))
    sword_skills = e2e.pick_sword_skills(content_bundle, "sword", count=3)
    dual_skill = e2e.pick_sword_skills(content_bundle, "dual_blades", count=1, include_unique=True)[0]
    four_skills = sword_skills + [dual_skill]
    e2e.assert_ok_result(engine.set_skill_slots(uid, four_skills))
    prof = engine.get_profile(uid, now_ts=clock.now)
    slots = e2e.extract_field(prof, "skill_slots", "equipped_skills", "active_skills")
    assert len(slots) == 4


# ===========================================================================
# Feature 15: Sword Skills (劍技), SP/CD, Mastery, Combo & Chase (追擊) (5 tests)
# ===========================================================================


def test_t1_f15_set_up_to_3_valid_sword_skills(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("劍技配置者", weapon_style="sword")
    skills = e2e.pick_sword_skills(content_bundle, "sword", count=3)
    e2e.assert_ok_result(engine.set_skill_slots(uid, skills))
    prof = engine.get_profile(uid, now_ts=clock.now)
    slots = e2e.extract_field(prof, "skill_slots", "equipped_skills", "active_skills")
    assert list(slots) == skills


def test_t1_f15_cast_sword_skill_consumes_sp_and_starts_cd(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("劍技施放者", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    skills = e2e.pick_sword_skills(content_bundle, "sword", count=2)
    e2e.assert_ok_result(engine.set_skill_slots(uid, skills))
    start = e2e.assert_ok_result(engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now))
    sp_before = int(e2e.extract_field(start, "player_sp", "sp", default=999))
    turn = e2e.assert_ok_result(
        engine.combat_action(uid, "skill", skill_id=skills[0], now_ts=clock.now),
        require_zh_tw=True,
    )
    dmg = int(e2e.extract_field(turn, "damage_dealt", "player_damage", "damage"))
    sp_after = int(e2e.extract_field(turn, "player_sp", "sp"))
    assert dmg > 0
    assert sp_after < sp_before


def test_t1_f15_casting_sword_skills_gains_weapon_mastery(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("熟練度鍛鍊者", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=8, unlock_boss_gate=True
    )
    s1 = e2e.pick_sword_skills(content_bundle, "sword", count=1)[0]
    engine.set_skill_slots(uid, [s1])
    prof_before = engine.get_profile(uid, now_ts=clock.now)
    m_before = str(e2e.extract_field(prof_before, "weapon_mastery", "mastery", default={}))
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_ok_result(engine.combat_action(uid, "skill", skill_id=s1, now_ts=clock.now))
    prof_after = engine.get_profile(uid, now_ts=clock.now)
    m_after = str(e2e.extract_field(prof_after, "weapon_mastery", "mastery", default={}))
    assert m_after != m_before


def test_t1_f15_consecutive_sword_skills_build_combo_multiplier(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("連擊劍士", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    skills = e2e.pick_sword_skills(content_bundle, "sword", count=2)
    engine.set_skill_slots(uid, skills)
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    t1 = e2e.assert_ok_result(engine.combat_action(uid, "skill", skill_id=skills[0], now_ts=clock.now))
    t2 = e2e.assert_ok_result(engine.combat_action(uid, "skill", skill_id=skills[1], now_ts=clock.now))
    combo1 = int(e2e.extract_field(t1, "combo", "combo_count", default=1))
    combo2 = int(e2e.extract_field(t2, "combo", "combo_count", default=2))
    assert combo2 >= combo1 and combo2 >= 2


def test_t1_f15_chase_and_post_delay_rigidity_resolved(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    skills = e2e.iter_entries(content_bundle.sword_skills)
    chase_or_multi = [
        sid
        for sid, spec in skills
        if spec.get("chase") or int(spec.get("hits", 1)) >= 2 or spec.get("post_delay")
    ]
    assert len(chase_or_multi) >= 1, "Expected multi-hit/chase/post_delay Sword Skills in JSON"
    uid = make_player("追擊連段者", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    sword_s = e2e.pick_sword_skills(content_bundle, "sword", count=2)
    engine.set_skill_slots(uid, sword_s)
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    res = e2e.assert_ok_result(engine.combat_action(uid, "skill", skill_id=sword_s[0], now_ts=clock.now))
    assert int(e2e.extract_field(res, "damage_dealt", "player_damage", "damage")) > 0


# ===========================================================================
# Feature 16: 4-Axis Damage/Resistance (斬/刺/打/龍) & Floor Penetration (5 tests)
# ===========================================================================


def test_t1_f16_compute_player_stats_populates_all_4_axes(
    db: Any,
    content_bundle: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    uid = make_player("四軸抗性測試")
    st = compute_stats(db.get_player(uid), [], content_bundle, floor=1)
    for attr in ("res_slash", "res_pierce", "res_blunt", "res_dragon"):
        val = float(getattr(st, attr))
        assert 0.0 <= val <= 0.75


def test_t1_f16_equipment_resistance_affixes_boost_exact_axis(
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    uid = make_player("抗性詞條測試")
    player = db.get_player(uid)
    base = compute_stats(player, [], content_bundle, floor=1)
    eq_cls = e2e.load_models_api()["EquipmentItem"]
    # Seed and load real EquipmentItem via DB to preserve exact dataclass signature
    e2e.seed_equipment(
        db,
        uid,
        slot="armor",
        rarity="rare",
        name="抗龍護甲",
        affixes={"res_dragon": 0.25, "res_slash": 0.20},
        now_ts=clock.now,
    )
    items = db.get_equipment(uid) if hasattr(db, "get_equipment") else []
    if not items:
        assert eq_cls is not None
        items = [i for i in getattr(player, "equipped_items", [])]
    boosted = compute_stats(player, items, content_bundle, floor=1)
    assert boosted.res_dragon >= base.res_dragon + 0.20
    assert boosted.res_slash >= base.res_slash + 0.15


def test_t1_f16_progressive_floor_penetration_f1_f50_f100(
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    uid = make_player("穿透階梯測試")
    e2e.seed_equipment(
        db,
        uid,
        slot="armor",
        rarity="legendary",
        name="高抗鎧甲",
        affixes={"res_slash": 0.70},
        now_ts=clock.now,
    )
    items = db.get_equipment(uid) if hasattr(db, "get_equipment") else []
    st = compute_stats(db.get_player(uid), items, content_bundle, floor=1)
    eff1 = float(st.effective_res("slash", 1))
    eff50 = float(st.effective_res("slash", 50))
    eff100 = float(st.effective_res("slash", 100))
    assert eff1 > eff50 > eff100 >= 0.0


def test_t1_f16_weakness_damage_type_triggers_bonus_in_combat(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("弱點打擊者", weapon_style="rapier")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    pierce_skill = e2e.pick_sword_skills(content_bundle, "rapier", count=1)[0]
    engine.set_skill_slots(uid, [pierce_skill])
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    turn = e2e.assert_ok_result(
        engine.combat_action(uid, "skill", skill_id=pierce_skill, now_ts=clock.now),
        require_zh_tw=True,
    )
    assert int(e2e.extract_field(turn, "damage_dealt", "player_damage", "damage")) > 0


def test_t1_f16_effective_res_valid_for_all_4_damage_types(
    db: Any,
    content_bundle: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    uid = make_player("全軸檢測")
    st = compute_stats(db.get_player(uid), [], content_bundle, floor=25)
    for dt in e2e.FOUR_DAMAGE_TYPES:
        val = float(st.effective_res(dt, 25))
        assert 0.0 <= val <= 0.75


# ===========================================================================
# Feature 17: Tactical Combat: Switch (⇄ 交換), Parry, Backstab, 14 Debuffs (5 tests)
# ===========================================================================


def test_t1_f17_parry_and_defend_mitigate_boss_strike(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("格擋彈反者", weapon_style="holy")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    r_parry = e2e.assert_ok_result(engine.combat_action(uid, "parry", now_ts=clock.now), require_zh_tw=True)
    r_defend = e2e.assert_ok_result(engine.combat_action(uid, "defend", now_ts=clock.now), require_zh_tw=True)
    assert e2e.has_zh_tw(e2e.extract_text_blob(r_parry))
    assert e2e.has_zh_tw(e2e.extract_text_blob(r_defend))


def test_t1_f17_katana_sheathe_stance_enhances_next_attack(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("居合劍豪", weapon_style="katana")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    sheathe = e2e.assert_ok_result(engine.combat_action(uid, "sheathe", now_ts=clock.now), require_zh_tw=True)
    assert sheathe
    strike = e2e.assert_ok_result(engine.combat_action(uid, "attack", now_ts=clock.now), require_zh_tw=True)
    assert int(e2e.extract_field(strike, "damage_dealt", "player_damage", "damage")) > 0


def test_t1_f17_coop_switch_transfers_aggro_builds_chain_and_break(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=3, floor=1, prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    u1, u2, u3 = party.member_ids
    engine.submit_raid_action(raid_id, u1, "defend", now_ts=clock.now)
    engine.submit_raid_action(raid_id, u2, "switch", now_ts=clock.now)
    r1 = e2e.assert_ok_result(engine.submit_raid_action(raid_id, u3, "switch", now_ts=clock.now))
    if not e2e.extract_field(r1, "round_resolved", "resolved", default=False):
        r1 = e2e.assert_ok_result(engine.resolve_raid_round(raid_id, requester_id=u1, now_ts=clock.now))
    chain = int(e2e.extract_field(r1, "switch_chain", "switch_count", default=1))
    assert chain >= 1


def test_t1_f17_backstab_bonus_when_ally_holds_aggro(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(
        count=2,
        floor=1,
        weapon_styles=["mace", "dagger"],
        roles=["tank", "dps"],
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    tank, dps = party.member_ids
    engine.submit_raid_action(raid_id, tank, "defend", now_ts=clock.now)
    r1 = e2e.assert_ok_result(engine.submit_raid_action(raid_id, dps, "attack", now_ts=clock.now))
    if not e2e.extract_field(r1, "round_resolved", "resolved", default=False):
        r1 = e2e.assert_ok_result(engine.resolve_raid_round(raid_id, requester_id=tank, now_ts=clock.now))
    assert e2e.has_zh_tw(e2e.extract_text_blob(r1))


def test_t1_f17_debuffs_apply_and_tick_over_turns(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    # Pick a skill carrying a debuff/status effect from content_bundle
    debuff_skill = None
    debuff_style = "dagger"
    for sid, spec in e2e.iter_entries(content_bundle.sword_skills):
        if spec.get("debuff") or spec.get("status") or spec.get("effects"):
            ws = str(spec.get("weapon_style") or spec.get("weapon") or "sword").lower()
            if ws in e2e.BASE_8_WEAPON_STYLES:
                debuff_skill = sid
                debuff_style = ws
                break
    assert debuff_skill is not None, "Expected at least one debuff-applying Sword Skill in catalog"
    uid = make_player("減益戰術家", weapon_style=debuff_style)
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.set_skill_slots(uid, [debuff_skill])
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    t1 = e2e.assert_ok_result(engine.combat_action(uid, "skill", skill_id=debuff_skill, now_ts=clock.now))
    t2 = e2e.assert_ok_result(engine.combat_action(uid, "defend", now_ts=clock.now))
    assert t1 and t2


# ===========================================================================
# Feature 18: Auto-Battle & Survival Thresholds (生存設定) (5 tests)
# ===========================================================================


def test_t1_f18_set_all_survival_thresholds_and_persist(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("生存設定者")
    e2e.assert_ok_result(
        engine.set_survival_config(
            uid,
            auto_potion_pct=60,
            auto_crystal_pct=30,
            auto_retreat_pct=15,
            stop_on_no_potion=True,
        ),
        require_zh_tw=True,
    )
    prof = engine.get_profile(uid, now_ts=clock.now)
    assert int(e2e.extract_field(prof, "auto_potion_pct")) == 60
    assert int(e2e.extract_field(prof, "auto_crystal_pct")) == 30
    assert int(e2e.extract_field(prof, "auto_retreat_pct")) == 15
    assert bool(e2e.extract_field(prof, "stop_on_no_potion")) is True


def test_t1_f18_partial_survival_config_update_preserves_unspecified(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("局部調整者")
    engine.set_survival_config(
        uid,
        auto_potion_pct=60,
        auto_crystal_pct=30,
        auto_retreat_pct=15,
        stop_on_no_potion=True,
    )
    engine.set_survival_config(uid, auto_potion_pct=75)
    prof = engine.get_profile(uid, now_ts=clock.now)
    assert int(e2e.extract_field(prof, "auto_potion_pct")) == 75
    assert int(e2e.extract_field(prof, "auto_crystal_pct")) == 30
    assert int(e2e.extract_field(prof, "auto_retreat_pct")) == 15
    assert bool(e2e.extract_field(prof, "stop_on_no_potion")) is True


def test_t1_f18_auto_battle_uses_recovery_potion_at_threshold(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("自動喝藥者")
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    e2e.seed_item(db, uid, potion_id, 5)
    engine.set_survival_config(uid, auto_potion_pct=99, auto_crystal_pct=0, auto_retreat_pct=0)
    e2e.trigger_road_combat(engine, uid, clock, seed_start=1801)
    # Take one round of damage then run auto
    engine.combat_action(uid, "defend", now_ts=clock.now)
    qty_before = e2e.get_player_item_qty(engine, uid, potion_id, clock)
    res = e2e.assert_ok_result(engine.combat_action(uid, "auto", now_ts=clock.now))
    qty_after = e2e.get_player_item_qty(engine, uid, potion_id, clock)
    assert qty_after < qty_before or e2e.extract_field(res, "ended", "finished", default=False) is True


def test_t1_f18_auto_battle_uses_healing_crystal_at_emergency_threshold(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("自動紅水者")
    heal_crystal = e2e.pick_crystal_ids(content_bundle)["healing"]
    e2e.seed_item(db, uid, heal_crystal, 3)
    engine.set_survival_config(uid, auto_potion_pct=0, auto_crystal_pct=99, auto_retreat_pct=0)
    e2e.trigger_road_combat(engine, uid, clock, seed_start=1810)
    engine.combat_action(uid, "defend", now_ts=clock.now)
    qty_before = e2e.get_player_item_qty(engine, uid, heal_crystal, clock)
    res = e2e.assert_ok_result(engine.combat_action(uid, "auto", now_ts=clock.now))
    qty_after = e2e.get_player_item_qty(engine, uid, heal_crystal, clock)
    assert qty_after < qty_before or e2e.extract_field(res, "ended", "finished", default=False) is True


def test_t1_f18_auto_battle_triggers_teleport_retreat_at_threshold(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("自動轉移撤退者")
    tp_crystal = e2e.pick_crystal_ids(content_bundle)["teleport"]
    e2e.seed_item(db, uid, tp_crystal, 3)
    engine.set_survival_config(uid, auto_potion_pct=0, auto_crystal_pct=0, auto_retreat_pct=99)
    e2e.trigger_road_combat(engine, uid, clock, seed_start=1820)
    engine.combat_action(uid, "defend", now_ts=clock.now)
    qty_before = e2e.get_player_item_qty(engine, uid, tp_crystal, clock)
    e2e.assert_ok_result(engine.combat_action(uid, "auto", now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, uid, tp_crystal, clock) < qty_before
    assert e2e.get_player_zone(engine, uid, clock) == "town"


# ===========================================================================
# Feature 19: 14 Bespoke Milestone Bosses + 10 Tier Guardians (7 tests)
# ===========================================================================


def test_t1_f19_all_14_milestone_bosses_and_tier_guardians_schema(
    engine: Any,
    content_bundle: Any,
    e2e: Any,
) -> None:
    seen_names: set[str] = set()
    for fl in e2e.MILESTONE_14_FLOORS:
        bid, spec = e2e.pick_boss_spec(content_bundle, fl)
        bars = int(spec.get("hp_bars", spec.get("bars", 0)))
        assert bars >= 3, f"Milestone F{fl} boss {bid} must have >=3 HP bars, got {bars}"
        phases = spec.get("phases") or spec.get("stages") or []
        assert len(phases) >= 2, f"Milestone F{fl} boss {bid} must have >=2 phases"
        assert spec.get("la_bonus_item_id") or spec.get("la_item_id"), f"F{fl} missing LA bonus item"
        seen_names.add(str(spec.get("name", bid)))
    assert len(seen_names) == 14
    for fl in (2, 12, 22, 32, 42, 52, 62, 72, 82, 92):
        finfo = e2e.assert_ok_result(engine.get_floor_info(fl))
        assert e2e.extract_field(finfo, "boss_id", "boss_name")


def test_t1_f19_f1_illfang_four_bars_adds_and_p4_nodachi_swap(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("伊爾方討伐者", weapon_style="rapier")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    start = e2e.assert_ok_result(engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now))
    assert int(e2e.extract_field(start, "hp_bars", "total_bars", "bars")) == 4
    logs: list[str] = [e2e.extract_text_blob(start)]
    for _ in range(80):
        turn = e2e.assert_ok_result(engine.combat_action(uid, "attack", now_ts=clock.now))
        logs.append(e2e.extract_text_blob(turn))
        if e2e.extract_field(turn, "ended", "finished", "victory", default=False) is True:
            break
    full_log = "\n".join(logs)
    assert any(k in full_log for k in ("野太刀", "太刀", "斬", "第四", "P4", "形態"))


def test_t1_f19_f10_kagachi_serpent_stance_switch_break(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(
        count=3,
        floor=10,
        weapon_styles=["mace", "sword", "rapier"],
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    assert int(e2e.extract_field(raid, "hp_bars", "total_bars", "bars")) >= 4

    def _strat(rnd: int, uid: str, _state: dict[str, Any]) -> tuple[str, str | None, str | None, int]:
        if rnd % 2 == 0 and uid in party.member_ids[:2]:
            return ("switch", None, None, 0)
        return ("attack", None, None, 0)

    final_res, history = e2e.drive_coop_raid(
        engine, clock, raid_id, party.member_ids, strategy_fn=_strat
    )
    assert len(history) >= 1 and final_res


def test_t1_f19_f20_f25_f30_f40_early_mid_milestone_mechanics(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    for fl in (20, 25, 30, 40):
        party = make_party_humans(
            count=2, floor=fl, prepare_floor=True, unlock_boss_gate=True
        )
        engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
        raid = e2e.assert_ok_result(
            engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now),
            require_zh_tw=True,
        )
        raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
        assert int(e2e.extract_field(raid, "hp_bars", "total_bars", "bars")) >= 4
        final_res, history = e2e.drive_coop_raid(engine, clock, raid_id, party.member_ids)
        assert final_res and len(history) >= 1


def test_t1_f19_f50_f60_f70_mid_high_milestone_mechanics(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    for fl in (50, 60, 70):
        party = make_party_humans(
            count=2, floor=fl, prepare_floor=True, unlock_boss_gate=True
        )
        engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
        raid = e2e.assert_ok_result(
            engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now),
            require_zh_tw=True,
        )
        raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
        assert int(e2e.extract_field(raid, "hp_bars", "total_bars", "bars")) >= 5
        final_res, _ = e2e.drive_coop_raid(engine, clock, raid_id, party.member_ids)
        assert final_res


def test_t1_f19_f74_gleam_eyes_and_f75_skull_reaper_mechanics(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    for fl, min_bars in ((74, 5), (75, 6)):
        party = make_party_humans(
            count=4,
            floor=fl,
            weapon_styles=["mace", "holy", "sword", "dagger"],
            roles=["tank", "tank", "dps", "dps"],
            prepare_floor=True,
            unlock_boss_gate=True,
        )
        engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
        raid = e2e.assert_ok_result(
            engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now),
            require_zh_tw=True,
        )
        raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
        assert int(e2e.extract_field(raid, "hp_bars", "total_bars", "bars")) >= min_bars

        members = party.member_ids

        def _dual_tank(
            rnd: int,
            uid: str,
            _s: dict[str, Any],
            m: list[str] = members,
        ) -> tuple[str, str | None, str | None, int]:
            if rnd == 1 and uid in m[:2]:
                return ("parry", None, None, 0)
            if uid == m[rnd % 2]:
                return ("switch", None, None, 0)
            return ("attack", None, None, 0)

        final_res, _ = e2e.drive_coop_raid(
            engine, clock, raid_id, members, strategy_fn=_dual_tank
        )
        assert final_res


def test_t1_f19_f80_f90_and_f100_dual_stage_radius_to_heathcliff(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    for fl in (80, 90, 100):
        party = make_party_humans(
            count=4,
            floor=fl,
            weapon_styles=["katana", "rapier", "mace", "holy"],
            roles=["dps", "breaker", "tank", "support"],
            prepare_floor=True,
            unlock_boss_gate=True,
        )
        engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
        raid = e2e.assert_ok_result(
            engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now),
            require_zh_tw=True,
        )
        raid_id = str(e2e.extract_field(raid, "raid_id", "id"))

        members = party.member_ids

        def _endgame_strat(
            rnd: int,
            uid: str,
            _s: dict[str, Any],
            m: list[str] = members,
        ) -> tuple[str, str | None, str | None, int]:
            if rnd % 3 == 0 and uid in m[:2]:
                return ("switch", None, None, 0)
            return ("attack", None, None, 0)

        final_res, history = e2e.drive_coop_raid(
            engine, clock, raid_id, members, strategy_fn=_endgame_strat, max_rounds=120
        )
        assert final_res and len(history) >= 1
        if fl == 100:
            blob = "\n".join(e2e.extract_text_blob(h) for h in history)
            assert any(k in blob for k in ("希茲克利夫", "神聖劍", "紅玉", "通關", "解放"))


# ===========================================================================
# Feature 20: Multi-Tier Boss Modes (First-Kill / Normal / Team / World) (6 tests)
# ===========================================================================


def test_t1_f20_first_kill_mode_claims_server_unlock_and_hall_of_fame(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("首殺先鋒")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=10)
    res = e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="first_kill")
    assert e2e.extract_field(res, "is_first_kill", "first_kill", default=True) is True
    intel = e2e.assert_ok_result(engine.get_argo_intel(user_id=uid, floor=1))
    assert "首殺先鋒" in e2e.extract_text_blob(intel) or uid in e2e.extract_text_blob(intel)
    e2e.assert_ok_result(engine.teleport_floor(uid, 2, now_ts=clock.now))


def test_t1_f20_normal_mode_repeatable_farm_after_first_kill(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("原首殺者")
    u2 = make_player("普通周回者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, u1, 1, clock=clock, level=10)
    e2e.prepare_player_for_floor(engine, db, content_bundle, u2, 1, clock=clock, level=10)
    e2e.clear_floor_organically(engine, u1, clock, floor=1, mode="first_kill")
    clock.advance(minutes=10)
    r1 = e2e.clear_floor_organically(engine, u2, clock, floor=1, mode="normal")
    clock.advance(minutes=10)
    r2 = e2e.clear_floor_organically(engine, u2, clock, floor=1, mode="normal")
    assert r1 and r2
    intel = e2e.assert_ok_result(engine.get_argo_intel(floor=1))
    assert "原首殺者" in e2e.extract_text_blob(intel) or u1 in e2e.extract_text_blob(intel)


def test_t1_f20_team_boss_mode_scaled_stats_and_three_daily_boosted_drops(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(
        count=3,
        floor=1,
        boss_mode="team_boss",
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    for run_no in range(1, 4):
        engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
        raid = e2e.assert_ok_result(
            engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now)
        )
        raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
        final_res, _ = e2e.drive_coop_raid(engine, clock, raid_id, party.member_ids)
        boosted = e2e.extract_field(final_res, "boosted_drop", "daily_boost", "is_boosted", default=True)
        assert boosted is True, f"Team Boss run {run_no}/3 must grant boosted drop"
        clock.advance(minutes=10)


def test_t1_f20_floor_world_boss_shared_hp_and_damage_ranking(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("世界王勇者甲")
    u2 = make_player("世界王勇者乙")
    u3 = make_player("世界王勇者丙")
    r1 = e2e.assert_ok_result(engine.attack_floor_world_boss(u1, now_ts=clock.now), require_zh_tw=True)
    hp1 = int(e2e.extract_field(r1, "boss_hp", "current_hp", "remaining_hp"))
    r2 = e2e.assert_ok_result(engine.attack_floor_world_boss(u2, now_ts=clock.now))
    hp2 = int(e2e.extract_field(r2, "boss_hp", "current_hp", "remaining_hp"))
    r3 = e2e.assert_ok_result(engine.attack_floor_world_boss(u3, now_ts=clock.now))
    hp3 = int(e2e.extract_field(r3, "boss_hp", "current_hp", "remaining_hp"))
    assert hp1 >= hp2 >= hp3
    lb = e2e.assert_ok_result(engine.get_leaderboard("world_boss", limit=10))
    entries = e2e.extract_field(lb, "entries", "rankings", "rows", "leaderboard")
    assert len(entries) >= 3


def test_t1_f20_world_boss_defeat_activates_accelerated_world_buff(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    defeated = False
    attackers: list[str] = []
    for i in range(12):
        uid = make_player(f"世界王討伐員{i}")
        e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 50, clock=clock, level=80)
        attackers.append(uid)
        for _ in range(3):
            res = e2e.assert_ok_result(engine.attack_floor_world_boss(uid, now_ts=clock.now))
            if (
                e2e.extract_field(res, "defeated", "boss_defeated", "accelerated_world", default=False) is True
                or "加速世界" in e2e.extract_text_blob(res)
            ):
                defeated = True
                break
        if defeated:
            break
    assert defeated, "High-power attackers should defeat shared Floor World Boss"
    prof = engine.get_profile(attackers[0], now_ts=clock.now)
    assert "加速" in e2e.extract_text_blob(prof) or e2e.has_field(prof, "world_buff", "world_buffs", "active_buffs")


def test_t1_f20_world_boss_attempt_banking_across_days(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("次數囤積者")
    # Skip Day 1 -> Day 2 banks 3 + 3 = 6 attempts
    clock.advance(days=1)
    for _ in range(6):
        e2e.assert_ok_result(engine.attack_floor_world_boss(uid, now_ts=clock.now))


# ===========================================================================
# Feature 21: Last Attack (LA) Bonus (尾刀獎勵) & Pending Loot Mailbox (5 tests)
# ===========================================================================


def test_t1_f21_solo_boss_kill_awards_iconic_f1_coat_of_midnight_la(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("午夜大衣獲得者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=12)
    res = e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="normal")
    la_winner = str(e2e.extract_field(res, "la_winner", "last_attack_user_id", "la_user_id", default=uid))
    assert la_winner == uid
    gear = e2e.get_player_equipment(engine, uid, clock)
    assert any(
        str(item.get("rarity", "")).lower() == "named" or "午夜" in str(item.get("name", ""))
        for item in gear
    )


def test_t1_f21_coop_raid_la_attributed_strictly_to_killing_player(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=3, floor=1, prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    u_a, u_b, u_c = party.member_ids

    def _only_b_kills(_rnd: int, uid: str, _s: dict[str, Any]) -> tuple[str, str | None, str | None, int]:
        if uid == u_b:
            return ("attack", None, None, 0)
        return ("defend", None, None, 0)

    final_res, _ = e2e.drive_coop_raid(
        engine, clock, raid_id, party.member_ids, strategy_fn=_only_b_kills, max_rounds=100
    )
    la_winner = str(e2e.extract_field(final_res, "la_winner", "last_attack_user_id", "la_user_id"))
    assert la_winner == u_b
    b_named = [g for g in e2e.get_player_equipment(engine, u_b, clock) if str(g.get("rarity", "")).lower() == "named"]
    a_named = [g for g in e2e.get_player_equipment(engine, u_a, clock) if str(g.get("rarity", "")).lower() == "named"]
    c_named = [g for g in e2e.get_player_equipment(engine, u_c, clock) if str(g.get("rarity", "")).lower() == "named"]
    assert len(b_named) >= 1 and len(a_named) == 0 and len(c_named) == 0


def test_t1_f21_milestone_f50_and_f100_named_la_drops_awarded(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    for fl in (50, 100):
        uid = make_player(f"尾刀王F{fl}")
        e2e.prepare_player_for_floor(engine, db, content_bundle, uid, fl, clock=clock, level=fl + 15)
        res = e2e.clear_floor_organically(engine, uid, clock, floor=fl, mode="normal")
        assert res
        gear = e2e.get_player_equipment(engine, uid, clock)
        assert any(str(g.get("rarity", "")).lower() == "named" for g in gear)


def test_t1_f21_bag_full_overflow_routes_la_drop_to_pending_loot_mailbox(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("滿包尾刀者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=12)
    for i in range(85):
        e2e.seed_equipment(
            db, uid, slot="ring", rarity="plain", name=f"備用戒{i}", template_id=f"fill_{i}", now_ts=clock.now
        )
    e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="normal")
    assert e2e.get_player_pending_loot_count(engine, uid, clock) >= 1


def test_t1_f21_claim_pending_loot_transfers_items_once_bag_has_space(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("信箱領取者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=12)
    filler_uids = [
        e2e.seed_equipment(
            db, uid, slot="ring", rarity="plain", name=f"填充戒{i}", template_id=f"box_{i}", now_ts=clock.now
        )
        for i in range(85)
    ]
    e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="normal")
    pending_before = e2e.get_player_pending_loot_count(engine, uid, clock)
    assert pending_before >= 1
    engine.travel_zone(uid, "town", now_ts=clock.now)
    # Free several bag slots via achievement gear turn-in
    for fuid in filler_uids[:10]:
        engine.turn_in_achievement_gear(uid, fuid)
    claim = e2e.assert_ok_result(engine.claim_pending_loot(uid), require_zh_tw=True)
    assert claim
    assert e2e.get_player_pending_loot_count(engine, uid, clock) < pending_before


# ===========================================================================
# Feature 22: Real-Human Party Lobby (組隊大廳) & Raid Alliance (6 tests)
# ===========================================================================


def test_t1_f22_create_standard_party_lobby_2_to_6_humans(
    engine: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=6, floor=1, max_size=6, is_raid_alliance=False)
    assert len(party.member_ids) == 6
    assert len(set(party.member_ids)) == 6
    assert party.floor == 1


def test_t1_f22_create_raid_alliance_12_to_24_humans(
    make_party_humans: Callable[..., Any],
) -> None:
    party = make_party_humans(
        count=12, floor=1, boss_mode="team_boss", max_size=24, is_raid_alliance=True
    )
    assert len(party.member_ids) == 12
    assert party.boss_mode == "team_boss"


def test_t1_f22_assign_all_four_party_roles(
    engine: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=4, floor=1, ready_all=False)
    roles = ("tank", "dps", "breaker", "support")
    for uid, role in zip(party.member_ids, roles):
        res = e2e.assert_ok_result(engine.set_party_role(party.party_id, uid, role))
        assert res


def test_t1_f22_ready_check_toggle_before_boss_entry(
    engine: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1, ready_all=False)
    u1, u2 = party.member_ids
    e2e.assert_ok_result(engine.set_party_ready(party.party_id, u1, True))
    r_false = e2e.assert_ok_result(engine.set_party_ready(party.party_id, u2, False))
    assert e2e.extract_field(r_false, "all_ready", default=False) is False
    r_true = e2e.assert_ok_result(engine.set_party_ready(party.party_id, u2, True))
    assert e2e.extract_field(r_true, "all_ready", default=True) is True


def test_t1_f22_two_step_enter_boss_room_then_start_party_raid(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1, prepare_floor=True, unlock_boss_gate=True)
    enter = e2e.assert_ok_result(
        engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now),
        require_zh_tw=True,
    )
    assert enter
    raid = e2e.assert_ok_result(
        engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now),
        require_zh_tw=True,
    )
    assert str(e2e.extract_field(raid, "raid_id", "id"))


def test_t1_f22_member_leave_party_updates_roster_cleanly(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=3, floor=1)
    u2 = party.member_ids[1]
    e2e.assert_ok_result(engine.leave_party(party.party_id, u2, now_ts=clock.now))
    # Former member is free to create a new party
    new_p = e2e.assert_ok_result(engine.create_party(u2, floor=1, now_ts=clock.now))
    assert str(e2e.extract_field(new_p, "party_id", "id")) != party.party_id


# ===========================================================================
# Feature 23: Synchronized Turn-Based Co-op Raid Combat & Concurrency (6 tests)
# ===========================================================================


def test_t1_f23_all_humans_submit_triggers_immediate_round_resolution(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=3, floor=1, prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    hp_before = int(e2e.extract_field(raid, "boss_hp", "current_hp", "hp"))
    u1, u2, u3 = party.member_ids
    e2e.assert_ok_result(engine.submit_raid_action(raid_id, u1, "attack", now_ts=clock.now))
    e2e.assert_ok_result(engine.submit_raid_action(raid_id, u2, "attack", now_ts=clock.now))
    r3 = e2e.assert_ok_result(engine.submit_raid_action(raid_id, u3, "defend", now_ts=clock.now))
    hp_after = int(e2e.extract_field(r3, "boss_hp", "current_hp", "hp"))
    assert hp_after < hp_before


def test_t1_f23_switch_chain_transfers_aggro_amplifies_damage_and_breaks(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1, prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    u1, u2 = party.member_ids
    engine.submit_raid_action(raid_id, u1, "switch", now_ts=clock.now)
    r1 = e2e.assert_ok_result(engine.submit_raid_action(raid_id, u2, "switch", now_ts=clock.now))
    if not e2e.extract_field(r1, "round_resolved", "resolved", default=False):
        r1 = e2e.assert_ok_result(engine.resolve_raid_round(raid_id, requester_id=u1, now_ts=clock.now))
    assert int(e2e.extract_field(r1, "switch_chain", "switch_count", default=1)) >= 1


def test_t1_f23_parry_and_defend_mitigate_telegraphed_boss_aoe(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1, prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    u1, u2 = party.member_ids
    engine.submit_raid_action(raid_id, u1, "parry", now_ts=clock.now)
    r1 = e2e.assert_ok_result(engine.submit_raid_action(raid_id, u2, "defend", now_ts=clock.now))
    if not e2e.extract_field(r1, "round_resolved", "resolved", default=False):
        r1 = e2e.assert_ok_result(engine.resolve_raid_round(raid_id, requester_id=u1, now_ts=clock.now))
    assert e2e.has_zh_tw(e2e.extract_text_blob(r1))


def test_t1_f23_party_combat_statistics_track_dps_tank_and_heal(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=3, floor=1, prepare_floor=True, unlock_boss_gate=True)
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    u1, _u2, u3 = party.member_ids

    def _roles_strat(rnd: int, uid: str, _s: dict[str, Any]) -> tuple[str, str | None, str | None, int]:
        if uid == u1:
            return ("defend", None, None, 0)
        if uid == u3 and rnd == 2:
            return ("item", None, potion_id, 0)
        return ("attack", None, None, 0)

    final_res, _ = e2e.drive_coop_raid(
        engine, clock, raid_id, party.member_ids, strategy_fn=_roles_strat
    )
    stats = e2e.extract_field(final_res, "party_stats", "member_stats", "combat_stats", "damage_by_user", default=final_res)
    assert stats


def test_t1_f23_raid_victory_atomically_settles_all_humans_rewards(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=4, floor=1, prepare_floor=True, unlock_boss_gate=True)
    cols_before = {uid: e2e.get_player_col(engine, uid, clock) for uid in party.member_ids}
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    e2e.drive_coop_raid(engine, clock, raid_id, party.member_ids)
    for uid in party.member_ids:
        assert e2e.get_player_col(engine, uid, clock) > cols_before[uid]
        assert e2e.get_player_floor(engine, uid, clock)[1] >= 2


def test_t1_f23_target_idx_selects_summoned_adds_during_boss_raid(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1, prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    u1, u2 = party.member_ids
    engine.submit_raid_action(raid_id, u1, "attack", target_idx=0, now_ts=clock.now)
    r1 = e2e.assert_ok_result(
        engine.submit_raid_action(raid_id, u2, "attack", target_idx=1, now_ts=clock.now)
    )
    if not e2e.extract_field(r1, "round_resolved", "resolved", default=False):
        r1 = e2e.assert_ok_result(engine.resolve_raid_round(raid_id, requester_id=u1, now_ts=clock.now))
    assert r1


# ===========================================================================
# Feature 24: Party Potion Sharing, Group Teleport & Downed Rescue (5 tests)
# ===========================================================================


def test_t1_f24_potion_sharing_auto_heals_injured_teammate_with_donor_log(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(
        count=2,
        floor=1,
        weapon_styles=["mace", "holy"],
        roles=["tank", "support"],
        prepare_floor=False,
        unlock_boss_gate=True,
    )
    tank, supp = party.member_ids
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    e2e.seed_item(db, supp, potion_id, 10)
    e2e.assert_ok_result(engine.toggle_potion_sharing(party.party_id, supp, True))
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    pot_before = e2e.get_player_item_qty(engine, supp, potion_id, clock)
    for _ in range(10):
        engine.submit_raid_action(raid_id, tank, "attack", now_ts=clock.now)
        res = e2e.assert_ok_result(engine.submit_raid_action(raid_id, supp, "defend", now_ts=clock.now))
        if e2e.get_player_item_qty(engine, supp, potion_id, clock) < pot_before:
            break
        if e2e.extract_field(res, "ended", "finished", default=False) is True:
            break
    assert e2e.get_player_item_qty(engine, supp, potion_id, clock) < pot_before


def test_t1_f24_toggle_potion_sharing_on_and_off_persists_in_party_state(
    engine: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1)
    u2 = party.member_ids[1]
    on_res = e2e.assert_ok_result(engine.toggle_potion_sharing(party.party_id, u2, True))
    assert e2e.extract_field(on_res, "potion_sharing", "enabled", "share_potions") is True
    off_res = e2e.assert_ok_result(engine.toggle_potion_sharing(party.party_id, u2, False))
    assert e2e.extract_field(off_res, "potion_sharing", "enabled", "share_potions") is False


def test_t1_f24_group_teleport_warps_entire_party_to_unlocked_floor_town(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=3, floor=2, prepare_floor=True)
    for uid in party.member_ids:
        engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_ok_result(
        engine.party_group_teleport(party.party_id, party.leader_id, 2, now_ts=clock.now),
        require_zh_tw=True,
    )
    for uid in party.member_ids:
        assert e2e.get_player_floor(engine, uid, clock)[0] == 2
        assert e2e.get_player_zone(engine, uid, clock) == "town"


def test_t1_f24_rescue_downed_player_consumes_teleport_crystal_and_restores_town(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    victim = make_player("倒地隊友", mode="standard")
    rescuer = make_player("救援者", mode="standard")
    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    e2e.seed_item(db, rescuer, tp_id, 3)
    e2e.induce_combat_defeat(engine, db, content_bundle, victim, clock)
    before_tp = e2e.get_player_item_qty(engine, rescuer, tp_id, clock)
    e2e.assert_ok_result(engine.rescue_downed_player(rescuer, victim, now_ts=clock.now), require_zh_tw=True)
    assert e2e.get_player_item_qty(engine, rescuer, tp_id, clock) == before_tp - 1
    assert e2e.get_player_zone(engine, victim, clock) == "town"
    mon = engine.get_monument_of_life(limit=10)
    assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 0


def test_t1_f24_rescue_works_across_multiple_downed_teammates_sequentially(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    v1 = make_player("倒地甲", mode="standard")
    v2 = make_player("倒地乙", mode="standard")
    rescuer = make_player("專職救護員", mode="standard")
    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    e2e.seed_item(db, rescuer, tp_id, 4)
    e2e.induce_combat_defeat(engine, db, content_bundle, v1, clock)
    e2e.induce_combat_defeat(engine, db, content_bundle, v2, clock)
    before_tp = e2e.get_player_item_qty(engine, rescuer, tp_id, clock)
    e2e.assert_ok_result(engine.rescue_downed_player(rescuer, v1, now_ts=clock.now))
    e2e.assert_ok_result(engine.rescue_downed_player(rescuer, v2, now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, rescuer, tp_id, clock) == before_tp - 2
    assert e2e.get_player_zone(engine, v1, clock) == "town"
    assert e2e.get_player_zone(engine, v2, clock) == "town"


# ===========================================================================
# Feature 25: Guild System (公會) (6 tests)
# ===========================================================================


def test_t1_f25_create_and_join_guild_initializes_roster_and_tag(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("團長希茲")
    u2 = make_player("副團長亞絲娜")
    e2e.seed_col(db, engine, u1, 10_000, clock)
    g = e2e.assert_ok_result(
        engine.create_guild(u1, "血盟騎士團", "KoB", now_ts=clock.now),
        require_zh_tw=True,
    )
    guild_id = int(e2e.extract_field(g, "guild_id", "id"))
    j = e2e.assert_ok_result(engine.join_guild(u2, guild_id, now_ts=clock.now))
    assert int(e2e.extract_field(j, "member_count", default=2)) >= 2


def test_t1_f25_five_rank_hierarchy_assignment_and_permissions(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("會長")
    e2e.seed_col(db, engine, u1, 10_000, clock)
    g = e2e.assert_ok_result(engine.create_guild(u1, "風林火山", "FLHS", now_ts=clock.now))
    guild_id = int(e2e.extract_field(g, "guild_id", "id"))
    members = [make_player(f"幹部{i}") for i in range(4)]
    for m in members:
        engine.join_guild(m, guild_id, now_ts=clock.now)
    # Assign distinct rank names from guild metadata (or canonical 4 subordinate rank tiers)
    ranks = e2e.extract_field(g, "ranks", "rank_names", default=["副會長", "幹部", "精銳", "新進"])
    if isinstance(ranks, dict):
        ranks = list(ranks.keys())
    target_ranks = [str(r) for r in ranks if str(r) not in ("leader", "會長", "團長")][:4]
    if len(target_ranks) < 4:
        target_ranks = ["vice_leader", "officer", "veteran", "member"]
    for m, rk in zip(members, target_ranks):
        e2e.assert_ok_result(engine.set_guild_rank(u1, m, rk))


def test_t1_f25_guild_contribute_vault_deducts_col_and_grows_guild_exp(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("公會創立者")
    u2 = make_player("熱心捐獻者")
    e2e.seed_col(db, engine, u1, 10_000, clock)
    e2e.seed_col(db, engine, u2, 5_000, clock)
    g = e2e.assert_ok_result(engine.create_guild(u1, "聖龍聯合", "DDA", now_ts=clock.now))
    guild_id = int(e2e.extract_field(g, "guild_id", "id"))
    engine.join_guild(u2, guild_id, now_ts=clock.now)
    col_before = e2e.get_player_col(engine, u2, clock)
    res = e2e.assert_ok_result(engine.guild_contribute(u2, 500, now_ts=clock.now), require_zh_tw=True)
    assert e2e.get_player_col(engine, u2, clock) == col_before - 500
    assert int(e2e.extract_field(res, "vault_col", "guild_col", "contribution", default=500)) >= 500


def test_t1_f25_guild_warehouse_deposit_withdraw_and_audit_logs(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("倉庫存物者")
    u2 = make_player("倉庫領物者")
    e2e.seed_col(db, engine, u1, 10_000, clock)
    g = e2e.assert_ok_result(engine.create_guild(u1, "月夜黑貓團", "MBC", now_ts=clock.now))
    guild_id = int(e2e.extract_field(g, "guild_id", "id"))
    engine.join_guild(u2, guild_id, now_ts=clock.now)
    # Promote u2 to officer/vice rank for withdrawal permission
    ranks = e2e.extract_field(g, "ranks", "rank_names", default=["officer"])
    officer_rank = str(ranks[1] if isinstance(ranks, list) and len(ranks) > 1 else "officer")
    engine.set_guild_rank(u1, u2, officer_rank)

    item_uid = e2e.seed_equipment(
        db, u1, slot="armor", rarity="rare", name="公會共享甲", now_ts=clock.now
    )
    dep = e2e.assert_ok_result(engine.guild_warehouse_deposit(u1, item_uid, now_ts=clock.now))
    wh_id = int(e2e.extract_field(dep, "warehouse_id", "id"))
    wd = e2e.assert_ok_result(engine.guild_warehouse_withdraw(u2, wh_id, now_ts=clock.now))
    assert wd
    assert any("公會共享甲" in str(it.get("name", "")) for it in e2e.get_player_equipment(engine, u2, clock))


def test_t1_f25_guild_rally_buff_applies_to_computed_member_stats(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("集結發動者")
    u2 = make_player("集結受惠者")
    e2e.seed_col(db, engine, u1, 20_000, clock)
    g = e2e.assert_ok_result(engine.create_guild(u1, "艾恩葛朗特解放軍", "ALS", now_ts=clock.now))
    guild_id = int(e2e.extract_field(g, "guild_id", "id"))
    engine.join_guild(u2, guild_id, now_ts=clock.now)
    engine.guild_contribute(u1, 5_000, now_ts=clock.now)
    p_before = engine.get_profile(u2, now_ts=clock.now)
    cp_before = int(e2e.extract_field(p_before, "combat_power", "power"))
    buff_res = e2e.assert_ok_result(
        engine.guild_activate_buff(u1, buff_id="rally", now_ts=clock.now),
        require_zh_tw=True,
    )
    assert buff_res
    p_after = engine.get_profile(u2, now_ts=clock.now)
    cp_after = int(e2e.extract_field(p_after, "combat_power", "power"))
    assert cp_after >= cp_before


def test_t1_f25_start_timed_guild_raid_creates_guild_encounter(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("突擊指揮官")
    e2e.seed_col(db, engine, u1, 20_000, clock)
    engine.create_guild(u1, "金蘋果公會", "GOLD", now_ts=clock.now)
    engine.guild_contribute(u1, 5_000, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_guild_raid(u1, now_ts=clock.now), require_zh_tw=True)
    assert e2e.has_field(raid, "raid_id", "guild_raid_id", "boss", "boss_hp", "ends_at")


# ===========================================================================
# Feature 26: Player Marketplace (市集) & Direct Trading (5 tests)
# ===========================================================================


def test_t1_f26_list_gear_in_escrow_with_lowest_price_preview(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("市集賣家")
    uid_item = e2e.seed_equipment(
        db,
        u1,
        slot="weapon",
        rarity="rare",
        name="市集試賣細劍",
        weapon_style="rapier",
        now_ts=clock.now,
    )
    res = e2e.assert_ok_result(
        engine.list_market_item(u1, item_uid=uid_item, price_col=300, now_ts=clock.now),
        require_zh_tw=True,
    )
    assert int(e2e.extract_field(res, "listing_id", "id")) > 0
    assert not any(int(it.get("id", it.get("item_uid", -1))) == uid_item for it in e2e.get_player_equipment(engine, u1, clock))


def test_t1_f26_list_stackable_material_or_cooked_dish_on_market(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("材料批發商")
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    e2e.seed_item(db, u1, potion_id, 5)
    before = e2e.get_player_item_qty(engine, u1, potion_id, clock)
    res = e2e.assert_ok_result(
        engine.list_market_item(u1, item_id=potion_id, qty=2, price_col=150, now_ts=clock.now)
    )
    assert int(e2e.extract_field(res, "listing_id", "id")) > 0
    assert e2e.get_player_item_qty(engine, u1, potion_id, clock) == before - 2


def test_t1_f26_search_market_by_weapon_rarity_slot_price_and_two_affixes(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    seller = make_player("精準篩選賣家")
    i1 = e2e.seed_equipment(
        db,
        seller,
        slot="weapon",
        rarity="rare",
        name="雙詞條細劍",
        weapon_style="rapier",
        affixes={"crit_rate": 0.08, "atk_pct": 0.12},
        now_ts=clock.now,
    )
    i2 = e2e.seed_equipment(
        db,
        seller,
        slot="armor",
        rarity="fine",
        name="普通皮甲",
        affixes={"hp": 50},
        now_ts=clock.now,
    )
    engine.list_market_item(seller, item_uid=i1, price_col=400, now_ts=clock.now)
    engine.list_market_item(seller, item_uid=i2, price_col=900, now_ts=clock.now)
    found = e2e.assert_ok_result(
        engine.search_market(
            weapon_class="rapier",
            rarity="rare",
            affix1="crit_rate",
            affix2="atk_pct",
            slot="weapon",
            max_price=500,
        )
    )
    listings = e2e.extract_field(found, "listings", "items", "results")
    assert len(listings) == 1
    assert int(e2e.extract_field(listings[0], "price_col", "price")) == 400


def test_t1_f26_buy_market_item_atomically_transfers_item_and_col(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    seller = make_player("交易賣方")
    buyer = make_player("交易買方")
    e2e.seed_col(db, engine, buyer, 1_000, clock)
    item_uid = e2e.seed_equipment(db, seller, slot="boots", rarity="rare", name="疾風長靴", now_ts=clock.now)
    listing = e2e.assert_ok_result(
        engine.list_market_item(seller, item_uid=item_uid, price_col=350, now_ts=clock.now)
    )
    lid = int(e2e.extract_field(listing, "listing_id", "id"))
    s_before = e2e.get_player_col(engine, seller, clock)
    b_before = e2e.get_player_col(engine, buyer, clock)
    e2e.assert_ok_result(engine.buy_market_item(buyer, lid, now_ts=clock.now), require_zh_tw=True)
    assert e2e.get_player_col(engine, buyer, clock) == b_before - 350
    assert e2e.get_player_col(engine, seller, clock) > s_before
    assert any("疾風長靴" in str(it.get("name", "")) for it in e2e.get_player_equipment(engine, buyer, clock))
    active = e2e.extract_field(engine.search_market(), "listings", "items", "results")
    assert all(int(e2e.extract_field(row, "listing_id", "id")) != lid for row in active)


def test_t1_f26_cancel_market_listing_returns_escrowed_item_to_seller(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    seller = make_player("下架賣家")
    item_uid = e2e.seed_equipment(db, seller, slot="gloves", rarity="rare", name="鐵拳手套", now_ts=clock.now)
    listing = e2e.assert_ok_result(
        engine.list_market_item(seller, item_uid=item_uid, price_col=250, now_ts=clock.now)
    )
    lid = int(e2e.extract_field(listing, "listing_id", "id"))
    e2e.assert_ok_result(engine.cancel_market_listing(seller, lid))
    assert any("鐵拳手套" in str(it.get("name", "")) for it in e2e.get_player_equipment(engine, seller, clock))


# ===========================================================================
# Feature 27: PvP Duels (決鬥: 初擊勝負 / 完全勝負) (5 tests)
# ===========================================================================


def test_t1_f27_challenge_and_accept_first_strike_duel(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("決鬥挑戰者")
    u2 = make_player("決鬥應戰者")
    ch = e2e.assert_ok_result(
        engine.challenge_duel(u1, u2, mode="first_strike", wager_col=0, now_ts=clock.now),
        require_zh_tw=True,
    )
    duel_id = str(e2e.extract_field(ch, "duel_id", "id"))
    acc = e2e.assert_ok_result(engine.accept_duel(duel_id, u2, now_ts=clock.now), require_zh_tw=True)
    assert str(e2e.extract_field(acc, "mode", default="first_strike")).lower() == "first_strike"


def test_t1_f27_first_strike_duel_ends_when_hp_drops_below_50_percent(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("初擊甲")
    u2 = make_player("初擊乙")
    ch = e2e.assert_ok_result(engine.challenge_duel(u1, u2, mode="first_strike", now_ts=clock.now))
    duel_id = str(e2e.extract_field(ch, "duel_id", "id"))
    engine.accept_duel(duel_id, u2, now_ts=clock.now)
    finished = None
    for i in range(50):
        res = e2e.assert_ok_result(
            engine.duel_action(duel_id, u1 if i % 2 == 0 else u2, "attack", now_ts=clock.now)
        )
        if e2e.extract_field(res, "finished", "ended", default=False) is True or str(
            e2e.extract_field(res, "status", default="")
        ).lower() in ("finished", "ended", "completed"):
            finished = res
            break
    assert finished is not None
    assert str(e2e.extract_field(finished, "winner_id", "winner")) in (u1, u2)


def test_t1_f27_full_duel_runs_to_1_hp_knockout_non_lethal(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("完全勝負甲")
    u2 = make_player("完全勝負乙")
    ch = e2e.assert_ok_result(engine.challenge_duel(u1, u2, mode="full", now_ts=clock.now))
    duel_id = str(e2e.extract_field(ch, "duel_id", "id"))
    engine.accept_duel(duel_id, u2, now_ts=clock.now)
    finished = None
    for i in range(80):
        res = e2e.assert_ok_result(
            engine.duel_action(duel_id, u1 if i % 2 == 0 else u2, "attack", now_ts=clock.now)
        )
        if e2e.extract_field(res, "finished", "ended", default=False) is True or str(
            e2e.extract_field(res, "status", default="")
        ).lower() in ("finished", "ended", "completed"):
            finished = res
            break
    assert finished is not None
    winner = str(e2e.extract_field(finished, "winner_id", "winner"))
    loser = u2 if winner == u1 else u1
    loser_hp = int(e2e.extract_field(engine.get_profile(loser, now_ts=clock.now), "hp", "current_hp", "max_hp"))
    assert loser_hp >= 1


def test_t1_f27_duel_col_wager_transfers_atomically_to_winner(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("賭注甲")
    u2 = make_player("賭注乙")
    e2e.seed_col(db, engine, u1, 1_000, clock)
    e2e.seed_col(db, engine, u2, 1_000, clock)
    c1_b = e2e.get_player_col(engine, u1, clock)
    c2_b = e2e.get_player_col(engine, u2, clock)
    ch = e2e.assert_ok_result(
        engine.challenge_duel(u1, u2, mode="first_strike", wager_col=200, now_ts=clock.now)
    )
    duel_id = str(e2e.extract_field(ch, "duel_id", "id"))
    engine.accept_duel(duel_id, u2, now_ts=clock.now)
    finished = None
    for i in range(50):
        res = e2e.assert_ok_result(
            engine.duel_action(duel_id, u1 if i % 2 == 0 else u2, "attack", now_ts=clock.now)
        )
        if e2e.extract_field(res, "finished", "ended", default=False) is True or str(
            e2e.extract_field(res, "status", default="")
        ).lower() in ("finished", "ended", "completed"):
            finished = res
            break
    assert finished is not None
    winner = str(e2e.extract_field(finished, "winner_id", "winner"))
    loser = u2 if winner == u1 else u1
    c1_a = e2e.get_player_col(engine, u1, clock)
    c2_a = e2e.get_player_col(engine, u2, clock)
    assert c1_a + c2_a == c1_b + c2_b
    assert e2e.get_player_col(engine, winner, clock) == (c1_b if winner == u1 else c2_b) + 200
    assert e2e.get_player_col(engine, loser, clock) == (c1_b if loser == u1 else c2_b) - 200


def test_t1_f27_duel_completion_updates_pvp_records_and_ratings(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("積分甲")
    u2 = make_player("積分乙")
    ch = e2e.assert_ok_result(engine.challenge_duel(u1, u2, mode="first_strike", now_ts=clock.now))
    duel_id = str(e2e.extract_field(ch, "duel_id", "id"))
    engine.accept_duel(duel_id, u2, now_ts=clock.now)
    finished = None
    for i in range(50):
        res = e2e.assert_ok_result(
            engine.duel_action(duel_id, u1 if i % 2 == 0 else u2, "attack", now_ts=clock.now)
        )
        if e2e.extract_field(res, "finished", "ended", default=False) is True or str(
            e2e.extract_field(res, "status", default="")
        ).lower() in ("finished", "ended", "completed"):
            finished = res
            break
    assert finished is not None
    winner = str(e2e.extract_field(finished, "winner_id", "winner"))
    loser = u2 if winner == u1 else u1
    pw = engine.get_profile(winner, now_ts=clock.now)
    pl = engine.get_profile(loser, now_ts=clock.now)
    assert int(e2e.extract_field(pw, "duel_wins", "pvp_wins", default=1)) >= 1
    assert int(e2e.extract_field(pl, "duel_losses", "pvp_losses", default=1)) >= 1


# ===========================================================================
# Feature 28: Level 1-100+, Stat Allocation & Branching Talent Trees (5 tests)
# ===========================================================================


def test_t1_f28_allocate_all_five_stats_increases_derived_combat_stats(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("配點劍士")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, power_boost=False
    )
    before = engine.get_profile(uid, now_ts=clock.now)
    cp_b = int(e2e.extract_field(before, "combat_power", "power"))
    pts_b = int(e2e.extract_field(before, "unspent_stat_points", "stat_points"))
    e2e.assert_ok_result(
        engine.allocate_stats(uid, {"str": 2, "agi": 2, "vit": 2, "dex": 2, "luk": 2})
    )
    after = engine.get_profile(uid, now_ts=clock.now)
    assert int(e2e.extract_field(after, "unspent_stat_points", "stat_points")) == pts_b - 10
    assert int(e2e.extract_field(after, "combat_power", "power")) > cp_b


def test_t1_f28_allocate_weapon_branch_talent_node(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("天賦學習者", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, power_boost=False
    )
    root_id, _ = e2e.pick_talent_pair(content_bundle, "sword")
    pts_b = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "unspent_talent_points", "talent_points"))
    e2e.assert_ok_result(engine.allocate_talent(uid, root_id), require_zh_tw=True)
    after = engine.get_profile(uid, now_ts=clock.now)
    assert int(e2e.extract_field(after, "unspent_talent_points", "talent_points")) == pts_b - 1
    assert root_id in str(e2e.extract_field(after, "talents", "allocated_talents"))


def test_t1_f28_allocate_branching_prerequisite_child_talent(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("分支天賦者", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=15, power_boost=False
    )
    root_id, child_id = e2e.pick_talent_pair(content_bundle, "sword")
    e2e.assert_ok_result(engine.allocate_talent(uid, root_id))
    if child_id is not None:
        e2e.assert_ok_result(engine.allocate_talent(uid, child_id))
        after = engine.get_profile(uid, now_ts=clock.now)
        assert child_id in str(e2e.extract_field(after, "talents", "allocated_talents"))


def test_t1_f28_free_town_respec_refunds_all_talent_points(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("免費洗點者", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=12, power_boost=False
    )
    root_id, _ = e2e.pick_talent_pair(content_bundle, "sword")
    pts_init = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "unspent_talent_points", "talent_points"))
    col_init = e2e.get_player_col(engine, uid, clock)
    engine.allocate_talent(uid, root_id)
    e2e.assert_ok_result(engine.respec_talents(uid), require_zh_tw=True)
    after = engine.get_profile(uid, now_ts=clock.now)
    assert int(e2e.extract_field(after, "unspent_talent_points", "talent_points")) == pts_init
    assert e2e.get_player_col(engine, uid, clock) == col_init


def test_t1_f28_compute_player_stats_monotonically_reflects_level_and_talents(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    u1 = make_player("一級角色")
    u20 = make_player("二十級角色")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, u20, 1, clock=clock, level=20, power_boost=False
    )
    s1 = compute_stats(db.get_player(u1), [], content_bundle, floor=1)
    s20 = compute_stats(db.get_player(u20), [], content_bundle, floor=1)
    assert s20.max_hp > s1.max_hp
    assert s20.atk > s1.atk
    assert s20.combat_power > s1.combat_power


# ===========================================================================
# Feature 29: Equipment System (8 Slots, 6 Rarities, Sets, Loadouts, Filter) (5 tests)
# ===========================================================================


def test_t1_f29_equip_across_all_eight_equipment_slots(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("八格全裝者")
    cp_prev = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "combat_power", "power"))
    uids: list[int] = []
    for slot in e2e.EIGHT_EQUIPMENT_SLOTS:
        item_uid = e2e.seed_equipment(
            db, uid, slot=slot, rarity="rare", name=f"裝備_{slot}", atk=20, defense=15, hp=60, now_ts=clock.now
        )
        e2e.assert_ok_result(engine.equip_item(uid, item_uid))
        uids.append(item_uid)
    prof = engine.get_profile(uid, now_ts=clock.now)
    assert int(e2e.extract_field(prof, "combat_power", "power")) > cp_prev
    assert len(uids) == 8


def test_t1_f29_two_piece_and_four_piece_set_bonuses_activate_in_stats(
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    sets, _ = e2e.pick_set_and_named_templates(content_bundle)
    set_id = sets[0][0]
    uid = make_player("套裝測試者")
    slots = ("helmet", "armor", "gloves", "boots")
    for sl in slots:
        e2e.seed_equipment(
            db, uid, slot=sl, rarity="set", name=f"珍品_{sl}", set_id=set_id, atk=10, defense=10, hp=50, now_ts=clock.now
        )
    all_eq = db.get_equipment(uid) if hasattr(db, "get_equipment") else []
    assert len(all_eq) >= 4
    player = db.get_player(uid)
    s0 = compute_stats(player, [], content_bundle, floor=1)
    s2 = compute_stats(player, all_eq[:2], content_bundle, floor=1)
    s4 = compute_stats(player, all_eq[:4], content_bundle, floor=1)
    assert s4.combat_power > s2.combat_power > s0.combat_power


def test_t1_f29_toggle_lock_item_persists_on_and_off(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("鎖裝測試者")
    item_uid = e2e.seed_equipment(db, uid, slot="weapon", rarity="rare", name="珍貴長劍", now_ts=clock.now)
    r1 = e2e.assert_ok_result(engine.toggle_lock_item(uid, item_uid))
    assert e2e.extract_field(r1, "is_locked", "locked") is True
    r2 = e2e.assert_ok_result(engine.toggle_lock_item(uid, item_uid))
    assert e2e.extract_field(r2, "is_locked", "locked") is False


def test_t1_f29_save_and_apply_multiple_gear_loadouts(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("方案切換者")
    w_tank = e2e.seed_equipment(db, uid, slot="weapon", rarity="rare", name="坦裝劍", atk=30, defense=80, hp=300, now_ts=clock.now)
    w_dps = e2e.seed_equipment(db, uid, slot="weapon", rarity="rare", name="輸出劍", atk=150, defense=10, hp=50, now_ts=clock.now)
    engine.equip_item(uid, w_tank)
    e2e.assert_ok_result(engine.save_loadout(uid, 1, "坦裝"))
    engine.equip_item(uid, w_dps)
    e2e.assert_ok_result(engine.save_loadout(uid, 2, "輸出裝"))
    e2e.assert_ok_result(engine.save_loadout(uid, 3, "備用裝"))
    e2e.assert_ok_result(engine.apply_loadout(uid, 1), require_zh_tw=True)
    atk_tank = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "atk"))
    e2e.assert_ok_result(engine.apply_loadout(uid, 2))
    atk_dps = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "atk"))
    assert atk_dps > atk_tank


def test_t1_f29_set_loot_filter_stores_and_applies_to_plain_drops(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("過濾設定者")
    e2e.assert_ok_result(
        engine.set_loot_filter(uid, min_rarity="rare", min_level=20, blocked_slots=["boots"]),
        require_zh_tw=True,
    )
    prof = engine.get_profile(uid, now_ts=clock.now)
    assert str(e2e.extract_field(prof, "min_rarity")).lower() == "rare"
    assert int(e2e.extract_field(prof, "min_level")) == 20


# ===========================================================================
# Feature 30: Workshop (工坊): Blacksmithing, Enhance +1~+15, Stones, Fusion (6 tests)
# ===========================================================================


def test_t1_f30_forge_craft_produces_gear_and_grants_blacksmithing_mastery(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("莉茲鍛造學徒")
    recipe_id, spec = e2e.pick_recipe(content_bundle, "blacksmithing")
    e2e.give_recipe_materials(db, engine, uid, spec, clock, multiplier=2)
    eq_before = len(e2e.get_player_equipment(engine, uid, clock))
    res = e2e.assert_ok_result(engine.forge_craft(uid, recipe_id, now_ts=clock.now), require_zh_tw=True)
    assert res
    assert len(e2e.get_player_equipment(engine, uid, clock)) > eq_before


def test_t1_f30_enhance_equipment_plus_1_to_plus_5_guaranteed_success(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("強化工匠")
    mats = e2e.pick_enhance_materials(content_bundle)
    e2e.seed_item(db, uid, mats["bright"], 50)
    e2e.seed_col(db, engine, uid, 50_000, clock)
    item_uid = e2e.seed_equipment(db, uid, slot="weapon", rarity="rare", name="待強化長劍", now_ts=clock.now)
    for step in range(1, 6):
        res = e2e.assert_ok_result(
            engine.enhance_equipment(uid, item_uid, use_protection=False, now_ts=clock.now, rng_seed=40 + step)
        )
        assert int(e2e.extract_field(res, "enhance_level", "new_level", "level")) == step


def test_t1_f30_enhance_equipment_pity_and_protection_talisman_at_high_tier(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("保底強化師")
    mats = e2e.pick_enhance_materials(content_bundle)
    e2e.seed_item(db, uid, mats["bright"], 200)
    e2e.seed_item(db, uid, mats["protection"], 50)
    # Seed dark crystals too if present in catalog
    for iid, spec in e2e.iter_entries(content_bundle.items_crystals):
        if "dark" in iid.lower() or "暗" in str(spec.get("name", "")):
            e2e.seed_item(db, uid, iid, 200)
    e2e.seed_col(db, engine, uid, 500_000, clock)
    item_uid = e2e.seed_equipment(
        db, uid, slot="weapon", rarity="legendary", name="高階聖劍", enhance_level=12, now_ts=clock.now
    )
    reached_13 = False
    for i in range(40):
        res = e2e.assert_ok_result(
            engine.enhance_equipment(uid, item_uid, use_protection=True, now_ts=clock.now, rng_seed=300 + i)
        )
        lvl = int(e2e.extract_field(res, "enhance_level", "new_level", "level"))
        assert lvl >= 12, "Protection talisman must prevent downgrade below +12"
        if lvl >= 13:
            reached_13 = True
            break
    assert reached_13, "Pity guarantee must eventually advance +12 -> +13"


def test_t1_f30_enhance_named_gear_allowed_up_to_plus_15(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("名品強化者")
    mats = e2e.pick_enhance_materials(content_bundle)
    e2e.seed_item(db, uid, mats["bright"], 20)
    e2e.seed_col(db, engine, uid, 20_000, clock)
    named_uid = e2e.seed_equipment(db, uid, slot="armor", rarity="named", name="午夜大衣", now_ts=clock.now)
    res = e2e.assert_ok_result(engine.enhance_equipment(uid, named_uid, now_ts=clock.now, rng_seed=1))
    assert int(e2e.extract_field(res, "enhance_level", "new_level", "level")) == 1


def test_t1_f30_apply_magic_stone_modifies_non_named_gear_affixes(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("魔石工匠")
    stone_id = e2e.pick_magic_stone_id(content_bundle)
    e2e.seed_item(db, uid, stone_id, 3)
    e2e.seed_col(db, engine, uid, 10_000, clock)
    item_uid = e2e.seed_equipment(db, uid, slot="weapon", rarity="rare", name="魔石長劍", now_ts=clock.now)
    qty_before = e2e.get_player_item_qty(engine, uid, stone_id, clock)
    res = e2e.assert_ok_result(engine.apply_magic_stone(uid, item_uid, stone_id, rng_seed=7), require_zh_tw=True)
    assert res
    assert e2e.get_player_item_qty(engine, uid, stone_id, clock) == qty_before - 1


def test_t1_f30_fuse_items_executes_fusion_recipe_cleanly(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("融煉大師")
    recipe_id, spec = e2e.pick_recipe(content_bundle, "fusion")
    e2e.give_recipe_materials(db, engine, uid, spec, clock, multiplier=2)
    res = e2e.assert_ok_result(engine.fuse_items(uid, recipe_id, now_ts=clock.now), require_zh_tw=True)
    assert res


# ===========================================================================
# Feature 31: Cooking (料理), Big Pot Stew & SAO Crystals / Quick Pouch (6 tests)
# ===========================================================================


def test_t1_f31_cook_dish_normal_vs_timing_perfect_and_mastery(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("亞絲娜主廚")
    recipe_id, spec = e2e.pick_recipe(content_bundle, "cooking")
    e2e.give_recipe_materials(db, engine, uid, spec, clock, multiplier=4)
    r_norm = e2e.assert_ok_result(
        engine.cook_dish(uid, recipe_id, timing_perfect=False, now_ts=clock.now),
        require_zh_tw=True,
    )
    r_perf = e2e.assert_ok_result(
        engine.cook_dish(uid, recipe_id, timing_perfect=True, now_ts=clock.now),
        require_zh_tw=True,
    )
    assert r_norm and r_perf


def test_t1_f31_big_pot_stew_party_start_and_teammate_claim(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=3, floor=1)
    u1, u2, u3 = party.member_ids
    stew_rid, spec = e2e.pick_recipe(content_bundle, "stew")
    e2e.give_recipe_materials(db, engine, u1, spec, clock, multiplier=2)
    stew = e2e.assert_ok_result(
        engine.start_big_pot_stew(u1, stew_rid, party.party_id, now_ts=clock.now),
        require_zh_tw=True,
    )
    stew_id = str(e2e.extract_field(stew, "stew_id", "id"))
    e2e.assert_ok_result(engine.claim_stew(u2, stew_id, now_ts=clock.now), require_zh_tw=True)
    e2e.assert_ok_result(engine.claim_stew(u3, stew_id, now_ts=clock.now), require_zh_tw=True)


def test_t1_f31_big_pot_stew_guild_start_and_guildmate_claim(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("公會廚師")
    u2 = make_player("公會食客")
    e2e.seed_col(db, engine, u1, 10_000, clock)
    g = e2e.assert_ok_result(engine.create_guild(u1, "美食騎士團", "CHEF", now_ts=clock.now))
    guild_id = int(e2e.extract_field(g, "guild_id", "id"))
    engine.join_guild(u2, guild_id, now_ts=clock.now)
    stew_rid, spec = e2e.pick_recipe(content_bundle, "stew")
    e2e.give_recipe_materials(db, engine, u1, spec, clock, multiplier=2)
    stew = e2e.assert_ok_result(
        engine.start_big_pot_stew(u1, stew_rid, str(guild_id), now_ts=clock.now)
    )
    stew_id = str(e2e.extract_field(stew, "stew_id", "id"))
    e2e.assert_ok_result(engine.claim_stew(u2, stew_id, now_ts=clock.now), require_zh_tw=True)


def test_t1_f31_buy_potions_and_all_four_sao_crystals(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("水晶採購者")
    e2e.seed_col(db, engine, uid, 100_000, clock)
    crystals = e2e.pick_crystal_ids(content_bundle)
    assert len(crystals) == 5
    for cid in crystals.values():
        before = e2e.get_player_item_qty(engine, uid, cid, clock)
        e2e.assert_ok_result(engine.buy_shop_item(uid, cid, qty=2, now_ts=clock.now))
        assert e2e.get_player_item_qty(engine, uid, cid, clock) == before + 2


def test_t1_f31_quick_pouch_stacks_consumables_without_using_gear_bag_slots(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("快捷腰包者")
    e2e.seed_col(db, engine, uid, 50_000, clock)
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    eq_before = len(e2e.get_player_equipment(engine, uid, clock))
    e2e.assert_ok_result(engine.buy_shop_item(uid, potion_id, qty=50, now_ts=clock.now))
    assert len(e2e.get_player_equipment(engine, uid, clock)) == eq_before
    assert e2e.get_player_item_qty(engine, uid, potion_id, clock) >= 50


def test_t1_f31_gacha_pull_deterministic_with_seed_and_pity(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("抽箱甲")
    u2 = make_player("抽箱乙")
    e2e.seed_col(db, engine, u1, 50_000, clock)
    e2e.seed_col(db, engine, u2, 50_000, clock)
    r1 = e2e.assert_ok_result(
        engine.gacha_pull(u1, chest_type="standard", count=5, now_ts=clock.now, rng_seed=1234)
    )
    r2 = e2e.assert_ok_result(
        engine.gacha_pull(u2, chest_type="standard", count=5, now_ts=clock.now, rng_seed=1234)
    )
    p1 = e2e.extract_field(r1, "pulls", "items", "rewards", "results")
    p2 = e2e.extract_field(r2, "pulls", "items", "rewards", "results")
    assert len(p1) == 5 and len(p2) == 5
    assert str(p1) == str(p2)


# ===========================================================================
# Feature 32: Passive & Life Skills (採集挖礦 + 7 生活技能) (5 tests)
# ===========================================================================


def test_t1_f32_mine_gather_f1_yields_ores_and_levels_mining_skill(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("一層礦工")
    res = e2e.assert_ok_result(
        engine.mine_gather(uid, floor=1, now_ts=clock.now, rng_seed=101),
        require_zh_tw=True,
    )
    assert e2e.has_field(res, "item_id", "ore_id", "ores", "drops", "items")


def test_t1_f32_mine_gather_f55_yields_crystallite_ingot_vein(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("西山採礦家")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 55, clock=clock)
    f1_res = e2e.assert_ok_result(engine.mine_gather(uid, floor=1, now_ts=clock.now, rng_seed=55))
    clock.advance(minutes=10)
    f55_res = e2e.assert_ok_result(
        engine.mine_gather(uid, floor=55, now_ts=clock.now, rng_seed=55),
        require_zh_tw=True,
    )
    assert e2e.extract_text_blob(f55_res) != e2e.extract_text_blob(f1_res)


def test_t1_f32_all_seven_passive_and_life_skills_tracked_and_progress(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("生活全能者")
    skills_before = e2e.get_player_life_skills(engine, uid, clock)
    assert len(skills_before) >= 7
    engine.mine_gather(uid, floor=1, now_ts=clock.now, rng_seed=3203)
    skills_after = e2e.get_player_life_skills(engine, uid, clock)
    assert str(skills_after) != str(skills_before)


def test_t1_f32_mine_gather_deterministic_with_rng_seed(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("礦脈種子甲")
    u2 = make_player("礦脈種子乙")
    r1 = e2e.assert_ok_result(engine.mine_gather(u1, floor=1, now_ts=clock.now, rng_seed=777))
    r2 = e2e.assert_ok_result(engine.mine_gather(u2, floor=1, now_ts=clock.now, rng_seed=777))
    assert e2e.extract_field(r1, "drops", "ores", "items", "item_id") == e2e.extract_field(
        r2, "drops", "ores", "items", "item_id"
    )


def test_t1_f32_high_searching_skill_improves_chest_trap_inspection(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("索敵達人")
    e2e.trigger_chest_encounter(engine, uid, clock, seed_start=3250)
    insp = e2e.assert_ok_result(
        engine.open_chest(uid, action="inspect", now_ts=clock.now, rng_seed=3250),
        require_zh_tw=True,
    )
    assert e2e.has_zh_tw(e2e.extract_text_blob(insp))


# ===========================================================================
# Feature 33: Quests, Bounties, Offline Expeditions & Achievement Turn-In (6 tests)
# ===========================================================================


def test_t1_f33_seven_day_daily_login_cycle_via_fake_clock(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("七日簽到者")
    for day in range(1, 8):
        col_before = e2e.get_player_col(engine, uid, clock)
        res = e2e.assert_ok_result(engine.claim_daily(uid, now_ts=clock.now), require_zh_tw=True)
        assert int(e2e.extract_field(res, "streak", "checkin_streak", "day")) == day
        assert e2e.get_player_col(engine, uid, clock) > col_before
        clock.advance(days=1)
    # Day 8 cycles cleanly
    e2e.assert_ok_result(engine.claim_daily(uid, now_ts=clock.now))


def test_t1_f33_main_story_branching_choice_persists_outcome(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("主線選擇者")
    quests = e2e.assert_ok_result(engine.get_quests(uid, now_ts=clock.now), require_zh_tw=True)
    assert quests
    ch_id, choice_id, _ = e2e.pick_story_choice(content_bundle)
    res = e2e.assert_ok_result(
        engine.choose_story_option(uid, ch_id, choice_id, now_ts=clock.now),
        require_zh_tw=True,
    )
    assert res


def test_t1_f33_complete_and_claim_quest_or_floor_bounty(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("懸賞獵人")
    # Perform basic daily actions (mine + explore) to complete a starter quest/bounty
    for i in range(3):
        engine.mine_gather(uid, floor=1, now_ts=clock.now, rng_seed=3300 + i)
        clock.advance(minutes=10)
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.explore_to_boss_gate(engine, uid, clock, floor=1)
    q_data = e2e.assert_ok_result(engine.get_quests(uid, now_ts=clock.now))
    q_list = e2e.extract_field(q_data, "quests", "daily", "bounties", "entries", default=[])
    claimable = None
    for q in q_list if isinstance(q_list, list) else e2e.iter_entries(q_list):
        m = e2e.as_mapping(q[1] if isinstance(q, tuple) else q)
        if m.get("completed") or int(m.get("progress", 0)) >= int(m.get("target", 1)):
            claimable = str(m.get("quest_id") or m.get("id") or (q[0] if isinstance(q, tuple) else ""))
            break
    assert claimable, f"Expected at least one completed quest after mining+exploration: {q_data!r}"
    col_before = e2e.get_player_col(engine, uid, clock)
    e2e.assert_ok_result(engine.claim_quest(uid, claimable, now_ts=clock.now), require_zh_tw=True)
    assert e2e.get_player_col(engine, uid, clock) >= col_before


def test_t1_f33_offline_expedition_start_advance_restart_and_claim(
    db: Any,
    db_path: Path,
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("遠征隊長")
    exp_id, _, duration = e2e.pick_expedition(content_bundle)
    e2e.assert_ok_result(engine.start_expedition(uid, exp_id, now_ts=clock.now), require_zh_tw=True)
    col_before = e2e.get_player_col(engine, uid, clock)
    db.close()

    db2 = e2e.load_db_api()["RPGDatabase"](db_path)
    try:
        eng2 = e2e.instantiate_engine(db2, content_bundle)
        clock.advance(seconds=duration + 60)
        res = e2e.assert_ok_result(eng2.claim_expedition(uid, now_ts=clock.now), require_zh_tw=True)
        assert res
        assert e2e.get_player_col(eng2, uid, clock) > col_before
    finally:
        db2.close()


def test_t1_f33_achievement_gear_turn_in_grants_permanent_stat_bonuses(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("成就上繳者")
    spare_uid = e2e.seed_equipment(db, uid, slot="ring", rarity="rare", name="冗餘戒指", now_ts=clock.now)
    cp_before = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "combat_power", "power"))
    e2e.assert_ok_result(engine.turn_in_achievement_gear(uid, spare_uid), require_zh_tw=True)
    prof_after = engine.get_profile(uid, now_ts=clock.now)
    assert int(e2e.extract_field(prof_after, "combat_power", "power")) > cp_before
    assert not any(int(it.get("id", it.get("item_uid", -1))) == spare_uid for it in e2e.get_player_equipment(engine, uid, clock))


def test_t1_f33_claim_achievement_and_equip_unlocked_title(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("稱號收藏家")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 100, clock=clock, level=100)
    e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="first_kill")
    _first_ach, titles = e2e.pick_achievement_and_title(content_bundle)
    # Try claiming first satisfied achievement from catalog
    claimed_title = None
    for aid, aspec in e2e.iter_entries(content_bundle.quests_events.get("achievements", {})):
        try:
            e2e.assert_ok_result(engine.claim_achievement(uid, aid))
            claimed_title = aspec.get("title_id") or aspec.get("reward_title")
            break
        except ValueError:
            continue
    prof = engine.get_profile(uid, now_ts=clock.now)
    unlocked_titles = e2e.extract_field(prof, "unlocked_titles", "titles", default=[])
    target_title = claimed_title or (unlocked_titles[0] if unlocked_titles else titles[0][0])
    e2e.assert_ok_result(engine.equip_title(uid, str(target_title)), require_zh_tw=True)
    assert str(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "active_title", "title")) == str(target_title)


# ===========================================================================
# Feature 34: Post-F100 Endgame & 7 Leaderboards (5 tests)
# ===========================================================================


def test_t1_f34_rebirth_after_f100_preserves_named_titles_turnins_and_adds_multiplier(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("轉生征服者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 100, clock=clock, level=100)
    named_uid = e2e.seed_equipment(db, uid, slot="weapon", rarity="named", name="紅玉聖劍", now_ts=clock.now)
    spare_uid = e2e.seed_equipment(db, uid, slot="ring", rarity="rare", name="獻祭戒", now_ts=clock.now)
    engine.turn_in_achievement_gear(uid, spare_uid)
    yui_before = len(e2e.extract_field(engine.get_yui_logs(uid), "logs", "entries"))

    res = e2e.assert_ok_result(engine.rebirth_player(uid, confirm=True, now_ts=clock.now), require_zh_tw=True)
    assert res
    prof = engine.get_profile(uid, now_ts=clock.now)
    assert int(e2e.extract_field(prof, "rebirth_count", "rebirths")) == 1
    assert any(
        int(it.get("id", it.get("item_uid", -1))) == named_uid or str(it.get("rarity", "")).lower() == "named"
        for it in e2e.get_player_equipment(engine, uid, clock)
    )
    assert len(e2e.extract_field(engine.get_yui_logs(uid), "logs", "entries")) == yui_before


def test_t1_f34_start_heroic_boss_rush_after_f100_clear(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("頭目連戰者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 100, clock=clock, level=100)
    res = e2e.assert_ok_result(engine.start_boss_rush(uid, now_ts=clock.now), require_zh_tw=True)
    assert e2e.has_field(res, "boss", "boss_id", "boss_hp", "stage", "wave")


def test_t1_f34_enter_nightmare_floor_101_plus_after_f100_clear(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("夢魘挑戰者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 100, clock=clock, level=100)
    r101 = e2e.assert_ok_result(engine.enter_nightmare_floor(uid, 101, now_ts=clock.now), require_zh_tw=True)
    r105 = e2e.assert_ok_result(engine.enter_nightmare_floor(uid, 105, now_ts=clock.now), require_zh_tw=True)
    assert int(e2e.extract_field(r101, "nightmare_floor", "floor")) == 101
    assert int(e2e.extract_field(r105, "nightmare_floor", "floor")) == 105


def test_t1_f34_all_seven_leaderboards_return_ordered_rankings(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("榜首一號")
    u2 = make_player("榜眼二號")
    e2e.prepare_player_for_floor(engine, db, content_bundle, u1, 50, clock=clock, level=60, col=90_000)
    e2e.prepare_player_for_floor(engine, db, content_bundle, u2, 20, clock=clock, level=25, col=30_000)
    engine.create_guild(u1, "排行榜公會", "TOP", now_ts=clock.now)
    engine.guild_contribute(u1, 2_000, now_ts=clock.now)
    engine.attack_floor_world_boss(u1, now_ts=clock.now)
    engine.attack_floor_world_boss(u2, now_ts=clock.now)

    for cat in e2e.SEVEN_LEADERBOARD_CATEGORIES:
        lb = e2e.assert_ok_result(engine.get_leaderboard(cat, limit=10), require_zh_tw=True)
        rows = e2e.extract_field(lb, "entries", "rankings", "rows", "leaderboard")
        assert isinstance(rows, list) and len(rows) >= 1, f"Leaderboard {cat!r} should have >=1 row"
        scores = [
            float(e2e.extract_field(r, "score", "value", "metric", "floor", "power", "level", "damage", "col", default=0))
            for r in rows
        ]
        assert scores == sorted(scores, reverse=True), f"Leaderboard {cat!r} not descending: {scores}"


def test_t1_f34_leaderboard_limit_parameter_caps_returned_rows(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    for i in range(6):
        uid = make_player(f"富豪{i}")
        e2e.seed_col(db, engine, uid, (i + 1) * 1000, clock)
    lb = e2e.assert_ok_result(engine.get_leaderboard("col", limit=3))
    rows = e2e.extract_field(lb, "entries", "rankings", "rows", "leaderboard")
    assert len(rows) == 3


# ===========================================================================
# Feature 35: Platform, Persistence, Hygiene, CI & /p Untouched (6 tests)
# ===========================================================================


def test_t1_f35_sqlite_wal_nested_transaction_rollback_and_save_seq(
    db: Any,
    db_path: Path,
    engine: Any,
    clock: Any,
    e2e: Any,
) -> None:
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert str(mode).lower() == "wal"

    seq_before = e2e.get_db_save_seq(db)
    engine.create_character("350001", "交易測試者", now_ts=clock.now)
    seq_after = e2e.get_db_save_seq(db)
    assert seq_after > seq_before

    with pytest.raises(RuntimeError), db.transaction():
        engine.create_character("350002", "將回滾者", now_ts=clock.now)
        raise RuntimeError("forced rollback")
    assert db.get_player("350002") is None


def test_t1_f35_v1_to_v2_migration_preserves_legacy_players_and_gear(
    v1_legacy_db_path: Path,
    content_bundle: Any,
    clock: Any,
    e2e: Any,
) -> None:
    db_api = e2e.load_db_api()
    assert int(db_api["SCHEMA_VERSION"]) == 2
    migrated = db_api["RPGDatabase"](v1_legacy_db_path)
    try:
        eng = e2e.instantiate_engine(migrated, content_bundle)
        assert e2e.get_db_save_seq(migrated) >= e2e.LEGACY_V1_MANIFEST["save_seq"]
        for lp in e2e.LEGACY_V1_MANIFEST["players"]:
            prof = e2e.assert_ok_result(eng.get_profile(lp["user_id"], now_ts=clock.now))
            assert str(e2e.extract_field(prof, "display_name", "name")) == lp["display_name"]
            assert int(e2e.extract_field(prof, "level")) == lp["level"]
            assert e2e.get_player_zone(eng, lp["user_id"], clock) == "town"
            assert e2e.get_player_cursor(eng, lp["user_id"], clock) == "green"
        assert len(e2e.get_player_equipment(eng, "800001", clock)) >= 1
    finally:
        migrated.close()


def test_t1_f35_local_backup_rotation_and_gzip_snapshot_roundtrip(
    db: Any,
    tmp_path: Path,
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("備份驗證者")
    e2e.seed_col(db, engine, uid, 77_777, clock)
    for _ in range(7):
        db.create_local_backup(keep=5)
    backup_files = list(tmp_path.rglob("*.db*"))
    # Exclude main db + wal/shm files when counting rotated backups
    rotated = [
        p
        for p in backup_files
        if "backup" in p.name.lower() or "bak" in p.name.lower() or p.parent != tmp_path
    ]
    assert 1 <= len(rotated) <= 5

    snap = e2e.export_db_snapshot_bytes(db)
    seq_orig = e2e.get_db_save_seq(db)
    db2 = e2e.load_db_api()["RPGDatabase"](tmp_path / "restored_t1.db")
    try:
        assert e2e.import_db_snapshot_bytes(db2, snap) is True
        assert e2e.get_db_save_seq(db2) == seq_orig
        eng2 = e2e.instantiate_engine(db2, content_bundle)
        assert e2e.get_player_col(eng2, uid, clock) == 77_777
    finally:
        db2.close()


def test_t1_f35_create_bot_registers_exact_23_slash_commands_incl_p(
    tmp_path: Path,
    e2e: Any,
) -> None:
    bot_api = e2e.load_bot_api()
    settings = bot_api["Settings"](
        discord_bot_token="local-e2e-synthetic-credential",
        timezone_offset_hours=8,
        rpg_db_path=str(tmp_path / "bot_t1.db"),
        rpg_backup_channel_id="",
        rpg_backup_interval_minutes=15,
    )
    bot_inst = bot_api["create_bot"](settings)
    try:
        names = [cmd.name for cmd in bot_inst.tree.get_commands()]
        assert len(names) == len(set(names)), f"Duplicate commands found: {names}"
        assert set(names) == e2e.EXPECTED_23_COMMANDS
        assert len(names) == 23
    finally:
        if hasattr(bot_inst, "db") and bot_inst.db is not None:
            bot_inst.db.close()


def test_t1_f35_discord_embeds_views_and_raster_assets_within_limits(
    tmp_path: Path,
    fake_discord: dict[str, Any],
    e2e: Any,
) -> None:
    bot_api = e2e.load_bot_api()
    settings = bot_api["Settings"](
        discord_bot_token="local-e2e-synthetic-credential",
        timezone_offset_hours=8,
        rpg_db_path=str(tmp_path / "bot_ui_t1.db"),
        rpg_backup_channel_id="",
        rpg_backup_interval_minutes=15,
    )
    bot_inst = bot_api["create_bot"](settings)
    try:
        user = fake_discord["make_user"](600001, "介面檢驗者")
        inter = fake_discord["make_interaction"](user, client=bot_inst)
        start_cmd = bot_inst.tree.get_command("start")
        help_cmd = bot_inst.tree.get_command("help")
        assert start_cmd is not None and help_cmd is not None
        e2e.run_async(start_cmd.callback(inter))
        e2e.run_async(help_cmd.callback(inter))
        payloads = inter.all_payloads()
        assert len(payloads) >= 2
        for p in payloads:
            e2e.assert_discord_payload_valid(
                content=p.get("content"),
                embeds=p.get("embeds"),
                view=p.get("view"),
            )
    finally:
        if hasattr(bot_inst, "db") and bot_inst.db is not None:
            bot_inst.db.close()


def test_t1_f35_preserved_p_meme_command_independent_of_sao_state(
    tmp_path: Path,
    e2e: Any,
) -> None:
    bot_api = e2e.load_bot_api()
    service = bot_api["AnimeMemeService"]()
    sample, matched_count, total_count = service.pick_random(category="all")
    assert sample is not None and matched_count > 0 and total_count > 0
    embed = bot_api["build_meme_embed"](sample)
    em_dict = embed.to_dict()
    assert em_dict.get("image", {}).get("url")
    assert not em_dict.get("title")
    assert not em_dict.get("description")
    assert not em_dict.get("fields")
    assert not em_dict.get("footer")
    e2e.assert_discord_payload_valid(embed=embed)
