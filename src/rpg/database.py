"""SQLite persistence layer with WAL durability, v1->v2 migration, local backups, and Discord snapshot sync."""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
import time
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from src.rpg.models import (
    LEGACY_CLASS_TO_WEAPON_STYLE,
    ActiveExpedition,
    EquipmentItem,
    GameError,
    GuildInfo,
    MarketListing,
    PartyLobby,
    PartyMemberState,
    PlayerProfile,
    WeaponStyle,
    WorldBossState,
)

logger = logging.getLogger("val-dc-rpg-db")

SCHEMA_VERSION = 2
SNAPSHOT_FILENAME_RE = re.compile(r"^rpg_snapshot_seq(\d+)\.db\.gz$")

SCHEMA_SQL = """
-- =============================================================================
-- Legacy v1 Core Tables (11 tables — preserved verbatim for v1 -> v2 compat)
-- =============================================================================
CREATE TABLE IF NOT EXISTS rpg_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    class_id TEXT NOT NULL,
    promo_tier INTEGER NOT NULL DEFAULT 1,
    level INTEGER NOT NULL DEFAULT 1,
    exp INTEGER NOT NULL DEFAULT 0,
    rebirth_count INTEGER NOT NULL DEFAULT 0,
    gold INTEGER NOT NULL DEFAULT 250,
    gems INTEGER NOT NULL DEFAULT 50,
    stamina INTEGER NOT NULL DEFAULT 100,
    stamina_updated_at INTEGER NOT NULL,
    pickaxe_tier INTEGER NOT NULL DEFAULT 1,
    mine_combo INTEGER NOT NULL DEFAULT 0,
    last_mine_at INTEGER NOT NULL DEFAULT 0,
    last_boss_at INTEGER NOT NULL DEFAULT 0,
    abyss_floor INTEGER NOT NULL DEFAULT 1,
    abyss_highest INTEGER NOT NULL DEFAULT 0,
    active_title TEXT NOT NULL DEFAULT '',
    gacha_pity_legendary INTEGER NOT NULL DEFAULT 0,
    gacha_pity_mythic INTEGER NOT NULL DEFAULT 0,
    checkin_streak INTEGER NOT NULL DEFAULT 0,
    last_checkin_date TEXT NOT NULL DEFAULT '',
    total_checkins INTEGER NOT NULL DEFAULT 0,
    total_mines INTEGER NOT NULL DEFAULT 0,
    total_dungeons INTEGER NOT NULL DEFAULT 0,
    total_enhances INTEGER NOT NULL DEFAULT 0,
    total_boss_damage INTEGER NOT NULL DEFAULT 0,
    boss_kills_participated INTEGER NOT NULL DEFAULT 0,
    combat_power INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    template_id TEXT NOT NULL,
    name TEXT NOT NULL,
    slot TEXT NOT NULL,
    rarity TEXT NOT NULL,
    tier INTEGER NOT NULL DEFAULT 1,
    set_id TEXT NOT NULL DEFAULT '',
    enhance_level INTEGER NOT NULL DEFAULT 0,
    enhance_pity INTEGER NOT NULL DEFAULT 0,
    base_hp INTEGER NOT NULL DEFAULT 0,
    base_mp INTEGER NOT NULL DEFAULT 0,
    base_atk INTEGER NOT NULL DEFAULT 0,
    base_def INTEGER NOT NULL DEFAULT 0,
    affixes_json TEXT NOT NULL DEFAULT '{}',
    is_equipped INTEGER NOT NULL DEFAULT 0,
    is_locked INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_equipment_user ON equipment(user_id);
CREATE INDEX IF NOT EXISTS idx_equipment_user_equipped ON equipment(user_id, is_equipped);

CREATE TABLE IF NOT EXISTS inventory (
    user_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, item_id),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dungeon_clears (
    user_id TEXT NOT NULL,
    dungeon_id TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    clear_count INTEGER NOT NULL DEFAULT 0,
    first_cleared_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, dungeon_id, difficulty),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS quests (
    user_id TEXT NOT NULL,
    period_type TEXT NOT NULL,
    period_key TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    target INTEGER NOT NULL,
    claimed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, period_type, period_key, quest_id),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS achievements (
    user_id TEXT NOT NULL,
    achievement_id TEXT NOT NULL,
    unlocked_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, achievement_id),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS expeditions (
    user_id TEXT PRIMARY KEY,
    expedition_id TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,
    claimed INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS shop_purchases (
    user_id TEXT NOT NULL,
    shop_bucket TEXT NOT NULL,
    offer_key TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, shop_bucket, offer_key),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS world_boss (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tier INTEGER NOT NULL,
    boss_id TEXT NOT NULL,
    name TEXT NOT NULL,
    max_hp INTEGER NOT NULL,
    current_hp INTEGER NOT NULL,
    atk INTEGER NOT NULL,
    def_ INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    spawned_at INTEGER NOT NULL,
    defeated_at INTEGER,
    killer_user_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_world_boss_status ON world_boss(status);

CREATE TABLE IF NOT EXISTS world_boss_damage (
    boss_instance_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    total_damage INTEGER NOT NULL DEFAULT 0,
    attacks_count INTEGER NOT NULL DEFAULT 0,
    last_attack_at INTEGER NOT NULL,
    PRIMARY KEY (boss_instance_id, user_id),
    FOREIGN KEY (boss_instance_id) REFERENCES world_boss(id) ON DELETE CASCADE
);

-- =============================================================================
-- SAO Aincrad v2 Extension Tables (22 new tables; 33 tables total)
-- =============================================================================

-- 1. Pending Loot Mailbox (Named / LA / Set overflow)
CREATE TABLE IF NOT EXISTS pending_loot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    source TEXT NOT NULL,
    item_type TEXT NOT NULL DEFAULT 'equipment',
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    claimed_at INTEGER DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pending_loot_user_unclaimed ON pending_loot(user_id, claimed_at);

-- 2. Per-Player 100-Floor Tower Progress & Daily Team Boss Boosted Clears
CREATE TABLE IF NOT EXISTS tower_progress (
    user_id TEXT NOT NULL,
    floor INTEGER NOT NULL,
    clear_count INTEGER NOT NULL DEFAULT 0,
    first_cleared_at INTEGER NOT NULL,
    best_turns INTEGER NOT NULL DEFAULT 0,
    daily_team_clears INTEGER NOT NULL DEFAULT 0,
    daily_team_date TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, floor),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

-- 3. Server-Wide Atomic First-Kill Hall of Fame (PK = floor guarantees single winner)
CREATE TABLE IF NOT EXISTS server_floor_clears (
    floor INTEGER PRIMARY KEY,
    boss_id TEXT NOT NULL,
    boss_name TEXT NOT NULL,
    leader_id TEXT NOT NULL,
    leader_name TEXT NOT NULL,
    la_user_id TEXT NOT NULL DEFAULT '',
    la_user_name TEXT NOT NULL DEFAULT '',
    participant_ids_json TEXT NOT NULL DEFAULT '[]',
    party_size INTEGER NOT NULL DEFAULT 1,
    cleared_at INTEGER NOT NULL
);

-- 4. Per-Player Floor Exploration Progress & Pending Discovered Chest
CREATE TABLE IF NOT EXISTS floor_exploration (
    user_id TEXT NOT NULL,
    floor INTEGER NOT NULL,
    progress_pct INTEGER NOT NULL DEFAULT 0,
    field_boss_cleared INTEGER NOT NULL DEFAULT 0,
    boss_gate_unlocked INTEGER NOT NULL DEFAULT 0,
    pending_chest_json TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, floor),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

-- 5. Weapon Proficiency & Passive/Life Skill Mastery
CREATE TABLE IF NOT EXISTS player_mastery (
    user_id TEXT NOT NULL,
    skill_key TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 1,
    exp INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, skill_key),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

-- 6. Branching Weapon Talent Tree Allocations
CREATE TABLE IF NOT EXISTS player_talents (
    user_id TEXT NOT NULL,
    talent_id TEXT NOT NULL,
    rank INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, talent_id),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

-- 7. Saved Equipment Loadouts (Slots 1..5)
CREATE TABLE IF NOT EXISTS gear_loadouts (
    user_id TEXT NOT NULL,
    slot_index INTEGER NOT NULL,
    name TEXT NOT NULL,
    gear_ids_json TEXT NOT NULL DEFAULT '[]',
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, slot_index),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

-- 8. Monument of Life (Black Iron Palace Chronicle & Defeat Logs)
CREATE TABLE IF NOT EXISTS monument_of_life (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    floor INTEGER NOT NULL DEFAULT 1,
    game_mode TEXT NOT NULL DEFAULT 'standard',
    cause TEXT NOT NULL DEFAULT '',
    last_log_json TEXT NOT NULL DEFAULT '[]',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_monument_created ON monument_of_life(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_monument_event ON monument_of_life(event_type, created_at DESC);

-- 9. Argo's Info — Observed Boss Skills per Player
CREATE TABLE IF NOT EXISTS boss_intel_seen (
    user_id TEXT NOT NULL,
    boss_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    first_seen_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, boss_id, skill_id),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

-- 10. Yui Console — Unlocked Cardinal Lore Archive Entries
CREATE TABLE IF NOT EXISTS yui_logs (
    user_id TEXT NOT NULL,
    log_id TEXT NOT NULL,
    unlocked_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, log_id),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

-- 11. Real-Human Party Lobbies & Raid Alliances
CREATE TABLE IF NOT EXISTS parties (
    party_id TEXT PRIMARY KEY,
    leader_id TEXT NOT NULL,
    floor INTEGER NOT NULL DEFAULT 1,
    boss_mode TEXT NOT NULL DEFAULT 'normal',
    max_size INTEGER NOT NULL DEFAULT 6,
    is_raid_alliance INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'lobby',
    channel_id INTEGER DEFAULT NULL,
    message_id INTEGER DEFAULT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_parties_status ON parties(status, floor);

-- 12. Party Members
CREATE TABLE IF NOT EXISTS party_members (
    party_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'dps',
    is_ready INTEGER NOT NULL DEFAULT 0,
    potion_sharing INTEGER NOT NULL DEFAULT 0,
    frontline_stance INTEGER NOT NULL DEFAULT 0,
    joined_at INTEGER NOT NULL,
    PRIMARY KEY (party_id, user_id),
    FOREIGN KEY (party_id) REFERENCES parties(party_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_party_members_user ON party_members(user_id);

-- 13. Co-op & Solo Boss Raid History
CREATE TABLE IF NOT EXISTS raid_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raid_id TEXT NOT NULL,
    party_id TEXT NOT NULL DEFAULT '',
    floor INTEGER NOT NULL,
    boss_id TEXT NOT NULL,
    boss_mode TEXT NOT NULL DEFAULT 'normal',
    victory INTEGER NOT NULL DEFAULT 0,
    is_first_kill INTEGER NOT NULL DEFAULT 0,
    la_user_id TEXT NOT NULL DEFAULT '',
    participants_json TEXT NOT NULL DEFAULT '[]',
    turns_taken INTEGER NOT NULL DEFAULT 0,
    started_at INTEGER NOT NULL,
    ended_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raid_history_floor ON raid_history(floor, ended_at DESC);

-- 14. Guilds
CREATE TABLE IF NOT EXISTS guilds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    tag TEXT NOT NULL UNIQUE,
    leader_id TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 1,
    exp INTEGER NOT NULL DEFAULT 0,
    vault_col INTEGER NOT NULL DEFAULT 0,
    merit_points INTEGER NOT NULL DEFAULT 0,
    ranks_config_json TEXT NOT NULL DEFAULT '{}',
    max_members INTEGER NOT NULL DEFAULT 20,
    active_buff_id TEXT NOT NULL DEFAULT '',
    active_buff_expires_at INTEGER NOT NULL DEFAULT 0,
    raid_last_started_at INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

-- 15. Guild Members
CREATE TABLE IF NOT EXISTS guild_members (
    user_id TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    rank_name TEXT NOT NULL DEFAULT 'member',
    contribution_col INTEGER NOT NULL DEFAULT 0,
    merit INTEGER NOT NULL DEFAULT 0,
    joined_at INTEGER NOT NULL,
    FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_guild_members_guild ON guild_members(guild_id);

-- 16. Guild Shared Warehouse
CREATE TABLE IF NOT EXISTS guild_warehouse (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    item_type TEXT NOT NULL DEFAULT 'equipment',
    equipment_id INTEGER DEFAULT NULL,
    item_id TEXT DEFAULT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    item_snapshot_json TEXT NOT NULL DEFAULT '{}',
    deposited_by TEXT NOT NULL,
    deposited_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'stored',
    withdrawn_by TEXT DEFAULT NULL,
    withdrawn_at INTEGER DEFAULT NULL,
    FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_guild_warehouse_stored ON guild_warehouse(guild_id, status);

-- 17. Guild Audit Logs
CREATE TABLE IF NOT EXISTS guild_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_guild_logs_guild ON guild_logs(guild_id, created_at DESC);

-- 18. Guild Quests & Equipment Commissions
CREATE TABLE IF NOT EXISTS guild_quests (
    guild_id INTEGER NOT NULL,
    period_type TEXT NOT NULL,
    period_key TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    target INTEGER NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, period_type, period_key, quest_id),
    FOREIGN KEY (guild_id) REFERENCES guilds(id) ON DELETE CASCADE
);

-- 19. Player Marketplace (Atomic Escrow)
CREATE TABLE IF NOT EXISTS market_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id TEXT NOT NULL,
    seller_name TEXT NOT NULL DEFAULT '',
    item_type TEXT NOT NULL DEFAULT 'equipment',
    equipment_id INTEGER DEFAULT NULL,
    item_id TEXT DEFAULT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    item_name TEXT NOT NULL DEFAULT '',
    slot TEXT NOT NULL DEFAULT '',
    weapon_style TEXT NOT NULL DEFAULT '',
    rarity TEXT NOT NULL DEFAULT '',
    affix_keys_json TEXT NOT NULL DEFAULT '[]',
    item_snapshot_json TEXT NOT NULL DEFAULT '{}',
    price_col INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    buyer_id TEXT DEFAULT NULL,
    created_at INTEGER NOT NULL,
    sold_at INTEGER DEFAULT NULL,
    FOREIGN KEY (seller_id) REFERENCES players(user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_market_active_search
    ON market_listings(status, rarity, slot, weapon_style, price_col);
CREATE INDEX IF NOT EXISTS idx_market_seller ON market_listings(seller_id, status);

-- 20. Achievement Collection Turn-In
CREATE TABLE IF NOT EXISTS achievement_turnins (
    user_id TEXT NOT NULL,
    turnin_key TEXT NOT NULL,
    item_name TEXT NOT NULL DEFAULT '',
    rarity TEXT NOT NULL DEFAULT 'plain',
    bonus_json TEXT NOT NULL DEFAULT '{}',
    turned_in_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, turnin_key),
    FOREIGN KEY (user_id) REFERENCES players(user_id) ON DELETE CASCADE
);

-- 21. PvP Duel Records
CREATE TABLE IF NOT EXISTS duel_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    duel_id TEXT NOT NULL,
    challenger_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    wager_col INTEGER NOT NULL DEFAULT 0,
    winner_id TEXT NOT NULL,
    turns INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_duel_records_users ON duel_records(challenger_id, target_id, created_at DESC);

-- 22. Server / Guild / Party World Buffs & Big Pot Stew
CREATE TABLE IF NOT EXISTS world_buffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buff_key TEXT NOT NULL,
    scope_type TEXT NOT NULL DEFAULT 'server',
    scope_id TEXT NOT NULL DEFAULT 'global',
    name TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    charges_remaining INTEGER NOT NULL DEFAULT -1,
    claimed_by_json TEXT NOT NULL DEFAULT '[]',
    created_by TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_world_buffs_active ON world_buffs(scope_type, scope_id, expires_at);
"""

# Static hardcoded migration columns (ZERO dynamic user-supplied identifiers)
_PLAYERS_V2_COLUMNS: tuple[tuple[str, str], ...] = (
    ("current_floor", "INTEGER NOT NULL DEFAULT 1"),
    ("highest_cleared_floor", "INTEGER NOT NULL DEFAULT 0"),
    ("zone", "TEXT NOT NULL DEFAULT 'town'"),
    ("weapon_style", "TEXT NOT NULL DEFAULT 'sword'"),
    ("game_mode", "TEXT NOT NULL DEFAULT 'standard'"),
    ("cursor_color", "TEXT NOT NULL DEFAULT 'green'"),
    ("karma", "INTEGER NOT NULL DEFAULT 0"),
    ("hp", "INTEGER NOT NULL DEFAULT 0"),
    ("sp", "INTEGER NOT NULL DEFAULT 100"),
    ("max_sp", "INTEGER NOT NULL DEFAULT 100"),
    ("miasma_stacks", "INTEGER NOT NULL DEFAULT 0"),
    ("miasma_exp_stacks", "INTEGER NOT NULL DEFAULT 0"),
    ("survival_config_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("loot_filter_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("skill_slots_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("unique_skills_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("stat_points", "INTEGER NOT NULL DEFAULT 0"),
    ("talent_points", "INTEGER NOT NULL DEFAULT 0"),
    ("str_stat", "INTEGER NOT NULL DEFAULT 5"),
    ("agi_stat", "INTEGER NOT NULL DEFAULT 5"),
    ("vit_stat", "INTEGER NOT NULL DEFAULT 5"),
    ("dex_stat", "INTEGER NOT NULL DEFAULT 5"),
    ("luk_stat", "INTEGER NOT NULL DEFAULT 5"),
    ("downed_until", "INTEGER NOT NULL DEFAULT 0"),
    ("is_dead", "INTEGER NOT NULL DEFAULT 0"),
    ("survival_streak", "INTEGER NOT NULL DEFAULT 0"),
    ("last_death_log", "TEXT NOT NULL DEFAULT ''"),
    ("guild_id", "INTEGER DEFAULT NULL"),
    ("guild_left_at", "INTEGER NOT NULL DEFAULT 0"),
    ("active_buffs_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("world_boss_attempts", "INTEGER NOT NULL DEFAULT 3"),
    ("world_boss_attempts_date", "TEXT NOT NULL DEFAULT ''"),
    ("story_choices_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("nightmare_highest", "INTEGER NOT NULL DEFAULT 0"),
    ("boss_rush_best", "INTEGER NOT NULL DEFAULT 0"),
    ("roguelike_best_score", "INTEGER NOT NULL DEFAULT 0"),
    ("in_boss_battle", "INTEGER NOT NULL DEFAULT 0"),
)

_EQUIPMENT_V2_COLUMNS: tuple[tuple[str, str], ...] = (
    ("weapon_style", "TEXT NOT NULL DEFAULT ''"),
    ("damage_type", "TEXT NOT NULL DEFAULT ''"),
    ("named_passive", "TEXT NOT NULL DEFAULT ''"),
    ("is_bound", "INTEGER NOT NULL DEFAULT 0"),
    ("min_level", "INTEGER NOT NULL DEFAULT 1"),
    ("escrow_state", "TEXT NOT NULL DEFAULT ''"),
    ("base_sp", "INTEGER NOT NULL DEFAULT 0"),
    ("base_spd", "INTEGER NOT NULL DEFAULT 0"),
    ("temper_level", "INTEGER NOT NULL DEFAULT 0"),
    ("socket_crystal_id", "TEXT NOT NULL DEFAULT ''"),
)

_WORLD_BOSS_V2_COLUMNS: tuple[tuple[str, str], ...] = (
    ("floor", "INTEGER NOT NULL DEFAULT 1"),
    ("accelerated_buff_hours", "INTEGER NOT NULL DEFAULT 2"),
)

_LEADERBOARD_ORDER_SQL: dict[str, str] = {
    "power": "combat_power DESC, rebirth_count DESC, level DESC",
    "level": "rebirth_count DESC, level DESC, exp DESC",
    "abyss": "abyss_highest DESC, combat_power DESC",
    "gold": "gold DESC, combat_power DESC",
    "mining": "total_mines DESC, pickaxe_tier DESC",
    "boss": "total_boss_damage DESC, boss_kills_participated DESC",
    # SAO categories
    "floor": "highest_cleared_floor DESC, combat_power DESC, level DESC",
    "col": "gold DESC, combat_power DESC",
    "world_boss": "total_boss_damage DESC, boss_kills_participated DESC",
    "survival": "survival_streak DESC, highest_cleared_floor DESC, combat_power DESC",
}


def _safe_json_dict(raw: str | None, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not raw:
        return dict(default) if default is not None else {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            if default:
                merged = dict(default)
                merged.update(parsed)
                return merged
            return parsed
    except json.JSONDecodeError:
        pass
    return dict(default) if default is not None else {}


def _safe_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    return []


class RPGDatabase:
    """Thread-safe, durable SQLite v2 storage for all SAO Aincrad players and world state."""

    def __init__(self, db_path: str | Path = "data/rpg.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir = self.db_path.parent / "backups"
        self._lock = threading.RLock()
        self._tx_depth = 0
        self._closed = False
        self._tx_dirty = False
        self._last_uploaded_seq = -1
        self._conn = self._open_connection()
        self._init_schema()

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            isolation_level=None,  # Explicit transaction control
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = FULL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 10000;")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA_SQL)
            now_str = str(int(time.time()))
            self._conn.execute(
                "INSERT OR IGNORE INTO rpg_meta (key, value) VALUES ('schema_version', '1')"
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO rpg_meta (key, value) VALUES ('save_seq', '0')"
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO rpg_meta (key, value) VALUES ('updated_at', ?)",
                (now_str,),
            )
            self._migrate_to_v2_locked()

    def _ensure_columns_locked(
        self, table: str, columns: tuple[tuple[str, str], ...]
    ) -> None:
        existing = {
            str(row["name"])
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for col_name, col_ddl in columns:
            if col_name not in existing:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_ddl}")

    def _migrate_to_v2_locked(self) -> None:
        """Idempotent v1 -> v2 schema evolution inside transaction(mark_dirty=False)."""
        with self.transaction(mark_dirty=False):
            row = self._conn.execute(
                "SELECT value FROM rpg_meta WHERE key = 'schema_version'"
            ).fetchone()
            current_schema = int(row["value"]) if row else 1

            self._ensure_columns_locked("players", _PLAYERS_V2_COLUMNS)
            self._ensure_columns_locked("equipment", _EQUIPMENT_V2_COLUMNS)
            self._ensure_columns_locked("world_boss", _WORLD_BOSS_V2_COLUMNS)

            if current_schema < SCHEMA_VERSION:
                for legacy_cls, sao_style in LEGACY_CLASS_TO_WEAPON_STYLE.items():
                    self._conn.execute(
                        """
                        UPDATE players SET weapon_style = ?
                        WHERE class_id = ? AND weapon_style = 'sword'
                        """,
                        (sao_style, legacy_cls),
                    )
                self._conn.execute(
                    """
                    UPDATE players
                    SET highest_cleared_floor = MIN(100, abyss_highest)
                    WHERE highest_cleared_floor = 0 AND abyss_highest > 0
                    """
                )

            # Post-migration indexes referencing v2-added columns (ONLY after ALTER TABLE!)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_players_floor "
                "ON players(highest_cleared_floor DESC, combat_power DESC);"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_players_guild ON players(guild_id);"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_equipment_escrow "
                "ON equipment(user_id, escrow_state);"
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO rpg_meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @contextlib.contextmanager
    def transaction(self, mark_dirty: bool = True) -> Iterator[sqlite3.Connection]:
        """Run a group of DB operations atomically with nested-transaction support."""
        with self._lock:
            is_outer = self._tx_depth == 0
            if is_outer:
                self._conn.execute("BEGIN IMMEDIATE;")
                self._tx_dirty = False
            self._tx_depth += 1
            try:
                yield self._conn
                if mark_dirty:
                    self._tx_dirty = True
                self._tx_depth -= 1
                if is_outer:
                    if self._tx_dirty:
                        self._bump_save_seq_locked()
                    self._conn.execute("COMMIT;")
            except Exception:
                self._tx_depth -= 1
                if is_outer:
                    with contextlib.suppress(sqlite3.Error):
                        self._conn.execute("ROLLBACK;")
                raise

    def _bump_save_seq_locked(self) -> None:
        row = self._conn.execute(
            "SELECT value FROM rpg_meta WHERE key = 'save_seq'"
        ).fetchone()
        cur = int(row["value"]) if row else 0
        self._conn.execute(
            "INSERT OR REPLACE INTO rpg_meta (key, value) VALUES ('save_seq', ?)",
            (str(cur + 1),),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO rpg_meta (key, value) VALUES ('updated_at', ?)",
            (str(int(time.time())),),
        )

    def get_save_seq(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM rpg_meta WHERE key = 'save_seq'"
            ).fetchone()
            return int(row["value"]) if row else 0

    @property
    def save_seq(self) -> int:
        return self.get_save_seq()

    def get_schema_version(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM rpg_meta WHERE key = 'schema_version'"
            ).fetchone()
            return int(row["value"]) if row else 1

    def get_player_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS cnt FROM players").fetchone()
            return int(row["cnt"]) if row else 0

    def checkpoint(self) -> None:
        """Flush WAL journal cleanly into the main SQLite file."""
        with self._lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except sqlite3.Error as exc:
                logger.warning("SQLite WAL checkpoint warning: %s", exc)

    def create_local_backup(self, keep: int = 5) -> Path | None:
        """Create a consistent SQLite backup file using the native backup API."""
        with self._lock:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
            seq = self.get_save_seq()
            dest = self.backup_dir / f"rpg_backup_{ts}_seq{seq}.db"
            try:
                with sqlite3.connect(str(dest)) as backup_conn:
                    self._conn.backup(backup_conn)
                backups = sorted(
                    self.backup_dir.glob("rpg_backup_*.db"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                for old in backups[keep:]:
                    with contextlib.suppress(OSError):
                        old.unlink()
                return dest
            except (sqlite3.Error, OSError) as exc:
                logger.warning("Failed to create local RPG backup: %s", exc)
                return None

    def export_gzip_snapshot(self) -> tuple[int, bytes]:
        """Export a consistent, gzip-compressed snapshot of the entire RPG database."""
        with self._lock:
            seq = self.get_save_seq()
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                with sqlite3.connect(str(tmp_path)) as backup_conn:
                    self._conn.backup(backup_conn)
                raw = tmp_path.read_bytes()
                buf = io.BytesIO()
                with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
                    gz.write(raw)
                return seq, buf.getvalue()
            finally:
                with contextlib.suppress(OSError):
                    tmp_path.unlink(missing_ok=True)

    def export_snapshot_bytes(self) -> bytes:
        return self.export_gzip_snapshot()[1]

    def import_gzip_snapshot(self, gzip_bytes: bytes, force: bool = False) -> bool:
        """Validate and restore a gzipped SQLite snapshot if newer than local DB."""
        with self._lock:
            try:
                raw_db = gzip.decompress(gzip_bytes)
            except (OSError, EOFError, zlib.error, ValueError) as exc:
                logger.warning("Invalid gzip snapshot: %s", exc)
                return False

            with tempfile.NamedTemporaryFile(
                dir=str(self.db_path.parent), suffix=".restore.db", delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(raw_db)

            try:
                with sqlite3.connect(str(tmp_path)) as check_conn:
                    check_conn.row_factory = sqlite3.Row
                    integrity = check_conn.execute("PRAGMA integrity_check;").fetchone()
                    if not integrity or integrity[0] != "ok":
                        logger.warning("Snapshot integrity check failed.")
                        return False
                    row = check_conn.execute(
                        "SELECT value FROM rpg_meta WHERE key = 'save_seq'"
                    ).fetchone()
                    remote_seq = int(row["value"]) if row else 0
                    remote_players_row = check_conn.execute(
                        "SELECT COUNT(*) AS cnt FROM players"
                    ).fetchone()
                    remote_players = (
                        int(remote_players_row["cnt"]) if remote_players_row else 0
                    )

                local_seq = self.get_save_seq()
                local_players = self.get_player_count()

                if not force:
                    if local_players > 0 and remote_seq <= local_seq:
                        return False
                    if local_players == 0 and remote_players == 0 and remote_seq <= local_seq:
                        return False

                with contextlib.suppress(sqlite3.Error):
                    self._conn.close()
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(self.db_path) + suffix)
                    with contextlib.suppress(OSError):
                        sidecar.unlink(missing_ok=True)

                os.replace(str(tmp_path), str(self.db_path))
                self._conn = self._open_connection()
                self._init_schema()
                self._last_uploaded_seq = self.get_save_seq()
                logger.info(
                    "✅ 已從備份快照還原 RPG 資料庫（seq=%d，共 %d 位玩家）",
                    self._last_uploaded_seq,
                    self.get_player_count(),
                )
                return True
            except (sqlite3.Error, OSError, ValueError) as exc:
                logger.warning("Failed to restore RPG snapshot: %s", exc)
                try:
                    self._conn.execute("SELECT 1")
                except sqlite3.Error:
                    self._conn = self._open_connection()
                return False
            finally:
                with contextlib.suppress(OSError):
                    tmp_path.unlink(missing_ok=True)

    def import_snapshot_bytes(self, payload: bytes, force: bool = False) -> bool:
        return self.import_gzip_snapshot(payload, force=force)

    async def restore_from_discord_channel(
        self, client: Any, channel_id_str: str
    ) -> bool:
        """Restore the newest RPG snapshot from a private Discord backup channel."""
        cid = (channel_id_str or "").strip()
        if not cid or not cid.isdigit():
            return False
        try:
            channel = client.get_channel(int(cid))
            if channel is None:
                channel = await client.fetch_channel(int(cid))
            if channel is None or not hasattr(channel, "history"):
                return False

            best_seq = -1
            best_attachment = None
            async for msg in channel.history(limit=30):
                for att in getattr(msg, "attachments", []):
                    match = SNAPSHOT_FILENAME_RE.match(att.filename)
                    if match:
                        seq = int(match.group(1))
                        if seq > best_seq:
                            best_seq = seq
                            best_attachment = att

            if best_attachment is None:
                return False

            local_seq = self.get_save_seq()
            if self.get_player_count() > 0 and best_seq <= local_seq:
                self._last_uploaded_seq = local_seq
                return False

            data = await best_attachment.read()
            return self.import_gzip_snapshot(data, force=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("從 Discord 備份頻道還原 RPG 快照失敗: %s", exc)
            return False

    async def backup_to_discord_channel(
        self, client: Any, channel_id_str: str, force: bool = False, keep: int = 5
    ) -> bool:
        """Upload a compressed RPG snapshot to a private Discord backup channel."""
        import discord

        cid = (channel_id_str or "").strip()
        if not cid or not cid.isdigit():
            return False

        seq = self.get_save_seq()
        if not force and seq <= self._last_uploaded_seq:
            return False
        if self.get_player_count() == 0 and seq == 0:
            return False

        try:
            channel = client.get_channel(int(cid))
            if channel is None:
                channel = await client.fetch_channel(int(cid))
            if channel is None:
                return False

            snap_seq, gz_bytes = self.export_gzip_snapshot()
            filename = f"rpg_snapshot_seq{snap_seq}.db.gz"
            file_obj = discord.File(io.BytesIO(gz_bytes), filename=filename)
            player_count = self.get_player_count()
            await channel.send(
                content=(
                    f"💾 **RPG 自動存檔快照** ｜ 序號：`#{snap_seq}` ｜ "
                    f"玩家數：`{player_count}` ｜ 大小：`{len(gz_bytes) / 1024:.1f} KB`"
                ),
                file=file_obj,
            )
            self._last_uploaded_seq = snap_seq

            with contextlib.suppress(Exception):
                snap_msgs = []
                async for msg in channel.history(limit=25):
                    if any(
                        SNAPSHOT_FILENAME_RE.match(a.filename)
                        for a in getattr(msg, "attachments", [])
                    ):
                        snap_msgs.append(msg)
                for old_msg in snap_msgs[keep:]:
                    with contextlib.suppress(Exception):
                        await old_msg.delete()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("上傳 RPG 快照至 Discord 備份頻道失敗: %s", exc)
            return False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.checkpoint()
            self.create_local_backup()
            with contextlib.suppress(sqlite3.Error):
                self._conn.close()

    # =========================================================================
    # Player CRUD
    # =========================================================================
    @staticmethod
    def _row_to_player(row: sqlite3.Row) -> PlayerProfile:
        default_survival = {
            "auto_potion_pct": 0.40,
            "auto_crystal_pct": 0.20,
            "auto_retreat_pct": 0.15,
            "stop_on_no_potion": True,
        }
        default_filter = {
            "min_rarity": "plain",
            "min_level": 1,
            "blocked_slots": [],
        }
        return PlayerProfile(
            user_id=row["user_id"],
            display_name=row["display_name"],
            class_id=row["class_id"],
            promo_tier=int(row["promo_tier"]),
            level=int(row["level"]),
            exp=int(row["exp"]),
            rebirth_count=int(row["rebirth_count"]),
            gold=int(row["gold"]),
            gems=int(row["gems"]),
            stamina=int(row["stamina"]),
            stamina_updated_at=int(row["stamina_updated_at"]),
            pickaxe_tier=int(row["pickaxe_tier"]),
            mine_combo=int(row["mine_combo"]),
            last_mine_at=int(row["last_mine_at"]),
            last_boss_at=int(row["last_boss_at"]),
            abyss_floor=int(row["abyss_floor"]),
            abyss_highest=int(row["abyss_highest"]),
            active_title=row["active_title"],
            gacha_pity_legendary=int(row["gacha_pity_legendary"]),
            gacha_pity_mythic=int(row["gacha_pity_mythic"]),
            checkin_streak=int(row["checkin_streak"]),
            last_checkin_date=row["last_checkin_date"],
            total_checkins=int(row["total_checkins"]),
            total_mines=int(row["total_mines"]),
            total_dungeons=int(row["total_dungeons"]),
            total_enhances=int(row["total_enhances"]),
            total_boss_damage=int(row["total_boss_damage"]),
            boss_kills_participated=int(row["boss_kills_participated"]),
            combat_power=int(row["combat_power"]),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
            current_floor=int(row["current_floor"]),
            highest_cleared_floor=int(row["highest_cleared_floor"]),
            zone=str(row["zone"]),
            weapon_style=str(row["weapon_style"]),
            game_mode=str(row["game_mode"]),
            cursor_color=str(row["cursor_color"]),
            karma=int(row["karma"]),
            hp=int(row["hp"]),
            sp=int(row["sp"]),
            max_sp=int(row["max_sp"]),
            miasma_stacks=int(row["miasma_stacks"]),
            miasma_exp_stacks=int(row["miasma_exp_stacks"]),
            survival_config=_safe_json_dict(row["survival_config_json"], default_survival),
            loot_filter=_safe_json_dict(row["loot_filter_json"], default_filter),
            skill_slots=[str(s) for s in _safe_json_list(row["skill_slots_json"])],
            unique_skills=[str(s) for s in _safe_json_list(row["unique_skills_json"])],
            stat_points=int(row["stat_points"]),
            talent_points=int(row["talent_points"]),
            str_stat=int(row["str_stat"]),
            agi_stat=int(row["agi_stat"]),
            vit_stat=int(row["vit_stat"]),
            dex_stat=int(row["dex_stat"]),
            luk_stat=int(row["luk_stat"]),
            downed_until=int(row["downed_until"]),
            is_dead=bool(row["is_dead"]),
            survival_streak=int(row["survival_streak"]),
            last_death_log=str(row["last_death_log"]),
            guild_id=int(row["guild_id"]) if row["guild_id"] is not None else None,
            guild_left_at=int(row["guild_left_at"]),
            active_buffs=_safe_json_dict(row["active_buffs_json"]),
            world_boss_attempts=int(row["world_boss_attempts"]),
            world_boss_attempts_date=str(row["world_boss_attempts_date"]),
            story_choices={
                str(k): str(v) for k, v in _safe_json_dict(row["story_choices_json"]).items()
            },
            nightmare_highest=int(row["nightmare_highest"]),
            boss_rush_best=int(row["boss_rush_best"]),
            roguelike_best_score=int(row["roguelike_best_score"]),
            in_boss_battle=bool(row["in_boss_battle"]),
        )

    def get_player(self, user_id: str) -> PlayerProfile | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM players WHERE user_id = ?", (str(user_id),)
            ).fetchone()
            return self._row_to_player(row) if row else None

    def create_player(
        self,
        user_id: str,
        display_name: str,
        class_id: str,
        now_ts: int,
        *,
        weapon_style: str | None = None,
        game_mode: str = "standard",
    ) -> PlayerProfile:
        resolved_style = weapon_style or LEGACY_CLASS_TO_WEAPON_STYLE.get(
            class_id, WeaponStyle.SWORD
        )
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO players (
                    user_id, display_name, class_id, promo_tier, level, exp,
                    rebirth_count, gold, gems, stamina, stamina_updated_at,
                    pickaxe_tier, mine_combo, last_mine_at, last_boss_at,
                    abyss_floor, abyss_highest, active_title,
                    gacha_pity_legendary, gacha_pity_mythic,
                    checkin_streak, last_checkin_date, total_checkins,
                    total_mines, total_dungeons, total_enhances,
                    total_boss_damage, boss_kills_participated, combat_power,
                    created_at, updated_at, weapon_style, game_mode
                ) VALUES (
                    ?, ?, ?, 1, 1, 0,
                    0, 350, 80, 100, ?,
                    1, 0, 0, 0,
                    1, 0, '',
                    0, 0,
                    0, '', 0,
                    0, 0, 0,
                    0, 0, 0,
                    ?, ?, ?, ?
                )
                """,
                (
                    str(user_id),
                    display_name[:64],
                    class_id,
                    now_ts,
                    now_ts,
                    now_ts,
                    str(resolved_style),
                    str(game_mode),
                ),
            )
        player = self.get_player(user_id)
        assert player is not None
        return player

    def save_player(self, player: PlayerProfile) -> None:
        if not player.updated_at:
            player.updated_at = int(time.time())
        with self.transaction():
            self._conn.execute(
                """
                UPDATE players SET
                    display_name = ?, class_id = ?, promo_tier = ?,
                    level = ?, exp = ?, rebirth_count = ?,
                    gold = ?, gems = ?, stamina = ?, stamina_updated_at = ?,
                    pickaxe_tier = ?, mine_combo = ?, last_mine_at = ?, last_boss_at = ?,
                    abyss_floor = ?, abyss_highest = ?, active_title = ?,
                    gacha_pity_legendary = ?, gacha_pity_mythic = ?,
                    checkin_streak = ?, last_checkin_date = ?, total_checkins = ?,
                    total_mines = ?, total_dungeons = ?, total_enhances = ?,
                    total_boss_damage = ?, boss_kills_participated = ?,
                    combat_power = ?, updated_at = ?,
                    current_floor = ?, highest_cleared_floor = ?, zone = ?,
                    weapon_style = ?, game_mode = ?, cursor_color = ?, karma = ?,
                    hp = ?, sp = ?, max_sp = ?, miasma_stacks = ?, miasma_exp_stacks = ?,
                    survival_config_json = ?, loot_filter_json = ?,
                    skill_slots_json = ?, unique_skills_json = ?,
                    stat_points = ?, talent_points = ?,
                    str_stat = ?, agi_stat = ?, vit_stat = ?, dex_stat = ?, luk_stat = ?,
                    downed_until = ?, is_dead = ?, survival_streak = ?, last_death_log = ?,
                    guild_id = ?, guild_left_at = ?, active_buffs_json = ?,
                    world_boss_attempts = ?, world_boss_attempts_date = ?,
                    story_choices_json = ?, nightmare_highest = ?,
                    boss_rush_best = ?, roguelike_best_score = ?, in_boss_battle = ?
                WHERE user_id = ?
                """,
                (
                    player.display_name[:64],
                    player.class_id,
                    player.promo_tier,
                    player.level,
                    player.exp,
                    player.rebirth_count,
                    player.gold,
                    player.gems,
                    player.stamina,
                    player.stamina_updated_at,
                    player.pickaxe_tier,
                    player.mine_combo,
                    player.last_mine_at,
                    player.last_boss_at,
                    player.abyss_floor,
                    player.abyss_highest,
                    player.active_title,
                    player.gacha_pity_legendary,
                    player.gacha_pity_mythic,
                    player.checkin_streak,
                    player.last_checkin_date,
                    player.total_checkins,
                    player.total_mines,
                    player.total_dungeons,
                    player.total_enhances,
                    player.total_boss_damage,
                    player.boss_kills_participated,
                    player.combat_power,
                    player.updated_at,
                    player.current_floor,
                    player.highest_cleared_floor,
                    str(player.zone),
                    str(player.weapon_style),
                    str(player.game_mode),
                    str(player.cursor_color),
                    player.karma,
                    player.hp,
                    player.sp,
                    player.max_sp,
                    player.miasma_stacks,
                    player.miasma_exp_stacks,
                    json.dumps(player.survival_config, ensure_ascii=False),
                    json.dumps(player.loot_filter, ensure_ascii=False),
                    json.dumps(player.skill_slots, ensure_ascii=False),
                    json.dumps(player.unique_skills, ensure_ascii=False),
                    player.stat_points,
                    player.talent_points,
                    player.str_stat,
                    player.agi_stat,
                    player.vit_stat,
                    player.dex_stat,
                    player.luk_stat,
                    player.downed_until,
                    1 if player.is_dead else 0,
                    player.survival_streak,
                    player.last_death_log,
                    player.guild_id,
                    player.guild_left_at,
                    json.dumps(player.active_buffs, ensure_ascii=False),
                    player.world_boss_attempts,
                    player.world_boss_attempts_date,
                    json.dumps(player.story_choices, ensure_ascii=False),
                    player.nightmare_highest,
                    player.boss_rush_best,
                    player.roguelike_best_score,
                    1 if player.in_boss_battle else 0,
                    player.user_id,
                ),
            )

    # =========================================================================
    # Equipment CRUD
    # =========================================================================
    @staticmethod
    def _row_to_equipment(row: sqlite3.Row) -> EquipmentItem:
        affixes = _safe_json_dict(row["affixes_json"])
        keys = row.keys()
        return EquipmentItem(
            id=int(row["id"]),
            user_id=row["user_id"],
            template_id=row["template_id"],
            name=row["name"],
            slot=row["slot"],
            rarity=row["rarity"],
            tier=int(row["tier"]),
            set_id=row["set_id"],
            enhance_level=int(row["enhance_level"]),
            enhance_pity=int(row["enhance_pity"]),
            base_hp=int(row["base_hp"]),
            base_mp=int(row["base_mp"]),
            base_atk=int(row["base_atk"]),
            base_def=int(row["base_def"]),
            affixes={k: float(v) for k, v in affixes.items()},
            is_equipped=bool(row["is_equipped"]),
            is_locked=bool(row["is_locked"]),
            created_at=int(row["created_at"]),
            weapon_style=str(row["weapon_style"]),
            damage_type=str(row["damage_type"]),
            named_passive=str(row["named_passive"]),
            is_bound=bool(row["is_bound"]),
            min_level=int(row["min_level"]),
            escrow_state=str(row["escrow_state"]),
            base_sp=int(row["base_sp"]),
            base_spd=int(row["base_spd"]),
            temper_level=int(row["temper_level"]) if "temper_level" in keys else 0,
            socket_crystal_id=str(row["socket_crystal_id"]) if "socket_crystal_id" in keys else "",
        )

    def add_equipment(self, item: EquipmentItem) -> EquipmentItem:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO equipment (
                    user_id, template_id, name, slot, rarity, tier, set_id,
                    enhance_level, enhance_pity, base_hp, base_mp, base_atk, base_def,
                    affixes_json, is_equipped, is_locked, created_at,
                    weapon_style, damage_type, named_passive, is_bound,
                    min_level, escrow_state, base_sp, base_spd,
                    temper_level, socket_crystal_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.user_id,
                    item.template_id,
                    item.name,
                    item.slot,
                    item.rarity,
                    item.tier,
                    item.set_id,
                    item.enhance_level,
                    item.enhance_pity,
                    item.base_hp,
                    item.base_mp,
                    item.base_atk,
                    item.base_def,
                    json.dumps(item.affixes, ensure_ascii=False),
                    1 if item.is_equipped else 0,
                    1 if item.is_locked else 0,
                    item.created_at or int(time.time()),
                    item.weapon_style,
                    item.damage_type,
                    item.named_passive,
                    1 if item.is_bound else 0,
                    item.min_level,
                    item.escrow_state,
                    item.base_sp,
                    item.base_spd,
                    int(item.temper_level),
                    str(item.socket_crystal_id or ""),
                ),
            )
            assert cur.lastrowid is not None
            item.id = int(cur.lastrowid)
        return item

    def get_equipment(
        self,
        user_id: str,
        equipped_only: bool = False,
        include_escrowed: bool = False,
    ) -> list[EquipmentItem]:
        with self._lock:
            escrow_clause = "" if include_escrowed else " AND escrow_state = ''"
            if equipped_only:
                rows = self._conn.execute(
                    f"SELECT * FROM equipment WHERE user_id = ? AND is_equipped = 1{escrow_clause} "
                    "ORDER BY id ASC",
                    (str(user_id),),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    f"SELECT * FROM equipment WHERE user_id = ?{escrow_clause} "
                    "ORDER BY is_equipped DESC, tier DESC, enhance_level DESC, id DESC",
                    (str(user_id),),
                ).fetchall()
            return [self._row_to_equipment(r) for r in rows]

    def get_equipment_by_id(
        self, user_id: str, item_id: int, include_escrowed: bool = False
    ) -> EquipmentItem | None:
        with self._lock:
            escrow_clause = "" if include_escrowed else " AND escrow_state = ''"
            row = self._conn.execute(
                f"SELECT * FROM equipment WHERE id = ? AND user_id = ?{escrow_clause}",
                (int(item_id), str(user_id)),
            ).fetchone()
            return self._row_to_equipment(row) if row else None

    def update_equipment(self, item: EquipmentItem) -> None:
        with self.transaction():
            self._conn.execute(
                """
                UPDATE equipment SET
                    template_id = ?, name = ?, rarity = ?, tier = ?, set_id = ?,
                    base_hp = ?, base_mp = ?, base_atk = ?, base_def = ?,
                    enhance_level = ?, enhance_pity = ?, is_equipped = ?, is_locked = ?,
                    affixes_json = ?, weapon_style = ?, damage_type = ?,
                    named_passive = ?, is_bound = ?, min_level = ?,
                    escrow_state = ?, base_sp = ?, base_spd = ?,
                    temper_level = ?, socket_crystal_id = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    item.template_id,
                    item.name,
                    item.rarity,
                    item.tier,
                    item.set_id,
                    item.base_hp,
                    item.base_mp,
                    item.base_atk,
                    item.base_def,
                    item.enhance_level,
                    item.enhance_pity,
                    1 if item.is_equipped else 0,
                    1 if item.is_locked else 0,
                    json.dumps(item.affixes, ensure_ascii=False),
                    item.weapon_style,
                    item.damage_type,
                    item.named_passive,
                    1 if item.is_bound else 0,
                    item.min_level,
                    item.escrow_state,
                    item.base_sp,
                    item.base_spd,
                    int(item.temper_level),
                    str(item.socket_crystal_id or ""),
                    item.id,
                    item.user_id,
                ),
            )

    def equip_item(self, user_id: str, item_id: int) -> EquipmentItem | None:
        with self.transaction():
            item = self.get_equipment_by_id(user_id, item_id, include_escrowed=False)
            if item is None:
                return None
            self._conn.execute(
                "UPDATE equipment SET is_equipped = 0 WHERE user_id = ? AND slot = ?",
                (str(user_id), item.slot),
            )
            self._conn.execute(
                "UPDATE equipment SET is_equipped = 1 WHERE id = ? AND user_id = ? AND escrow_state = ''",
                (int(item_id), str(user_id)),
            )
            item.is_equipped = True
            return item

    def unequip_slot(self, user_id: str, slot: str) -> None:
        with self.transaction():
            self._conn.execute(
                "UPDATE equipment SET is_equipped = 0 WHERE user_id = ? AND slot = ?",
                (str(user_id), slot),
            )

    def delete_equipment(self, user_id: str, item_ids: list[int]) -> int:
        if not item_ids:
            return 0
        with self.transaction():
            placeholders = ",".join("?" for _ in item_ids)
            cur = self._conn.execute(
                f"DELETE FROM equipment WHERE user_id = ? AND escrow_state = '' AND id IN ({placeholders})",
                [str(user_id), *[int(i) for i in item_ids]],
            )
            return cur.rowcount

    def get_max_enhance_level(self, user_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(enhance_level), 0) AS mx FROM equipment WHERE user_id = ? AND escrow_state = ''",
                (str(user_id),),
            ).fetchone()
            return int(row["mx"]) if row else 0

    # =========================================================================
    # Inventory CRUD
    # =========================================================================
    def get_inventory(self, user_id: str) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT item_id, quantity FROM inventory WHERE user_id = ? AND quantity > 0",
                (str(user_id),),
            ).fetchall()
            return {row["item_id"]: int(row["quantity"]) for row in rows}

    def get_item_qty(self, user_id: str, item_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT quantity FROM inventory WHERE user_id = ? AND item_id = ?",
                (str(user_id), item_id),
            ).fetchone()
            return int(row["quantity"]) if row else 0

    def add_item(self, user_id: str, item_id: str, qty: int) -> int:
        if qty == 0:
            return self.get_item_qty(user_id, item_id)
        with self.transaction():
            cur_qty = self.get_item_qty(user_id, item_id)
            new_qty = max(0, cur_qty + qty)
            if new_qty == 0:
                self._conn.execute(
                    "DELETE FROM inventory WHERE user_id = ? AND item_id = ?",
                    (str(user_id), item_id),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO inventory (user_id, item_id, quantity)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, item_id) DO UPDATE SET quantity = excluded.quantity
                    """,
                    (str(user_id), item_id, new_qty),
                )
            return new_qty

    def consume_items(self, user_id: str, reqs: dict[str, int]) -> bool:
        """Atomically verify and deduct multiple item quantities."""
        with self.transaction():
            for item_id, qty in reqs.items():
                if self.get_item_qty(user_id, item_id) < qty:
                    return False
            for item_id, qty in reqs.items():
                self.add_item(user_id, item_id, -qty)
            return True

    # =========================================================================
    # Dungeon Clears (Legacy Preserved)
    # =========================================================================
    def get_dungeon_clears(self, user_id: str) -> dict[tuple[str, str], int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT dungeon_id, difficulty, clear_count FROM dungeon_clears WHERE user_id = ?",
                (str(user_id),),
            ).fetchall()
            return {(r["dungeon_id"], r["difficulty"]): int(r["clear_count"]) for r in rows}

    def record_dungeon_clear(
        self, user_id: str, dungeon_id: str, difficulty: str, now_ts: int
    ) -> bool:
        with self.transaction():
            row = self._conn.execute(
                """
                SELECT clear_count FROM dungeon_clears
                WHERE user_id = ? AND dungeon_id = ? AND difficulty = ?
                """,
                (str(user_id), dungeon_id, difficulty),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO dungeon_clears (user_id, dungeon_id, difficulty, clear_count, first_cleared_at)
                    VALUES (?, ?, ?, 1, ?)
                    """,
                    (str(user_id), dungeon_id, difficulty, now_ts),
                )
                return True
            self._conn.execute(
                """
                UPDATE dungeon_clears SET clear_count = clear_count + 1
                WHERE user_id = ? AND dungeon_id = ? AND difficulty = ?
                """,
                (str(user_id), dungeon_id, difficulty),
            )
            return False

    # =========================================================================
    # Quests & Achievements (Legacy Preserved)
    # =========================================================================
    def get_quests(
        self, user_id: str, period_type: str, period_key: str
    ) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT quest_id, progress, target, claimed FROM quests
                WHERE user_id = ? AND period_type = ? AND period_key = ?
                """,
                (str(user_id), period_type, period_key),
            ).fetchall()
            return {
                r["quest_id"]: {
                    "progress": int(r["progress"]),
                    "target": int(r["target"]),
                    "claimed": bool(r["claimed"]),
                }
                for r in rows
            }

    def increment_quest(
        self,
        user_id: str,
        period_type: str,
        period_key: str,
        quest_id: str,
        target: int,
        delta: int = 1,
    ) -> None:
        with self.transaction():
            row = self._conn.execute(
                """
                SELECT progress FROM quests
                WHERE user_id = ? AND period_type = ? AND period_key = ? AND quest_id = ?
                """,
                (str(user_id), period_type, period_key, quest_id),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO quests (user_id, period_type, period_key, quest_id, progress, target, claimed)
                    VALUES (?, ?, ?, ?, ?, ?, 0)
                    """,
                    (str(user_id), period_type, period_key, quest_id, min(target, delta), target),
                )
            else:
                new_prog = min(target, int(row["progress"]) + delta)
                self._conn.execute(
                    """
                    UPDATE quests SET progress = ?
                    WHERE user_id = ? AND period_type = ? AND period_key = ? AND quest_id = ?
                    """,
                    (new_prog, str(user_id), period_type, period_key, quest_id),
                )

    def mark_quest_claimed(
        self, user_id: str, period_type: str, period_key: str, quest_id: str
    ) -> None:
        with self.transaction():
            self._conn.execute(
                """
                UPDATE quests SET claimed = 1
                WHERE user_id = ? AND period_type = ? AND period_key = ? AND quest_id = ?
                """,
                (str(user_id), period_type, period_key, quest_id),
            )

    def get_achievements(self, user_id: str) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT achievement_id, unlocked_at FROM achievements WHERE user_id = ?",
                (str(user_id),),
            ).fetchall()
            return {r["achievement_id"]: int(r["unlocked_at"]) for r in rows}

    def unlock_achievement(
        self, user_id: str, achievement_id: str, now_ts: int
    ) -> bool:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT OR IGNORE INTO achievements (user_id, achievement_id, unlocked_at)
                VALUES (?, ?, ?)
                """,
                (str(user_id), achievement_id, now_ts),
            )
            return cur.rowcount > 0

    # =========================================================================
    # Expeditions (Legacy Preserved)
    # =========================================================================
    def get_expedition(self, user_id: str) -> ActiveExpedition | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM expeditions WHERE user_id = ?", (str(user_id),)
            ).fetchone()
            if not row:
                return None
            return ActiveExpedition(
                user_id=row["user_id"],
                expedition_id=row["expedition_id"],
                started_at=int(row["started_at"]),
                ends_at=int(row["ends_at"]),
                claimed=bool(row["claimed"]),
            )

    def set_expedition(
        self, user_id: str, expedition_id: str, started_at: int, ends_at: int
    ) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT OR REPLACE INTO expeditions (user_id, expedition_id, started_at, ends_at, claimed)
                VALUES (?, ?, ?, ?, 0)
                """,
                (str(user_id), expedition_id, started_at, ends_at),
            )

    def clear_expedition(self, user_id: str) -> None:
        with self.transaction():
            self._conn.execute(
                "DELETE FROM expeditions WHERE user_id = ?", (str(user_id),)
            )

    # =========================================================================
    # Shop Purchases Tracking (Legacy Preserved)
    # =========================================================================
    def get_shop_purchased_qty(
        self, user_id: str, shop_bucket: str, offer_key: str
    ) -> int:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT quantity FROM shop_purchases
                WHERE user_id = ? AND shop_bucket = ? AND offer_key = ?
                """,
                (str(user_id), shop_bucket, offer_key),
            ).fetchone()
            return int(row["quantity"]) if row else 0

    def get_shop_bucket_purchases(
        self, user_id: str, shop_bucket: str
    ) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT offer_key, quantity FROM shop_purchases
                WHERE user_id = ? AND shop_bucket = ?
                """,
                (str(user_id), shop_bucket),
            ).fetchall()
            return {r["offer_key"]: int(r["quantity"]) for r in rows}

    def record_shop_purchase(
        self, user_id: str, shop_bucket: str, offer_key: str, qty: int = 1
    ) -> None:
        with self.transaction():
            cur = self.get_shop_purchased_qty(user_id, shop_bucket, offer_key)
            self._conn.execute(
                """
                INSERT OR REPLACE INTO shop_purchases (user_id, shop_bucket, offer_key, quantity)
                VALUES (?, ?, ?, ?)
                """,
                (str(user_id), shop_bucket, offer_key, cur + qty),
            )

    # =========================================================================
    # World Boss (Legacy + SAO Floor/Accelerated World Extended)
    # =========================================================================
    @staticmethod
    def _row_to_boss(row: sqlite3.Row) -> WorldBossState:
        return WorldBossState(
            id=int(row["id"]),
            tier=int(row["tier"]),
            boss_id=row["boss_id"],
            name=row["name"],
            max_hp=int(row["max_hp"]),
            current_hp=int(row["current_hp"]),
            atk=int(row["atk"]),
            def_=int(row["def_"]),
            status=row["status"],
            spawned_at=int(row["spawned_at"]),
            defeated_at=int(row["defeated_at"]) if row["defeated_at"] is not None else None,
            killer_user_id=row["killer_user_id"],
            floor=int(row["floor"]),
            accelerated_buff_hours=int(row["accelerated_buff_hours"]),
        )

    def get_active_world_boss(self) -> WorldBossState | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM world_boss WHERE status = 'active' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return self._row_to_boss(row) if row else None

    def get_latest_world_boss_tier(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(tier), 0) AS mx FROM world_boss"
            ).fetchone()
            return int(row["mx"]) if row else 0

    def create_world_boss(
        self,
        tier: int,
        boss_id: str,
        name: str,
        max_hp: int,
        atk: int,
        def_: int,
        now_ts: int,
        *,
        floor: int = 1,
        accelerated_buff_hours: int = 2,
    ) -> WorldBossState:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO world_boss (
                    tier, boss_id, name, max_hp, current_hp, atk, def_,
                    status, spawned_at, floor, accelerated_buff_hours
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    tier,
                    boss_id,
                    name,
                    max_hp,
                    max_hp,
                    atk,
                    def_,
                    now_ts,
                    floor,
                    accelerated_buff_hours,
                ),
            )
            assert cur.lastrowid is not None
            boss_row = self._conn.execute(
                "SELECT * FROM world_boss WHERE id = ?", (int(cur.lastrowid),)
            ).fetchone()
            assert boss_row is not None
            return self._row_to_boss(boss_row)

    def update_world_boss(self, boss: WorldBossState) -> None:
        with self.transaction():
            self._conn.execute(
                """
                UPDATE world_boss SET
                    current_hp = ?, status = ?, defeated_at = ?, killer_user_id = ?
                WHERE id = ?
                """,
                (
                    boss.current_hp,
                    boss.status,
                    boss.defeated_at,
                    boss.killer_user_id,
                    boss.id,
                ),
            )

    def record_world_boss_damage(
        self,
        boss_instance_id: int,
        user_id: str,
        display_name: str,
        damage: int,
        now_ts: int,
    ) -> None:
        with self.transaction():
            row = self._conn.execute(
                """
                SELECT total_damage, attacks_count FROM world_boss_damage
                WHERE boss_instance_id = ? AND user_id = ?
                """,
                (boss_instance_id, str(user_id)),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO world_boss_damage (
                        boss_instance_id, user_id, display_name, total_damage, attacks_count, last_attack_at
                    ) VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (boss_instance_id, str(user_id), display_name[:64], damage, now_ts),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE world_boss_damage
                    SET display_name = ?, total_damage = total_damage + ?, attacks_count = attacks_count + 1, last_attack_at = ?
                    WHERE boss_instance_id = ? AND user_id = ?
                    """,
                    (display_name[:64], damage, now_ts, boss_instance_id, str(user_id)),
                )

    def get_world_boss_rankings(
        self, boss_instance_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT user_id, display_name, total_damage, attacks_count
                FROM world_boss_damage
                WHERE boss_instance_id = ?
                ORDER BY total_damage DESC
                LIMIT ?
                """,
                (boss_instance_id, limit),
            ).fetchall()
            return [
                {
                    "user_id": r["user_id"],
                    "display_name": r["display_name"],
                    "total_damage": int(r["total_damage"]),
                    "attacks_count": int(r["attacks_count"]),
                }
                for r in rows
            ]

    # =========================================================================
    # Leaderboards (Legacy + SAO Categories)
    # =========================================================================
    def get_leaderboard(
        self, category: str, limit: int = 10
    ) -> list[PlayerProfile]:
        order_sql = _LEADERBOARD_ORDER_SQL.get(category, _LEADERBOARD_ORDER_SQL["power"])
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM players ORDER BY {order_sql} LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_player(r) for r in rows]

    def get_player_rank(self, user_id: str, category: str) -> tuple[int | None, int]:
        """Return (1-based rank, total_players) for the specified leaderboard category."""
        order_sql = _LEADERBOARD_ORDER_SQL.get(category, _LEADERBOARD_ORDER_SQL["power"])
        with self._lock:
            rows = self._conn.execute(
                f"SELECT user_id FROM players ORDER BY {order_sql}"
            ).fetchall()
            total = len(rows)
            for idx, r in enumerate(rows, start=1):
                if r["user_id"] == str(user_id):
                    return idx, total
            return None, total

    # =========================================================================
    # SAO v2: Atomic Server First-Kill & Tower Progress & Floor Exploration
    # =========================================================================
    def claim_server_floor_first_kill(
        self,
        floor: int,
        boss_id: str,
        boss_name: str,
        leader_id: str,
        leader_name: str,
        la_user_id: str,
        la_user_name: str,
        participant_ids: list[str],
        cleared_at: int,
    ) -> bool:
        """Atomically claim server First-Kill on `floor`. Returns True strictly once per floor."""
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT OR IGNORE INTO server_floor_clears (
                    floor, boss_id, boss_name, leader_id, leader_name,
                    la_user_id, la_user_name, participant_ids_json, party_size, cleared_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(floor),
                    str(boss_id),
                    str(boss_name),
                    str(leader_id),
                    str(leader_name)[:64],
                    str(la_user_id),
                    str(la_user_name)[:64],
                    json.dumps([str(p) for p in participant_ids], ensure_ascii=False),
                    max(1, len(participant_ids)),
                    int(cleared_at),
                ),
            )
            return cur.rowcount == 1

    # Convenient alias matching blueprint/test naming
    claim_floor_first_kill = claim_server_floor_first_kill

    def get_server_floor_clear(self, floor: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM server_floor_clears WHERE floor = ?", (int(floor),)
            ).fetchone()
            if not row:
                return None
            return {
                "floor": int(row["floor"]),
                "boss_id": row["boss_id"],
                "boss_name": row["boss_name"],
                "leader_id": row["leader_id"],
                "leader_name": row["leader_name"],
                "la_user_id": row["la_user_id"],
                "la_user_name": row["la_user_name"],
                "participant_ids": _safe_json_list(row["participant_ids_json"]),
                "party_size": int(row["party_size"]),
                "cleared_at": int(row["cleared_at"]),
            }

    def get_all_server_floor_clears(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM server_floor_clears ORDER BY floor ASC"
            ).fetchall()
            return [
                {
                    "floor": int(r["floor"]),
                    "boss_id": r["boss_id"],
                    "boss_name": r["boss_name"],
                    "leader_id": r["leader_id"],
                    "leader_name": r["leader_name"],
                    "la_user_id": r["la_user_id"],
                    "la_user_name": r["la_user_name"],
                    "participant_ids": _safe_json_list(r["participant_ids_json"]),
                    "party_size": int(r["party_size"]),
                    "cleared_at": int(r["cleared_at"]),
                }
                for r in rows
            ]

    def get_server_frontline_floor(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(floor), 0) AS mx FROM server_floor_clears"
            ).fetchone()
            mx = int(row["mx"]) if row else 0
            return min(100, mx + 1)

    def record_tower_clear(
        self,
        user_id: str,
        floor: int,
        now_ts: int | None = None,
        *,
        turns: int = 0,
        is_team_boss: bool = False,
        today_key: str = "",
    ) -> dict[str, Any]:
        ts = int(now_ts if now_ts is not None else time.time())
        with self.transaction():
            self._conn.execute(
                """
                UPDATE players
                SET highest_cleared_floor = MAX(highest_cleared_floor, ?), updated_at = ?
                WHERE user_id = ?
                """,
                (int(floor), ts, str(user_id)),
            )
            row = self._conn.execute(
                "SELECT * FROM tower_progress WHERE user_id = ? AND floor = ?",
                (str(user_id), int(floor)),
            ).fetchone()
            if row is None:
                daily_clears = 1 if is_team_boss else 0
                self._conn.execute(
                    """
                    INSERT INTO tower_progress (
                        user_id, floor, clear_count, first_cleared_at, best_turns,
                        daily_team_clears, daily_team_date
                    ) VALUES (?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        str(user_id),
                        int(floor),
                        ts,
                        max(0, int(turns)),
                        daily_clears,
                        today_key if is_team_boss else "",
                    ),
                )
                return {
                    "first_personal_clear": True,
                    "clear_count": 1,
                    "daily_team_clears": daily_clears,
                }

            clear_count = int(row["clear_count"]) + 1
            prev_best = int(row["best_turns"])
            best_turns = (
                int(turns)
                if turns > 0 and (prev_best == 0 or turns < prev_best)
                else prev_best
            )
            daily_date = str(row["daily_team_date"])
            daily_clears = int(row["daily_team_clears"])
            if is_team_boss:
                if daily_date != today_key:
                    daily_clears = 1
                    daily_date = today_key
                else:
                    daily_clears += 1

            self._conn.execute(
                """
                UPDATE tower_progress SET
                    clear_count = ?, best_turns = ?,
                    daily_team_clears = ?, daily_team_date = ?
                WHERE user_id = ? AND floor = ?
                """,
                (clear_count, best_turns, daily_clears, daily_date, str(user_id), int(floor)),
            )
            return {
                "first_personal_clear": False,
                "clear_count": clear_count,
                "daily_team_clears": daily_clears,
            }

    def unlock_floor(
        self, user_id: str, floor: int, now_ts: int | None = None
    ) -> None:
        """Unlock access to target Aincrad floor (1..100) by ensuring prior clear threshold."""
        target = max(1, min(100, int(floor)))
        ts = int(now_ts if now_ts is not None else time.time())
        if target <= 1:
            return
        with self.transaction():
            self._conn.execute(
                """
                UPDATE players
                SET highest_cleared_floor = MAX(highest_cleared_floor, ?), updated_at = ?
                WHERE user_id = ?
                """,
                (target - 1, ts, str(user_id)),
            )


    def get_tower_progress(
        self, user_id: str, floor: int | None = None
    ) -> dict[int, dict[str, Any]]:
        with self._lock:
            if floor is not None:
                rows = self._conn.execute(
                    "SELECT * FROM tower_progress WHERE user_id = ? AND floor = ?",
                    (str(user_id), int(floor)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM tower_progress WHERE user_id = ? ORDER BY floor ASC",
                    (str(user_id),),
                ).fetchall()
            return {
                int(r["floor"]): {
                    "floor": int(r["floor"]),
                    "clear_count": int(r["clear_count"]),
                    "first_cleared_at": int(r["first_cleared_at"]),
                    "best_turns": int(r["best_turns"]),
                    "daily_team_clears": int(r["daily_team_clears"]),
                    "daily_team_date": str(r["daily_team_date"]),
                }
                for r in rows
            }

    def get_floor_exploration(self, user_id: str, floor: int) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM floor_exploration WHERE user_id = ? AND floor = ?",
                (str(user_id), int(floor)),
            ).fetchone()
            if not row:
                return {
                    "user_id": str(user_id),
                    "floor": int(floor),
                    "progress_pct": 0,
                    "field_boss_cleared": False,
                    "boss_gate_unlocked": False,
                    "pending_chest": None,
                    "updated_at": 0,
                }
            pending = _safe_json_dict(row["pending_chest_json"])
            return {
                "user_id": row["user_id"],
                "floor": int(row["floor"]),
                "progress_pct": int(row["progress_pct"]),
                "field_boss_cleared": bool(row["field_boss_cleared"]),
                "boss_gate_unlocked": bool(row["boss_gate_unlocked"]),
                "pending_chest": pending if pending else None,
                "updated_at": int(row["updated_at"]),
            }

    def save_floor_exploration(
        self,
        user_id: str,
        floor: int,
        progress_pct: int,
        field_boss_cleared: bool,
        boss_gate_unlocked: bool,
        pending_chest: dict[str, Any] | None,
        now_ts: int,
    ) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO floor_exploration (
                    user_id, floor, progress_pct, field_boss_cleared,
                    boss_gate_unlocked, pending_chest_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, floor) DO UPDATE SET
                    progress_pct = excluded.progress_pct,
                    field_boss_cleared = excluded.field_boss_cleared,
                    boss_gate_unlocked = excluded.boss_gate_unlocked,
                    pending_chest_json = excluded.pending_chest_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(user_id),
                    int(floor),
                    max(0, min(100, int(progress_pct))),
                    1 if field_boss_cleared else 0,
                    1 if boss_gate_unlocked else 0,
                    json.dumps(pending_chest, ensure_ascii=False) if pending_chest else "",
                    int(now_ts),
                ),
            )

    # =========================================================================
    # SAO v2: Atomic Pending Loot Mailbox (Named / LA / Set Overflow)
    # =========================================================================
    def enqueue_pending_loot(
        self,
        user_id: str,
        source: str,
        item_type: str,
        payload: dict[str, Any],
        now_ts: int,
    ) -> int:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO pending_loot (user_id, source, item_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(user_id),
                    str(source),
                    str(item_type),
                    json.dumps(payload, ensure_ascii=False),
                    int(now_ts),
                ),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_pending_loot(
        self, user_id: str, unclaimed_only: bool = True
    ) -> list[dict[str, Any]]:
        with self._lock:
            clause = " AND claimed_at IS NULL" if unclaimed_only else ""
            rows = self._conn.execute(
                f"SELECT * FROM pending_loot WHERE user_id = ?{clause} ORDER BY id ASC",
                (str(user_id),),
            ).fetchall()
            return [
                {
                    "id": int(r["id"]),
                    "user_id": r["user_id"],
                    "source": r["source"],
                    "item_type": r["item_type"],
                    "payload": _safe_json_dict(r["payload_json"]),
                    "created_at": int(r["created_at"]),
                    "claimed_at": int(r["claimed_at"]) if r["claimed_at"] is not None else None,
                }
                for r in rows
            ]

    def claim_pending_loot_entry(
        self, user_id: str, loot_id: int, now_ts: int
    ) -> dict[str, Any] | None:
        """Atomically mark a pending loot entry claimed; returns None if already claimed or missing."""
        with self.transaction():
            cur = self._conn.execute(
                """
                UPDATE pending_loot SET claimed_at = ?
                WHERE id = ? AND user_id = ? AND claimed_at IS NULL
                """,
                (int(now_ts), int(loot_id), str(user_id)),
            )
            if cur.rowcount != 1:
                return None
            row = self._conn.execute(
                "SELECT * FROM pending_loot WHERE id = ?", (int(loot_id),)
            ).fetchone()
            if not row:
                return None
            return {
                "id": int(row["id"]),
                "user_id": row["user_id"],
                "source": row["source"],
                "item_type": row["item_type"],
                "payload": _safe_json_dict(row["payload_json"]),
                "created_at": int(row["created_at"]),
                "claimed_at": int(row["claimed_at"]),
            }

    # =========================================================================
    # SAO v2: Mastery, Talents, Loadouts, Monument, Argo Intel, Yui Logs, Turn-Ins
    # =========================================================================
    def get_mastery(self, user_id: str) -> dict[str, dict[str, int]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT skill_key, level, exp FROM player_mastery WHERE user_id = ?",
                (str(user_id),),
            ).fetchall()
            return {
                r["skill_key"]: {"level": int(r["level"]), "exp": int(r["exp"])}
                for r in rows
            }

    def set_floor_exploration(
        self,
        user_id: str,
        floor: int,
        progress_pct: int,
        now_ts: int | None = None,
    ) -> None:
        pct = max(0, min(100, int(progress_pct)))
        ts = int(now_ts if now_ts is not None else time.time())
        self.save_floor_exploration(
            user_id,
            floor,
            pct,
            field_boss_cleared=pct >= 100,
            boss_gate_unlocked=pct >= 100,
            pending_chest=None,
            now_ts=ts,
        )

    def upsert_mastery(self, user_id: str, skill_key: str, level: int, exp: int = 0) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO player_mastery (user_id, skill_key, level, exp)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, skill_key) DO UPDATE SET
                    level = excluded.level,
                    exp = excluded.exp
                """,
                (str(user_id), str(skill_key), int(level), int(exp)),
            )

    def get_talents(self, user_id: str) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT talent_id, rank FROM player_talents WHERE user_id = ?",
                (str(user_id),),
            ).fetchall()
            return {r["talent_id"]: int(r["rank"]) for r in rows}

    def set_talent_rank(self, user_id: str, talent_id: str, rank: int) -> None:
        with self.transaction():
            if rank <= 0:
                self._conn.execute(
                    "DELETE FROM player_talents WHERE user_id = ? AND talent_id = ?",
                    (str(user_id), str(talent_id)),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO player_talents (user_id, talent_id, rank)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, talent_id) DO UPDATE SET rank = excluded.rank
                    """,
                    (str(user_id), str(talent_id), int(rank)),
                )

    def clear_talents(self, user_id: str) -> int:
        with self.transaction():
            row = self._conn.execute(
                "SELECT COALESCE(SUM(rank), 0) AS total FROM player_talents WHERE user_id = ?",
                (str(user_id),),
            ).fetchone()
            refunded = int(row["total"]) if row else 0
            self._conn.execute(
                "DELETE FROM player_talents WHERE user_id = ?", (str(user_id),)
            )
            return refunded

    def save_gear_loadout(
        self, user_id: str, slot_index: int, name: str, gear_ids: list[int], now_ts: int
    ) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO gear_loadouts (user_id, slot_index, name, gear_ids_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, slot_index) DO UPDATE SET
                    name = excluded.name,
                    gear_ids_json = excluded.gear_ids_json,
                    updated_at = excluded.updated_at
                """,
                (
                    str(user_id),
                    int(slot_index),
                    str(name)[:48],
                    json.dumps([int(g) for g in gear_ids]),
                    int(now_ts),
                ),
            )

    def get_gear_loadouts(self, user_id: str) -> dict[int, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM gear_loadouts WHERE user_id = ? ORDER BY slot_index ASC",
                (str(user_id),),
            ).fetchall()
            return {
                int(r["slot_index"]): {
                    "slot_index": int(r["slot_index"]),
                    "name": r["name"],
                    "gear_ids": [int(x) for x in _safe_json_list(r["gear_ids_json"])],
                    "updated_at": int(r["updated_at"]),
                }
                for r in rows
            }

    def record_monument_event(
        self,
        user_id: str,
        display_name: str,
        event_type: str,
        floor: int,
        game_mode: str,
        cause: str,
        last_log: list[str],
        now_ts: int,
    ) -> int:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO monument_of_life (
                    user_id, display_name, event_type, floor, game_mode, cause, last_log_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(user_id),
                    str(display_name)[:64],
                    str(event_type),
                    int(floor),
                    str(game_mode),
                    str(cause),
                    json.dumps(last_log, ensure_ascii=False),
                    int(now_ts),
                ),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_monument_summary(
        self, limit: int = 10, now_ts: int | None = None
    ) -> dict[str, Any]:
        with self._lock:
            if now_ts is None:
                counts = self._conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN is_dead = 1 THEN 1 ELSE 0 END) AS fallen,
                        SUM(CASE WHEN is_dead = 0 AND downed_until > 0 THEN 1 ELSE 0 END) AS downed
                    FROM players
                    """
                ).fetchone()
            else:
                counts = self._conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN is_dead = 1 THEN 1 ELSE 0 END) AS fallen,
                        SUM(CASE WHEN is_dead = 0 AND downed_until > ? THEN 1 ELSE 0 END) AS downed
                    FROM players
                    """,
                    (int(now_ts),),
                ).fetchone()
            total = int(counts["total"]) if counts and counts["total"] is not None else 0
            fallen = int(counts["fallen"]) if counts and counts["fallen"] is not None else 0
            downed = int(counts["downed"]) if counts and counts["downed"] is not None else 0
            alive = max(0, total - fallen - downed)

            rows = self._conn.execute(
                "SELECT * FROM monument_of_life ORDER BY created_at DESC, id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            entries = [
                {
                    "id": int(r["id"]),
                    "user_id": r["user_id"],
                    "display_name": r["display_name"],
                    "event_type": r["event_type"],
                    "floor": int(r["floor"]),
                    "game_mode": r["game_mode"],
                    "cause": r["cause"],
                    "last_log": _safe_json_list(r["last_log_json"]),
                    "created_at": int(r["created_at"]),
                }
                for r in rows
            ]
            return {
                "total": total,
                "alive": alive,
                "downed": downed,
                "fallen": fallen,
                "entries": entries,
            }

    def record_boss_intel_seen(
        self, user_id: str, boss_id: str, skill_id: str, now_ts: int
    ) -> bool:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT OR IGNORE INTO boss_intel_seen (user_id, boss_id, skill_id, first_seen_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(user_id), str(boss_id), str(skill_id), int(now_ts)),
            )
            return cur.rowcount == 1

    def get_boss_intel_seen(
        self, user_id: str, boss_id: str | None = None
    ) -> dict[str, list[str]]:
        with self._lock:
            if boss_id is not None:
                rows = self._conn.execute(
                    "SELECT boss_id, skill_id FROM boss_intel_seen WHERE user_id = ? AND boss_id = ? ORDER BY first_seen_at ASC",
                    (str(user_id), str(boss_id)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT boss_id, skill_id FROM boss_intel_seen WHERE user_id = ? ORDER BY boss_id ASC, first_seen_at ASC",
                    (str(user_id),),
                ).fetchall()
            out: dict[str, list[str]] = {}
            for r in rows:
                out.setdefault(str(r["boss_id"]), []).append(str(r["skill_id"]))
            return out

    def unlock_yui_log(self, user_id: str, log_id: str, now_ts: int) -> bool:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT OR IGNORE INTO yui_logs (user_id, log_id, unlocked_at)
                VALUES (?, ?, ?)
                """,
                (str(user_id), str(log_id), int(now_ts)),
            )
            return cur.rowcount == 1

    def get_yui_logs(self, user_id: str) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT log_id, unlocked_at FROM yui_logs WHERE user_id = ? ORDER BY unlocked_at ASC",
                (str(user_id),),
            ).fetchall()
            return {str(r["log_id"]): int(r["unlocked_at"]) for r in rows}

    def record_achievement_turnin(
        self,
        user_id: str,
        turnin_key: str,
        item_name: str,
        rarity: str,
        bonus: dict[str, float],
        now_ts: int,
    ) -> bool:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT OR IGNORE INTO achievement_turnins (
                    user_id, turnin_key, item_name, rarity, bonus_json, turned_in_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(user_id),
                    str(turnin_key),
                    str(item_name),
                    str(rarity),
                    json.dumps(bonus, ensure_ascii=False),
                    int(now_ts),
                ),
            )
            return cur.rowcount == 1

    def get_achievement_turnins(self, user_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM achievement_turnins WHERE user_id = ? ORDER BY turned_in_at ASC",
                (str(user_id),),
            ).fetchall()
            return [
                {
                    "turnin_key": r["turnin_key"],
                    "item_name": r["item_name"],
                    "rarity": r["rarity"],
                    "bonus": {
                        k: float(v) for k, v in _safe_json_dict(r["bonus_json"]).items()
                    },
                    "turned_in_at": int(r["turned_in_at"]),
                }
                for r in rows
            ]

    # =========================================================================
    # SAO v2: Real-Human Parties & Raid History
    # =========================================================================
    def save_party(self, lobby: PartyLobby) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO parties (
                    party_id, leader_id, floor, boss_mode, max_size,
                    is_raid_alliance, status, channel_id, message_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(party_id) DO UPDATE SET
                    leader_id = excluded.leader_id,
                    floor = excluded.floor,
                    boss_mode = excluded.boss_mode,
                    max_size = excluded.max_size,
                    is_raid_alliance = excluded.is_raid_alliance,
                    status = excluded.status,
                    channel_id = excluded.channel_id,
                    message_id = excluded.message_id,
                    updated_at = excluded.updated_at
                """,
                (
                    lobby.party_id,
                    lobby.leader_id,
                    lobby.floor,
                    str(lobby.boss_mode),
                    lobby.max_size,
                    1 if lobby.is_raid_alliance else 0,
                    lobby.status,
                    lobby.channel_id,
                    lobby.message_id,
                    lobby.created_at,
                    lobby.updated_at or int(time.time()),
                ),
            )
            self._conn.execute(
                "DELETE FROM party_members WHERE party_id = ?", (lobby.party_id,)
            )
            for member in lobby.members.values():
                self._conn.execute(
                    """
                    INSERT INTO party_members (
                        party_id, user_id, role, is_ready, potion_sharing,
                        frontline_stance, joined_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lobby.party_id,
                        member.user_id,
                        member.role,
                        1 if member.is_ready else 0,
                        1 if member.potion_sharing else 0,
                        1 if member.frontline_stance else 0,
                        member.joined_at,
                    ),
                )

    def _hydrate_party_locked(self, row: sqlite3.Row) -> PartyLobby:
        member_rows = self._conn.execute(
            """
            SELECT pm.*, p.display_name, p.weapon_style, p.level, p.combat_power
            FROM party_members pm
            JOIN players p ON p.user_id = pm.user_id
            WHERE pm.party_id = ?
            ORDER BY pm.joined_at ASC
            """,
            (row["party_id"],),
        ).fetchall()
        members: dict[str, PartyMemberState] = {}
        for m in member_rows:
            members[m["user_id"]] = PartyMemberState(
                user_id=m["user_id"],
                display_name=m["display_name"],
                role=m["role"],
                weapon_style=m["weapon_style"],
                level=int(m["level"]),
                combat_power=int(m["combat_power"]),
                is_ready=bool(m["is_ready"]),
                potion_sharing=bool(m["potion_sharing"]),
                frontline_stance=bool(m["frontline_stance"]),
                joined_at=int(m["joined_at"]),
            )
        return PartyLobby(
            party_id=row["party_id"],
            leader_id=row["leader_id"],
            floor=int(row["floor"]),
            boss_mode=row["boss_mode"],
            max_size=int(row["max_size"]),
            is_raid_alliance=bool(row["is_raid_alliance"]),
            status=row["status"],
            members=members,
            channel_id=int(row["channel_id"]) if row["channel_id"] is not None else None,
            message_id=int(row["message_id"]) if row["message_id"] is not None else None,
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )

    def get_party(self, party_id: str) -> PartyLobby | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM parties WHERE party_id = ?", (str(party_id),)
            ).fetchone()
            return self._hydrate_party_locked(row) if row else None

    def get_user_active_party(self, user_id: str) -> PartyLobby | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT p.* FROM parties p
                JOIN party_members pm ON pm.party_id = p.party_id
                WHERE pm.user_id = ? AND p.status != 'disbanded'
                ORDER BY p.updated_at DESC LIMIT 1
                """,
                (str(user_id),),
            ).fetchone()
            return self._hydrate_party_locked(row) if row else None

    def delete_party(self, party_id: str) -> None:
        with self.transaction():
            self._conn.execute("DELETE FROM parties WHERE party_id = ?", (str(party_id),))

    def record_raid_history(
        self,
        raid_id: str,
        party_id: str,
        floor: int,
        boss_id: str,
        boss_mode: str,
        victory: bool,
        is_first_kill: bool,
        la_user_id: str,
        participants: list[str],
        turns_taken: int,
        started_at: int,
        ended_at: int,
    ) -> int:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO raid_history (
                    raid_id, party_id, floor, boss_id, boss_mode, victory,
                    is_first_kill, la_user_id, participants_json, turns_taken,
                    started_at, ended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(raid_id),
                    str(party_id),
                    int(floor),
                    str(boss_id),
                    str(boss_mode),
                    1 if victory else 0,
                    1 if is_first_kill else 0,
                    str(la_user_id),
                    json.dumps([str(p) for p in participants], ensure_ascii=False),
                    int(turns_taken),
                    int(started_at),
                    int(ended_at),
                ),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_raid_history(
        self, floor: int | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self._lock:
            if floor is not None:
                rows = self._conn.execute(
                    "SELECT * FROM raid_history WHERE floor = ? ORDER BY ended_at DESC LIMIT ?",
                    (int(floor), int(limit)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM raid_history ORDER BY ended_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            return [
                {
                    "id": int(r["id"]),
                    "raid_id": r["raid_id"],
                    "party_id": r["party_id"],
                    "floor": int(r["floor"]),
                    "boss_id": r["boss_id"],
                    "boss_mode": r["boss_mode"],
                    "victory": bool(r["victory"]),
                    "is_first_kill": bool(r["is_first_kill"]),
                    "la_user_id": r["la_user_id"],
                    "participants": _safe_json_list(r["participants_json"]),
                    "turns_taken": int(r["turns_taken"]),
                    "started_at": int(r["started_at"]),
                    "ended_at": int(r["ended_at"]),
                }
                for r in rows
            ]

    # =========================================================================
    # SAO v2: Guilds, Atomic Warehouse Escrow, Logs & Guild Quests
    # =========================================================================
    def _row_to_guild_locked(self, row: sqlite3.Row) -> GuildInfo:
        cnt_row = self._conn.execute(
            "SELECT COUNT(*) AS cnt FROM guild_members WHERE guild_id = ?",
            (int(row["id"]),),
        ).fetchone()
        member_count = int(cnt_row["cnt"]) if cnt_row else 0
        return GuildInfo(
            id=int(row["id"]),
            name=row["name"],
            tag=row["tag"],
            leader_id=row["leader_id"],
            level=int(row["level"]),
            exp=int(row["exp"]),
            vault_col=int(row["vault_col"]),
            merit_points=int(row["merit_points"]),
            ranks_config=_safe_json_dict(row["ranks_config_json"]),
            member_count=member_count,
            max_members=int(row["max_members"]),
            active_buff_id=row["active_buff_id"],
            active_buff_expires_at=int(row["active_buff_expires_at"]),
            raid_last_started_at=int(row["raid_last_started_at"]),
            created_at=int(row["created_at"]),
        )

    def create_guild(
        self,
        name: str,
        tag: str,
        leader_id: str,
        ranks_config: dict[str, Any],
        now_ts: int,
    ) -> GuildInfo:
        with self.transaction():
            try:
                cur = self._conn.execute(
                    """
                    INSERT INTO guilds (name, tag, leader_id, ranks_config_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        name.strip()[:32],
                        tag.strip().upper()[:6],
                        str(leader_id),
                        json.dumps(ranks_config, ensure_ascii=False),
                        int(now_ts),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise GameError("公會名稱或縮寫已被其他公會使用。", code="GUILD_NAME_TAKEN") from exc
            assert cur.lastrowid is not None
            guild_id = int(cur.lastrowid)
            self._conn.execute(
                """
                INSERT INTO guild_members (user_id, guild_id, rank_name, joined_at)
                VALUES (?, ?, 'leader', ?)
                """,
                (str(leader_id), guild_id, int(now_ts)),
            )
            self._conn.execute(
                "UPDATE players SET guild_id = ?, updated_at = ? WHERE user_id = ?",
                (guild_id, int(now_ts), str(leader_id)),
            )
            row = self._conn.execute(
                "SELECT * FROM guilds WHERE id = ?", (guild_id,)
            ).fetchone()
            assert row is not None
            return self._row_to_guild_locked(row)

    def get_guild(self, guild_id: int) -> GuildInfo | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM guilds WHERE id = ?", (int(guild_id),)
            ).fetchone()
            return self._row_to_guild_locked(row) if row else None

    def get_guild_by_user(self, user_id: str) -> GuildInfo | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT g.* FROM guilds g
                JOIN guild_members gm ON gm.guild_id = g.id
                WHERE gm.user_id = ?
                """,
                (str(user_id),),
            ).fetchone()
            return self._row_to_guild_locked(row) if row else None

    def update_guild(self, guild: GuildInfo) -> None:
        with self.transaction():
            self._conn.execute(
                """
                UPDATE guilds SET
                    name = ?, tag = ?, leader_id = ?, level = ?, exp = ?,
                    vault_col = ?, merit_points = ?, ranks_config_json = ?,
                    max_members = ?, active_buff_id = ?,
                    active_buff_expires_at = ?, raid_last_started_at = ?
                WHERE id = ?
                """,
                (
                    guild.name,
                    guild.tag,
                    guild.leader_id,
                    guild.level,
                    guild.exp,
                    guild.vault_col,
                    guild.merit_points,
                    json.dumps(guild.ranks_config, ensure_ascii=False),
                    guild.max_members,
                    guild.active_buff_id,
                    guild.active_buff_expires_at,
                    guild.raid_last_started_at,
                    guild.id,
                ),
            )

    def add_guild_member(
        self, guild_id: int, user_id: str, rank_name: str, now_ts: int
    ) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO guild_members (user_id, guild_id, rank_name, joined_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(user_id), int(guild_id), str(rank_name), int(now_ts)),
            )
            self._conn.execute(
                "UPDATE players SET guild_id = ?, updated_at = ? WHERE user_id = ?",
                (int(guild_id), int(now_ts), str(user_id)),
            )

    def remove_guild_member(self, guild_id: int, user_id: str, now_ts: int) -> None:
        with self.transaction():
            self._conn.execute(
                "DELETE FROM guild_members WHERE guild_id = ? AND user_id = ?",
                (int(guild_id), str(user_id)),
            )
            self._conn.execute(
                "UPDATE players SET guild_id = NULL, guild_left_at = ?, updated_at = ? WHERE user_id = ?",
                (int(now_ts), int(now_ts), str(user_id)),
            )

    def get_guild_members(self, guild_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT gm.*, p.display_name, p.level, p.combat_power, p.highest_cleared_floor
                FROM guild_members gm
                JOIN players p ON p.user_id = gm.user_id
                WHERE gm.guild_id = ?
                ORDER BY gm.contribution_col DESC, gm.joined_at ASC
                """,
                (int(guild_id),),
            ).fetchall()
            return [
                {
                    "user_id": r["user_id"],
                    "guild_id": int(r["guild_id"]),
                    "display_name": r["display_name"],
                    "rank_name": r["rank_name"],
                    "contribution_col": int(r["contribution_col"]),
                    "merit": int(r["merit"]),
                    "level": int(r["level"]),
                    "combat_power": int(r["combat_power"]),
                    "highest_cleared_floor": int(r["highest_cleared_floor"]),
                    "joined_at": int(r["joined_at"]),
                }
                for r in rows
            ]

    def update_guild_member(
        self,
        guild_id: int,
        user_id: str,
        *,
        rank_name: str | None = None,
        add_col: int = 0,
        add_merit: int = 0,
    ) -> None:
        with self.transaction():
            if rank_name is not None:
                self._conn.execute(
                    "UPDATE guild_members SET rank_name = ? WHERE guild_id = ? AND user_id = ?",
                    (str(rank_name), int(guild_id), str(user_id)),
                )
            if add_col != 0 or add_merit != 0:
                self._conn.execute(
                    """
                    UPDATE guild_members
                    SET contribution_col = contribution_col + ?, merit = merit + ?
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (int(add_col), int(add_merit), int(guild_id), str(user_id)),
                )

    def get_guild_leaderboard(self, limit: int = 10) -> list[GuildInfo]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM guilds ORDER BY level DESC, exp DESC, vault_col DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [self._row_to_guild_locked(r) for r in rows]

    def deposit_guild_warehouse_equipment(
        self,
        guild_id: int,
        user_id: str,
        equipment_id: int,
        snapshot: dict[str, Any],
        now_ts: int,
    ) -> int:
        with self.transaction():
            cur = self._conn.execute(
                """
                UPDATE equipment SET escrow_state = 'guild_warehouse'
                WHERE id = ? AND user_id = ? AND is_equipped = 0
                  AND is_locked = 0 AND is_bound = 0 AND escrow_state = ''
                """,
                (int(equipment_id), str(user_id)),
            )
            if cur.rowcount != 1:
                raise GameError(
                    "該裝備無法存入公會倉庫（可能裝備中、已鎖定、綁定或已託管）。",
                    code="WAREHOUSE_DEPOSIT_DENIED",
                )
            wcur = self._conn.execute(
                """
                INSERT INTO guild_warehouse (
                    guild_id, item_type, equipment_id, item_id, quantity,
                    item_snapshot_json, deposited_by, deposited_at, status
                ) VALUES (?, 'equipment', ?, NULL, 1, ?, ?, ?, 'stored')
                """,
                (
                    int(guild_id),
                    int(equipment_id),
                    json.dumps(snapshot, ensure_ascii=False),
                    str(user_id),
                    int(now_ts),
                ),
            )
            assert wcur.lastrowid is not None
            return int(wcur.lastrowid)

    def withdraw_guild_warehouse_item(
        self, guild_id: int, user_id: str, warehouse_id: int, now_ts: int
    ) -> dict[str, Any]:
        with self.transaction():
            cur = self._conn.execute(
                """
                UPDATE guild_warehouse
                SET status = 'withdrawn', withdrawn_by = ?, withdrawn_at = ?
                WHERE id = ? AND guild_id = ? AND status = 'stored'
                """,
                (str(user_id), int(now_ts), int(warehouse_id), int(guild_id)),
            )
            if cur.rowcount != 1:
                raise GameError("公會倉庫物品不存在或已被其他成員領取。", code="WAREHOUSE_ITEM_GONE")
            row = self._conn.execute(
                "SELECT * FROM guild_warehouse WHERE id = ?", (int(warehouse_id),)
            ).fetchone()
            assert row is not None
            if row["item_type"] == "equipment" and row["equipment_id"] is not None:
                eq_cur = self._conn.execute(
                    """
                    UPDATE equipment SET user_id = ?, escrow_state = '', is_equipped = 0
                    WHERE id = ? AND escrow_state = 'guild_warehouse'
                    """,
                    (str(user_id), int(row["equipment_id"])),
                )
                if eq_cur.rowcount != 1:
                    raise GameError("倉庫託管裝備狀態異常。", code="WAREHOUSE_ESCROW_ERROR")
            elif row["item_type"] == "item" and row["item_id"] is not None:
                self.add_item(str(user_id), str(row["item_id"]), int(row["quantity"]))
            return {
                "id": int(row["id"]),
                "guild_id": int(row["guild_id"]),
                "item_type": row["item_type"],
                "equipment_id": int(row["equipment_id"]) if row["equipment_id"] is not None else None,
                "item_id": row["item_id"],
                "quantity": int(row["quantity"]),
                "item_snapshot": _safe_json_dict(row["item_snapshot_json"]),
                "deposited_by": row["deposited_by"],
                "withdrawn_by": str(user_id),
            }

    def get_guild_warehouse(
        self, guild_id: int, stored_only: bool = True
    ) -> list[dict[str, Any]]:
        with self._lock:
            clause = " AND status = 'stored'" if stored_only else ""
            rows = self._conn.execute(
                f"SELECT * FROM guild_warehouse WHERE guild_id = ?{clause} ORDER BY id DESC",
                (int(guild_id),),
            ).fetchall()
            return [
                {
                    "id": int(r["id"]),
                    "guild_id": int(r["guild_id"]),
                    "item_type": r["item_type"],
                    "equipment_id": int(r["equipment_id"]) if r["equipment_id"] is not None else None,
                    "item_id": r["item_id"],
                    "quantity": int(r["quantity"]),
                    "item_snapshot": _safe_json_dict(r["item_snapshot_json"]),
                    "deposited_by": r["deposited_by"],
                    "deposited_at": int(r["deposited_at"]),
                    "status": r["status"],
                    "withdrawn_by": r["withdrawn_by"],
                    "withdrawn_at": int(r["withdrawn_at"]) if r["withdrawn_at"] is not None else None,
                }
                for r in rows
            ]

    def add_guild_log(
        self, guild_id: int, actor_id: str, action: str, detail: str, now_ts: int
    ) -> None:
        with self.transaction():
            self._conn.execute(
                """
                INSERT INTO guild_logs (guild_id, actor_id, action, detail, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(guild_id), str(actor_id), str(action), str(detail), int(now_ts)),
            )

    def get_guild_logs(self, guild_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM guild_logs WHERE guild_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (int(guild_id), int(limit)),
            ).fetchall()
            return [
                {
                    "id": int(r["id"]),
                    "guild_id": int(r["guild_id"]),
                    "actor_id": r["actor_id"],
                    "action": r["action"],
                    "detail": r["detail"],
                    "created_at": int(r["created_at"]),
                }
                for r in rows
            ]

    def get_guild_quests(
        self, guild_id: int, period_type: str, period_key: str
    ) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT quest_id, progress, target, completed FROM guild_quests
                WHERE guild_id = ? AND period_type = ? AND period_key = ?
                """,
                (int(guild_id), str(period_type), str(period_key)),
            ).fetchall()
            return {
                r["quest_id"]: {
                    "progress": int(r["progress"]),
                    "target": int(r["target"]),
                    "completed": bool(r["completed"]),
                }
                for r in rows
            }

    def increment_guild_quest(
        self,
        guild_id: int,
        period_type: str,
        period_key: str,
        quest_id: str,
        target: int,
        delta: int = 1,
    ) -> bool:
        with self.transaction():
            row = self._conn.execute(
                """
                SELECT progress, completed FROM guild_quests
                WHERE guild_id = ? AND period_type = ? AND period_key = ? AND quest_id = ?
                """,
                (int(guild_id), str(period_type), str(period_key), str(quest_id)),
            ).fetchone()
            if row is None:
                prog = min(target, delta)
                done = 1 if prog >= target else 0
                self._conn.execute(
                    """
                    INSERT INTO guild_quests (guild_id, period_type, period_key, quest_id, progress, target, completed)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (int(guild_id), str(period_type), str(period_key), str(quest_id), prog, target, done),
                )
                return bool(done)
            was_done = bool(row["completed"])
            new_prog = min(target, int(row["progress"]) + delta)
            now_done = 1 if new_prog >= target else 0
            self._conn.execute(
                """
                UPDATE guild_quests SET progress = ?, completed = ?
                WHERE guild_id = ? AND period_type = ? AND period_key = ? AND quest_id = ?
                """,
                (new_prog, now_done, int(guild_id), str(period_type), str(period_key), str(quest_id)),
            )
            return (not was_done) and bool(now_done)

    # =========================================================================
    # SAO v2: Atomic Player Marketplace Escrow
    # =========================================================================
    @staticmethod
    def _row_to_listing(row: sqlite3.Row) -> MarketListing:
        return MarketListing(
            id=int(row["id"]),
            seller_id=row["seller_id"],
            seller_name=row["seller_name"],
            item_type=row["item_type"],
            equipment_id=int(row["equipment_id"]) if row["equipment_id"] is not None else None,
            item_id=row["item_id"],
            quantity=int(row["quantity"]),
            item_name=row["item_name"],
            slot=row["slot"],
            weapon_style=row["weapon_style"],
            rarity=row["rarity"],
            affix_keys=[str(k) for k in _safe_json_list(row["affix_keys_json"])],
            item_snapshot=_safe_json_dict(row["item_snapshot_json"]),
            price_col=int(row["price_col"]),
            status=row["status"],
            buyer_id=row["buyer_id"],
            created_at=int(row["created_at"]),
            sold_at=int(row["sold_at"]) if row["sold_at"] is not None else None,
        )

    def create_market_listing(
        self,
        seller_id: str,
        seller_name: str,
        *,
        item_type: str,
        price_col: int,
        now_ts: int,
        equipment_id: int | None = None,
        item_id: str | None = None,
        quantity: int = 1,
        item_name: str = "",
        slot: str = "",
        weapon_style: str = "",
        rarity: str = "",
        affix_keys: list[str] | None = None,
        item_snapshot: dict[str, Any] | None = None,
    ) -> MarketListing:
        if price_col <= 0:
            raise GameError("市集定價必須大於 0 柯爾。", code="INVALID_PRICE")
        with self.transaction():
            if item_type == "equipment":
                if equipment_id is None:
                    raise GameError("缺少上架裝備編號。", code="MISSING_EQUIPMENT_ID")
                cur = self._conn.execute(
                    """
                    UPDATE equipment SET escrow_state = 'market'
                    WHERE id = ? AND user_id = ? AND is_equipped = 0
                      AND is_locked = 0 AND is_bound = 0 AND rarity != 'named'
                      AND escrow_state = ''
                    """,
                    (int(equipment_id), str(seller_id)),
                )
                if cur.rowcount != 1:
                    raise GameError(
                        "此裝備無法上架市集（名品、綁定、鎖定、裝備中或已在託管狀態）。",
                        code="LISTING_EQUIPMENT_DENIED",
                    )
            elif item_type == "item":
                if not item_id or quantity <= 0:
                    raise GameError("無效的上架物品或數量。", code="INVALID_LISTING_ITEM")
                if not self.consume_items(str(seller_id), {str(item_id): int(quantity)}):
                    raise GameError("背包內物品數量不足，無法上架。", code="INSUFFICIENT_ITEM")
            else:
                raise GameError(f"不支援的市集商品類型：{item_type}", code="INVALID_ITEM_TYPE")

            lcur = self._conn.execute(
                """
                INSERT INTO market_listings (
                    seller_id, seller_name, item_type, equipment_id, item_id, quantity,
                    item_name, slot, weapon_style, rarity, affix_keys_json,
                    item_snapshot_json, price_col, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    str(seller_id),
                    str(seller_name)[:64],
                    str(item_type),
                    int(equipment_id) if equipment_id is not None else None,
                    str(item_id) if item_id is not None else None,
                    int(quantity),
                    str(item_name),
                    str(slot),
                    str(weapon_style),
                    str(rarity),
                    json.dumps(affix_keys or [], ensure_ascii=False),
                    json.dumps(item_snapshot or {}, ensure_ascii=False),
                    int(price_col),
                    int(now_ts),
                ),
            )
            assert lcur.lastrowid is not None
            row = self._conn.execute(
                "SELECT * FROM market_listings WHERE id = ?", (int(lcur.lastrowid),)
            ).fetchone()
            assert row is not None
            return self._row_to_listing(row)

    def buy_market_listing(
        self, listing_id: int, buyer_id: str, now_ts: int
    ) -> MarketListing:
        """Atomically purchase an active marketplace listing under BEGIN IMMEDIATE."""
        with self.transaction():
            row = self._conn.execute(
                "SELECT * FROM market_listings WHERE id = ?", (int(listing_id),)
            ).fetchone()
            if not row or row["status"] != "active":
                raise GameError("此商品已被他人買走或已下架。", code="LISTING_NOT_ACTIVE")
            if str(row["seller_id"]) == str(buyer_id):
                raise GameError("無法購買自己上架的商品。", code="SELF_PURCHASE_FORBIDDEN")

            price = int(row["price_col"])
            claim_cur = self._conn.execute(
                """
                UPDATE market_listings
                SET status = 'sold', buyer_id = ?, sold_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (str(buyer_id), int(now_ts), int(listing_id)),
            )
            if claim_cur.rowcount != 1:
                raise GameError("此商品已被他人買走或已下架。", code="LISTING_NOT_ACTIVE")

            debit_cur = self._conn.execute(
                """
                UPDATE players SET gold = gold - ?, updated_at = ?
                WHERE user_id = ? AND gold >= ?
                """,
                (price, int(now_ts), str(buyer_id), price),
            )
            if debit_cur.rowcount != 1:
                raise GameError("柯爾不足，無法購買此商品！", code="INSUFFICIENT_COL")

            self._conn.execute(
                "UPDATE players SET gold = gold + ?, updated_at = ? WHERE user_id = ?",
                (price, int(now_ts), str(row["seller_id"])),
            )

            if row["item_type"] == "equipment" and row["equipment_id"] is not None:
                eq_cur = self._conn.execute(
                    """
                    UPDATE equipment SET user_id = ?, escrow_state = '', is_equipped = 0
                    WHERE id = ? AND escrow_state = 'market'
                    """,
                    (str(buyer_id), int(row["equipment_id"])),
                )
                if eq_cur.rowcount != 1:
                    raise GameError("市集託管裝備異常，交易已回滾。", code="MARKET_ESCROW_ERROR")
            elif row["item_type"] == "item" and row["item_id"] is not None:
                self.add_item(str(buyer_id), str(row["item_id"]), int(row["quantity"]))

            sold_row = self._conn.execute(
                "SELECT * FROM market_listings WHERE id = ?", (int(listing_id),)
            ).fetchone()
            assert sold_row is not None
            return self._row_to_listing(sold_row)

    def cancel_market_listing(self, listing_id: int, seller_id: str) -> MarketListing:
        with self.transaction():
            row = self._conn.execute(
                "SELECT * FROM market_listings WHERE id = ? AND seller_id = ?",
                (int(listing_id), str(seller_id)),
            ).fetchone()
            if not row or row["status"] != "active":
                raise GameError("找不到可下架的市集商品。", code="LISTING_NOT_ACTIVE")
            cur = self._conn.execute(
                """
                UPDATE market_listings SET status = 'cancelled'
                WHERE id = ? AND seller_id = ? AND status = 'active'
                """,
                (int(listing_id), str(seller_id)),
            )
            if cur.rowcount != 1:
                raise GameError("找不到可下架的市集商品。", code="LISTING_NOT_ACTIVE")
            if row["item_type"] == "equipment" and row["equipment_id"] is not None:
                self._conn.execute(
                    "UPDATE equipment SET escrow_state = '' WHERE id = ? AND user_id = ? AND escrow_state = 'market'",
                    (int(row["equipment_id"]), str(seller_id)),
                )
            elif row["item_type"] == "item" and row["item_id"] is not None:
                self.add_item(str(seller_id), str(row["item_id"]), int(row["quantity"]))
            updated = self._conn.execute(
                "SELECT * FROM market_listings WHERE id = ?", (int(listing_id),)
            ).fetchone()
            assert updated is not None
            return self._row_to_listing(updated)

    def search_market_listings(
        self,
        *,
        weapon_style: str | None = None,
        slot: str | None = None,
        rarity: str | None = None,
        affix1: str | None = None,
        affix2: str | None = None,
        max_price: int | None = None,
        limit: int = 25,
    ) -> list[MarketListing]:
        clauses = ["status = 'active'"]
        params: list[Any] = []
        if weapon_style:
            clauses.append("weapon_style = ?")
            params.append(str(weapon_style))
        if slot:
            clauses.append("slot = ?")
            params.append(str(slot))
        if rarity:
            clauses.append("rarity = ?")
            params.append(str(rarity))
        if max_price is not None:
            clauses.append("price_col <= ?")
            params.append(int(max_price))

        where_sql = " AND ".join(clauses)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM market_listings WHERE {where_sql} ORDER BY price_col ASC, id ASC",
                params,
            ).fetchall()
            results: list[MarketListing] = []
            for r in rows:
                listing = self._row_to_listing(r)
                if affix1 and affix1 not in listing.affix_keys:
                    continue
                if affix2 and affix2 not in listing.affix_keys:
                    continue
                results.append(listing)
                if len(results) >= limit:
                    break
            return results

    def get_lowest_market_price(
        self,
        *,
        item_id: str | None = None,
        slot: str | None = None,
        rarity: str | None = None,
    ) -> int | None:
        clauses = ["status = 'active'"]
        params: list[Any] = []
        if item_id:
            clauses.append("item_id = ?")
            params.append(str(item_id))
        if slot:
            clauses.append("slot = ?")
            params.append(str(slot))
        if rarity:
            clauses.append("rarity = ?")
            params.append(str(rarity))
        where_sql = " AND ".join(clauses)
        with self._lock:
            row = self._conn.execute(
                f"SELECT MIN(price_col) AS min_price FROM market_listings WHERE {where_sql}",
                params,
            ).fetchone()
            return int(row["min_price"]) if row and row["min_price"] is not None else None

    # =========================================================================
    # SAO v2: PvP Duels & World Buffs / Big Pot Stew
    # =========================================================================
    def record_duel_result(
        self,
        duel_id: str,
        challenger_id: str,
        target_id: str,
        mode: str,
        wager_col: int,
        winner_id: str,
        turns: int,
        now_ts: int,
    ) -> int:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO duel_records (
                    duel_id, challenger_id, target_id, mode, wager_col, winner_id, turns, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(duel_id),
                    str(challenger_id),
                    str(target_id),
                    str(mode),
                    int(wager_col),
                    str(winner_id),
                    int(turns),
                    int(now_ts),
                ),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_duel_stats(self, user_id: str) -> dict[str, int]:
        uid = str(user_id)
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN winner_id = ? THEN 1 ELSE 0 END) AS wins
                FROM duel_records
                WHERE challenger_id = ? OR target_id = ?
                """,
                (uid, uid, uid),
            ).fetchone()
            total = int(row["total"]) if row and row["total"] is not None else 0
            wins = int(row["wins"]) if row and row["wins"] is not None else 0
            return {"wins": wins, "losses": max(0, total - wins), "total": total}

    def create_world_buff(
        self,
        buff_key: str,
        scope_type: str,
        scope_id: str,
        name: str,
        payload: dict[str, Any],
        expires_at: int,
        now_ts: int,
        *,
        created_by: str = "",
        charges: int = -1,
    ) -> int:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO world_buffs (
                    buff_key, scope_type, scope_id, name, payload_json,
                    charges_remaining, claimed_by_json, created_by, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)
                """,
                (
                    str(buff_key),
                    str(scope_type),
                    str(scope_id),
                    str(name),
                    json.dumps(payload, ensure_ascii=False),
                    int(charges),
                    str(created_by),
                    int(now_ts),
                    int(expires_at),
                ),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_active_world_buffs(
        self, scope_type: str, scope_id: str, now_ts: int
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM world_buffs
                WHERE scope_type = ? AND scope_id = ? AND expires_at > ?
                ORDER BY id DESC
                """,
                (str(scope_type), str(scope_id), int(now_ts)),
            ).fetchall()
            return [
                {
                    "id": int(r["id"]),
                    "buff_key": r["buff_key"],
                    "scope_type": r["scope_type"],
                    "scope_id": r["scope_id"],
                    "name": r["name"],
                    "payload": _safe_json_dict(r["payload_json"]),
                    "charges_remaining": int(r["charges_remaining"]),
                    "claimed_by": [str(u) for u in _safe_json_list(r["claimed_by_json"])],
                    "created_by": r["created_by"],
                    "created_at": int(r["created_at"]),
                    "expires_at": int(r["expires_at"]),
                }
                for r in rows
            ]

    def claim_world_buff_charge(
        self, buff_id: int, user_id: str, now_ts: int
    ) -> dict[str, Any]:
        """Atomically claim one serving of a Big Pot Stew or scoped buff."""
        uid = str(user_id)
        with self.transaction():
            row = self._conn.execute(
                "SELECT * FROM world_buffs WHERE id = ? AND expires_at > ?",
                (int(buff_id), int(now_ts)),
            ).fetchone()
            if not row:
                raise GameError("此增益或一大鍋已過期或不存在。", code="BUFF_EXPIRED")
            claimed = [str(u) for u in _safe_json_list(row["claimed_by_json"])]
            if uid in claimed:
                raise GameError("你已經領取過這鍋料理的增益了。", code="ALREADY_CLAIMED_STEW")
            charges = int(row["charges_remaining"])
            if charges == 0:
                raise GameError("這一大鍋已經被盛光了！", code="STEW_EMPTY")
            new_charges = charges - 1 if charges > 0 else charges
            claimed.append(uid)
            self._conn.execute(
                """
                UPDATE world_buffs
                SET charges_remaining = ?, claimed_by_json = ?
                WHERE id = ?
                """,
                (new_charges, json.dumps(claimed, ensure_ascii=False), int(buff_id)),
            )
            return {
                "id": int(row["id"]),
                "buff_key": row["buff_key"],
                "name": row["name"],
                "payload": _safe_json_dict(row["payload_json"]),
                "charges_remaining": new_charges,
                "expires_at": int(row["expires_at"]),
            }
