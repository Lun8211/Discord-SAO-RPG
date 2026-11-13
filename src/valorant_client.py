import base64
import json
import logging
import re
import time
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
        self._jwt_payload: dict = {}
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "RiotClient/91.0.2.1870.3774 rso-auth (Windows;10;;Professional, x64)"
                ),
                "Accept": "*/*",
            }
        )

    def _build_cookie_header(self) -> str:
        raw = (self.riot_cookies or self.riot_ssid or "").strip()
        if not raw:
            raise RiotAuthError("未提供 RIOT_SSID 或 RIOT_COOKIES。")
        if raw.lower().startswith("cookie:"):
            raw = raw[7:].strip()
        if ";" in raw or "=" in raw:
            return raw
        return f"ssid={raw}"

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
            m_acc = re.search(
                r"access_token=(eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)",
                uri,
            )
            if m_acc:
                access_tokens = [m_acc.group(1)]
            m_id = re.search(
                r"id_token=(eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)",
                uri,
            )
            if m_id and not id_tokens:
                id_tokens = [m_id.group(1)]
        if not access_tokens:
            raise RiotAuthError(
                "無法從 Riot 回應取得 access_token。您的 RIOT_SSID Cookie 可能已過期，請重新取得。"
            )
        return access_tokens[0], (id_tokens[0] if id_tokens else None)

    @staticmethod
    def _parse_cookie_map(raw_cookie_str: str) -> Dict[str, str]:
        clean = raw_cookie_str.strip()
        if clean.lower().startswith("cookie:"):
            clean = clean[7:].strip()
        if ";" not in clean:
            return {}
        result: Dict[str, str] = {}
        for part in clean.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                result[k.strip()] = v.strip()
        return result

    @classmethod
    def _inspect_jwt_info(cls, token_str: str) -> Tuple[dict, str]:
        """Return (decoded_payload_dict, diagnostic_summary) for a JWT or raw token string safely."""
        clean = token_str.strip()
        if clean.lower().startswith("cookie:"):
            clean = clean[7:].strip()
        if clean.startswith("ssid="):
            clean = clean[5:].strip()
        if ";" in clean:
            cmap = cls._parse_cookie_map(clean)
            names = sorted(list(cmap.keys()))
            sub_val = cmap.get("sub", "")
            ssid_val = cmap.get("ssid", "")
            csid_val = cmap.get("csid", "")
            sec_id_tok = cmap.get("__Secure-id_token", "")
            payload = {}
            if ssid_val and ssid_val.startswith("eyJ"):
                payload, _ = cls._inspect_jwt_info(ssid_val)
            elif csid_val and csid_val.startswith("eyJ"):
                payload, _ = cls._inspect_jwt_info(csid_val)
            elif sec_id_tok and sec_id_tok.startswith("eyJ"):
                payload, _ = cls._inspect_jwt_info(sec_id_tok)
            if not sub_val and payload.get("sub"):
                sub_val = str(payload.get("sub"))
            sub_short = sub_val[:8] if sub_val else "None"
            ssid_exp = payload.get("exp")
            ssid_iat = payload.get("iat")
            return (
                payload,
                f"cookie_pairs(len={len(clean)}, names={names}, sub={sub_short}, ssid_len={len(ssid_val)}, csid_len={len(csid_val)}, ssid_iat={ssid_iat}, ssid_exp={ssid_exp})",
            )
        parts = clean.split(".")
        if len(parts) != 3 or not clean.startswith("eyJ"):
            return {}, f"non_jwt(len={len(clean)}, prefix={clean[:4]!r})"
        try:
            padded = parts[1] + "=" * (-len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            keys = sorted(list(payload.keys()))
            exp = payload.get("exp")
            sub_Info = f"keys={keys}, len={len(clean)}, exp={exp}"
            return payload, sub_Info
        except Exception as exc:
            return {}, f"jwt_decode_err(len={len(clean)}, err={exc})"

    def authenticate(self) -> Tuple[str, Optional[str]]:
        """Perform Riot Cookie Reauth and return (access_token, id_token)."""
        raw_input = f"{self.riot_ssid} {self.riot_cookies}".strip()
        if "access_token=" in raw_input and "ssid=" not in raw_input:
            try:
                access_tok, id_tok = self._parse_tokens_from_uri(raw_input)
                parsed_tok, _ = self._inspect_jwt_info(access_tok)
                tok_exp = parsed_tok.get("exp")
                if not (isinstance(tok_exp, (int, float)) and tok_exp <= time.time() + 30):
                    self._jwt_payload = parsed_tok
                    return access_tok, id_tok
            except RiotAuthError:
                pass

        jwt_payload, jwt_diag = self._inspect_jwt_info(self.riot_ssid or self.riot_cookies)
        self._jwt_payload = jwt_payload

        base_cookie_header = self._build_cookie_header()
        clean_tok = (self.riot_ssid or "").strip()
        if clean_tok.startswith("ssid="):
            clean_tok = clean_tok[5:].strip()

        cookie_headers_to_try = []
        cmap = self._parse_cookie_map(base_cookie_header)
        if cmap:
            # 1. Original full Cookie header first (proven working in Run #43020085118)
            cookie_headers_to_try.append(base_cookie_header)
            # 2. Strip analytics/consent/ephemeral & short-lived access_token while keeping __Secure-* auth cookies & ssid
            ephemeral_keys = {
                "asid",
                "ccid",
                "osano_consentmanager",
                "osano_consentmanager_uuid",
                "__cf_bm",
                "_cfuvid",
                "_fbp",
                "_gid",
                "_gcl_au",
                "__Secure-access_token",
            }
            core_parts = [
                f"{k}={v}"
                for k, v in cmap.items()
                if k not in ephemeral_keys and not k.startswith("_ga") and v
            ]
            if core_parts:
                core_header = "; ".join(core_parts)
                if core_header not in cookie_headers_to_try:
                    cookie_headers_to_try.append(core_header)
            # 3. Classic 5 Riot auth cookies fallback
            clean5_keys = ["tdid", "clid", "sub", "csid", "ssid"]
            clean5_parts = [f"{k}={cmap[k]}" for k in clean5_keys if k in cmap and cmap[k]]
            if clean5_parts:
                clean5_header = "; ".join(clean5_parts)
                if clean5_header not in cookie_headers_to_try:
                    cookie_headers_to_try.append(clean5_header)
            # 4. Without csid fallback (in case csid expired separately from ssid)
            no_csid_keys = ["tdid", "clid", "sub", "ssid"]
            no_csid_parts = [f"{k}={cmap[k]}" for k in no_csid_keys if k in cmap and cmap[k]]
            if no_csid_parts:
                no_csid_header = "; ".join(no_csid_parts)
                if no_csid_header not in cookie_headers_to_try:
                    cookie_headers_to_try.append(no_csid_header)
            # 5. Standalone ssid fallback
            if cmap.get("ssid"):
                ssid_only_header = f"ssid={cmap['ssid']}"
                if ssid_only_header not in cookie_headers_to_try:
                    cookie_headers_to_try.append(ssid_only_header)
        else:
            cookie_headers_to_try.append(base_cookie_header)
            if clean_tok and ";" not in base_cookie_header:
                sub_val = jwt_payload.get("sub", "")
                extra_parts = [f"ssid={clean_tok}", f"csid={clean_tok}"]
                if sub_val:
                    extra_parts.append(f"sub={sub_val}")
                extra_parts.append("clid=ap1")
                cookie_headers_to_try.insert(0, "; ".join(extra_parts))

        auth_attempts = [
            (
                "GET(web)",
                "GET",
                (
                    "https://auth.riotgames.com/authorize"
                    "?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in"
                    "&client_id=play-valorant-web-prod"
                    "&response_type=token%20id_token"
                    "&nonce=1"
                    "&scope=account%20openid"
                ),
                None,
            ),
            (
                "GET(riot-client)",
                "GET",
                (
                    "https://auth.riotgames.com/authorize"
                    "?client_id=riot-client"
                    "&response_type=id_token%20token"
                    "&redirect_uri=http%3A%2F%2Flocalhost%2Fredirect"
                    "&scope=read"
                ),
                None,
            ),
            (
                "POST(v1)",
                "POST",
                "https://auth.riotgames.com/api/v1/authorization",
                {
                    "client_id": "play-valorant-web-prod",
                    "nonce": "1",
                    "redirect_uri": "https://playvalorant.com/opt_in",
                    "response_type": "token id_token",
                    "scope": "account openid",
                },
            ),
        ]

        diagnostics: List[str] = [f"token_info=[{jwt_diag}]"]
        redirected_to_login = False

        for c_idx, cookie_header in enumerate(cookie_headers_to_try):
            for label, method, url, json_body in auth_attempts:
                self.session.cookies.clear()
                attempt_label = label if c_idx == 0 else f"{label}#base{c_idx}"
                try:
                    if method == "POST":
                        resp = self.session.post(
                            url,
                            headers={
                                "Cookie": cookie_header,
                                "Accept": "application/json",
                            },
                            json=json_body,
                            allow_redirects=False,
                            timeout=self.timeout,
                        )
                    else:
                        resp = self.session.get(
                            url,
                            headers={
                                "Cookie": cookie_header,
                                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                            },
                            allow_redirects=False,
                            timeout=self.timeout,
                        )

                    location = resp.headers.get("Location", "")
                    if not location and resp.status_code == 200:
                        try:
                            data = resp.json()
                            location = (
                                data.get("response", {})
                                .get("parameters", {})
                                .get("uri", "")
                            )
                            if c_idx == 0 and not location and data.get("type"):
                                diagnostics.append(
                                    f"{attempt_label}: HTTP 200 type={data.get('type')} error={data.get('error', '')}"
                                )
                        except Exception:
                            pass

                    if "access_token=" in location:
                        logger.info("透過 %s 成功交換取得最新 access_token", attempt_label)
                        access_tok, id_tok = self._parse_tokens_from_uri(location)
                        parsed_payload, _ = self._inspect_jwt_info(access_tok)
                        if parsed_payload:
                            self._jwt_payload = parsed_payload
                        return access_tok, id_tok

                    if c_idx == 0:
                        if location:
                            parsed_loc = urlparse(location)
                            safe_loc = f"{parsed_loc.scheme}://{parsed_loc.netloc}{parsed_loc.path}"
                            if parsed_loc.query:
                                q_params = parse_qs(parsed_loc.query)
                                if "error" in q_params:
                                    safe_loc += f"?error={q_params['error'][0]}"
                            diagnostics.append(f"{attempt_label}: HTTP {resp.status_code} -> {safe_loc}")
                        elif not (resp.status_code == 200 and "type=" in diagnostics[-1]):
                            body_preview = resp.text[:100].replace("\n", " ").strip()
                            diagnostics.append(
                                f"{attempt_label}: HTTP {resp.status_code} ({body_preview})"
                            )

                    if (
                        "authenticate.riotgames.com" in location
                        or "xsso.riotgames.com" in location
                        or "/login" in location
                    ):
                        redirected_to_login = True
                except Exception as exc:
                    if c_idx == 0:
                        diagnostics.append(f"{attempt_label} 例外: {exc}")

        if "access_token=" in raw_input:
            try:
                access_tok, id_tok = self._parse_tokens_from_uri(raw_input)
                parsed_tok, _ = self._inspect_jwt_info(access_tok)
                tok_exp = parsed_tok.get("exp")
                if not (isinstance(tok_exp, (int, float)) and tok_exp <= time.time() + 30):
                    self._jwt_payload = parsed_tok
                    logger.info(
                        "Cookie Reauth 未跳轉 (%s)，改用輸入字串內含的 access_token 進行查詢",
                        " | ".join(diagnostics),
                    )
                    return access_tok, id_tok
                diagnostics.append(f"embedded_access_token_expired(exp={tok_exp})")
            except RiotAuthError:
                pass

        # Fallback: if the token itself carries OAuth claims ('scp' or 'cid'), try using it as an access_token
        if jwt_payload and ("scp" in jwt_payload or jwt_payload.get("cid") == "play-valorant-web-prod"):
            tok_exp = jwt_payload.get("exp")
            if not (isinstance(tok_exp, (int, float)) and tok_exp <= time.time() + 30):
                logger.info(
                    "Cookie Reauth 未跳轉 (%s)，改用直接 Token (%s) 進行查詢",
                    " | ".join(diagnostics),
                    jwt_diag,
                )
                return clean_tok, None
            diagnostics.append(f"direct_token_expired(exp={tok_exp})")

        diag_str = " | ".join(diagnostics)

        if jwt_payload and "acct" in jwt_payload and "aud" in jwt_payload and "scp" not in jwt_payload:
            raise RiotAuthError(
                f"偵測到此帳號貼的是單獨的 `csid` Cookie 或 `id_token`（長度 {len(clean_tok)} 字元，含 acct/aud 但不含 scp），無法單獨換取商店權限！\n"
                "👉 解決方式（二選一）：\n"
                "1. 在 `https://auth.riotgames.com` 的 Cookies 中，將多個欄位用分號串起來貼上：`ssid=值; csid=值; tdid=值; sub=值; clid=ap1`\n"
                "2. 或直接貼上登入完成跳轉後網址列整串 `https://playvalorant.com/opt_in#access_token=eyJ...`（或裡面的 `access_token`，約 1,037 字元）。"
            )

        if any("HTTP 403" in d for d in diagnostics):
            raise RiotAuthError(
                f"Riot 驗證遭到防火牆阻擋 (HTTP 403 Forbidden)，雲端機房 IP 可能被 Cloudflare 攔截。診斷資訊：{diag_str}"
            )
        if redirected_to_login:
            raise RiotAuthError(
                f"Riot Cookie (RIOT_SSID) 已過期、無效或缺少關聯 Cookie（伺服器跳轉回登入頁）。診斷資訊：{diag_str}"
            )
        raise RiotAuthError(
            f"Riot 驗證失敗，請確認 RIOT_SSID 是否正確且未過期。診斷資訊：{diag_str}"
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
        if resp.status_code != 200 or not resp.text.strip():
            raise RiotAuthError(
                f"無法取得 Riot Entitlements Token (HTTP {resp.status_code}, len={len(resp.text)}): {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except Exception as exc:
            raise RiotAuthError(
                f"解析 Riot Entitlements 回應失敗 (HTTP {resp.status_code}): {exc}"
            ) from exc
        token = data.get("entitlements_token")
        if not token:
            raise RiotAuthError("Riot Entitlements 回應缺少 entitlements_token。")
        logger.info("成功取得 Riot Entitlements Token (len=%d)", len(token))
        return token

    def get_user_info(self, access_token: str) -> Tuple[str, str]:
        """Return (puuid, display_name_with_tag)."""
        resp = self.session.get(
            "https://auth.riotgames.com/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self.timeout,
        )
        if resp.status_code == 200 and resp.text.strip():
            try:
                data = resp.json()
                puuid = data.get("sub", "")
                if puuid:
                    acct = data.get("acct") or {}
                    game_name = acct.get("game_name") or "特戰英豪玩家"
                    tag_line = acct.get("tag_line") or ""
                    full_name = f"{game_name}#{tag_line}" if tag_line else game_name
                    return puuid, full_name
            except Exception as exc:
                logger.warning("解析 userinfo JSON 失敗，嘗試從 JWT payload 讀取: %s", exc)
        else:
            logger.warning(
                "userinfo 回應 HTTP %s (len=%d)，改從 JWT payload 讀取玩家 PUUID",
                resp.status_code,
                len(resp.text),
            )

        puuid = (self._jwt_payload or {}).get("sub", "")
        if not puuid:
            raise RiotAuthError(
                f"無法取得 Riot 玩家資訊 (userinfo HTTP {resp.status_code}, len={len(resp.text)}): {resp.text[:200]}"
            )
        acct = (self._jwt_payload or {}).get("acct") or (self._jwt_payload or {}).get("dat") or {}
        if isinstance(acct, dict):
            game_name = acct.get("game_name") or acct.get("gn") or ""
            tag_line = acct.get("tag_line") or acct.get("tl") or ""
            if game_name:
                full_name = f"{game_name}#{tag_line}" if tag_line else game_name
                return puuid, full_name
        return puuid, "特戰英豪玩家"

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
                if resp.status_code == 200 and resp.text.strip():
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
        v3_status = resp.status_code
        v3_len = len(resp.text)

        if resp.status_code in (404, 405) or not resp.text.strip():
            logger.info(
                "storefront v3 回應 HTTP %s (len=%d)，嘗試改用 v2 GET...",
                v3_status,
                v3_len,
            )
            v2_url = f"https://pd.{shard}.a.pvp.net/store/v2/storefront/{puuid}"
            resp = self.session.get(v2_url, headers=headers, timeout=self.timeout)

        if resp.status_code != 200 or not resp.text.strip():
            raise ValorantAPIError(
                f"查詢每日商店失敗 (v3 HTTP {v3_status} len={v3_len}, v2 HTTP {resp.status_code} len={len(resp.text)}): {resp.text[:250]}"
            )
        try:
            return resp.json()
        except Exception as exc:
            raise ValorantAPIError(
                f"解析每日商店 JSON 失敗 (HTTP {resp.status_code}, len={len(resp.text)}): {exc}"
            ) from exc

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

        if player_name == "特戰英豪玩家":
            try:
                name_resp = self.session.put(
                    f"https://pd.{shard}.a.pvp.net/name-service/v2/players",
                    headers=self._build_riot_headers(
                        access_token, entitlements_token, resolved_version
                    ),
                    json=[puuid],
                    timeout=self.timeout,
                )
                if name_resp.status_code == 200 and name_resp.text.strip():
                    entries = name_resp.json()
                    if isinstance(entries, list) and entries:
                        gn = entries[0].get("GameName") or ""
                        tl = entries[0].get("TagLine") or ""
                        if gn:
                            player_name = f"{gn}#{tl}" if tl else gn
            except Exception as exc:
                logger.warning("從 Name Service 查詢玩家名稱失敗 (略過): %s", exc)

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
