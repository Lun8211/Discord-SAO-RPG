import pytest

from src.config import Settings
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
        account_label="小明",
        discord_user_id="123456789",
    )

    assert report.player_name == "Lun#TW1"
    assert report.account_label == "小明"
    assert report.discord_user_id == "123456789"
    assert report.remaining_seconds == 28800
    assert len(report.items) == 4
    assert report.items[0].name == "掠奪印象 暴徒"
    assert report.items[0].price_vp == 1775
    assert report.items[0].tier_name == "尊爵"
    assert report.items[3].name == "Kuronami 暴徒"
    assert report.items[3].price_vp == 2375


def test_build_store_message_payload_creates_four_embeds() -> None:
    report = build_mock_store_report(
        player_name="DemoPlayer#TW1",
        account_label="小明",
        discord_user_id="99887766",
    )
    payload = build_store_message_payload(report, now_ts=1700000000)

    assert "【小明】DemoPlayer#TW1" in payload["content"]
    assert "<@99887766>" in payload["content"]
    assert "<t:1700043200:R>" in payload["content"]
    assert len(payload["embeds"]) == 4

    first_embed = payload["embeds"][0]
    assert first_embed["title"] == "掠奪印象 暴徒"
    assert first_embed["image"]["url"].startswith("https://")
    assert any("1,775 VP" in f["value"] for f in first_embed["fields"])


def test_build_error_message_payload() -> None:
    payload = build_error_message_payload(
        "Cookie 已過期", account_label="阿華", discord_user_id="112233"
    )
    assert "（阿華）" in payload["content"]
    assert "<@112233>" in payload["content"]
    assert len(payload["embeds"]) == 1
    assert "Cookie 已過期" in payload["embeds"][0]["description"]


def test_multi_account_parsing_multiline_and_numbered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot_tok")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "default_chan")
    monkeypatch.setenv(
        "RIOT_ACCOUNTS",
        "小明|ssid_ming|11111\n阿華|ssid_hua|22222|custom_chan\n",
    )
    monkeypatch.setenv("ACCOUNT_NAME_3", "小美")
    monkeypatch.setenv("RIOT_SSID_3", "ssid_mei")
    monkeypatch.setenv("RIOT_SSID", "")

    settings = Settings.from_env()
    assert len(settings.accounts) == 3

    assert settings.accounts[0].label == "小明"
    assert settings.accounts[0].riot_ssid == "ssid_ming"
    assert settings.accounts[0].discord_user_id == "11111"
    assert settings.accounts[0].discord_channel_id == "default_chan"

    assert settings.accounts[1].label == "阿華"
    assert settings.accounts[1].riot_ssid == "ssid_hua"
    assert settings.accounts[1].discord_user_id == "22222"
    assert settings.accounts[1].discord_channel_id == "custom_chan"

    assert settings.accounts[2].label == "小美"
    assert settings.accounts[2].riot_ssid == "ssid_mei"


def test_multi_account_parsing_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "RIOT_ACCOUNTS",
        '[{"name": "P1", "ssid": "s1", "discord_user_id": "u1"}, {"name": "P2", "ssid": "s2"}]',
    )
    monkeypatch.setenv("RIOT_SSID", "")
    settings = Settings.from_env()
    assert len(settings.accounts) == 2
    assert settings.accounts[0].label == "P1"
    assert settings.accounts[0].riot_ssid == "s1"
    assert settings.accounts[1].label == "P2"
    assert settings.accounts[1].riot_ssid == "s2"
