"""Tier 5: White-Box Adversarial Hardening & Invariant Verification Suite.

Targets concurrency races, exploit bypasses, economy/escrow conservation,
Crystal-Null non-consumption, Named/Locked immutability, Hardcore vs Roguelike
separation, snapshot anti-rollback resilience, zero-Discord domain purity, and
Discord Embed/View hard-limit fuzzing across all 100 Aincrad floors.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1. Concurrency & Atomicity Races
# ---------------------------------------------------------------------------


def test_t5_01_concurrent_market_purchase_8_buyers_col_and_item_conservation(
    engine: Any,
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    seller = make_player("黑市拍賣師")
    buyers = [make_player(f"搶購者{i}") for i in range(8)]
    for b in buyers:
        e2e.seed_col(db, engine, b, 2_000, clock)

    item_uid = e2e.seed_equipment(
        db, seller, slot="weapon", rarity="legendary", name="稀世光劍", atk=420, now_ts=clock.now
    )
    listing = e2e.assert_ok_result(
        engine.list_market_item(seller, item_uid=item_uid, price_col=1_000, now_ts=clock.now)
    )
    lid = int(e2e.extract_field(listing, "listing_id", "id"))

    seller_before = e2e.get_player_col(engine, seller, clock)
    buyers_before = {b: e2e.get_player_col(engine, b, clock) for b in buyers}

    game_err = e2e.load_engine_api()["GameError"]
    outcomes = e2e.run_concurrent_calls(
        [(lambda b=buyer: engine.buy_market_item(b, lid, now_ts=clock.now)) for buyer in buyers]
    )
    wins = [val for ok, val in outcomes if ok]
    errs = [val for ok, val in outcomes if not ok]
    assert len(wins) == 1
    assert len(errs) == 7
    assert all(isinstance(err, game_err) for err in errs)

    # Strictly 1 buyer paid 1000 Col and owns the item; 7 losers paid 0 Col
    paid = [b for b in buyers if e2e.get_player_col(engine, b, clock) == buyers_before[b] - 1_000]
    unchanged = [b for b in buyers if e2e.get_player_col(engine, b, clock) == buyers_before[b]]
    assert len(paid) == 1 and len(unchanged) == 7
    winner = paid[0]
    assert any(int(g.get("id", g.get("item_uid", -1))) == item_uid for g in e2e.get_player_equipment(engine, winner, clock))
    assert not any(int(g.get("id", g.get("item_uid", -1))) == item_uid for g in e2e.get_player_equipment(engine, seller, clock))
    assert e2e.get_player_col(engine, seller, clock) > seller_before


def test_t5_02_concurrent_party_join_strictly_respects_max_size(
    engine: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    leader = make_player("滿員防爆隊長")
    candidates = [make_player(f"排隊玩家{i}") for i in range(10)]
    party = e2e.assert_ok_result(engine.create_party(leader, floor=1, max_size=4, now_ts=clock.now))
    pid = str(e2e.extract_field(party, "party_id", "id"))

    game_err = e2e.load_engine_api()["GameError"]
    outcomes = e2e.run_concurrent_calls(
        [(lambda u=uid: engine.join_party(pid, u, role="dps", now_ts=clock.now)) for uid in candidates]
    )
    wins = [ok for ok, _ in outcomes if ok]
    errs = [val for ok, val in outcomes if not ok]
    assert len(wins) == 3
    assert len(errs) == 7
    assert all(isinstance(err, game_err) for err in errs)


def test_t5_03_concurrent_first_kill_claim_6_contenders_strictly_one_winner(
    db: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    contenders = [make_player(f"首殺競速者{i}") for i in range(6)]
    outcomes = e2e.run_concurrent_calls(
        [
            (
                lambda u=uid, idx=i: db.claim_server_floor_first_kill(
                    floor=10,
                    boss_id="kagachi_samurai_lord",
                    boss_name="武士領主・加賀智",
                    leader_id=u,
                    leader_name=f"首殺競速者{idx}",
                    la_user_id=u,
                    la_user_name=f"首殺競速者{idx}",
                    participant_ids=[u],
                    cleared_at=clock.now,
                )
            )
            for i, uid in enumerate(contenders)
        ]
    )
    assert all(ok for ok, _ in outcomes)
    claimed_flags = [bool(val) for _, val in outcomes]
    assert sum(claimed_flags) == 1
    fk_row = db.get_server_floor_clear(10)
    assert fk_row is not None and fk_row["leader_id"] in contenders


def test_t5_04_concurrent_raid_actions_and_double_clicks_zero_bleedthrough(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    party = make_party_humans(count=4, floor=1, prepare_floor=True, unlock_boss_gate=True)
    engine.enter_boss_room(party.party_id, party.leader_id, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, party.leader_id, now_ts=clock.now))
    rid = str(e2e.extract_field(raid, "raid_id", "id"))

    game_err = e2e.load_engine_api()["GameError"]
    # 4 unique players + 4 simultaneous duplicate double-clicks in Round 1
    burst = [
        (lambda u=uid: engine.submit_raid_action(rid, u, "attack", now_ts=clock.now))
        for uid in party.member_ids
    ] + [
        (lambda u=uid: engine.submit_raid_action(rid, u, "defend", now_ts=clock.now))
        for uid in party.member_ids
    ]
    outcomes = e2e.run_concurrent_calls(burst)
    assert sum(1 for ok, _ in outcomes if ok) == 4
    assert all(isinstance(val, game_err) for ok, val in outcomes if not ok)


# ---------------------------------------------------------------------------
# 2. Exploit Bypasses & Immutability Guards
# ---------------------------------------------------------------------------


def test_t5_05_mid_boss_exploit_lockout_matrix(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("頭目戰全防呆測者", weapon_style="sword")
    e2e.prepare_player_for_floor(
        engine, db, content_bundle, uid, 1, clock=clock, level=15, unlock_boss_gate=True
    )
    e2e.seed_col(db, engine, uid, 10_000, clock)
    engine.travel_zone(uid, "town", now_ts=clock.now)
    engine.save_loadout(uid, 1, "標準配裝")
    engine.create_guild(uid, "防呆騎士團", "ADV", now_ts=clock.now)
    spare = e2e.seed_equipment(db, uid, slot="ring", rarity="rare", name="防呆戒", now_ts=clock.now)
    forge_rid, spec = e2e.pick_recipe(content_bundle, "blacksmithing")
    e2e.give_recipe_materials(db, engine, uid, spec, clock)
    skills = e2e.pick_sword_skills(content_bundle, "sword", count=2)

    engine.start_floor_boss(uid, floor=1, mode="normal", now_ts=clock.now)

    # Every single exploit vector must be blocked mid-boss
    e2e.assert_game_error(lambda: engine.respec_talents(uid))
    e2e.assert_game_error(lambda: engine.equip_item(uid, spare))
    e2e.assert_game_error(lambda: engine.apply_loadout(uid, 1))
    e2e.assert_game_error(lambda: engine.switch_weapon_style(uid, "axe"))
    e2e.assert_game_error(lambda: engine.set_skill_slots(uid, skills))
    e2e.assert_game_error(lambda: engine.forge_craft(uid, forge_rid, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.list_market_item(uid, item_uid=spare, price_col=100, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.guild_warehouse_deposit(uid, spare, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.teleport_floor(uid, 1, now_ts=clock.now))


def test_t5_06_named_and_locked_gear_immutability_guards(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    uid = make_player("名品與鎖定守衛者")
    e2e.seed_col(db, engine, uid, 10_000, clock)
    engine.create_guild(uid, "名品守護會", "NMG", now_ts=clock.now)

    named_uid = e2e.seed_equipment(
        db, uid, slot="weapon", rarity="named", name="闡釋者（Elucidator）", atk=500, now_ts=clock.now
    )
    locked_uid = e2e.seed_equipment(
        db, uid, slot="ring", rarity="rare", name="鎖定勇氣戒", atk=30, now_ts=clock.now
    )
    engine.toggle_lock_item(uid, locked_uid)

    stones = [iid for iid, sp in content_bundle.items_crystals.items() if sp.get("category") == "magic_stone"]
    assert stones
    e2e.seed_item(db, uid, stones[0], 3)

    # Named gear: no magic stone, no market listing, no guild warehouse deposit
    e2e.assert_game_error(lambda: engine.apply_magic_stone(uid, named_uid, stones[0]))
    e2e.assert_game_error(lambda: engine.list_market_item(uid, item_uid=named_uid, price_col=999, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.guild_warehouse_deposit(uid, named_uid, now_ts=clock.now))

    # Locked gear: no market listing, no achievement turn-in, no guild warehouse deposit
    e2e.assert_game_error(lambda: engine.list_market_item(uid, item_uid=locked_uid, price_col=100, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.turn_in_achievement_gear(uid, locked_uid))
    e2e.assert_game_error(lambda: engine.guild_warehouse_deposit(uid, locked_uid, now_ts=clock.now))


def test_t5_07_negative_overflow_magic_and_sqli_input_rejection(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    u1 = make_player("注入防禦者")
    u2 = make_player("對手防禦者")
    e2e.seed_col(db, engine, u1, 5_000, clock)
    engine.create_guild(u1, "合法安全公會", "SEC", now_ts=clock.now)

    # Negative / zero / invalid bounds
    e2e.assert_game_error(lambda: engine.guild_contribute(u1, -500, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.guild_contribute(u1, 0, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.buy_shop_item(u1, "hp_potion_t1", qty=-5, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.buy_shop_item(u1, "hp_potion_t1", qty=0, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.challenge_duel(u1, u2, mode="first_strike", wager_col=-100, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.allocate_stats(u1, {"int": 1}))
    e2e.assert_game_error(lambda: engine.allocate_stats(u1, {"magic": 1}))
    e2e.assert_game_error(lambda: engine.allocate_stats(u1, {"str": -2}))
    e2e.assert_game_error(lambda: engine.teleport_floor(u1, 0, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.teleport_floor(u1, 101, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.get_floor_info(-3))

    # SQL injection strings must be safely parameterized and leave DB tables intact
    sqli = "'; DROP TABLE players; --"
    res = e2e.assert_ok_result(engine.search_market(affix1=sqli, weapon_class=sqli))
    assert isinstance(res, dict)
    assert db.get_player(u1) is not None and db.get_player(u2) is not None


def test_t5_08_crystal_null_non_consumption_solo_and_party(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    tp_id = e2e.pick_crystal_ids(content_bundle)["teleport"]
    party = make_party_humans(count=2, floor=100, prepare_floor=True, unlock_boss_gate=True)
    leader = party.leader_id
    before_tp = e2e.get_player_item_qty(engine, leader, tp_id, clock)
    assert before_tp >= 1

    engine.enter_boss_room(party.party_id, leader, now_ts=clock.now)
    raid = e2e.assert_ok_result(engine.start_party_raid(party.party_id, leader, now_ts=clock.now))
    rid = str(e2e.extract_field(raid, "raid_id", "id"))

    e2e.assert_game_error(lambda: engine.submit_raid_action(rid, leader, "crystal", item_id=tp_id, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.submit_raid_action(rid, leader, "retreat", now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.party_group_teleport(party.party_id, leader, 1, now_ts=clock.now))
    assert e2e.get_player_item_qty(engine, leader, tp_id, clock) == before_tp


def test_t5_09_hardcore_permadeath_vs_roguelike_non_lethal_separation(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: Any,
    make_player: Callable[..., str],
    e2e: Any,
) -> None:
    hc_rogue = make_player("地下城硬核倖存者", mode="hardcore")
    hc_field = make_player("前線硬核犧牲者", mode="hardcore")

    # Defeat inside Black Iron Palace Underground Roguelike MUST stay alive
    e2e.induce_combat_defeat(engine, db, content_bundle, hc_rogue, clock, in_roguelike=True)
    p_rogue = db.get_player(hc_rogue)
    assert p_rogue is not None and not p_rogue.is_dead and p_rogue.zone == "town"

    # Defeat in normal floor boss combat triggers permanent Hardcore death
    e2e.induce_combat_defeat(engine, db, content_bundle, hc_field, clock, in_boss=True)
    p_field = db.get_player(hc_field)
    assert p_field is not None and p_field.is_dead
    e2e.assert_game_error(lambda: engine.explore_floor(hc_field, steps=1, now_ts=clock.now))
    e2e.assert_game_error(lambda: engine.start_roguelike(hc_field, now_ts=clock.now))


def test_t5_10_snapshot_anti_rollback_and_corrupt_payload_resilience(
    tmp_path: Path,
    content_bundle: Any,
    clock: Any,
    e2e: Any,
) -> None:
    db_api = e2e.load_db_api()
    db_inst = db_api["RPGDatabase"](tmp_path / "t5_snap.db")
    try:
        eng = e2e.instantiate_engine(db_inst, content_bundle)
        eng.create_character("510001", "快照守門員", now_ts=clock.now)
        snap_old = db_inst.export_snapshot_bytes()
        seq_old = db_inst.get_save_seq()

        eng.claim_daily("510001", now_ts=clock.now)
        eng.create_character("510002", "新進攻略者", now_ts=clock.now)
        seq_new = db_inst.get_save_seq()
        assert seq_new > seq_old

        # Stale snapshot rollback MUST be rejected when force=False
        assert db_inst.import_snapshot_bytes(snap_old, force=False) is False
        assert db_inst.get_player("510002") is not None

        # Corrupt / non-gzip / truncated bytes MUST fail cleanly without harming live DB
        for bad_bytes in (b"", b"not-gzip-at-all", snap_old[:12]):
            try:
                ok = db_inst.import_snapshot_bytes(bad_bytes, force=True)
                assert ok is False
            except (ValueError, OSError):
                pass
        assert db_inst.get_player("510001") is not None
        assert db_inst.get_player("510002") is not None
    finally:
        db_inst.close()


# ---------------------------------------------------------------------------
# 3. Architectural Purity & Discord Hard-Limit Fuzzing
# ---------------------------------------------------------------------------


def test_t5_11_domain_core_has_zero_discord_imports() -> None:
    pure_targets: list[Path] = [
        REPO_ROOT / "src" / "rpg" / "models.py",
        REPO_ROOT / "src" / "rpg" / "engine.py",
        REPO_ROOT / "src" / "rpg" / "data.py",
        REPO_ROOT / "src" / "rpg" / "assets.py",
    ]
    pure_targets.extend(sorted((REPO_ROOT / "src" / "rpg" / "content").rglob("*.py")))
    pure_targets.extend(sorted((REPO_ROOT / "src" / "rpg" / "systems").rglob("*.py")))

    violations: list[str] = []
    for fpath in pure_targets:
        tree = ast.parse(fpath.read_text(encoding="utf-8"), filename=str(fpath))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "discord" or alias.name.startswith("discord."):
                        violations.append(f"{fpath.relative_to(REPO_ROOT)}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "discord" or node.module.startswith("discord.")
            ):
                violations.append(f"{fpath.relative_to(REPO_ROOT)}:{node.lineno} from {node.module}")

    # database.py must also have zero top-level discord imports (only lazy snapshot helper)
    db_path = REPO_ROOT / "src" / "rpg" / "database.py"
    db_tree = ast.parse(db_path.read_text(encoding="utf-8"), filename=str(db_path))
    for node in db_tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "discord" or alias.name.startswith("discord."):
                    violations.append(f"src/rpg/database.py:{node.lineno} top-level import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module and (
            node.module == "discord" or node.module.startswith("discord.")
        ):
            violations.append(f"src/rpg/database.py:{node.lineno} top-level from {node.module}")

    assert not violations, f"Pure domain modules must NOT import discord: {violations}"


def test_t5_12_discord_embeds_and_views_pass_hard_limits_across_all_100_floors(
    engine: Any,
    clock: Any,
    make_party_humans: Callable[..., Any],
    e2e: Any,
) -> None:
    from src.rpg.ui.embeds_party import build_coop_raid_embed, build_party_lobby_embed
    from src.rpg.ui.embeds_tower import build_argo_intel_embed, build_tower_embed

    # Fuzz Tower & Argo embeds across every single floor 1..100
    for floor in range(1, 101):
        finfo = engine.get_floor_info(floor)
        t_em = build_tower_embed(finfo)
        e2e.assert_discord_payload_valid(embed=t_em)
        if floor in e2e.MILESTONE_14_FLOORS:
            argo = engine.get_argo_intel(floor=floor)
            e2e.assert_discord_payload_valid(embed=build_argo_intel_embed(argo))

    # Fuzz 24-human Raid Alliance Party Lobby & Active Coop Raid HUD embed limits
    alliance = make_party_humans(
        count=12,
        floor=1,
        boss_mode="team_boss",
        max_size=24,
        is_raid_alliance=True,
        prepare_floor=True,
        unlock_boss_gate=True,
    )
    party_obj = engine.db.get_party(alliance.party_id)
    assert party_obj is not None
    lobby_em = build_party_lobby_embed({"party": party_obj, "message": "大型攻略團集結！"})
    e2e.assert_discord_payload_valid(embed=lobby_em)

    engine.enter_boss_room(alliance.party_id, alliance.leader_id, now_ts=clock.now)
    raid_res = engine.start_party_raid(alliance.party_id, alliance.leader_id, now_ts=clock.now)
    raid_em = build_coop_raid_embed(raid_res)
    e2e.assert_discord_payload_valid(embed=raid_em)
