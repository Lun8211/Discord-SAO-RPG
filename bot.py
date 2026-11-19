import argparse
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import tasks

from src.config import Settings
from src.rpg.commands import register_rpg_commands
from src.rpg.database import RPGDatabase
from src.rpg.engine import RPGEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("rpg-dc-bot")

settings = Settings.from_env()


class RPGBot(discord.Client):
    def __init__(self, run_minutes: int = 0) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.run_minutes = run_minutes
        self._synced_guilds = False
        self._rpg_restore_started = False
        self._rpg_restored = False
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
        if self.run_minutes > 0:
            asyncio.create_task(self._auto_shutdown_after(self.run_minutes))

    async def _auto_shutdown_after(self, minutes: int) -> None:
        await self.wait_until_ready()
        logger.info("⏳ 機器人將於 %d 分鐘後自動安全下線...", minutes)
        await asyncio.sleep(minutes * 60)
        logger.info("⏹️ 已達設定執行時間 (%d 分鐘)，正在存檔並安全關閉機器人...", minutes)
        await self.close()

    async def close(self) -> None:
        # 關機前務必完成 RPG SQLite checkpoint、本地備份與（若已設定）雲端備份上傳
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


def parse_bot_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="星界紀元持久化 RPG Discord 機器人")
    parser.add_argument(
        "--run-minutes",
        type=int,
        default=0,
        help="設定機器人執行幾分鐘後自動下線（0 代表持續常駐不關閉）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_bot_args()
    if not settings.discord_bot_token:
        raise SystemExit("請先設定 DISCORD_BOT_TOKEN 環境變數。")
    bot.run_minutes = args.run_minutes
    bot.run(settings.discord_bot_token)
