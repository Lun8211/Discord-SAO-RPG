import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
from typing import IO, Optional, Sequence

import discord
from discord import app_commands
from discord.ext import tasks

from src.config import Settings
from src.rpg.commands import register_rpg_commands
from src.rpg.database import RPGDatabase
from src.rpg.engine import RPGEngine

# 避免繁體中文 Windows (cp950) 輸出 Emoji 時發生編碼錯誤
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
)
logger = logging.getLogger("rpg-dc-bot")

settings = Settings.from_env()

ALREADY_RUNNING_EXIT_CODE = 2
MISSING_TOKEN_EXIT_CODE = 3


def configure_file_logging(log_file: str) -> RotatingFileHandler:
    """Attach a UTF-8 rotating file handler to the root logger."""
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    resolved = str(log_path.resolve())
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", None) == resolved:
            return handler
    handler = RotatingFileHandler(
        resolved,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    root.addHandler(handler)
    return handler


class SingleInstanceLock:
    """OS-level non-blocking file lock + PID file to prevent duplicate bot processes."""

    def __init__(self, control_dir: Path | str = "data") -> None:
        self.control_dir = Path(control_dir)
        self.lock_path = self.control_dir / "bot.lock"
        self.pid_path = self.control_dir / "bot.pid"
        self._handle: Optional[IO[bytes]] = None

    def acquire(self) -> bool:
        self.control_dir.mkdir(parents=True, exist_ok=True)
        handle = open(self.lock_path, "a+b")
        try:
            handle.seek(0)
            if len(handle.read(1)) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False

        self._handle = handle
        try:
            self.pid_path.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if self.pid_path.exists() and self.pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                self.pid_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None


class RPGBot(discord.Client):
    def __init__(self, run_minutes: int = 0) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.run_minutes = run_minutes
        self.stop_signal_path: Optional[Path] = None
        self._synced_guilds = False
        self._rpg_restore_started = False
        self._rpg_restored = False
        self._closing_started = False
        self.rpg_db = RPGDatabase(db_path=settings.rpg_db_path)
        self.rpg_engine = RPGEngine(
            db=self.rpg_db,
            timezone_offset_hours=settings.timezone_offset_hours,
        )
        register_rpg_commands(self.tree, self.rpg_engine)

    async def setup_hook(self) -> None:
        # 採用全域斜線指令註冊，避免在各伺服器出現重複指令
        await self.tree.sync()
        self.rpg_backup_task.change_interval(minutes=settings.rpg_backup_interval_minutes)
        self.rpg_backup_task.start()
        if self.stop_signal_path is not None:
            asyncio.create_task(self._watch_stop_signal())
        if self.run_minutes > 0:
            asyncio.create_task(self._auto_shutdown_after(self.run_minutes))

    async def _watch_stop_signal(self) -> None:
        while not self.is_closed():
            if self.stop_signal_path is not None and self.stop_signal_path.exists():
                logger.info("🛑 收到安全停止訊號，正在完成存檔並關閉機器人...")
                await self.close()
                return
            await asyncio.sleep(2.0)

    async def _auto_shutdown_after(self, minutes: int) -> None:
        await self.wait_until_ready()
        logger.info("⏳ 機器人將於 %d 分鐘後自動安全下線...", minutes)
        await asyncio.sleep(minutes * 60)
        logger.info("⏹️ 已達設定執行時間 (%d 分鐘)，正在存檔並安全關閉機器人...", minutes)
        await self.close()

    async def close(self) -> None:
        # 關機前務必完成 RPG SQLite checkpoint、本地備份與（若已設定）雲端備份上傳
        if not self._closing_started:
            self._closing_started = True
            try:
                if settings.rpg_backup_channel_id and self.is_ready() and self._rpg_restored:
                    uploaded = await self.rpg_db.backup_to_discord_channel(
                        self, settings.rpg_backup_channel_id, force=False
                    )
                    if uploaded:
                        logger.info("💾 關機前已完成 RPG 雲端快照備份。")
            except Exception as exc:
                logger.warning("關機前上傳 RPG 雲端備份失敗: %s", exc)
            try:
                self.rpg_db.close()
                logger.info("💾 RPG 資料庫已完成 checkpoint 與本地備份。")
            except Exception as exc:
                logger.warning("關閉 RPG 資料庫時發生警告: %s", exc)
        await super().close()

    async def on_ready(self) -> None:
        # 若設定了 RPG_BACKUP_CHANNEL_ID，開機時自動檢查並還原較新的雲端存檔快照
        if not self._rpg_restore_started:
            self._rpg_restore_started = True
            try:
                if settings.rpg_backup_channel_id:
                    await self.rpg_db.restore_from_discord_channel(
                        self, settings.rpg_backup_channel_id
                    )
            finally:
                self._rpg_restored = True

        # 不在 log 中記錄機器人 / 伺服器名稱與 ID（公開 repo 的 Actions log 任何人都看得到）
        logger.info(
            "🤖 星界紀元 RPG 機器人已上線，共載入 %d 位冒險者檔案，已加入 %d 個伺服器",
            self.rpg_db.get_player_count(),
            len(self.guilds),
        )
        if not self._synced_guilds:
            self._synced_guilds = True
            # 清除舊版本殘留在各伺服器的「伺服器專屬指令」，避免與全域指令重複或殘留舊指令
            cleared = 0
            for guild in self.guilds:
                try:
                    self.tree.clear_commands(guild=guild)
                    await self.tree.sync(guild=guild)
                    cleared += 1
                except Exception as exc:
                    logger.warning("清除伺服器專屬斜線指令失敗: %s", exc)
            logger.info(
                "✅ 全部 %d 個 RPG 斜線指令已使用全域註冊（已清理 %d 個伺服器的舊指令快取）",
                len(self.tree.get_commands()),
                cleared,
            )

    @tasks.loop(minutes=15)
    async def rpg_backup_task(self) -> None:
        # 定時建立 SQLite 本地備份與（若設定）Discord 私有備份頻道快照，攔截所有例外以免排程中斷
        try:
            if not self._rpg_restored:
                return
            self.rpg_db.checkpoint()
            if self.rpg_db.get_player_count() > 0:
                self.rpg_db.create_local_backup(keep=5)
            if settings.rpg_backup_channel_id:
                await self.rpg_db.backup_to_discord_channel(
                    self, settings.rpg_backup_channel_id, force=False
                )
        except Exception as exc:
            logger.warning("RPG 定時備份任務發生警告: %s", exc)

    @rpg_backup_task.before_loop
    async def before_rpg_backup(self) -> None:
        await self.wait_until_ready()


bot = RPGBot()


def parse_bot_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="星界紀元持久化 RPG Discord 機器人")
    parser.add_argument(
        "--run-minutes",
        type=int,
        default=0,
        help="設定機器人執行幾分鐘後自動下線（0 代表持續常駐不關閉）",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default="",
        help="選填：將執行紀錄以 UTF-8 自動輪替寫入指定檔案（例如 logs/bot.log）",
    )
    parser.add_argument(
        "--control-dir",
        type=str,
        default="data",
        help="選填：存放防重複啟動鎖定檔與安全停止訊號檔的資料夾（預設 data）",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_bot_args(argv)
    if args.log_file:
        configure_file_logging(args.log_file)
    if not settings.discord_bot_token:
        logger.error("請先設定 DISCORD_BOT_TOKEN 環境變數（或於 .env 檔案中填入）。")
        return MISSING_TOKEN_EXIT_CODE

    control_dir = Path(args.control_dir)
    lock = SingleInstanceLock(control_dir)
    if not lock.acquire():
        logger.warning("⚠️ 偵測到機器人已經在執行中，已略過重複啟動。")
        return ALREADY_RUNNING_EXIT_CODE

    stop_signal = control_dir / "bot.stop"
    try:
        stop_signal.unlink(missing_ok=True)
    except OSError:
        pass

    bot.run_minutes = args.run_minutes
    bot.stop_signal_path = stop_signal
    try:
        bot.run(settings.discord_bot_token)
        return 0
    finally:
        try:
            stop_signal.unlink(missing_ok=True)
        except OSError:
            pass
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
