import pytest

from src.discord_notifier import (
    build_error_message_payload,
    build_store_message_payload,
)
from src.valorant_client import (
    RiotAuthError,
    ValorantClient,
    VP_CURRENCY_ID,
    WalletBalance,
    build_mock_store_report,
)


def test_parse_tokens_from_redirect_uri() -> None:
    uri = (
        "https://playvalorant.com/opt_in"
        "#access_token=eyJ_test_access&scope=openid"
        "&id_token=eyJ_test_id&token_type=Bearer&expires_in=3600"
    )
    access_token, id_token = ValorantClient._parse_tokens_from_uri(uri)
    assert access_token == "eyJ_test_access"
    assert id_token == "eyJ_test_id"


def test_parse_tokens_missing_raises() -> None:
    with pytest.raises(RiotAuthError):
        ValorantClient._parse_tokens_from_uri("https://authenticate.riotgames.com/login")


def test_parse_daily_store_four_items() -> None:
    client = ValorantClient(riot_ssid="test_ssid")
    storefront = {
        "SkinsPanelLayout": {
            "SingleItemOffersRemainingDurationInSeconds": 28800,
            "SingleItemStoreOffers": [
                {
                    "OfferID": "uuid-1",
                    "Cost": {VP_CURRENCY_ID: 1775},
                    "Rewards": [{"ItemID": "uuid-1"}],
                },
                {
                    "OfferID": "uuid-2",
                    "Cost": {VP_CURRENCY_ID: 2175},
                    "Rewards": [{"ItemID": "uuid-2"}],
                },
                {
                    "OfferID": "uuid-3",
                    "Cost": {VP_CURRENCY_ID: 1275},
                    "Rewards": [{"ItemID": "uuid-3"}],
                },
                {
                    "OfferID": "uuid-4",
                    "Cost": {VP_CURRENCY_ID: 2375},
                    "Rewards": [{"ItemID": "uuid-4"}],
                },
            ],
        }
    }
    skins_catalog = {
        "uuid-1": {
            "name": "掠奪印象 暴徒",
            "icon": "https://example.com/1.png",
            "tier_uuid": "tier-premium",
            "video_url": "https://example.com/1.mp4",
        },
        "uuid-2": {
            "name": "奇點 幻象",
            "icon": "https://example.com/2.png",
            "tier_uuid": "tier-exclusive",
            "video_url": None,
        },
        "uuid-3": {
            "name": "極地寒冬 暴徒",
            "icon": "https://example.com/3.png",
            "tier_uuid": "tier-deluxe",
            "video_url": None,
        },
        "uuid-4": {
            "name": "Kuronami 暴徒",
            "icon": "https://example.com/4.png",
            "tier_uuid": "tier-exclusive",
            "video_url": "https://example.com/4.mp4",
        },
    }
    tiers_catalog = {
        "tier-premium": {
            "name": "尊爵",
            "icon": "https://example.com/tier-p.png",
            "color": 0xD1548D,
        },
        "tier-exclusive": {
            "name": "限定",
            "icon": "https://example.com/tier-e.png",
            "color": 0xF5955B,
        },
        "tier-deluxe": {
            "name": "極品",
            "icon": "https://example.com/tier-d.png",
            "color": 0x009587,
        },
    }

    report = client.parse_daily_store(
        storefront=storefront,
        skins_by_level_uuid=skins_catalog,
        tiers_by_uuid=tiers_catalog,
        player_name="Lun#TW1",
        puuid="test-puuid",
        shard="ap",
        wallet=WalletBalance(vp=3000, radianite=100, kingdom_credits=5000),
    )

    assert report.player_name == "Lun#TW1"
    assert report.remaining_seconds == 28800
    assert len(report.items) == 4
    assert report.items[0].name == "掠奪印象 暴徒"
    assert report.items[0].price_vp == 1775
    assert report.items[0].tier_name == "尊爵"
    assert report.items[3].name == "Kuronami 暴徒"
    assert report.items[3].price_vp == 2375


def test_build_store_message_payload_creates_four_embeds() -> None:
    report = build_mock_store_report()
    payload = build_store_message_payload(report, now_ts=1700000000)

    assert "DemoPlayer#TW1" in payload["content"]
    assert "<t:1700043200:R>" in payload["content"]
    assert len(payload["embeds"]) == 4

    first_embed = payload["embeds"][0]
    assert first_embed["title"] == "掠奪印象 暴徒"
    assert first_embed["image"]["url"].startswith("https://")
    assert any("1,775 VP" in f["value"] for f in first_embed["fields"])


def test_build_error_message_payload() -> None:
    payload = build_error_message_payload("Cookie 已過期")
    assert len(payload["embeds"]) == 1
    assert "Cookie 已過期" in payload["embeds"][0]["description"]
