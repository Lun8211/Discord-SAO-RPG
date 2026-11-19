"""Comprehensive test suite for the persistent RPG module."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import bot as bot_module
from src.rpg.assets import (
    all_asset_urls,
    get_abyss_guardian_portrait_url,
    get_class_icon_url,
    get_class_portrait_url,
    get_dungeon_boss_portrait_url,
    get_equipment_image_url,
    get_expedition_banner_url,
    get_item_icon_url,
    get_leaderboard_icon_url,
    get_mine_zone_banner_url,
    get_pickaxe_icon_url,
    get_shop_tab_icon_url,
    get_world_boss_portrait_url,
)
from src.rpg.data import (
    CLASSES,
    DUNGEONS,
    EXPEDITIONS,
    GEAR_TIERS,
    ITEMS,
    MAX_LEVEL,
    MINE_ZONES,
    PICKAXES,
    SLOT_ORDER,
    STAMINA_REGEN_SECONDS,
    WORLD_BOSS_POOL,
)
from src.rpg.database import RPGDatabase
from src.rpg.embeds import (
    build_achievements_embed,
    build_bag_embed,
    build_class_embed,
    build_combat_embed,
    build_combat_embeds,
    build_daily_quests_embed,
    build_dungeon_list_embed,
    build_enhance_result_embed,
    build_equipment_card_embed,
    build_expedition_embed,
    build_forge_embed,
    build_help_embed,
    build_leaderboard_embed,
    build_mine_result_embed,
    build_profile_embed,
    build_rebirth_embed,
    build_shop_embed,
    build_welcome_class_embed,
    build_world_boss_embed,
)
from src.rpg.engine import RPGEngine, RPGError


def _make_engine(tmp_path: Path, name: str = "rpg.db") -> tuple[RPGDatabase, RPGEngine]:
    db = RPGDatabase(db_path=str(tmp_path / name))
    engine = RPGEngine(db=db, timezone_offset_hours=8)
    return db, engine


def test_bot_registers_only_rpg_command_group() -> None:
    cmd_names = {cmd.name for cmd in bot_module.bot.tree.get_commands()}
    assert cmd_names == {"rpg"}
    assert "shop" not in cmd_names
    assert "cookie" not in cmd_names

    rpg_group = bot_module.bot.tree.get_command("rpg")
    assert rpg_group is not None
    sub_names = {c.name for c in rpg_group.commands}
    expected_subs = {
        "start",
        "profile",
        "mine",
        "dungeon",
        "abyss",
        "boss",
        "shop",
        "bag",
        "equip",
        "inspect",
        "forge",
        "daily",
        "expedition",
        "leaderboard",
        "achievements",
        "class",
        "rebirth",
        "help",
    }
    assert sub_names == expected_subs
    assert len(sub_names) <= 25


def test_settings_from_env_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import Settings

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TIMEZONE_OFFSET_HOURS", "9")
    monkeypatch.setenv("RPG_DB_PATH", "custom/rpg.db")
    monkeypatch.setenv("RPG_BACKUP_CHANNEL_ID", "123456789012345678")
    monkeypatch.setenv("RPG_BACKUP_INTERVAL_MINUTES", "10")

    s = Settings.from_env()
    assert s.discord_bot_token == "dummy-token"
    assert s.timezone_offset_hours == 9
    assert s.rpg_db_path == "custom/rpg.db"
    assert s.rpg_backup_channel_id == "123456789012345678"
    assert s.rpg_backup_interval_minutes == 10


def test_persistence_across_full_bot_restart(tmp_path: Path) -> None:
    """All player state, gear, ores, clears, expedition, and world boss HP must survive DB close & reopen."""
    db_file = tmp_path / "restart_test.db"
    db1 = RPGDatabase(db_path=str(db_file))
    eng1 = RPGEngine(db1)

    t0 = 1_750_000_000
    p1 = eng1.register_player("1001", "Alice", "swordsman", now_ts=t0)
    assert p1.level == 1
    assert p1.combat_power > 0

    # Mine twice, start expedition, attack world boss, check in daily
    eng1.mine("1001", "Alice", now_ts=t0 + 10)
    eng1.mine("1001", "Alice", now_ts=t0 + 20)
    eng1.daily_checkin("1001", "Alice", now_ts=t0 + 25)
    exp_obj = eng1.start_expedition("1001", "forest_patrol", now_ts=t0 + 30)
    boss_res = eng1.attack_world_boss("1001", "Alice", now_ts=t0 + 35)

    p1_before = eng1.db.get_player("1001")
    inv_before = eng1.db.get_inventory("1001")
    gear_before = eng1.db.get_equipment("1001")
    boss_before = eng1.get_or_spawn_world_boss(t0 + 40)
    assert p1_before is not None
    assert boss_before.current_hp == boss_before.max_hp - boss_res["dealt"]

    # Simulate graceful bot shutdown + local backup
    db1.close()
    assert list((tmp_path / "backups").glob("rpg_backup_*.db"))

    # Simulate brand new bot process reopening the same SQLite DB
    db2 = RPGDatabase(db_path=str(db_file))
    eng2 = RPGEngine(db2)

    p1_after = eng2.db.get_player("1001")
    assert p1_after is not None
    assert p1_after.display_name == "Alice"
    assert p1_after.gold == p1_before.gold
    assert p1_after.gems == p1_before.gems
    assert p1_after.total_mines == 2
    assert p1_after.checkin_streak == 1
    assert eng2.db.get_inventory("1001") == inv_before
    assert len(eng2.db.get_equipment("1001")) == len(gear_before)

    # Expedition persists and can be claimed after duration elapses post-restart!
    exp_after = eng2.db.get_expedition("1001")
    assert exp_after is not None
    assert exp_after.ends_at == exp_obj.ends_at
    claim_res = eng2.claim_expedition("1001", now_ts=exp_after.ends_at + 10)
    assert claim_res["gold"] > 0
    assert eng2.db.get_expedition("1001") is None

    # World Boss HP & player damage contribution survived restart!
    boss_after = eng2.get_or_spawn_world_boss(t0 + 4000)
    assert boss_after.id == boss_before.id
    assert boss_after.current_hp == boss_before.current_hp
    ranks = eng2.db.get_world_boss_rankings(boss_after.id)
    assert ranks[0]["user_id"] == "1001"
    assert ranks[0]["total_damage"] == boss_res["dealt"]
    db2.close()


def test_gzip_snapshot_export_restore_and_stale_guard(tmp_path: Path) -> None:
    """Ephemeral cloud hosts restore from snapshot, while newer local DB rejects stale snapshots."""
    db_src, eng_src = _make_engine(tmp_path, "src.db")
    t0 = 1_750_000_000
    eng_src.register_player("2001", "Bob", "mage", now_ts=t0)
    eng_src.mine("2001", "Bob", now_ts=t0 + 10)
    old_seq, old_snapshot = db_src.export_gzip_snapshot()

    eng_src.mine("2001", "Bob", now_ts=t0 + 20)
    new_seq, new_snapshot = db_src.export_gzip_snapshot()
    assert new_seq > old_seq

    # Fresh empty DB restores newest snapshot cleanly
    db_dst, _ = _make_engine(tmp_path, "dst.db")
    assert db_dst.get_player_count() == 0
    assert db_dst.import_gzip_snapshot(new_snapshot) is True
    assert db_dst.get_player_count() == 1
    p_bob = db_dst.get_player("2001")
    assert p_bob is not None
    assert p_bob.total_mines == 2

    # Attempting to import older snapshot must NOT overwrite newer data
    assert db_dst.import_gzip_snapshot(old_snapshot) is False
    p_bob_still = db_dst.get_player("2001")
    assert p_bob_still is not None
    assert p_bob_still.total_mines == 2

    # Corrupt bytes must fail safely without breaking connection
    assert db_dst.import_gzip_snapshot(b"not-a-gzip") is False
    assert db_dst.get_player_count() == 1
    db_src.close()
    db_dst.close()


def test_discord_channel_backup_and_restore_flow(tmp_path: Path) -> None:
    """Verify async Discord private backup channel upload & restore with mocked channel."""
    db1, eng1 = _make_engine(tmp_path, "cloud1.db")
    eng1.register_player("3001", "Carol", "ranger", now_ts=1_750_000_000)

    stored_messages = []

    class FakeAttachment:
        def __init__(self, filename: str, payload: bytes) -> None:
            self.filename = filename
            self._payload = payload

        async def read(self) -> bytes:
            return self._payload

    class FakeMessage:
        def __init__(self, filename: str, payload: bytes) -> None:
            self.attachments = [FakeAttachment(filename, payload)]

        async def delete(self) -> None:
            pass

    class FakeChannel:
        async def send(self, content: str = "", file=None):
            data = file.fp.read()
            stored_messages.insert(0, FakeMessage(file.filename, data))

        async def history(self, limit: int = 25):
            for m in stored_messages[:limit]:
                yield m

    class FakeClient:
        def __init__(self, ch) -> None:
            self._ch = ch

        def get_channel(self, _cid: int):
            return self._ch

    client = FakeClient(FakeChannel())
    uploaded = asyncio.run(db1.backup_to_discord_channel(client, "999999999"))
    assert uploaded is True
    assert len(stored_messages) == 1

    # Fresh runner restores from fake Discord channel
    db2, _ = _make_engine(tmp_path, "cloud2.db")
    restored = asyncio.run(db2.restore_from_discord_channel(client, "999999999"))
    assert restored is True
    assert db2.get_player("3001") is not None
    assert db2.get_player("3001").display_name == "Carol"
    db1.close()
    db2.close()


def test_stamina_regeneration_and_mining_progression(tmp_path: Path) -> None:
    db, eng = _make_engine(tmp_path)
    t0 = 1_750_000_000
    eng.register_player("4001", "Miner", "paladin", now_ts=t0)

    # First mine spends 5 stamina
    res = eng.mine("4001", now_ts=t0 + 5)
    assert res["player"].stamina == 95
    assert res["combo"] == 1
    assert res["loot"]

    # Immediate re-mine hits cooldown
    with pytest.raises(RPGError, match="等待"):
        eng.mine("4001", now_ts=t0 + 6)

    # Mine after cooldown increases combo
    res2 = eng.mine("4001", now_ts=t0 + 10)
    assert res2["combo"] == 2
    assert res2["player"].stamina == 90

    # After 3 stamina regen intervals, +3 stamina regenerates
    p_regen = eng.require_player("4001", now_ts=t0 + 10 + STAMINA_REGEN_SECONDS * 3)
    assert p_regen.stamina == 93

    # Upgrade pickaxe to T2 once materials & gold are ready
    p_regen.gold += 5000
    db.save_player(p_regen)
    db.add_item("4001", "copper_ore", 30)
    db.add_item("4001", "iron_ore", 20)
    up = eng.upgrade_pickaxe("4001", now_ts=t0 + 1000)
    assert up["new_tier"] == 2
    assert db.get_player("4001").pickaxe_tier == 2
    db.close()


def test_equipment_forge_enhance_pity_protect_lock_and_dismantle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, eng = _make_engine(tmp_path)
    t0 = 1_750_000_000
    p = eng.register_player("5001", "Smith", "swordsman", now_ts=t0)
    p.gold = 500_000
    p.level = 50
    db.save_player(p)
    db.add_item("5001", "iron_ore", 100)
    db.add_item("5001", "silver_ore", 100)
    db.add_item("5001", "enhance_stone", 200)
    db.add_item("5001", "adv_enhance_stone", 100)
    db.add_item("5001", "protect_scroll", 5)

    # Forge T2 armor specifically
    forged = eng.forge_equipment("5001", tier=2, slot="armor", now_ts=t0 + 10)
    eq = forged["item"]
    assert eq.slot == "armor"
    assert eq.tier == 2

    # Equip and enhance safely +1..+5 (100% rate)
    eng.equip_item("5001", eq.id)
    for expected in range(1, 6):
        res = eng.enhance_equipment("5001", eq.id, now_ts=t0 + 20 + expected)
        assert res["success"] is True
        assert res["new_level"] == expected

    # Force failure at +11 with protect scroll: must NOT downgrade and must build pity
    eq_loaded = db.get_equipment_by_id("5001", eq.id)
    assert eq_loaded is not None
    eq_loaded.enhance_level = 11
    db.update_equipment(eq_loaded)

    monkeypatch.setattr("src.rpg.engine.random.random", lambda: 0.999)
    fail_prot = eng.enhance_equipment("5001", eq.id, use_protect=True, now_ts=t0 + 100)
    assert fail_prot["success"] is False
    assert fail_prot["downgraded"] is False
    assert fail_prot["used_protect"] is True
    assert fail_prot["item"].enhance_level == 11
    assert fail_prot["item"].enhance_pity > 0

    # At 100 pity, enhancement is guaranteed even with high roll
    eq_pity = db.get_equipment_by_id("5001", eq.id)
    eq_pity.enhance_pity = 100
    db.update_equipment(eq_pity)
    pity_win = eng.enhance_equipment("5001", eq.id, now_ts=t0 + 110)
    assert pity_win["success"] is True
    assert pity_win["new_level"] == 12

    # Test lock protects from bulk dismantle
    extra_unlocked = eng._build_equipment_obj("5001", tier=1, slot="boots", rarity="common", now_ts=t0)
    extra_unlocked.is_locked = False
    extra_unlocked = db.add_equipment(extra_unlocked)

    extra_locked = eng._build_equipment_obj("5001", tier=1, slot="gloves", rarity="common", now_ts=t0)
    extra_locked.is_locked = True
    extra_locked = db.add_equipment(extra_locked)

    dis = eng.bulk_dismantle("5001", max_rarity="rare")
    assert dis["count"] == 1
    assert db.get_equipment_by_id("5001", extra_unlocked.id) is None
    assert db.get_equipment_by_id("5001", extra_locked.id) is not None
    db.close()


def test_dungeon_combat_auto_sweep_and_endless_abyss(tmp_path: Path) -> None:
    db, eng = _make_engine(tmp_path)
    t0 = 1_750_000_000
    p = eng.register_player("6001", "Hero", "swordsman", now_ts=t0)
    p.level = 15
    p.stamina = 200
    db.save_player(p)

    # Hard mode locked until Normal is cleared
    with pytest.raises(RPGError, match="先通關"):
        eng.start_dungeon_combat("6001", "goblin_woods", "hard", now_ts=t0)

    # Sweep locked until cleared
    with pytest.raises(RPGError, match="手動通關"):
        eng.sweep_dungeon("6001", "goblin_woods", "normal", times=1, now_ts=t0)

    # Manual combat actions + auto-battle win
    session = eng.start_dungeon_combat("6001", "goblin_woods", "normal", now_ts=t0 + 5)
    session = eng.combat_action("6001", "skill", now_ts=t0 + 6)
    if not session.finished:
        session = eng.combat_action("6001", "defend", now_ts=t0 + 7)
    if not session.finished:
        session = eng.combat_action("6001", "auto", now_ts=t0 + 8)

    assert session.finished is True
    assert session.victory is True
    assert session.rewards_summary is not None
    assert session.rewards_summary["first_clear"] is True
    assert session.rewards_summary["gems"] > 0

    # Sweep is now unlocked!
    sw = eng.sweep_dungeon("6001", "goblin_woods", "normal", times=2, now_ts=t0 + 20)
    assert sw["times"] == 2
    assert sw["gold"] > 0

    # Hard difficulty is now unlocked!
    hard_sess = eng.start_dungeon_combat("6001", "goblin_woods", "hard", now_ts=t0 + 30)
    # Test retreat refunds half stamina
    stam_mid = db.get_player("6001").stamina
    ret_sess = eng.combat_action("6001", "retreat", now_ts=t0 + 31)
    assert ret_sess.retreated is True
    assert db.get_player("6001").stamina == stam_mid + (hard_sess.stamina_spent // 2)

    # Endless Abyss floor 1 clear updates abyss_highest
    abyss_sess = eng.start_abyss_combat("6001", floor=1, now_ts=t0 + 40)
    abyss_sess = eng.combat_action("6001", "auto", now_ts=t0 + 41)
    assert abyss_sess.victory is True
    assert db.get_player("6001").abyss_highest == 1
    db.close()


def test_world_boss_coop_kill_rewards_and_respawn(tmp_path: Path) -> None:
    db, eng = _make_engine(tmp_path)
    t0 = 1_750_000_000
    p1 = eng.register_player("7001", "Raider1", "mage", now_ts=t0)
    p2 = eng.register_player("7002", "Raider2", "ranger", now_ts=t0)
    p1.level = 80
    p2.level = 80
    db.save_player(p1)
    db.save_player(p2)

    boss = eng.get_or_spawn_world_boss(t0)
    assert boss.tier == 1

    # Player 1 deals first hit
    res1 = eng.attack_world_boss("7001", "Raider1", now_ts=t0 + 10)
    assert res1["dealt"] > 0
    assert res1["boss_killed"] is False

    # Lower boss HP so Player 2 lands finishing blow
    boss_live = db.get_active_world_boss()
    assert boss_live is not None
    boss_live.current_hp = 5
    db.update_world_boss(boss_live)

    p1_gems_before = db.get_player("7001").gems
    p2_gems_before = db.get_player("7002").gems

    res2 = eng.attack_world_boss("7002", "Raider2", now_ts=t0 + 20)
    assert res2["boss_killed"] is True
    assert res2["next_boss"] is not None
    assert res2["next_boss"].tier == 2

    # BOTH participants automatically received kill rewards & achievements!
    p1_after = db.get_player("7001")
    p2_after = db.get_player("7002")
    assert p1_after.gems > p1_gems_before
    assert p2_after.gems > p2_gems_before
    assert p1_after.boss_kills_participated == 1
    assert p2_after.boss_kills_participated == 1
    db.close()


def test_shop_mystery_gacha_pity_quests_rebirth_and_leaderboards(tmp_path: Path) -> None:
    db, eng = _make_engine(tmp_path)
    t0 = 1_750_000_000
    p = eng.register_player("8001", "Whale", "paladin", now_ts=t0)
    p.gold = 200_000
    p.gems = 5_000
    db.save_player(p)

    # Supply shop daily limit enforcement
    for _ in range(3):
        eng.buy_supply_item("8001", "buy_stamina", now_ts=t0 + 10)
    with pytest.raises(RPGError, match="限購"):
        eng.buy_supply_item("8001", "buy_stamina", now_ts=t0 + 11)

    # Mystery shop deterministic offer purchase (1x per 6h epoch)
    mshop = eng.get_mystery_shop(db.get_player("8001"), now_ts=t0 + 20)
    assert len(mshop["offers"]) == 5
    first_key = mshop["offers"][0]["key"]
    eng.buy_mystery_offer("8001", first_key, now_ts=t0 + 25)
    with pytest.raises(RPGError, match="已購買"):
        eng.buy_mystery_offer("8001", first_key, now_ts=t0 + 26)

    # Astral chest pity guarantees Mythic on 30th pull
    p_gacha = db.get_player("8001")
    p_gacha.gacha_pity_mythic = 29
    db.save_player(p_gacha)
    pull = eng.open_chest("8001", "astral", now_ts=t0 + 30)
    assert pull["gear"].rarity == "mythic"
    assert pull["pity_mythic"] == 0

    # Daily check-in + consecutive streak next day
    c1 = eng.daily_checkin("8001", now_ts=t0)
    assert c1["streak"] == 1
    with pytest.raises(RPGError, match="已經簽到"):
        eng.daily_checkin("8001", now_ts=t0 + 60)
    c2 = eng.daily_checkin("8001", now_ts=t0 + 86400)
    assert c2["streak"] == 2

    # Quests: mine 5 times -> claim daily_mine quest
    for i in range(5):
        eng.mine("8001", now_ts=t0 + 100 + i * 5)
    q_claim = eng.claim_all_quests("8001", now_ts=t0 + 200)
    assert "勤勞礦工" in q_claim["claimed_names"]

    # Class promotion (Lv.30) & Class Change (with emblem)
    p_pr = db.get_player("8001")
    p_pr.level = 30
    db.save_player(p_pr)
    db.add_item("8001", "mithril_ore", 20)
    db.add_item("8001", "boss_essence", 10)
    promo = eng.promote_class("8001")
    assert promo["new_title"] == "聖光守護者"

    db.add_item("8001", "class_emblem", 1)
    sw_cls = eng.change_class("8001", "swordsman")
    assert sw_cls["new_title"] == "烈焰劍聖"

    # Rebirth at Lv.100 keeps gear/gold/gems and grants permanent stat multiplier
    p_rb = db.get_player("8001")
    p_rb.level = MAX_LEVEL
    db.save_player(p_rb)
    gear_count_before = len(db.get_equipment("8001"))
    rb = eng.rebirth("8001", now_ts=t0 + 500)
    assert rb["rebirth_count"] == 1
    p_after_rb = db.get_player("8001")
    assert p_after_rb.level == 1
    assert p_after_rb.rebirth_count == 1
    assert len(db.get_equipment("8001")) == gear_count_before

    # Leaderboards across all 6 categories
    eng.register_player("8002", "Rival", "ranger", now_ts=t0 + 600)
    for cat in ("power", "level", "abyss", "gold", "mining", "boss"):
        board = db.get_leaderboard(cat, limit=10)
        assert len(board) == 2
        rank, total = db.get_player_rank("8001", cat)
        assert rank in (1, 2)
        assert total == 2
    db.close()


def _is_valid_raster_image_url(url: str) -> bool:
    return url.startswith("https://") and url.lower().endswith((".png", ".webp", ".jpg", ".jpeg"))


def test_all_embed_builders_produce_valid_discord_embeds(tmp_path: Path) -> None:
    """Smoke-test every Embed builder to catch formatting errors, missing artwork, or Discord limit overflows."""
    db, eng = _make_engine(tmp_path)
    t0 = 1_750_000_000
    p = eng.register_player("9001", "EmbedTester", "mage", now_ts=t0)
    p.gold = 50_000
    db.save_player(p)
    db.add_item("9001", "enhance_stone", 20)
    stats = eng.compute_stats(p)
    eq = db.get_equipment("9001")
    inv = db.get_inventory("9001")
    mine_res = eng.mine("9001", now_ts=t0 + 10)
    sess = eng.start_dungeon_combat("9001", "goblin_woods", "normal", now_ts=t0 + 20)
    boss = eng.get_or_spawn_world_boss(t0 + 30)
    mshop = eng.get_mystery_shop(p, now_ts=t0 + 30)
    enh_res = eng.enhance_equipment("9001", eq[0].id, now_ts=t0 + 35)

    # Simulate a victory combat session with a dropped piece of equipment
    sess_win = eng.start_dungeon_combat("9001", "goblin_woods", "normal", now_ts=t0 + 40)
    sess_win.finished = True
    sess_win.victory = True
    sess_win.rewards_summary = {
        "gold": 500,
        "exp": 300,
        "gems": 25,
        "first_clear": True,
        "stamina_refund": 6,
        "levels_gained": 1,
        "loot": {"copper_ore": 5},
        "gear": [eq[0]],
        "achievements": [],
    }
    combat_cards = build_combat_embeds(sess_win, p)
    assert len(combat_cards) == 2

    embeds = [
        build_welcome_class_embed(),
        build_profile_embed(p, stats, eq, 120, 1, 1),
        build_mine_result_embed(mine_res),
        build_combat_embed(sess, p),
        *combat_cards,
        build_equipment_card_embed(eq[0]),
        build_enhance_result_embed(enh_res),
        build_dungeon_list_embed(p, {}),
        build_dungeon_list_embed(p, {}, selected_dungeon_id="astral_citadel"),
        build_world_boss_embed(boss, [], p),
        build_shop_embed(p, "supply", {}, mshop, 0),
        build_shop_embed(p, "mystery", {}, mshop, 0),
        build_shop_embed(p, "gacha", {}, mshop, 0),
        build_shop_embed(p, "sell", {}, mshop, 0),
        build_bag_embed(p, eq, inv, "gear", 0),
        build_bag_embed(p, eq, inv, "materials", 0),
        build_forge_embed(p, inv, eq),
        build_daily_quests_embed(p, eng.get_quests_status("9001", t0), eng.today_key(t0)),
        build_expedition_embed(p, None, t0),
        build_leaderboard_embed("power", [p], 1, 1),
        build_achievements_embed(p, {}),
        build_class_embed(p, inv),
        build_rebirth_embed(p),
        build_help_embed(),
    ]
    for emb in embeds:
        d = emb.to_dict()
        assert d.get("title")
        assert len(d.get("description", "")) <= 4096
        for f in d.get("fields", []):
            assert len(f["name"]) <= 256
            assert len(f["value"]) <= 1024
        # Every RPG embed must display at least one valid raster image (thumbnail or image)
        thumb_url = d.get("thumbnail", {}).get("url")
        img_url = d.get("image", {}).get("url")
        assert thumb_url or img_url, f"Embed missing artwork: {d.get('title')}"
        if thumb_url:
            assert _is_valid_raster_image_url(thumb_url), f"Invalid thumbnail URL: {thumb_url}"
        if img_url:
            assert _is_valid_raster_image_url(img_url), f"Invalid image URL: {img_url}"
    db.close()


def test_rpg_artwork_registry_coverage_and_format() -> None:
    """Every RPG item, gear tier/slot, class portrait, boss, zone, and expedition has a valid raster URL."""
    all_urls = all_asset_urls()
    assert len(all_urls) >= 100
    for url in all_urls:
        assert _is_valid_raster_image_url(url), f"Invalid or non-raster asset URL: {url}"
        assert ".svg" not in url.lower()

    for tier in GEAR_TIERS:
        for slot in SLOT_ORDER:
            assert _is_valid_raster_image_url(get_equipment_image_url(tier, slot))

    for cid in CLASSES:
        assert _is_valid_raster_image_url(get_class_icon_url(cid))
        portraits = [get_class_portrait_url(cid, promo) for promo in (1, 2, 3)]
        assert all(_is_valid_raster_image_url(u) for u in portraits)
        assert len(set(portraits)) == 3, f"Class {cid} portraits should evolve across 1/2/3轉"

    for d in DUNGEONS:
        assert _is_valid_raster_image_url(get_dungeon_boss_portrait_url(d["id"]))

    for wb in WORLD_BOSS_POOL:
        assert _is_valid_raster_image_url(get_world_boss_portrait_url(wb["id"]))

    for floor in range(1, 20):
        assert _is_valid_raster_image_url(get_abyss_guardian_portrait_url(floor))

    for z in MINE_ZONES:
        assert _is_valid_raster_image_url(get_mine_zone_banner_url(z["id"]))

    for p_tier in PICKAXES:
        assert _is_valid_raster_image_url(get_pickaxe_icon_url(p_tier))

    for item_id in ITEMS:
        assert _is_valid_raster_image_url(get_item_icon_url(item_id))

    for exp in EXPEDITIONS:
        assert _is_valid_raster_image_url(get_expedition_banner_url(exp["id"]))

    for tab in ("supply", "mystery", "gacha", "sell"):
        assert _is_valid_raster_image_url(get_shop_tab_icon_url(tab))

    for cat in ("power", "level", "abyss", "gold", "mining", "boss"):
        assert _is_valid_raster_image_url(get_leaderboard_icon_url(cat))


def test_all_classes_skills_ultimates_set_bonuses_and_auto_equip(tmp_path: Path) -> None:
    db, eng = _make_engine(tmp_path)
    t0 = 1_750_000_000

    for idx, cls_id in enumerate(("swordsman", "mage", "ranger", "paladin"), start=1):
        uid = f"910{idx}"
        p = eng.register_player(uid, f"Tester_{cls_id}", cls_id, now_ts=t0)
        p.level = 25
        p.stamina = 100
        db.save_player(p)

        # Equip 4 pieces of Pioneer set -> activates both 2-piece & 4-piece set bonuses
        for slot in ("helmet", "armor", "gloves", "boots"):
            eq = eng._build_equipment_obj(uid, tier=2, slot=slot, rarity="epic", now_ts=t0)
            db.add_equipment(eq)
        _, stats = eng.auto_equip_best(uid)
        assert any("拓荒者套裝 (2件)" in s for s in stats.active_sets)
        assert any("拓荒者套裝 (4件)" in s for s in stats.active_sets)

        # Exercise skill, ultimate, potion, defend, and auto-battle for each class
        sess = eng.start_dungeon_combat(uid, "undead_crypt", "normal", now_ts=t0 + 10)
        sess = eng.combat_action(uid, "skill", now_ts=t0 + 11)
        if not sess.finished:
            sess = eng.combat_action(uid, "ultimate", now_ts=t0 + 12)
        if not sess.finished:
            sess = eng.combat_action(uid, "potion", now_ts=t0 + 13)
        if not sess.finished:
            sess = eng.combat_action(uid, "auto", now_ts=t0 + 14)
        assert sess.finished is True

    # Test ore selling keeps crafting reserve
    db.add_item("9101", "copper_ore", 25)
    sell_res = eng.sell_ores("9101", keep_each=10)
    assert sell_res["sold_items"]["copper_ore"] == 15
    assert db.get_item_qty("9101", "copper_ore") == 10
    assert sell_res["gold"] > 0
    db.close()


def test_all_discord_ui_views_instantiate_cleanly(tmp_path: Path) -> None:
    """Verify every interactive discord.ui.View constructs without layout/option errors."""
    from src.rpg.views import (
        AchievementView,
        BagView,
        ClassHallView,
        ClassSelectView,
        CombatView,
        DailyQuestView,
        DungeonHallView,
        ExpeditionView,
        ForgeView,
        LeaderboardView,
        MineView,
        ProfileHubView,
        RebirthView,
        ShopView,
        WorldBossView,
    )

    db, eng = _make_engine(tmp_path)
    t0 = 1_750_000_000
    eng.register_player("9201", "ViewTester", "swordsman", now_ts=t0)
    # Add 7 extra pieces of gear so BagView renders both Inspect Select (row 3) and Pagination (row 4)
    for idx in range(7):
        extra = eng._build_equipment_obj(
            "9201", tier=(idx % 6) + 1, slot=SLOT_ORDER[idx % len(SLOT_ORDER)], rarity="rare", now_ts=t0
        )
        db.add_equipment(extra)
    eng.start_dungeon_combat("9201", "goblin_woods", "normal", now_ts=t0 + 5)

    async def _build_all() -> None:
        views = [
            ClassSelectView(eng, 9201),
            ProfileHubView(eng, 9201),
            MineView(eng, 9201, "emerald_pit"),
            CombatView(eng, 9201),
            DungeonHallView(eng, 9201),
            WorldBossView(eng),
            ShopView(eng, 9201, tab="supply"),
            ShopView(eng, 9201, tab="mystery"),
            ShopView(eng, 9201, tab="gacha"),
            ShopView(eng, 9201, tab="sell"),
            BagView(eng, 9201, tab="gear"),
            BagView(eng, 9201, tab="materials"),
            ForgeView(eng, 9201),
            DailyQuestView(eng, 9201),
            ExpeditionView(eng, 9201),
            LeaderboardView(eng, category="power"),
            AchievementView(eng, 9201),
            ClassHallView(eng, 9201),
            RebirthView(eng, 9201),
        ]
        for v in views:
            assert len(v.children) > 0
            assert len(v.children) <= 25
            for child in v.children:
                assert child.row is None or 0 <= child.row <= 4
            v.stop()

    asyncio.run(_build_all())
    db.close()

