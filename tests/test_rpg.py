"""SAO Aincrad Discord Bot, UI Views/Embeds, Persistence, Assets & Windows Script Tests."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import discord
import pytest

import bot as bot_module
from src.config import Settings
from src.rpg import assets
from src.rpg.database import RPGDatabase
from src.rpg.engine import RPGEngine
from src.rpg.ui import (
    BagEquipView,
    ChestView,
    CoopRaidView,
    DailyQuestView,
    DuelView,
    LeaderboardView,
    PartyLobbyView,
    PostCombatView,
    PostCoopRaidView,
    ProfileView,
    RoguelikeView,
    SecretRealmView,
    ShopView,
    SoloCombatView,
    TowerFloorView,
    WorkshopView,
    WorldBossView,
    build_argo_intel_embed,
    build_bag_embed,
    build_combat_embed,
    build_cooking_embed,
    build_coop_raid_embed,
    build_duel_embed,
    build_error_embed,
    build_guild_embed,
    build_help_embed,
    build_leaderboard_embed,
    build_market_embed,
    build_monument_embed,
    build_party_lobby_embed,
    build_profile_embed,
    build_quests_embed,
    build_roguelike_embed,
    build_secret_realm_embed,
    build_shop_embed,
    build_skills_embed,
    build_start_embed,
    build_tower_embed,
    build_workshop_embed,
    build_world_boss_embed,
    build_yui_embed,
)

EXPECTED_23_COMMANDS = {
    "start",
    "profile",
    "tower",
    "party",
    "boss",
    "skills",
    "bag",
    "equip",
    "inspect",
    "forge",
    "cook",
    "mine",
    "shop",
    "market",
    "guild",
    "duel",
    "daily",
    "expedition",
    "achievements",
    "leaderboard",
    "rebirth",
    "help",
    "p",
}


def _assert_embed_valid(embed: discord.Embed) -> None:
    d = embed.to_dict()
    total = len(str(d.get("title") or "")) + len(str(d.get("description") or ""))
    total += len(str((d.get("footer") or {}).get("text") or ""))
    fields = list(d.get("fields") or [])
    assert len(fields) <= 25
    for f in fields:
        total += len(str(f.get("name") or "")) + len(str(f.get("value") or ""))
    assert total <= 6000
    for key in ("image", "thumbnail"):
        url = (d.get(key) or {}).get("url")
        if url:
            assert str(url).startswith("https://")
            assert ".svg" not in str(url).lower()


def test_bot_registers_exact_23_top_level_commands(tmp_path: Path) -> None:
    cfg = Settings(discord_bot_token="", rpg_db_path=str(tmp_path / "bot_test.db"))
    b = bot_module.create_bot(cfg)
    try:
        names = {cmd.name for cmd in b.tree.get_commands()}
        assert names == EXPECTED_23_COMMANDS
    finally:
        b.rpg_db.close()


def test_settings_from_env_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "  placeholder_token_value  ")
    monkeypatch.setenv("TIMEZONE_OFFSET_HOURS", "9")
    monkeypatch.setenv("RPG_DB_PATH", "custom/aincrad.db")
    monkeypatch.setenv("RPG_BACKUP_INTERVAL_MINUTES", "20")
    s = Settings.from_env()
    assert s.discord_bot_token == "placeholder_token_value"
    assert s.timezone_offset_hours == 9
    assert s.rpg_db_path == "custom/aincrad.db"
    assert s.rpg_backup_interval_minutes == 20


def test_persistence_across_full_bot_restart(tmp_path: Path) -> None:
    db_file = tmp_path / "restart.db"
    db1 = RPGDatabase(db_file)
    eng1 = RPGEngine(db1)
    eng1.create_character("1001", "桐人", weapon_style="sword", now_ts=1760000000)
    eng1.claim_daily("1001", now_ts=1760000000)
    db1.close()

    db2 = RPGDatabase(db_file)
    eng2 = RPGEngine(db2)
    prof = eng2.get_profile("1001", now_ts=1760000000)
    assert prof["display_name"] == "桐人"
    assert prof["col"] > 500
    db2.close()


def test_all_embed_builders_produce_valid_discord_embeds(tmp_path: Path) -> None:
    db = RPGDatabase(tmp_path / "embeds.db")
    eng = RPGEngine(db)
    try:
        st = eng.create_character("2001", "亞絲娜", weapon_style="rapier", now_ts=1760000000)
        eng.create_character("2002", "克萊因", weapon_style="katana", now_ts=1760000000)
        prof = eng.get_profile("2001", now_ts=1760000000)
        finfo = eng.get_floor_info(1, user_id="2001")
        mon = eng.get_monument_of_life()
        yui = eng.get_yui_logs("2001")
        lb = eng.get_leaderboard("power")
        argo = eng.get_argo_intel(user_id="2001", floor=1)
        rl = eng.start_roguelike("2001", now_ts=1760000000, rng_seed=7)
        eng.extract_roguelike("2001", now_ts=1760000000)
        pty = eng.create_party("2001", floor=1, now_ts=1760000000)
        eng.join_party(pty["party_id"], "2002", now_ts=1760000000)
        eng.set_party_ready(pty["party_id"], "2001", True)
        eng.set_party_ready(pty["party_id"], "2002", True)
        eng.enter_boss_room(pty["party_id"], "2001", now_ts=1760000000)
        raid = eng.start_party_raid(pty["party_id"], "2001", now_ts=1760000000)
        wb = eng.attack_floor_world_boss("2002", now_ts=1760000000)
        eng.create_character("2003", "莉茲", weapon_style="mace", now_ts=1760000000)
        eng.create_character("2004", "西莉卡", weapon_style="dagger", now_ts=1760000000)
        duel = eng.challenge_duel("2003", "2004", now_ts=1760000000)
        gld = eng.create_guild("2003", "血盟騎士團", "KoB", now_ts=1760000000)
        mkt = eng.search_market()
        qst = eng.get_quests("2003", now_ts=1760000000)

        combat_res_with_drops = {
            "message": "🎉 擊敗哥布林斥候！",
            "logs": ["斬擊造成 45 點傷害！"],
            "rewards": {
                "exp_gain": 60,
                "col_gain": 120,
                "levels_gained": 1,
                "items": {"bright_crystal_shard": 2},
                "equipment_drops": [
                    {"status": "added", "item_uid": 10, "item_name": "鋼鐵長劍", "rarity": "rare", "slot": "weapon", "tier": 1}
                ],
            },
        }
        secret_res = {
            "floor": 1,
            "miasma_stacks": 3,
            "col_gain": 200,
            "exp_gain": 90,
            "items": {"bright_crystal_shard": 1},
            "equipment_drops": [{"item_name": "瘴氣短刀", "rarity": "rare", "slot": "weapon", "tier": 1}],
            "message": "🌫️ 秘境探索成功，瘴氣堆疊 3 層！",
        }

        embeds = [
            build_error_embed("錯誤", "測試錯誤訊息"),
            build_start_embed(st),
            build_profile_embed(prof),
            build_skills_embed(prof, eng.content),
            build_bag_embed(prof, eng.content),
            build_monument_embed(mon),
            build_yui_embed(yui),
            build_leaderboard_embed(lb),
            build_help_embed(),
            build_tower_embed(finfo),
            build_combat_embed({"message": "戰鬥開始"}),
            build_combat_embed(combat_res_with_drops, floor_info=finfo),
            build_secret_realm_embed(secret_res),
            build_argo_intel_embed(argo),
            build_roguelike_embed(rl),
            build_party_lobby_embed(pty),
            build_coop_raid_embed(raid),
            build_world_boss_embed(wb),
            build_duel_embed(duel),
            build_workshop_embed("鍛造", {"message": "鍛造成功", "enhance_level": 5}),
            build_workshop_embed(
                prof,
                prof["equipment"],
                prof["inventory"],
                selected_item=prof["equipment"][0] if prof["equipment"] else None,
                notice="🔨 歡迎來到莉茲貝特工坊",
                protection_on=True,
            ),
            build_cooking_embed({"message": "料理完成", "stew_id": "1"}),
            build_shop_embed(
                {"message": "商店購物", "col_remaining": 400, "tickets_remaining": 1},
                category_label="🧪 藥水與 SAO 水晶",
                catalog_lines=["• 回復藥水 — 80 柯爾"],
            ),
            build_market_embed(mkt),
            build_guild_embed(gld),
            build_quests_embed(qst),
        ]
        for em in embeds:
            _assert_embed_valid(em)
    finally:
        db.close()


def test_all_discord_ui_views_instantiate_and_obey_limits(tmp_path: Path) -> None:
    db = RPGDatabase(tmp_path / "views.db")
    eng = RPGEngine(db)
    eng.create_character("3001", "桐人", weapon_style="sword", now_ts=1760000000)

    async def _build_all() -> list[discord.ui.View]:
        return [
            ProfileView(eng, "3001"),
            BagEquipView(eng, "3001"),
            TowerFloorView(eng, "3001", 1),
            PostCombatView(eng, "3001", combat_mode="field", floor=1, outcome="victory"),
            PostCombatView(eng, "3001", combat_mode="field", floor=1, outcome="victory", boss_gate_unlocked=True),
            PostCombatView(eng, "3001", combat_mode="boss", floor=1, outcome="victory", unlocked_next_floor=2),
            PostCombatView(eng, "3001", combat_mode="boss", floor=100, outcome="victory", unlocked_next_floor=100),
            PostCombatView(eng, "3001", combat_mode="field", floor=1, outcome="defeat", hp_ratio=0.01),
            PostCombatView(eng, "3001", combat_mode="field", floor=1, outcome="defeat", is_hardcore_dead=True),
            PostCombatView(eng, "3001", combat_mode="roguelike", floor=1, outcome="victory", has_active_roguelike=True),
            SecretRealmView(eng, "3001"),
            ChestView(eng, "3001"),
            SoloCombatView(eng, "3001"),
            RoguelikeView(eng, "3001"),
            PartyLobbyView(eng, "pty_demo"),
            CoopRaidView(eng, "raid_demo"),
            PostCoopRaidView(eng, "pty_demo", floor=1, victory=True),
            PostCoopRaidView(eng, "pty_demo", floor=100, victory=True),
            WorldBossView(eng),
            DuelView(eng, "duel_demo"),
            WorkshopView(eng, "3001"),
            ShopView(eng, "3001", category="potions_crystals"),
            ShopView(eng, "3001", category="enhance_stones"),
            ShopView(eng, "3001", category="socket_crystals"),
            ShopView(eng, "3001", category="crates_tickets"),
            LeaderboardView(eng),
            DailyQuestView(eng, "3001"),
        ]

    try:
        views = asyncio.run(_build_all())
        for vw in views:
            assert len(vw.children) <= 25
            row_widths: dict[int, int] = {}
            for child in vw.children:
                row = getattr(child, "row", None)
                assert row is None or (0 <= row <= 4)
                r = 0 if row is None else int(row)
                width = 5 if isinstance(child, discord.ui.Select) else 1
                row_widths[r] = row_widths.get(r, 0) + width
                assert row_widths[r] <= 5, f"Row {r} exceeded Discord width 5 on {type(vw).__name__}"
                if hasattr(child, "options"):
                    assert 1 <= len(child.options) <= 25
                    for opt in child.options:
                        assert 1 <= len(opt.label) <= 100
                        assert 1 <= len(opt.value) <= 100
                        if opt.description:
                            assert len(opt.description) <= 100
    finally:
        db.close()


def test_rpg_artwork_registry_all_raster_non_svg() -> None:
    urls = assets.all_asset_urls()
    assert len(urls) >= 50
    for url in urls:
        assert url.startswith("https://")
        assert ".svg" not in url.lower()


def test_single_instance_lock_logging_and_cli_args(tmp_path: Path) -> None:
    lock1 = bot_module.SingleInstanceLock(tmp_path)
    lock2 = bot_module.SingleInstanceLock(tmp_path)

    assert lock1.acquire() is True
    assert (tmp_path / "bot.pid").read_text(encoding="utf-8").strip() == str(os.getpid())
    assert lock2.acquire() is False

    lock1.release()
    assert not (tmp_path / "bot.pid").exists()
    assert lock2.acquire() is True
    lock2.release()

    log_file = tmp_path / "logs" / "bot.log"
    handler = bot_module.configure_file_logging(str(log_file))
    handler_same = bot_module.configure_file_logging(str(log_file))
    assert handler is handler_same
    try:
        bot_module.logger.info("⚔️ SAO UTF-8 日誌測試成功")
        handler.flush()
        content = log_file.read_text(encoding="utf-8")
        assert "⚔️ SAO UTF-8 日誌測試成功" in content
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()

    args = bot_module.parse_bot_args(
        ["--run-minutes", "120", "--log-file", "logs/bot.log", "--control-dir", "tmp_ctrl"]
    )
    assert args.run_minutes == 120
    assert args.log_file == "logs/bot.log"
    assert args.control_dir == "tmp_ctrl"


def test_windows_autostart_scripts_format_and_encoding() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    scripts = [
        "start_bot.bat",
        "start_bot_hidden.vbs",
        "stop_bot.bat",
        "setup_autostart.bat",
        "update_bot.bat",
    ]
    for name in scripts:
        p = repo_root / name
        assert p.exists(), f"Missing Windows script: {name}"
        raw = p.read_bytes()
        assert b"\r\n" in raw, f"{name} must use CRLF line endings for Windows"
        assert b"\n" not in raw.replace(b"\r\n", b""), f"{name} contains bare LF"

    update_text = (repo_root / "update_bot.bat").read_text(encoding="utf-8")
    assert "Lun8211/Discord-SAO-RPG" in update_text
    assert ".env" in update_text
    assert "load_and_validate_all" in update_text

    vbs_raw = (repo_root / "start_bot_hidden.vbs").read_bytes()
    vbs_raw.decode("ascii")
    assert b"--hidden" in vbs_raw
