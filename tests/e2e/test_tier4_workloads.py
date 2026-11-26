"""Tier 4 E2E Real-World Multi-Human SAO Workloads Suite (W01–W20).

20 comprehensive end-to-end multi-human SAO application campaigns spanning:
- W01–W09: F1 Link Start -> F10 Kagachi -> F25 Abyssward -> F27 Crystal-Null Trap ->
  F50 Algade/Elucidator/Dual Blades -> F74 Gleam Eyes/Starburst Stream ->
  F75 Skull Reaper 6-Human Dual-Tank -> F80 Doom + F90 Tri-Shield ->
  F100 Dual-Stage Finale (Radius -> Heathcliff)
- W10: Post-F100 Rebirth, Boss Rush, Nightmare & 7 Leaderboards
- W11–W13: Secret Realm Miasma, Underground Roguelike, Full Workshop/Loadouts/Cooking Economy
- W14–W18: 12-Human Guild Raid Alliance, Marketplace Concurrency Race, World Boss/PvP/Cursor,
  Hardcore Permadeath vs Standard Rescue, Multi-Human Concurrency & First-Kill Race
- W19–W20: SQLite WAL v1->v2 Migration/Snapshot Sync & Full 23-Command Discord UI + /p Smoke

Module top-level imports are strictly Python stdlib + pytest only.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# ===========================================================================
# W01: F1 Link Start to Illfang First-Kill (4 Real Humans)
# ===========================================================================


def test_w01_f1_link_start_to_illfang_first_kill(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    e2e: Any,
) -> None:
    roster = [
        ("401001", "桐人", "sword", "dps"),
        ("401002", "亞絲娜", "rapier", "breaker"),
        ("401003", "艾基爾", "axe", "tank"),
        ("401004", "克萊因", "katana", "support"),
    ]
    for uid, name, style, _ in roster:
        e2e.assert_ok_result(
            engine.create_character(uid, name, weapon_style=style, mode="standard", now_ts=clock.now),
            require_zh_tw=True,
        )
    mon = e2e.assert_ok_result(engine.get_monument_of_life(limit=10))
    assert int(e2e.extract_field(mon, "total", "total_players")) == 4
    assert int(e2e.extract_field(mon, "alive", "alive_count", "alive_players")) == 4
    assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 0

    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    for uid, _, _, _ in roster:
        e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=8)
        e2e.assert_ok_result(engine.buy_shop_item(uid, potion_id, qty=3, now_ts=clock.now))
        e2e.assert_ok_result(engine.set_survival_config(uid, auto_potion_pct=40, stop_on_no_potion=True))
    # Leader organically explores F1 to 100% + inspects/opens chest
    e2e.trigger_chest_encounter(engine, "401001", clock, seed_start=4010)
    e2e.assert_ok_result(engine.open_chest("401001", action="inspect", now_ts=clock.now, rng_seed=4010))
    opened = e2e.assert_ok_result(engine.open_chest("401001", action="open", now_ts=clock.now, rng_seed=4010))
    if e2e.extract_field(opened, "in_combat", "is_mimic", default=False):
        e2e.resolve_active_combat(engine, "401001", clock)
    finfo = e2e.explore_to_boss_gate(engine, "401003", clock, floor=1, seed_base=4020)
    assert int(e2e.extract_field(finfo, "exploration_pct", "exploration", "progress")) == 100

    p_res = e2e.assert_ok_result(
        engine.create_party("401003", floor=1, boss_mode="first_kill", max_size=6, now_ts=clock.now)
    )
    party_id = str(e2e.extract_field(p_res, "party_id", "id"))
    for uid, _, _, role in roster:
        if uid != "401003":
            e2e.assert_ok_result(engine.join_party(party_id, uid, role=role, now_ts=clock.now))
        e2e.assert_ok_result(engine.set_party_role(party_id, uid, role))
        e2e.assert_ok_result(engine.set_party_ready(party_id, uid, True))

    e2e.assert_ok_result(engine.enter_boss_room(party_id, "401003", now_ts=clock.now))
    raid = e2e.assert_ok_result(engine.start_party_raid(party_id, "401003", now_ts=clock.now))
    assert int(e2e.extract_field(raid, "hp_bars", "total_bars", "bars")) == 4
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))

    def _f1_strat(rnd: int, uid: str, _s: dict[str, Any]) -> tuple[str, str | None, str | None, int]:
        if rnd % 3 == 0 and uid in ("401003", "401002"):
            return ("switch", None, None, 0)
        if rnd % 4 == 0 and uid == "401003":
            return ("parry", None, None, 0)
        return ("attack", None, None, 0)

    final_res, history = e2e.drive_coop_raid(
        engine, clock, raid_id, [u for u, _, _, _ in roster], strategy_fn=_f1_strat
    )
    full_log = "\n".join(e2e.extract_text_blob(h) for h in history)
    assert any(k in full_log for k in ("野太刀", "太刀", "斬", "P4", "伊爾方"))
    la_winner = str(e2e.extract_field(final_res, "la_winner", "last_attack_user_id", "la_user_id"))
    assert la_winner in {u for u, _, _, _ in roster}
    assert any(
        str(g.get("rarity", "")).lower() == "named" or "午夜" in str(g.get("name", ""))
        for g in e2e.get_player_equipment(engine, la_winner, clock)
    )
    argo = e2e.assert_ok_result(engine.get_argo_intel(floor=1))
    assert any(name in e2e.extract_text_blob(argo) for _, name, _, _ in roster) or any(
        uid in e2e.extract_text_blob(argo) for uid, _, _, _ in roster
    )
    for uid, _, _, _ in roster:
        e2e.assert_ok_result(engine.teleport_floor(uid, 2, now_ts=clock.now))
        assert e2e.get_player_floor(engine, uid, clock)[0] == 2
        assert e2e.get_player_zone(engine, uid, clock) == "town"


# ===========================================================================
# W02: F10 Kagachi Serpent Break Co-op (4 Real Humans)
# ===========================================================================


def test_w02_f10_kagachi_serpent_break_coop(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(
        count=4,
        floor=10,
        boss_mode="first_kill",
        weapon_styles=["mace", "katana", "sword", "rapier"],
        roles=["tank", "dps", "breaker", "dps"],
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    f10 = e2e.assert_ok_result(engine.get_floor_info(10))
    assert any(k in e2e.extract_text_blob(f10) for k in ("加賀智", "武士"))
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))
    assert int(e2e.extract_field(raid, "hp_bars", "total_bars", "bars")) >= 4

    def _serpent_break(rnd: int, uid: str, _s: dict[str, Any]) -> tuple[str, str | None, str | None, int]:
        if rnd % 2 == 0 and uid in (party.member_ids[0], party.member_ids[2]):
            return ("switch", None, None, 0)
        return ("attack", None, None, 0)

    final_res, _history = e2e.drive_coop_raid(
        engine, clock, raid_id, party.member_ids, strategy_fn=_serpent_break
    )
    la_winner = str(e2e.extract_field(final_res, "la_winner", "last_attack_user_id", "la_user_id"))
    assert la_winner in party.member_ids
    assert any(str(g.get("rarity", "")).lower() == "named" for g in e2e.get_player_equipment(engine, la_winner, clock))
    argo = e2e.assert_ok_result(engine.get_argo_intel(user_id=party.leader_id, floor=10))
    assert e2e.has_zh_tw(e2e.extract_text_blob(argo))
    yui = e2e.assert_ok_result(engine.get_yui_logs(party.leader_id))
    assert sum(1 for e in e2e.extract_field(yui, "logs", "entries") if e2e.as_mapping(e).get("unlocked", True)) >= 2
    e2e.assert_ok_result(engine.teleport_floor(party.leader_id, 11, now_ts=clock.now))


# ===========================================================================
# W03: F25 Twin-Mouthed Callout Raid (4 Real Humans)
# ===========================================================================


def test_w03_f25_twin_mouthed_callout_raid(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(
        count=4,
        floor=25,
        boss_mode="first_kill",
        weapon_styles=["mace", "holy", "rapier", "sword"],
        roles=["tank", "support", "dps", "breaker"],
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    assert int(e2e.extract_field(raid, "hp_bars", "total_bars", "bars")) >= 5
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))

    def _callout_strat(rnd: int, uid: str, state: dict[str, Any]) -> tuple[str, str | None, str | None, int]:
        blob = e2e.extract_text_blob(state)
        if any(k in blob for k in ("宣判", "口", "蓄力", "預警")):
            return ("parry" if uid == party.member_ids[0] else "defend", None, None, 0)
        if rnd % 3 == 0 and uid == party.member_ids[3]:
            return ("switch", None, None, 0)
        return ("attack", None, None, 0)

    final_res, _ = e2e.drive_coop_raid(
        engine, clock, raid_id, party.member_ids, strategy_fn=_callout_strat
    )
    la_winner = str(e2e.extract_field(final_res, "la_winner", "last_attack_user_id", "la_user_id"))
    assert any(str(g.get("rarity", "")).lower() == "named" for g in e2e.get_player_equipment(engine, la_winner, clock))
    yui = e2e.assert_ok_result(engine.get_yui_logs(party.leader_id))
    assert sum(1 for e in e2e.extract_field(yui, "logs", "entries") if e2e.as_mapping(e).get("unlocked", True)) >= 3
    e2e.assert_ok_result(engine.teleport_floor(party.leader_id, 26, now_ts=clock.now))


# ===========================================================================
# W04: F27 Crystal-Null Trap & Rescue (3 Real Humans)
# ===========================================================================


def test_w04_f27_crystal_null_trap_and_rescue(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    scout = make_player("第27層斥候", mode="standard")
    victim = make_player("黑貓受困者", mode="standard")
    rescuer = make_player("及時救援者", mode="standard")
    e2e.prepare_player_for_floor(engine, db, content_bundle, scout, 27, clock=clock, level=35)
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, victim, 27, clock=clock, level=1, power_boost=False, add_crystals=True
    )
    e2e.prepare_player_for_floor(engine, db, content_bundle, rescuer, 27, clock=clock, level=35, add_crystals=True)

    f27 = e2e.assert_ok_result(engine.get_floor_info(27))
    assert any(k in e2e.extract_text_blob(f27) for k in ("水晶", "無效", "陷阱", "27"))

    # Scout inspects & leaves safely with 0 damage
    e2e.trigger_chest_encounter(engine, scout, clock, seed_start=4040)
    hp_scout_before = int(e2e.extract_field(engine.get_profile(scout, now_ts=clock.now), "hp", "current_hp", "max_hp"))
    e2e.assert_ok_result(engine.open_chest(scout, action="inspect", now_ts=clock.now, rng_seed=4040), require_zh_tw=True)
    e2e.assert_ok_result(engine.open_chest(scout, action="leave", now_ts=clock.now))
    assert int(e2e.extract_field(engine.get_profile(scout, now_ts=clock.now), "hp", "current_hp", "max_hp")) == hp_scout_before

    # Victim triggers F27 Crystal-Null combat, Teleport Crystal blocked without loss, then Downed -> Rescued
    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    victim_tp_before = e2e.get_player_item_qty(engine, victim, tp_id, clock)
    rescuer_tp_before = e2e.get_player_item_qty(engine, rescuer, tp_id, clock)

    engine.travel_zone(victim, "labyrinth", now_ts=clock.now)
    in_null_fight = False
    for s in range(4050, 4120):
        res = e2e.assert_ok_result(engine.explore_floor(victim, steps=1, now_ts=clock.now, rng_seed=s))
        ev = str(e2e.extract_field(res, "event_type", "encounter_type", "type", "event", default="")).lower()
        if "chest" in ev or e2e.has_field(res, "chest", "chest_tier"):
            op = e2e.assert_ok_result(engine.open_chest(victim, action="open", now_ts=clock.now, rng_seed=s))
            if e2e.extract_field(op, "crystal_null", "in_combat", "is_trap", default=False):
                in_null_fight = True
                break
        elif e2e.extract_field(res, "in_combat", default=False) is True:
            if e2e.extract_field(res, "crystal_null", default=False) is True:
                in_null_fight = True
                break
            e2e.resolve_active_combat(engine, victim, clock)
    assert in_null_fight
    e2e.assert_game_error(lambda: engine.combat_action(victim, "crystal", item_id=tp_id, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.combat_action(victim, "retreat", now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, victim, tp_id, clock) == victim_tp_before

    # Allow undergeared victim to drop to 0 HP (Downed)
    engine.set_survival_config(victim, auto_potion_pct=0, auto_crystal_pct=0, auto_retreat_pct=0)
    for _ in range(60):
        t = e2e.assert_ok_result(engine.combat_action(victim, "attack", now_ts=clock.now))
        if e2e.extract_field(t, "ended", "finished", "defeat", default=False) is True:
            break
    e2e.assert_ok_result(engine.rescue_downed_player(rescuer, victim, now_ts=clock.now), require_zh_tw=True)
    assert e2e.get_player_item_qty(engine, rescuer, tp_id, clock) == rescuer_tp_before - 1
    assert e2e.get_player_zone(engine, victim, clock) == "town"
    assert int(e2e.extract_field(engine.get_monument_of_life(), "fallen", "dead", "fallen_count", "dead_count")) == 0


# ===========================================================================
# W05: F50 Algade, Elucidator & Dual Blades Unlock (4 Real Humans)
# ===========================================================================


def test_w05_f50_algade_elucidator_and_dual_blades_unlock(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    fresh = make_player("一級想學二刀流")
    e2e.assert_game_error(lambda: engine.unlock_unique_skill(fresh, "dual_blades"))

    party = make_party_humans(
        count=4,
        floor=50,
        boss_mode="first_kill",
        weapon_styles=["sword", "mace", "holy", "rapier"],
        roles=["dps", "tank", "tank", "support"],
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    dps_uid = party.member_ids[0]
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    assert int(e2e.extract_field(raid, "hp_bars", "total_bars", "bars")) >= 5

    def _f50_strat(rnd: int, uid: str, _s: dict[str, Any]) -> tuple[str, str | None, str | None, int]:
        if uid == dps_uid:
            return ("attack", None, None, 0)
        if rnd % 2 == 0 and uid in party.member_ids[1:3]:
            return ("switch", None, None, 0)
        return ("defend", None, None, 0)

    final_res, _ = e2e.drive_coop_raid(
        engine, clock, str(e2e.extract_field(raid, "raid_id", "id")), party.member_ids, strategy_fn=_f50_strat
    )
    la_winner = str(e2e.extract_field(final_res, "la_winner", "last_attack_user_id", "la_user_id"))
    named_gear = [g for g in e2e.get_player_equipment(engine, la_winner, clock) if str(g.get("rarity", "")).lower() == "named"]
    assert len(named_gear) >= 1
    elucidator_uid = int(named_gear[0].get("id", named_gear[0].get("item_uid")))

    # Unlock Dual Blades & equip 4 skill slots
    e2e.prepare_player_for_floor(engine, db, content_bundle, la_winner, 50, clock=clock, level=55, mastery=600)
    e2e.assert_ok_result(engine.unlock_unique_skill(la_winner, "dual_blades"), require_zh_tw=True)
    sw3 = e2e.pick_sword_skills(content_bundle, "sword", count=3)
    db1 = e2e.pick_sword_skills(content_bundle, "dual_blades", count=1, include_unique=True)[0]
    e2e.assert_ok_result(engine.set_skill_slots(la_winner, sw3 + [db1]))
    e2e.assert_game_error(lambda: engine.set_skill_slots(la_winner, sw3 + [db1, sw3[0]]))

    # Town Workshop: enhance Named allowed, Magic Stone on Named blocked
    mats = e2e.pick_enhance_materials(content_bundle)
    stone_id = e2e.pick_magic_stone_id(content_bundle)
    e2e.seed_item(db, la_winner, mats["bright"], 10)
    e2e.seed_item(db, la_winner, stone_id, 2)
    engine.travel_zone(la_winner, "town", now_ts=clock.now)
    e2e.assert_ok_result(engine.enhance_equipment(la_winner, elucidator_uid, now_ts=clock.now, rng_seed=50))
    e2e.assert_game_error(lambda: engine.apply_magic_stone(la_winner, elucidator_uid, stone_id, rng_seed=50))
    yui = e2e.assert_ok_result(engine.get_yui_logs(la_winner))
    assert sum(1 for e in e2e.extract_field(yui, "logs", "entries") if e2e.as_mapping(e).get("unlocked", True)) >= 5


# ===========================================================================
# W06: F74 The Gleam Eyes & Starburst Stream Burst (4 Real Humans)
# ===========================================================================


def test_w06_f74_gleam_eyes_and_starburst_stream_burst(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(
        count=4,
        floor=74,
        boss_mode="first_kill",
        weapon_styles=["sword", "rapier", "mace", "katana"],
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    kirito = party.member_ids[0]
    e2e.prepare_player_for_floor(engine, db, content_bundle, kirito, 74, clock=clock, level=80, mastery=800)
    engine.unlock_unique_skill(kirito, "dual_blades")
    sw3 = e2e.pick_sword_skills(content_bundle, "sword", count=3)
    dual_skills = e2e.pick_sword_skills(content_bundle, "dual_blades", count=1, include_unique=True)
    starburst_id = dual_skills[0]
    engine.set_skill_slots(kirito, sw3 + [starburst_id])

    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    assert int(e2e.extract_field(raid, "hp_bars", "total_bars", "bars")) >= 5
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))

    def _f74_strat(rnd: int, uid: str, _s: dict[str, Any]) -> tuple[str, str | None, str | None, int]:
        if uid == kirito and rnd == 1:
            return ("skill", starburst_id, None, 0)
        if rnd == 1 and uid == party.member_ids[2]:
            return ("switch", None, None, 0)
        return ("attack", None, None, 0)

    final_res, history = e2e.drive_coop_raid(
        engine, clock, raid_id, party.member_ids, strategy_fn=_f74_strat
    )
    assert final_res and len(history) >= 1
    argo = e2e.assert_ok_result(engine.get_argo_intel(user_id=kirito, floor=74))
    assert e2e.has_zh_tw(e2e.extract_text_blob(argo))
    e2e.assert_ok_result(engine.teleport_floor(kirito, 75, now_ts=clock.now))


# ===========================================================================
# W07: F75 The Skull Reaper Dual-Tank Formation (6 Real Humans)
# ===========================================================================


def test_w07_f75_skull_reaper_dual_tank_formation(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(
        count=6,
        floor=75,
        boss_mode="first_kill",
        weapon_styles=["mace", "holy", "dagger", "katana", "rapier", "sword"],
        roles=["tank", "tank", "dps", "dps", "dps", "support"],
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    t1, t2 = party.member_ids[0], party.member_ids[1]
    supp = party.member_ids[5]
    potion_id = e2e.pick_crystal_ids(content_bundle)["potion"]
    e2e.seed_item(db, supp, potion_id, 20)
    e2e.assert_ok_result(engine.toggle_potion_sharing(party.party_id, supp, True))

    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    assert int(e2e.extract_field(raid, "hp_bars", "total_bars", "bars")) >= 6
    raid_id = str(e2e.extract_field(raid, "raid_id", "id"))

    def _dual_tank_strat(rnd: int, uid: str, _s: dict[str, Any]) -> tuple[str, str | None, str | None, int]:
        if rnd == 1 and uid in (t1, t2):
            return ("parry", None, None, 0)
        if uid == t1:
            return ("switch" if rnd % 2 == 0 else "defend", None, None, 0)
        if uid == t2:
            return ("switch" if rnd % 2 == 1 else "defend", None, None, 0)
        return ("attack", None, None, 0)

    final_res, _ = e2e.drive_coop_raid(
        engine, clock, raid_id, party.member_ids, strategy_fn=_dual_tank_strat, max_rounds=100
    )
    la_winner = str(e2e.extract_field(final_res, "la_winner", "last_attack_user_id", "la_user_id"))
    assert any(str(g.get("rarity", "")).lower() == "named" for g in e2e.get_player_equipment(engine, la_winner, clock))
    yui = e2e.assert_ok_result(engine.get_yui_logs(party.leader_id))
    assert sum(1 for e in e2e.extract_field(yui, "logs", "entries") if e2e.as_mapping(e).get("unlocked", True)) >= 6
    e2e.assert_ok_result(engine.teleport_floor(party.leader_id, 76, now_ts=clock.now))


# ===========================================================================
# W08: F80 Doom & F90 Tri-Shield Endgame Mechanics Gauntlet (4 Real Humans)
# ===========================================================================


def test_w08_f80_doom_and_f90_tri_shield_gauntlet(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    heal_crystal = e2e.pick_crystal_ids(content_bundle)["healing"]

    # Part A: F80 Mortis + Red Healing Crystal Doom cleanse
    p80 = make_party_humans(
        count=4,
        floor=80,
        boss_mode="first_kill",
        weapon_styles=["katana", "rapier", "mace", "holy"],
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    engine.enter_boss_room(p80.party_id, p80.leader_id, now_ts=clock.now)
    r80 = e2e.assert_ok_result(engine.start_party_raid(p80.party_id, p80.leader_id, now_ts=clock.now))
    rid80 = str(e2e.extract_field(r80, "raid_id", "id"))

    def _f80_strat(rnd: int, uid: str, state: dict[str, Any]) -> tuple[str, str | None, str | None, int]:
        if rnd == 2 and "死印" in e2e.extract_text_blob(state) and uid == p80.member_ids[0]:
            return ("crystal", None, heal_crystal, 0)
        return ("attack", None, None, 0)

    fin80, _ = e2e.drive_coop_raid(engine, clock, rid80, p80.member_ids, strategy_fn=_f80_strat)
    la80 = str(e2e.extract_field(fin80, "la_winner", "last_attack_user_id", "la_user_id"))
    assert any(str(g.get("rarity", "")).lower() == "named" for g in e2e.get_player_equipment(engine, la80, clock))

    # Part B: F90 Chronos 3-axis shield + floor 90 penetration verification
    p90 = make_party_humans(
        count=4,
        floor=90,
        boss_mode="first_kill",
        weapon_styles=["katana", "rapier", "mace", "holy"],
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    st90 = compute_stats(db.get_player(p90.leader_id), db.get_equipment(p90.leader_id), content_bundle, floor=90)
    assert st90.effective_res("slash", 90) < st90.effective_res("slash", 1)

    engine.enter_boss_room(p90.party_id, p90.leader_id, now_ts=clock.now)
    r90 = e2e.assert_ok_result(engine.start_party_raid(p90.party_id, p90.leader_id, now_ts=clock.now))
    assert int(e2e.extract_field(r90, "hp_bars", "total_bars", "bars")) >= 6
    fin90, _ = e2e.drive_coop_raid(
        engine, clock, str(e2e.extract_field(r90, "raid_id", "id")), p90.member_ids, max_rounds=120
    )
    la90 = str(e2e.extract_field(fin90, "la_winner", "last_attack_user_id", "la_user_id"))
    assert any(str(g.get("rarity", "")).lower() == "named" for g in e2e.get_player_equipment(engine, la90, clock))


# ===========================================================================
# W09: F100 Dual-Stage Finale (Radius -> Heathcliff) (6 Real Humans)
# ===========================================================================


def test_w09_f100_dual_stage_finale_radius_to_heathcliff(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    party = make_party_humans(
        count=6,
        floor=100,
        boss_mode="first_kill",
        weapon_styles=["sword", "rapier", "mace", "holy", "katana", "axe"],
        roles=["dps", "dps", "tank", "tank", "breaker", "support"],
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    st100 = compute_stats(db.get_player(party.leader_id), db.get_equipment(party.leader_id), content_bundle, floor=100)
    assert st100.effective_res("slash", 100) == pytest.approx(st100.effective_res("slash", 120), abs=1e-6)

    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    rid = str(e2e.extract_field(raid, "raid_id", "id"))

    # Crystal-Null no-escape verified in F100 Ruby Palace
    tp_before = e2e.get_player_item_qty(engine, party.leader_id, tp_id, clock)
    e2e.assert_game_error(lambda: engine.submit_raid_action(rid, party.leader_id, "retreat", now_ts=clock.now))
    e2e.assert_game_error(
        lambda: engine.submit_raid_action(rid, party.leader_id, "crystal", item_id=tp_id, now_ts=clock.now)
    )
    assert e2e.get_player_item_qty(engine, party.leader_id, tp_id, clock) == tp_before

    def _f100_strat(rnd: int, uid: str, state: dict[str, Any]) -> tuple[str, str | None, str | None, int]:
        blob = e2e.extract_text_blob(state)
        if "反擊" in blob and uid in party.member_ids[:2]:
            return ("defend", None, None, 0)
        if rnd % 2 == 0 and uid in party.member_ids[2:4]:
            return ("switch", None, None, 0)
        return ("attack", None, None, 0)

    final_res, history = e2e.drive_coop_raid(
        engine, clock, rid, party.member_ids, strategy_fn=_f100_strat, max_rounds=150
    )
    full_blob = "\n".join(e2e.extract_text_blob(h) for h in history)
    assert any(k in full_blob for k in ("希茲克利夫", "神聖劍", "紅玉", "解放", "通關"))
    la_winner = str(e2e.extract_field(final_res, "la_winner", "last_attack_user_id", "la_user_id"))
    assert any(str(g.get("rarity", "")).lower() == "named" for g in e2e.get_player_equipment(engine, la_winner, clock))
    argo = e2e.assert_ok_result(engine.get_argo_intel(floor=100))
    assert e2e.has_zh_tw(e2e.extract_text_blob(argo))
    yui = e2e.assert_ok_result(engine.get_yui_logs(party.leader_id))
    assert sum(1 for e in e2e.extract_field(yui, "logs", "entries") if e2e.as_mapping(e).get("unlocked", True)) >= 7


# ===========================================================================
# W10: Post-F100 Rebirth, Boss Rush, Nightmare & All 7 Leaderboards
# ===========================================================================


def test_w10_post_f100_rebirth_boss_rush_nightmare_and_leaderboards(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    compute_stats = e2e.load_stats_api()["compute_player_stats"]
    u_pre = make_player("新手基準")
    u_rush = make_player("連戰夢魘者")
    u_rebirth = make_player("轉生先驅者")
    u_mid = make_player("中層公會長")

    e2e.assert_game_error(lambda: engine.rebirth_player(u_pre, confirm=True, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.start_boss_rush(u_pre, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.enter_nightmare_floor(u_pre, 101, now_ts=clock.now))

    e2e.prepare_player_for_floor(engine, db, content_bundle, u_rush, 100, clock=clock, level=100)
    e2e.prepare_player_for_floor(engine, db, content_bundle, u_rebirth, 100, clock=clock, level=100)
    e2e.prepare_player_for_floor(engine, db, content_bundle, u_mid, 45, clock=clock, level=50)

    # Boss Rush & Nightmare F101+
    e2e.assert_ok_result(engine.start_boss_rush(u_rush, now_ts=clock.now), require_zh_tw=True)
    e2e.assert_ok_result(engine.combat_action(u_rush, "attack", now_ts=clock.now))
    e2e.assert_ok_result(engine.enter_nightmare_floor(u_rush, 101, now_ts=clock.now), require_zh_tw=True)
    st101 = compute_stats(db.get_player(u_rush), db.get_equipment(u_rush), content_bundle, floor=101)
    assert st101.effective_res("slash", 101) == pytest.approx(st101.effective_res("slash", 100), abs=1e-6)

    # Rebirth preview vs confirm=True preservation
    e2e.seed_equipment(db, u_rebirth, slot="weapon", rarity="named", name="紅玉聖劍", now_ts=clock.now)
    spare = e2e.seed_equipment(db, u_rebirth, slot="ring", rarity="rare", name="傳承戒", now_ts=clock.now)
    engine.turn_in_achievement_gear(u_rebirth, spare)
    yui_before = sum(1 for e in e2e.extract_field(engine.get_yui_logs(u_rebirth), "logs", "entries") if e2e.as_mapping(e).get("unlocked", True))

    game_err = e2e.load_engine_api()["GameError"]
    try:
        engine.rebirth_player(u_rebirth, confirm=False, now_ts=clock.now)
    except game_err as exc:
        assert getattr(exc, "code", "")
    assert int(e2e.extract_field(engine.get_profile(u_rebirth, now_ts=clock.now), "rebirth_count", "rebirths", default=0)) == 0

    e2e.assert_ok_result(engine.rebirth_player(u_rebirth, confirm=True, now_ts=clock.now), require_zh_tw=True)
    assert int(e2e.extract_field(engine.get_profile(u_rebirth, now_ts=clock.now), "rebirth_count", "rebirths")) == 1
    assert any(str(g.get("rarity", "")).lower() == "named" for g in e2e.get_player_equipment(engine, u_rebirth, clock))
    assert sum(1 for e in e2e.extract_field(engine.get_yui_logs(u_rebirth), "logs", "entries") if e2e.as_mapping(e).get("unlocked", True)) == yui_before

    # Populate guild & world boss for all 7 leaderboards
    engine.create_guild(u_mid, "終局公會", "END", now_ts=clock.now)
    engine.guild_contribute(u_mid, 3_000, now_ts=clock.now)
    engine.attack_floor_world_boss(u_rush, now_ts=clock.now)
    for cat in e2e.SEVEN_LEADERBOARD_CATEGORIES:
        lb = e2e.assert_ok_result(engine.get_leaderboard(cat, limit=10), require_zh_tw=True)
        rows = e2e.extract_field(lb, "entries", "rankings", "rows", "leaderboard")
        assert len(rows) >= 1
        scores = [
            float(e2e.extract_field(r, "score", "value", "metric", "floor", "power", "level", "damage", "col", default=0))
            for r in rows
        ]
        assert scores == sorted(scores, reverse=True)


# ===========================================================================
# W11: Secret Realm Miasma & Party Contagion (3 Real Humans)
# ===========================================================================


def test_w11_secret_realm_miasma_and_party_contagion(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    farmer = make_player("秘境農夫")
    clean = make_player("潔淨新隊友")
    partner = make_player("同行夥伴")
    e2e.prepare_player_for_floor(engine, db, content_bundle, farmer, 1, clock=clock, level=20)
    e2e.prepare_player_for_floor(engine, db, content_bundle, partner, 1, clock=clock, level=20)

    engine.travel_zone(farmer, "field", now_ts=clock.now)
    e2e.assert_ok_result(engine.enter_secret_realm(farmer, action="enter", now_ts=clock.now, rng_seed=411))
    prev_m = 0
    for i in range(5):
        r = e2e.assert_ok_result(
            engine.enter_secret_realm(farmer, action="explore", now_ts=clock.now, rng_seed=412 + i)
        )
        if e2e.extract_field(r, "in_combat", default=False) is True:
            e2e.resolve_active_combat(engine, farmer, clock)
        cur_m = e2e.get_player_miasma(engine, farmer, clock)
        assert cur_m > prev_m
        prev_m = cur_m
    assert prev_m >= 5

    # Leaving Secret Realm clears EXP bonus only, keeps Miasma
    e2e.assert_ok_result(engine.enter_secret_realm(farmer, action="leave", now_ts=clock.now))
    assert e2e.get_player_miasma(engine, farmer, clock) == prev_m
    exp_after_leave = float(
        e2e.extract_field(engine.get_profile(farmer, now_ts=clock.now), "secret_realm_exp_bonus", "miasma_exp_bonus", default=0.0)
    )
    assert exp_after_leave <= 1.0

    # Forming party spreads Miasma damage penalty to Clean Joiner without free EXP bonus
    pid = str(e2e.extract_field(engine.create_party(farmer, floor=1, now_ts=clock.now), "party_id", "id"))
    engine.join_party(pid, clean, role="dps", now_ts=clock.now)
    engine.join_party(pid, partner, role="support", now_ts=clock.now)
    engine.travel_zone(clean, "field", now_ts=clock.now)
    engine.enter_secret_realm(clean, action="enter", now_ts=clock.now, rng_seed=419)
    assert e2e.get_player_miasma(engine, clean, clock) >= prev_m
    clean_exp = float(
        e2e.extract_field(engine.get_profile(clean, now_ts=clock.now), "secret_realm_exp_bonus", "miasma_exp_bonus", default=0.0)
    )
    assert clean_exp <= 1.0

    # Returning to Town Safe Zone clears Miasma to 0 for everyone
    engine.enter_secret_realm(clean, action="leave", now_ts=clock.now)
    engine.travel_zone(farmer, "town", now_ts=clock.now)
    engine.travel_zone(clean, "town", now_ts=clock.now)
    assert e2e.get_player_miasma(engine, farmer, clock) == 0
    assert e2e.get_player_miasma(engine, clean, clock) == 0


# ===========================================================================
# W12: Black Iron Palace Underground Roguelike (Standard + Hardcore)
# ===========================================================================


def test_w12_black_iron_palace_underground_roguelike(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    std_runner = make_player("標準地城探索者", mode="standard")
    hc_runner = make_player("硬核地城探索者", mode="hardcore")
    e2e.prepare_player_for_floor(engine, db, content_bundle, std_runner, 1, clock=clock, level=15)

    # Field entry blocked -> Town entry succeeds
    engine.travel_zone(std_runner, "field", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.start_roguelike(std_runner, now_ts=clock.now))
    engine.travel_zone(std_runner, "town", now_ts=clock.now)
    col_before = e2e.get_player_col(engine, std_runner, clock)

    e2e.assert_ok_result(engine.start_roguelike(std_runner, now_ts=clock.now, rng_seed=412), require_zh_tw=True)
    e2e.assert_game_error(lambda: engine.start_roguelike(std_runner, now_ts=clock.now, rng_seed=413))
    e2e.assert_game_error(lambda: engine.step_roguelike(std_runner, node_index=-1, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.step_roguelike(std_runner, node_index=999, now_ts=clock.now))

    for _ in range(4):
        sres = e2e.assert_ok_result(engine.step_roguelike(std_runner, node_index=0, now_ts=clock.now))
        if e2e.extract_field(sres, "in_combat", default=False) is True:
            e2e.resolve_active_combat(engine, std_runner, clock)
        if e2e.extract_field(sres, "ended", "finished", default=False) is True:
            break
    if e2e.get_player_zone(engine, std_runner, clock) == "roguelike":
        ext = e2e.assert_ok_result(engine.extract_roguelike(std_runner, now_ts=clock.now), require_zh_tw=True)
        assert int(e2e.extract_field(ext, "score", "final_score", "points")) > 0
    assert e2e.get_player_col(engine, std_runner, clock) >= col_before
    assert e2e.get_player_zone(engine, std_runner, clock) == "town"

    # Hardcore defeat inside Underground Roguelike settles cleanly with ZERO permadeath
    e2e.induce_combat_defeat(engine, db, content_bundle, hc_runner, clock, in_roguelike=True)
    mon = e2e.assert_ok_result(engine.get_monument_of_life(limit=10))
    assert int(e2e.extract_field(mon, "fallen", "dead", "fallen_count", "dead_count")) == 0
    assert e2e.get_player_zone(engine, hc_runner, clock) == "town"


# ===========================================================================
# W13: Full Workshop, Loadouts, Loot Filter & Cooking Stew Economy
# ===========================================================================


def test_w13_workshop_loadouts_loot_filter_and_cooking_stew(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=3, floor=55, prepare_floor=True)
    crafter, mate1, mate2 = party.member_ids

    # 1. F55 Mining + Blacksmithing
    e2e.assert_ok_result(engine.mine_gather(crafter, floor=55, now_ts=clock.now, rng_seed=55), require_zh_tw=True)
    forge_rid, forge_spec = e2e.pick_recipe(content_bundle, "blacksmithing")
    e2e.give_recipe_materials(db, engine, crafter, forge_spec, clock, multiplier=2)
    crafted = e2e.assert_ok_result(engine.forge_craft(crafter, forge_rid, now_ts=clock.now), require_zh_tw=True)
    crafted_uid = int(e2e.extract_field(crafted, "item_uid", "id"))

    # 2. Enhancement +1..+15 ceiling + Protection Talisman + Magic Stone (blocked on Named) + Fusion
    mats = e2e.pick_enhance_materials(content_bundle)
    stone_id = e2e.pick_magic_stone_id(content_bundle)
    e2e.seed_item(db, crafter, mats["bright"], 300)
    e2e.seed_item(db, crafter, mats["protection"], 50)
    e2e.seed_item(db, crafter, stone_id, 5)
    for iid, spec in e2e.iter_entries(content_bundle.items_crystals):
        if "dark" in iid.lower() or "暗" in str(spec.get("name", "")):
            e2e.seed_item(db, crafter, iid, 300)
    e2e.seed_col(db, engine, crafter, 1_000_000, clock)

    e2e.assert_ok_result(engine.enhance_equipment(crafter, crafted_uid, use_protection=True, now_ts=clock.now, rng_seed=1))
    e2e.assert_ok_result(engine.apply_magic_stone(crafter, crafted_uid, stone_id, rng_seed=2))
    named_uid = e2e.seed_equipment(db, crafter, slot="weapon", rarity="named", name="水晶細劍", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.apply_magic_stone(crafter, named_uid, stone_id, rng_seed=3))
    max15_uid = e2e.seed_equipment(
        db, crafter, slot="weapon", rarity="legendary", name="極致十五劍", enhance_level=15, now_ts=clock.now
    )
    e2e.assert_game_error(lambda: engine.enhance_equipment(crafter, max15_uid, now_ts=clock.now))

    fuse_rid, fuse_spec = e2e.pick_recipe(content_bundle, "fusion")
    e2e.give_recipe_materials(db, engine, crafter, fuse_spec, clock, multiplier=2)
    e2e.assert_ok_result(engine.fuse_items(crafter, fuse_rid, now_ts=clock.now))

    # 3. 3 Loadouts + Loot Filter
    engine.equip_item(crafter, crafted_uid)
    e2e.assert_ok_result(engine.save_loadout(crafter, 1, "鍛造裝"))
    engine.equip_item(crafter, named_uid)
    e2e.assert_ok_result(engine.save_loadout(crafter, 2, "名品裝"))
    e2e.assert_ok_result(engine.save_loadout(crafter, 3, "備用裝"))
    e2e.assert_ok_result(engine.apply_loadout(crafter, 1))
    e2e.assert_ok_result(engine.set_loot_filter(crafter, min_rarity="rare", min_level=50))

    # 4. Cooking (timing_perfect) + Party Big Pot Stew
    cook_rid, cook_spec = e2e.pick_recipe(content_bundle, "cooking")
    e2e.give_recipe_materials(db, engine, crafter, cook_spec, clock, multiplier=2)
    e2e.assert_ok_result(engine.cook_dish(crafter, cook_rid, timing_perfect=True, now_ts=clock.now))

    stew_rid, stew_spec = e2e.pick_recipe(content_bundle, "stew")
    e2e.give_recipe_materials(db, engine, crafter, stew_spec, clock, multiplier=2)
    stew_id = str(
        e2e.extract_field(
            engine.start_big_pot_stew(crafter, stew_rid, party.party_id, now_ts=clock.now),
            "stew_id",
            "id",
        )
    )
    e2e.assert_ok_result(engine.claim_stew(mate1, stew_id, now_ts=clock.now))
    e2e.assert_ok_result(engine.claim_stew(mate2, stew_id, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.claim_stew(mate1, stew_id, now_ts=clock.now))


# ===========================================================================
# W14: Full Guild Lifecycle & 12-Human Raid Alliance (12 Real Humans)
# ===========================================================================


def test_w14_guild_lifecycle_and_12_human_raid_alliance(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    humans = [make_player(f"血盟成員{i + 1}") for i in range(12)]
    leader = humans[0]
    for uid in humans:
        e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 1, clock=clock, level=12, col=20_000)

    g = e2e.assert_ok_result(engine.create_guild(leader, "血盟騎士團W14", "K14", now_ts=clock.now))
    gid = int(e2e.extract_field(g, "guild_id", "id"))
    e2e.assert_game_error(lambda: engine.create_guild(humans[1], "血盟騎士團W14", "DUP", now_ts=clock.now))
    for m in humans[1:]:
        e2e.assert_ok_result(engine.join_guild(m, gid, now_ts=clock.now))

    ranks = e2e.extract_field(g, "ranks", "rank_names", default=["vice_leader", "officer", "veteran", "member"])
    if isinstance(ranks, dict):
        ranks = list(ranks.keys())
    sub_ranks = [str(r) for r in ranks if str(r) not in ("leader", "會長", "團長")][:4]
    if len(sub_ranks) < 4:
        sub_ranks = ["vice_leader", "officer", "veteran", "member"]
    for m, rk in zip(humans[1:5], sub_ranks):
        e2e.assert_ok_result(engine.set_guild_rank(leader, m, rk))

    e2e.assert_ok_result(engine.guild_contribute(leader, 5_000, now_ts=clock.now))
    spare = e2e.seed_equipment(db, leader, slot="armor", rarity="rare", name="騎士團制式甲", now_ts=clock.now)
    wh_id = int(e2e.extract_field(engine.guild_warehouse_deposit(leader, spare, now_ts=clock.now), "warehouse_id", "id"))
    e2e.assert_game_error(lambda: engine.guild_warehouse_withdraw(humans[-1], wh_id, now_ts=clock.now))
    e2e.assert_ok_result(engine.guild_warehouse_withdraw(humans[1], wh_id, now_ts=clock.now))
    e2e.assert_ok_result(engine.guild_activate_buff(leader, "rally", now_ts=clock.now))
    e2e.assert_ok_result(engine.start_guild_raid(leader, now_ts=clock.now))

    # 12h rejoin cooldown + leader leave guard
    e2e.assert_game_error(lambda: engine.leave_guild(leader, now_ts=clock.now))
    e2e.assert_ok_result(engine.leave_guild(humans[11], now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.join_guild(humans[11], gid, now_ts=clock.now + 3600))
    clock.advance(hours=12, minutes=1)
    e2e.assert_ok_result(engine.join_guild(humans[11], gid, now_ts=clock.now))

    # 12-human Raid Alliance Team Boss x4 runs (3 boosted + 4th non-boosted)
    e2e.explore_to_boss_gate(engine, leader, clock, floor=1)
    party = e2e.assert_ok_result(
        engine.create_party(
            leader, floor=1, boss_mode="team_boss", max_size=12, is_raid_alliance=True, now_ts=clock.now
        )
    )
    pid = str(e2e.extract_field(party, "party_id", "id"))
    for m in humans[1:]:
        e2e.assert_ok_result(engine.join_party(pid, m, role="dps", now_ts=clock.now))
    for m in humans:
        e2e.assert_ok_result(engine.set_party_ready(pid, m, True))

    boosts: list[bool] = []
    for _ in range(4):
        e2e.assert_ok_result(engine.enter_boss_room(pid, leader, now_ts=clock.now))
        rid = str(e2e.extract_field(engine.start_party_raid(pid, leader, now_ts=clock.now), "raid_id", "id"))
        fin, _ = e2e.drive_coop_raid(engine, clock, rid, humans)
        boosts.append(bool(e2e.extract_field(fin, "boosted_drop", "daily_boost", "is_boosted", default=False)))
        clock.advance(minutes=10)
    assert boosts == [True, True, True, False]
    lb = e2e.assert_ok_result(engine.get_leaderboard("guild", limit=10))
    assert len(e2e.extract_field(lb, "entries", "rankings", "rows", "leaderboard")) >= 1


# ===========================================================================
# W15: Marketplace Escrow & 4-Buyer Concurrent Race (5 Real Humans)
# ===========================================================================


def test_w15_marketplace_escrow_and_concurrent_buyer_race(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    seller = make_player("大商人艾基爾")
    buyers = [make_player(f"買家{i}") for i in range(4)]
    for b in buyers:
        e2e.seed_col(db, engine, b, 500, clock)

    named_uid = e2e.seed_equipment(db, seller, slot="weapon", rarity="named", name="非賣名品", now_ts=clock.now)
    locked_uid = e2e.seed_equipment(db, seller, slot="ring", rarity="rare", name="鎖定戒", now_ts=clock.now)
    engine.toggle_lock_item(seller, locked_uid)
    trade_uid1 = e2e.seed_equipment(
        db,
        seller,
        slot="weapon",
        rarity="rare",
        name="競標閃爍細劍",
        weapon_style="rapier",
        affixes={"crit_rate": 0.1, "atk_pct": 0.15},
        now_ts=clock.now,
    )
    trade_uid2 = e2e.seed_equipment(db, seller, slot="boots", rarity="fine", name="撤回靴", now_ts=clock.now)

    # Reject Field, Named, Locked listings
    engine.travel_zone(seller, "field", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.list_market_item(seller, item_uid=trade_uid1, price_col=250, now_ts=clock.now))
    engine.travel_zone(seller, "town", now_ts=clock.now)
    e2e.assert_game_error(lambda: engine.list_market_item(seller, item_uid=named_uid, price_col=250, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.list_market_item(seller, item_uid=locked_uid, price_col=250, now_ts=clock.now))

    # List & cancel test + self-buy guard + 2-affix search
    l_cancel = int(
        e2e.extract_field(
            engine.list_market_item(seller, item_uid=trade_uid2, price_col=120, now_ts=clock.now),
            "listing_id",
            "id",
        )
    )
    e2e.assert_ok_result(engine.cancel_market_listing(seller, l_cancel))
    assert any(int(g.get("id", g.get("item_uid", -1))) == trade_uid2 for g in e2e.get_player_equipment(engine, seller, clock))

    lid = int(
        e2e.extract_field(
            engine.list_market_item(seller, item_uid=trade_uid1, price_col=250, now_ts=clock.now),
            "listing_id",
            "id",
        )
    )
    e2e.assert_game_error(lambda: engine.buy_market_item(seller, lid, now_ts=clock.now))
    found = e2e.extract_field(
        engine.search_market(
            weapon_class="rapier", rarity="rare", affix1="crit_rate", affix2="atk_pct", max_price=300
        ),
        "listings",
        "items",
        "results",
    )
    assert len(found) == 1

    # 4 concurrent buyers race for the single listing
    game_err = e2e.load_engine_api()["GameError"]
    seller_col_before = e2e.get_player_col(engine, seller, clock)
    outcomes = e2e.run_concurrent_calls(
        [(lambda b=buyer: engine.buy_market_item(b, lid, now_ts=clock.now)) for buyer in buyers]
    )
    wins = [ok for ok, _ in outcomes if ok]
    errs = [val for ok, val in outcomes if not ok]
    assert len(wins) == 1 and len(errs) == 3
    assert all(isinstance(err, game_err) for err in errs)
    cols_after = sorted(e2e.get_player_col(engine, b, clock) for b in buyers)
    assert cols_after == [250, 500, 500, 500]
    assert e2e.get_player_col(engine, seller, clock) > seller_col_before


# ===========================================================================
# W16: Floor World Boss, Accelerated World, PvP Duels & Color Cursor (5 Humans)
# ===========================================================================


def test_w16_world_boss_accelerated_world_pvp_duels_and_cursor(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    players = [make_player(f"競技勇者{i}") for i in range(5)]
    for idx, uid in enumerate(players):
        e2e.prepare_player_for_floor(engine, db, content_bundle, uid, 30, clock=clock, level=40 + idx * 5, col=2_000)

    # 1. Floor World Boss attempts, banking & leaderboard
    for uid in players:
        for _ in range(3):
            e2e.assert_ok_result(engine.attack_floor_world_boss(uid, now_ts=clock.now))
        e2e.assert_game_error(lambda u=uid: engine.attack_floor_world_boss(u, now_ts=clock.now))
    clock.advance(days=2)
    for _ in range(6):
        e2e.assert_ok_result(engine.attack_floor_world_boss(players[0], now_ts=clock.now))
    lb = e2e.assert_ok_result(engine.get_leaderboard("world_boss", limit=10))
    rows = e2e.extract_field(lb, "entries", "rankings", "rows", "leaderboard")
    dmgs = [float(e2e.extract_field(r, "score", "damage", "total_damage", "value")) for r in rows]
    assert len(rows) >= 5 and dmgs == sorted(dmgs, reverse=True)

    # 2. First-Strike wager duel + Full duel + negative guards
    u1, u2, u3, u4, u5 = players
    e2e.assert_game_error(lambda: engine.challenge_duel(u1, u1, mode="first_strike", now_ts=clock.now))
    c1_b, c2_b = e2e.get_player_col(engine, u1, clock), e2e.get_player_col(engine, u2, clock)
    d1 = str(
        e2e.extract_field(
            engine.challenge_duel(u1, u2, mode="first_strike", wager_col=100, now_ts=clock.now), "duel_id", "id"
        )
    )
    e2e.assert_game_error(lambda: engine.accept_duel(d1, u3, now_ts=clock.now))
    engine.accept_duel(d1, u2, now_ts=clock.now)
    for i in range(60):
        res = e2e.assert_ok_result(engine.duel_action(d1, u1 if i % 2 == 0 else u2, "attack", now_ts=clock.now))
        if e2e.extract_field(res, "finished", "ended", default=False) is True or str(
            e2e.extract_field(res, "status", default="")
        ).lower() in ("finished", "ended", "completed"):
            break
    assert e2e.get_player_col(engine, u1, clock) + e2e.get_player_col(engine, u2, clock) == c1_b + c2_b
    assert e2e.get_player_cursor(engine, u1, clock) == "green"
    assert e2e.get_player_cursor(engine, u2, clock) == "green"

    d2 = str(e2e.extract_field(engine.challenge_duel(u3, u4, mode="full", now_ts=clock.now), "duel_id", "id"))
    engine.accept_duel(d2, u4, now_ts=clock.now)
    for i in range(80):
        res = e2e.assert_ok_result(engine.duel_action(d2, u3 if i % 2 == 0 else u4, "attack", now_ts=clock.now))
        if e2e.extract_field(res, "finished", "ended", default=False) is True or str(
            e2e.extract_field(res, "status", default="")
        ).lower() in ("finished", "ended", "completed"):
            break
    assert int(e2e.extract_field(engine.get_profile(u3, now_ts=clock.now), "hp", "current_hp", "max_hp")) >= 1
    assert int(e2e.extract_field(engine.get_profile(u4, now_ts=clock.now), "hp", "current_hp", "max_hp")) >= 1

    # 3. Color Cursor shift & FakeClock redemption
    ch_id, choice_id, _ = e2e.pick_story_choice(content_bundle, karma_negative=True)
    engine.choose_story_option(u5, ch_id, choice_id, now_ts=clock.now)
    clock.advance(days=7)
    assert e2e.get_player_cursor(engine, u5, clock) == "green"


# ===========================================================================
# W17: Hardcore Permadeath vs Standard Rescue & Monument of Life (4 Humans)
# ===========================================================================


def test_w17_hardcore_permadeath_vs_standard_rescue_and_monument(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    hc = make_player("硬核烈士", mode="hardcore")
    std_v = make_player("標準傷兵", mode="standard")
    rescuer = make_player("醫療後援", mode="standard")
    make_player("見證同伴", mode="standard")

    mon0 = engine.get_monument_of_life(limit=10)
    assert int(e2e.extract_field(mon0, "total", "total_players")) == 4
    assert int(e2e.extract_field(mon0, "alive", "alive_count", "alive_players")) == 4
    assert int(e2e.extract_field(mon0, "fallen", "dead", "fallen_count", "dead_count")) == 0

    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    e2e.seed_item(db, rescuer, tp_id, 3)
    spare = e2e.seed_equipment(db, hc, slot="ring", rarity="rare", name="傳承遺戒", now_ts=clock.now)
    engine.turn_in_achievement_gear(hc, spare)

    e2e.induce_combat_defeat(engine, db, content_bundle, hc, clock, in_boss=True)
    e2e.induce_combat_defeat(engine, db, content_bundle, std_v, clock)

    mon1 = engine.get_monument_of_life(limit=10)
    assert int(e2e.extract_field(mon1, "fallen", "dead", "fallen_count", "dead_count")) == 1
    assert "硬核烈士" in e2e.extract_text_blob(mon1) or hc in e2e.extract_text_blob(mon1)

    tp_before = e2e.get_player_item_qty(engine, rescuer, tp_id, clock)
    e2e.assert_game_error(lambda: engine.rescue_downed_player(rescuer, hc, now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, rescuer, tp_id, clock) == tp_before

    e2e.assert_ok_result(engine.rescue_downed_player(rescuer, std_v, now_ts=clock.now), require_zh_tw=True)
    assert e2e.get_player_item_qty(engine, rescuer, tp_id, clock) == tp_before - 1
    assert e2e.get_player_zone(engine, std_v, clock) == "town"
    assert int(e2e.extract_field(engine.get_monument_of_life(limit=10), "fallen", "dead", "fallen_count", "dead_count")) == 1


# ===========================================================================
# W18: Multi-Human Concurrency Stress, First-Kill Race & AFK Timeout (8 Humans)
# ===========================================================================


def test_w18_concurrency_stress_first_kill_race_and_afk_timeout(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    pa = make_party_humans(count=4, floor=1, boss_mode="first_kill", prepare_floor=True, unlock_boss_gate=True)
    pb = make_party_humans(count=4, floor=1, boss_mode="first_kill", prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(pa.party_id, pa.leader_id, now_ts=clock.now)
    rid_a = str(e2e.extract_field(engine.start_party_raid(pa.party_id, pa.leader_id, now_ts=clock.now), "raid_id", "id"))
    engine.enter_boss_room(pb.party_id, pb.leader_id, now_ts=clock.now)
    rid_b = str(e2e.extract_field(engine.start_party_raid(pb.party_id, pb.leader_id, now_ts=clock.now), "raid_id", "id"))

    # 1. Parallel action submissions + duplicate double-clicks on Party A
    game_err = e2e.load_engine_api()["GameError"]
    round1_calls = [
        (lambda u=uid: engine.submit_raid_action(rid_a, u, "attack", now_ts=clock.now))
        for uid in pa.member_ids
    ] + [
        lambda: engine.submit_raid_action(rid_a, pa.member_ids[0], "defend", now_ts=clock.now),
        lambda: engine.submit_raid_action(rid_a, pa.member_ids[1], "defend", now_ts=clock.now),
    ]
    r1_out = e2e.run_concurrent_calls(round1_calls)
    assert sum(1 for ok, _ in r1_out if ok) == 4
    assert all(isinstance(val, game_err) for ok, val in r1_out if not ok)

    # 2. AFK timeout (25s+) x2 marks member 4 sleeping/auto-managed cleanly without deadlock
    for _ in range(2):
        for uid in pa.member_ids[:3]:
            engine.submit_raid_action(rid_a, uid, "defend", now_ts=clock.now)
        clock.advance(seconds=26)
        e2e.assert_ok_result(
            engine.resolve_raid_round(rid_a, requester_id=pa.leader_id, force_timeout=True, now_ts=clock.now)
        )

    # 3. Party A & Party B concurrently finish uncleared Floor 1 First-Kill race
    race_out = e2e.run_concurrent_calls(
        [
            lambda: e2e.drive_coop_raid(engine, clock, rid_a, pa.member_ids)[0],
            lambda: e2e.drive_coop_raid(engine, clock, rid_b, pb.member_ids)[0],
        ]
    )
    assert all(ok for ok, _ in race_out), f"Concurrent First-Kill race failed: {race_out!r}"
    fk_wins = [bool(e2e.extract_field(res, "is_first_kill", "first_kill", default=False)) for _, res in race_out]
    assert sum(fk_wins) == 1
    for uid in pa.member_ids + pb.member_ids:
        assert e2e.get_player_floor(engine, uid, clock)[1] >= 2


# ===========================================================================
# W19: SQLite WAL Migration, Restart Recovery & Gzip Snapshot Sync
# ===========================================================================


def test_w19_sqlite_wal_migration_restart_recovery_and_snapshot_sync(
    v1_legacy_db_path: Path,
    tmp_path: Path,
    content_bundle: Any,
    clock: Any,
    e2e: Any,
) -> None:
    db_api = e2e.load_db_api()
    assert int(db_api["SCHEMA_VERSION"]) == 2
    db1 = db_api["RPGDatabase"](v1_legacy_db_path)
    try:
        eng1 = e2e.instantiate_engine(db1, content_bundle)
        # Legacy v1 players survived migration intact
        legacy_prof = e2e.assert_ok_result(eng1.get_profile("800001", now_ts=clock.now))
        assert str(e2e.extract_field(legacy_prof, "display_name", "name")) == "舊紀元劍士"

        # New SAO players + Offline Expedition + nested transaction rollback
        eng1.create_character("419002", "遠征先鋒", now_ts=clock.now)
        eng1.create_character("419003", "備份見證者", now_ts=clock.now)
        exp_id, _, duration = e2e.pick_expedition(content_bundle)
        eng1.start_expedition("419002", exp_id, now_ts=clock.now)
        col_before = e2e.get_player_col(eng1, "419002", clock)

        with pytest.raises(RuntimeError), db1.transaction():
            eng1.create_character("419999", "回滾測試", now_ts=clock.now)
            raise RuntimeError("rollback verification")
        assert db1.get_player("419999") is None

        # Local backup rotation + monotonic Gzip snapshots
        for _ in range(6):
            db1.create_local_backup(keep=5)
        snap_1 = e2e.export_db_snapshot_bytes(db1)
        seq_1 = e2e.get_db_save_seq(db1)
        eng1.claim_daily("419003", now_ts=clock.now)
        snap_2 = e2e.export_db_snapshot_bytes(db1)
        seq_2 = e2e.get_db_save_seq(db1)
        assert seq_2 > seq_1

        # Rollback guard rejects stale snap_1; corrupt bytes rejected
        try:
            assert e2e.import_db_snapshot_bytes(db1, snap_1, force=False) is False
        except ValueError as exc:
            assert str(exc)
        try:
            assert e2e.import_db_snapshot_bytes(db1, b"corrupt-non-gzip") is False
        except (ValueError, OSError) as exc:
            assert str(exc)
    finally:
        db1.close()

    # Restore snap_2 into brand-new DB and claim Offline Expedition after FakeClock advance
    db_restored = db_api["RPGDatabase"](tmp_path / "w19_restored.db")
    try:
        assert e2e.import_db_snapshot_bytes(db_restored, snap_2) is True
        eng2 = e2e.instantiate_engine(db_restored, content_bundle)
        clock.advance(seconds=duration + 60)
        e2e.assert_ok_result(eng2.claim_expedition("419002", now_ts=clock.now), require_zh_tw=True)
        assert e2e.get_player_col(eng2, "419002", clock) > col_before
    finally:
        db_restored.close()


# ===========================================================================
# W20: Full Discord CommandTree, Views & /p Untouched Regression Smoke
# ===========================================================================


def test_w20_discord_command_tree_views_and_p_regression(
    tmp_path: Path,
    fake_discord: dict[str, Any],
    e2e: Any,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    side_db = tmp_path / "no_side_effect_w20" / "rpg.db"
    proc = subprocess.run(
        [sys.executable, "-c", "import bot; assert callable(bot.create_bot)"],
        cwd=str(repo_root),
        env={
            "PATH": "/usr/bin:/bin",
            "RPG_DB_PATH": str(side_db),
            "DISCORD_BOT_TOKEN": "local-e2e-synthetic-credential",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"Bare bot import failed: {proc.stderr}"
    assert not side_db.exists()

    bot_api = e2e.load_bot_api()
    settings = bot_api["Settings"](
        discord_bot_token="local-e2e-synthetic-credential",
        timezone_offset_hours=8,
        rpg_db_path=str(tmp_path / "bot_w20.db"),
        rpg_backup_channel_id="",
        rpg_backup_interval_minutes=15,
    )
    bot_inst = bot_api["create_bot"](settings)
    try:
        cmd_names = {cmd.name for cmd in bot_inst.tree.get_commands()}
        assert cmd_names == e2e.EXPECTED_23_COMMANDS

        user = fake_discord["make_user"](700001, "亞絲娜UI測試")
        inter = fake_discord["make_interaction"](user, client=bot_inst)

        # Exercise key SAO slash commands & validate every Embed/View against Discord hard limits
        for cname in ("start", "profile", "tower", "party", "forge", "market", "guild", "leaderboard", "help"):
            cmd = bot_inst.tree.get_command(cname)
            assert cmd is not None, f"Missing slash command /{cname}"
            inter_cmd = fake_discord["make_interaction"](user, ch=inter.channel, client=bot_inst)
            e2e.run_async(cmd.callback(inter_cmd))
            payloads = inter_cmd.all_payloads()
            assert len(payloads) >= 1, f"Command /{cname} emitted no Discord response"
            for payload in payloads:
                e2e.assert_discord_payload_valid(
                    content=payload.get("content"),
                    embeds=payload.get("embeds"),
                    view=payload.get("view"),
                )

        # Verify untouched /p meme command stays independent of SAO RPG state
        p_cmd = bot_inst.tree.get_command("p")
        assert p_cmd is not None
        sample_meme, matched_cnt, total_cnt = bot_api["AnimeMemeService"]().pick_random(category="all")
        assert sample_meme is not None and matched_cnt > 0 and total_cnt > 0
        meme_embed = bot_api["build_meme_embed"](sample_meme)
        em_dict = meme_embed.to_dict()
        assert em_dict.get("image", {}).get("url")
        assert not em_dict.get("title") and not em_dict.get("description") and not em_dict.get("fields")
        e2e.assert_discord_payload_valid(embed=meme_embed)
    finally:
        if hasattr(bot_inst, "db") and bot_inst.db is not None:
            bot_inst.db.close()
