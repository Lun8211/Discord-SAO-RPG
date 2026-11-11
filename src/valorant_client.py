import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests

logger = logging.getLogger(__name__)

VP_CURRENCY_ID = "85ad13f7-3d1b-5128-9eb2-7cd8ee0b5741"
RADIANITE_CURRENCY_ID = "e59aa87c-4cbf-517a-5983-6e81511be9b7"
KINGDOM_CREDITS_CURRENCY_ID = "85ca954a-41f2-ce94-9b45-8ca3dd39a00d"

CLIENT_PLATFORM_PAYLOAD = {
    "platformType": "PC",
    "platformOS": "Windows",
    "platformOSVersion": "10.0.19042.1.256.64bit",
    "platformChipset": "Unknown",
}
CLIENT_PLATFORM_B64 = base64.b64encode(
    json.dumps(CLIENT_PLATFORM_PAYLOAD).encode("utf-8")
).decode("utf-8")

# Canonical Valorant rarity tier colors for Discord Embeds
TIER_COLOR_MAP: Dict[str, int] = {
    "select": 0x5A9FE2,     # 精選 (Select) - 藍
    "deluxe": 0x009587,     # 極品 (Deluxe) - 綠
    "premium": 0xD1548D,    # 尊爵 (Premium) - 粉紫
    "ultra": 0xFAD663,      # 傳奇 (Ultra) - 金黃
    "exclusive": 0xF5955B,  # 限定 (Exclusive) - 橘金
}

REGION_TO_SHARD: Dict[str, str] = {
    "ap": "ap",
    "na": "na",
    "latam": "na",
    "br": "na",
    "eu": "eu",
    "kr": "kr",
    "pbe": "pbe",
}


class RiotAuthError(Exception):
    """Raised when Riot authentication or cookie reauth fails."""


class ValorantAPIError(Exception):
    """Raised when Valorant storefront or metadata API requests fail."""


@dataclass
class StoreSkinItem:
    uuid: str
    name: str
    price_vp: int
    icon_url: str
    tier_name: str = "造型"
    tier_icon_url: str = ""
    tier_color: int = 0xFF4655
    video_url: Optional[str] = None


@dataclass
class WalletBalance:
    vp: int = 0
    radianite: int = 0
    kingdom_credits: int = 0


@dataclass
class DailyStoreReport:
    player_name: str
    puuid: str
    shard: str
    remaining_seconds: int
    items: List[StoreSkinItem] = field(default_factory=list)
    wallet: Optional[WalletBalance] = None
    account_label: str = ""
    discord_user_id: str = ""


class ValorantClient:
    """Client for Riot Cookie Reauth, Valorant Storefront v3 API, and Valorant-API.com."""

    def __init__(
        self,
        riot_ssid: str = "",
        riot_cookies: str = "",
        region: str = "ap",
        language: str = "zh-TW",
        timeout: int = 20,
    ) -> None:
        self.riot_ssid = riot_ssid.strip()
        self.riot_cookies = riot_cookies.strip()
        self.default_region = (region or "ap").lower().strip()
        self.language = language or "zh-TW"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "RiotClient/91.0.2.1870.3774 rso-auth (Windows;10;;Professional, x64)"
                ),
                "Accept": "application/json",
            }
        )

    def _build_cookie_header(self) -> str:
        if self.riot_cookies:
            return self.riot_cookies
        if not self.riot_ssid:
            raise RiotAuthError("未提供 RIOT_SSID 或 RIOT_COOKIES。")
        if self.riot_ssid.startswith("ssid="):
            return self.riot_ssid
        return f"ssid={self.riot_ssid}"

    @staticmethod
    def _parse_tokens_from_uri(uri: str) -> Tuple[str, Optional[str]]:
        parsed = urlparse(uri)
        fragment_params = parse_qs(parsed.fragment)
        query_params = parse_qs(parsed.query)
        access_tokens = fragment_params.get("access_token") or query_params.get(
            "access_token"
        )
        id_tokens = fragment_params.get("id_token") or query_params.get("id_token")
        if not access_tokens:
            raise RiotAuthError(
                "無法從 Riot 回應取得 access_token。您的 RIOT_SSID Cookie 可能已過期，請重新取得。"
            )
        return access_tokens[0], (id_tokens[0] if id_tokens else None)

    def authenticate(self) -> Tuple[str, Optional[str]]:
        """Perform Riot Cookie Reauth and return (access_token, id_token)."""
        cookie_header = self._build_cookie_header()
        auth_urls = [
            (
                "https://auth.riotgames.com/authorize"
                "?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in"
                "&client_id=play-valorant-web-prod"
                "&response_type=token%20id_token"
                "&nonce=1"
                "&scope=account%20openid"
            ),
            (
                "https://auth.riotgames.com/authorize"
                "?redirect_uri=http%3A%2F%2Flocalhost%2Fredirect"
                "&client_id=riot-client"
                "&response_type=token%20id_token"
                "&nonce=1"
                "&scope=account%20openid"
            ),
        ]

        last_err: Optional[Exception] = None
        for url in auth_urls:
            try:
                resp = self.session.get(
                    url,
                    headers={"Cookie": cookie_header},
                    allow_redirects=False,
                    timeout=self.timeout,
                )
                location = resp.headers.get("Location", "")
                if not location and resp.status_code == 200:
                    data = resp.json()
                    location = data.get("response", {}).get("parameters", {}).get("uri", "")

                if "access_token=" in location:
                    return self._parse_tokens_from_uri(location)

                if "authenticate.riotgames.com" in location or "/login" in location:
                    raise RiotAuthError(
                        "Riot Cookie (RIOT_SSID) 已過期或無效，請重新登入 Riot 網頁取得最新的 ssid Cookie。"
                    )
            except RiotAuthError as exc:
                last_err = exc
                break
            except Exception as exc:
                last_err = exc

        if isinstance(last_err, RiotAuthError):
            raise last_err
        raise RiotAuthError(
            f"Riot 驗證失敗，請確認 RIOT_SSID 是否正確且未過期。詳細資訊：{last_err}"
        )

    def get_entitlements_token(self, access_token: str) -> str:
        resp = self.session.post(
            "https://entitlements.auth.riotgames.com/api/token/v1",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RiotAuthError(
                f"無法取得 Riot Entitlements Token (HTTP {resp.status_code}): {resp.text[:200]}"
            )
        token = resp.json().get("entitlements_token")
        if not token:
            raise RiotAuthError("Riot Entitlements 回應缺少 entitlements_token。")
        return token

    def get_user_info(self, access_token: str) -> Tuple[str, str]:
        """Return (puuid, display_name_with_tag)."""
        resp = self.session.get(
            "https://auth.riotgames.com/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise RiotAuthError(
                f"無法取得 Riot 玩家資訊 (HTTP {resp.status_code}): {resp.text[:200]}"
            )
        data = resp.json()
        puuid = data.get("sub", "")
        if not puuid:
            raise RiotAuthError("Riot userinfo 回應缺少玩家 PUUID (sub)。")
        acct = data.get("acct") or {}
        game_name = acct.get("game_name") or "特戰英豪玩家"
        tag_line = acct.get("tag_line") or ""
        full_name = f"{game_name}#{tag_line}" if tag_line else game_name
        return puuid, full_name

    def get_shard(self, access_token: str, id_token: Optional[str]) -> str:
        if id_token:
            try:
                resp = self.session.put(
                    "https://riot-geo.pas.si.riotgames.com/pas/v1/product/valorant",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json={"id_token": id_token},
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    live_region = (
                        resp.json()
                        .get("affinities", {})
                        .get("live", "")
                        .lower()
                        .strip()
                    )
                    if live_region in REGION_TO_SHARD:
                        return REGION_TO_SHARD[live_region]
            except Exception as exc:
                logger.warning(
                    "Riot Geo 自動偵測分區失敗，改用預設分區 (%s): %s",
                    self.default_region,
                    exc,
                )

        return REGION_TO_SHARD.get(self.default_region, "ap")

    def get_client_version(self) -> str:
        try:
            resp = self.session.get(
                "https://valorant-api.com/v1/version", timeout=self.timeout
            )
            if resp.status_code == 200:
                version = resp.json().get("data", {}).get("riotClientVersion")
                if version:
                    return version
        except Exception as exc:
            logger.warning("無法從 valorant-api.com 取得最新版本號: %s", exc)
        return "release-09.10-shipping-11-2984820"

    def _build_riot_headers(
        self, access_token: str, entitlements_token: str, client_version: str
    ) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "X-Riot-Entitlements-JWT": entitlements_token,
            "X-Riot-ClientPlatform": CLIENT_PLATFORM_B64,
            "X-Riot-ClientVersion": client_version,
            "Content-Type": "application/json",
        }

    def get_storefront_raw(
        self,
        shard: str,
        puuid: str,
        access_token: str,
        entitlements_token: str,
        client_version: str,
    ) -> dict:
        headers = self._build_riot_headers(
            access_token, entitlements_token, client_version
        )
        v3_url = f"https://pd.{shard}.a.pvp.net/store/v3/storefront/{puuid}"
        resp = self.session.post(v3_url, headers=headers, json={}, timeout=self.timeout)

        if resp.status_code in (404, 405):
            v2_url = f"https://pd.{shard}.a.pvp.net/store/v2/storefront/{puuid}"
            resp = self.session.get(v2_url, headers=headers, timeout=self.timeout)

        if resp.status_code != 200:
            raise ValorantAPIError(
                f"查詢每日商店失敗 (HTTP {resp.status_code}): {resp.text[:250]}"
            )
        return resp.json()

    def get_wallet(
        self,
        shard: str,
        puuid: str,
        access_token: str,
        entitlements_token: str,
        client_version: str,
    ) -> Optional[WalletBalance]:
        headers = self._build_riot_headers(
            access_token, entitlements_token, client_version
        )
        url = f"https://pd.{shard}.a.pvp.net/store/v1/wallet/{puuid}"
        try:
            resp = self.session.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code == 200:
                balances = resp.json().get("Balances", {})
                return WalletBalance(
                    vp=int(balances.get(VP_CURRENCY_ID, 0)),
                    radianite=int(balances.get(RADIANITE_CURRENCY_ID, 0)),
                    kingdom_credits=int(balances.get(KINGDOM_CREDITS_CURRENCY_ID, 0)),
                )
        except Exception as exc:
            logger.warning("查詢錢包餘額失敗 (略過): %s", exc)
        return None

    def fetch_skin_catalog(self) -> Tuple[Dict[str, dict], Dict[str, dict]]:
        """Fetch localized weapon skins and content tiers from valorant-api.com."""
        skins_by_level_uuid: Dict[str, dict] = {}
        tiers_by_uuid: Dict[str, dict] = {}

        # 1. Content tiers (rarities)
        try:
            tiers_resp = self.session.get(
                "https://valorant-api.com/v1/contenttiers",
                params={"language": self.language},
                timeout=self.timeout,
            )
            if tiers_resp.status_code == 200:
                for tier in tiers_resp.json().get("data", []):
                    t_uuid = (tier.get("uuid") or "").lower()
                    dev_name = (tier.get("devName") or "").lower()
                    highlight = (tier.get("highlightColor") or "")[:6]
                    color = TIER_COLOR_MAP.get(dev_name)
                    if color is None and len(highlight) == 6:
                        try:
                            color = int(highlight, 16)
                        except ValueError:
                            color = 0xFF4655
                    tiers_by_uuid[t_uuid] = {
                        "name": tier.get("displayName") or tier.get("devName") or "造型",
                        "icon": tier.get("displayIcon") or "",
                        "color": color or 0xFF4655,
                    }
        except Exception as exc:
            logger.warning("無法取得稀有度分類資料: %s", exc)

        # 2. Weapon skins
        skins_resp = self.session.get(
            "https://valorant-api.com/v1/weapons/skins",
            params={"language": self.language},
            timeout=self.timeout,
        )
        if skins_resp.status_code != 200:
            raise ValorantAPIError(
                f"無法從 valorant-api.com 取得武器造型目錄 (HTTP {skins_resp.status_code})"
            )

        for skin in skins_resp.json().get("data", []):
            skin_name = skin.get("displayName") or "未知造型"
            tier_uuid = (skin.get("contentTierUuid") or "").lower()
            chromas = skin.get("chromas") or []
            levels = skin.get("levels") or []

            base_icon = ""
            if levels and levels[0].get("displayIcon"):
                base_icon = levels[0]["displayIcon"]
            elif chromas and chromas[0].get("fullRender"):
                base_icon = chromas[0]["fullRender"]
            elif skin.get("displayIcon"):
                base_icon = skin["displayIcon"]

            video_url = None
            for lvl in reversed(levels):
                if lvl.get("streamedVideo"):
                    video_url = lvl["streamedVideo"]
                    break

            for lvl in levels:
                lvl_uuid = (lvl.get("uuid") or "").lower()
                if not lvl_uuid:
                    continue
                skins_by_level_uuid[lvl_uuid] = {
                    "name": skin_name,
                    "icon": lvl.get("displayIcon") or base_icon,
                    "tier_uuid": tier_uuid,
                    "video_url": video_url,
                }

        return skins_by_level_uuid, tiers_by_uuid

    def parse_daily_store(
        self,
        storefront: dict,
        skins_by_level_uuid: Dict[str, dict],
        tiers_by_uuid: Dict[str, dict],
        player_name: str,
        puuid: str,
        shard: str,
        wallet: Optional[WalletBalance] = None,
        account_label: str = "",
        discord_user_id: str = "",
    ) -> DailyStoreReport:
        panel = storefront.get("SkinsPanelLayout") or {}
        remaining_seconds = int(
            panel.get("SingleItemOffersRemainingDurationInSeconds", 0)
        )
        store_offers = panel.get("SingleItemStoreOffers") or []
        single_ids = panel.get("SingleItemOffers") or []

        parsed_items: List[StoreSkinItem] = []

        if store_offers:
            for offer in store_offers[:4]:
                offer_id = (offer.get("OfferID") or "").lower()
                rewards = offer.get("Rewards") or []
                item_id = (
                    (rewards[0].get("ItemID") if rewards else offer_id) or offer_id
                ).lower()
                cost_dict = offer.get("Cost") or {}
                price_vp = int(
                    cost_dict.get(VP_CURRENCY_ID)
                    or next(iter(cost_dict.values()), 0)
                )
                parsed_items.append(
                    self._build_skin_item(
                        item_id, price_vp, skins_by_level_uuid, tiers_by_uuid
                    )
                )
        else:
            for item_id in single_ids[:4]:
                parsed_items.append(
                    self._build_skin_item(
                        item_id.lower(), 0, skins_by_level_uuid, tiers_by_uuid
                    )
                )

        return DailyStoreReport(
            player_name=player_name,
            puuid=puuid,
            shard=shard,
            remaining_seconds=remaining_seconds,
            items=parsed_items,
            wallet=wallet,
            account_label=account_label,
            discord_user_id=discord_user_id,
        )

    @staticmethod
    def _build_skin_item(
        level_uuid: str,
        price_vp: int,
        skins_by_level_uuid: Dict[str, dict],
        tiers_by_uuid: Dict[str, dict],
    ) -> StoreSkinItem:
        skin_meta = skins_by_level_uuid.get(level_uuid, {})
        tier_uuid = skin_meta.get("tier_uuid", "")
        tier_meta = tiers_by_uuid.get(tier_uuid, {})

        return StoreSkinItem(
            uuid=level_uuid,
            name=skin_meta.get("name") or f"未知造型 ({level_uuid[:8]})",
            price_vp=price_vp,
            icon_url=skin_meta.get("icon") or "",
            tier_name=tier_meta.get("name") or "造型",
            tier_icon_url=tier_meta.get("icon") or "",
            tier_color=tier_meta.get("color", 0xFF4655),
            video_url=skin_meta.get("video_url"),
        )

    def fetch_daily_store_report(
        self,
        account_label: str = "",
        discord_user_id: str = "",
        skin_catalog: Optional[Tuple[Dict[str, dict], Dict[str, dict]]] = None,
        client_version: Optional[str] = None,
    ) -> DailyStoreReport:
        """Full end-to-end workflow to authenticate and retrieve the 4 daily store items."""
        access_token, id_token = self.authenticate()
        entitlements_token = self.get_entitlements_token(access_token)
        puuid, player_name = self.get_user_info(access_token)
        shard = self.get_shard(access_token, id_token)
        resolved_version = client_version or self.get_client_version()

        storefront = self.get_storefront_raw(
            shard=shard,
            puuid=puuid,
            access_token=access_token,
            entitlements_token=entitlements_token,
            client_version=resolved_version,
        )
        wallet = self.get_wallet(
            shard=shard,
            puuid=puuid,
            access_token=access_token,
            entitlements_token=entitlements_token,
            client_version=resolved_version,
        )
        if skin_catalog is not None:
            skins_by_level_uuid, tiers_by_uuid = skin_catalog
        else:
            skins_by_level_uuid, tiers_by_uuid = self.fetch_skin_catalog()

        return self.parse_daily_store(
            storefront=storefront,
            skins_by_level_uuid=skins_by_level_uuid,
            tiers_by_uuid=tiers_by_uuid,
            player_name=player_name,
            puuid=puuid,
            shard=shard,
            wallet=wallet,
            account_label=account_label,
            discord_user_id=discord_user_id,
        )


def build_mock_store_report(
    player_name: str = "DemoPlayer#TW1",
    account_label: str = "",
    discord_user_id: str = "",
) -> DailyStoreReport:
    """Generate a realistic 4-item mock daily store report for testing Discord embeds."""
    return DailyStoreReport(
        player_name=player_name,
        puuid="00000000-0000-0000-0000-000000000000",
        shard="ap",
        remaining_seconds=43200,
        account_label=account_label,
        discord_user_id=discord_user_id,
        wallet=WalletBalance(vp=2450, radianite=160, kingdom_credits=8500),
        items=[
            StoreSkinItem(
                uuid="89be9866-4807-6235-2a95-499cd23828df",
                name="掠奪印象 暴徒",
                price_vp=1775,
                icon_url="https://media.valorant-api.com/weaponskinlevels/89be9866-4807-6235-2a95-499cd23828df/displayicon.png",
                tier_name="尊爵",
                tier_icon_url="https://media.valorant-api.com/contenttiers/60bca009-4182-7998-dee7-b8a2558dc369/displayicon.png",
                tier_color=0xD1548D,
            ),
            StoreSkinItem(
                uuid="f5355966-4b32-8949-0332-4782f9d3247f",
                name="쿠로나미 (Kuronami) 暴徒",
                price_vp=2375,
                icon_url="https://media.valorant-api.com/weaponskins/7c692229-424c-647f-8804-86870f02c882/displayicon.png",
                tier_name="限定",
                tier_icon_url="https://media.valorant-api.com/contenttiers/e046854e-406c-37f4-6607-19a9ba8426fc/displayicon.png",
                tier_color=0xF5955B,
            ),
            StoreSkinItem(
                uuid="42fe9204-4090-64c4-942c-7798e333c9e0",
                name="奇點 幻象",
                price_vp=2175,
                icon_url="https://media.valorant-api.com/weaponskinlevels/42fe9204-4090-64c4-942c-7798e333c9e0/displayicon.png",
                tier_name="限定",
                tier_icon_url="https://media.valorant-api.com/contenttiers/e046854e-406c-37f4-6607-19a9ba8426fc/displayicon.png",
                tier_color=0xF5955B,
            ),
            StoreSkinItem(
                uuid="5305d9c4-4f46-fbf4-9e9a-a7b2c2a3b421",
                name="紫金狂潮 暴徒",
                price_vp=1775,
                icon_url="https://media.valorant-api.com/weaponskinlevels/5305d9c4-4f46-fbf4-9e9a-a7b2c2a3b421/displayicon.png",
                tier_name="尊爵",
                tier_icon_url="https://media.valorant-api.com/contenttiers/60bca009-4182-7998-dee7-b8a2558dc369/displayicon.png",
                tier_color=0xD1548D,
            ),
        ],
    )
