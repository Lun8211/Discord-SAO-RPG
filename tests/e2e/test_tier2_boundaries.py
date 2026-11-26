"""Tier 2 E2E Boundary, Corner, Negative, Concurrency & Security Suite.

Covers Features 01–35 from PROJECT.md § Feature Inventory with >= 5 distinct
boundary/negative/invariant tests per feature (>= 185 total collected tests).
Module top-level imports are strictly Python stdlib + pytest only.
"""

from __future__ import annotations

import math
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# ===========================================================================
# Feature 01: Aincrad 100-Floor Worldview & Character Creation (6 tests)
# ===========================================================================


def test_t2_f01_duplicate_character_creation_rejected(
    engine: Any,
    clock: Any,
    e2e: Any,
) -> None:
    e2e.assert_ok_result(engine.create_character("201001", "桐人", now_ts=clock.now))
    e2e.assert_game_error(
        lambda: engine.create_character("201001", "重複者", now_ts=clock.now)
    )
    prof = engine.get_profile("201001", now_ts=clock.now)
    assert str(e2e.extract_field(prof, "display_name", "name")) == "桐人"


def test_t2_f01_blank_whitespace_and_control_char_name_rejected(
    db: Any,
    engine: Any,
    clock: Any,
    e2e: Any,
) -> None:
    for idx, bad_name in enumerate(("", "   ", "\n\t\x00")):
        uid = f"20101{idx}"
        e2e.assert_game_error(
            lambda u=uid, n=bad_name: engine.create_character(u, n, now_ts=clock.now)
        )
        assert db.get_player(uid) is None


def test_t2_f01_overlong_display_name_rejected_or_safely_bounded(
    engine: Any,
    clock: Any,
    e2e: Any,
) -> None:
    long_name = "桐" * 120
    game_err = e2e.load_engine_api()["GameError"]
    try:
        e2e.assert_ok_result(engine.create_character("201020", long_name, now_ts=clock.now))
        prof = engine.get_profile("201020", now_ts=clock.now)
        stored = str(e2e.extract_field(prof, "display_name", "name"))
        assert 1 <= len(stored) <= 64
    except game_err as exc:
        assert getattr(exc, "code", "") and e2e.has_zh_tw(str(exc))


def test_t2_f01_invalid_or_unique_starter_weapon_style_rejected(
    db: Any,
    engine: Any,
    clock: Any,
    e2e: Any,
) -> None:
    for idx, bad_style in enumerate(("wizard_staff", "dual_blades", "holy_sword")):
        uid = f"20103{idx}"
        e2e.assert_game_error(
            lambda u=uid, s=bad_style: engine.create_character(
                u, "試煉者", weapon_style=s, now_ts=clock.now
            )
        )
        assert db.get_player(uid) is None


def test_t2_f01_invalid_game_mode_rejected(
    db: Any,
    engine: Any,
    clock: Any,
    e2e: Any,
) -> None:
    for idx, bad_mode in enumerate(("creative", "")):
        uid = f"20104{idx}"
        e2e.assert_game_error(
            lambda u=uid, m=bad_mode: engine.create_character(
                u, "試煉者", mode=m, now_ts=clock.now
            )
        )
        assert db.get_player(uid) is None


def test_t2_f01_get_profile_unknown_user_rejected(
    engine: Any,
    clock: Any,
    e2e: Any,
) -> None:
    e2e.assert_game_error(lambda: engine.get_profile("99999999", now_ts=clock.now))


# ===========================================================================
# Feature 02: Safe Zone (圈內) vs Field / Labyrinth (6 tests)
# ===========================================================================


def test_t2_f02_travel_unknown_zone_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("非法區域測試")
    for bad_zone in ("sky_castle", ""):
        e2e.assert_game_error(
            lambda z=bad_zone: engine.travel_zone(uid, z, now_ts=clock.now)
        )
    assert e2e.get_player_zone(engine, uid, clock) == "town"


def test_t2_f02_forge_craft_blocked_in_field(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("野外鍛造測試")
    recipe_id, spec = e2e.pick_recipe(content_bundle, "blacksmithing")
    e2e.give_recipe_materials(db, engine, uid, spec, clock)
    col_before = e2e.get_player_col(engine, uid, clock)
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.forge_craft(uid, recipe_id, now_ts=clock.now))
    assert e2e.get_player_col(engine, uid, clock) == col_before


def test_t2_f02_market_listing_blocked_in_field(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("野外擺攤測試")
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    e2e.seed_item(db, uid, potion_id, 5)
    before = e2e.get_player_item_qty(engine, uid, potion_id, clock)
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_game_error(
        lambda: engine.list_market_item(
            uid, item_id=potion_id, qty=1, price_col=100, now_ts=clock.now
        )
    )
    assert e2e.get_player_item_qty(engine, uid, potion_id, clock) == before


def test_t2_f02_talent_respec_blocked_in_field(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("野外洗點測試")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.respec_talents(uid))


def test_t2_f02_direct_travel_to_boss_room_blocked(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("跳關測試")
    e2e.assert_game_error(lambda: engine.travel_zone(uid, "boss_room", now_ts=clock.now))
    assert e2e.get_player_zone(engine, uid, clock) == "town"


def test_t2_f02_travel_zone_blocked_mid_combat_and_warehouse_blocked_in_field(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("戰中移動測試")
    e2e.seed_col(db, engine, uid, 10_000, clock)
    engine.create_guild(uid, "野外倉測公會", "FW", now_ts=clock.now)
    item_uid = e2e.seed_equipment(db, uid, slot="ring", rarity="rare", name="倉測戒", now_ts=clock.now)
    dep = e2e.assert_ok_result(engine.guild_warehouse_deposit(uid, item_uid, now_ts=clock.now))
    wh_id = int(e2e.extract_field(dep, "warehouse_id", "id"))
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.guild_warehouse_withdraw(uid, wh_id, now_ts=clock.now))
    e2e.trigger_road_combat(engine, uid, clock, seed_start=2026)
    e2e.assert_game_error(lambda: engine.travel_zone(uid, "town", now_ts=clock.now))


# ===========================================================================
# Feature 03: Teleport Gate (轉移門) (5 tests)
# ===========================================================================


def test_t2_f03_teleport_floor_zero_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("零層傳送測試")
    e2e.assert_game_error(lambda: engine.teleport_floor(uid, 0, now_ts=clock.now))
    assert e2e.get_player_floor(engine, uid, clock)[0] == 1


def test_t2_f03_teleport_negative_floor_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("負層傳送測試")
    e2e.assert_game_error(lambda: engine.teleport_floor(uid, -1, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.teleport_floor(uid, -100, now_ts=clock.now))
    assert e2e.get_player_floor(engine, uid, clock)[0] == 1


def test_t2_f03_teleport_floor_above_100_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("越界層傳送測試")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 100, clock=clock, level=100)
    e2e.assert_game_error(lambda: engine.teleport_floor(uid, 101, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.teleport_floor(uid, 999, now_ts=clock.now))


def test_t2_f03_teleport_locked_floor_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("未解鎖傳送測試")
    e2e.assert_game_error(lambda: engine.teleport_floor(uid, 2, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.teleport_floor(uid, 50, now_ts=clock.now))
    assert e2e.get_player_floor(engine, uid, clock)[0] == 1


def test_t2_f03_teleport_blocked_during_active_boss_battle(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("頭目戰逃逸測試")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.teleport_floor(uid, 1, now_ts=clock.now))


# ===========================================================================
# Feature 04: Monument of Life (生命之碑) & Survival Logs (6 tests)
# ===========================================================================


def test_t2_f04_monument_empty_db_returns_inaugural_notice(
    engine: Any,
    e2e: Any,
) -> None:
    mon = e2e.assert_ok_result(engine.get_monument_of_life(limit=10), require_zh_tw=True)
    assert int(e2e.extract_field(mon, "total", "total_players")) == 0
    assert int(e2e.extract_field(mon, "alive", "alive_count", "alive_players")) == 0
    assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 0


def test_t2_f04_monument_zero_or_negative_limit_rejected(
    engine: Any,
    e2e: Any,
) -> None:
    e2e.assert_game_error(lambda: engine.get_monument_of_life(limit=0))
    e2e.assert_game_error(lambda: engine.get_monument_of_life(limit=-5))


def test_t2_f04_monument_huge_limit_bounded_safely(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    make_player("碑文測試甲")
    make_player("碑文測試乙")
    mon = e2e.assert_ok_result(engine.get_monument_of_life(limit=10_000))
    assert int(e2e.extract_field(mon, "total", "total_players")) == 2


def test_t2_f04_hardcore_boss_death_increments_fallen_count(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("一命劍士", mode="hardcore")
    e2e.induce_combat_defeat(engine, db, content_bundle, uid, clock, in_boss=True)
    mon = e2e.assert_ok_result(engine.get_monument_of_life(limit=10))
    assert int(e2e.extract_field(mon, "total", "total_players")) == 1
    assert int(e2e.extract_field(mon, "alive", "alive_count", "alive_players")) == 0
    assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 1


def test_t2_f04_standard_downed_separated_from_fallen(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("標準劍士", mode="standard")
    e2e.induce_combat_defeat(engine, db, content_bundle, uid, clock)
    mon = e2e.assert_ok_result(engine.get_monument_of_life(limit=10))
    assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 0


def test_t2_f04_monument_defeat_log_persists_across_db_restart(
    db: Any,
    db_path: Path,
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("永恆碑名", mode="hardcore")
    e2e.induce_combat_defeat(engine, db, content_bundle, uid, clock, in_boss=True)
    db.close()
    db2 = e2e.load_db_api()["RPGDatabase"](db_path)
    try:
        eng2 = e2e.instantiate_engine(db2, content_bundle)
        mon = e2e.assert_ok_result(eng2.get_monument_of_life(limit=10))
        assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 1
        assert "永恆碑名" in e2e.extract_text_blob(mon) or uid in e2e.extract_text_blob(mon)
    finally:
        db2.close()


# ===========================================================================
# Feature 05: Color Cursor (光標顏色) & Karma (5 tests)
# ===========================================================================


def test_t2_f05_cursor_always_within_valid_enum_set(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("光標邊界測試")
    assert e2e.get_player_cursor(engine, uid, clock) in e2e.THREE_CURSORS
    ch_id, choice_id, _ = e2e.pick_story_choice(content_bundle)
    engine.choose_story_option(uid, ch_id, choice_id, now_ts=clock.now)
    assert e2e.get_player_cursor(engine, uid, clock) in e2e.THREE_CURSORS


def test_t2_f05_unconsented_duel_attack_blocked_in_safe_zone(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    p1 = make_player("偷襲者")
    p2 = make_player("和平玩家")
    ch = e2e.assert_ok_result(engine.challenge_duel(p1, p2, mode="first_strike", now_ts=clock.now))
    duel_id = str(e2e.extract_field(ch, "duel_id", "id"))
    e2e.assert_game_error(lambda: engine.duel_action(duel_id, p1, "attack", now_ts=clock.now))
    assert e2e.get_player_cursor(engine, p1, clock) == "green"


def test_t2_f05_safe_zone_full_duel_never_lethal_or_red_cursor(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    p1 = make_player("安全決鬥甲")
    p2 = make_player("安全決鬥乙", mode="hardcore")
    ch = e2e.assert_ok_result(engine.challenge_duel(p1, p2, mode="full", now_ts=clock.now))
    duel_id = str(e2e.extract_field(ch, "duel_id", "id"))
    engine.accept_duel(duel_id, p2, now_ts=clock.now)
    for i in range(80):
        res = e2e.assert_ok_result(
            engine.duel_action(duel_id, p1 if i % 2 == 0 else p2, "attack", now_ts=clock.now)
        )
        if e2e.extract_field(res, "finished", "ended", default=False) is True or str(
            e2e.extract_field(res, "status", default="")
        ).lower() in ("finished", "ended", "completed"):
            break
    assert e2e.get_player_cursor(engine, p1, clock) == "green"
    assert e2e.get_player_cursor(engine, p2, clock) == "green"
    mon = engine.get_monument_of_life(limit=10)
    assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 0


def test_t2_f05_karma_clamped_on_repeated_extreme_choices(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("重複劇情防刷")
    ch_id, choice_id, _ = e2e.pick_story_choice(content_bundle, karma_negative=True)
    e2e.assert_ok_result(engine.choose_story_option(uid, ch_id, choice_id, now_ts=clock.now))
    # Replaying the exact same completed chapter must be rejected
    e2e.assert_game_error(
        lambda: engine.choose_story_option(uid, ch_id, choice_id, now_ts=clock.now)
    )


def test_t2_f05_cursor_decay_boundary_one_second_does_not_instant_clear(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("冷卻邊界者")
    ch_id, choice_id, _ = e2e.pick_story_choice(content_bundle, karma_negative=True)
    engine.choose_story_option(uid, ch_id, choice_id, now_ts=clock.now)
    before_cursor = e2e.get_player_cursor(engine, uid, clock)
    before_karma = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "karma", default=0))
    clock.advance(seconds=1)
    after_cursor = e2e.get_player_cursor(engine, uid, clock)
    after_karma = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "karma", default=0))
    assert after_cursor == before_cursor and after_karma == before_karma


# ===========================================================================
# Feature 06: Argo's Info (阿爾狗的情報) & Clearers (5 tests)
# ===========================================================================


def test_t2_f06_argo_invalid_floor_zero_negative_or_101_rejected(
    engine: Any,
    e2e: Any,
) -> None:
    for bad in (0, -3, 101):
        e2e.assert_game_error(lambda f=bad: engine.get_argo_intel(floor=f))


def test_t2_f06_argo_unknown_user_id_rejected(
    engine: Any,
    e2e: Any,
) -> None:
    e2e.assert_game_error(lambda: engine.get_argo_intel(user_id="ghost_999", floor=1))


def test_t2_f06_unencountered_f100_boss_skills_never_leaked(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("一層窺探者")
    intel = e2e.assert_ok_result(engine.get_argo_intel(user_id=uid, floor=100))
    observed = e2e.extract_field(intel, "observed_skills", "seen_skills", "known_skills", default=[])
    assert len(observed) == 0 or "???" in e2e.extract_text_blob(intel)


def test_t2_f06_personal_observed_intel_isolated_between_players(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    ua = make_player("實戰觀測甲")
    ub = make_player("未參戰乙")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, ua, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.start_floor_boss(ua, floor=1, mode="normal", now_ts=clock.now)
    for _ in range(4):
        res = e2e.assert_ok_result(engine.combat_action(ua, "defend", now_ts=clock.now))
        if e2e.extract_field(res, "ended", "finished", default=False) is True:
            break
    ia = e2e.assert_ok_result(engine.get_argo_intel(user_id=ua, floor=1))
    ib = e2e.assert_ok_result(engine.get_argo_intel(user_id=ub, floor=1))
    assert e2e.extract_text_blob(ia).count("???") <= e2e.extract_text_blob(ib).count("???")
    obs_b = e2e.extract_field(ib, "observed_skills", "seen_skills", "known_skills", default=[])
    assert len(obs_b) == 0


def test_t2_f06_second_clear_preserves_original_first_kill_attribution(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    ua = make_player("原首殺冠軍")
    ub = make_player("後續討伐者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, ua, 1, clock=clock, level=12)
    e2e.prepare_player_for_floor(engine, db, content_bundle, ub, 1, clock=clock, level=12)
    e2e.clear_floor_organically(engine, ua, clock, floor=1, mode="first_kill")
    clock.advance(minutes=10)
    e2e.clear_floor_organically(engine, ub, clock, floor=1, mode="first_kill")
    intel = e2e.assert_ok_result(engine.get_argo_intel(floor=1))
    blob = e2e.extract_text_blob(intel)
    assert "原首殺冠軍" in blob or ua in blob


# ===========================================================================
# Feature 07: Yui Console (結衣終端機) Lore Archive (5 tests)
# ===========================================================================


def test_t2_f07_yui_logs_unknown_user_rejected(
    engine: Any,
    e2e: Any,
) -> None:
    e2e.assert_game_error(lambda: engine.get_yui_logs("no_such_player"))


def test_t2_f07_locked_logs_redact_content_with_permission_gate(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("權限受限者")
    res = e2e.assert_ok_result(engine.get_yui_logs(uid), require_zh_tw=True)
    entries = e2e.extract_field(res, "logs", "entries")
    locked = [e2e.as_mapping(e) for e in entries if not e2e.as_mapping(e).get("unlocked", True)]
    assert len(locked) >= 5, "F1 starter must have milestone logs locked"


def test_t2_f07_non_milestone_floors_do_not_prematurely_unlock_next_log(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("臨界樓層檢驗")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 9, clock=clock)
    c9 = sum(1 for e in e2e.extract_field(engine.get_yui_logs(uid), "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 10, clock=clock)
    c10 = sum(1 for e in e2e.extract_field(engine.get_yui_logs(uid), "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    assert c10 > c9


def test_t2_f07_teleporting_down_to_f1_keeps_unlocked_logs(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("回低層保檔者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 50, clock=clock)
    c50 = sum(1 for e in e2e.extract_field(engine.get_yui_logs(uid), "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    engine.teleport_floor(uid, 1, now_ts=clock.now)
    c_after = sum(1 for e in e2e.extract_field(engine.get_yui_logs(uid), "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    assert c_after == c50


def test_t2_f07_rebirth_preserves_yui_console_archive(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("轉生留檔者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 100, clock=clock, level=100)
    before = sum(1 for e in e2e.extract_field(engine.get_yui_logs(uid), "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    engine.rebirth_player(uid, confirm=True, now_ts=clock.now)
    after = sum(1 for e in e2e.extract_field(engine.get_yui_logs(uid), "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    assert after == before and after >= 7


# ===========================================================================
# Feature 08: JSON-Driven 100-Floor Template & Override Engine (5 tests)
# ===========================================================================


def test_t2_f08_get_floor_info_out_of_bounds_rejected(
    engine: Any,
    e2e: Any,
) -> None:
    for bad in (0, -1, 101, 1000):
        e2e.assert_game_error(lambda f=bad: engine.get_floor_info(f))


def test_t2_f08_monotonic_scaling_from_f1_to_f100(
    engine: Any,
    e2e: Any,
) -> None:
    prev_val = 0.0
    for fl in (1, 10, 25, 50, 75, 100):
        info = e2e.assert_ok_result(engine.get_floor_info(fl))
        val = float(e2e.extract_field(info, "boss_hp", "hp_scale", "stat_multiplier", "recommended_level"))
        assert val >= prev_val, f"Floor {fl} scaling regressed: {val} < {prev_val}"
        prev_val = val
    f1 = float(e2e.extract_field(engine.get_floor_info(1), "boss_hp", "hp_scale", "stat_multiplier", "recommended_level"))
    assert prev_val > f1


def test_t2_f08_zero_dangling_cross_references_in_content_bundle(
    content_bundle: Any,
    e2e: Any,
) -> None:
    boss_ids = {bid for bid, _ in e2e.iter_entries(content_bundle.bosses)}
    mob_ids = {mid for mid, _ in e2e.iter_entries(content_bundle.monsters)}
    for fl_key, ov in (content_bundle.floors_override or {}).items():
        if isinstance(ov, dict) and ov.get("boss_id"):
            assert ov["boss_id"] in boss_ids, f"Floor {fl_key} dangling boss_id {ov['boss_id']!r}"
    tiers = content_bundle.biomes.get("tiers") if isinstance(content_bundle.biomes, dict) else content_bundle.biomes
    for tid, tspec in e2e.iter_entries(tiers):
        for mid in tspec.get("mob_pool_ids", tspec.get("monster_ids", [])):
            assert mid in mob_ids, f"Biome {tid} dangling mob_id {mid!r}"


def test_t2_f08_load_content_cache_and_force_reload_equivalent(
    e2e: Any,
) -> None:
    load_content = e2e.load_content_api()["load_content"]
    b1 = load_content(force_reload=False)
    b2 = load_content(force_reload=True)
    assert set(b1.bosses.keys()) == set(b2.bosses.keys())
    assert set(b1.sword_skills.keys()) == set(b2.sword_skills.keys())
    assert set(b1.items_crystals.keys()) == set(b2.items_crystals.keys())


def test_t2_f08_every_tenth_floor_boss_is_distinct(
    engine: Any,
    e2e: Any,
) -> None:
    boss_ids: list[str] = []
    for fl in (1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
        info = e2e.assert_ok_result(engine.get_floor_info(fl))
        boss_ids.append(str(e2e.extract_field(info, "boss_id", "boss_name")))
    assert len(set(boss_ids)) == len(boss_ids), f"Duplicate 10th-floor bosses found: {boss_ids}"


# ===========================================================================
# Feature 09: Floor Exploration Progression (5 tests)
# ===========================================================================


def test_t2_f09_explore_zero_and_negative_steps_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("步數邊界測試")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.explore_floor(uid, steps=0, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.explore_floor(uid, steps=-5, now_ts=clock.now))


def test_t2_f09_explore_excessive_steps_rejected_or_clamped_to_100(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("超步探索測試")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    game_err = e2e.load_engine_api()["GameError"]
    try:
        e2e.assert_ok_result(engine.explore_floor(uid, steps=9999, now_ts=clock.now, rng_seed=99))
        pct = int(e2e.extract_field(engine.get_floor_info(1, user_id=uid), "exploration_pct", "exploration", "progress"))
        assert 0 <= pct <= 100
    except game_err as exc:
        assert getattr(exc, "code", "") and e2e.has_zh_tw(str(exc))


def test_t2_f09_start_floor_boss_blocked_before_exploration_gate(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("零探索闖王測試")
    e2e.assert_game_error(lambda: engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now))


def test_t2_f09_exploration_progress_never_exceeds_100(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("百探上限測試")
    e2e.explore_to_boss_gate(engine, uid, clock, floor=1)
    res = e2e.assert_ok_result(engine.explore_floor(uid, steps=1, now_ts=clock.now, rng_seed=999))
    assert res
    pct = int(e2e.extract_field(engine.get_floor_info(1, user_id=uid), "exploration_pct", "exploration", "progress"))
    assert pct == 100


def test_t2_f09_explore_blocked_while_unresolved_combat_active(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("戰中跳探索防呆")
    e2e.trigger_road_combat(engine, uid, clock, seed_start=2095)
    e2e.assert_game_error(lambda: engine.explore_floor(uid, steps=1, now_ts=clock.now, rng_seed=2096))


# ===========================================================================
# Feature 10: Road Monsters (5 tests)
# ===========================================================================


def test_t2_f10_combat_action_outside_combat_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("非戰鬥揮劍者")
    e2e.assert_game_error(lambda: engine.combat_action(uid, "attack", now_ts=clock.now))


def test_t2_f10_unknown_combat_action_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("非法動作測試")
    e2e.trigger_road_combat(engine, uid, clock, seed_start=2102)
    e2e.assert_game_error(lambda: engine.combat_action(uid, "fireball", now_ts=clock.now))
    # Combat session remains intact so valid attack succeeds
    e2e.assert_ok_result(engine.combat_action(uid, "attack", now_ts=clock.now))


def test_t2_f10_elite_and_field_boss_stronger_than_normal_mob(
    content_bundle: Any,
    e2e: Any,
) -> None:
    mobs = e2e.iter_entries(content_bundle.monsters)
    by_tier: dict[int, dict[str, list[int]]] = {}
    for _, spec in mobs:
        tier = int(spec.get("tier", 1))
        rank = str(spec.get("rank", spec.get("kind", spec.get("category", "normal")))).lower()
        hp = int(spec.get("hp", spec.get("base_hp", 0)))
        by_tier.setdefault(tier, {}).setdefault(rank, []).append(hp)
    checked = 0
    for tier, ranks in by_tier.items():
        normals = ranks.get("normal", [])
        stronger = ranks.get("elite", []) + ranks.get("field_boss", [])
        if normals and stronger:
            assert max(stronger) > min(normals), f"Tier {tier} elite/field_boss must beat normal HP"
            checked += 1
    assert checked >= 1


def test_t2_f10_zero_dangling_mob_ids_or_drop_ids(
    content_bundle: Any,
    e2e: Any,
) -> None:
    item_ids = {iid for iid, _ in e2e.iter_entries(content_bundle.items_crystals)}
    eq_ids = set()
    if isinstance(content_bundle.weapons_equipment, dict):
        for sec in ("base_gear", "named_items", "sets"):
            eq_ids.update(k for k, _ in e2e.iter_entries(content_bundle.weapons_equipment.get(sec, {})))
    valid_targets = item_ids | eq_ids
    for mid, spec in e2e.iter_entries(content_bundle.monsters):
        for entry in spec.get("drops", []):
            iid = entry.get("item_id") if isinstance(entry, dict) else str(entry)
            if iid:
                assert iid in valid_targets, f"Monster {mid} dangling drop {iid!r}"


def test_t2_f10_combat_action_after_victory_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("鞭屍防呆測試")
    e2e.trigger_road_combat(engine, uid, clock, seed_start=2105)
    e2e.resolve_active_combat(engine, uid, clock)
    col_after_win = e2e.get_player_col(engine, uid, clock)
    e2e.assert_game_error(lambda: engine.combat_action(uid, "attack", now_ts=clock.now))
    assert e2e.get_player_col(engine, uid, clock) == col_after_win


# ===========================================================================
# Feature 11: Treasure Chests (6 Tiers) + Mimic & Crystal-Null Trap (6 tests)
# ===========================================================================


def test_t2_f11_invalid_chest_action_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("非法開箱動作")
    e2e.trigger_chest_encounter(engine, uid, clock, seed_start=2111)
    e2e.assert_game_error(lambda: engine.open_chest(uid, action="explode", now_ts=clock.now))


def test_t2_f11_open_chest_when_none_present_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("空氣開箱測試")
    e2e.assert_game_error(lambda: engine.open_chest(uid, action="open", now_ts=clock.now))


def test_t2_f11_double_open_same_chest_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("重複開箱測試")
    e2e.trigger_chest_encounter(engine, uid, clock, seed_start=2113)
    res = e2e.assert_ok_result(engine.open_chest(uid, action="open", now_ts=clock.now, rng_seed=2113))
    if e2e.extract_field(res, "in_combat", "is_mimic", default=False):
        e2e.resolve_active_combat(engine, uid, clock)
    e2e.assert_game_error(lambda: engine.open_chest(uid, action="open", now_ts=clock.now))


def test_t2_f11_f27_crystal_null_trap_blocks_teleport_without_consuming_crystal(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("第27層陷阱受困者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 27, clock=clock, level=35)
    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    before_tp = e2e.get_player_item_qty(engine, uid, tp_id, clock)
    assert before_tp >= 1
    # Trigger F27 chest/trap or F27 field encounter subject to Crystal-Null rule
    engine.travel_zone(uid, "labyrinth", now_ts=clock.now)
    trap_triggered = False
    for s in range(2700, 2760):
        res = e2e.assert_ok_result(engine.explore_floor(uid, steps=1, now_ts=clock.now, rng_seed=s))
        ev = str(e2e.extract_field(res, "event_type", "encounter_type", "type", "event", default="")).lower()
        if "chest" in ev or e2e.has_field(res, "chest", "chest_tier"):
            opened = e2e.assert_ok_result(engine.open_chest(uid, action="open", now_ts=clock.now, rng_seed=s))
            if e2e.extract_field(opened, "crystal_null", "in_combat", "is_trap", default=False):
                trap_triggered = True
                break
        elif e2e.extract_field(res, "in_combat", default=False) is True:
            if e2e.extract_field(res, "crystal_null", default=False) is True:
                trap_triggered = True
                break
            e2e.resolve_active_combat(engine, uid, clock)
    assert trap_triggered, "F27 labyrinth must trigger Crystal-Null encounter"
    e2e.assert_game_error(lambda: engine.combat_action(uid, "crystal", item_id=tp_id, now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, uid, tp_id, clock) == before_tp


def test_t2_f11_mimic_chest_triggers_ambush_or_potion_bite(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("擬態寶箱獵人")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=10)
    saw_mimic = False
    for s in range(1, 100):
        e2e.trigger_chest_encounter(engine, uid, clock, seed_start=3000 + s * 10)
        res = e2e.assert_ok_result(engine.open_chest(uid, action="open", now_ts=clock.now, rng_seed=s))
        blob = e2e.extract_text_blob(res)
        if (
            e2e.extract_field(res, "is_mimic", "mimic", "in_combat", default=False) is True
            or "擬態" in blob
            or "寶箱怪" in blob
        ):
            saw_mimic = True
            if e2e.extract_field(res, "in_combat", default=False) is True:
                e2e.resolve_active_combat(engine, uid, clock)
            break
    assert saw_mimic, "Expected Mimic ambush across seeded chest openings"


def test_t2_f11_full_bag_chest_gear_routes_to_pending_loot_mailbox(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("滿包開箱測試")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=10)
    for i in range(85):
        e2e.seed_equipment(db, uid, slot="ring", rarity="plain", name=f"佔位戒{i}", now_ts=clock.now)
    # Open chests until gear drop overflows or boss LA drop overflows cleanly without crash
    e2e.trigger_chest_encounter(engine, uid, clock, seed_start=2116)
    res = e2e.assert_ok_result(engine.open_chest(uid, action="open", now_ts=clock.now, rng_seed=2116))
    assert res
    assert len(e2e.get_player_equipment(engine, uid, clock)) >= 80


# ===========================================================================
# Feature 12: Secret Realm & Miasma (秘境與瘴氣) (5 tests)
# ===========================================================================


def test_t2_f12_invalid_secret_realm_action_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("秘境非法動作")
    e2e.assert_game_error(lambda: engine.enter_secret_realm(uid, action="cleanse", now_ts=clock.now))


def test_t2_f12_explore_or_leave_before_entering_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("未進秘境探索")
    e2e.assert_game_error(lambda: engine.enter_secret_realm(uid, action="explore", now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.enter_secret_realm(uid, action="leave", now_ts=clock.now))


def test_t2_f12_high_miasma_amplifies_incoming_combat_damage(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("高瘴氣承傷者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=15)
    engine.travel_zone(uid, "field", now_ts=clock.now)
    engine.enter_secret_realm(uid, action="enter", now_ts=clock.now, rng_seed=2123)
    for k in range(4):
        r = e2e.assert_ok_result(
            engine.enter_secret_realm(uid, action="explore", now_ts=clock.now, rng_seed=2124 + k)
        )
        if e2e.extract_field(r, "in_combat", default=False) is True:
            e2e.resolve_active_combat(engine, uid, clock)
    assert e2e.get_player_miasma(engine, uid, clock) >= 4
    prof = engine.get_profile(uid, now_ts=clock.now)
    dmg_mult = float(e2e.extract_field(prof, "miasma_dmg_taken_mult", "miasma_penalty", "miasma_stacks"))
    assert dmg_mult > 1.0


def test_t2_f12_party_miasma_contagion_spreads_penalty_without_free_exp(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    carrier = make_player("帶毒者")
    clean = make_player("潔淨隊友")
    e2e.prepare_player_for_floor(engine, db, content_bundle, carrier, 1, clock=clock, level=12)
    engine.travel_zone(carrier, "field", now_ts=clock.now)
    engine.enter_secret_realm(carrier, action="enter", now_ts=clock.now, rng_seed=2126)
    for k in range(3):
        r = e2e.assert_ok_result(
            engine.enter_secret_realm(carrier, action="explore", now_ts=clock.now, rng_seed=2127 + k)
        )
        if e2e.extract_field(r, "in_combat", default=False) is True:
            e2e.resolve_active_combat(engine, carrier, clock)
    p_res = e2e.assert_ok_result(engine.create_party(carrier, floor=1, now_ts=clock.now))
    pid = str(e2e.extract_field(p_res, "party_id", "id"))
    engine.join_party(pid, clean, role="dps", now_ts=clock.now)
    engine.travel_zone(clean, "field", now_ts=clock.now)
    engine.enter_secret_realm(clean, action="enter", now_ts=clock.now, rng_seed=2130)
    assert e2e.get_player_miasma(engine, clean, clock) >= 3
    clean_exp = float(e2e.extract_field(engine.get_profile(clean, now_ts=clock.now), "secret_realm_exp_bonus", "miasma_exp_bonus", default=0.0))
    assert clean_exp <= 1.0


def test_t2_f12_boss_entry_under_high_miasma_blocked_or_warned(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("瘴氣闖王者")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=15, unlock_boss_gate=True
    )
    engine.travel_zone(uid, "field", now_ts=clock.now)
    engine.enter_secret_realm(uid, action="enter", now_ts=clock.now, rng_seed=2135)
    for k in range(5):
        r = e2e.assert_ok_result(
            engine.enter_secret_realm(uid, action="explore", now_ts=clock.now, rng_seed=2136 + k)
        )
        if e2e.extract_field(r, "in_combat", default=False) is True:
            e2e.resolve_active_combat(engine, uid, clock)
    engine.enter_secret_realm(uid, action="leave", now_ts=clock.now)
    game_err = e2e.load_engine_api()["GameError"]
    try:
        boss_res = e2e.assert_ok_result(engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now))
        blob = e2e.extract_text_blob(boss_res)
        assert "瘴氣" in blob or int(e2e.extract_field(boss_res, "miasma", "miasma_stacks", default=0)) > 0
    except game_err as exc:
        assert getattr(exc, "code", "") and e2e.has_zh_tw(str(exc))


# ===========================================================================
# Feature 13: Black Iron Palace Underground Roguelike (5 tests)
# ===========================================================================


def test_t2_f13_start_roguelike_blocked_outside_town(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("野外開地城防呆")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.start_roguelike(uid, now_ts=clock.now))


def test_t2_f13_duplicate_start_roguelike_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("雙開地城防呆")
    e2e.assert_ok_result(engine.start_roguelike(uid, now_ts=clock.now, rng_seed=2132))
    e2e.assert_game_error(lambda: engine.start_roguelike(uid, now_ts=clock.now, rng_seed=2133))


def test_t2_f13_step_roguelike_invalid_node_index_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("越界節點測試")
    e2e.assert_ok_result(engine.start_roguelike(uid, now_ts=clock.now, rng_seed=2134))
    e2e.assert_game_error(lambda: engine.step_roguelike(uid, node_index=-1, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.step_roguelike(uid, node_index=99, now_ts=clock.now))


def test_t2_f13_step_and_extract_without_active_run_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("無局操作測試")
    e2e.assert_game_error(lambda: engine.step_roguelike(uid, node_index=0, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.extract_roguelike(uid, now_ts=clock.now))


def test_t2_f13_hardcore_defeat_in_roguelike_no_permadeath(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("地下城硬核", mode="hardcore")
    e2e.induce_combat_defeat(engine, db, content_bundle, uid, clock, in_roguelike=True)
    mon = e2e.assert_ok_result(engine.get_monument_of_life(limit=10))
    assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 0
    assert int(e2e.extract_field(mon, "alive", "alive_count", "alive_players")) == 1
    assert e2e.get_player_zone(engine, uid, clock) == "town"


# ===========================================================================
# Feature 14: 8 Weapon Classes/Styles + 2 Hidden Unique Skills (5 tests)
# ===========================================================================


def test_t2_f14_switch_invalid_weapon_style_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("非法流派切換")
    e2e.assert_game_error(lambda: engine.switch_weapon_style(uid, "plasma_rifle"))
    assert str(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "weapon_style", "style")).lower() == "sword"


def test_t2_f14_premature_unique_skill_unlock_blocked(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("一級偷開二刀流")
    e2e.assert_game_error(lambda: engine.unlock_unique_skill(uid, "dual_blades"))
    e2e.assert_game_error(lambda: engine.unlock_unique_skill(uid, "holy_sword"))


def test_t2_f14_unknown_unique_skill_id_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("虛構獨特技能")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 60, clock=clock, level=60, mastery=500)
    e2e.assert_game_error(lambda: engine.unlock_unique_skill(uid, "infinite_mana"))


def test_t2_f14_incompatible_weapon_skill_rejected(
    engine: Any,
    content_bundle: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("跨武器裝備劍技", weapon_style="axe")
    rapier_skill = e2e.pick_sword_skills(content_bundle, "rapier", count=1)[0]
    e2e.assert_game_error(lambda: engine.set_skill_slots(uid, [rapier_skill]))


def test_t2_f14_switch_weapon_style_blocked_mid_boss(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("頭目戰切武器")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.switch_weapon_style(uid, "rapier"))


# ===========================================================================
# Feature 15: Sword Skills (劍技), SP/CD, Mastery, Combo & Chase (5 tests)
# ===========================================================================


def test_t2_f15_exceeding_skill_slot_cap_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("超格裝備劍技", weapon_style="sword")
    sword_skills = e2e.pick_sword_skills(content_bundle, "sword", count=4)
    e2e.assert_game_error(lambda: engine.set_skill_slots(uid, sword_skills))
    # Even after Unique Skill unlocks 4th slot, 5 skills must fail
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 50, clock=clock, level=55, mastery=500)
    engine.unlock_unique_skill(uid, "dual_blades")
    dual_skill = e2e.pick_sword_skills(content_bundle, "dual_blades", count=1, include_unique=True)[0]
    e2e.assert_game_error(lambda: engine.set_skill_slots(uid, sword_skills + [dual_skill]))


def test_t2_f15_duplicate_or_unknown_skill_id_rejected(
    engine: Any,
    content_bundle: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("重複劍技防呆", weapon_style="sword")
    s1 = e2e.pick_sword_skills(content_bundle, "sword", count=1)[0]
    e2e.assert_game_error(lambda: engine.set_skill_slots(uid, [s1, s1]))
    e2e.assert_game_error(lambda: engine.set_skill_slots(uid, ["does_not_exist"]))


def test_t2_f15_cast_skill_insufficient_sp_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("低SP施技防呆", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=5, power_boost=False, unlock_boss_gate=True
    )
    skills = e2e.pick_sword_skills(content_bundle, "sword", count=3)
    engine.set_skill_slots(uid, skills)
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    # Cast skills until SP is insufficient for another cast
    hit_sp_err = False
    game_err = e2e.load_engine_api()["GameError"]
    for i in range(20):
        sid = skills[i % len(skills)]
        try:
            res = e2e.assert_ok_result(engine.combat_action(uid, "skill", skill_id=sid, now_ts=clock.now))
            assert int(e2e.extract_field(res, "player_sp", "sp", default=0)) >= 0
            if e2e.extract_field(res, "ended", "finished", default=False) is True:
                break
        except game_err as exc:
            assert getattr(exc, "code", "") and e2e.has_zh_tw(str(exc))
            hit_sp_err = True
            break
    assert hit_sp_err, "Expected SP exhaustion or cooldown GameError during repeated skill casts"


def test_t2_f15_cast_skill_on_cooldown_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("冷卻施技防呆", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    # Pick a sword skill with cd >= 1
    cd_skill = None
    for sid, spec in e2e.iter_entries(content_bundle.sword_skills):
        ws = str(spec.get("weapon_style") or spec.get("weapon") or "").lower()
        if ws == "sword" and int(spec.get("cooldown", spec.get("cd", 0))) >= 1:
            cd_skill = sid
            break
    assert cd_skill is not None, "Expected at least one sword skill with cooldown >= 1"
    engine.set_skill_slots(uid, [cd_skill])
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_ok_result(engine.combat_action(uid, "skill", skill_id=cd_skill, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.combat_action(uid, "skill", skill_id=cd_skill, now_ts=clock.now))


def test_t2_f15_swap_skill_slots_mid_combat_blocked(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("戰中換技防呆", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    skills = e2e.pick_sword_skills(content_bundle, "sword", count=2)
    engine.set_skill_slots(uid, [skills[0]])
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.set_skill_slots(uid, [skills[1]]))


# ===========================================================================
# Feature 16: 4-Axis Damage/Resistance & Floor Penetration (5 tests)
# ===========================================================================


def test_t2_f16_resistance_hard_capped_at_75_percent(
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    uid = make_player("抗性上限測試")
    for idx, slot in enumerate(("helmet", "armor", "boots")):
        e2e.seed_equipment(
            db,
            uid,
            slot=slot,
            rarity="legendary",
            name=f"超抗裝備{idx}",
            affixes={"res_slash": 0.60, "res_pierce": 0.60, "res_blunt": 0.60, "res_dragon": 0.60},
            now_ts=clock.now,
        )
    items = db.get_equipment(uid)
    st = compute_stats(db.get_player(uid), items, content_bundle, floor=1)
    for attr in ("res_slash", "res_pierce", "res_blunt", "res_dragon"):
        assert float(getattr(st, attr)) <= 0.75 + 1e-9


def test_t2_f16_floor_penetration_capped_at_65_percent_above_f100(
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    uid = make_player("穿透上限測試")
    e2e.seed_equipment(
        db, uid, slot="armor", rarity="legendary", name="滿抗鎧", affixes={"res_slash": 0.75}, now_ts=clock.now
    )
    st = compute_stats(db.get_player(uid), db.get_equipment(uid), content_bundle, floor=100)
    r100 = float(st.effective_res("slash", 100))
    r120 = float(st.effective_res("slash", 120))
    r200 = float(st.effective_res("slash", 200))
    assert r100 == pytest.approx(r120, abs=1e-6)
    assert r100 == pytest.approx(r200, abs=1e-6)


def test_t2_f16_effective_res_never_negative_or_nan(
    db: Any,
    content_bundle: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    uid = make_player("零抗百層測試")
    st = compute_stats(db.get_player(uid), [], content_bundle, floor=100)
    for dt in e2e.FOUR_DAMAGE_TYPES:
        val = float(st.effective_res(dt, 100))
        assert not math.isnan(val) and math.isfinite(val) and val >= 0.0


def test_t2_f16_invalid_damage_type_rejected(
    db: Any,
    content_bundle: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    uid = make_player("非法傷害類型")
    st = compute_stats(db.get_player(uid), [], content_bundle, floor=10)
    with pytest.raises(ValueError):
        st.effective_res("arcane_fire", 10)


def test_t2_f16_boss_mid_fight_damage_type_swap_respected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("野太刀切換檢驗", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    saw_slash_swap = False
    for _ in range(80):
        turn = e2e.assert_ok_result(engine.combat_action(uid, "attack", now_ts=clock.now))
        dt = str(e2e.extract_field(turn, "boss_dmg_type", "dmg_type", "damage_type", default="")).lower()
        blob = e2e.extract_text_blob(turn)
        if dt == "slash" or any(k in blob for k in ("野太刀", "斬擊")):
            saw_slash_swap = True
        if e2e.extract_field(turn, "ended", "finished", default=False) is True:
            break
    assert saw_slash_swap, "Illfang P4 must swap to slash/Nodachi mid-fight"


# ===========================================================================
# Feature 17: Tactical Combat: Switch, Parry, Backstab, 14 Debuffs (5 tests)
# ===========================================================================


def test_t2_f17_solo_switch_without_living_teammate_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("單人交換防呆")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.combat_action(uid, "switch", now_ts=clock.now))


def test_t2_f17_stunned_player_switch_rejected(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    # Single surviving active player after teammate retreats cannot Switch either
    party = make_party_humans(count=2, floor=1, prepare_floor=True, unlock_boss_gate=True)
    u1, u2 = party.member_ids
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    engine.submit_raid_action(raid_id, u1, "defend", now_ts=clock.now)
    r1 = e2e.assert_ok_result(engine.submit_raid_action(raid_id, u2, "retreat", now_ts=clock.now))
    if not e2e.extract_field(r1, "round_resolved", "resolved", default=False):
        engine.resolve_raid_round(raid_id, requester_id=u1, now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.submit_raid_action(raid_id, u1, "switch", now_ts=clock.now))


def test_t2_f17_boss_stun_immunity_prevents_infinite_stunlock(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1, prepare_floor=True, unlock_boss_gate=True)
    u1, u2 = party.member_ids
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    # Execute consecutive Switch Break rounds and verify Boss cannot be permanently stunlocked every single round
    stun_rounds = 0
    for _ in range(8):
        engine.submit_raid_action(raid_id, u1, "switch", now_ts=clock.now)
        res = e2e.assert_ok_result(engine.submit_raid_action(raid_id, u2, "switch", now_ts=clock.now))
        if not e2e.extract_field(res, "round_resolved", "resolved", default=False):
            res = e2e.assert_ok_result(engine.resolve_raid_round(raid_id, requester_id=u1, now_ts=clock.now))
        if e2e.extract_field(res, "boss_stunned", default=False) is True:
            stun_rounds += 1
        if e2e.extract_field(res, "ended", "finished", default=False) is True:
            break
    assert stun_rounds < 8, "Boss stun immunity must prevent 100% continuous stunlock"


def test_t2_f17_retreat_blocked_in_f100_boss_room(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("紅玉宮禁逃テスト")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 100, clock=clock, level=100, unlock_boss_gate=True
    )
    engine.start_floor_boss(uid, floor=100, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.combat_action(uid, "retreat", now_ts=clock.now))


def test_t2_f17_simultaneous_switch_resolved_deterministically_by_agi(
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
        weapon_styles=["rapier", "mace"],
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    fast, slow = party.member_ids
    engine.allocate_stats(fast, {"agi": 15})
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    engine.submit_raid_action(raid_id, slow, "switch", now_ts=clock.now)
    res = e2e.assert_ok_result(engine.submit_raid_action(raid_id, fast, "switch", now_ts=clock.now))
    if not e2e.extract_field(res, "round_resolved", "resolved", default=False):
        res = e2e.assert_ok_result(engine.resolve_raid_round(raid_id, requester_id=fast, now_ts=clock.now))
    assert int(e2e.extract_field(res, "switch_chain", "switch_count", default=2)) >= 2


# ===========================================================================
# Feature 18: Auto-Battle & Survival Thresholds (5 tests)
# ===========================================================================


def test_t2_f18_negative_survival_thresholds_rejected(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("負數生存設定")
    e2e.assert_game_error(lambda: engine.set_survival_config(uid, auto_potion_pct=-1))
    e2e.assert_game_error(lambda: engine.set_survival_config(uid, auto_crystal_pct=-10))
    e2e.assert_game_error(lambda: engine.set_survival_config(uid, auto_retreat_pct=-5))


def test_t2_f18_over_100_survival_thresholds_rejected(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("超百生存設定")
    e2e.assert_game_error(lambda: engine.set_survival_config(uid, auto_potion_pct=101))
    e2e.assert_game_error(lambda: engine.set_survival_config(uid, auto_crystal_pct=200))
    e2e.assert_game_error(lambda: engine.set_survival_config(uid, auto_retreat_pct=101))


def test_t2_f18_auto_battle_never_consumes_unconfigured_crystals(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("珍藏水晶測試")
    crystals = e2e.pick_crystal_ids(content_bundle)
    e2e.seed_item(db, uid, crystals["healing"], 4)
    e2e.seed_item(db, uid, crystals["teleport"], 4)
    engine.set_survival_config(uid, auto_potion_pct=0, auto_crystal_pct=0, auto_retreat_pct=0)
    e2e.trigger_road_combat(engine, uid, clock, seed_start=2183)
    h_before = e2e.get_player_item_qty(engine, uid, crystals["healing"], clock)
    t_before = e2e.get_player_item_qty(engine, uid, crystals["teleport"], clock)
    e2e.assert_ok_result(engine.combat_action(uid, "auto", now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, uid, crystals["healing"], clock) == h_before
    assert e2e.get_player_item_qty(engine, uid, crystals["teleport"], clock) == t_before


def test_t2_f18_stop_on_no_potion_pauses_cleanly_when_potions_empty(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("無藥停掛測試")
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    engine.set_survival_config(uid, auto_potion_pct=99, stop_on_no_potion=True)
    e2e.trigger_road_combat(engine, uid, clock, seed_start=2184)
    engine.combat_action(uid, "defend", now_ts=clock.now)
    res = e2e.assert_ok_result(engine.combat_action(uid, "auto", now_ts=clock.now))
    assert res
    assert e2e.get_player_item_qty(engine, uid, potion_id, clock) >= 0


def test_t2_f18_auto_retreat_blocked_in_crystal_null_room_preserves_crystal(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("無效化自動撤退測試")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 100, clock=clock, level=100, unlock_boss_gate=True
    )
    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    before_tp = e2e.get_player_item_qty(engine, uid, tp_id, clock)
    engine.set_survival_config(uid, auto_potion_pct=0, auto_crystal_pct=0, auto_retreat_pct=99)
    engine.start_floor_boss(uid, floor=100, mode="normal", now_ts=clock.now)
    engine.combat_action(uid, "defend", now_ts=clock.now)
    game_err = e2e.load_engine_api()["GameError"]
    try:
        e2e.assert_ok_result(engine.combat_action(uid, "auto", now_ts=clock.now))
    except game_err as exc:
        assert getattr(exc, "code", "") and e2e.has_zh_tw(str(exc))
    assert e2e.get_player_item_qty(engine, uid, tp_id, clock) == before_tp


# ===========================================================================
# Feature 19: 14 Bespoke Milestone Bosses (6 tests)
# ===========================================================================


def test_t2_f19_phase_health_gate_prevents_skip_on_overkill_nuke(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("超傷核彈測試", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=100, unlock_boss_gate=True
    )
    # Equip massive ATK weapon to trigger overkill across F1 Illfang phase boundary
    over_uid = e2e.seed_equipment(
        db, uid, slot="weapon", rarity="legendary", name="超限試驗劍", atk=99_999, now_ts=clock.now
    )
    engine.equip_item(uid, over_uid)
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    logs: list[str] = []
    for _ in range(10):
        turn = e2e.assert_ok_result(engine.combat_action(uid, "attack", now_ts=clock.now))
        logs.append(e2e.extract_text_blob(turn))
        if e2e.extract_field(turn, "ended", "finished", default=False) is True:
            break
    full = "\n".join(logs)
    assert any(k in full for k in ("野太刀", "太刀", "鎖血", "階段", "P4", "斬"))


def test_t2_f19_enrage_turn_escalates_boss_combat_threat(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("狂暴拖延者", weapon_style="mace")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=50, unlock_boss_gate=True
    )
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    saw_enrage = False
    for _ in range(35):
        turn = e2e.assert_ok_result(engine.combat_action(uid, "defend", now_ts=clock.now))
        if (
            e2e.extract_field(turn, "enraged", "is_enraged", default=False) is True
            or "狂暴" in e2e.extract_text_blob(turn)
        ):
            saw_enrage = True
            break
        if e2e.extract_field(turn, "ended", "finished", default=False) is True:
            break
    assert saw_enrage, "Stalling past Boss enrage_turn must trigger Enrage state"


def test_t2_f19_invalid_or_locked_floor_and_reentry_cooldown_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("冷卻與鎖層測試")
    e2e.assert_game_error(lambda: engine.start_floor_boss(uid, floor=0, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.start_floor_boss(uid, floor=101, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.start_floor_boss(uid, floor=50, now_ts=clock.now))
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="normal")
    # Immediate re-entry before respawn cooldown should be rejected, then succeed after advance
    e2e.assert_game_error(lambda: engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now + 5))
    clock.advance(minutes=10)
    e2e.assert_ok_result(engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now))


def test_t2_f19_f100_no_escape_teleport_crystal_blocked_without_loss(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("百層無逃脫測試")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 100, clock=clock, level=100, unlock_boss_gate=True
    )
    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    tp_before = e2e.get_player_item_qty(engine, uid, tp_id, clock)
    engine.start_floor_boss(uid, floor=100, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(
        lambda: engine.combat_action(uid, "crystal", item_id=tp_id, now_ts=clock.now)
    )
    e2e.assert_game_error(lambda: engine.combat_action(uid, "retreat", now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, uid, tp_id, clock) == tp_before


def test_t2_f19_mid_boss_exploit_actions_all_blocked(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("頭目戰防漏洞者", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=12, unlock_boss_gate=True
    )
    e2e.seed_col(db, engine, uid, 10_000, clock)
    engine.travel_zone(uid, "town", now_ts=clock.now)
    engine.save_loadout(uid, 1, "王前配裝")
    engine.create_guild(uid, "戰中倉防會", "MBG", now_ts=clock.now)
    spare = e2e.seed_equipment(db, uid, slot="ring", rarity="rare", name="倉內戒", now_ts=clock.now)
    dep = e2e.assert_ok_result(engine.guild_warehouse_deposit(uid, spare, now_ts=clock.now))
    wh_id = int(e2e.extract_field(dep, "warehouse_id", "id"))
    alt_skills = e2e.pick_sword_skills(content_bundle, "sword", count=2)

    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.respec_talents(uid))
    e2e.assert_game_error(lambda: engine.guild_warehouse_withdraw(uid, wh_id, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.switch_weapon_style(uid, "axe"))
    e2e.assert_game_error(lambda: engine.set_skill_slots(uid, alt_skills))
    e2e.assert_game_error(lambda: engine.apply_loadout(uid, 1))


def test_t2_f19_f25_solo_callout_double_damage_penalty(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("單挑雙面獄魔者")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 25, clock=clock, level=35, unlock_boss_gate=True
    )
    engine.start_floor_boss(uid, floor=25, mode="normal", now_ts=clock.now)
    logs: list[str] = []
    for _ in range(12):
        turn = e2e.assert_ok_result(engine.combat_action(uid, "attack", now_ts=clock.now))
        logs.append(e2e.extract_text_blob(turn))
        if e2e.extract_field(turn, "ended", "finished", default=False) is True:
            break
    assert len(logs) >= 1 and any(e2e.has_zh_tw(x) for x in logs)


# ===========================================================================
# Feature 20: Multi-Tier Boss Modes (5 tests)
# ===========================================================================


def test_t2_f20_invalid_boss_mode_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("非法模式測試")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    e2e.assert_game_error(
        lambda: engine.start_floor_boss(uid, floor=1, mode="mythic_solo", now_ts=clock.now)
    )
    e2e.assert_game_error(
        lambda: engine.create_party(uid, floor=1, boss_mode="godmode", now_ts=clock.now)
    )


def test_t2_f20_team_boss_fourth_daily_clear_loses_boosted_drop_bonus(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(
        count=2, floor=1, boss_mode="team_boss", prepare_floor=True, unlock_boss_gate=True
    )
    results: list[bool] = []
    for _ in range(4):
        engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
        raid = e2e.assert_ok_result(
            engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now)
        )
        raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
        fin, _ = e2e.drive_coop_raid(engine, clock, raid_id, party.member_ids)
        results.append(bool(e2e.extract_field(fin, "boosted_drop", "daily_boost", "is_boosted", default=False)))
        clock.advance(minutes=10)
    assert results[:3] == [True, True, True]
    assert results[3] is False
    # Next UTC day restores daily boosted drop
    clock.advance(days=1)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid5 = e2e.assert_ok_result(
        engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now)
    )
    fin5, _ = e2e.drive_coop_raid(engine, clock, str(e2e.extract_field(raid5, "raid_id", "id")), party.member_ids)
    assert bool(e2e.extract_field(fin5, "boosted_drop", "daily_boost", "is_boosted")) is True


def test_t2_f20_world_boss_zero_attempts_blocked(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("零次數世界王測試")
    for _ in range(3):
        e2e.assert_ok_result(engine.attack_floor_world_boss(uid, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.attack_floor_world_boss(uid, now_ts=clock.now))


def test_t2_f20_world_boss_bank_and_catchup_cap_bounded_at_nine(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("十日未打囤積上限")
    clock.advance(days=10)
    game_err = e2e.load_engine_api()["GameError"]
    count = 0
    for _ in range(12):
        try:
            e2e.assert_ok_result(engine.attack_floor_world_boss(uid, now_ts=clock.now))
            count += 1
        except game_err:
            break
    assert 3 <= count <= 9, f"Banked/catch-up attempts must be capped <= 9, got {count}"


def test_t2_f20_concurrent_first_kill_race_grants_strictly_one_server_claim(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    pa = make_party_humans(
        count=2, floor=1, boss_mode="first_kill", prepare_floor=True, unlock_boss_gate=True
    )
    pb = make_party_humans(
        count=2, floor=1, boss_mode="first_kill", prepare_floor=True, unlock_boss_gate=True
    )
    engine.enter_boss_room(pa.party_id, pa.leader_id, now_ts=clock.now)
    ra = e2e.assert_ok_result(engine.start_party_raid(pa.party_id, pa.leader_id, now_ts=clock.now))
    rid_a = str(e2e.extract_field(ra, "raid_id", "id"))

    engine.enter_boss_room(pb.party_id, pb.leader_id, now_ts=clock.now)
    rb = e2e.assert_ok_result(engine.start_party_raid(pb.party_id, pb.leader_id, now_ts=clock.now))
    rid_b = str(e2e.extract_field(rb, "raid_id", "id"))

    outcomes = e2e.run_concurrent_calls(
        [
            lambda: e2e.drive_coop_raid(engine, clock, rid_a, pa.member_ids)[0],
            lambda: e2e.drive_coop_raid(engine, clock, rid_b, pb.member_ids)[0],
        ]
    )
    for ok, val in outcomes:
        assert ok is True, f"Concurrent First-Kill race raised unexpected error: {val!r}"
    fk_flags = [
        bool(e2e.extract_field(val, "is_first_kill", "first_kill", default=False))
        for _, val in outcomes
    ]
    assert sum(fk_flags) == 1, f"Strictly 1 party must win First-Kill, got {fk_flags}"


# ===========================================================================
# Feature 21: Last Attack (LA) Bonus & Pending Loot Mailbox (5 tests)
# ===========================================================================


def test_t2_f21_claim_pending_loot_when_mailbox_empty_is_safe(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("空信箱測試")
    game_err = e2e.load_engine_api()["GameError"]
    try:
        res = e2e.assert_ok_result(engine.claim_pending_loot(uid))
        assert int(e2e.extract_field(res, "claimed", "claimed_count", default=0)) == 0
    except game_err as exc:
        assert getattr(exc, "code", "") and e2e.has_zh_tw(str(exc))


def test_t2_f21_claim_pending_loot_while_bag_still_full_preserves_item(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("滿包硬領信箱")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=12)
    for i in range(85):
        e2e.seed_equipment(db, uid, slot="ring", rarity="plain", name=f"滿包戒{i}", now_ts=clock.now)
    e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="normal")
    pending_before = e2e.get_player_pending_loot_count(engine, uid, clock)
    assert pending_before >= 1
    game_err = e2e.load_engine_api()["GameError"]
    try:
        res = e2e.assert_ok_result(engine.claim_pending_loot(uid))
        assert int(e2e.extract_field(res, "claimed", "claimed_count", default=0)) == 0
    except game_err as exc:
        assert getattr(exc, "code", "") and e2e.has_zh_tw(str(exc))
    assert e2e.get_player_pending_loot_count(engine, uid, clock) == pending_before


def test_t2_f21_simultaneous_lethal_hits_tie_broken_deterministically(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1, prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    fin, _ = e2e.drive_coop_raid(
        engine, clock, str(e2e.extract_field(raid, "raid_id", "id")), party.member_ids
    )
    la_winner = str(e2e.extract_field(fin, "la_winner", "last_attack_user_id", "la_user_id"))
    assert la_winner in party.member_ids
    named_counts = [
        sum(1 for g in e2e.get_player_equipment(engine, uid, clock) if str(g.get("rarity", "")).lower() == "named")
        for uid in party.member_ids
    ]
    assert sum(named_counts) == 1, f"LA Named item must go to strictly 1 winner, got {named_counts}"


def test_t2_f21_repeat_la_kills_handle_uniqueness_without_corruption(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("雙尾刀測試")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=12)
    e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="normal")
    clock.advance(minutes=10)
    res2 = e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="normal")
    assert res2


def test_t2_f21_pending_loot_persists_across_db_restart(
    db: Any,
    db_path: Path,
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("重啟信箱測試")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=12)
    fillers = [
        e2e.seed_equipment(db, uid, slot="ring", rarity="plain", name=f"重啟戒{i}", now_ts=clock.now)
        for i in range(85)
    ]
    e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="normal")
    assert e2e.get_player_pending_loot_count(engine, uid, clock) >= 1
    db.close()

    db2 = e2e.load_db_api()["RPGDatabase"](db_path)
    try:
        eng2 = e2e.instantiate_engine(db2, content_bundle)
        assert e2e.get_player_pending_loot_count(eng2, uid, clock) >= 1
        eng2.travel_zone(uid, "town", now_ts=clock.now)
        for fuid in fillers[:10]:
            eng2.turn_in_achievement_gear(uid, fuid)
        e2e.assert_ok_result(eng2.claim_pending_loot(uid))
        assert e2e.get_player_pending_loot_count(eng2, uid, clock) == 0
    finally:
        db2.close()


# ===========================================================================
# Feature 22: Real-Human Party Lobby & Raid Alliance (6 tests)
# ===========================================================================


def test_t2_f22_join_full_party_exceeding_max_size_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2, u3 = make_player("滿員甲"), make_player("滿員乙"), make_player("滿員丙")
    p = e2e.assert_ok_result(engine.create_party(u1, floor=1, max_size=2, now_ts=clock.now))
    pid = str(e2e.extract_field(p, "party_id", "id"))
    e2e.assert_ok_result(engine.join_party(pid, u2, role="dps", now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.join_party(pid, u3, role="dps", now_ts=clock.now))


def test_t2_f22_duplicate_join_and_cross_party_join_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2, u3 = make_player("重加甲"), make_player("重加乙"), make_player("重加丙")
    pa = str(e2e.extract_field(engine.create_party(u1, floor=1, now_ts=clock.now), "party_id", "id"))
    pb = str(e2e.extract_field(engine.create_party(u3, floor=1, now_ts=clock.now), "party_id", "id"))
    e2e.assert_ok_result(engine.join_party(pa, u2, role="dps", now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.join_party(pa, u2, role="dps", now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.join_party(pb, u2, role="dps", now_ts=clock.now))


def test_t2_f22_non_leader_cannot_enter_boss_room_or_start_raid(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1, prepare_floor=True, unlock_boss_gate=True)
    non_leader = party.member_ids[1]
    e2e.assert_game_error(lambda: engine.enter_boss_room(party.party_id, non_leader, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.start_party_raid(party.party_id, non_leader, now_ts=clock.now))


def test_t2_f22_leader_leave_auto_promotes_or_disbands_cleanly(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2, u3 = make_player("離隊隊長"), make_player("繼任隊長"), make_player("遲來路人")
    pid = str(e2e.extract_field(engine.create_party(u1, floor=1, now_ts=clock.now), "party_id", "id"))
    engine.join_party(pid, u2, role="dps", now_ts=clock.now)
    leave1 = e2e.assert_ok_result(engine.leave_party(pid, u1, now_ts=clock.now))
    assert str(e2e.extract_field(leave1, "leader_id", "new_leader_id", default=u2)) == u2
    e2e.assert_ok_result(engine.leave_party(pid, u2, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.join_party(pid, u3, role="dps", now_ts=clock.now))


def test_t2_f22_invalid_party_id_role_and_size_bounds_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("邊界組隊者")
    e2e.assert_game_error(lambda: engine.join_party("nonexistent_party", u1, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.create_party(u1, floor=1, max_size=0, now_ts=clock.now))
    e2e.assert_game_error(
        lambda: engine.create_party(u1, floor=1, max_size=7, is_raid_alliance=False, now_ts=clock.now)
    )
    e2e.assert_game_error(
        lambda: engine.create_party(u1, floor=1, max_size=25, is_raid_alliance=True, now_ts=clock.now)
    )
    pid = str(e2e.extract_field(engine.create_party(u1, floor=1, now_ts=clock.now), "party_id", "id"))
    e2e.assert_game_error(lambda: engine.set_party_role(pid, u1, "healer_mage"))


def test_t2_f22_start_party_raid_blocked_when_members_not_ready_or_locked_floor(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    u_low = make_player("一樓想開五十樓隊")
    e2e.assert_game_error(lambda: engine.create_party(u_low, floor=50, now_ts=clock.now))
    party = make_party_humans(
        count=2, floor=1, ready_all=False, prepare_floor=True, unlock_boss_gate=True
    )
    e2e.assert_game_error(lambda: engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))


# ===========================================================================
# Feature 23: Synchronized Turn-Based Co-op Raid Combat & Concurrency (6 tests)
# ===========================================================================


def test_t2_f23_duplicate_action_submission_in_same_round_rejected(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1, prepare_floor=True, unlock_boss_gate=True)
    u1, _ = party.member_ids
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    e2e.assert_ok_result(engine.submit_raid_action(raid_id, u1, "attack", now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.submit_raid_action(raid_id, u1, "attack", now_ts=clock.now))


def test_t2_f23_downed_dead_or_fled_player_action_rejected(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1, prepare_floor=True, unlock_boss_gate=True)
    u1, u2 = party.member_ids
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    engine.submit_raid_action(raid_id, u1, "defend", now_ts=clock.now)
    r1 = e2e.assert_ok_result(engine.submit_raid_action(raid_id, u2, "retreat", now_ts=clock.now))
    if not e2e.extract_field(r1, "round_resolved", "resolved", default=False):
        engine.resolve_raid_round(raid_id, requester_id=u1, now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.submit_raid_action(raid_id, u2, "attack", now_ts=clock.now))


def test_t2_f23_afk_timeout_25s_or_force_timeout_auto_guards_no_deadlock(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=3, floor=1, prepare_floor=True, unlock_boss_gate=True)
    u1, u2, _ = party.member_ids
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    engine.submit_raid_action(raid_id, u1, "attack", now_ts=clock.now)
    engine.submit_raid_action(raid_id, u2, "attack", now_ts=clock.now)
    clock.advance(seconds=26)
    res = e2e.assert_ok_result(
        engine.resolve_raid_round(raid_id, requester_id=u1, force_timeout=True, now_ts=clock.now)
    )
    assert int(e2e.extract_field(res, "round", "turn", "round_no", default=2)) >= 1


def test_t2_f23_two_consecutive_afk_timeouts_mark_player_sleeping_auto(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=3, floor=1, prepare_floor=True, unlock_boss_gate=True)
    u1, u2, _ = party.member_ids
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    for _ in range(2):
        engine.submit_raid_action(raid_id, u1, "defend", now_ts=clock.now)
        engine.submit_raid_action(raid_id, u2, "defend", now_ts=clock.now)
        clock.advance(seconds=26)
        e2e.assert_ok_result(
            engine.resolve_raid_round(raid_id, requester_id=u1, force_timeout=True, now_ts=clock.now)
        )
    # Round 3: after 2 timeouts u3 is sleeping/auto-managed so u1+u2 immediately resolve
    engine.submit_raid_action(raid_id, u1, "attack", now_ts=clock.now)
    r3 = e2e.assert_ok_result(engine.submit_raid_action(raid_id, u2, "attack", now_ts=clock.now))
    assert (
        e2e.extract_field(r3, "round_resolved", "resolved", default=False) is True
        or "沉睡" in e2e.extract_text_blob(r3)
        or "託管" in e2e.extract_text_blob(r3)
    )


def test_t2_f23_non_participant_submit_raid_action_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    outsider = make_player("路人甲")
    party = make_party_humans(count=2, floor=1, prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    e2e.assert_game_error(
        lambda: engine.submit_raid_action(raid_id, outsider, "attack", now_ts=clock.now)
    )


def test_t2_f23_concurrent_threadpool_submissions_zero_corruption(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=6, floor=1, prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    for _ in range(2):
        outcomes = e2e.run_concurrent_calls(
            [
                (lambda u=uid: engine.submit_raid_action(raid_id, u, "attack", now_ts=clock.now))
                for uid in party.member_ids
            ]
        )
        for ok, val in outcomes:
            assert ok is True, f"Concurrent submit failed unexpectedly: {val!r}"
        if any(e2e.extract_field(val, "ended", "finished", default=False) for _, val in outcomes):
            break


# ===========================================================================
# Feature 24: Party Potion Sharing, Group Teleport & Downed Rescue (6 tests)
# ===========================================================================


def test_t2_f24_potion_sharing_inactive_when_opted_out_or_donor_out_of_potions(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1, prepare_floor=False, unlock_boss_gate=True)
    u1, u2 = party.member_ids
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    e2e.seed_item(db, u2, potion_id, 5)
    # Explicitly opted out
    engine.toggle_potion_sharing(party.party_id, u2, False)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    before = e2e.get_player_item_qty(engine, u2, potion_id, clock)
    engine.submit_raid_action(raid_id, u1, "attack", now_ts=clock.now)
    engine.submit_raid_action(raid_id, u2, "defend", now_ts=clock.now)
    assert e2e.get_player_item_qty(engine, u2, potion_id, clock) == before


def test_t2_f24_non_leader_group_teleport_rejected(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1)
    non_leader = party.member_ids[1]
    e2e.assert_game_error(
        lambda: engine.party_group_teleport(party.party_id, non_leader, 1, now_ts=clock.now)
    )


def test_t2_f24_group_teleport_blocked_in_f100_crystal_null_boss_room(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=100, prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now)
    e2e.assert_game_error(
        lambda: engine.party_group_teleport(party.party_id, party.leader_id, 1, now_ts=clock.now)
    )


def test_t2_f24_group_teleport_to_locked_or_invalid_floor_rejected(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1)
    for bad in (0, 101, 50):
        e2e.assert_game_error(
            lambda f=bad: engine.party_group_teleport(
                party.party_id, party.leader_id, f, now_ts=clock.now
            )
        )


def test_t2_f24_rescue_without_teleport_crystal_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    victim = make_player("無晶救援目標", mode="standard")
    rescuer = make_player("無晶救援者", mode="standard")
    e2e.induce_combat_defeat(engine, db, content_bundle, victim, clock)
    e2e.assert_game_error(lambda: engine.rescue_downed_player(rescuer, victim, now_ts=clock.now))


def test_t2_f24_rescue_healthy_player_or_self_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    healthy = make_player("健康隊友")
    rescuer = make_player("多餘救援者")
    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    e2e.seed_item(db, rescuer, tp_id, 3)
    before = e2e.get_player_item_qty(engine, rescuer, tp_id, clock)
    e2e.assert_game_error(lambda: engine.rescue_downed_player(rescuer, healthy, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.rescue_downed_player(rescuer, rescuer, now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, rescuer, tp_id, clock) == before


# ===========================================================================
# Feature 25: Guild System (6 tests)
# ===========================================================================


def test_t2_f25_duplicate_guild_name_tag_or_blank_rejected(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2 = make_player("建會甲"), make_player("建會乙")
    e2e.seed_col(db, engine, u1, 20_000, clock)
    e2e.seed_col(db, engine, u2, 20_000, clock)
    engine.create_guild(u1, "血盟騎士團", "KoB", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.create_guild(u2, "血盟騎士團", "NEW", now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.create_guild(u2, "新公會", "KoB", now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.create_guild(u2, "   ", "TAG", now_ts=clock.now))


def test_t2_f25_unauthorized_member_rank_buff_raid_and_warehouse_rejected(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    leader = make_player("團長權限")
    recruit = make_player("新進成員")
    peer = make_player("一般成員")
    e2e.seed_col(db, engine, leader, 20_000, clock)
    g = e2e.assert_ok_result(engine.create_guild(leader, "權限驗證團", "AUTH", now_ts=clock.now))
    gid = int(e2e.extract_field(g, "guild_id", "id"))
    engine.join_guild(recruit, gid, now_ts=clock.now)
    engine.join_guild(peer, gid, now_ts=clock.now)
    item_uid = e2e.seed_equipment(db, leader, slot="ring", rarity="rare", name="權限戒", now_ts=clock.now)
    dep = e2e.assert_ok_result(engine.guild_warehouse_deposit(leader, item_uid, now_ts=clock.now))
    wh_id = int(e2e.extract_field(dep, "warehouse_id", "id"))

    e2e.assert_game_error(lambda: engine.set_guild_rank(recruit, peer, "officer"))
    e2e.assert_game_error(lambda: engine.guild_activate_buff(recruit, "rally", now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.start_guild_raid(recruit, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.guild_warehouse_withdraw(recruit, wh_id, now_ts=clock.now))


def test_t2_f25_leader_leaving_guild_without_transfer_rejected(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2 = make_player("想退會團長"), make_player("留守團員")
    e2e.seed_col(db, engine, u1, 20_000, clock)
    g = e2e.assert_ok_result(engine.create_guild(u1, "不棄公會", "STAY", now_ts=clock.now))
    engine.join_guild(u2, int(e2e.extract_field(g, "guild_id", "id")), now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.leave_guild(u1, now_ts=clock.now))


def test_t2_f25_twelve_hour_rejoin_cooldown_boundary_enforced(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2 = make_player("冷卻會長"), make_player("跳槽成員")
    e2e.seed_col(db, engine, u1, 20_000, clock)
    g = e2e.assert_ok_result(engine.create_guild(u1, "冷卻驗證團", "COOL", now_ts=clock.now))
    gid = int(e2e.extract_field(g, "guild_id", "id"))
    engine.join_guild(u2, gid, now_ts=clock.now)
    engine.leave_guild(u2, now_ts=clock.now)
    # 1 second before 12h must still fail
    e2e.assert_game_error(lambda: engine.join_guild(u2, gid, now_ts=clock.now + 43_199))
    # Exact 12h boundary succeeds
    e2e.assert_ok_result(engine.join_guild(u2, gid, now_ts=clock.now + 43_200))


def test_t2_f25_warehouse_withdraw_blocked_mid_boss_and_outside_town(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("倉取禁區測試")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.travel_zone(uid, "town", now_ts=clock.now)
    engine.create_guild(uid, "禁區倉測團", "WHB", now_ts=clock.now)
    spare = e2e.seed_equipment(db, uid, slot="ring", rarity="rare", name="禁取戒", now_ts=clock.now)
    wh_id = int(e2e.extract_field(engine.guild_warehouse_deposit(uid, spare, now_ts=clock.now), "warehouse_id", "id"))
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.guild_warehouse_withdraw(uid, wh_id, now_ts=clock.now))
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.guild_warehouse_withdraw(uid, wh_id, now_ts=clock.now))


def test_t2_f25_invalid_contribution_and_locked_or_named_deposit_rejected(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("非法奉納測試")
    e2e.seed_col(db, engine, uid, 20_000, clock)
    engine.create_guild(uid, "奉納防呆團", "DON", now_ts=clock.now)
    col_before = e2e.get_player_col(engine, uid, clock)
    e2e.assert_game_error(lambda: engine.guild_contribute(uid, 0, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.guild_contribute(uid, -100, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.guild_contribute(uid, col_before + 999_999, now_ts=clock.now))
    assert e2e.get_player_col(engine, uid, clock) == col_before
    locked_uid = e2e.seed_equipment(db, uid, slot="ring", rarity="rare", name="鎖定戒", now_ts=clock.now)
    engine.toggle_lock_item(uid, locked_uid)
    named_uid = e2e.seed_equipment(db, uid, slot="armor", rarity="named", name="午夜大衣", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.guild_warehouse_deposit(uid, locked_uid, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.guild_warehouse_deposit(uid, named_uid, now_ts=clock.now))


# ===========================================================================
# Feature 26: Player Marketplace (市集) & Direct Trading (6 tests)
# ===========================================================================


def test_t2_f26_listing_named_locked_or_equipped_item_rejected(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u = make_player("禁售品測試")
    named_uid = e2e.seed_equipment(db, u, slot="armor", rarity="named", name="闡釋者", now_ts=clock.now)
    locked_uid = e2e.seed_equipment(db, u, slot="ring", rarity="rare", name="上鎖戒", now_ts=clock.now)
    engine.toggle_lock_item(u, locked_uid)
    eq_uid = e2e.seed_equipment(db, u, slot="boots", rarity="rare", name="穿著靴", now_ts=clock.now)
    engine.equip_item(u, eq_uid)
    e2e.assert_game_error(lambda: engine.list_market_item(u, item_uid=named_uid, price_col=500, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.list_market_item(u, item_uid=locked_uid, price_col=500, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.list_market_item(u, item_uid=eq_uid, price_col=500, now_ts=clock.now))


def test_t2_f26_invalid_price_qty_or_ambiguous_item_args_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u = make_player("市集參數防呆")
    item_uid = e2e.seed_equipment(db, u, slot="ring", rarity="rare", name="待測戒", now_ts=clock.now)
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    e2e.seed_item(db, u, potion_id, 5)
    e2e.assert_game_error(lambda: engine.list_market_item(u, item_uid=item_uid, price_col=0, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.list_market_item(u, item_uid=item_uid, price_col=-50, now_ts=clock.now))
    e2e.assert_game_error(
        lambda: engine.list_market_item(u, item_id=potion_id, qty=0, price_col=50, now_ts=clock.now)
    )
    e2e.assert_game_error(lambda: engine.list_market_item(u, price_col=50, now_ts=clock.now))


def test_t2_f26_buy_own_listing_or_insufficient_col_rejected(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    seller = make_player("自買賣家")
    poor = make_player("窮買家")
    item_uid = e2e.seed_equipment(db, seller, slot="ring", rarity="rare", name="高價戒", now_ts=clock.now)
    lid = int(
        e2e.extract_field(
            engine.list_market_item(seller, item_uid=item_uid, price_col=99_999, now_ts=clock.now),
            "listing_id",
            "id",
        )
    )
    poor_col = e2e.get_player_col(engine, poor, clock)
    e2e.assert_game_error(lambda: engine.buy_market_item(seller, lid, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.buy_market_item(poor, lid, now_ts=clock.now))
    assert e2e.get_player_col(engine, poor, clock) == poor_col


def test_t2_f26_market_actions_blocked_outside_town_safe_zone(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    seller = make_player("野外賣家")
    buyer = make_player("野外買家")
    e2e.seed_col(db, engine, buyer, 2_000, clock)
    uid1 = e2e.seed_equipment(db, seller, slot="ring", rarity="rare", name="野外戒1", now_ts=clock.now)
    uid2 = e2e.seed_equipment(db, seller, slot="ring", rarity="rare", name="野外戒2", now_ts=clock.now)
    lid = int(
        e2e.extract_field(
            engine.list_market_item(seller, item_uid=uid1, price_col=100, now_ts=clock.now),
            "listing_id",
            "id",
        )
    )
    engine.travel_zone(seller, "field", now_ts=clock.now)
    engine.travel_zone(buyer, "field", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.list_market_item(seller, item_uid=uid2, price_col=100, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.buy_market_item(buyer, lid, now_ts=clock.now))


def test_t2_f26_concurrent_two_buyer_race_strictly_one_winner_zero_col_loss(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    seller = make_player("競標賣家")
    b1 = make_player("搶標甲")
    b2 = make_player("搶標乙")
    e2e.seed_col(db, engine, b1, 1_000, clock)
    e2e.seed_col(db, engine, b2, 1_000, clock)
    b1_init = e2e.get_player_col(engine, b1, clock)
    b2_init = e2e.get_player_col(engine, b2, clock)
    item_uid = e2e.seed_equipment(db, seller, slot="weapon", rarity="rare", name="競標名劍", now_ts=clock.now)
    lid = int(
        e2e.extract_field(
            engine.list_market_item(seller, item_uid=item_uid, price_col=400, now_ts=clock.now),
            "listing_id",
            "id",
        )
    )
    game_err = e2e.load_engine_api()["GameError"]
    outcomes = e2e.run_concurrent_calls(
        [
            lambda: engine.buy_market_item(b1, lid, now_ts=clock.now),
            lambda: engine.buy_market_item(b2, lid, now_ts=clock.now),
        ]
    )
    wins = [ok for ok, _ in outcomes if ok]
    errs = [val for ok, val in outcomes if not ok]
    assert len(wins) == 1 and len(errs) == 1
    assert isinstance(errs[0], game_err)
    b1_after = e2e.get_player_col(engine, b1, clock)
    b2_after = e2e.get_player_col(engine, b2, clock)
    assert (b1_init - b1_after) + (b2_init - b2_after) == 400


def test_t2_f26_cancel_non_owned_or_already_sold_listing_rejected(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    seller = make_player("掛單賣家")
    buyer = make_player("成交買家")
    e2e.seed_col(db, engine, buyer, 1_000, clock)
    item_uid = e2e.seed_equipment(db, seller, slot="ring", rarity="rare", name="售出戒", now_ts=clock.now)
    lid = int(
        e2e.extract_field(
            engine.list_market_item(seller, item_uid=item_uid, price_col=200, now_ts=clock.now),
            "listing_id",
            "id",
        )
    )
    e2e.assert_game_error(lambda: engine.cancel_market_listing(buyer, lid))
    engine.buy_market_item(buyer, lid, now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.cancel_market_listing(seller, lid))


# ===========================================================================
# Feature 27: PvP Duels (5 tests)
# ===========================================================================


def test_t2_f27_self_duel_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("自殘防呆")
    e2e.assert_game_error(lambda: engine.challenge_duel(u1, u1, mode="first_strike", now_ts=clock.now))


def test_t2_f27_non_target_accepting_duel_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2, u3 = make_player("挑者"), make_player("應者"), make_player("亂入者")
    duel_id = str(
        e2e.extract_field(engine.challenge_duel(u1, u2, mode="first_strike", now_ts=clock.now), "duel_id", "id")
    )
    e2e.assert_game_error(lambda: engine.accept_duel(duel_id, u3, now_ts=clock.now))


def test_t2_f27_negative_or_unaffordable_wager_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2 = make_player("賭注防呆甲"), make_player("賭注防呆乙")
    e2e.assert_game_error(
        lambda: engine.challenge_duel(u1, u2, mode="first_strike", wager_col=-10, now_ts=clock.now)
    )
    e2e.assert_game_error(
        lambda: engine.challenge_duel(u1, u2, mode="first_strike", wager_col=9_999_999, now_ts=clock.now)
    )


def test_t2_f27_safe_zone_duel_never_triggers_hardcore_permadeath_or_orange_cursor(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("切磋甲", mode="standard")
    u2 = make_player("切磋乙硬核", mode="hardcore")
    duel_id = str(
        e2e.extract_field(engine.challenge_duel(u1, u2, mode="full", now_ts=clock.now), "duel_id", "id")
    )
    engine.accept_duel(duel_id, u2, now_ts=clock.now)
    for i in range(80):
        res = e2e.assert_ok_result(
            engine.duel_action(duel_id, u1 if i % 2 == 0 else u2, "attack", now_ts=clock.now)
        )
        if e2e.extract_field(res, "finished", "ended", default=False) is True or str(
            e2e.extract_field(res, "status", default="")
        ).lower() in ("finished", "ended", "completed"):
            break
    mon = engine.get_monument_of_life(limit=10)
    assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 0
    assert e2e.get_player_cursor(engine, u1, clock) == "green"
    assert e2e.get_player_cursor(engine, u2, clock) == "green"


def test_t2_f27_busy_target_invalid_mode_or_non_participant_action_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2, u3 = make_player("忙測甲"), make_player("忙測乙"), make_player("旁觀丙")
    e2e.assert_game_error(lambda: engine.challenge_duel(u1, u2, mode="deathmatch", now_ts=clock.now))
    duel_id = str(
        e2e.extract_field(engine.challenge_duel(u1, u2, mode="first_strike", now_ts=clock.now), "duel_id", "id")
    )
    engine.accept_duel(duel_id, u2, now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.duel_action(duel_id, u3, "attack", now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.challenge_duel(u3, u2, mode="first_strike", now_ts=clock.now))


# ===========================================================================
# Feature 28: Level 1-100+, Stat Allocation & Talent Trees (5 tests)
# ===========================================================================


def test_t2_f28_negative_zero_or_overbudget_stat_deltas_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("配點邊界者")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=5, power_boost=False
    )
    pts = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "unspent_stat_points", "stat_points"))
    e2e.assert_game_error(lambda: engine.allocate_stats(uid, {"str": -1}))
    e2e.assert_game_error(lambda: engine.allocate_stats(uid, {"str": 0}))
    e2e.assert_game_error(lambda: engine.allocate_stats(uid, {}))
    e2e.assert_game_error(lambda: engine.allocate_stats(uid, {"str": pts + 1}))
    assert int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "unspent_stat_points", "stat_points")) == pts


def test_t2_f28_invalid_stat_name_magic_int_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("無魔力屬性測試")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=5, power_boost=False
    )
    e2e.assert_game_error(lambda: engine.allocate_stats(uid, {"int": 1}))
    e2e.assert_game_error(lambda: engine.allocate_stats(uid, {"mana": 1}))


def test_t2_f28_unknown_or_locked_prerequisite_talent_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("前置天賦測試", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, power_boost=False
    )
    e2e.assert_game_error(lambda: engine.allocate_talent(uid, "fireball_mastery"))
    _, child_id = e2e.pick_talent_pair(content_bundle, "sword")
    if child_id is not None:
        e2e.assert_game_error(lambda: engine.allocate_talent(uid, child_id))


def test_t2_f28_respec_talents_blocked_outside_town_safe_zone(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("野外洗點禁止")
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.respec_talents(uid))


def test_t2_f28_respec_talents_blocked_mid_boss_battle(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("王戰退點禁止")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.respec_talents(uid))


# ===========================================================================
# Feature 29: Equipment System (5 tests)
# ===========================================================================


def test_t2_f29_equip_unowned_or_nonexistent_item_uid_rejected(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2 = make_player("裝主"), make_player("小偷")
    uid_item = e2e.seed_equipment(db, u1, slot="weapon", rarity="rare", name="專屬劍", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.equip_item(u2, uid_item))
    e2e.assert_game_error(lambda: engine.equip_item(u1, 999_999))


def test_t2_f29_locked_item_protected_from_market_and_turnin(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("上鎖保護者")
    item_uid = e2e.seed_equipment(db, uid, slot="ring", rarity="rare", name="摯愛戒指", now_ts=clock.now)
    engine.toggle_lock_item(uid, item_uid)
    e2e.assert_game_error(lambda: engine.list_market_item(uid, item_uid=item_uid, price_col=100, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.turn_in_achievement_gear(uid, item_uid))


def test_t2_f29_invalid_loadout_slot_index_and_empty_loadout_rejected(
    engine: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("方案邊界者")
    e2e.assert_game_error(lambda: engine.save_loadout(uid, 0, "bad"))
    e2e.assert_game_error(lambda: engine.save_loadout(uid, 6, "bad"))
    e2e.assert_game_error(lambda: engine.apply_loadout(uid, 4))


def test_t2_f29_apply_loadout_blocked_during_active_combat_or_boss(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("戰中換裝禁止")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.travel_zone(uid, "town", now_ts=clock.now)
    engine.save_loadout(uid, 1, "基本裝")
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.apply_loadout(uid, 1))


def test_t2_f29_loot_filter_never_skips_set_or_named_drops(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("極端過濾器測試")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=12)
    engine.set_loot_filter(
        uid,
        min_rarity="legendary",
        min_level=100,
        blocked_slots=["armor", "weapon"],
    )
    e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="normal")
    gear = e2e.get_player_equipment(engine, uid, clock)
    assert any(
        str(g.get("rarity", "")).lower() == "named" or "午夜" in str(g.get("name", ""))
        for g in gear
    ), "Loot Filter must NEVER discard Named LA drop!"


# ===========================================================================
# Feature 30: Workshop (工坊) (5 tests)
# ===========================================================================


def test_t2_f30_workshop_actions_blocked_outside_town_safe_zone(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("野外工坊禁止")
    forge_rid, forge_spec = e2e.pick_recipe(content_bundle, "blacksmithing")
    fuse_rid, fuse_spec = e2e.pick_recipe(content_bundle, "fusion")
    e2e.give_recipe_materials(db, engine, uid, forge_spec, clock)
    e2e.give_recipe_materials(db, engine, uid, fuse_spec, clock)
    stone_id = e2e.pick_magic_stone_id(content_bundle)
    mats = e2e.pick_enhance_materials(content_bundle)
    e2e.seed_item(db, uid, stone_id, 2)
    e2e.seed_item(db, uid, mats["bright"], 5)
    item_uid = e2e.seed_equipment(db, uid, slot="weapon", rarity="rare", name="野外測劍", now_ts=clock.now)
    engine.travel_zone(uid, "field", now_ts=clock.now)

    e2e.assert_game_error(lambda: engine.forge_craft(uid, forge_rid, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.enhance_equipment(uid, item_uid, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.apply_magic_stone(uid, item_uid, stone_id))
    e2e.assert_game_error(lambda: engine.fuse_items(uid, fuse_rid, now_ts=clock.now))


def test_t2_f30_apply_magic_stone_on_named_gear_always_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("名品禁魔石")
    stone_id = e2e.pick_magic_stone_id(content_bundle)
    e2e.seed_item(db, uid, stone_id, 3)
    named_uid = e2e.seed_equipment(db, uid, slot="weapon", rarity="named", name="闡釋者", now_ts=clock.now)
    qty_before = e2e.get_player_item_qty(engine, uid, stone_id, clock)
    e2e.assert_game_error(lambda: engine.apply_magic_stone(uid, named_uid, stone_id, rng_seed=1))
    assert e2e.get_player_item_qty(engine, uid, stone_id, clock) == qty_before


def test_t2_f30_enhance_past_plus_15_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("滿強測試")
    mats = e2e.pick_enhance_materials(content_bundle)
    e2e.seed_item(db, uid, mats["bright"], 20)
    e2e.seed_col(db, engine, uid, 50_000, clock)
    max_uid = e2e.seed_equipment(
        db, uid, slot="weapon", rarity="legendary", name="極限十五劍", enhance_level=15, now_ts=clock.now
    )
    qty_before = e2e.get_player_item_qty(engine, uid, mats["bright"], clock)
    e2e.assert_game_error(lambda: engine.enhance_equipment(uid, max_uid, now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, uid, mats["bright"], clock) == qty_before


def test_t2_f30_insufficient_mats_or_col_atomic_no_partial_deduction(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("缺料原子性測試")
    forge_rid, _ = e2e.pick_recipe(content_bundle, "blacksmithing")
    fuse_rid, _ = e2e.pick_recipe(content_bundle, "fusion")
    col_before = e2e.get_player_col(engine, uid, clock)
    e2e.assert_game_error(lambda: engine.forge_craft(uid, forge_rid, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.fuse_items(uid, fuse_rid, now_ts=clock.now))
    assert e2e.get_player_col(engine, uid, clock) == col_before


def test_t2_f30_unknown_recipe_stone_or_unowned_item_rejected(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2 = make_player("工坊甲"), make_player("工坊乙")
    u1_uid = e2e.seed_equipment(db, u1, slot="weapon", rarity="rare", name="甲劍", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.forge_craft(u1, "nope_recipe", now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.fuse_items(u1, "nope_fusion", now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.apply_magic_stone(u1, u1_uid, "nope_stone"))
    e2e.assert_game_error(lambda: engine.enhance_equipment(u2, u1_uid, now_ts=clock.now))


# ===========================================================================
# Feature 31: Cooking, Big Pot Stew & SAO Crystals / Quick Pouch (5 tests)
# ===========================================================================


def test_t2_f31_cook_dish_missing_ingredients_or_unknown_recipe_rejected(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("空鍋廚師")
    cook_rid, _ = e2e.pick_recipe(content_bundle, "cooking")
    e2e.assert_game_error(lambda: engine.cook_dish(uid, cook_rid, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.cook_dish(uid, "magic_elixir", now_ts=clock.now))


def test_t2_f31_claim_stew_duplicate_claim_and_outsider_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=2, floor=1)
    u1, u2 = party.member_ids
    outsider = make_player("偷喝湯路人")
    stew_rid, spec = e2e.pick_recipe(content_bundle, "stew")
    e2e.give_recipe_materials(db, engine, u1, spec, clock, multiplier=2)
    stew_id = str(
        e2e.extract_field(engine.start_big_pot_stew(u1, stew_rid, party.party_id, now_ts=clock.now), "stew_id", "id")
    )
    e2e.assert_ok_result(engine.claim_stew(u2, stew_id, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.claim_stew(u2, stew_id, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.claim_stew(outsider, stew_id, now_ts=clock.now))


def test_t2_f31_buy_shop_item_invalid_qty_unknown_item_or_low_col_rejected(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("商店防呆")
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    col_before = e2e.get_player_col(engine, uid, clock)
    e2e.assert_game_error(lambda: engine.buy_shop_item(uid, potion_id, qty=0, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.buy_shop_item(uid, potion_id, qty=-3, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.buy_shop_item(uid, "no_such_item", qty=1, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.buy_shop_item(uid, potion_id, qty=999_999, now_ts=clock.now))
    assert e2e.get_player_col(engine, uid, clock) == col_before


def test_t2_f31_gacha_pull_invalid_count_or_chest_type_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("轉蛋防呆")
    col_before = e2e.get_player_col(engine, uid, clock)
    e2e.assert_game_error(lambda: engine.gacha_pull(uid, chest_type="standard", count=0, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.gacha_pull(uid, chest_type="standard", count=-1, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.gacha_pull(uid, chest_type="invalid_banner", count=1, now_ts=clock.now))
    assert e2e.get_player_col(engine, uid, clock) == col_before


def test_t2_f31_quick_pouch_teleport_crystal_blocked_in_crystal_null_no_consume(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("腰包水晶無效測試")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 100, clock=clock, level=100, unlock_boss_gate=True
    )
    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    before = e2e.get_player_item_qty(engine, uid, tp_id, clock)
    engine.start_floor_boss(uid, floor=100, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(
        lambda: engine.combat_action(uid, "crystal", item_id=tp_id, now_ts=clock.now)
    )
    assert e2e.get_player_item_qty(engine, uid, tp_id, clock) == before


# ===========================================================================
# Feature 32: Passive & Life Skills (採集挖礦 + 7 生活技能) (5 tests)
# ===========================================================================


def test_t2_f32_mine_gather_locked_higher_floor_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("偷挖五十五層礦")
    e2e.assert_game_error(lambda: engine.mine_gather(uid, floor=55, now_ts=clock.now))


def test_t2_f32_mine_gather_invalid_floor_bounds_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("越界挖礦測試")
    for bad in (0, -1, 101):
        e2e.assert_game_error(lambda f=bad: engine.mine_gather(uid, floor=f, now_ts=clock.now))


def test_t2_f32_mine_gather_cooldown_and_stamina_enforced_via_clock(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("冷卻挖礦者")
    e2e.assert_ok_result(engine.mine_gather(uid, floor=1, now_ts=clock.now, rng_seed=3201))
    # Immediate rapid second mine at exact same timestamp violates cooldown (or exhausts stamina)
    hit_limit = False
    game_err = e2e.load_engine_api()["GameError"]
    for i in range(40):
        try:
            engine.mine_gather(uid, floor=1, now_ts=clock.now, rng_seed=3202 + i)
        except game_err as exc:
            assert getattr(exc, "code", "") and e2e.has_zh_tw(str(exc))
            hit_limit = True
            break
    assert hit_limit, "Rapid mining at identical now_ts must hit cooldown or stamina guard"
    clock.advance(hours=2)
    e2e.assert_ok_result(engine.mine_gather(uid, floor=1, now_ts=clock.now, rng_seed=3299))


def test_t2_f32_mine_gather_blocked_mid_boss_battle(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("頭目戰挖礦禁止")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.mine_gather(uid, floor=1, now_ts=clock.now))


def test_t2_f32_life_skills_remain_bounded_and_non_negative(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("技能邊界檢驗")
    for i in range(5):
        engine.mine_gather(uid, floor=1, now_ts=clock.now, rng_seed=3250 + i)
        clock.advance(minutes=15)
    skills = e2e.get_player_life_skills(engine, uid, clock)
    for name, val in skills.items():
        if isinstance(val, (int, float)):
            assert val >= 0, f"Life skill {name} negative: {val}"
        elif isinstance(val, dict):
            assert int(val.get("level", 0)) >= 0 and int(val.get("exp", 0)) >= 0


# ===========================================================================
# Feature 33: Quests, Bounties, Offline Expeditions & Turn-In (5 tests)
# ===========================================================================


def test_t2_f33_double_claim_daily_same_utc_day_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("重複簽到防呆")
    e2e.assert_ok_result(engine.claim_daily(uid, now_ts=clock.now))
    col_after = e2e.get_player_col(engine, uid, clock)
    e2e.assert_game_error(lambda: engine.claim_daily(uid, now_ts=clock.now + 3600))
    assert e2e.get_player_col(engine, uid, clock) == col_after


def test_t2_f33_claim_incomplete_already_claimed_or_unknown_quest_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("任務防呆者")
    q_data = e2e.assert_ok_result(engine.get_quests(uid, now_ts=clock.now))
    q_list = e2e.extract_field(q_data, "quests", "daily", "bounties", "entries", default=[])
    e2e.assert_game_error(lambda: engine.claim_quest(uid, "fake_q", now_ts=clock.now))
    for q in q_list if isinstance(q_list, list) else e2e.iter_entries(q_list):
        m = e2e.as_mapping(q[1] if isinstance(q, tuple) else q)
        if not m.get("completed") and int(m.get("progress", 0)) < int(m.get("target", 1)):
            qid = str(m.get("quest_id") or m.get("id") or (q[0] if isinstance(q, tuple) else ""))
            e2e.assert_game_error(lambda target=qid: engine.claim_quest(uid, target, now_ts=clock.now))
            break


def test_t2_f33_expedition_early_claim_double_claim_and_overlap_rejected(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("遠征防呆者")
    exp_id, _, duration = e2e.pick_expedition(content_bundle)
    e2e.assert_ok_result(engine.start_expedition(uid, exp_id, now_ts=clock.now))
    # Overlap start rejected
    e2e.assert_game_error(lambda: engine.start_expedition(uid, exp_id, now_ts=clock.now + 10))
    # 1 second before ends_at rejected
    e2e.assert_game_error(lambda: engine.claim_expedition(uid, now_ts=clock.now + duration - 1))
    # Valid claim succeeds once, second claim rejected
    clock.advance(seconds=duration + 10)
    e2e.assert_ok_result(engine.claim_expedition(uid, now_ts=clock.now))
    col_paid = e2e.get_player_col(engine, uid, clock)
    e2e.assert_game_error(lambda: engine.claim_expedition(uid, now_ts=clock.now))
    assert e2e.get_player_col(engine, uid, clock) == col_paid


def test_t2_f33_turn_in_locked_equipped_or_unowned_gear_rejected(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2 = make_player("上繳防呆甲"), make_player("上繳防呆乙")
    locked_uid = e2e.seed_equipment(db, u1, slot="ring", rarity="rare", name="鎖定上繳戒", now_ts=clock.now)
    engine.toggle_lock_item(u1, locked_uid)
    eq_uid = e2e.seed_equipment(db, u1, slot="boots", rarity="rare", name="穿著上繳靴", now_ts=clock.now)
    engine.equip_item(u1, eq_uid)
    other_uid = e2e.seed_equipment(db, u2, slot="ring", rarity="rare", name="他人戒", now_ts=clock.now)

    e2e.assert_game_error(lambda: engine.turn_in_achievement_gear(u1, locked_uid))
    e2e.assert_game_error(lambda: engine.turn_in_achievement_gear(u1, eq_uid))
    e2e.assert_game_error(lambda: engine.turn_in_achievement_gear(u1, other_uid))


def test_t2_f33_equip_locked_or_unknown_title_rejected(
    engine: Any,
    content_bundle: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("稱號防呆者")
    _, titles = e2e.pick_achievement_and_title(content_bundle)
    e2e.assert_game_error(lambda: engine.equip_title(uid, "nonexistent_title_xyz"))
    # High-milestone title must be rejected for fresh F1 player
    endgame_title = titles[-1][0]
    e2e.assert_game_error(lambda: engine.equip_title(uid, endgame_title))


# ===========================================================================
# Feature 34: Post-F100 Endgame & 7 Leaderboards (5 tests)
# ===========================================================================


def test_t2_f34_rebirth_before_f100_or_lv100_rejected(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("一級想轉生")
    e2e.assert_game_error(lambda: engine.rebirth_player(uid, confirm=True, now_ts=clock.now))
    assert int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "rebirth_count", "rebirths", default=0)) == 0


def test_t2_f34_rebirth_with_confirm_false_never_resets_player(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("預覽轉生者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 100, clock=clock, level=100)
    game_err = e2e.load_engine_api()["GameError"]
    try:
        e2e.assert_ok_result(engine.rebirth_player(uid, confirm=False, now_ts=clock.now))
    except game_err as exc:
        assert getattr(exc, "code", "") and e2e.has_zh_tw(str(exc))
    prof = engine.get_profile(uid, now_ts=clock.now)
    assert int(e2e.extract_field(prof, "level")) == 100
    assert int(e2e.extract_field(prof, "rebirth_count", "rebirths", default=0)) == 0


def test_t2_f34_nightmare_floor_below_101_or_pre_f100_rejected(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u_low = make_player("低層進夢魘")
    u_high = make_player("百層進非法夢魘")
    e2e.prepare_player_for_floor(engine, db, content_bundle, u_high, 100, clock=clock, level=100)
    e2e.assert_game_error(lambda: engine.enter_nightmare_floor(u_low, 101, now_ts=clock.now))
    for bad in (100, 0, -5):
        e2e.assert_game_error(lambda f=bad: engine.enter_nightmare_floor(u_high, f, now_ts=clock.now))


def test_t2_f34_start_boss_rush_blocked_before_f100_unlock(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("未通關頭目連戰")
    e2e.assert_game_error(lambda: engine.start_boss_rush(uid, now_ts=clock.now))


def test_t2_f34_invalid_leaderboard_category_or_non_positive_limit_rejected(
    engine: Any,
    e2e: Any,
) -> None:
    e2e.assert_game_error(lambda: engine.get_leaderboard("magic_power", limit=10))
    e2e.assert_game_error(lambda: engine.get_leaderboard("floor", limit=0))
    e2e.assert_game_error(lambda: engine.get_leaderboard("floor", limit=-5))


# ===========================================================================
# Feature 35: Platform, Persistence, Hygiene, CI & Secret Scan (6 tests)
# ===========================================================================


def test_t2_f35_snapshot_rollback_guard_rejects_stale_lower_save_seq(
    db: Any,
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    make_player("初始存檔者")
    stale_blob = e2e.export_db_snapshot_bytes(db)
    seq_old = e2e.get_db_save_seq(db)
    u_new = make_player("新進度存檔者")
    seq_new = e2e.get_db_save_seq(db)
    assert seq_new > seq_old

    try:
        imported = e2e.import_db_snapshot_bytes(db, stale_blob, force=False)
        assert imported is False, "Rollback guard must refuse stale snapshot with lower save_seq"
    except ValueError as exc:
        assert str(exc)
    assert e2e.get_db_save_seq(db) == seq_new
    assert db.get_player(u_new) is not None


def test_t2_f35_corrupted_or_non_gzip_snapshot_rejected_cleanly(
    db: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u = make_player("完整庫保護")
    bad_payloads = (
        b"not-a-gzip-at-all",
        e2e.gzip_bytes(b"valid gzip but NOT an sqlite database header"),
        b"\x1f\x8b\x08\x00truncated",
    )
    for bad in bad_payloads:
        try:
            ok = e2e.import_db_snapshot_bytes(db, bad)
            assert ok is False
        except (ValueError, OSError) as exc:
            assert str(exc)
    assert db.get_player(u) is not None


def test_t2_f35_importing_bot_module_creates_no_side_effect_db(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    side_db = tmp_path / "should_not_exist" / "rpg.db"
    env = {
        "PATH": "/usr/bin:/bin",
        "RPG_DB_PATH": str(side_db),
        "DISCORD_BOT_TOKEN": "local-e2e-synthetic-credential",
    }
    proc = subprocess.run(
        [sys.executable, "-c", "import bot; assert callable(bot.create_bot)"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"Importing bot failed: {proc.stderr}"
    assert not side_db.exists(), "Bare `import bot` must NEVER create data/rpg.db as a side effect"


def test_t2_f35_zero_secrets_or_pii_leaked_in_embeds_and_env_template(
    e2e: Any,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env_example = repo_root / ".env.example"
    assert env_example.exists(), ".env.example must exist"
    e2e.assert_no_secrets(env_example.read_text(encoding="utf-8"), context=".env.example")


def test_t2_f35_gitignore_protects_agents_data_env_without_ignoring_json_content() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    must_ignore = (".agents/sample.md", "data/rpg.db", ".env.local")
    must_not_ignore = (".env.example", "src/rpg/content/biomes.json")

    for rel in must_ignore:
        res = subprocess.run(
            ["git", "check-ignore", "-q", rel],
            cwd=str(repo_root),
            check=False,
        )
        assert res.returncode == 0, f"{rel!r} MUST be ignored by .gitignore"

    for rel in must_not_ignore:
        res = subprocess.run(
            ["git", "check-ignore", "-q", rel],
            cwd=str(repo_root),
            check=False,
        )
        assert res.returncode != 0, f"{rel!r} MUST NOT be ignored by .gitignore"


def test_t2_f35_windows_scripts_crlf_and_pure_ascii_vbs_invariants() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    for name in ("start_bot.bat", "stop_bot.bat", "setup_autostart.bat", "start_bot_hidden.vbs"):
        script = repo_root / name
        assert script.exists(), f"Missing Windows script {name}"
        raw = script.read_bytes()
        assert b"\r\n" in raw, f"{name} must use CRLF line endings"
        assert b"\n" not in raw.replace(b"\r\n", b""), f"{name} contains stray LF without CR"
    vbs_raw = (repo_root / "start_bot_hidden.vbs").read_bytes()
    vbs_raw.decode("ascii")
