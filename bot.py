"""Sword Art Online: Aincrad 100-Floor Multiplayer Discord RPG Bot entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import sys
from collections.abc import Sequence
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import IO

import discord
from discord import app_commands
from discord.ext import tasks

from src.config import Settings
from src.memes import AnimeMemeService, register_meme_commands
from src.rpg.commands import register_rpg_commands
from src.rpg.content.loader import load_and_validate_all
from src.rpg.database import RPGDatabase
from src.rpg.engine import RPGEngine

# 避免繁體中文 Windows (cp950) 輸出 Emoji 時發生編碼錯誤
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        with contextlib.suppress(AttributeError, OSError, ValueError):
            _stream.reconfigure(encoding="utf-8", errors="replace")

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
)
logger = logging.getLogger("sao-aincrad-bot")

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
        self._handle: IO[bytes] | None = None

    def acquire(self) -> bool:
        self.control_dir.mkdir(parents=True, exist_ok=True)
        handle = open(self.lock_path, "a+b")  # noqa: SIM115
        try:
            handle.seek(0)
            if len(handle.read(1)) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
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

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
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
    """SAO Aincrad 100-Floor Multiplayer RPG Discord Client (with preserved /p meme command)."""

    def __init__(
        self,
        bot_settings: Settings | None = None,
        *,
        run_minutes: int = 0,
    ) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.settings = bot_settings if bot_settings is not None else Settings.from_env()
        self.tree = app_commands.CommandTree(self)
        self.run_minutes = run_minutes
        self.stop_signal_path: Path | None = None
        self._synced_guilds = False
        self._rpg_restore_started = False
        self._rpg_restored = False
        self._closing_started = False

        content_bundle = load_and_validate_all()
        self.rpg_db = RPGDatabase(db_path=self.settings.rpg_db_path)
        self.rpg_engine = RPGEngine(
            db=self.rpg_db,
            content=content_bundle,
            timezone_offset_hours=self.settings.timezone_offset_hours,
        )
        self.meme_service = AnimeMemeService()
        register_rpg_commands(self.tree, self.rpg_engine)
        register_meme_commands(self.tree, self.meme_service)

    async def setup_hook(self) -> None:
        await self.tree.sync()
        asyncio.create_task(self.meme_service.ensure_loaded())
        self.rpg_backup_task.change_interval(minutes=self.settings.rpg_backup_interval_minutes)
        self.rpg_backup_task.start()
        if self.stop_signal_path is not None:
            asyncio.create_task(self._watch_stop_signal())
        if self.run_minutes > 0:
            asyncio.create_task(self._auto_shutdown_after(self.run_minutes))

    async def _watch_stop_signal(self) -> None:
        while not self.is_closed():
            if self.stop_signal_path is not None and self.stop_signal_path.exists():
                logger.info("🛑 收到安全停止訊號，正在完成艾恩葛朗特存檔並關閉機器人...")
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
        if not self._closing_started:
            self._closing_started = True
            try:
                if self.settings.rpg_backup_channel_id and self.is_ready() and self._rpg_restored:
                    uploaded = await self.rpg_db.backup_to_discord_channel(
                        self, self.settings.rpg_backup_channel_id, force=False
                    )
                    if uploaded:
                        logger.info("💾 關機前已完成 SAO 雲端快照備份。")
            except Exception as exc:  # noqa: BLE001
                logger.warning("關機前上傳 SAO 雲端備份失敗: %s", exc)
            try:
                self.rpg_db.close()
                logger.info("💾 SAO 資料庫已完成 checkpoint 與本地備份。")
            except Exception as exc:  # noqa: BLE001
                logger.warning("關閉 SAO 資料庫時發生警告: %s", exc)
        await super().close()

    async def on_ready(self) -> None:
        if not self._rpg_restore_started:
            self._rpg_restore_started = True
            try:
                if self.settings.rpg_backup_channel_id:
                    await self.rpg_db.restore_from_discord_channel(
                        self, self.settings.rpg_backup_channel_id
                    )
            finally:
                self._rpg_restored = True

        # 不在 log 中記錄機器人 / 伺服器名稱與 ID（公開 repo 的 Actions log 任何人都看得到）
        logger.info(
            "⚔️ 刀劍神域 SAO 艾恩葛朗特機器人已上線，共載入 %d 位攻略者檔案，已加入 %d 個伺服器",
            self.rpg_db.get_player_count(),
            len(self.guilds),
        )
        if not self._synced_guilds:
            self._synced_guilds = True
            cleared = 0
            for guild in self.guilds:
                try:
                    self.tree.clear_commands(guild=guild)
                    await self.tree.sync(guild=guild)
                    cleared += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("清除伺服器專屬斜線指令失敗: %s", exc)
            logger.info(
                "✅ 全部 %d 個斜線指令已使用全域註冊（已清理 %d 個伺服器的舊指令快取）",
                len(self.tree.get_commands()),
                cleared,
            )

    @tasks.loop(minutes=15)
    async def rpg_backup_task(self) -> None:
        try:
            if not self._rpg_restored:
                return
            self.rpg_db.checkpoint()
            if self.rpg_db.get_player_count() > 0:
                self.rpg_db.create_local_backup(keep=5)
            if self.settings.rpg_backup_channel_id:
                await self.rpg_db.backup_to_discord_channel(
                    self, self.settings.rpg_backup_channel_id, force=False
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SAO 定時備份任務發生警告: %s", exc)

    @rpg_backup_task.before_loop
    async def before_rpg_backup(self) -> None:
        await self.wait_until_ready()


def create_bot(
    bot_settings: Settings | None = None,
    *,
    run_minutes: int = 0,
) -> RPGBot:
    """Factory creating an isolated RPGBot instance without import-time DB side-effects."""
    return RPGBot(bot_settings=bot_settings, run_minutes=run_minutes)


_LAZY_BOT: RPGBot | None = None


def __getattr__(name: str) -> object:
    global _LAZY_BOT
    if name == "bot":
        if _LAZY_BOT is None:
            _LAZY_BOT = create_bot()
        return _LAZY_BOT
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def parse_bot_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="刀劍神域 SAO 艾恩葛朗特 100 層持久化多人 RPG Discord 機器人")
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_bot_args(argv)
    if args.log_file:
        configure_file_logging(args.log_file)
    active_settings = Settings.from_env()
    if not active_settings.discord_bot_token:
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

    bot_instance = create_bot(active_settings, run_minutes=args.run_minutes)
    bot_instance.stop_signal_path = stop_signal
    try:
        bot_instance.run(active_settings.discord_bot_token)
        return 0
    finally:
        try:
            stop_signal.unlink(missing_ok=True)
        except OSError:
            pass
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
