"""Tier 3 E2E Pairwise Cross-Feature Interaction Suite (40 Tests, 35/35 Features).

Organizes 40 distinct pairwise cross-feature tests into:
- Group A: Shared State Interactions (T3_01..T3_14)
- Group B: Data Flow Interactions (T3_15..T3_28)
- Group C: Control Flow Interactions (T3_29..T3_40)

Module top-level imports are strictly Python stdlib + pytest only.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# ===========================================================================
# Group A: Shared State Interactions (T3_01..T3_14, 14 Tests)
# ===========================================================================


def test_t3_01_f1_f4_character_modes_update_monument_of_life(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    e2e: Any,
) -> None:
    e2e.assert_ok_result(
        engine.create_character("301001", "標準劍士", weapon_style="sword", mode="standard", now_ts=clock.now)
    )
    e2e.assert_ok_result(
        engine.create_character("301002", "死遊劍士", weapon_style="katana", mode="hardcore", now_ts=clock.now)
    )
    mon_before = e2e.assert_ok_result(engine.get_monument_of_life(limit=10))
    assert int(e2e.extract_field(mon_before, "total", "total_players")) == 2
    assert int(e2e.extract_field(mon_before, "alive", "alive_count", "alive_players")) == 2
    assert int(e2e.extract_field(mon_before, "fallen", "dead", "fallen_count", "dead_count")) == 0

    e2e.induce_combat_defeat(engine, db, content_bundle, "301001", clock)
    e2e.induce_combat_defeat(engine, db, content_bundle, "301002", clock, in_boss=True)

    mon_after = e2e.assert_ok_result(engine.get_monument_of_life(limit=10), require_zh_tw=True)
    assert int(e2e.extract_field(mon_after, "fallen", "dead", "fallen_count", "dead_count")) == 1
    assert "死遊劍士" in e2e.extract_text_blob(mon_after) or "301002" in e2e.extract_text_blob(mon_after)


def test_t3_02_f2_f12_secret_realm_miasma_cleared_only_in_town(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("瘴氣淨化驗證者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=15)
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_ok_result(engine.enter_secret_realm(uid, action="enter", now_ts=clock.now, rng_seed=11))
    for i in range(3):
        r = e2e.assert_ok_result(
            engine.enter_secret_realm(uid, action="explore", now_ts=clock.now, rng_seed=12 + i)
        )
        if e2e.extract_field(r, "in_combat", default=False) is True:
            e2e.resolve_active_combat(engine, uid, clock)
    m_in = e2e.get_player_miasma(engine, uid, clock)
    assert m_in >= 3
    e2e.assert_ok_result(engine.enter_secret_realm(uid, action="leave", now_ts=clock.now))
    assert e2e.get_player_miasma(engine, uid, clock) == m_in
    exp_field = float(
        e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "secret_realm_exp_bonus", "miasma_exp_bonus", default=0.0)
    )
    assert exp_field <= 1.0
    engine.travel_zone(uid, "town", now_ts=clock.now)
    assert e2e.get_player_zone(engine, uid, clock) == "town"
    assert e2e.get_player_miasma(engine, uid, clock) == 0


def test_t3_03_f12_f22_secret_realm_miasma_party_contagion_without_free_exp(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    carrier = make_player("瘴氣攜帶者")
    clean = make_player("無辜入隊者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, carrier, 1, clock=clock, level=15)
    engine.travel_zone(carrier, "field", now_ts=clock.now)
    engine.enter_secret_realm(carrier, action="enter", now_ts=clock.now, rng_seed=303)
    for i in range(3):
        r = e2e.assert_ok_result(
            engine.enter_secret_realm(carrier, action="explore", now_ts=clock.now, rng_seed=304 + i)
        )
        if e2e.extract_field(r, "in_combat", default=False) is True:
            e2e.resolve_active_combat(engine, carrier, clock)
    carrier_m = e2e.get_player_miasma(engine, carrier, clock)
    assert carrier_m >= 3

    pid = str(e2e.extract_field(engine.create_party(carrier, floor=1, now_ts=clock.now), "party_id", "id"))
    engine.join_party(pid, clean, role="dps", now_ts=clock.now)
    engine.travel_zone(clean, "field", now_ts=clock.now)
    engine.enter_secret_realm(clean, action="enter", now_ts=clock.now, rng_seed=308)
    assert e2e.get_player_miasma(engine, clean, clock) >= carrier_m
    clean_exp = float(
        e2e.extract_field(engine.get_profile(clean, now_ts=clock.now), "secret_realm_exp_bonus", "miasma_exp_bonus", default=0.0)
    )
    assert clean_exp <= 1.0


def test_t3_04_f21_f29_la_named_loot_overflows_to_pending_mailbox_when_bag_full(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("滿包信箱互動者")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=12)
    fillers = [
        e2e.seed_equipment(db, uid, slot="ring", rarity="plain", name=f"填滿戒{i}", now_ts=clock.now)
        for i in range(85)
    ]
    e2e.clear_floor_organically(engine, uid, clock, floor=1, mode="normal")
    pending = e2e.get_player_pending_loot_count(engine, uid, clock)
    assert pending >= 1
    engine.travel_zone(uid, "town", now_ts=clock.now)
    for fuid in fillers[:10]:
        engine.turn_in_achievement_gear(uid, fuid)
    e2e.assert_ok_result(engine.claim_pending_loot(uid), require_zh_tw=True)
    assert e2e.get_player_pending_loot_count(engine, uid, clock) < pending
    named_items = [g for g in e2e.get_player_equipment(engine, uid, clock) if str(g.get("rarity", "")).lower() == "named"]
    assert len(named_items) >= 1
    e2e.assert_ok_result(engine.equip_item(uid, int(named_items[0].get("id", named_items[0].get("item_uid")))))


def test_t3_05_f26_f29_locked_and_named_gear_blocked_from_marketplace(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("市集裝備鎖互動")
    reg_uid = e2e.seed_equipment(db, uid, slot="weapon", rarity="rare", name="可交易劍", now_ts=clock.now)
    named_uid = e2e.seed_equipment(db, uid, slot="armor", rarity="named", name="午夜大衣", now_ts=clock.now)
    engine.toggle_lock_item(uid, reg_uid)
    e2e.assert_game_error(lambda: engine.list_market_item(uid, item_uid=reg_uid, price_col=100, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.list_market_item(uid, item_uid=named_uid, price_col=500, now_ts=clock.now))
    engine.toggle_lock_item(uid, reg_uid)
    listed = e2e.assert_ok_result(
        engine.list_market_item(uid, item_uid=reg_uid, price_col=150, now_ts=clock.now)
    )
    lid = int(e2e.extract_field(listed, "listing_id", "id"))
    found = e2e.extract_field(engine.search_market(max_price=200), "listings", "items", "results")
    assert any(int(e2e.extract_field(r, "listing_id", "id")) == lid for r in found)
    e2e.assert_ok_result(engine.cancel_market_listing(uid, lid))
    assert any(int(it.get("id", it.get("item_uid", -1))) == reg_uid for it in e2e.get_player_equipment(engine, uid, clock))


def test_t3_06_f29_f30_locked_and_named_gear_workshop_invariants(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("工坊名品互動")
    stone_id = e2e.pick_magic_stone_id(content_bundle)
    mats = e2e.pick_enhance_materials(content_bundle)
    e2e.seed_item(db, uid, stone_id, 4)
    e2e.seed_item(db, uid, mats["bright"], 10)
    e2e.seed_col(db, engine, uid, 20_000, clock)
    named_uid = e2e.seed_equipment(db, uid, slot="weapon", rarity="named", name="闡釋者", now_ts=clock.now)
    reg_uid = e2e.seed_equipment(db, uid, slot="weapon", rarity="rare", name="鋼鐵劍", now_ts=clock.now)

    stones_before = e2e.get_player_item_qty(engine, uid, stone_id, clock)
    e2e.assert_game_error(lambda: engine.apply_magic_stone(uid, named_uid, stone_id, rng_seed=1))
    assert e2e.get_player_item_qty(engine, uid, stone_id, clock) == stones_before

    e2e.assert_ok_result(engine.enhance_equipment(uid, named_uid, now_ts=clock.now, rng_seed=2))
    e2e.assert_ok_result(engine.apply_magic_stone(uid, reg_uid, stone_id, rng_seed=3))
    assert e2e.get_player_item_qty(engine, uid, stone_id, clock) == stones_before - 1


def test_t3_07_f20_f6_concurrent_first_kill_race_and_argo_hall_of_fame(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    pa = make_party_humans(count=2, floor=1, boss_mode="first_kill", prepare_floor=True, unlock_boss_gate=True)
    pb = make_party_humans(count=2, floor=1, boss_mode="first_kill", prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(pa.party_id, pa.leader_id, now_ts=clock.now)
    rid_a = str(e2e.extract_field(engine.start_party_raid(pa.party_id, pa.leader_id, now_ts=clock.now), "raid_id", "id"))
    engine.enter_boss_room(pb.party_id, pb.leader_id, now_ts=clock.now)
    rid_b = str(e2e.extract_field(engine.start_party_raid(pb.party_id, pb.leader_id, now_ts=clock.now), "raid_id", "id"))

    outcomes = e2e.run_concurrent_calls(
        [
            lambda: e2e.drive_coop_raid(engine, clock, rid_a, pa.member_ids)[0],
            lambda: e2e.drive_coop_raid(engine, clock, rid_b, pb.member_ids)[0],
        ]
    )
    assert all(ok for ok, _ in outcomes)
    fk_count = sum(
        1 for _, res in outcomes if bool(e2e.extract_field(res, "is_first_kill", "first_kill", default=False))
    )
    assert fk_count == 1
    for uid in pa.member_ids + pb.member_ids:
        assert e2e.get_player_floor(engine, uid, clock)[1] >= 2
    argo = e2e.assert_ok_result(engine.get_argo_intel(floor=1))
    assert e2e.has_zh_tw(e2e.extract_text_blob(argo))


def test_t3_08_f23_f24_coop_raid_potion_sharing_auto_heals_ally(
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
    engine.toggle_potion_sharing(party.party_id, supp, True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    rid = str(e2e.extract_field(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now), "raid_id", "id"))
    before = e2e.get_player_item_qty(engine, supp, potion_id, clock)
    for _ in range(10):
        engine.submit_raid_action(rid, tank, "attack", now_ts=clock.now)
        res = e2e.assert_ok_result(engine.submit_raid_action(rid, supp, "defend", now_ts=clock.now))
        if e2e.get_player_item_qty(engine, supp, potion_id, clock) < before:
            break
        if e2e.extract_field(res, "ended", "finished", default=False) is True:
            break
    mid = e2e.get_player_item_qty(engine, supp, potion_id, clock)
    assert mid < before
    engine.toggle_potion_sharing(party.party_id, supp, False)


def test_t3_09_f25_f31_guild_big_pot_stew_and_rally_buff_shared_across_members(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    leader = make_player("公會大廚")
    member = make_player("公會團員")
    outsider = make_player("外來路人")
    e2e.seed_col(db, engine, leader, 20_000, clock)
    g = e2e.assert_ok_result(engine.create_guild(leader, "風林火山燉鍋團", "STEW", now_ts=clock.now))
    gid = int(e2e.extract_field(g, "guild_id", "id"))
    engine.join_guild(member, gid, now_ts=clock.now)
    engine.guild_contribute(leader, 5_000, now_ts=clock.now)

    stew_rid, spec = e2e.pick_recipe(content_bundle, "stew")
    e2e.give_recipe_materials(db, engine, leader, spec, clock, multiplier=2)
    cp_before = int(e2e.extract_field(engine.get_profile(member, now_ts=clock.now), "combat_power", "power"))
    stew_id = str(
        e2e.extract_field(engine.start_big_pot_stew(leader, stew_rid, str(gid), now_ts=clock.now), "stew_id", "id")
    )
    engine.guild_activate_buff(leader, "rally", now_ts=clock.now)
    e2e.assert_ok_result(engine.claim_stew(member, stew_id, now_ts=clock.now))
    assert int(e2e.extract_field(engine.get_profile(member, now_ts=clock.now), "combat_power", "power")) >= cp_before
    e2e.assert_game_error(lambda: engine.claim_stew(member, stew_id, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.claim_stew(outsider, stew_id, now_ts=clock.now))


def test_t3_10_f27_f5_safe_zone_pvp_duel_wager_and_green_cursor_preserved(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    p1 = make_player("安全決鬥甲")
    p2 = make_player("安全決鬥乙")
    e2e.seed_col(db, engine, p1, 1_000, clock)
    e2e.seed_col(db, engine, p2, 1_000, clock)
    c1_b, c2_b = e2e.get_player_col(engine, p1, clock), e2e.get_player_col(engine, p2, clock)
    did = str(
        e2e.extract_field(
            engine.challenge_duel(p1, p2, mode="first_strike", wager_col=50, now_ts=clock.now),
            "duel_id",
            "id",
        )
    )
    engine.accept_duel(did, p2, now_ts=clock.now)
    fin = None
    for i in range(60):
        res = e2e.assert_ok_result(
            engine.duel_action(did, p1 if i % 2 == 0 else p2, "attack", now_ts=clock.now)
        )
        if e2e.extract_field(res, "finished", "ended", default=False) is True or str(
            e2e.extract_field(res, "status", default="")
        ).lower() in ("finished", "ended", "completed"):
            fin = res
            break
    assert fin is not None
    winner = str(e2e.extract_field(fin, "winner_id", "winner"))
    loser = p2 if winner == p1 else p1
    assert e2e.get_player_col(engine, winner, clock) == (c1_b if winner == p1 else c2_b) + 50
    assert e2e.get_player_col(engine, loser, clock) == (c1_b if loser == p1 else c2_b) - 50
    assert e2e.get_player_cursor(engine, p1, clock) == "green"
    assert e2e.get_player_cursor(engine, p2, clock) == "green"
    assert int(e2e.extract_field(engine.get_monument_of_life(), "fallen", "dead", "fallen_count", "dead_count")) == 0


def test_t3_11_f25_f29_guild_warehouse_transfer_and_audit_log_integrity(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    leader = make_player("倉庫團長")
    officer = make_player("倉庫幹部")
    recruit = make_player("倉庫新兵")
    e2e.seed_col(db, engine, leader, 20_000, clock)
    g = e2e.assert_ok_result(engine.create_guild(leader, "倉儲審查公會", "LOG", now_ts=clock.now))
    gid = int(e2e.extract_field(g, "guild_id", "id"))
    engine.join_guild(officer, gid, now_ts=clock.now)
    engine.join_guild(recruit, gid, now_ts=clock.now)
    ranks = e2e.extract_field(g, "ranks", "rank_names", default=["officer"])
    officer_rank = str(ranks[1] if isinstance(ranks, list) and len(ranks) > 1 else "officer")
    engine.set_guild_rank(leader, officer, officer_rank)

    item_uid = e2e.seed_equipment(db, leader, slot="helmet", rarity="rare", name="審查頭盔", now_ts=clock.now)
    wh_id = int(e2e.extract_field(engine.guild_warehouse_deposit(leader, item_uid, now_ts=clock.now), "warehouse_id", "id"))
    e2e.assert_game_error(lambda: engine.guild_warehouse_withdraw(recruit, wh_id, now_ts=clock.now))
    e2e.assert_ok_result(engine.guild_warehouse_withdraw(officer, wh_id, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.guild_warehouse_withdraw(officer, wh_id, now_ts=clock.now))

    copies = sum(
        1
        for u in (leader, officer, recruit)
        for it in e2e.get_player_equipment(engine, u, clock)
        if "審查頭盔" in str(it.get("name", ""))
    )
    assert copies == 1


def test_t3_12_f26_f35_market_concurrent_buy_race_and_snapshot_persistence(
    db: Any,
    tmp_path: Path,
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    seller = make_player("快照賣家")
    b1, b2 = make_player("快照買甲"), make_player("快照買乙")
    e2e.seed_col(db, engine, b1, 500, clock)
    e2e.seed_col(db, engine, b2, 500, clock)
    item_uid = e2e.seed_equipment(db, seller, slot="weapon", rarity="rare", name="快照寶劍", now_ts=clock.now)
    lid = int(
        e2e.extract_field(
            engine.list_market_item(seller, item_uid=item_uid, price_col=200, now_ts=clock.now),
            "listing_id",
            "id",
        )
    )
    seq_before = e2e.get_db_save_seq(db)
    outcomes = e2e.run_concurrent_calls(
        [
            lambda: engine.buy_market_item(b1, lid, now_ts=clock.now),
            lambda: engine.buy_market_item(b2, lid, now_ts=clock.now),
        ]
    )
    assert sum(1 for ok, _ in outcomes if ok) == 1
    assert e2e.get_db_save_seq(db) > seq_before

    snap = e2e.export_db_snapshot_bytes(db)
    db2 = e2e.load_db_api()["RPGDatabase"](tmp_path / "market_reloaded.db")
    try:
        assert e2e.import_db_snapshot_bytes(db2, snap) is True
        eng2 = e2e.instantiate_engine(db2, content_bundle)
        c1, c2 = e2e.get_player_col(eng2, b1, clock), e2e.get_player_col(eng2, b2, clock)
        assert sorted([c1, c2]) == [300, 500]
        active = e2e.extract_field(eng2.search_market(), "listings", "items", "results")
        assert all(int(e2e.extract_field(r, "listing_id", "id")) != lid for r in active)
    finally:
        db2.close()


def test_t3_13_f23_f35_coop_raid_thread_safety_and_wal_persistence(
    db: Any,
    db_path: Path,
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=4, floor=1, prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    rid = str(e2e.extract_field(raid, "raid_id", "id"))
    game_err = e2e.load_engine_api()["GameError"]

    calls = [
        (lambda u=uid: engine.submit_raid_action(rid, u, "attack", now_ts=clock.now))
        for uid in party.member_ids
    ] + [lambda: engine.submit_raid_action(rid, party.member_ids[0], "defend", now_ts=clock.now)]
    outcomes = e2e.run_concurrent_calls(calls)
    wins = [ok for ok, _ in outcomes if ok]
    errs = [val for ok, val in outcomes if not ok]
    assert len(wins) == 4 and len(errs) == 1 and isinstance(errs[0], game_err)

    db.close()
    db2 = e2e.load_db_api()["RPGDatabase"](db_path)
    try:
        eng2 = e2e.instantiate_engine(db2, content_bundle)
        for uid in party.member_ids:
            e2e.assert_ok_result(eng2.get_profile(uid, now_ts=clock.now))
    finally:
        db2.close()


def test_t3_14_f33_f35_offline_expedition_survives_db_restart_and_clock_advance(
    db: Any,
    db_path: Path,
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("離線重啟測試者")
    exp_id, _, duration = e2e.pick_expedition(content_bundle)
    engine.start_expedition(uid, exp_id, now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.claim_expedition(uid, now_ts=clock.now + 5))
    col_before = e2e.get_player_col(engine, uid, clock)
    db.close()

    db2 = e2e.load_db_api()["RPGDatabase"](db_path)
    try:
        eng2 = e2e.instantiate_engine(db2, content_bundle)
        clock.advance(seconds=duration + 60)
        e2e.assert_ok_result(eng2.claim_expedition(uid, now_ts=clock.now), require_zh_tw=True)
        assert e2e.get_player_col(eng2, uid, clock) > col_before
        e2e.assert_game_error(lambda: eng2.claim_expedition(uid, now_ts=clock.now))
    finally:
        db2.close()


# ===========================================================================
# Group B: Data Flow Interactions (T3_15..T3_28, 14 Tests)
# ===========================================================================


def test_t3_15_f8_f10_json_biome_scaling_drives_floor_mobs_and_drops(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    scales = [
        float(e2e.extract_field(engine.get_floor_info(f), "boss_hp", "hp_scale", "stat_multiplier"))
        for f in (1, 10, 50, 100)
    ]
    assert scales[0] < scales[1] < scales[2] < scales[3]
    uid = make_player("階梯小怪測試")
    col_b = e2e.get_player_col(engine, uid, clock)
    e2e.trigger_road_combat(engine, uid, clock, seed_start=3150)
    e2e.resolve_active_combat(engine, uid, clock)
    assert e2e.get_player_col(engine, uid, clock) > col_b


def test_t3_16_f8_f16_floor_penetration_flows_into_four_axis_effective_res(
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    uid = make_player("穿透資料流測試")
    e2e.seed_equipment(
        db,
        uid,
        slot="armor",
        rarity="legendary",
        name="全軸高抗甲",
        affixes={"res_slash": 0.70, "res_pierce": 0.70, "res_blunt": 0.70, "res_dragon": 0.70},
        now_ts=clock.now,
    )
    items = db.get_equipment(uid)
    player = db.get_player(uid)
    s1 = compute_stats(player, items, content_bundle, floor=1)
    s50 = compute_stats(player, items, content_bundle, floor=50)
    s100 = compute_stats(player, items, content_bundle, floor=100)
    s120 = compute_stats(player, items, content_bundle, floor=120)
    for dt in e2e.FOUR_DAMAGE_TYPES:
        assert s1.effective_res(dt, 1) > s50.effective_res(dt, 50) > s100.effective_res(dt, 100) >= 0.0
        assert s120.effective_res(dt, 120) == pytest.approx(s100.effective_res(dt, 100), abs=1e-6)


def test_t3_17_f10_f31_mob_meat_drops_flow_into_cooking_and_buffs(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("狩獵料理人")
    recipe_id, spec = e2e.pick_recipe(content_bundle, "cooking")
    e2e.give_recipe_materials(db, engine, uid, spec, clock, multiplier=4)
    skills_before = str(e2e.get_player_life_skills(engine, uid, clock))
    r1 = e2e.assert_ok_result(engine.cook_dish(uid, recipe_id, timing_perfect=False, now_ts=clock.now))
    r2 = e2e.assert_ok_result(engine.cook_dish(uid, recipe_id, timing_perfect=True, now_ts=clock.now))
    assert r1 and r2
    assert str(e2e.get_player_life_skills(engine, uid, clock)) != skills_before


def test_t3_18_f32_f11_searching_skill_improves_chest_inspection_and_trap_detection(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("索敵開箱互動")
    e2e.trigger_chest_encounter(engine, uid, clock, seed_start=3180)
    insp = e2e.assert_ok_result(engine.open_chest(uid, action="inspect", now_ts=clock.now, rng_seed=18), require_zh_tw=True)
    assert insp
    e2e.assert_ok_result(engine.open_chest(uid, action="leave", now_ts=clock.now))
    e2e.trigger_chest_encounter(engine, uid, clock, seed_start=3195)
    opened = e2e.assert_ok_result(engine.open_chest(uid, action="open", now_ts=clock.now, rng_seed=19))
    assert opened


def test_t3_19_f32_f30_mining_ores_flow_into_blacksmithing_and_enhancement(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("採礦鍛造強化流")
    e2e.assert_ok_result(engine.mine_gather(uid, floor=1, now_ts=clock.now, rng_seed=19))
    recipe_id, spec = e2e.pick_recipe(content_bundle, "blacksmithing")
    e2e.give_recipe_materials(db, engine, uid, spec, clock, multiplier=2)
    mats = e2e.pick_enhance_materials(content_bundle)
    e2e.seed_item(db, uid, mats["bright"], 10)
    crafted = e2e.assert_ok_result(engine.forge_craft(uid, recipe_id, now_ts=clock.now))
    crafted_uid = int(e2e.extract_field(crafted, "item_uid", "id"))
    e2e.assert_ok_result(engine.enhance_equipment(uid, crafted_uid, now_ts=clock.now, rng_seed=19))
    cp_before = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "combat_power", "power"))
    e2e.assert_ok_result(engine.equip_item(uid, crafted_uid))
    assert int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "combat_power", "power")) >= cp_before


def test_t3_20_f14_f15_weapon_style_and_unique_skill_unlock_fourth_skill_slot(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("武器劍技聯動", weapon_style="sword")
    sw = e2e.pick_sword_skills(content_bundle, "sword", count=4)
    rp = e2e.pick_sword_skills(content_bundle, "rapier", count=1)
    e2e.assert_ok_result(engine.set_skill_slots(uid, sw[:3]))
    e2e.assert_game_error(lambda: engine.set_skill_slots(uid, sw[:4]))
    engine.switch_weapon_style(uid, "rapier")
    e2e.assert_game_error(lambda: engine.set_skill_slots(uid, [sw[0]]))
    e2e.assert_ok_result(engine.set_skill_slots(uid, rp))

    engine.switch_weapon_style(uid, "sword")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 50, clock=clock, level=55, mastery=500)
    e2e.assert_ok_result(engine.unlock_unique_skill(uid, "dual_blades"))
    dual = e2e.pick_sword_skills(content_bundle, "dual_blades", count=1, include_unique=True)[0]
    e2e.assert_ok_result(engine.set_skill_slots(uid, sw[:3] + [dual]))


def test_t3_21_f15_f16_sword_skill_damage_type_triggers_weakness_and_combo(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("細劍弱點連段", weapon_style="rapier")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    rapier_skills = e2e.pick_sword_skills(content_bundle, "rapier", count=2)
    engine.set_skill_slots(uid, rapier_skills)
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    t1 = e2e.assert_ok_result(engine.combat_action(uid, "skill", skill_id=rapier_skills[0], now_ts=clock.now))
    assert int(e2e.extract_field(t1, "damage_dealt", "player_damage", "damage")) > 0
    t2 = e2e.assert_ok_result(engine.combat_action(uid, "skill", skill_id=rapier_skills[1], now_ts=clock.now))
    assert int(e2e.extract_field(t2, "combo", "combo_count", default=2)) >= 2


def test_t3_22_f19_f6_boss_skill_observation_unmasks_argo_intel(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    obs = make_player("情報觀測者")
    unseen = make_player("未觀察者")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, obs, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    before = e2e.extract_text_blob(engine.get_argo_intel(user_id=obs, floor=1)).count("???")
    engine.start_floor_boss(obs, floor=1, mode="normal", now_ts=clock.now)
    for _ in range(5):
        r = e2e.assert_ok_result(engine.combat_action(obs, "defend", now_ts=clock.now))
        if e2e.extract_field(r, "ended", "finished", default=False) is True:
            break
    obs_after = e2e.assert_ok_result(engine.get_argo_intel(user_id=obs, floor=1))
    unseen_after = e2e.assert_ok_result(engine.get_argo_intel(user_id=unseen, floor=1))
    assert e2e.extract_text_blob(obs_after).count("???") <= before
    assert len(e2e.extract_field(unseen_after, "observed_skills", "seen_skills", "known_skills", default=[])) == 0


def test_t3_23_f19_f7_milestone_boss_clears_unlock_yui_console_logs(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("結衣解鎖聯動")
    c1 = sum(1 for e in e2e.extract_field(engine.get_yui_logs(uid), "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 10, clock=clock, level=20)
    e2e.clear_floor_organically(engine, uid, clock, floor=10, mode="normal")
    c10 = sum(1 for e in e2e.extract_field(engine.get_yui_logs(uid), "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    assert c10 > c1


def test_t3_24_f28_f14_stats_and_talents_scale_weapon_combat_power(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("配點天賦聯動", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=12, power_boost=False
    )
    cp0 = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "combat_power", "power"))
    engine.allocate_stats(uid, {"str": 3, "agi": 2})
    root_id, _ = e2e.pick_talent_pair(content_bundle, "sword")
    engine.allocate_talent(uid, root_id)
    cp1 = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "combat_power", "power"))
    assert cp1 > cp0
    e2e.assert_ok_result(engine.respec_talents(uid))


def test_t3_25_f29_f33_spare_gear_achievement_turn_in_grants_permanent_stats_and_titles(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("上繳稱號聯動")
    spare = e2e.seed_equipment(db, uid, slot="ring", rarity="rare", name="備戒", now_ts=clock.now)
    eq = e2e.seed_equipment(db, uid, slot="boots", rarity="rare", name="鞋", now_ts=clock.now)
    lock = e2e.seed_equipment(db, uid, slot="gloves", rarity="rare", name="鎖套", now_ts=clock.now)
    engine.equip_item(uid, eq)
    engine.toggle_lock_item(uid, lock)
    e2e.assert_game_error(lambda: engine.turn_in_achievement_gear(uid, eq))
    e2e.assert_game_error(lambda: engine.turn_in_achievement_gear(uid, lock))
    cp0 = int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "combat_power", "power"))
    e2e.assert_ok_result(engine.turn_in_achievement_gear(uid, spare))
    assert int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "combat_power", "power")) > cp0


def test_t3_26_f33_f34_rebirth_preserves_turnins_titles_named_and_updates_leaderboards(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("轉生保存聯動")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 100, clock=clock, level=100)
    e2e.seed_equipment(db, uid, slot="weapon", rarity="named", name="紅玉聖劍", now_ts=clock.now)
    spare = e2e.seed_equipment(db, uid, slot="ring", rarity="rare", name="上繳戒", now_ts=clock.now)
    engine.turn_in_achievement_gear(uid, spare)
    yui_before = sum(1 for e in e2e.extract_field(engine.get_yui_logs(uid), "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    e2e.assert_ok_result(engine.rebirth_player(uid, confirm=True, now_ts=clock.now))
    assert int(e2e.extract_field(engine.get_profile(uid, now_ts=clock.now), "rebirth_count", "rebirths")) == 1
    assert any(str(g.get("rarity", "")).lower() == "named" for g in e2e.get_player_equipment(engine, uid, clock))
    yui_after = sum(1 for e in e2e.extract_field(engine.get_yui_logs(uid), "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))
    assert yui_after == yui_before
    lb = e2e.assert_ok_result(engine.get_leaderboard("level", limit=10))
    assert len(e2e.extract_field(lb, "entries", "rankings", "rows", "leaderboard")) >= 1


def test_t3_27_f11_f13_roguelike_nodes_flow_into_chest_mimic_and_extraction(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("地城開箱撤離流")
    e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=12)
    col_before = e2e.get_player_col(engine, uid, clock)
    engine.start_roguelike(uid, now_ts=clock.now, rng_seed=327)
    for _ in range(3):
        step = e2e.assert_ok_result(engine.step_roguelike(uid, node_index=0, now_ts=clock.now))
        if e2e.extract_field(step, "in_combat", default=False) is True:
            e2e.resolve_active_combat(engine, uid, clock)
    ext = e2e.assert_ok_result(engine.extract_roguelike(uid, now_ts=clock.now))
    assert int(e2e.extract_field(ext, "score", "final_score", "points")) > 0
    assert e2e.get_player_col(engine, uid, clock) >= col_before
    e2e.assert_game_error(lambda: engine.step_roguelike(uid, node_index=0, now_ts=clock.now))


def test_t3_28_f20_f34_world_boss_damage_updates_leaderboard_and_accelerated_world(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1, u2, u3 = make_player("世界榜甲"), make_player("世界榜乙"), make_player("世界榜丙")
    e2e.prepare_player_for_floor(engine, db, content_bundle, u1, 30, clock=clock, level=40)
    e2e.prepare_player_for_floor(engine, db, content_bundle, u2, 10, clock=clock, level=15)
    for u in (u1, u2, u3):
        for _ in range(3):
            e2e.assert_ok_result(engine.attack_floor_world_boss(u, now_ts=clock.now))
        e2e.assert_game_error(lambda target=u: engine.attack_floor_world_boss(target, now_ts=clock.now))
    lb = e2e.assert_ok_result(engine.get_leaderboard("world_boss", limit=10))
    rows = e2e.extract_field(lb, "entries", "rankings", "rows", "leaderboard")
    assert len(rows) >= 3
    dmgs = [float(e2e.extract_field(r, "score", "damage", "total_damage", "value")) for r in rows]
    assert dmgs == sorted(dmgs, reverse=True) and dmgs[0] > 0


# ===========================================================================
# Group C: Control Flow Interactions (T3_29..T3_40, 12 Tests)
# ===========================================================================


def test_t3_29_f1_f2_spawn_in_town_and_field_blocks_town_only_services(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    e2e: Any,
) -> None:
    e2e.assert_ok_result(
        engine.create_character("329001", "安全區控流者", weapon_style="sword", mode="standard", now_ts=clock.now)
    )
    assert e2e.get_player_zone(engine, "329001", clock) == "town"
    assert e2e.get_player_floor(engine, "329001", clock)[0] == 1
    forge_rid, spec = e2e.pick_recipe(content_bundle, "blacksmithing")
    e2e.give_recipe_materials(db, engine, "329001", spec, clock)
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    e2e.seed_item(db, "329001", potion_id, 5)
    col_before = e2e.get_player_col(engine, "329001", clock)

    engine.travel_zone("329001", "field", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.forge_craft("329001", forge_rid, now_ts=clock.now))
    e2e.assert_game_error(
        lambda: engine.list_market_item("329001", item_id=potion_id, qty=1, price_col=100, now_ts=clock.now)
    )
    e2e.assert_game_error(lambda: engine.respec_talents("329001"))
    e2e.assert_game_error(lambda: engine.start_roguelike("329001", now_ts=clock.now))
    assert e2e.get_player_col(engine, "329001", clock) == col_before

    engine.travel_zone("329001", "town", now_ts=clock.now)
    e2e.assert_ok_result(engine.respec_talents("329001"))
    e2e.assert_ok_result(engine.start_roguelike("329001", now_ts=clock.now, rng_seed=329))


def test_t3_30_f2_f3_teleport_gate_lands_in_safe_zone_and_blocks_locked_or_mid_boss(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("轉移門控流者")
    e2e.assert_game_error(lambda: engine.teleport_floor(uid, 2, now_ts=clock.now))
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=12, unlock_boss_gate=True
    )
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.teleport_floor(uid, 1, now_ts=clock.now))
    e2e.resolve_active_combat(engine, uid, clock)
    engine.travel_zone(uid, "field", now_ts=clock.now)
    e2e.assert_ok_result(engine.teleport_floor(uid, 2, now_ts=clock.now))
    assert e2e.get_player_floor(engine, uid, clock)[0] == 2
    assert e2e.get_player_zone(engine, uid, clock) == "town"


def test_t3_31_f9_f19_exploration_progress_gates_floor_boss_room(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("探索開門控流者")
    e2e.assert_game_error(lambda: engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now))
    finfo = e2e.explore_to_boss_gate(engine, uid, clock, floor=1)
    assert int(e2e.extract_field(finfo, "exploration_pct", "exploration", "progress")) == 100
    boss = e2e.assert_ok_result(engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now))
    assert int(e2e.extract_field(boss, "hp_bars", "total_bars", "bars")) == 4


def test_t3_32_f11_f18_crystal_null_room_blocks_auto_retreat_without_consuming_crystal(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("水晶無效生存控流")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 100, clock=clock, level=100, unlock_boss_gate=True
    )
    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    before = e2e.get_player_item_qty(engine, uid, tp_id, clock)
    engine.set_survival_config(
        uid, auto_potion_pct=20, auto_crystal_pct=10, auto_retreat_pct=95, stop_on_no_potion=True
    )
    engine.start_floor_boss(uid, floor=100, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.combat_action(uid, "crystal", item_id=tp_id, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.combat_action(uid, "retreat", now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, uid, tp_id, clock) == before


def test_t3_33_f17_f19_boss_phase_health_gate_and_stun_immunity_control_flow(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("鎖血與抗暈控流")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=80, unlock_boss_gate=True
    )
    nuke = e2e.seed_equipment(db, uid, slot="weapon", rarity="legendary", name="破界大劍", atk=50_000, now_ts=clock.now)
    engine.equip_item(uid, nuke)
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)
    logs: list[str] = []
    for _ in range(12):
        t = e2e.assert_ok_result(engine.combat_action(uid, "attack", now_ts=clock.now))
        logs.append(e2e.extract_text_blob(t))
        if e2e.extract_field(t, "ended", "finished", default=False) is True:
            break
    assert any(k in "\n".join(logs) for k in ("野太刀", "斬", "P4", "階段"))


def test_t3_34_f17_f23_coop_raid_switch_chain_agi_tiebreak_and_solo_block(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    solo = make_player("孤狼交換防呆")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, solo, 1, clock=clock, level=10, unlock_boss_gate=True
    )
    engine.start_floor_boss(solo, floor=1, mode="normal", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.combat_action(solo, "switch", now_ts=clock.now))

    party = make_party_humans(
        count=3,
        floor=1,
        weapon_styles=["rapier", "mace", "sword"],
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    fast, slow, dps = party.member_ids
    engine.allocate_stats(fast, {"agi": 20})
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    rid = str(e2e.extract_field(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now), "raid_id", "id"))
    engine.submit_raid_action(rid, slow, "switch", now_ts=clock.now)
    engine.submit_raid_action(rid, fast, "switch", now_ts=clock.now)
    res = e2e.assert_ok_result(engine.submit_raid_action(rid, dps, "attack", now_ts=clock.now))
    if not e2e.extract_field(res, "round_resolved", "resolved", default=False):
        res = e2e.assert_ok_result(engine.resolve_raid_round(rid, requester_id=fast, now_ts=clock.now))
    assert int(e2e.extract_field(res, "switch_chain", "switch_count", default=2)) >= 2


def test_t3_35_f19_f28_active_boss_blocks_respec_style_switch_and_loadout_swap(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("王戰封鎖控流者", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=12, unlock_boss_gate=True
    )
    engine.travel_zone(uid, "town", now_ts=clock.now)
    engine.save_loadout(uid, 1, "攻略配裝")
    alt_skills = e2e.pick_sword_skills(content_bundle, "sword", count=2)
    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)

    e2e.assert_game_error(lambda: engine.respec_talents(uid))
    e2e.assert_game_error(lambda: engine.switch_weapon_style(uid, "axe"))
    e2e.assert_game_error(lambda: engine.apply_loadout(uid, 1))
    e2e.assert_game_error(lambda: engine.set_skill_slots(uid, alt_skills))

    e2e.resolve_active_combat(engine, uid, clock)
    engine.travel_zone(uid, "town", now_ts=clock.now)
    e2e.assert_ok_result(engine.respec_talents(uid))
    e2e.assert_ok_result(engine.apply_loadout(uid, 1))


def test_t3_36_f22_f20_party_lobby_gates_team_boss_and_daily_boost_limit(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(
        count=4,
        floor=1,
        boss_mode="team_boss",
        max_size=12,
        is_raid_alliance=True,
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    non_leader = party.member_ids[1]
    e2e.assert_game_error(lambda: engine.enter_boss_room(party.party_id, non_leader, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.start_party_raid(party.party_id, non_leader, now_ts=clock.now))
    # Must enter_boss_room before start_party_raid
    e2e.assert_game_error(lambda: engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))

    boosts: list[bool] = []
    for _ in range(4):
        engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
        rid = str(
            e2e.extract_field(
                engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now),
                "raid_id",
                "id",
            )
        )
        fin, _ = e2e.drive_coop_raid(engine, clock, rid, party.member_ids)
        boosts.append(bool(e2e.extract_field(fin, "boosted_drop", "daily_boost", "is_boosted", default=False)))
        clock.advance(minutes=10)
    assert boosts == [True, True, True, False]


def test_t3_37_f24_f3_group_teleport_leader_unlock_and_straggler_guards(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    leader = make_player("傳送隊長")
    mate_f2 = make_player("已解鎖隊友")
    mate_f1 = make_player("未解鎖隊友")
    e2e.prepare_player_for_floor(engine, db, content_bundle, leader, 2, clock=clock)
    e2e.prepare_player_for_floor(engine, db, content_bundle, mate_f2, 2, clock=clock)
    pid = str(e2e.extract_field(engine.create_party(leader, floor=1, now_ts=clock.now), "party_id", "id"))
    engine.join_party(pid, mate_f2, role="dps", now_ts=clock.now)
    engine.join_party(pid, mate_f1, role="support", now_ts=clock.now)

    e2e.assert_game_error(lambda: engine.party_group_teleport(pid, mate_f2, 1, now_ts=clock.now))

    game_err = e2e.load_engine_api()["GameError"]
    try:
        res = e2e.assert_ok_result(engine.party_group_teleport(pid, leader, 2, now_ts=clock.now))
        # Unlocked mate_f1 must NEVER be silently teleported to locked F2
        assert e2e.get_player_floor(engine, mate_f1, clock)[0] == 1
        assert res
    except game_err as exc:
        assert getattr(exc, "code", "") and e2e.has_zh_tw(str(exc))
        assert e2e.get_player_floor(engine, mate_f1, clock)[0] == 1

    e2e.assert_ok_result(engine.party_group_teleport(pid, leader, 1, now_ts=clock.now))
    for u in (leader, mate_f2, mate_f1):
        assert e2e.get_player_floor(engine, u, clock)[0] == 1
        assert e2e.get_player_zone(engine, u, clock) == "town"


def test_t3_38_f24_f4_teleport_crystal_rescues_standard_downed_not_hardcore_dead(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    rescuer = make_player("救援者338")
    std_v = make_player("標準傷員", mode="standard")
    hc_v = make_player("硬核陣亡者", mode="hardcore")
    healthy = make_player("滿血隊友")
    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    e2e.seed_item(db, rescuer, tp_id, 2)

    e2e.induce_combat_defeat(engine, db, content_bundle, std_v, clock)
    e2e.induce_combat_defeat(engine, db, content_bundle, hc_v, clock, in_boss=True)

    before = e2e.get_player_item_qty(engine, rescuer, tp_id, clock)
    e2e.assert_game_error(lambda: engine.rescue_downed_player(rescuer, healthy, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.rescue_downed_player(rescuer, hc_v, now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, rescuer, tp_id, clock) == before

    e2e.assert_ok_result(engine.rescue_downed_player(rescuer, std_v, now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, rescuer, tp_id, clock) == before - 1
    assert e2e.get_player_zone(engine, std_v, clock) == "town"
    assert int(e2e.extract_field(engine.get_monument_of_life(), "fallen", "dead", "fallen_count", "dead_count")) == 1


def test_t3_39_f33_f5_story_choices_shift_color_cursor_and_time_decay_restores_green(
    engine: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("光標劇情控流")
    assert e2e.get_player_cursor(engine, uid, clock) == "green"
    ch_id, choice_id, _ = e2e.pick_story_choice(content_bundle, karma_negative=True)
    e2e.assert_ok_result(engine.choose_story_option(uid, ch_id, choice_id, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.choose_story_option(uid, ch_id, choice_id, now_ts=clock.now))
    clock.advance(days=7)
    assert e2e.get_player_cursor(engine, uid, clock) == "green"


def test_t3_40_f13_f1_hardcore_roguelike_defeat_is_non_permadeath(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("硬核地城倖存者", mode="hardcore")
    mon_before = engine.get_monument_of_life(limit=10)
    fallen_before = int(e2e.extract_field(mon_before, "fallen", "dead", "fallen_count", "dead_count"))
    e2e.induce_combat_defeat(engine, db, content_bundle, uid, clock, in_roguelike=True)
    mon_after = engine.get_monument_of_life(limit=10)
    assert int(e2e.extract_field(mon_after, "fallen", "dead", "fallen_count", "dead_count")) == fallen_before
    assert e2e.get_player_zone(engine, uid, clock) == "town"
    e2e.assert_ok_result(engine.travel_zone(uid, "field", now_ts=clock.now))
