import argparse
import json
import logging
import sys

from src.config import Settings
from src.discord_notifier import (
    DiscordNotifyError,
    build_error_message_payload,
    build_store_message_payload,
    send_discord_payload,
)
from src.valorant_client import (
    RiotAuthError,
    ValorantAPIError,
    ValorantClient,
    build_mock_store_report,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("val-dc")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VALORANT 每日商店 Discord 自動推送腳本"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="使用範例的 4 個造型資料進行測試（可用於測試 Discord 機器人發送效果）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="僅在終端機印出將發送的 Discord Embed JSON，不實際發送到 Discord",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()

    try:
        if args.mock:
            logger.info("啟用 --mock 測試模式，產生 4 個範例每日商店物品...")
            report = build_mock_store_report()
        else:
            settings.validate_riot()
            logger.info("正在驗證 Riot 帳號並讀取特戰英豪每日商店...")
            client = ValorantClient(
                riot_ssid=settings.riot_ssid,
                riot_cookies=settings.riot_cookies,
                region=settings.riot_region,
                language=settings.valorant_lang,
            )
            report = client.fetch_daily_store_report()

        logger.info(
            "成功取得玩家 %s 的每日商店（共 %d 個物品）：%s",
            report.player_name,
            len(report.items),
            ", ".join(f"{item.name} ({item.price_vp} VP)" for item in report.items),
        )

        payload = build_store_message_payload(report)

        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        send_discord_payload(settings, payload)
        logger.info("✅ 已成功將 4 張每日商店 Embed 圖卡發送至 Discord 頻道！")
        return 0

    except (RiotAuthError, ValorantAPIError) as exc:
        logger.error("❌ 取得特戰英豪商店時發生錯誤: %s", exc)
        if not args.dry_run:
            try:
                err_payload = build_error_message_payload(str(exc))
                send_discord_payload(settings, err_payload)
                logger.info("已發送錯誤提醒訊息至 Discord 頻道。")
            except Exception as notify_exc:
                logger.warning("無法發送錯誤提醒至 Discord: %s", notify_exc)
        return 1
    except (ValueError, DiscordNotifyError) as exc:
        logger.error("❌ 設定或發送失敗: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
