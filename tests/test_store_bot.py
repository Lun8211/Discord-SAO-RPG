import base64
import json

import pytest

import bot as bot_module
from src.config import AccountConfig, Settings
from src.discord_notifier import (
    build_cookie_status_payload,
    build_error_message_payload,
    build_store_message_payload,
    format_remaining_duration,
)
from src.valorant_client import (
    CookieCheckResult,
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


def test_expired_embedded_access_token_is_not_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "12345678-1234-1234-1234-123456789012", "exp": 1000000}).encode()
    ).decode().rstrip("=")
    expired_jwt = f"{header}.{payload}.sig"
    cookie_str = f"ssid={expired_jwt}; __Secure-access_token={expired_jwt}; tdid=abc"

    client = ValorantClient(riot_cookies=cookie_str)

    class FakeResp:
        def __init__(self, status_code: int, location: str = "", json_data: dict | None = None) -> None:
            self.status_code = status_code
            self.headers = {"Location": location} if location else {}
            self._json = json_data
            self.text = json.dumps(json_data) if json_data else ""

        def json(self) -> dict:
            return self._json or {}

    monkeypatch.setattr(
        client.session,
        "get",
        lambda *args, **kwargs: FakeResp(303, "https://authenticate.riotgames.com/login"),
    )
    monkeypatch.setattr(
        client.session,
        "post",
        lambda *args, **kwargs: FakeResp(200, json_data={"type": "auth"}),
    )

    with pytest.raises(RiotAuthError) as exc_info:
        client.authenticate()

    assert "embedded_access_token_expired" in str(exc_info.value)
    assert "已過期" in str(exc_info.value)


def _make_jwt(payload: dict) -> str:
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "ES256", "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    body = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    )
    return f"{header}.{body}.sig"


def test_inspect_cookie_metadata_prefers_ssid_exp_over_id_token() -> None:
    now_ts = 1794500000
    ssid_jwt = _make_jwt({"sub": "puuid-1", "iat": now_ts - 86400, "exp": now_ts + 20 * 86400})
    short_id_token = _make_jwt({"sub": "puuid-1", "acct": {"game_name": "Lun"}, "aud": "play", "exp": now_ts - 3600})
    raw_cookie = f"__Secure-id_token={short_id_token}; csid=abc; tdid=def; ssid={ssid_jwt}"

    client = ValorantClient(riot_cookies=raw_cookie)
    meta = client.inspect_cookie_metadata()

    assert meta["token_source"] == "full_cookies"
    assert meta["has_ssid"] is True
    assert meta["has_csid"] is True
    assert meta["has_tdid"] is True
    assert meta["issued_at"] == now_ts - 86400
    assert meta["expires_at"] == now_ts + 20 * 86400
    assert meta["expires_source"] == "ssid_jwt"


def test_inspect_cookie_metadata_detects_access_token_and_missing_ssid() -> None:
    now_ts = 1794500000
    acc_jwt = _make_jwt({"sub": "puuid-1", "scp": ["openid"], "exp": now_ts + 1800})
    client_acc = ValorantClient(riot_ssid=acc_jwt)
    meta_acc = client_acc.inspect_cookie_metadata()
    assert meta_acc["token_source"] == "access_token"
    assert meta_acc["expires_at"] == now_ts + 1800

    client_missing = ValorantClient(riot_cookies="csid=abc; tdid=def; clid=ap1")
    meta_missing = client_missing.inspect_cookie_metadata()
    assert meta_missing["token_source"] == "missing_ssid"
    assert meta_missing["has_ssid"] is False


def test_check_cookie_status_live_and_set_cookie_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    now_ts = 1794500000
    ssid_jwt = _make_jwt({"sub": "puuid-1", "iat": now_ts - 86400, "exp": now_ts + 2 * 86400})
    client = ValorantClient(riot_cookies=f"ssid={ssid_jwt}; csid=c1; tdid=t1")

    monkeypatch.setattr(client, "authenticate", lambda: ("acc_tok", "id_tok"))
    monkeypatch.setattr(client, "get_user_info", lambda _tok: ("puuid-1", "Lun#TW1"))

    res = client.check_cookie_status(
        account_label="Lun",
        discord_user_id="12345",
        now_ts=now_ts,
        verify_live=True,
    )
    assert res.is_valid is True
    assert res.status_code == "expiring_soon"
    assert res.player_name == "Lun#TW1"
    assert res.remaining_seconds == 2 * 86400
    assert res.expires_source == "ssid_jwt"

    # Opaque ssid fallback to Set-Cookie expiration captured during authenticate()
    client_opaque = ValorantClient(riot_cookies="ssid=opaque_token; csid=c1")

    def _fake_auth() -> tuple[str, str]:
        client_opaque._last_auth_method = "GET(web)"
        client_opaque._last_set_cookie_ssid_expires = now_ts + 15 * 86400
        return "acc_tok", "id_tok"

    monkeypatch.setattr(client_opaque, "authenticate", _fake_auth)
    monkeypatch.setattr(client_opaque, "get_user_info", lambda _tok: ("puuid-2", "Mahiru#0830"))

    res_opaque = client_opaque.check_cookie_status(
        account_label="Mahiru",
        now_ts=now_ts,
        verify_live=True,
    )
    assert res_opaque.is_valid is True
    assert res_opaque.status_code == "valid"
    assert res_opaque.expires_at == now_ts + 15 * 86400
    assert res_opaque.expires_source == "set_cookie"


def test_check_cookie_status_revoked_before_exp(monkeypatch: pytest.MonkeyPatch) -> None:
    now_ts = 1794500000
    ssid_jwt = _make_jwt({"sub": "puuid-1", "exp": now_ts + 10 * 86400})
    client = ValorantClient(riot_cookies=f"ssid={ssid_jwt}; csid=c1")

    def _fail_auth() -> tuple[str, None]:
        raise RiotAuthError("Riot Cookie (RIOT_SSID) 已過期、無效或缺少關聯 Cookie（伺服器跳轉回登入頁）。診斷資訊：test")

    monkeypatch.setattr(client, "authenticate", _fail_auth)
    res = client.check_cookie_status(account_label="john", now_ts=now_ts, verify_live=True)
    assert res.is_valid is False
    assert res.status_code == "expired"
    assert res.expires_at == now_ts + 10 * 86400


def test_build_cookie_status_payload_formats_summary_and_timestamps() -> None:
    now_ts = 1794500000
    assert format_remaining_duration(10 * 86400 + 5 * 3600) == "10 天 5 小時"
    assert format_remaining_duration(3 * 3600 + 25 * 60) == "3 小時 25 分鐘"
    assert format_remaining_duration(45) == "1 分鐘"

    acc1 = AccountConfig(index=1, label="Lun", discord_user_id="111")
    res1 = CookieCheckResult(
        account_label="Lun",
        discord_user_id="111",
        player_name="Lun#TW1",
        is_valid=True,
        status_code="valid",
        token_source="full_cookies",
        issued_at=now_ts - 86400,
        expires_at=now_ts + 10 * 86400,
        expires_source="ssid_jwt",
        remaining_seconds=10 * 86400,
    )
    acc2 = AccountConfig(index=2, label="john", discord_user_id="222")
    res2 = CookieCheckResult(
        account_label="john",
        discord_user_id="222",
        is_valid=False,
        status_code="expired",
        message="Riot Cookie (RIOT_SSID) 已過期。診斷資訊：hidden",
        token_source="full_cookies",
        expires_at=now_ts - 7200,
        expires_source="ssid_jwt",
        remaining_seconds=-7200,
    )

    payload = build_cookie_status_payload([(acc1, res1), (acc2, res2)], now_ts=now_ts)
    assert "提醒" in payload["content"]
    assert len(payload["embeds"]) == 1
    embed = payload["embeds"][0]
    assert embed["color"] == 0xE74C3C
    assert "🟢 **1** 正常" in embed["description"]
    assert "🔴 **1** 已失效" in embed["description"]
    assert len(embed["fields"]) == 2
    assert "10 天 0 小時" in embed["fields"][0]["value"]
    assert f"<t:{now_ts + 10 * 86400}:R>" in embed["fields"][0]["value"]
    assert "診斷資訊" not in embed["fields"][1]["value"]
    assert "2 小時 0 分鐘前" in embed["fields"][1]["value"]


def test_bot_registers_shop_and_cookie_commands() -> None:
    cmd_names = {cmd.name for cmd in bot_module.bot.tree.get_commands()}
    assert "shop" in cmd_names
    assert "cookie" in cmd_names

    acc = AccountConfig(index=1, label="Lun", discord_user_id="123456")
    assert bot_module._match_account_filter(acc, None, None) is True
    assert bot_module._match_account_filter(acc, "all", None) is True
    assert bot_module._match_account_filter(acc, "me", "123456") is True
    assert bot_module._match_account_filter(acc, "me", "999999") is False
    assert bot_module._match_account_filter(acc, "1", None) is True
    assert bot_module._match_account_filter(acc, "lun", None) is True



def test_daily_store_task_isolates_per_account_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """One failing channel must not skip remaining accounts or raise out of tasks.loop."""
    import asyncio

    bot = bot_module.bot
    acc_bad = AccountConfig(index=1, label="壞頻道", discord_channel_id="111")
    acc_invalid = AccountConfig(index=2, label="格式錯誤", discord_channel_id="not-a-number")
    acc_ok = AccountConfig(index=3, label="正常", discord_channel_id="222")
    payload = {"content": "hi", "embeds": []}

    async def fake_fetch_all(*_args, **_kwargs):
        return [(acc_bad, payload), (acc_invalid, payload), (acc_ok, payload)]

    sent = []

    class FakeChannel:
        def __init__(self, cid: int) -> None:
            self.cid = cid

        async def send(self, **_kwargs) -> None:
            if self.cid == 111:
                raise RuntimeError("Missing Access")
            sent.append(self.cid)

    async def no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(bot, "fetch_all_payloads_async", fake_fetch_all)
    monkeypatch.setattr(bot, "get_channel", lambda cid: FakeChannel(cid))
    monkeypatch.setattr(bot_module.asyncio, "sleep", no_sleep)

    asyncio.run(bot.daily_store_task.coro(bot))
    assert sent == [222]


def test_cookie_diagnostics_do_not_leak_puuid() -> None:
    _, diag = ValorantClient._inspect_jwt_info(
        "ssid=abc; csid=def; sub=12345678-aaaa-bbbb-cccc-1234567890ab; tdid=x"
    )
    assert "12345678" not in diag
    assert "has_sub=True" in diag
