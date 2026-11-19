"""SQLite persistence layer with WAL durability, local backups, and optional Discord snapshot sync."""

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
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from src.rpg.models import (
    ActiveExpedition,
    EquipmentItem,
    PlayerProfile,
    WorldBossState,
)

logger = logging.getLogger("val-dc-rpg-db")

SCHEMA_VERSION = 1
SNAPSHOT_FILENAME_RE = re.compile(r"^rpg_snapshot_seq(\d+)\.db\.gz$")

SCHEMA_SQL = """
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
"""


class RPGDatabase:
    """Thread-safe, durable SQLite storage for all RPG players and world state."""

    def __init__(self, db_path: str = "data/rpg.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir = self.db_path.parent / "backups"
        self._lock = threading.RLock()
        self._tx_depth = 0
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
                "INSERT OR IGNORE INTO rpg_meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO rpg_meta (key, value) VALUES ('save_seq', '0')"
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO rpg_meta (key, value) VALUES ('updated_at', ?)",
                (now_str,),
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
                    try:
                        self._conn.execute("ROLLBACK;")
                    except sqlite3.Error:
                        pass
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

    def create_local_backup(self, keep: int = 5) -> Optional[Path]:
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
                    try:
                        old.unlink()
                    except OSError:
                        pass
                return dest
            except Exception as exc:
                logger.warning("Failed to create local RPG backup: %s", exc)
                return None

    def export_gzip_snapshot(self) -> Tuple[int, bytes]:
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
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def import_gzip_snapshot(self, gzip_bytes: bytes, force: bool = False) -> bool:
        """Validate and restore a gzipped SQLite snapshot if newer than local DB."""
        with self._lock:
            try:
                raw_db = gzip.decompress(gzip_bytes)
            except Exception as exc:
                logger.warning("Invalid gzip snapshot: %s", exc)
                return False

            with tempfile.NamedTemporaryFile(
                dir=str(self.db_path.parent), suffix=".restore.db", delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(raw_db)

            try:
                # Verify SQLite integrity and inspect save_seq before replacing live DB
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

                # Close current DB cleanly, remove WAL/SHM sidecars, atomically replace
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(self.db_path) + suffix)
                    try:
                        sidecar.unlink(missing_ok=True)
                    except OSError:
                        pass

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
            except Exception as exc:
                logger.warning("Failed to restore RPG snapshot: %s", exc)
                # Ensure connection is still open if restore failed before swap
                try:
                    self._conn.execute("SELECT 1")
                except sqlite3.Error:
                    self._conn = self._open_connection()
                return False
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

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
        except Exception as exc:
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

            # Prune older bot snapshot messages to keep the backup channel tidy
            try:
                snap_msgs = []
                async for msg in channel.history(limit=25):
                    if any(
                        SNAPSHOT_FILENAME_RE.match(a.filename)
                        for a in getattr(msg, "attachments", [])
                    ):
                        snap_msgs.append(msg)
                for old_msg in snap_msgs[keep:]:
                    try:
                        await old_msg.delete()
                    except Exception:
                        pass
            except Exception:
                pass
            return True
        except Exception as exc:
            logger.warning("上傳 RPG 快照至 Discord 備份頻道失敗: %s", exc)
            return False

    def close(self) -> None:
        with self._lock:
            self.checkpoint()
            self.create_local_backup()
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    # =========================================================================
    # Player CRUD
    # =========================================================================
    @staticmethod
    def _row_to_player(row: sqlite3.Row) -> PlayerProfile:
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
        )

    def get_player(self, user_id: str) -> Optional[PlayerProfile]:
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
    ) -> PlayerProfile:
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
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?, 1, 1, 0,
                    0, 350, 80, 100, ?,
                    1, 0, 0, 0,
                    1, 0, '',
                    0, 0,
                    0, '', 0,
                    0, 0, 0,
                    0, 0, 0,
                    ?, ?
                )
                """,
                (str(user_id), display_name[:64], class_id, now_ts, now_ts, now_ts),
            )
        player = self.get_player(user_id)
        assert player is not None
        return player

    def save_player(self, player: PlayerProfile) -> None:
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
                    combat_power = ?, updated_at = ?
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
                    player.user_id,
                ),
            )

    # =========================================================================
    # Equipment CRUD
    # =========================================================================
    @staticmethod
    def _row_to_equipment(row: sqlite3.Row) -> EquipmentItem:
        try:
            affixes = json.loads(row["affixes_json"]) if row["affixes_json"] else {}
        except json.JSONDecodeError:
            affixes = {}
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
        )

    def add_equipment(self, item: EquipmentItem) -> EquipmentItem:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO equipment (
                    user_id, template_id, name, slot, rarity, tier, set_id,
                    enhance_level, enhance_pity, base_hp, base_mp, base_atk, base_def,
                    affixes_json, is_equipped, is_locked, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            item.id = int(cur.lastrowid)
        return item

    def get_equipment(self, user_id: str, equipped_only: bool = False) -> List[EquipmentItem]:
        with self._lock:
            if equipped_only:
                rows = self._conn.execute(
                    "SELECT * FROM equipment WHERE user_id = ? AND is_equipped = 1 ORDER BY id ASC",
                    (str(user_id),),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM equipment WHERE user_id = ? ORDER BY is_equipped DESC, tier DESC, enhance_level DESC, id DESC",
                    (str(user_id),),
                ).fetchall()
            return [self._row_to_equipment(r) for r in rows]

    def get_equipment_by_id(self, user_id: str, item_id: int) -> Optional[EquipmentItem]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM equipment WHERE id = ? AND user_id = ?",
                (int(item_id), str(user_id)),
            ).fetchone()
            return self._row_to_equipment(row) if row else None

    def update_equipment(self, item: EquipmentItem) -> None:
        with self.transaction():
            self._conn.execute(
                """
                UPDATE equipment SET
                    enhance_level = ?, enhance_pity = ?, is_equipped = ?, is_locked = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    item.enhance_level,
                    item.enhance_pity,
                    1 if item.is_equipped else 0,
                    1 if item.is_locked else 0,
                    item.id,
                    item.user_id,
                ),
            )

    def equip_item(self, user_id: str, item_id: int) -> Optional[EquipmentItem]:
        with self.transaction():
            item = self.get_equipment_by_id(user_id, item_id)
            if item is None:
                return None
            self._conn.execute(
                "UPDATE equipment SET is_equipped = 0 WHERE user_id = ? AND slot = ?",
                (str(user_id), item.slot),
            )
            self._conn.execute(
                "UPDATE equipment SET is_equipped = 1 WHERE id = ? AND user_id = ?",
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

    def delete_equipment(self, user_id: str, item_ids: List[int]) -> int:
        if not item_ids:
            return 0
        with self.transaction():
            placeholders = ",".join("?" for _ in item_ids)
            cur = self._conn.execute(
                f"DELETE FROM equipment WHERE user_id = ? AND id IN ({placeholders})",
                [str(user_id), *[int(i) for i in item_ids]],
            )
            return cur.rowcount

    def get_max_enhance_level(self, user_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(enhance_level), 0) AS mx FROM equipment WHERE user_id = ?",
                (str(user_id),),
            ).fetchone()
            return int(row["mx"]) if row else 0

    # =========================================================================
    # Inventory CRUD
    # =========================================================================
    def get_inventory(self, user_id: str) -> Dict[str, int]:
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

    def consume_items(self, user_id: str, reqs: Dict[str, int]) -> bool:
        """Atomically verify and deduct multiple item quantities."""
        with self.transaction():
            for item_id, qty in reqs.items():
                if self.get_item_qty(user_id, item_id) < qty:
                    return False
            for item_id, qty in reqs.items():
                self.add_item(user_id, item_id, -qty)
            return True

    # =========================================================================
    # Dungeon Clears
    # =========================================================================
    def get_dungeon_clears(self, user_id: str) -> Dict[Tuple[str, str], int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT dungeon_id, difficulty, clear_count FROM dungeon_clears WHERE user_id = ?",
                (str(user_id),),
            ).fetchall()
            return {
                (r["dungeon_id"], r["difficulty"]): int(r["clear_count"]) for r in rows
            }

    def record_dungeon_clear(
        self, user_id: str, dungeon_id: str, difficulty: str, now_ts: int
    ) -> bool:
        """Record a clear and return True if this was the player's first clear."""
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
    # Quests & Achievements
    # =========================================================================
    def get_quests(
        self, user_id: str, period_type: str, period_key: str
    ) -> Dict[str, Dict[str, Any]]:
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

    def get_achievements(self, user_id: str) -> Dict[str, int]:
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
    # Expeditions
    # =========================================================================
    def get_expedition(self, user_id: str) -> Optional[ActiveExpedition]:
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
    # Shop Purchases Tracking
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
    ) -> Dict[str, int]:
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
    # World Boss
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
        )

    def get_active_world_boss(self) -> Optional[WorldBossState]:
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
    ) -> WorldBossState:
        with self.transaction():
            cur = self._conn.execute(
                """
                INSERT INTO world_boss (tier, boss_id, name, max_hp, current_hp, atk, def_, status, spawned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (tier, boss_id, name, max_hp, max_hp, atk, def_, now_ts),
            )
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
    ) -> List[Dict[str, Any]]:
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
    # Leaderboards
    # =========================================================================
    def get_leaderboard(
        self, category: str, limit: int = 10
    ) -> List[PlayerProfile]:
        order_map = {
            "power": "combat_power DESC, rebirth_count DESC, level DESC",
            "level": "rebirth_count DESC, level DESC, exp DESC",
            "abyss": "abyss_highest DESC, combat_power DESC",
            "gold": "gold DESC, combat_power DESC",
            "mining": "total_mines DESC, pickaxe_tier DESC",
            "boss": "total_boss_damage DESC, boss_kills_participated DESC",
        }
        order_sql = order_map.get(category, order_map["power"])
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM players ORDER BY {order_sql} LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_player(r) for r in rows]

    def get_player_rank(self, user_id: str, category: str) -> Tuple[Optional[int], int]:
        """Return (1-based rank, total_players) for the specified leaderboard category."""
        order_map = {
            "power": "combat_power DESC, rebirth_count DESC, level DESC",
            "level": "rebirth_count DESC, level DESC, exp DESC",
            "abyss": "abyss_highest DESC, combat_power DESC",
            "gold": "gold DESC, combat_power DESC",
            "mining": "total_mines DESC, pickaxe_tier DESC",
            "boss": "total_boss_damage DESC, boss_kills_participated DESC",
        }
        order_sql = order_map.get(category, order_map["power"])
        with self._lock:
            rows = self._conn.execute(
                f"SELECT user_id FROM players ORDER BY {order_sql}"
            ).fetchall()
            total = len(rows)
            for idx, r in enumerate(rows, start=1):
                if r["user_id"] == str(user_id):
                    return idx, total
            return None, total
