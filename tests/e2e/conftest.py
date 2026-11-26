"""Shared opaque-box E2E test harness for SAO: Aincrad 100-Floor Discord RPG.

Dual-Track Lazy Import Rule:
- Module top-level imports are strictly Python stdlib + pytest ONLY.
- All production imports (`src.rpg.*`, `src.memes.*`, `src.config`, `bot`, `discord`)
  are deferred inside fixtures and helper functions so collection succeeds cleanly
  even while implementation milestones run in parallel, while every test invokes
  100% real production classes at runtime.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import dataclasses
import gzip
import inspect
import re
import sqlite3
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Contract-pinned SAO constants (PROJECT.md § Interface Contracts)
# ---------------------------------------------------------------------------

BASE_8_WEAPON_STYLES: tuple[str, ...] = (
    "sword",
    "rapier",
    "katana",
    "axe",
    "mace",
    "holy",
    "scythe",
    "dagger",
)
UNIQUE_2_SKILLS: tuple[str, ...] = ("dual_blades", "holy_sword")
FOUR_DAMAGE_TYPES: tuple[str, ...] = ("slash", "pierce", "blunt", "dragon")
EIGHT_EQUIPMENT_SLOTS: tuple[str, ...] = (
    "weapon",
    "offhand",
    "helmet",
    "armor",
    "gloves",
    "boots",
    "ring",
    "necklace",
)
SIX_RARITIES: tuple[str, ...] = (
    "plain",
    "fine",
    "rare",
    "set",
    "legendary",
    "named",
)
SIX_ZONES: tuple[str, ...] = (
    "town",
    "field",
    "labyrinth",
    "secret_realm",
    "boss_room",
    "roguelike",
)
THREE_CURSORS: tuple[str, ...] = ("green", "orange", "red")
TWO_GAME_MODES: tuple[str, ...] = ("standard", "hardcore")
FOUR_BOSS_MODES: tuple[str, ...] = ("first_kill", "normal", "team_boss", "world_boss")
SEVEN_LEADERBOARD_CATEGORIES: tuple[str, ...] = (
    "floor",
    "power",
    "level",
    "world_boss",
    "guild",
    "col",
    "survival",
)
MILESTONE_14_FLOORS: tuple[int, ...] = (
    1,
    10,
    20,
    25,
    30,
    40,
    50,
    60,
    70,
    74,
    75,
    80,
    90,
    100,
)
EXPECTED_22_SAO_COMMANDS: frozenset[str] = frozenset(
    {
        "start",
        "profile",
        "tower",
        "party",
        "boss",
        "skills",
        "bag",
        "equip",
        "inspect",
        "forge",
        "cook",
        "mine",
        "shop",
        "market",
        "guild",
        "duel",
        "daily",
        "expedition",
        "achievements",
        "leaderboard",
        "rebirth",
        "help",
    }
)
EXPECTED_23_COMMANDS: frozenset[str] = EXPECTED_22_SAO_COMMANDS | {"p"}

SECRET_LEAK_REGEXES: tuple[re.Pattern[str], ...] = (
    re.compile(r"[MN][A-Za-z\d]{23,}\.[\w-]{6}\.[\w-]{27,}"),
    re.compile(r"(?:ghp_|gho_|github_pat_)[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+"),
)

LEGACY_V1_MANIFEST: dict[str, Any] = {
    "schema_version": 1,
    "save_seq": 42,
    "updated_at": 1_759_999_000,
    "players": [
        {
            "user_id": "800001",
            "display_name": "舊紀元劍士",
            "class_id": "swordsman",
            "level": 18,
            "exp": 4500,
            "gold": 12500,
            "gems": 320,
            "abyss_highest": 12,
            "rebirth_count": 0,
            "combat_power": 2400,
        },
        {
            "user_id": "800002",
            "display_name": "舊紀元遊俠",
            "class_id": "ranger",
            "level": 35,
            "exp": 9800,
            "gold": 54000,
            "gems": 900,
            "abyss_highest": 28,
            "rebirth_count": 1,
            "combat_power": 6800,
        },
    ],
    "equipment_count": 2,
    "inventory": {
        "800001": {"iron_ore": 25, "hp_potion": 10},
        "800002": {"enhance_stone": 6},
    },
    "expedition_user": "800001",
    "expedition_ends_at": 1_760_005_000,
}

_MISSING = object()


# ---------------------------------------------------------------------------
# Deterministic Clock & Party Setup dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    """Deterministic UTC epoch clock injected via `now_ts` across E2E tests."""

    _now: int = 1_760_000_000  # 2025-10-09T08:53:20Z

    @property
    def now(self) -> int:
        return self._now

    def advance(
        self,
        seconds: int = 0,
        *,
        minutes: int = 0,
        hours: int = 0,
        days: int = 0,
    ) -> int:
        delta = seconds + minutes * 60 + hours * 3600 + days * 86400
        if delta < 0:
            raise ValueError("FakeClock cannot move backward")
        self._now += delta
        return self._now

    def set(self, ts: int) -> int:
        self._now = int(ts)
        return self._now

    def __call__(self) -> int:
        return self._now


@dataclass
class PartySetup:
    """Structured setup result returned by `make_party_humans`."""

    party_id: str
    leader_id: str
    member_ids: list[str]
    roles: dict[str, str]
    floor: int
    boss_mode: str
    create_result: dict[str, Any]


# ---------------------------------------------------------------------------
# Simulated Discord Boundary Doubles (for W20 & F35 UI/Command verification)
# ---------------------------------------------------------------------------


@dataclass
class FakeDiscordUser:
    id: int
    display_name: str
    name: str = ""
    bot: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.display_name

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"


@dataclass
class FakeDiscordMessage:
    id: int
    channel: FakeDiscordChannel
    content: str = ""
    embeds: list[Any] = field(default_factory=list)
    view: Any = None
    files: list[Any] = field(default_factory=list)
    author: Any = None
    edits: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[Any] = field(default_factory=list)

    async def edit(
        self,
        *,
        content: Any = _MISSING,
        embed: Any = _MISSING,
        embeds: Any = _MISSING,
        view: Any = _MISSING,
    ) -> FakeDiscordMessage:
        record: dict[str, Any] = {}
        if content is not _MISSING:
            self.content = content or ""
            record["content"] = self.content
        if embed is not _MISSING:
            self.embeds = [embed] if embed is not None else []
            record["embeds"] = list(self.embeds)
        if embeds is not _MISSING:
            self.embeds = list(embeds) if embeds is not None else []
            record["embeds"] = list(self.embeds)
        if view is not _MISSING:
            self.view = view
            record["view"] = view
        self.edits.append(record)
        return self

    async def delete(self) -> None:
        if self in self.channel.messages:
            self.channel.messages.remove(self)


class FakeDiscordChannel:
    def __init__(self, channel_id: int = 888001, name: str = "aincrad-raid") -> None:
        self.id = channel_id
        self.name = name
        self.messages: list[FakeDiscordMessage] = []
        self._msg_seq = 1000

    async def send(
        self,
        content: str | None = None,
        *,
        embed: Any = None,
        embeds: list[Any] | None = None,
        view: Any = None,
        file: Any = None,
        files: list[Any] | None = None,
    ) -> FakeDiscordMessage:
        self._msg_seq += 1
        em_list = list(embeds) if embeds else ([embed] if embed is not None else [])
        file_list = list(files) if files else ([file] if file is not None else [])
        msg = FakeDiscordMessage(
            id=self._msg_seq,
            channel=self,
            content=content or "",
            embeds=em_list,
            view=view,
            files=file_list,
        )
        self.messages.append(msg)
        return msg

    async def history(self, limit: int = 50):
        for msg in reversed(self.messages[-limit:]):
            yield msg


class FakeDiscordResponse:
    def __init__(self, interaction: FakeDiscordInteraction) -> None:
        self._interaction = interaction
        self.deferred = False
        self.sent_messages: list[dict[str, Any]] = []
        self.edited_messages: list[dict[str, Any]] = []

    def is_done(self) -> bool:
        return self.deferred or bool(self.sent_messages) or bool(self.edited_messages)

    async def defer(self, *, ephemeral: bool = False, thinking: bool = True) -> None:
        self.deferred = True

    async def send_message(
        self,
        content: str | None = None,
        *,
        embed: Any = None,
        embeds: list[Any] | None = None,
        view: Any = None,
        file: Any = None,
        files: list[Any] | None = None,
        ephemeral: bool = False,
    ) -> FakeDiscordMessage:
        em_list = list(embeds) if embeds else ([embed] if embed is not None else [])
        file_list = list(files) if files else ([file] if file is not None else [])
        msg = await self._interaction.channel.send(
            content=content,
            embeds=em_list,
            view=view,
            files=file_list,
        )
        self._interaction.message = msg
        self.sent_messages.append(
            {
                "content": content,
                "embeds": em_list,
                "view": view,
                "files": file_list,
                "ephemeral": ephemeral,
            }
        )
        return msg

    async def edit_message(
        self,
        *,
        content: Any = _MISSING,
        embed: Any = _MISSING,
        embeds: Any = _MISSING,
        view: Any = _MISSING,
    ) -> None:
        em_list: list[Any] = []
        if embed is not _MISSING and embed is not None:
            em_list = [embed]
        elif embeds is not _MISSING and embeds is not None:
            em_list = list(embeds)
        if self._interaction.message is not None:
            await self._interaction.message.edit(
                content=content,
                embed=embed,
                embeds=embeds,
                view=view,
            )
        self.edited_messages.append(
            {
                "content": None if content is _MISSING else content,
                "embeds": em_list,
                "view": None if view is _MISSING else view,
            }
        )


class FakeDiscordFollowup:
    def __init__(self, interaction: FakeDiscordInteraction) -> None:
        self._interaction = interaction
        self.sent_messages: list[dict[str, Any]] = []

    async def send(
        self,
        content: str | None = None,
        *,
        embed: Any = None,
        embeds: list[Any] | None = None,
        view: Any = None,
        file: Any = None,
        files: list[Any] | None = None,
        ephemeral: bool = False,
        wait: bool = False,
    ) -> FakeDiscordMessage:
        em_list = list(embeds) if embeds else ([embed] if embed is not None else [])
        file_list = list(files) if files else ([file] if file is not None else [])
        msg = await self._interaction.channel.send(
            content=content,
            embeds=em_list,
            view=view,
            files=file_list,
        )
        self._interaction.message = msg
        self.sent_messages.append(
            {
                "content": content,
                "embeds": em_list,
                "view": view,
                "files": file_list,
                "ephemeral": ephemeral,
            }
        )
        return msg


class FakeDiscordInteraction:
    def __init__(
        self,
        user: FakeDiscordUser,
        channel: FakeDiscordChannel | None = None,
        guild_id: int = 777001,
        client: Any = None,
    ) -> None:
        self.user = user
        self.channel = channel or FakeDiscordChannel()
        self.channel_id = self.channel.id
        self.guild_id = guild_id
        self.guild = type("FakeGuild", (), {"id": guild_id, "name": "Aincrad Guild"})()
        self.client = client
        self.message: FakeDiscordMessage | None = None
        self.response = FakeDiscordResponse(self)
        self.followup = FakeDiscordFollowup(self)
        self.data: dict[str, Any] = {}

    async def original_response(self) -> FakeDiscordMessage | None:
        return self.message

    def all_payloads(self) -> list[dict[str, Any]]:
        return (
            list(self.response.sent_messages)
            + list(self.response.edited_messages)
            + list(self.followup.sent_messages)
        )


# ---------------------------------------------------------------------------
# Lazy Production Module Loaders (NEVER imported at module top-level!)
# ---------------------------------------------------------------------------


def load_content_api() -> dict[str, Any]:
    from src.rpg.content.loader import (
        SAOContentBundle,
        load_and_validate_all,
        load_content,
    )

    return {
        "SAOContentBundle": SAOContentBundle,
        "load_content": load_content,
        "load_and_validate_all": load_and_validate_all,
    }


def load_models_api() -> dict[str, Any]:
    from src.rpg import models

    return {
        "models": models,
        "GameError": models.GameError,
        "WeaponStyle": models.WeaponStyle,
        "DamageType": models.DamageType,
        "EquipmentSlot": models.EquipmentSlot,
        "Rarity": models.Rarity,
        "ZoneType": models.ZoneType,
        "CursorColor": models.CursorColor,
        "GameMode": models.GameMode,
        "BossMode": models.BossMode,
        "ComputedStats": models.ComputedStats,
        "EquipmentItem": models.EquipmentItem,
        "PlayerProfile": models.PlayerProfile,
        "ActionResult": models.ActionResult,
    }


def load_db_api() -> dict[str, Any]:
    from src.rpg import database

    return {
        "database": database,
        "RPGDatabase": database.RPGDatabase,
        "SCHEMA_VERSION": getattr(database, "SCHEMA_VERSION", 2),
    }


def load_stats_api() -> dict[str, Any]:
    from src.rpg.systems.stats import compute_player_stats

    return {"compute_player_stats": compute_player_stats}


def load_engine_api() -> dict[str, Any]:
    from src.rpg.engine import GameError, RPGEngine

    return {"RPGEngine": RPGEngine, "GameError": GameError}


def load_bot_api() -> dict[str, Any]:
    import bot
    from src.config import Settings
    from src.memes.catalog import AnimeMemeService
    from src.memes.commands import build_meme_embed, register_meme_commands
    from src.rpg.commands import register_rpg_commands

    return {
        "bot": bot,
        "create_bot": bot.create_bot,
        "Settings": Settings,
        "AnimeMemeService": AnimeMemeService,
        "build_meme_embed": build_meme_embed,
        "register_meme_commands": register_meme_commands,
        "register_rpg_commands": register_rpg_commands,
    }


def instantiate_engine(db: Any, content_bundle: Any) -> Any:
    """Instantiate real RPGEngine matching its public __init__ signature."""
    engine_cls = load_engine_api()["RPGEngine"]
    sig = inspect.signature(engine_cls.__init__)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    if len(params) >= 2:
        second = params[1].name
        if second in ("content", "content_bundle", "bundle"):
            return engine_cls(db, **{second: content_bundle})
        return engine_cls(db, content_bundle)
    return engine_cls(db)


# ---------------------------------------------------------------------------
# Strict 3-Layer Payload & Error Assertions (Zero Tautologies)
# ---------------------------------------------------------------------------


def as_mapping(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return {"value": obj}


def _collect_string_values(obj: Any, *, depth: int = 0) -> list[str]:
    if depth > 6:
        return []
    if isinstance(obj, str):
        return [obj] if obj.strip() else []
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        obj = dataclasses.asdict(obj)
    if isinstance(obj, Mapping):
        out: list[str] = []
        for v in obj.values():
            out.extend(_collect_string_values(v, depth=depth + 1))
        return out
    if isinstance(obj, (list, tuple, set)):
        out = []
        for item in obj:
            out.extend(_collect_string_values(item, depth=depth + 1))
        return out
    return []


def extract_text_blob(res: Any) -> str:
    return "\n".join(_collect_string_values(res))


def has_zh_tw(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def assert_ok_result(res: Any, *, require_zh_tw: bool = False) -> dict[str, Any]:
    """Validate structured non-empty ActionResult/dict payload with ok != False."""
    mapping = as_mapping(res)
    assert isinstance(mapping, dict) and len(mapping) > 0, (
        f"Expected non-empty dict/dataclass payload, got {type(res)}: {res!r}"
    )
    if "ok" in mapping:
        assert mapping["ok"] is True, f"Expected ok=True, got failure payload: {mapping!r}"
    if "error_code" in mapping:
        assert not mapping["error_code"], f"Unexpected error_code in ok payload: {mapping!r}"
    if require_zh_tw:
        blob = extract_text_blob(mapping)
        assert has_zh_tw(blob), f"Expected zh-TW user-facing text in payload, got: {blob!r}"
    return mapping


def unwrap_payload(res: Any) -> dict[str, Any]:
    """Assert ok result and merge top-level + `data` dict for clean inspection."""
    mapping = assert_ok_result(res)
    merged = dict(mapping)
    data = mapping.get("data")
    if dataclasses.is_dataclass(data) and not isinstance(data, type):
        data = dataclasses.asdict(data)
    if isinstance(data, dict):
        for k, v in data.items():
            merged.setdefault(k, v)
    return merged


_NESTED_CONTAINERS: tuple[str, ...] = (
    "data",
    "player",
    "profile",
    "stats",
    "computed_stats",
    "floor_info",
    "floor",
    "boss",
    "boss_state",
    "combat",
    "session",
    "party",
    "lobby",
    "raid",
    "chest",
    "roguelike",
    "run",
    "survival",
    "survival_config",
    "guild",
    "duel",
    "market",
    "listing",
    "stew",
    "monument",
    "intel",
    "logs",
    "item",
    "equipment",
    "expedition",
    "quest",
    "result",
    "world_boss",
    "rewards",
    "loot",
)


def _iter_containers(payload: Any) -> list[dict[str, Any]]:
    root = as_mapping(payload)
    containers: list[dict[str, Any]] = [root]
    seen_ids = {id(root)}

    def _enqueue(val: Any, depth: int) -> None:
        if depth > 3:
            return
        if dataclasses.is_dataclass(val) and not isinstance(val, type):
            val = dataclasses.asdict(val)
        if isinstance(val, dict) and id(val) not in seen_ids:
            seen_ids.add(id(val))
            containers.append(val)
            for key in _NESTED_CONTAINERS:
                if key in val and val[key] is not None:
                    _enqueue(val[key], depth + 1)

    for key in _NESTED_CONTAINERS:
        if key in root and root[key] is not None:
            _enqueue(root[key], 1)
    return containers


def extract_field(payload: Any, *candidate_keys: str, default: Any = _MISSING) -> Any:
    """Strictly extract a semantic field from payload or standard nested containers.

    Raises AssertionError if missing and no explicit default is provided.
    """
    containers = _iter_containers(payload)
    for container in containers:
        for key in candidate_keys:
            if key in container and container[key] is not None:
                return container[key]
    if default is not _MISSING:
        return default
    available = {k for c in containers for k in c}
    raise AssertionError(
        f"Contract field missing: none of {candidate_keys!r} found; "
        f"available keys={sorted(available)!r}; payload={payload!r}"
    )


_NOT_FOUND = object()


def has_field(payload: Any, *candidate_keys: str) -> bool:
    return extract_field(payload, *candidate_keys, default=_NOT_FOUND) is not _NOT_FOUND


def assert_game_error(
    fn: Callable[[], Any],
    *,
    code_contains: str | None = None,
    msg_contains: str | Iterable[str] | None = None,
) -> Exception:
    """Invoke `fn()` and verify it raises GameError(ValueError) with `.code` and zh-TW msg."""
    game_error_cls = load_engine_api()["GameError"]
    assert issubclass(game_error_cls, ValueError), (
        f"GameError must inherit from ValueError, got MRO {game_error_cls.__mro__}"
    )
    with pytest.raises(game_error_cls) as exc_info:
        fn()
    exc = exc_info.value
    code = getattr(exc, "code", None)
    assert isinstance(code, str) and code.strip(), (
        f"GameError.code must be a non-empty string, got {code!r}"
    )
    msg = str(exc).strip()
    assert msg, "GameError message must be non-empty"
    assert has_zh_tw(msg), f"GameError message must contain zh-TW text, got: {msg!r}"
    if code_contains is not None:
        assert code_contains.lower() in code.lower(), (
            f"Expected GameError.code containing {code_contains!r}, got {code!r}"
        )
    if msg_contains is not None:
        needles = (msg_contains,) if isinstance(msg_contains, str) else tuple(msg_contains)
        assert any(n in msg for n in needles), (
            f"Expected one of {needles!r} in GameError message {msg!r}"
        )
    return exc


def assert_no_secrets(text: str, *, context: str = "payload") -> None:
    for pattern in SECRET_LEAK_REGEXES:
        match = pattern.search(text)
        assert match is None, f"Secret pattern leaked in {context}: {match.group(0)!r}"


def assert_discord_payload_valid(
    *,
    embed: Any = None,
    embeds: list[Any] | None = None,
    view: Any = None,
    content: str | None = None,
) -> None:
    """Enforce Discord API hard constraints, raster-only assets, and zero secret leaks."""
    if content is not None:
        assert isinstance(content, str)
        assert len(content) <= 2000, f"Discord content exceeds 2000 chars: {len(content)}"
        assert_no_secrets(content, context="discord content")

    embed_list: list[Any] = []
    if embed is not None:
        embed_list.append(embed)
    if embeds:
        embed_list.extend(embeds)

    assert len(embed_list) <= 10, f"Discord allows <=10 embeds per message, got {len(embed_list)}"
    for em in embed_list:
        em_dict = em.to_dict() if hasattr(em, "to_dict") else dict(em)
        title = str(em_dict.get("title") or "")
        desc = str(em_dict.get("description") or "")
        footer_text = str((em_dict.get("footer") or {}).get("text") or "")
        author_name = str((em_dict.get("author") or {}).get("name") or "")
        fields = list(em_dict.get("fields") or [])

        assert len(title) <= 256, f"Embed title > 256: {len(title)}"
        assert len(desc) <= 4096, f"Embed description > 4096: {len(desc)}"
        assert len(footer_text) <= 2048, f"Embed footer > 2048: {len(footer_text)}"
        assert len(author_name) <= 256, f"Embed author > 256: {len(author_name)}"
        assert len(fields) <= 25, f"Embed fields > 25: {len(fields)}"

        total_chars = len(title) + len(desc) + len(footer_text) + len(author_name)
        for fld in fields:
            fname = str(fld.get("name") or "")
            fval = str(fld.get("value") or "")
            assert len(fname) <= 256, f"Embed field name > 256: {len(fname)}"
            assert len(fval) <= 1024, f"Embed field value > 1024: {len(fval)}"
            total_chars += len(fname) + len(fval)
        assert total_chars <= 6000, f"Embed total chars > 6000: {total_chars}"

        url_candidates = [
            (em_dict.get("image") or {}).get("url"),
            (em_dict.get("thumbnail") or {}).get("url"),
            (em_dict.get("author") or {}).get("icon_url"),
            (em_dict.get("footer") or {}).get("icon_url"),
        ]
        for url in url_candidates:
            if url:
                url_str = str(url)
                assert url_str.startswith("https://"), f"Non-HTTPS asset URL: {url_str!r}"
                assert ".svg" not in url_str.lower(), f"Forbidden SVG asset URL: {url_str!r}"

        assert_no_secrets(str(em_dict), context="discord embed")

    if view is not None:
        children = list(getattr(view, "children", []))
        assert len(children) <= 25, f"Discord View children > 25: {len(children)}"
        row_widths: dict[int, int] = {}
        for child in children:
            row = getattr(child, "row", None)
            assert row is None or (isinstance(row, int) and 0 <= row <= 4), (
                f"Discord View child row out of 0..4: {row!r}"
            )
            label = str(getattr(child, "label", "") or "")
            cid = str(getattr(child, "custom_id", "") or "")
            assert_no_secrets(f"{label} {cid}", context="discord view child")

            if hasattr(child, "options"):
                opts = list(child.options)
                assert 1 <= len(opts) <= 25, (
                    f"Discord Select options must be in 1..25, got {len(opts)}"
                )
                for opt in opts:
                    assert_no_secrets(
                        f"{getattr(opt, 'label', '')} {getattr(opt, 'value', '')}",
                        context="discord select option",
                    )
                width = 5
            else:
                width = 1
            if row is not None:
                row_widths[row] = row_widths.get(row, 0) + width
                assert row_widths[row] <= 5, (
                    f"Discord View row {row} exceeds 5-slot width budget: {row_widths[row]}"
                )


# ---------------------------------------------------------------------------
# Dynamic Content Bundle Pickers (Zero Guessed JSON Slugs)
# ---------------------------------------------------------------------------


def iter_entries(collection: Any) -> list[tuple[str, dict[str, Any]]]:
    """Normalize dict[id, spec] or list[spec] or wrapper dicts from JSON content."""
    if isinstance(collection, list):
        out: list[tuple[str, dict[str, Any]]] = []
        for idx, item in enumerate(collection):
            if isinstance(item, dict):
                eid = str(
                    item.get("id")
                    or item.get("skill_id")
                    or item.get("item_id")
                    or item.get("recipe_id")
                    or item.get("boss_id")
                    or item.get("mob_id")
                    or item.get("quest_id")
                    or item.get("expedition_id")
                    or item.get("achievement_id")
                    or item.get("title_id")
                    or item.get("talent_id")
                    or idx
                )
                out.append((eid, item))
        return out
    if isinstance(collection, dict):
        # Detect top-level wrapper containers (e.g. {"items": {...}} or {"skills": [...]})
        out = []
        for k, v in collection.items():
            if isinstance(v, dict):
                # Is `v` an entry dict or a sub-collection of entries?
                if any(
                    marker in v
                    for marker in (
                        "name",
                        "zh_name",
                        "title",
                        "weapon_style",
                        "weapon",
                        "sp_cost",
                        "hp_bars",
                        "phases",
                        "slot",
                        "rarity",
                        "ingredients",
                        "inputs",
                        "materials",
                        "outputs",
                        "output",
                        "choices",
                        "duration",
                        "duration_sec",
                        "duration_seconds",
                        "floor",
                        "tier",
                        "dmg_type",
                        "damage_type",
                        "price",
                        "price_col",
                        "kind",
                        "category",
                        "type",
                    )
                ):
                    out.append((str(k), v))
                else:
                    sub = iter_entries(v)
                    if sub:
                        out.extend(sub)
            elif isinstance(v, list):
                out.extend(iter_entries(v))
        return out
    return []


def pick_sword_skills(
    content_bundle: Any,
    weapon_style: str,
    *,
    count: int = 1,
    include_unique: bool = False,
    tag: str | None = None,
) -> list[str]:
    entries = iter_entries(content_bundle.sword_skills)
    matched: list[str] = []
    for sid, spec in entries:
        styles_raw = (
            spec.get("weapon_class")
            or spec.get("weapon_style")
            or spec.get("weapon_styles")
            or spec.get("weapon")
            or spec.get("style")
            or spec.get("unique_skill")
            or ""
        )
        styles = (
            [str(s).lower() for s in styles_raw]
            if isinstance(styles_raw, (list, tuple, set))
            else [str(styles_raw).lower()]
        )
        is_unique = bool(
            spec.get("is_unique")
            or spec.get("unique_skill")
            or any(u in styles for u in UNIQUE_2_SKILLS)
        )
        if not include_unique and is_unique and weapon_style.lower() not in UNIQUE_2_SKILLS:
            continue
        if weapon_style.lower() not in styles:
            continue
        if tag is not None:
            blob = f"{sid} {spec}".lower()
            if tag.lower() not in blob:
                continue
        if sid not in matched:
            matched.append(sid)
    assert len(matched) >= count, (
        f"Expected >= {count} sword skills for style={weapon_style!r} (tag={tag!r}), "
        f"found {matched!r}"
    )
    return matched[:count]


def pick_item_id(
    content_bundle: Any,
    *,
    id_keywords: tuple[str, ...] = (),
    name_keywords: tuple[str, ...] = (),
    kind_keywords: tuple[str, ...] = (),
    exclude_keywords: tuple[str, ...] = (),
) -> str:
    entries = iter_entries(content_bundle.items_crystals)
    for iid, spec in entries:
        iid_l = iid.lower()
        name_s = str(spec.get("name") or spec.get("zh_name") or "")
        kind_s = str(
            spec.get("kind")
            or spec.get("type")
            or spec.get("category")
            or spec.get("effect")
            or ""
        ).lower()
        blob = f"{iid_l} {name_s.lower()} {kind_s} {str(spec).lower()}"
        if exclude_keywords and any(ex.lower() in blob for ex in exclude_keywords):
            continue
        id_ok = not id_keywords or any(k.lower() in iid_l for k in id_keywords)
        name_ok = not name_keywords or any(k in name_s for k in name_keywords)
        kind_ok = not kind_keywords or any(k.lower() in blob for k in kind_keywords)
        if id_ok and name_ok and kind_ok:
            return iid
    # Fallback relaxed OR match across id/name/kind keywords
    for iid, spec in entries:
        iid_l = iid.lower()
        name_s = str(spec.get("name") or spec.get("zh_name") or "")
        blob = f"{iid_l} {name_s.lower()} {str(spec).lower()}"
        if exclude_keywords and any(ex.lower() in blob for ex in exclude_keywords):
            continue
        if (
            any(k.lower() in iid_l for k in id_keywords)
            or any(k in name_s for k in name_keywords)
            or any(k.lower() in blob for k in kind_keywords)
        ):
            return iid
    raise AssertionError(
        f"No item matched id={id_keywords!r}, name={name_keywords!r}, kind={kind_keywords!r} "
        f"in items_crystals ({len(entries)} entries)"
    )


def pick_crystal_ids(content_bundle: Any) -> dict[str, str]:
    """Resolve all 4 canonical SAO Crystals + Recovery Potion from items_crystals."""
    return {
        "potion": pick_item_id(
            content_bundle,
            id_keywords=("potion", "hp_pot", "recovery_potion"),
            name_keywords=("回復藥水", "藥水", "治療藥水"),
            exclude_keywords=("crystal", "水晶"),
        ),
        "healing": pick_item_id(
            content_bundle,
            id_keywords=("heal_crystal", "healing_crystal", "red_crystal"),
            name_keywords=("回復水晶", "治療水晶", "紅水晶"),
        ),
        "teleport": pick_item_id(
            content_bundle,
            id_keywords=("teleport_crystal", "tp_crystal", "blue_crystal"),
            name_keywords=("轉移水晶", "藍水晶"),
        ),
        "antidote": pick_item_id(
            content_bundle,
            id_keywords=("antidote_crystal", "green_crystal"),
            name_keywords=("解毒水晶", "綠水晶"),
        ),
        "corridor": pick_item_id(
            content_bundle,
            id_keywords=("corridor_crystal", "yellow_crystal"),
            name_keywords=("迴廊水晶", "黃水晶"),
        ),
    }


def pick_magic_stone_id(content_bundle: Any) -> str:
    return pick_item_id(
        content_bundle,
        id_keywords=("magic_stone", "stone", "affix_stone", "reroll", "flip_stone"),
        name_keywords=("魔石", "翻石", "替石", "毛石"),
        exclude_keywords=("enhance_crystal", "亮閃晶", "暗結晶"),
    )


def pick_enhance_materials(content_bundle: Any) -> dict[str, str]:
    bright = pick_item_id(
        content_bundle,
        id_keywords=("bright", "enhance", "crystal_bright"),
        name_keywords=("亮閃晶", "強化石", "強化結晶"),
        exclude_keywords=("dark", "暗", "protect", "保護"),
    )
    protection = pick_item_id(
        content_bundle,
        id_keywords=("protect", "talisman", "charm"),
        name_keywords=("保護符", "守護符"),
    )
    return {"bright": bright, "protection": protection}


def pick_recipe(content_bundle: Any, category: str) -> tuple[str, dict[str, Any]]:
    """Resolve a recipe from content_bundle.recipes for blacksmithing/cooking/stew/fusion."""
    cat_l = category.lower()
    aliases = {
        "blacksmithing": ("blacksmithing", "blacksmith", "forge", "craft", "weapon", "armor"),
        "cooking": ("cooking", "cook", "dish", "food"),
        "stew": ("stew", "big_pot", "big_pot_stew", "pot_stew", "一大鍋"),
        "fusion": ("fusion", "fuse", "refine", "融煉"),
    }
    keys = aliases.get(cat_l, (cat_l,))
    recipes = content_bundle.recipes
    if isinstance(recipes, dict):
        for k in keys:
            if recipes.get(k):
                sub = iter_entries(recipes[k])
                if sub:
                    return sub[0]
    for rid, spec in iter_entries(recipes):
        blob = f"{rid} {spec.get('category', '')} {spec.get('type', '')} {spec.get('station', '')} {spec.get('name', '')}".lower()
        if any(a.lower() in blob for a in keys):
            return rid, spec
    raise AssertionError(f"No recipe found for category={category!r} in content_bundle.recipes")


def pick_story_choice(
    content_bundle: Any,
    *,
    karma_negative: bool | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Resolve (chapter_id, choice_id, choice_spec) from quests_events."""
    qe = content_bundle.quests_events
    story_section = None
    if isinstance(qe, dict):
        for k in ("story", "main_story", "story_chapters", "chapters"):
            if qe.get(k):
                story_section = qe[k]
                break
    chapters = iter_entries(story_section if story_section is not None else qe)
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for ch_id, ch_spec in chapters:
        choices_raw = ch_spec.get("choices") or ch_spec.get("options")
        if not choices_raw:
            continue
        for c_id, c_spec in iter_entries(choices_raw):
            candidates.append((ch_id, c_id, c_spec))
    assert candidates, "Expected story chapters with choices in content_bundle.quests_events"
    if karma_negative is True:
        for ch_id, c_id, c_spec in candidates:
            karma_val = c_spec.get("karma", c_spec.get("karma_delta", c_spec.get("cursor_delta", 0)))
            cursor_val = str(c_spec.get("cursor", c_spec.get("cursor_color", ""))).lower()
            if (isinstance(karma_val, (int, float)) and karma_val < 0) or cursor_val in (
                "orange",
                "red",
            ):
                return ch_id, c_id, c_spec
    elif karma_negative is False:
        for ch_id, c_id, c_spec in candidates:
            karma_val = c_spec.get("karma", c_spec.get("karma_delta", c_spec.get("cursor_delta", 0)))
            if isinstance(karma_val, (int, float)) and karma_val >= 0:
                return ch_id, c_id, c_spec
    return candidates[0]


def pick_expedition(content_bundle: Any) -> tuple[str, dict[str, Any], int]:
    qe = content_bundle.quests_events
    section = None
    if isinstance(qe, dict):
        for k in ("expeditions", "offline_expeditions"):
            if qe.get(k):
                section = qe[k]
                break
    entries = iter_entries(section if section is not None else [])
    assert entries, "Expected expeditions catalog in content_bundle.quests_events"
    eid, spec = entries[0]
    duration = int(
        spec.get("duration_seconds")
        or spec.get("duration_sec")
        or spec.get("duration")
        or (int(spec.get("duration_minutes", 30)) * 60)
    )
    return eid, spec, max(60, duration)


def pick_talent_pair(
    content_bundle: Any,
    weapon_style: str = "sword",
) -> tuple[str, str | None]:
    """Find (root_talent_id, child_talent_id_or_None) from content bundle."""
    sources = [
        content_bundle.weapons_equipment,
        content_bundle.sword_skills,
        content_bundle.quests_events,
    ]
    talents: list[tuple[str, dict[str, Any]]] = []
    for src in sources:
        if isinstance(src, dict):
            for k in ("talents", "talent_trees", "weapon_talents"):
                if src.get(k):
                    talents.extend(iter_entries(src[k]))
    if not talents:
        # Check inside weapon_classes[weapon_style]["talents" | "talent_tree"]
        we = content_bundle.weapons_equipment
        if isinstance(we, dict):
            wc = we.get("weapon_classes") or {}
            for _, wspec in iter_entries(wc):
                if isinstance(wspec, dict):
                    raw_t = wspec.get("talents") or wspec.get("talent_tree")
                    if raw_t:
                        talents.extend(iter_entries(raw_t))
    assert talents, "Expected weapon talent definitions in content_bundle"

    # Prefer matching weapon_style
    filtered = [
        (tid, tspec)
        for tid, tspec in talents
        if weapon_style.lower() in f"{tid} {tspec}".lower()
    ] or talents

    roots = [
        (tid, tspec)
        for tid, tspec in filtered
        if not (tspec.get("requires") or tspec.get("prereq") or tspec.get("parent"))
    ]
    root_id = roots[0][0] if roots else filtered[0][0]
    child_id = None
    for tid, tspec in filtered:
        req = tspec.get("requires") or tspec.get("prereq") or tspec.get("parent")
        if req == root_id or (isinstance(req, list) and root_id in req):
            child_id = tid
            break
    return root_id, child_id


def pick_set_and_named_templates(
    content_bundle: Any,
) -> tuple[list[tuple[str, dict[str, Any]]], tuple[str, dict[str, Any]]]:
    """Return (set_items_list, (named_id, named_spec)) from weapons_equipment."""
    we = content_bundle.weapons_equipment
    named_entries: list[tuple[str, dict[str, Any]]] = []
    set_entries: list[tuple[str, dict[str, Any]]] = []
    if isinstance(we, dict):
        if we.get("named_items"):
            named_entries.extend(iter_entries(we["named_items"]))
        if we.get("sets"):
            set_entries.extend(iter_entries(we["sets"]))
        if we.get("base_gear"):
            for gid, gspec in iter_entries(we["base_gear"]):
                r = str(gspec.get("rarity", "")).lower()
                if r == "named":
                    named_entries.append((gid, gspec))
                elif r == "set":
                    set_entries.append((gid, gspec))
    assert named_entries, "Expected named_items in content_bundle.weapons_equipment"
    assert set_entries, "Expected sets in content_bundle.weapons_equipment"
    return set_entries, named_entries[0]


def pick_achievement_and_title(
    content_bundle: Any,
) -> tuple[tuple[str, dict[str, Any]], list[tuple[str, dict[str, Any]]]]:
    qe = content_bundle.quests_events
    achs = iter_entries(qe.get("achievements", {}) if isinstance(qe, dict) else {})
    titles = iter_entries(qe.get("titles", {}) if isinstance(qe, dict) else {})
    assert achs, "Expected achievements in content_bundle.quests_events"
    assert titles, "Expected titles in content_bundle.quests_events"
    return achs[0], titles


def pick_boss_spec(content_bundle: Any, floor: int) -> tuple[str, dict[str, Any]]:
    """Resolve boss spec for a floor from floors_override + bosses."""
    fo = content_bundle.floors_override
    boss_id = None
    if isinstance(fo, dict):
        fspec = fo.get(str(floor)) or fo.get(floor)
        if isinstance(fspec, dict):
            boss_id = fspec.get("boss_id")
    bosses = iter_entries(content_bundle.bosses)
    if boss_id:
        for bid, bspec in bosses:
            if bid == boss_id:
                return bid, bspec
    for bid, bspec in bosses:
        if bspec.get("floor") == floor:
            return bid, bspec
    raise AssertionError(f"No milestone boss found for floor={floor} in content_bundle.bosses")


# ---------------------------------------------------------------------------
# Database Snapshot & Public State Helpers (Contract-Safe)
# ---------------------------------------------------------------------------


def get_db_save_seq(db: Any) -> int:
    if hasattr(db, "save_seq"):
        val = db.save_seq
        return int(val() if callable(val) else val)
    if hasattr(db, "get_save_seq"):
        return int(db.get_save_seq())
    raise AssertionError("RPGDatabase must expose `save_seq` or `get_save_seq()`")


def export_db_snapshot_bytes(db: Any) -> bytes:
    if hasattr(db, "export_snapshot_bytes"):
        data = db.export_snapshot_bytes()
    elif hasattr(db, "export_gzip_snapshot"):
        res = db.export_gzip_snapshot()
        data = res[1] if isinstance(res, tuple) else res
    else:
        raise AssertionError("RPGDatabase must expose `export_snapshot_bytes()`")
    assert isinstance(data, (bytes, bytearray)) and len(data) > 0
    assert data[:2] == b"\x1f\x8b", "Exported snapshot must be valid Gzip bytes"
    return bytes(data)


def import_db_snapshot_bytes(db: Any, payload: bytes, *, force: bool = False) -> bool:
    if hasattr(db, "import_snapshot_bytes"):
        sig = inspect.signature(db.import_snapshot_bytes)
        if "force" in sig.parameters:
            res = db.import_snapshot_bytes(payload, force=force)
        else:
            res = db.import_snapshot_bytes(payload)
        return True if res is None else bool(res)
    if hasattr(db, "import_gzip_snapshot"):
        return bool(db.import_gzip_snapshot(payload, force=force))
    raise AssertionError("RPGDatabase must expose `import_snapshot_bytes(payload)`")


# ---------------------------------------------------------------------------
# Player Read-Back Extractors (Strictly via Public `get_profile`)
# ---------------------------------------------------------------------------


def get_player_col(engine: Any, user_id: str, clock: FakeClock | None = None) -> int:
    prof = engine.get_profile(user_id, now_ts=clock.now if clock else None)
    return int(extract_field(prof, "col", "gold"))


def get_player_floor(engine: Any, user_id: str, clock: FakeClock | None = None) -> tuple[int, int]:
    prof = engine.get_profile(user_id, now_ts=clock.now if clock else None)
    cur = int(extract_field(prof, "current_floor", "floor"))
    highest = int(
        extract_field(
            prof,
            "max_unlocked_floor",
            "highest_floor",
            "unlocked_floor",
            "max_floor",
            default=cur,
        )
    )
    return cur, highest


def get_player_zone(engine: Any, user_id: str, clock: FakeClock | None = None) -> str:
    prof = engine.get_profile(user_id, now_ts=clock.now if clock else None)
    return str(extract_field(prof, "zone", "current_zone")).lower()


def get_player_cursor(engine: Any, user_id: str, clock: FakeClock | None = None) -> str:
    prof = engine.get_profile(user_id, now_ts=clock.now if clock else None)
    return str(extract_field(prof, "cursor_color", "cursor")).lower()


def get_player_miasma(engine: Any, user_id: str, clock: FakeClock | None = None) -> int:
    prof = engine.get_profile(user_id, now_ts=clock.now if clock else None)
    return int(extract_field(prof, "miasma_stacks", "miasma", default=0))


def get_player_item_qty(
    engine: Any,
    user_id: str,
    item_id: str,
    clock: FakeClock | None = None,
) -> int:
    prof = engine.get_profile(user_id, now_ts=clock.now if clock else None)
    for key in ("inventory", "quick_pouch", "pouch", "items", "consumables"):
        inv = extract_field(prof, key, default=None)
        if isinstance(inv, dict) and item_id in inv:
            val = inv[item_id]
            return int(val["qty"] if isinstance(val, dict) and "qty" in val else val)
        if isinstance(inv, list):
            for entry in inv:
                if isinstance(entry, dict) and (
                    entry.get("item_id") == item_id or entry.get("id") == item_id
                ):
                    return int(entry.get("qty", entry.get("quantity", 0)))
    return 0


def get_player_equipment(
    engine: Any,
    user_id: str,
    clock: FakeClock | None = None,
) -> list[dict[str, Any]]:
    prof = engine.get_profile(user_id, now_ts=clock.now if clock else None)
    raw = extract_field(prof, "equipment", "bag", "gear", "equipped_items", default=[])
    items: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for entry in raw:
            items.append(as_mapping(entry))
    elif isinstance(raw, dict):
        for val in raw.values():
            if val is not None:
                items.append(as_mapping(val))
    return items


def get_player_pending_loot_count(
    engine: Any,
    user_id: str,
    clock: FakeClock | None = None,
) -> int:
    prof = engine.get_profile(user_id, now_ts=clock.now if clock else None)
    val = extract_field(prof, "pending_loot_count", "pending_loot", "mailbox", default=0)
    if isinstance(val, (list, dict)):
        return len(val)
    return int(val)


def get_player_life_skills(
    engine: Any,
    user_id: str,
    clock: FakeClock | None = None,
) -> dict[str, Any]:
    prof = engine.get_profile(user_id, now_ts=clock.now if clock else None)
    skills = extract_field(prof, "life_skills", "passive_skills", "mastery", default={})
    return as_mapping(skills)


# ---------------------------------------------------------------------------
# Opaque-Box Public Arrange/Setup Helpers (Zero Private Internals)
# ---------------------------------------------------------------------------


def _call_public_db_method(db: Any, candidates: tuple[str, ...], *args: Any, **kwargs: Any) -> Any:
    for name in candidates:
        fn = getattr(db, name, None)
        if callable(fn):
            return fn(*args, **kwargs)
    return _MISSING


def seed_col(db: Any, engine: Any, user_id: str, amount: int, clock: FakeClock) -> int:
    """Ensure player has at least `amount` Col using public DB/Engine APIs."""
    cur = get_player_col(engine, user_id, clock)
    if cur >= amount:
        return cur
    delta = amount - cur
    res = _call_public_db_method(db, ("add_col", "add_gold", "adjust_col"), user_id, delta)
    if res is _MISSING:
        player = _call_public_db_method(db, ("get_player",), user_id)
        if player is not _MISSING and player is not None:
            for attr in ("col", "gold"):
                if hasattr(player, attr):
                    setattr(player, attr, int(getattr(player, attr)) + delta)
                    break
            _call_public_db_method(db, ("save_player", "upsert_player", "update_player"), player)
    return get_player_col(engine, user_id, clock)


def seed_item(db: Any, user_id: str, item_id: str, qty: int) -> None:
    res = _call_public_db_method(
        db,
        ("add_item", "add_inventory_item", "upsert_inventory", "add_pouch_item"),
        user_id,
        item_id,
        qty,
    )
    assert res is not _MISSING, (
        "RPGDatabase must expose a public inventory add method (`add_item` / `add_inventory_item`)"
    )


def seed_equipment(
    db: Any,
    user_id: str,
    *,
    slot: str = "weapon",
    rarity: str = "rare",
    name: str = "鋼鐵長劍",
    template_id: str = "e2e_steel_sword",
    weapon_style: str = "sword",
    tier: int = 1,
    set_id: str = "",
    enhance_level: int = 0,
    atk: int = 45,
    defense: int = 15,
    hp: int = 120,
    sp: int = 20,
    affixes: dict[str, Any] | None = None,
    is_locked: bool = False,
    now_ts: int = 1_760_000_000,
) -> int:
    """Create a real EquipmentItem via public `models.EquipmentItem` + `RPGDatabase`."""
    eq_cls = load_models_api()["EquipmentItem"]
    sig = inspect.signature(eq_cls)
    kwargs: dict[str, Any] = {}
    field_values = {
        "id": 0,
        "item_uid": 0,
        "user_id": user_id,
        "template_id": template_id,
        "item_id": template_id,
        "name": name,
        "slot": slot,
        "rarity": rarity,
        "weapon_style": weapon_style,
        "weapon_class": weapon_style,
        "tier": tier,
        "floor_tier": tier,
        "req_level": max(1, (tier - 1) * 10 + 1),
        "level": max(1, (tier - 1) * 10 + 1),
        "set_id": set_id,
        "enhance_level": enhance_level,
        "enhance_pity": 0,
        "base_hp": hp,
        "hp": hp,
        "base_sp": sp,
        "base_mp": sp,
        "sp": sp,
        "base_atk": atk,
        "atk": atk,
        "base_def": defense,
        "defense": defense,
        "affixes": affixes or {},
        "affixes_json": affixes or {},
        "is_equipped": False,
        "is_locked": is_locked,
        "created_at": now_ts,
    }
    for pname in sig.parameters:
        if pname in field_values:
            val = field_values[pname]
            if pname == "affixes_json" and isinstance(val, dict):
                import json

                val = json.dumps(val, ensure_ascii=False)
            kwargs[pname] = val
    item = eq_cls(**kwargs)
    created = _call_public_db_method(
        db,
        ("add_equipment", "create_equipment", "insert_equipment"),
        item,
    )
    if created is _MISSING:
        created = _call_public_db_method(
            db,
            ("add_equipment", "create_equipment"),
            user_id,
            item,
        )
    assert created is not _MISSING, "RPGDatabase must expose `add_equipment`"
    if isinstance(created, int):
        return created
    if hasattr(created, "id"):
        return int(created.id)
    if hasattr(created, "item_uid"):
        return int(created.item_uid)
    if isinstance(created, dict):
        return int(extract_field(created, "item_uid", "id"))
    return int(created)


def give_recipe_materials(
    db: Any,
    engine: Any,
    user_id: str,
    recipe_spec: dict[str, Any],
    clock: FakeClock,
    *,
    multiplier: int = 2,
) -> None:
    """Seed required ingredients & Col for a JSON recipe via public APIs."""
    col_cost = int(recipe_spec.get("col_cost") or recipe_spec.get("cost_col") or recipe_spec.get("gold_cost") or 500)
    seed_col(db, engine, user_id, col_cost * multiplier + 1000, clock)
    mats = (
        recipe_spec.get("ingredients")
        or recipe_spec.get("materials")
        or recipe_spec.get("inputs")
        or {}
    )
    if isinstance(mats, dict):
        for item_id, qty in mats.items():
            seed_item(db, user_id, str(item_id), int(qty) * multiplier)
    elif isinstance(mats, list):
        for entry in mats:
            if isinstance(entry, dict):
                iid = str(entry.get("item_id") or entry.get("id"))
                qty = int(entry.get("qty") or entry.get("quantity") or 1)
                seed_item(db, user_id, iid, qty * multiplier)


# ---------------------------------------------------------------------------
# Opaque-Box Combat, Exploration, Progression & Concurrency Helpers
# ---------------------------------------------------------------------------


def _is_combat_finished(res: dict[str, Any]) -> bool:
    for key in ("ended", "finished", "combat_ended", "battle_ended", "victory", "defeat", "retreated"):
        val = extract_field(res, key, default=None)
        if val is True:
            return True
    status = str(extract_field(res, "status", "outcome", "state", default="")).lower()
    if status in ("victory", "win", "won", "defeat", "lost", "lose", "retreated", "fled", "finished", "ended", "cleared"):
        return True
    in_combat = extract_field(res, "in_combat", "active", default=None)
    return in_combat is False


def resolve_active_combat(
    engine: Any,
    user_id: str,
    clock: FakeClock,
    *,
    strategy: str = "attack",
    skill_id: str | None = None,
    heal_item_id: str | None = None,
    max_turns: int = 60,
) -> dict[str, Any]:
    """Drive an active solo combat session to completion via public `combat_action`."""
    last: dict[str, Any] = {}
    for turn in range(max_turns):
        action = strategy
        use_skill = skill_id if action == "skill" else None
        use_item = None
        if heal_item_id and turn > 0 and turn % 4 == 0:
            action = "item"
            use_item = heal_item_id
            use_skill = None
        last = assert_ok_result(
            engine.combat_action(
                user_id,
                action,
                skill_id=use_skill,
                item_id=use_item,
                now_ts=clock.now,
            )
        )
        if _is_combat_finished(last):
            return last
    raise AssertionError(f"Solo combat for {user_id} did not finish within {max_turns} turns: {last!r}")


def explore_to_boss_gate(
    engine: Any,
    user_id: str,
    clock: FakeClock,
    *,
    floor: int | None = None,
    max_steps: int = 80,
    seed_base: int = 1000,
) -> dict[str, Any]:
    """Explore a floor organically via public APIs until Boss Gate unlocks."""
    cur_floor, _ = get_player_floor(engine, user_id, clock)
    target_floor = floor or cur_floor
    if target_floor != cur_floor:
        engine.teleport_floor(user_id, target_floor, now_ts=clock.now)
    if get_player_zone(engine, user_id, clock) == "town":
        engine.travel_zone(user_id, "field", now_ts=clock.now)

    for idx in range(max_steps):
        finfo = assert_ok_result(engine.get_floor_info(target_floor, user_id=user_id))
        pct = int(extract_field(finfo, "exploration_pct", "exploration", "progress", default=0))
        gate = extract_field(finfo, "boss_gate_unlocked", "boss_unlocked", "can_challenge_boss", default=False)
        if pct >= 100 or gate is True:
            return finfo

        step_res = assert_ok_result(
            engine.explore_floor(user_id, steps=1, now_ts=clock.now, rng_seed=seed_base + idx)
        )
        ev_type = str(
            extract_field(step_res, "event_type", "encounter_type", "type", "event", default="")
        ).lower()
        if "chest" in ev_type or has_field(step_res, "chest", "chest_tier"):
            chest_res = assert_ok_result(
                engine.open_chest(user_id, action="open", now_ts=clock.now, rng_seed=seed_base + idx)
            )
            if extract_field(chest_res, "in_combat", "ambush", "is_mimic", default=False):
                resolve_active_combat(engine, user_id, clock)
        elif (
            "combat" in ev_type
            or "monster" in ev_type
            or "mob" in ev_type
            or "battle" in ev_type
            or "boss" in ev_type
            or extract_field(step_res, "in_combat", default=False) is True
        ) and not _is_combat_finished(step_res):
            resolve_active_combat(engine, user_id, clock)

    finfo = assert_ok_result(engine.get_floor_info(target_floor, user_id=user_id))
    pct = int(extract_field(finfo, "exploration_pct", "exploration", "progress", default=0))
    gate = extract_field(finfo, "boss_gate_unlocked", "boss_unlocked", "can_challenge_boss", default=False)
    assert pct >= 100 or gate is True, (
        f"Floor {target_floor} exploration failed to unlock Boss Gate after {max_steps} steps: {finfo!r}"
    )
    return finfo


def trigger_chest_encounter(
    engine: Any,
    user_id: str,
    clock: FakeClock,
    *,
    seed_start: int = 100,
    max_attempts: int = 80,
) -> dict[str, Any]:
    """Explore deterministically until a treasure chest encounter is active."""
    if get_player_zone(engine, user_id, clock) == "town":
        engine.travel_zone(user_id, "field", now_ts=clock.now)
    for i in range(max_attempts):
        res = assert_ok_result(
            engine.explore_floor(user_id, steps=1, now_ts=clock.now, rng_seed=seed_start + i)
        )
        ev = str(extract_field(res, "event_type", "encounter_type", "type", "event", default="")).lower()
        if "chest" in ev or has_field(res, "chest", "chest_tier"):
            return res
        if (
            extract_field(res, "in_combat", default=False) is True
            or any(k in ev for k in ("combat", "mob", "monster", "battle", "elite", "field_boss"))
        ) and not _is_combat_finished(res):
            resolve_active_combat(engine, user_id, clock)
    raise AssertionError(f"No chest encounter occurred within {max_attempts} seeded explorations")


def trigger_road_combat(
    engine: Any,
    user_id: str,
    clock: FakeClock,
    *,
    seed_start: int = 200,
    max_attempts: int = 60,
) -> dict[str, Any]:
    """Explore deterministically until an active road-monster combat begins."""
    if get_player_zone(engine, user_id, clock) == "town":
        engine.travel_zone(user_id, "field", now_ts=clock.now)
    for i in range(max_attempts):
        res = assert_ok_result(
            engine.explore_floor(user_id, steps=1, now_ts=clock.now, rng_seed=seed_start + i)
        )
        ev = str(extract_field(res, "event_type", "encounter_type", "type", "event", default="")).lower()
        if "chest" in ev or has_field(res, "chest", "chest_tier"):
            engine.open_chest(user_id, action="leave", now_ts=clock.now)
            continue
        if (
            extract_field(res, "in_combat", default=False) is True
            or any(k in ev for k in ("combat", "mob", "monster", "battle", "elite"))
        ) and not _is_combat_finished(res):
            return res
    raise AssertionError(f"No road combat triggered within {max_attempts} seeded explorations")


def clear_floor_organically(
    engine: Any,
    user_id: str,
    clock: FakeClock,
    *,
    floor: int = 1,
    mode: str = "normal",
    heal_item_id: str | None = None,
) -> dict[str, Any]:
    """Explore to Boss Gate, enter Floor Boss, and defeat it via public APIs."""
    explore_to_boss_gate(engine, user_id, clock, floor=floor)
    assert_ok_result(engine.start_floor_boss(user_id, floor=floor, mode=mode, now_ts=clock.now))
    return resolve_active_combat(
        engine,
        user_id,
        clock,
        strategy="attack",
        heal_item_id=heal_item_id,
        max_turns=120,
    )


def prepare_player_for_floor(
    engine: Any,
    db: Any,
    content_bundle: Any,
    user_id: str,
    target_floor: int,
    *,
    clock: FakeClock,
    level: int | None = None,
    col: int = 50_000,
    unlock_boss_gate: bool = False,
    add_crystals: bool = True,
    mastery: int | None = None,
    power_boost: bool = True,
) -> dict[str, Any]:
    """Opaque-box high-floor Arrange helper using ONLY public DB/Engine APIs."""
    eff_level = level if level is not None else max(1, target_floor + 5)
    player = _call_public_db_method(db, ("get_player",), user_id)
    assert player is not None and player is not _MISSING, f"Player {user_id} not found in DB"

    # Update documented public PlayerProfile fields if present
    updates = {
        "level": eff_level,
        "col": max(int(getattr(player, "col", 0)), col),
        "gold": max(int(getattr(player, "gold", 0)), col),
        "max_unlocked_floor": max(int(getattr(player, "max_unlocked_floor", 1)), target_floor),
        "highest_floor": max(int(getattr(player, "highest_floor", 1)), target_floor),
        "unlocked_floor": max(int(getattr(player, "unlocked_floor", 1)), target_floor),
        "max_floor": max(int(getattr(player, "max_floor", 1)), target_floor),
        "stat_points": max(int(getattr(player, "stat_points", 0)), 5 + eff_level * 3),
        "unspent_stat_points": max(int(getattr(player, "unspent_stat_points", 0)), 5 + eff_level * 3),
        "talent_points": max(int(getattr(player, "talent_points", 0)), max(5, eff_level // 2)),
        "unspent_talent_points": max(int(getattr(player, "unspent_talent_points", 0)), max(5, eff_level // 2)),
    }
    for attr, val in updates.items():
        if hasattr(player, attr):
            setattr(player, attr, val)
    _call_public_db_method(db, ("save_player", "upsert_player", "update_player"), player)

    # Record tower floor unlocks through public DB methods if exposed
    for fl in range(1, target_floor + 1):
        _call_public_db_method(db, ("unlock_floor", "set_floor_unlocked"), user_id, fl)
    if target_floor >= 100:
        _call_public_db_method(db, ("mark_floor_cleared", "record_tower_clear"), user_id, 100)

    if mastery is not None:
        style = str(getattr(player, "weapon_style", "sword"))
        _call_public_db_method(
            db,
            ("set_mastery", "add_mastery", "upsert_mastery"),
            user_id,
            style,
            mastery,
        )

    if power_boost:
        tier = min(10, max(1, (target_floor - 1) // 10 + 1))
        scale = max(1, target_floor)
        w_uid = seed_equipment(
            db,
            user_id,
            slot="weapon",
            rarity="legendary",
            name=f"攻略組第{target_floor}層制式劍",
            template_id=f"e2e_f{target_floor}_weapon",
            weapon_style=str(getattr(player, "weapon_style", "sword")),
            tier=tier,
            enhance_level=min(15, tier + 2),
            atk=80 + scale * 35,
            defense=20 + scale * 10,
            hp=200 + scale * 60,
            sp=40 + scale * 4,
            now_ts=clock.now,
        )
        a_uid = seed_equipment(
            db,
            user_id,
            slot="armor",
            rarity="legendary",
            name=f"攻略組第{target_floor}層重鎧",
            template_id=f"e2e_f{target_floor}_armor",
            tier=tier,
            enhance_level=min(15, tier + 2),
            atk=20 + scale * 8,
            defense=60 + scale * 25,
            hp=400 + scale * 120,
            sp=30 + scale * 3,
            affixes={"res_slash": 0.25, "res_pierce": 0.25, "res_blunt": 0.25, "res_dragon": 0.25},
            now_ts=clock.now,
        )
        engine.equip_item(user_id, w_uid)
        engine.equip_item(user_id, a_uid)

    if add_crystals:
        crystals = pick_crystal_ids(content_bundle)
        for cid in crystals.values():
            seed_item(db, user_id, cid, 15)

    if target_floor >= 1:
        engine.teleport_floor(user_id, target_floor, now_ts=clock.now)
    if unlock_boss_gate:
        explore_to_boss_gate(engine, user_id, clock, floor=target_floor)
    return assert_ok_result(engine.get_profile(user_id, now_ts=clock.now))


def drive_coop_raid(
    engine: Any,
    clock: FakeClock,
    raid_id: str,
    member_ids: list[str],
    *,
    strategy_fn: Callable[[int, str, dict[str, Any]], tuple[str, str | None, str | None, int]] | None = None,
    max_rounds: int = 80,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Drive a synchronized multi-human co-op raid to completion via public APIs."""
    history: list[dict[str, Any]] = []
    last_state: dict[str, Any] = {}
    game_err = load_engine_api()["GameError"]
    for round_no in range(1, max_rounds + 1):
        round_resolved = False
        accepted_this_round = 0
        last_err: Exception | None = None
        for uid in member_ids:
            if strategy_fn is not None:
                action, skill_id, item_id, target_idx = strategy_fn(round_no, uid, last_state)
            else:
                action, skill_id, item_id, target_idx = ("attack", None, None, 0)
            try:
                res = assert_ok_result(
                    engine.submit_raid_action(
                        raid_id,
                        uid,
                        action,
                        skill_id=skill_id,
                        item_id=item_id,
                        target_idx=target_idx,
                        now_ts=clock.now,
                    )
                )
            except game_err as exc:
                last_err = exc
                continue
            accepted_this_round += 1
            last_state = res
            if extract_field(res, "round_resolved", "resolved", default=False) is True or _is_combat_finished(res):
                round_resolved = True
                history.append(res)
                if _is_combat_finished(res):
                    return res, history
                break
        if not round_resolved:
            assert accepted_this_round > 0, (
                f"Zero raid actions accepted in round {round_no}; last_err={last_err!r}"
            )
            res = assert_ok_result(
                engine.resolve_raid_round(
                    raid_id,
                    requester_id=member_ids[0],
                    force_timeout=True,
                    now_ts=clock.now,
                )
            )
            last_state = res
            history.append(res)
            if _is_combat_finished(res):
                return res, history
    raise AssertionError(f"Co-op raid {raid_id} did not finish within {max_rounds} rounds: {last_state!r}")


def induce_combat_defeat(
    engine: Any,
    db: Any,
    content_bundle: Any,
    user_id: str,
    clock: FakeClock,
    *,
    in_boss: bool = False,
    in_roguelike: bool = False,
    max_turns: int = 80,
) -> dict[str, Any]:
    """Organically drive a character to 0 HP through real combat."""
    # Disable auto-survival so player does not auto-heal/retreat
    engine.set_survival_config(
        user_id,
        auto_potion_pct=0,
        auto_crystal_pct=0,
        auto_retreat_pct=0,
        stop_on_no_potion=False,
    )
    if in_roguelike:
        if get_player_zone(engine, user_id, clock) != "town":
            engine.travel_zone(user_id, "town", now_ts=clock.now)
        engine.start_roguelike(user_id, now_ts=clock.now, rng_seed=911)
        for step in range(25):
            sres = assert_ok_result(engine.step_roguelike(user_id, node_index=0, now_ts=clock.now))
            if extract_field(sres, "in_combat", default=False) is True or "battle" in str(sres).lower():
                break
            if _is_combat_finished(sres):
                return sres
    elif in_boss:
        # Unlock F10 boss gate on an underleveled Lv.1 player or fight F1 boss unequipped
        prepare_player_for_floor(
            engine,
            db,
            content_bundle,
            user_id,
            10,
            clock=clock,
            level=1,
            power_boost=False,
            add_crystals=False,
            unlock_boss_gate=False,
        )
        _call_public_db_method(db, ("set_floor_exploration", "upsert_floor_exploration"), user_id, 10, 100)
        engine.start_floor_boss(user_id, floor=10, mode="normal", now_ts=clock.now)
    else:
        # Enter F10 field at Lv.1 unequipped so road monster defeats player cleanly
        prepare_player_for_floor(
            engine,
            db,
            content_bundle,
            user_id,
            10,
            clock=clock,
            level=1,
            power_boost=False,
            add_crystals=False,
        )
        trigger_road_combat(engine, user_id, clock, seed_start=700)

    last: dict[str, Any] = {}
    for _ in range(max_turns):
        last = assert_ok_result(engine.combat_action(user_id, "attack", now_ts=clock.now))
        if _is_combat_finished(last):
            return last
    raise AssertionError(f"Failed to reach defeat state for {user_id} in {max_turns} turns: {last!r}")


def run_concurrent_calls(
    callables: list[Callable[[], Any]],
) -> list[tuple[bool, Any]]:
    """Run callables concurrently with a threading.Barrier so threads genuinely collide."""
    n = len(callables)
    barrier = threading.Barrier(n)

    def _worker(fn: Callable[[], Any]) -> tuple[bool, Any]:
        barrier.wait(timeout=10)
        try:
            return True, fn()
        except Exception as exc:  # noqa: BLE001
            return False, exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(_worker, fn) for fn in callables]
        return [f.result(timeout=30) for f in futures]


# ---------------------------------------------------------------------------
# Authentic Legacy SCHEMA_VERSION=1 SQLite Fixture Builder
# ---------------------------------------------------------------------------


def _build_legacy_v1_db(path: Path) -> Path:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE rpg_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE players (
                user_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                class_id TEXT NOT NULL,
                promo_tier INTEGER NOT NULL DEFAULT 1,
                level INTEGER NOT NULL DEFAULT 1,
                exp INTEGER NOT NULL DEFAULT 0,
                rebirth_count INTEGER NOT NULL DEFAULT 0,
                gold INTEGER NOT NULL DEFAULT 250,
                gems INTEGER NOT NULL DEFAULT 50,
                stamina INTEGER NOT NULL DEFAULT 100,
                stamina_updated_at INTEGER NOT NULL,
                pickaxe_tier INTEGER NOT NULL DEFAULT 1,
                mine_combo INTEGER NOT NULL DEFAULT 0,
                last_mine_at INTEGER NOT NULL DEFAULT 0,
                last_boss_at INTEGER NOT NULL DEFAULT 0,
                abyss_floor INTEGER NOT NULL DEFAULT 1,
                abyss_highest INTEGER NOT NULL DEFAULT 0,
                active_title TEXT NOT NULL DEFAULT '',
                gacha_pity_legendary INTEGER NOT NULL DEFAULT 0,
                gacha_pity_mythic INTEGER NOT NULL DEFAULT 0,
                checkin_streak INTEGER NOT NULL DEFAULT 0,
                last_checkin_date TEXT NOT NULL DEFAULT '',
                total_checkins INTEGER NOT NULL DEFAULT 0,
                total_mines INTEGER NOT NULL DEFAULT 0,
                total_dungeons INTEGER NOT NULL DEFAULT 0,
                total_enhances INTEGER NOT NULL DEFAULT 0,
                total_boss_damage INTEGER NOT NULL DEFAULT 0,
                boss_kills_participated INTEGER NOT NULL DEFAULT 0,
                combat_power INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE equipment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                template_id TEXT NOT NULL,
                name TEXT NOT NULL,
                slot TEXT NOT NULL,
                rarity TEXT NOT NULL,
                tier INTEGER NOT NULL DEFAULT 1,
                set_id TEXT NOT NULL DEFAULT '',
                enhance_level INTEGER NOT NULL DEFAULT 0,
                enhance_pity INTEGER NOT NULL DEFAULT 0,
                base_hp INTEGER NOT NULL DEFAULT 0,
                base_mp INTEGER NOT NULL DEFAULT 0,
                base_atk INTEGER NOT NULL DEFAULT 0,
                base_def INTEGER NOT NULL DEFAULT 0,
                affixes_json TEXT NOT NULL DEFAULT '{}',
                is_equipped INTEGER NOT NULL DEFAULT 0,
                is_locked INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE inventory (
                user_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, item_id)
            );
            CREATE TABLE dungeon_clears (
                user_id TEXT NOT NULL,
                dungeon_id TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                clear_count INTEGER NOT NULL DEFAULT 0,
                first_cleared_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, dungeon_id, difficulty)
            );
            CREATE TABLE quests (
                user_id TEXT NOT NULL,
                period_type TEXT NOT NULL,
                period_key TEXT NOT NULL,
                quest_id TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                target INTEGER NOT NULL DEFAULT 1,
                claimed INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, period_type, period_key, quest_id)
            );
            CREATE TABLE achievements (
                user_id TEXT NOT NULL,
                achievement_id TEXT NOT NULL,
                unlocked_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, achievement_id)
            );
            CREATE TABLE expeditions (
                user_id TEXT PRIMARY KEY,
                expedition_id TEXT NOT NULL,
                started_at INTEGER NOT NULL,
                ends_at INTEGER NOT NULL,
                claimed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE shop_purchases (
                user_id TEXT NOT NULL,
                shop_bucket TEXT NOT NULL,
                offer_key TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, shop_bucket, offer_key)
            );
            CREATE TABLE world_boss (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tier INTEGER NOT NULL,
                boss_id TEXT NOT NULL,
                name TEXT NOT NULL,
                max_hp INTEGER NOT NULL,
                current_hp INTEGER NOT NULL,
                atk INTEGER NOT NULL,
                def_ INTEGER NOT NULL,
                status TEXT NOT NULL,
                spawned_at INTEGER NOT NULL,
                defeated_at INTEGER NOT NULL DEFAULT 0,
                killer_user_id TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE world_boss_damage (
                boss_instance_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                total_damage INTEGER NOT NULL DEFAULT 0,
                attacks_count INTEGER NOT NULL DEFAULT 0,
                last_attack_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (boss_instance_id, user_id)
            );
            """
        )
        conn.executemany(
            "INSERT INTO rpg_meta(key, value) VALUES (?, ?)",
            [
                ("schema_version", "1"),
                ("save_seq", str(LEGACY_V1_MANIFEST["save_seq"])),
                ("updated_at", str(LEGACY_V1_MANIFEST["updated_at"])),
            ],
        )
        for p in LEGACY_V1_MANIFEST["players"]:
            conn.execute(
                """
                INSERT INTO players(
                    user_id, display_name, class_id, level, exp, rebirth_count,
                    gold, gems, stamina, stamina_updated_at, abyss_highest,
                    combat_power, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 100, ?, ?, ?, ?, ?)
                """,
                (
                    p["user_id"],
                    p["display_name"],
                    p["class_id"],
                    p["level"],
                    p["exp"],
                    p["rebirth_count"],
                    p["gold"],
                    p["gems"],
                    LEGACY_V1_MANIFEST["updated_at"],
                    p["abyss_highest"],
                    p["combat_power"],
                    LEGACY_V1_MANIFEST["updated_at"],
                    LEGACY_V1_MANIFEST["updated_at"],
                ),
            )
        conn.execute(
            """
            INSERT INTO equipment(
                user_id, template_id, name, slot, rarity, tier, enhance_level,
                base_atk, base_def, is_equipped, is_locked, created_at
            ) VALUES ('800001', 'legacy_blade', '舊紀元鐵劍', 'weapon', 'rare', 2, 5, 120, 15, 1, 1, ?)
            """,
            (LEGACY_V1_MANIFEST["updated_at"],),
        )
        conn.execute(
            """
            INSERT INTO equipment(
                user_id, template_id, name, slot, rarity, tier, enhance_level,
                base_hp, base_def, is_equipped, is_locked, created_at
            ) VALUES ('800002', 'legacy_mail', '舊紀元鎖子甲', 'armor', 'fine', 3, 3, 240, 80, 1, 0, ?)
            """,
            (LEGACY_V1_MANIFEST["updated_at"],),
        )
        for uid, inv in LEGACY_V1_MANIFEST["inventory"].items():
            for iid, qty in inv.items():
                conn.execute(
                    "INSERT INTO inventory(user_id, item_id, quantity) VALUES (?, ?, ?)",
                    (uid, iid, qty),
                )
        conn.execute(
            """
            INSERT INTO expeditions(user_id, expedition_id, started_at, ends_at, claimed)
            VALUES ('800001', 'legacy_patrol', 1759995000, ?, 0)
            """,
            (LEGACY_V1_MANIFEST["expedition_ends_at"],),
        )
        conn.execute(
            "INSERT INTO achievements(user_id, achievement_id, unlocked_at) VALUES ('800001', 'legacy_first', 1759995000)"
        )
        conn.commit()
    finally:
        conn.close()
    return path


# ---------------------------------------------------------------------------
# E2E Helper Namespace Exposed via Fixture (Zero `from conftest import ...`)
# ---------------------------------------------------------------------------


class E2EHelpers:
    """Centralized fixture-exposed helper namespace for Tier 1–4 test modules."""

    FakeClock = FakeClock
    PartySetup = PartySetup
    FakeDiscordUser = FakeDiscordUser
    FakeDiscordChannel = FakeDiscordChannel
    FakeDiscordMessage = FakeDiscordMessage
    FakeDiscordInteraction = FakeDiscordInteraction

    BASE_8_WEAPON_STYLES = BASE_8_WEAPON_STYLES
    UNIQUE_2_SKILLS = UNIQUE_2_SKILLS
    FOUR_DAMAGE_TYPES = FOUR_DAMAGE_TYPES
    EIGHT_EQUIPMENT_SLOTS = EIGHT_EQUIPMENT_SLOTS
    SIX_RARITIES = SIX_RARITIES
    SIX_ZONES = SIX_ZONES
    THREE_CURSORS = THREE_CURSORS
    TWO_GAME_MODES = TWO_GAME_MODES
    FOUR_BOSS_MODES = FOUR_BOSS_MODES
    SEVEN_LEADERBOARD_CATEGORIES = SEVEN_LEADERBOARD_CATEGORIES
    MILESTONE_14_FLOORS = MILESTONE_14_FLOORS
    EXPECTED_22_SAO_COMMANDS = EXPECTED_22_SAO_COMMANDS
    EXPECTED_23_COMMANDS = EXPECTED_23_COMMANDS
    SECRET_LEAK_REGEXES = SECRET_LEAK_REGEXES
    LEGACY_V1_MANIFEST = LEGACY_V1_MANIFEST

    load_content_api = staticmethod(load_content_api)
    load_models_api = staticmethod(load_models_api)
    load_db_api = staticmethod(load_db_api)
    load_stats_api = staticmethod(load_stats_api)
    load_engine_api = staticmethod(load_engine_api)
    load_bot_api = staticmethod(load_bot_api)
    instantiate_engine = staticmethod(instantiate_engine)

    as_mapping = staticmethod(as_mapping)
    extract_text_blob = staticmethod(extract_text_blob)
    has_zh_tw = staticmethod(has_zh_tw)
    assert_ok_result = staticmethod(assert_ok_result)
    unwrap_payload = staticmethod(unwrap_payload)
    extract_field = staticmethod(extract_field)
    has_field = staticmethod(has_field)
    assert_game_error = staticmethod(assert_game_error)
    assert_no_secrets = staticmethod(assert_no_secrets)
    assert_discord_payload_valid = staticmethod(assert_discord_payload_valid)

    iter_entries = staticmethod(iter_entries)
    pick_sword_skills = staticmethod(pick_sword_skills)
    pick_item_id = staticmethod(pick_item_id)
    pick_crystal_ids = staticmethod(pick_crystal_ids)
    pick_magic_stone_id = staticmethod(pick_magic_stone_id)
    pick_enhance_materials = staticmethod(pick_enhance_materials)
    pick_recipe = staticmethod(pick_recipe)
    pick_story_choice = staticmethod(pick_story_choice)
    pick_expedition = staticmethod(pick_expedition)
    pick_talent_pair = staticmethod(pick_talent_pair)
    pick_set_and_named_templates = staticmethod(pick_set_and_named_templates)
    pick_achievement_and_title = staticmethod(pick_achievement_and_title)
    pick_boss_spec = staticmethod(pick_boss_spec)

    get_db_save_seq = staticmethod(get_db_save_seq)
    export_db_snapshot_bytes = staticmethod(export_db_snapshot_bytes)
    import_db_snapshot_bytes = staticmethod(import_db_snapshot_bytes)

    get_player_col = staticmethod(get_player_col)
    get_player_floor = staticmethod(get_player_floor)
    get_player_zone = staticmethod(get_player_zone)
    get_player_cursor = staticmethod(get_player_cursor)
    get_player_miasma = staticmethod(get_player_miasma)
    get_player_item_qty = staticmethod(get_player_item_qty)
    get_player_equipment = staticmethod(get_player_equipment)
    get_player_pending_loot_count = staticmethod(get_player_pending_loot_count)
    get_player_life_skills = staticmethod(get_player_life_skills)

    seed_col = staticmethod(seed_col)
    seed_item = staticmethod(seed_item)
    seed_equipment = staticmethod(seed_equipment)
    give_recipe_materials = staticmethod(give_recipe_materials)

    resolve_active_combat = staticmethod(resolve_active_combat)
    explore_to_boss_gate = staticmethod(explore_to_boss_gate)
    trigger_chest_encounter = staticmethod(trigger_chest_encounter)
    trigger_road_combat = staticmethod(trigger_road_combat)
    clear_floor_organically = staticmethod(clear_floor_organically)
    prepare_player_for_floor = staticmethod(prepare_player_for_floor)
    drive_coop_raid = staticmethod(drive_coop_raid)
    induce_combat_defeat = staticmethod(induce_combat_defeat)
    run_concurrent_calls = staticmethod(run_concurrent_calls)

    @staticmethod
    def run_async(coro: Any) -> Any:
        return asyncio.run(coro)

    @staticmethod
    def gzip_bytes(raw: bytes) -> bytes:
        return gzip.compress(raw)


# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def e2e() -> E2EHelpers:
    return E2EHelpers()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def content_bundle() -> Any:
    bundle = load_content_api()["load_and_validate_all"]()
    for attr in (
        "biomes",
        "floors_override",
        "bosses",
        "monsters",
        "chests_loot",
        "weapons_equipment",
        "sword_skills",
        "items_crystals",
        "recipes",
        "quests_events",
    ):
        val = getattr(bundle, attr, None)
        assert val, f"SAOContentBundle.{attr} must be non-empty"
    return bundle


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "aincrad_e2e.db"


@pytest.fixture
def db(db_path: Path) -> Any:
    db_cls = load_db_api()["RPGDatabase"]
    instance = db_cls(db_path)
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture
def engine(db: Any, content_bundle: Any) -> Any:
    return instantiate_engine(db, content_bundle)


@pytest.fixture
def next_user_id() -> Callable[[], str]:
    counter = [900_000]

    def _next() -> str:
        counter[0] += 1
        return str(counter[0])

    return _next


@pytest.fixture
def make_player(
    engine: Any,
    clock: FakeClock,
    next_user_id: Callable[[], str],
) -> Callable[..., str]:
    def _create(
        name: str | None = None,
        *,
        user_id: str | None = None,
        weapon_style: str = "sword",
        mode: str = "standard",
        now_ts: int | None = None,
    ) -> str:
        uid = str(user_id or next_user_id())
        display = name if name is not None else f"攻略者{uid[-3:]}"
        res = engine.create_character(
            uid,
            display,
            weapon_style=weapon_style,
            mode=mode,
            now_ts=clock.now if now_ts is None else now_ts,
        )
        assert_ok_result(res)
        return uid

    return _create


@pytest.fixture
def make_party_humans(
    engine: Any,
    db: Any,
    content_bundle: Any,
    clock: FakeClock,
    make_player: Callable[..., str],
) -> Callable[..., PartySetup]:
    default_styles = ("mace", "sword", "rapier", "axe", "katana", "holy", "scythe", "dagger")
    default_roles = ("tank", "dps", "breaker", "support")

    def _build(
        count: int = 4,
        *,
        floor: int = 1,
        boss_mode: str = "normal",
        max_size: int | None = None,
        is_raid_alliance: bool = False,
        roles: list[str] | None = None,
        ready_all: bool = True,
        weapon_styles: list[str] | None = None,
        prepare_floor: bool = False,
        unlock_boss_gate: bool = False,
    ) -> PartySetup:
        member_ids: list[str] = []
        role_map: dict[str, str] = {}
        for i in range(count):
            style = (
                weapon_styles[i]
                if weapon_styles and i < len(weapon_styles)
                else default_styles[i % len(default_styles)]
            )
            uid = make_player(f"隊員{i + 1}", weapon_style=style)
            if prepare_floor or floor > 1:
                prepare_player_for_floor(
                    engine,
                    db,
                    content_bundle,
                    uid,
                    floor,
                    clock=clock,
                    unlock_boss_gate=unlock_boss_gate and (i == 0),
                )
            elif unlock_boss_gate and i == 0:
                explore_to_boss_gate(engine, uid, clock, floor=floor)
            member_ids.append(uid)
            role_map[uid] = (
                roles[i]
                if roles and i < len(roles)
                else default_roles[i % len(default_roles)]
            )

        leader_id = member_ids[0]
        cap = max_size if max_size is not None else (24 if is_raid_alliance else max(6, count))
        create_res = assert_ok_result(
            engine.create_party(
                leader_id,
                floor=floor,
                boss_mode=boss_mode,
                max_size=cap,
                is_raid_alliance=is_raid_alliance,
                now_ts=clock.now,
            )
        )
        party_id = str(extract_field(create_res, "party_id", "id"))
        engine.set_party_role(party_id, leader_id, role_map[leader_id])
        for uid in member_ids[1:]:
            assert_ok_result(
                engine.join_party(party_id, uid, role=role_map[uid], now_ts=clock.now)
            )
            engine.set_party_role(party_id, uid, role_map[uid])
        if ready_all:
            for uid in member_ids:
                assert_ok_result(engine.set_party_ready(party_id, uid, True))

        return PartySetup(
            party_id=party_id,
            leader_id=leader_id,
            member_ids=member_ids,
            roles=role_map,
            floor=floor,
            boss_mode=boss_mode,
            create_result=create_res,
        )

    return _build


@pytest.fixture
def v1_legacy_db_path(tmp_path: Path) -> Path:
    return _build_legacy_v1_db(tmp_path / "legacy_v1.db")


@pytest.fixture
def fake_discord() -> dict[str, Any]:
    channel = FakeDiscordChannel()

    def _make_user(uid: int = 500001, name: str = "桐人") -> FakeDiscordUser:
        return FakeDiscordUser(id=uid, display_name=name, name=name)

    def _make_interaction(
        user: FakeDiscordUser | None = None,
        *,
        ch: FakeDiscordChannel | None = None,
        client: Any = None,
    ) -> FakeDiscordInteraction:
        return FakeDiscordInteraction(
            user=user or _make_user(),
            channel=ch or channel,
            client=client,
        )

    return {
        "channel": channel,
        "make_user": _make_user,
        "make_interaction": _make_interaction,
        "assert_valid": assert_discord_payload_valid,
    }


@pytest.fixture(name="assert_game_error")
def assert_game_error_fixture() -> Callable[..., Exception]:
    return assert_game_error


@pytest.fixture(name="assert_ok_result")
def assert_ok_result_fixture() -> Callable[..., dict[str, Any]]:
    return assert_ok_result


@pytest.fixture(name="assert_discord_payload_valid")
def assert_discord_payload_valid_fixture() -> Callable[..., None]:
    return assert_discord_payload_valid
