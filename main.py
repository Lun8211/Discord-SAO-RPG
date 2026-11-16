import argparse
import json
import logging
import sys
import time
from typing import Dict, List, Optional, Tuple

from src.config import AccountConfig, Settings
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
        description="VALORANT 每日商店 Discord 多帳號自動推送腳本"
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


def _process_single_account(
    account: AccountConfig,
    settings: Settings,
    skin_catalog: Tuple[Dict[str, dict], Dict[str, dict]],
    client_version: str,
    dry_run: bool,
    dry_run_outputs: List[dict],
) -> bool:
    """Process and send the daily store for a single account. Returns True on success."""
    logger.info("正在讀取 [%s] 的特戰英豪每日商店...", account.display_label)
    try:
        client = ValorantClient(
            riot_ssid=account.riot_ssid,
            riot_cookies=account.riot_cookies,
            region=account.riot_region or settings.riot_region,
            language=settings.valorant_lang,
        )
        report = client.fetch_daily_store_report(
            account_label=account.label,
            discord_user_id=account.discord_user_id,
            skin_catalog=skin_catalog,
            client_version=client_version,
        )
        logger.info(
            "成功取得 [%s] 玩家 %s 的每日商店（共 %d 個物品）：%s",
            account.display_label,
            report.player_name,
            len(report.items),
            ", ".join(f"{item.name} ({item.price_vp} VP)" for item in report.items),
        )

        payload = build_store_message_payload(report)

        if dry_run:
            dry_run_outputs.append(payload)
            return True

        send_discord_payload(
            settings,
            payload,
            target_channel_id=account.discord_channel_id or settings.discord_channel_id,
        )
        logger.info(
            "✅ 已成功將 [%s] (%s) 的 4 張每日商店 Embed 圖卡發送至 Discord 頻道！",
            account.display_label,
            report.player_name,
        )
        return True

    except (RiotAuthError, ValorantAPIError) as exc:
        logger.error(
            "❌ 取得 [%s] 的特戰英豪商店時發生錯誤: %s",
            account.display_label,
            exc,
        )
        if not dry_run:
            try:
                err_payload = build_error_message_payload(
                    str(exc),
                    account_label=account.display_label,
                    discord_user_id=account.discord_user_id,
                )
                send_discord_payload(
                    settings,
                    err_payload,
                    target_channel_id=account.discord_channel_id
                    or settings.discord_channel_id,
                )
                logger.info(
                    "已發送 [%s] 的錯誤提醒訊息至 Discord 頻道。",
                    account.display_label,
                )
            except Exception as notify_exc:
                logger.warning("無法發送錯誤提醒至 Discord: %s", notify_exc)
        return False
    except (ValueError, DiscordNotifyError) as exc:
        logger.error("❌ 發送 [%s] 至 Discord 失敗: %s", account.display_label, exc)
        return False


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()

    try:
        if args.mock:
            logger.info("啟用 --mock 測試模式...")
            mock_accounts = settings.accounts or [
                AccountConfig(
                    index=1,
                    label="玩家1",
                    discord_channel_id=settings.discord_channel_id,
                ),
                AccountConfig(
                    index=2,
                    label="玩家2",
                    discord_channel_id=settings.discord_channel_id,
                ),
            ]
            dry_run_outputs: List[dict] = []
            for idx, acc in enumerate(mock_accounts, start=1):
                report = build_mock_store_report(
                    player_name=f"DemoPlayer{idx}#TW{idx}",
                    account_label=acc.label,
                    discord_user_id=acc.discord_user_id,
                )
                payload = build_store_message_payload(report)
                if args.dry_run:
                    dry_run_outputs.append(payload)
                else:
                    send_discord_payload(
                        settings,
                        payload,
                        target_channel_id=acc.discord_channel_id
                        or settings.discord_channel_id,
                    )
                    logger.info(
                        "✅ 已發送模擬帳號 [%s] 的 4 張 Embed 圖卡！",
                        acc.display_label,
                    )
                    if idx < len(mock_accounts):
                        time.sleep(1.0)

            if args.dry_run:
                output_obj = (
                    dry_run_outputs[0]
                    if len(dry_run_outputs) == 1
                    else dry_run_outputs
                )
                print(json.dumps(output_obj, ensure_ascii=False, indent=2))
            return 0

        settings.validate_riot()
        total_accounts = len(settings.accounts)
        logger.info("共載入 %d 個特戰英豪帳號，準備抓取造型目錄與每日商店...", total_accounts)

        # Fetch shared version and skin catalog once across all accounts
        shared_client = ValorantClient(
            region=settings.riot_region,
            language=settings.valorant_lang,
        )
        client_version = shared_client.get_client_version()
        skin_catalog = shared_client.fetch_skin_catalog()

        success_count = 0
        dry_run_outputs = []

        for idx, account in enumerate(settings.accounts, start=1):
            ok = _process_single_account(
                account=account,
                settings=settings,
                skin_catalog=skin_catalog,
                client_version=client_version,
                dry_run=args.dry_run,
                dry_run_outputs=dry_run_outputs,
            )
            if ok:
                success_count += 1
            if not args.dry_run and idx < total_accounts:
                time.sleep(1.0)

        if args.dry_run:
            output_obj = (
                dry_run_outputs[0]
                if len(dry_run_outputs) == 1
                else dry_run_outputs
            )
            print(json.dumps(output_obj, ensure_ascii=False, indent=2))
            return 0 if success_count == total_accounts else 1

        logger.info(
            "📊 每日商店推送完成：成功 %d / %d 個帳號。",
            success_count,
            total_accounts,
        )
        return 0 if success_count == total_accounts else 1

    except (ValueError, ValorantAPIError, DiscordNotifyError) as exc:
        logger.error("❌ 執行失敗: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
