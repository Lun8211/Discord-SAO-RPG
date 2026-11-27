"""Comprehensive M1 tests: SAO JSON content validation, SQLite v1->v2 migration, concurrency, pure stats, assets & hygiene."""

from __future__ import annotations

import ast
import copy
import gzip
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.rpg import assets, data
from src.rpg.content.loader import (
    MILESTONE_BOSS_FLOORS,
    REQUIRED_MAGIC_STONES,
    REQUIRED_SAO_CRYSTALS,
    REQUIRED_YUI_LOGS,
    VALID_DAMAGE_TYPES,
    VALID_SLOTS,
    VALID_UNIQUE_SKILLS,
    VALID_WEAPON_CLASSES,
    SAOContentBundle,
    load_and_validate_all,
    load_content,
    resolve_floor_config,
    validate_content_bundle,
)
from src.rpg.database import RPGDatabase
from src.rpg.models import EquipmentItem, GameError, PlayerProfile
from src.rpg.systems.stats import (
    compute_player_stats,
    compute_weapon_style_passives,
    effective_resistance,
    floor_resistance_penetration,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# =============================================================================
# Group 1: JSON Content Bundle, 100 Floors, 14 Milestone Bosses & Negative Validation
# =============================================================================
def test_load_and_validate_all_succeeds_and_caches() -> None:
    bundle = load_and_validate_all(force_reload=True)
    cached = load_content()
    assert cached is bundle

    for attr in (
        "biomes",
        "floors_override",
        "bosses",
        "monsters",
        "chests_loot",
        "weapons_equipment",
        "sword_skills",
        "items_crystals",
        "recipes",
        "quests_events",
    ):
        section = getattr(bundle, attr)
        assert isinstance(section, dict) and len(section) > 0, f"{attr} must be non-empty dict"

    assert len(bundle.bosses) == 34  # 14 milestone + 10 tier templates + 10 world bosses
    assert len(bundle.monsters) == 77
    assert len(bundle.sword_skills) == 34
    assert len(bundle.items_crystals) >= 88


def test_all_100_floors_covered_and_monotonically_scaled() -> None:
    bundle = load_and_validate_all()
    prev: dict[str, Any] | None = None
    seen_tiers: set[int] = set()

    for floor in range(1, 101):
        cfg = resolve_floor_config(floor, bundle)
        assert cfg["floor"] == floor
        assert 1 <= cfg["tier"] <= 10
        seen_tiers.add(cfg["tier"])
        assert len(cfg["mob_pool_ids"]) >= 4
        assert cfg["chest_table_id"] in bundle.chests_loot["tier_tables"]
        assert cfg["boss"]["hp_bars"] >= 3
        assert len(cfg["boss"]["phases"]) >= 2
        if prev is not None:
            for key in ("base_hp", "base_atk", "base_def", "exp_base", "col_base"):
                assert cfg[key] > prev[key], f"Non-monotonic {key} at floor {floor}"
            assert cfg["res_penetration"] >= prev["res_penetration"]
        prev = cfg

    assert seen_tiers == set(range(1, 11))

    # Checkpoint scaling & bool/out-of-range guards
    f1 = resolve_floor_config(1, bundle)
    f10 = resolve_floor_config(10, bundle)
    f25 = resolve_floor_config(25, bundle)
    f50 = resolve_floor_config(50, bundle)
    f75 = resolve_floor_config(75, bundle)
    f100 = resolve_floor_config(100, bundle)
    assert f1["base_hp"] < f10["base_hp"] < f25["base_hp"] < f50["base_hp"] < f75["base_hp"] < f100["base_hp"]
    assert f1["boss_id"] == "illfang_kobold_lord"
    assert f100["boss_id"] == "f100_incarnation_and_heathcliff"

    # Mutating resolved floor config must not corrupt cached bundle
    f1["boss"]["name"] = "CORRUPTED"
    assert resolve_floor_config(1, bundle)["boss"]["name"] == "狗頭人領主・伊爾方"

    with pytest.raises(ValueError):
        resolve_floor_config(True, bundle)
    with pytest.raises(ValueError):
        resolve_floor_config(0, bundle)
    with pytest.raises(ValueError):
        resolve_floor_config(101, bundle)


def test_all_14_milestone_bosses_and_10_tier_guardians_have_phase_scripts() -> None:
    bundle = load_and_validate_all()
    assert len(MILESTONE_BOSS_FLOORS) == 14
    named_items = bundle.weapons_equipment["named_items"]

    milestone_ids: set[str] = set()
    for floor in MILESTONE_BOSS_FLOORS:
        cfg = resolve_floor_config(floor, bundle)
        assert cfg["is_milestone_boss"] is True
        boss = cfg["boss"]
        milestone_ids.add(cfg["boss_id"])
        assert boss["hp_bars"] >= 4
        assert len(boss["phases"]) >= 2
        assert set(boss["dmg_types"]).issubset(VALID_DAMAGE_TYPES)
        assert boss["la_bonus_item_id"] in named_items
        for phase in boss["phases"]:
            assert phase["on_enter_broadcast"].strip()
            assert phase["telegraph"].strip()

    assert len(milestone_ids) == 14
    assert bundle.bosses["f100_incarnation_and_heathcliff"]["dual_stage"] is True
    assert bundle.bosses["f100_incarnation_and_heathcliff"]["anti_crystal"] is True
    assert bundle.bosses["gleam_eyes"]["anti_crystal"] is True
    assert bundle.bosses["skull_reaper"]["anti_crystal"] is True

    for t in range(1, 11):
        tpl = bundle.bosses[f"tier_{t}_guardian"]
        assert tpl["is_template"] is True
        assert len(tpl["phases"]) >= 2
        assert len(tpl["name_patterns"]) >= 3


def test_content_referential_integrity_items_skills_sets_recipes_assets() -> None:
    bundle = load_and_validate_all()
    weq = bundle.weapons_equipment

    assert set(weq["weapon_classes"].keys()) == VALID_WEAPON_CLASSES
    assert set(weq["unique_skills"].keys()) == VALID_UNIQUE_SKILLS
    assert tuple(weq["slot_order"]) == VALID_SLOTS

    for crystal_id in REQUIRED_SAO_CRYSTALS:
        assert crystal_id in bundle.items_crystals
    for stone_id in REQUIRED_MAGIC_STONES:
        assert stone_id in bundle.items_crystals
    for log_id in REQUIRED_YUI_LOGS:
        assert log_id in bundle.quests_events["yui_logs"]

    assert bundle.sword_skills["starburst_stream"]["hits"] == 16
    assert bundle.sword_skills["the_eclipse"]["hits"] == 27
    assert bundle.sword_skills["mothers_rosario"]["hits"] == 11
    assert "crystallite_ingot" in bundle.recipes["blacksmithing"]["forge_dark_repulser"]["ingredients"]

    # Every chest tier & trap present
    assert len(bundle.chests_loot["chest_tiers"]) == 6
    assert bundle.chests_loot["traps"]["mimic"]["mob_id"] in bundle.monsters
    assert bundle.chests_loot["traps"]["crystal_null_room"]["no_teleport_crystal"] is True

    # Every named item & biome banner resolves via assets.resolve_asset_key
    for tier in bundle.biomes["tiers"]:
        assert assets.resolve_asset_key(tier["banner_asset_key"]) is not None
    for nspec in weq["named_items"].values():
        assert assets.resolve_asset_key(nspec["asset_key"]) is not None


def _clone_bundle(bundle: SAOContentBundle) -> dict[str, dict[str, Any]]:
    return {
        "biomes": copy.deepcopy(bundle.biomes),
        "floors_override": copy.deepcopy(bundle.floors_override),
        "bosses": copy.deepcopy(bundle.bosses),
        "monsters": copy.deepcopy(bundle.monsters),
        "chests_loot": copy.deepcopy(bundle.chests_loot),
        "weapons_equipment": copy.deepcopy(bundle.weapons_equipment),
        "sword_skills": copy.deepcopy(bundle.sword_skills),
        "items_crystals": copy.deepcopy(bundle.items_crystals),
        "recipes": copy.deepcopy(bundle.recipes),
        "quests_events": copy.deepcopy(bundle.quests_events),
    }


@pytest.mark.parametrize(
    "case_name",
    [
        "dangling_override_boss",
        "dangling_biome_mob",
        "dangling_la_bonus",
        "missing_f50_milestone_boss",
        "broken_banner_asset_key",
        "invalid_magic_damage_type",
        "floor_gap_at_42",
        "placeholder_todo_string",
    ],
)
def test_validator_rejects_broken_references_and_corrupt_data(case_name: str) -> None:
    valid = load_and_validate_all()
    cloned = _clone_bundle(valid)

    if case_name == "dangling_override_boss":
        cloned["floors_override"]["1"]["boss_id"] = "nonexistent_boss_xyz"
    elif case_name == "dangling_biome_mob":
        cloned["biomes"]["tiers"][0]["mob_pool_ids"][0] = "ghost_mob_xyz"
    elif case_name == "dangling_la_bonus":
        cloned["bosses"]["illfang_kobold_lord"]["la_bonus_item_id"] = "fake_la_sword"
    elif case_name == "missing_f50_milestone_boss":
        del cloned["floors_override"]["50"]["boss_id"]
    elif case_name == "broken_banner_asset_key":
        cloned["biomes"]["tiers"][0]["banner_asset_key"] = "biome_missing_999"
    elif case_name == "invalid_magic_damage_type":
        cloned["sword_skills"]["slant"]["dmg_type"] = "magic"
    elif case_name == "floor_gap_at_42":
        cloned["biomes"]["tiers"][4]["floor_min"] = 43
    elif case_name == "placeholder_todo_string":
        cloned["quests_events"]["yui_logs"]["yui_log_f01"]["content"] = "TODO write lore later"

    corrupted = SAOContentBundle(**cloned)
    with pytest.raises(ValueError):
        validate_content_bundle(corrupted)


# =============================================================================
# Group 2: SQLite WAL v1 -> v2 Migration, Snapshot Anti-Rollback & Concurrency
# =============================================================================
_LEGACY_V1_DDL = """
CREATE TABLE rpg_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE players (
    user_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, class_id TEXT NOT NULL,
    promo_tier INTEGER NOT NULL DEFAULT 1, level INTEGER NOT NULL DEFAULT 1,
    exp INTEGER NOT NULL DEFAULT 0, rebirth_count INTEGER NOT NULL DEFAULT 0,
    gold INTEGER NOT NULL DEFAULT 250, gems INTEGER NOT NULL DEFAULT 50,
    stamina INTEGER NOT NULL DEFAULT 100, stamina_updated_at INTEGER NOT NULL,
    pickaxe_tier INTEGER NOT NULL DEFAULT 1, mine_combo INTEGER NOT NULL DEFAULT 0,
    last_mine_at INTEGER NOT NULL DEFAULT 0, last_boss_at INTEGER NOT NULL DEFAULT 0,
    abyss_floor INTEGER NOT NULL DEFAULT 1, abyss_highest INTEGER NOT NULL DEFAULT 0,
    active_title TEXT NOT NULL DEFAULT '', gacha_pity_legendary INTEGER NOT NULL DEFAULT 0,
    gacha_pity_mythic INTEGER NOT NULL DEFAULT 0, checkin_streak INTEGER NOT NULL DEFAULT 0,
    last_checkin_date TEXT NOT NULL DEFAULT '', total_checkins INTEGER NOT NULL DEFAULT 0,
    total_mines INTEGER NOT NULL DEFAULT 0, total_dungeons INTEGER NOT NULL DEFAULT 0,
    total_enhances INTEGER NOT NULL DEFAULT 0, total_boss_damage INTEGER NOT NULL DEFAULT 0,
    boss_kills_participated INTEGER NOT NULL DEFAULT 0, combat_power INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, template_id TEXT NOT NULL,
    name TEXT NOT NULL, slot TEXT NOT NULL, rarity TEXT NOT NULL, tier INTEGER NOT NULL DEFAULT 1,
    set_id TEXT NOT NULL DEFAULT '', enhance_level INTEGER NOT NULL DEFAULT 0,
    enhance_pity INTEGER NOT NULL DEFAULT 0, base_hp INTEGER NOT NULL DEFAULT 0,
    base_mp INTEGER NOT NULL DEFAULT 0, base_atk INTEGER NOT NULL DEFAULT 0,
    base_def INTEGER NOT NULL DEFAULT 0, affixes_json TEXT NOT NULL DEFAULT '{}',
    is_equipped INTEGER NOT NULL DEFAULT 0, is_locked INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);
CREATE TABLE inventory (
    user_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, item_id),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);
CREATE TABLE dungeon_clears (
    user_id TEXT NOT NULL, dungeon_id TEXT NOT NULL, difficulty TEXT NOT NULL,
    clear_count INTEGER NOT NULL DEFAULT 0, first_cleared_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, dungeon_id, difficulty)
);
CREATE TABLE quests (
    user_id TEXT NOT NULL, period_type TEXT NOT NULL, period_key TEXT NOT NULL,
    quest_id TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, target INTEGER NOT NULL,
    claimed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, period_type, period_key, quest_id)
);
CREATE TABLE achievements (
    user_id TEXT NOT NULL, achievement_id TEXT NOT NULL, unlocked_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, achievement_id)
);
CREATE TABLE expeditions (
    user_id TEXT PRIMARY KEY, expedition_id TEXT NOT NULL,
    started_at INTEGER NOT NULL, ends_at INTEGER NOT NULL, claimed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE shop_purchases (
    user_id TEXT NOT NULL, shop_bucket TEXT NOT NULL, offer_key TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, shop_bucket, offer_key)
);
CREATE TABLE world_boss (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tier INTEGER NOT NULL, boss_id TEXT NOT NULL,
    name TEXT NOT NULL, max_hp INTEGER NOT NULL, current_hp INTEGER NOT NULL,
    atk INTEGER NOT NULL, def_ INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active',
    spawned_at INTEGER NOT NULL, defeated_at INTEGER, killer_user_id TEXT
);
CREATE TABLE world_boss_damage (
    boss_instance_id INTEGER NOT NULL, user_id TEXT NOT NULL, display_name TEXT NOT NULL,
    total_damage INTEGER NOT NULL DEFAULT 0, attacks_count INTEGER NOT NULL DEFAULT 0,
    last_attack_at INTEGER NOT NULL, PRIMARY KEY (boss_instance_id, user_id)
);
"""


def test_v1_to_v2_migration_preserves_legacy_saves_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_v1.db"
    now = 1_700_000_000
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(_LEGACY_V1_DDL)
        conn.execute("INSERT INTO rpg_meta (key, value) VALUES ('schema_version', '1')")
        conn.execute("INSERT INTO rpg_meta (key, value) VALUES ('save_seq', '17')")
        conn.execute("INSERT INTO rpg_meta (key, value) VALUES ('updated_at', ?)", (str(now),))
        conn.execute(
            """
            INSERT INTO players (
                user_id, display_name, class_id, promo_tier, level, exp, rebirth_count,
                gold, gems, stamina, stamina_updated_at, abyss_highest, active_title,
                combat_power, created_at, updated_at
            ) VALUES ('1001', 'LegacyKirito', 'swordsman', 2, 42, 900, 1, 12345, 99, 100, ?, 35, '⚔️ 拓荒者', 8888, ?, ?)
            """,
            (now, now, now),
        )
        conn.execute(
            """
            INSERT INTO players (
                user_id, display_name, class_id, promo_tier, level, exp, rebirth_count,
                gold, gems, stamina, stamina_updated_at, abyss_highest, active_title,
                combat_power, created_at, updated_at
            ) VALUES ('1002', 'LegacyHeath', 'paladin', 3, 88, 5000, 2, 99999, 250, 120, ?, 75, '🛡️ 聖光守護者', 44444, ?, ?)
            """,
            (now, now, now),
        )
        for idx, (uid, slot, eq, locked) in enumerate(
            [
                ("1001", "weapon", 1, 1),
                ("1001", "accessory", 1, 0),
                ("1002", "armor", 1, 1),
                ("1002", "helmet", 0, 0),
            ],
            start=1,
        ):
            conn.execute(
                """
                INSERT INTO equipment (
                    user_id, template_id, name, slot, rarity, tier, set_id,
                    enhance_level, base_hp, base_mp, base_atk, base_def,
                    affixes_json, is_equipped, is_locked, created_at
                ) VALUES (?, ?, ?, ?, 'epic', 3, 'pioneer', 7, 100, 20, 50, 30, '{"atk_pct": 0.08}', ?, ?, ?)
                """,
                (uid, f"tpl_{idx}", f"遺產裝備{idx}", slot, eq, locked, now),
            )
        conn.execute("INSERT INTO inventory (user_id, item_id, quantity) VALUES ('1001', 'enhance_stone', 15)")
        conn.execute(
            "INSERT INTO expeditions (user_id, expedition_id, started_at, ends_at, claimed) "
            "VALUES ('1001', 'forest_patrol', ?, ?, 0)",
            (now, now + 1800),
        )
        conn.execute(
            "INSERT INTO world_boss (tier, boss_id, name, max_hp, current_hp, atk, def_, status, spawned_at) "
            "VALUES (3, 'abyss_wyrm', '深淵魔龍', 50000, 42000, 200, 80, 'active', ?)",
            (now,),
        )
        conn.commit()

    # First open -> runs v1 -> v2 migration
    db = RPGDatabase(db_path)
    try:
        assert db.get_schema_version() == 2
        assert db.save_seq == 17  # Migration MUST NOT drift save_seq!

        p1 = db.get_player("1001")
        p2 = db.get_player("1002")
        assert p1 is not None and p2 is not None
        assert p1.display_name == "LegacyKirito" and p1.level == 42 and p1.gold == 12345 and p1.col == 12345
        assert p1.weapon_style == "sword" and p1.highest_cleared_floor == 35
        assert p1.current_floor == 1 and p1.zone == "town" and p1.cursor_color == "green" and p1.game_mode == "standard"
        assert p1.str_stat == 5 and p1.luk_stat == 5
        assert p2.weapon_style == "holy" and p2.highest_cleared_floor == 75 and p2.equipped_title == "🛡️ 聖光守護者"

        assert len(db.get_equipment("1001")) == 2
        assert len(db.get_equipment("1002")) == 2
        assert db.get_item_qty("1001", "enhance_stone") == 15
        exp_row = db.get_expedition("1001")
        assert exp_row is not None and exp_row.expedition_id == "forest_patrol"
        wb = db.get_active_world_boss()
        assert wb is not None and wb.current_hp == 42000 and wb.floor == 1

        # Verify all 22 new v2 tables exist (33 total)
        with sqlite3.connect(str(db_path)) as chk:
            tables = {
                r[0]
                for r in chk.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
        expected_v2_tables = {
            "pending_loot",
            "tower_progress",
            "server_floor_clears",
            "floor_exploration",
            "player_mastery",
            "player_talents",
            "gear_loadouts",
            "monument_of_life",
            "boss_intel_seen",
            "yui_logs",
            "parties",
            "party_members",
            "raid_history",
            "guilds",
            "guild_members",
            "guild_warehouse",
            "guild_logs",
            "guild_quests",
            "market_listings",
            "achievement_turnins",
            "duel_records",
            "world_buffs",
        }
        assert expected_v2_tables.issubset(tables)
        assert len(tables) == 33
    finally:
        db.close()

    # Second open -> proves 100% idempotent migration
    db2 = RPGDatabase(db_path)
    try:
        assert db2.get_schema_version() == 2
        assert db2.save_seq == 17
        assert db2.get_player_count() == 2
    finally:
        db2.close()


def test_nested_transaction_rollback_and_save_seq_monotonicity(tmp_path: Path) -> None:
    db = RPGDatabase(tmp_path / "tx.db")
    try:
        assert db.save_seq == 0
        now = int(time.time())
        db.create_player("u1", "Kirito", "swordsman", now)
        seq_after_create = db.save_seq
        assert seq_after_create == 1

        with pytest.raises(RuntimeError, match="forced failure"), db.transaction():
            db.add_item("u1", "healing_crystal", 5)
            with db.transaction():
                db.add_item("u1", "teleport_crystal", 3)
                raise RuntimeError("forced failure")

        # Zero partial writes & save_seq unchanged
        assert db.get_item_qty("u1", "healing_crystal") == 0
        assert db.get_item_qty("u1", "teleport_crystal") == 0
        assert db.save_seq == seq_after_create

        db.add_item("u1", "healing_crystal", 2)
        assert db.get_item_qty("u1", "healing_crystal") == 2
        assert db.save_seq == seq_after_create + 1
    finally:
        db.close()


def test_gzip_snapshot_export_import_anti_rollback_and_corrupt_rejection(tmp_path: Path) -> None:
    src = RPGDatabase(tmp_path / "src.db")
    dst = RPGDatabase(tmp_path / "dst.db")
    try:
        now = int(time.time())
        src.create_player("u1", "Asuna", "ranger", now)
        seq_old, snap_old = src.export_gzip_snapshot()
        assert seq_old >= 1

        src.add_item("u1", "s_rank_ragout_rabbit", 4)
        src.unlock_yui_log("u1", "yui_log_f01", now)
        seq_new = src.save_seq
        snap_new = src.export_snapshot_bytes()
        assert seq_new > seq_old

        # Restore newer snapshot onto empty destination
        assert dst.import_snapshot_bytes(snap_new) is True
        assert dst.save_seq == seq_new
        assert dst.get_item_qty("u1", "s_rank_ragout_rabbit") == 4
        assert "yui_log_f01" in dst.get_yui_logs("u1")

        # Anti-rollback: older snapshot MUST be rejected
        assert dst.import_gzip_snapshot(snap_old, force=False) is False
        assert dst.save_seq == seq_new
        assert dst.get_item_qty("u1", "s_rank_ragout_rabbit") == 4

        # Corrupt bytes / truncated gzip / non-SQLite gzipped payload MUST fail safely
        assert dst.import_gzip_snapshot(b"not-valid-gzip") is False
        assert dst.import_gzip_snapshot(snap_new[:24]) is False
        assert dst.import_gzip_snapshot(gzip.compress(b"plain text not sqlite")) is False
        # Live DB connection stays healthy
        assert dst.get_player_count() == 1
        assert dst.get_item_qty("u1", "s_rank_ragout_rabbit") == 4

        # Local backup rotation (keep=2)
        for i in range(4):
            src.add_item("u1", "boar_meat", 1)
            bk = src.create_local_backup(keep=2)
            assert bk is not None and bk.exists()
            # Ensure distinct mtimes for deterministic pruning
            if i < 3:
                time.sleep(0.02)
        backups = list(src.backup_dir.glob("rpg_backup_*.db"))
        assert len(backups) <= 2
    finally:
        src.close()
        dst.close()


def test_concurrent_first_kill_pk_contention_threadpool(tmp_path: Path) -> None:
    db_path = tmp_path / "fk_race.db"
    db = RPGDatabase(db_path)
    try:
        barrier = threading.Barrier(8)
        now = int(time.time())

        def attempt_claim(idx: int) -> bool:
            barrier.wait()
            return db.claim_floor_first_kill(
                floor=10,
                boss_id="kagachi_samurai_lord",
                boss_name="武士領主・加賀智",
                leader_id=f"u{idx}",
                leader_name=f"Player{idx}",
                la_user_id=f"u{idx}",
                la_user_name=f"Player{idx}",
                participant_ids=[f"u{idx}"],
                cleared_at=now,
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt_claim, range(8)))

        assert results.count(True) == 1
        assert results.count(False) == 7
        record = db.get_server_floor_clear(10)
        assert record is not None and record["boss_id"] == "kagachi_samurai_lord"
        assert db.get_server_frontline_floor() == 11

        # Dual-connection multi-thread contention on Floor 50
        db_conn2 = RPGDatabase(db_path)
        try:
            barrier2 = threading.Barrier(4)

            def dual_attempt(idx: int) -> bool:
                target = db if idx % 2 == 0 else db_conn2
                barrier2.wait()
                return target.claim_server_floor_first_kill(
                    floor=50,
                    boss_id="steel_arbiter_algade",
                    boss_name="鋼鐵審判官",
                    leader_id=f"p{idx}",
                    leader_name=f"Clearer{idx}",
                    la_user_id=f"p{idx}",
                    la_user_name=f"Clearer{idx}",
                    participant_ids=[f"p{idx}"],
                    cleared_at=now,
                )

            with ThreadPoolExecutor(max_workers=4) as pool:
                res2 = list(pool.map(dual_attempt, range(4)))
            assert res2.count(True) == 1
            assert res2.count(False) == 3
        finally:
            db_conn2.close()
    finally:
        db.close()


def test_concurrent_marketplace_buy_race_threadpool(tmp_path: Path) -> None:
    db = RPGDatabase(tmp_path / "market_race.db")
    try:
        now = int(time.time())
        seller = db.create_player("seller", "Agil", "swordsman", now)
        seller.col = 500
        db.save_player(seller)

        eq = db.add_equipment(
            EquipmentItem(
                id=0,
                user_id="seller",
                template_id="t5_sword",
                name="阿爾格特秘銀刃",
                slot="weapon",
                rarity="rare",
                tier=5,
                set_id="",
                enhance_level=5,
                enhance_pity=0,
                base_hp=100,
                base_mp=20,
                base_atk=180,
                base_def=10,
                affixes={"atk_pct": 0.1, "res_slash": 0.05},
                weapon_style="sword",
                damage_type="slash",
                created_at=now,
            )
        )
        listing = db.create_market_listing(
            "seller",
            "Agil",
            item_type="equipment",
            equipment_id=eq.id,
            item_name=eq.name,
            slot=eq.slot,
            weapon_style=eq.weapon_style,
            rarity=eq.rarity,
            affix_keys=list(eq.affixes.keys()),
            price_col=1500,
            now_ts=now,
        )
        # Escrowed item is hidden from seller's active bag
        assert db.get_equipment("seller") == []

        for idx in range(8):
            buyer = db.create_player(f"buyer_{idx}", f"Buyer{idx}", "swordsman", now)
            buyer.col = 10_000
            db.save_player(buyer)

        barrier = threading.Barrier(8)

        def try_buy(idx: int) -> tuple[str, bool]:
            uid = f"buyer_{idx}"
            barrier.wait()
            try:
                db.buy_market_listing(listing.id, uid, now + 5)
                return uid, True
            except GameError:
                return uid, False

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(try_buy, range(8)))

        winners = [uid for uid, ok in outcomes if ok]
        losers = [uid for uid, ok in outcomes if not ok]
        assert len(winners) == 1
        assert len(losers) == 7

        winner_id = winners[0]
        seller_after = db.get_player("seller")
        winner_after = db.get_player(winner_id)
        assert seller_after is not None and seller_after.col == 2000
        assert winner_after is not None and winner_after.col == 8500

        winner_gear = db.get_equipment(winner_id)
        assert len(winner_gear) == 1 and winner_gear[0].id == eq.id
        for loser_id in losers:
            lp = db.get_player(loser_id)
            assert lp is not None and lp.col == 10_000
            assert db.get_equipment(loser_id) == []
    finally:
        db.close()


def test_pending_loot_mailbox_overflow_and_atomic_single_claim(tmp_path: Path) -> None:
    db = RPGDatabase(tmp_path / "mailbox.db")
    try:
        now = int(time.time())
        db.create_player("u1", "Kirito", "swordsman", now)
        loot_id = db.enqueue_pending_loot(
            user_id="u1",
            source="F50 LA Bonus",
            item_type="equipment",
            payload={"named_item_id": "elucidator", "name": "闡釋者"},
            now_ts=now,
        )
        unclaimed = db.get_pending_loot("u1", unclaimed_only=True)
        assert len(unclaimed) == 1 and unclaimed[0]["id"] == loot_id

        barrier = threading.Barrier(8)

        def try_claim(_: int) -> dict[str, Any] | None:
            barrier.wait()
            return db.claim_pending_loot_entry("u1", loot_id, now + 10)

        with ThreadPoolExecutor(max_workers=8) as pool:
            claimed_results = list(pool.map(try_claim, range(8)))

        non_none = [r for r in claimed_results if r is not None]
        assert len(non_none) == 1
        assert non_none[0]["payload"]["named_item_id"] == "elucidator"
        assert db.get_pending_loot("u1", unclaimed_only=True) == []
    finally:
        db.close()


# =============================================================================
# Group 3: Pure Stats Engine & Zero-Discord Import Purity
# =============================================================================
def test_pure_modules_have_zero_discord_imports() -> None:
    pure_files = [
        REPO_ROOT / "src/rpg/systems/stats.py",
        REPO_ROOT / "src/rpg/models.py",
        REPO_ROOT / "src/rpg/content/loader.py",
        REPO_ROOT / "src/rpg/assets.py",
    ]
    for path in pure_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("discord"), f"Forbidden discord import in {path}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("discord"), f"Forbidden discord import in {path}"

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, src.rpg.systems.stats; assert 'discord' not in sys.modules",
        ],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_floor_resistance_penetration_and_75pct_cap() -> None:
    bundle = load_and_validate_all()
    assert floor_resistance_penetration(0) == 0.0
    assert floor_resistance_penetration(1) == pytest.approx(0.0065)
    assert floor_resistance_penetration(50) == pytest.approx(0.325)
    assert floor_resistance_penetration(100) == pytest.approx(0.65)
    assert floor_resistance_penetration(150) == pytest.approx(0.65)

    assert effective_resistance(float("nan"), 10) == 0.0
    assert effective_resistance(float("inf"), 10) == 0.0
    assert effective_resistance(1.40, 100) == effective_resistance(0.75, 100)

    player = PlayerProfile(user_id="p1", display_name="Tank", weapon_style="mace")
    overcapped_armor = EquipmentItem(
        id=1,
        user_id="p1",
        template_id="overcap_armor",
        name="超限重鎧",
        slot="armor",
        rarity="legendary",
        tier=10,
        set_id="",
        enhance_level=0,
        enhance_pity=0,
        base_hp=100,
        base_mp=0,
        base_atk=0,
        base_def=50,
        affixes={"res_slash": 1.20},
    )
    stats = compute_player_stats(player, [overcapped_armor], bundle, floor=1)
    assert stats.res_slash == pytest.approx(0.75)
    assert stats.effective_res("slash", floor=1) == pytest.approx(0.75 * (1.0 - 0.0065))
    assert stats.effective_res("slash", floor=100) == pytest.approx(0.75 * 0.35)
    assert stats.effective_res("slash", floor=150) == stats.effective_res("slash", floor=100)

    with pytest.raises(GameError) as exc_info:
        stats.effective_res("magic", floor=1)
    assert isinstance(exc_info.value, ValueError)
    assert exc_info.value.code == "INVALID_DAMAGE_TYPE"


def test_stats_level_allocation_enhancement_sets_buffs_guild_turnin_rebirth() -> None:
    bundle = load_and_validate_all()

    base_player = PlayerProfile(
        user_id="p1",
        display_name="Kirito",
        level=1,
        str_stat=5,
        agi_stat=5,
        vit_stat=5,
        dex_stat=5,
        luk_stat=5,
        weapon_style="sword",
    )
    s_base = compute_player_stats(base_player, [], bundle, floor=1)

    # Stat allocation (also verify duck-typed stat_str..stat_luk support!)
    allocated = SimpleNamespace(
        level=10,
        rebirth_count=0,
        stat_str=25,
        stat_agi=20,
        stat_vit=20,
        stat_dex=18,
        stat_luk=15,
        weapon_style="sword",
        unique_skills=[],
    )
    s_alloc = compute_player_stats(allocated, [], bundle, floor=10)
    assert s_alloc.atk > s_base.atk
    assert s_alloc.spd > s_base.spd
    assert s_alloc.evasion > s_base.evasion
    assert s_alloc.max_hp > s_base.max_hp
    assert s_alloc.defense > s_base.defense
    assert s_alloc.crit_rate > s_base.crit_rate
    assert s_alloc.max_sp > s_base.max_sp
    assert s_alloc.drop_bonus > s_base.drop_bonus
    assert s_alloc.combat_power > s_base.combat_power

    # Enhancement milestones (+0, +5, +10, +15)
    def make_piece(slot: str, enh: int, set_id: str = "") -> EquipmentItem:
        return EquipmentItem(
            id=1,
            user_id="p1",
            template_id=f"tpl_{slot}",
            name=f"裝_{slot}",
            slot=slot,
            rarity="set" if set_id else "rare",
            tier=5,
            set_id=set_id,
            enhance_level=enh,
            enhance_pity=0,
            base_hp=100,
            base_mp=20,
            base_atk=100,
            base_def=50,
            affixes={},
        )

    assert make_piece("weapon", 0).enhance_multiplier() == pytest.approx(1.00)
    assert make_piece("weapon", 5).enhance_multiplier() == pytest.approx(1.60)
    assert make_piece("weapon", 10).enhance_multiplier() == pytest.approx(2.30)
    assert make_piece("weapon", 15).enhance_multiplier() == pytest.approx(3.15)
    assert (
        compute_player_stats(base_player, [make_piece("weapon", 15)], bundle).atk
        > compute_player_stats(base_player, [make_piece("weapon", 10)], bundle).atk
        > compute_player_stats(base_player, [make_piece("weapon", 5)], bundle).atk
        > compute_player_stats(base_player, [make_piece("weapon", 0)], bundle).atk
    )

    # 2pc & 4pc JSON string-key Set bonuses
    set_2 = [make_piece("helmet", 0, "black_swordsman"), make_piece("armor", 0, "black_swordsman")]
    set_4 = set_2 + [
        make_piece("gloves", 0, "black_swordsman"),
        make_piece("boots", 0, "black_swordsman"),
    ]
    s_2pc = compute_player_stats(base_player, set_2, bundle)
    s_4pc = compute_player_stats(base_player, set_4, bundle)
    assert any("黑色劍士套裝 (2件)" in s for s in s_2pc.active_sets)
    assert any("黑色劍士套裝 (4件)" in s for s in s_4pc.active_sets)
    assert s_4pc.crit_dmg > s_2pc.crit_dmg and s_4pc.skill_dmg_bonus > s_2pc.skill_dmg_bonus

    # Active buffs, guild buff, turn-in bonuses & rebirth scaling (non-mutating)
    buffs_input = {"dish": {"atk_pct": 0.15, "res_dragon": 0.12}}
    guild_input = {"active": True, "bonuses": {"dmg_reduction": 0.08, "evasion": 0.05}}
    turnin_input = {"hp_flat": 250.0, "atk_flat": 40.0, "res_slash": 0.06}
    s_buffed = compute_player_stats(
        base_player,
        set_4,
        bundle,
        active_buffs=buffs_input,
        guild_buff=guild_input,
        turnin_bonuses=turnin_input,
    )
    assert s_buffed.combat_power > s_4pc.combat_power
    assert s_buffed.res_dragon >= 0.12
    assert s_buffed.dmg_reduction >= 0.08
    assert buffs_input == {"dish": {"atk_pct": 0.15, "res_dragon": 0.12}}

    rebirth_player = copy.deepcopy(base_player)
    rebirth_player.rebirth_count = 2
    s_rebirth = compute_player_stats(rebirth_player, set_4, bundle)
    assert s_rebirth.atk > s_4pc.atk and s_rebirth.max_hp > s_4pc.max_hp
    assert s_rebirth.exp_bonus > s_4pc.exp_bonus


def test_weapon_style_passives_all_8_styles_and_2_unique_skills() -> None:
    bundle = load_and_validate_all()
    for style in VALID_WEAPON_CLASSES:
        p = compute_weapon_style_passives(style, [], bundle)
        assert p["style"] == style
        assert p["dmg_type"] in VALID_DAMAGE_TYPES
        assert p["max_skill_slots"] == 3

    shield = EquipmentItem(
        id=10,
        user_id="p1",
        template_id="iron_shield",
        name="精鋼盾牌",
        slot="offhand",
        rarity="rare",
        tier=3,
        set_id="",
        enhance_level=0,
        enhance_pity=0,
        base_hp=100,
        base_mp=0,
        base_atk=0,
        base_def=40,
        affixes={},
    )
    offhand_sword = EquipmentItem(
        id=11,
        user_id="p1",
        template_id="dark_repulser",
        name="逐闇者",
        slot="offhand",
        rarity="named",
        tier=6,
        set_id="",
        enhance_level=0,
        enhance_pity=0,
        base_hp=100,
        base_mp=0,
        base_atk=200,
        base_def=10,
        affixes={},
    )

    # Mace + Shield has ZERO speed penalty vs Sword + Shield (-8 SPD penalty)
    mace_player = PlayerProfile(user_id="m1", weapon_style="mace")
    sword_player = PlayerProfile(user_id="s1", weapon_style="sword")
    s_mace_bare = compute_player_stats(mace_player, [], bundle)
    s_mace_shield = compute_player_stats(mace_player, [shield], bundle)
    s_sword_bare = compute_player_stats(sword_player, [], bundle)
    s_sword_shield = compute_player_stats(sword_player, [shield], bundle)
    assert s_mace_shield.spd >= s_mace_bare.spd
    assert s_sword_shield.spd == s_sword_bare.spd - 8

    # Dual Blades unlocks 4 skill slots & extra ATK/CRIT with offhand weapon
    db_player = PlayerProfile(user_id="k1", weapon_style="sword", unique_skills=["dual_blades"])
    db_passives = compute_weapon_style_passives(
        "sword", [offhand_sword], bundle, unique_skills=["dual_blades"]
    )
    assert db_passives["max_skill_slots"] == 4
    s_db_no_off = compute_player_stats(db_player, [], bundle)
    s_db_with_off = compute_player_stats(db_player, [offhand_sword], bundle)
    assert s_db_with_off.atk > s_db_no_off.atk and s_db_with_off.crit_rate > s_db_no_off.crit_rate

    # Holy Sword unlocks 4 skill slots & increases all 4 resistances + dmg_reduction
    hs_player = PlayerProfile(user_id="h1", weapon_style="holy", unique_skills=["holy_sword"])
    s_holy_plain = compute_player_stats(PlayerProfile(user_id="h0", weapon_style="holy"), [shield], bundle)
    s_holy_unique = compute_player_stats(hs_player, [shield], bundle)
    assert s_holy_unique.active_passives["max_skill_slots"] == 4
    assert s_holy_unique.dmg_reduction > s_holy_plain.dmg_reduction
    assert s_holy_unique.res_slash > s_holy_plain.res_slash
    assert s_holy_unique.res_dragon > s_holy_plain.res_dragon


# =============================================================================
# Group 4: Assets CDN Registry, data.py Facade & .gitignore Hygiene
# =============================================================================
def test_assets_registry_all_sao_and_legacy_raster_urls_zero_svg() -> None:
    urls = assets.all_asset_urls()
    assert len(urls) >= 120
    prefix = f"https://raw.githubusercontent.com/wesnoth/wesnoth/{assets.WESNOTH_COMMIT}/"
    for url in urls:
        assert url.startswith(prefix)
        assert ".svg" not in url.lower()
        assert url.lower().endswith((".png", ".webp", ".jpg", ".jpeg"))

    # 10 biome banners (keys & int tiers 1..10)
    for tier in range(1, 11):
        assert assets.get_biome_banner_url(tier).startswith(prefix)
    for key in assets.BIOME_BANNERS:
        assert assets.get_biome_banner_url(key).startswith(prefix)

    # 14 milestone bosses + 10 tier guardians
    for floor in MILESTONE_BOSS_FLOORS:
        assert assets.get_sao_boss_portrait_url("", floor=floor).startswith(prefix)
    for t in range(1, 11):
        assert assets.get_sao_boss_portrait_url(f"tier_{t}_guardian").startswith(prefix)

    # 8 weapon styles + 2 unique skills
    for style in VALID_WEAPON_CLASSES | VALID_UNIQUE_SKILLS:
        assert assets.get_weapon_style_icon_url(style).startswith(prefix)
        assert assets.get_weapon_style_portrait_url(style).startswith(prefix)

    # 8 SAO slots + legacy accessory across tiers 1..10
    for tier in range(1, 11):
        for slot in (*VALID_SLOTS, "accessory"):
            assert assets.get_equipment_image_url(tier, slot).startswith(prefix)

    # 4 crystals, chests + mimic + trap, mob categories, SAO UI banners
    for cid in REQUIRED_SAO_CRYSTALS:
        assert assets.get_crystal_icon_url(cid).startswith(prefix)
    for chest_key in ("wooden", "iron", "silver", "gold", "boss_relic", "named_vault", "mimic", "crystal_null_trap"):
        assert assets.get_chest_icon_url(chest_key).startswith(prefix)
    for mob_cat in ("beast", "undead", "dragon", "demon", "mimic", "boss_field"):
        assert assets.get_mob_portrait_url(mob_cat).startswith(prefix)
    for banner_key in (
        "aincrad_welcome_banner",
        "town_safe_zone_banner",
        "monument_of_life_banner",
        "argo_intel_banner",
        "yui_console_banner",
        "guild_hall_banner",
        "market_banner",
    ):
        assert assets.get_ui_asset_url(banner_key).startswith(prefix)


def test_data_py_legacy_and_sao_facade_compatibility() -> None:
    # Legacy symbols intact
    assert data.MAX_LEVEL == 100
    assert data.RARITY_ORDER == ["common", "uncommon", "rare", "epic", "legendary", "mythic"]
    assert len(data.SLOT_ORDER) == 6
    assert "pioneer" in data.EQUIPMENT_SETS

    # SAO facade symbols active & backed by loader
    assert len(data.SAO_WEAPON_CLASSES) == 8
    assert len(data.SAO_UNIQUE_SKILLS) == 2
    assert data.get_floor_config(1)["boss_id"] == "illfang_kobold_lord"
    assert data.get_boss_spec("gleam_eyes") is not None
    assert data.get_sword_skill("starburst_stream") is not None
    assert data.get_sao_item("teleport_crystal") is not None
    assert data.get_weapon_class("dual_blades") is not None
    assert data.get_sao_rarity("named") is not None

    # Dual formatting / title resolution
    assert "龍息抗性" in data.format_affix("res_dragon", 0.08)
    assert "攻擊力" in data.format_affix("atk_pct", 0.10)
    assert data.get_class_title("katana", 1) == "太刀"
    assert data.get_class_title("swordsman", 2) == "烈焰劍聖"
    assert data.get_class_title("swordsman", 3) == "星辰劍帝"


def test_gitignore_hygiene_with_git_check_ignore() -> None:
    should_ignore = [
        ".agents/test",
        "data/rpg.db",
        ".env.local",
        ".mypy_cache/a",
        ".ruff_cache/a",
        "htmlcov/index.html",
        ".coverage.1",
        "test.sqlite",
        "test.sqlite3",
    ]
    for path in should_ignore:
        res = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path],
            cwd=str(REPO_ROOT),
            check=False,
        )
        assert res.returncode == 0, f"Expected '{path}' to be gitignored (exit 0), got {res.returncode}"

    should_not_ignore = [
        ".env.example",
        "src/rpg/content/biomes.json",
        "src/rpg/data/foo.json",
    ]
    for path in should_not_ignore:
        res = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path],
            cwd=str(REPO_ROOT),
            check=False,
        )
        assert res.returncode == 1, f"Expected '{path}' NOT to be gitignored (exit 1), got {res.returncode}"


# =============================================================================
# Group 5: Round 2 Expanded Catalog, 5-Axis Model/DB/Stats & Domain Purity
# =============================================================================
def test_r2_expanded_content_catalog_and_assets() -> None:
    bundle = load_and_validate_all(force_reload=True)

    # Hard backward-compatibility counts preserved
    assert len(bundle.bosses) == 34
    assert len(bundle.monsters) == 77
    assert len(bundle.sword_skills) == 34
    assert len(bundle.chests_loot["chest_tiers"]) == 6

    # Round 2 catalog expansions
    weq = bundle.weapons_equipment
    assert len(weq["named_items"]) == 30
    assert len(bundle.items_crystals) == 105
    assert len(bundle.recipes["blacksmithing"]) == 22
    assert len(bundle.recipes["fusion"]) == 10

    # Style-authentic weapon names & non-shield offhand names across all 10 tiers
    for tier_idx in range(1, 11):
        bg = weq["base_gear"][str(tier_idx)]
        assert set(bg["weapon_style_names"].keys()) == VALID_WEAPON_CLASSES
        assert bg.get("offhand_weapon_names")

    # New Round 2 items present and have valid non-SVG pinned Wesnoth CDN asset URLs
    prefix = f"https://raw.githubusercontent.com/wesnoth/wesnoth/{assets.WESNOTH_COMMIT}/"
    socket_ids = [iid for iid, spec in bundle.items_crystals.items() if spec.get("category") == "socket_crystal"]
    assert len(socket_ids) == 8
    for req_id in (
        "forge_scrap",
        "expand_stone",
        "gear_supply_crate_t1",
        "gear_supply_crate_t2",
        "gear_supply_crate_t3",
        *socket_ids,
    ):
        assert req_id in bundle.items_crystals
        akey = bundle.items_crystals[req_id].get("asset_key", "")
        resolved = assets.resolve_asset_key(akey)
        assert resolved is not None and resolved.startswith(prefix)
        assert ".svg" not in resolved.lower()

    for nspec in weq["named_items"].values():
        resolved = assets.resolve_asset_key(nspec["asset_key"])
        assert resolved is not None and resolved.startswith(prefix)
        assert ".svg" not in resolved.lower()


def test_r2_equipment_temper_socket_persistence_and_stats(tmp_path: Path) -> None:
    bundle = load_and_validate_all()
    db_path = tmp_path / "r2_persist.db"
    db = RPGDatabase(db_path)
    try:
        now = int(time.time())
        player = db.create_player("u_r2", "LisbethTester", "sword", now)
        eq = db.add_equipment(
            EquipmentItem(
                id=0,
                user_id="u_r2",
                template_id="tpl_sword",
                name="青銅長劍",
                slot="weapon",
                rarity="plain",
                tier=1,
                set_id="",
                enhance_level=0,
                enhance_pity=0,
                base_hp=40,
                base_mp=10,
                base_atk=100,
                base_def=20,
                affixes={"atk_pct": 0.05},
                weapon_style="sword",
                damage_type="slash",
                is_equipped=True,
                created_at=now,
            )
        )
        # Verify exact temper_multiplier() and enhance_multiplier() formulas
        assert eq.enhance_multiplier() == pytest.approx(1.00)
        assert eq.temper_multiplier() == pytest.approx(1.00)
        s0 = compute_player_stats(player, [eq], bundle)

        eq.name = "秘銀星輝劍"
        eq.rarity = "rare"
        eq.tier = 3
        eq.base_atk = 180
        eq.temper_level = 3
        eq.socket_crystal_id = "socket_crystal_crimson"
        assert eq.temper_multiplier() == pytest.approx(1.36)
        s3 = compute_player_stats(player, [eq], bundle)
        assert s3.atk > s0.atk
        assert s3.crit_rate >= s0.crit_rate + 0.03 - 1e-6
        assert s3.res_slash >= s0.res_slash + 0.03 - 1e-6

        eq.temper_level = 5
        assert eq.temper_multiplier() == pytest.approx(1.60)
        s5 = compute_player_stats(player, [eq], bundle)
        assert s5.skill_dmg_bonus >= s3.skill_dmg_bonus + 0.08 - 1e-6
        assert s5.dmg_reduction >= s3.dmg_reduction + 0.05 - 1e-6

        db.update_equipment(eq)
    finally:
        db.close()

    # Reopen DB to verify full persistence of all Round 2 columns & mutated metadata
    db2 = RPGDatabase(db_path)
    try:
        reloaded = db2.get_equipment("u_r2")
        assert len(reloaded) == 1
        r = reloaded[0]
        assert r.name == "秘銀星輝劍"
        assert r.rarity == "rare"
        assert r.tier == 3
        assert r.base_atk == 180
        assert r.temper_level == 5
        assert r.socket_crystal_id == "socket_crystal_crimson"
    finally:
        db2.close()


def test_r2_all_pure_domain_modules_zero_discord_imports() -> None:
    strict_pure_paths = [
        REPO_ROOT / "src/rpg/models.py",
        REPO_ROOT / "src/rpg/engine.py",
        REPO_ROOT / "src/rpg/data.py",
        REPO_ROOT / "src/rpg/assets.py",
        *(REPO_ROOT / "src/rpg/content").glob("*.py"),
        *(REPO_ROOT / "src/rpg/systems").glob("*.py"),
    ]
    for path in strict_pure_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("discord"), f"Forbidden discord import in {path}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("discord"), f"Forbidden discord import in {path}"

    # Top-level database.py must also have zero discord imports
    db_path = REPO_ROOT / "src/rpg/database.py"
    db_tree = ast.parse(db_path.read_text(encoding="utf-8"), filename=str(db_path))
    for stmt in db_tree.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                assert not alias.name.startswith("discord"), "Forbidden top-level discord import in database.py"
        elif isinstance(stmt, ast.ImportFrom) and stmt.module:
            assert not stmt.module.startswith("discord"), "Forbidden top-level discord import in database.py"

