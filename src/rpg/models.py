"""Core typed domain models, StrEnums, and GameError for SAO Aincrad 100-Floor RPG."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class GameError(ValueError):
    """Domain rule rejection with zh-TW user message and machine-readable code."""

    def __init__(self, message: str, code: str = "GAME_ERROR") -> None:
        super().__init__(message)
        self.message: str = message
        self.code: str = code


# =============================================================================
# SAO Aincrad Controlled Vocabularies (Python 3.11+ StrEnum)
# =============================================================================
class WeaponStyle(StrEnum):
    SWORD = "sword"
    RAPIER = "rapier"
    KATANA = "katana"
    AXE = "axe"
    MACE = "mace"
    HOLY = "holy"
    SCYTHE = "scythe"
    DAGGER = "dagger"
    DUAL_BLADES = "dual_blades"
    HOLY_SWORD = "holy_sword"


BASE_WEAPON_STYLES: tuple[str, ...] = (
    "sword",
    "rapier",
    "katana",
    "axe",
    "mace",
    "holy",
    "scythe",
    "dagger",
)
UNIQUE_WEAPON_STYLES: tuple[str, ...] = ("dual_blades", "holy_sword")
LEGACY_CLASS_TO_WEAPON_STYLE: dict[str, str] = {
    "swordsman": "sword",
    "ranger": "rapier",
    "paladin": "holy",
    "mage": "scythe",
}


class DamageType(StrEnum):
    SLASH = "slash"
    PIERCE = "pierce"
    BLUNT = "blunt"
    DRAGON = "dragon"


class EquipmentSlot(StrEnum):
    WEAPON = "weapon"
    OFFHAND = "offhand"
    HELMET = "helmet"
    ARMOR = "armor"
    GLOVES = "gloves"
    BOOTS = "boots"
    RING = "ring"
    NECKLACE = "necklace"


SAO_SLOT_ORDER: tuple[str, ...] = (
    "weapon",
    "offhand",
    "helmet",
    "armor",
    "gloves",
    "boots",
    "ring",
    "necklace",
)


class Rarity(StrEnum):
    PLAIN = "plain"
    FINE = "fine"
    RARE = "rare"
    SET = "set"
    LEGENDARY = "legendary"
    NAMED = "named"


SAO_RARITY_ORDER: tuple[str, ...] = ("plain", "fine", "rare", "set", "legendary", "named")
LEGACY_TO_SAO_RARITY: dict[str, str] = {
    "common": "plain",
    "uncommon": "fine",
    "rare": "rare",
    "epic": "set",
    "legendary": "legendary",
    "mythic": "named",
}


class ZoneType(StrEnum):
    TOWN = "town"
    FIELD = "field"
    LABYRINTH = "labyrinth"
    SECRET_REALM = "secret_realm"
    BOSS_ROOM = "boss_room"
    ROGUELIKE = "roguelike"


class CursorColor(StrEnum):
    GREEN = "green"
    ORANGE = "orange"
    RED = "red"


class GameMode(StrEnum):
    STANDARD = "standard"
    HARDCORE = "hardcore"


class BossMode(StrEnum):
    FIRST_KILL = "first_kill"
    NORMAL = "normal"
    TEAM_BOSS = "team_boss"
    WORLD_BOSS = "world_boss"


def _clamp_res(val: float) -> float:
    safe = float(val) if math.isfinite(val) else 0.0
    return min(0.75, max(0.0, safe))


# =============================================================================
# 16 Core Dataclasses (100% Legacy Field Order & Default Compatibility Preserved)
# =============================================================================
@dataclass
class ComputedStats:
    """Total computed combat & utility stats for a player (Legacy + SAO 4-Axis)."""

    # Legacy 16 fields (exact order preserved for existing engine.py & embeds.py)
    max_hp: int = 100
    max_mp: int = 50
    atk: int = 10
    def_: int = 5
    crit_rate: float = 0.05
    crit_dmg: float = 1.5
    dodge: float = 0.01
    lifesteal: float = 0.0
    gold_bonus: float = 0.0
    exp_bonus: float = 0.0
    drop_bonus: float = 0.0
    mine_bonus: float = 0.0
    skill_dmg_bonus: float = 0.0
    dmg_reduction: float = 0.0
    combat_power: int = 0
    active_sets: list[str] = field(default_factory=list)
    # Unified SAO fields
    max_sp: int = 0
    defense: int = 0
    spd: int = 100
    evasion: float = 0.0
    res_slash: float = 0.0
    res_pierce: float = 0.0
    res_blunt: float = 0.0
    res_dragon: float = 0.0
    col_bonus: float = 0.0
    healing_bonus: float = 0.0
    armor_pen: float = 0.0
    break_bonus: float = 0.0
    aggro_mult: float = 1.0
    potion_bonus: float = 0.0
    battle_regen_pct: float = 0.0
    active_passives: dict[str, Any] = field(default_factory=dict)
    set_bonuses: dict[str, float] = field(default_factory=dict)
    floor: int = 1

    def __post_init__(self) -> None:
        if self.defense == 0 and self.def_ > 0:
            self.defense = self.def_
        elif self.def_ == 0 and self.defense > 0:
            self.def_ = self.defense

        if self.max_sp == 0 and self.max_mp > 0:
            self.max_sp = self.max_mp
        elif self.max_mp == 0 and self.max_sp > 0:
            self.max_mp = self.max_sp

        if self.evasion == 0.0 and self.dodge > 0.0:
            self.evasion = self.dodge
        elif self.dodge == 0.0 and self.evasion > 0.0:
            self.dodge = self.evasion

        if self.col_bonus == 0.0 and self.gold_bonus != 0.0:
            self.col_bonus = self.gold_bonus
        elif self.gold_bonus == 0.0 and self.col_bonus != 0.0:
            self.gold_bonus = self.col_bonus

        self.res_slash = _clamp_res(self.res_slash)
        self.res_pierce = _clamp_res(self.res_pierce)
        self.res_blunt = _clamp_res(self.res_blunt)
        self.res_dragon = _clamp_res(self.res_dragon)

    @property
    def def_pen(self) -> float:
        return self.armor_pen

    @property
    def weapon_passives(self) -> dict[str, Any]:
        return self.active_passives

    def effective_res(self, dmg_type: str, floor: int | None = None) -> float:
        """Compute effective resistance after 75% hard cap and floor penetration (up to 65%)."""
        key = str(dmg_type).strip().lower()
        axis_map = {
            "slash": self.res_slash,
            "pierce": self.res_pierce,
            "blunt": self.res_blunt,
            "dragon": self.res_dragon,
        }
        if key not in axis_map:
            raise GameError(f"無效的傷害類型：{dmg_type}", code="INVALID_DAMAGE_TYPE")
        target_floor = self.floor if floor is None else floor
        pen = min(0.65, max(0, int(target_floor)) * 0.0065)
        capped = _clamp_res(axis_map[key])
        return max(0.0, round(capped * (1.0 - pen), 6))


@dataclass
class EquipmentItem:
    """An individual owned equipment piece persisted in SQLite."""

    # Legacy 18 fields (exact order preserved)
    id: int
    user_id: str
    template_id: str
    name: str
    slot: str
    rarity: str
    tier: int
    set_id: str
    enhance_level: int
    enhance_pity: int
    base_hp: int
    base_mp: int
    base_atk: int
    base_def: int
    affixes: dict[str, float]
    is_equipped: bool = False
    is_locked: bool = False
    created_at: int = 0
    # SAO extension fields (8)
    weapon_style: str = ""
    damage_type: str = ""
    named_passive: str = ""
    is_bound: bool = False
    min_level: int = 1
    escrow_state: str = ""  # "" | "market" | "guild_warehouse"
    base_sp: int = 0
    base_spd: int = 0

    def enhance_multiplier(self) -> float:
        # +10% per level, plus bonus milestones at +5 (+10%), +10 (+20%), +15 (+35%)
        mult = 1.0 + 0.10 * self.enhance_level
        if self.enhance_level >= 5:
            mult += 0.10
        if self.enhance_level >= 10:
            mult += 0.20
        if self.enhance_level >= 15:
            mult += 0.35
        return mult

    @property
    def uid(self) -> int:
        return self.id

    @property
    def hp(self) -> int:
        return round(self.base_hp * self.enhance_multiplier())

    @property
    def mp(self) -> int:
        return round(self.base_mp * self.enhance_multiplier())

    @property
    def sp(self) -> int:
        return round((self.base_sp or self.base_mp) * self.enhance_multiplier())

    @property
    def atk(self) -> int:
        return round(self.base_atk * self.enhance_multiplier())

    @property
    def def_(self) -> int:
        return round(self.base_def * self.enhance_multiplier())

    @property
    def defense(self) -> int:
        return self.def_

    @property
    def spd(self) -> int:
        return self.base_spd

    @property
    def is_named(self) -> bool:
        return self.rarity == Rarity.NAMED or bool(self.named_passive)

    @property
    def is_set_piece(self) -> bool:
        return self.rarity == Rarity.SET or bool(self.set_id)

    @property
    def power_score(self) -> int:
        affix_score = 0.0
        for key, val in self.affixes.items():
            if key in ("atk_pct", "def_pct", "hp_pct"):
                affix_score += val * 800
            elif key in ("crit_rate", "dodge", "evasion", "lifesteal"):
                affix_score += val * 1200
            elif key in ("res_slash", "res_pierce", "res_blunt", "res_dragon"):
                affix_score += val * 900
            elif key == "crit_dmg":
                affix_score += val * 450
            else:
                affix_score += val * 300
        return int(
            self.atk * 5
            + self.def_ * 4
            + self.hp * 0.6
            + self.sp * 1.2
            + self.spd * 2.0
            + affix_score
        )


def _default_survival_config() -> dict[str, Any]:
    return {
        "auto_potion_pct": 0.40,
        "auto_crystal_pct": 0.20,
        "auto_retreat_pct": 0.15,
        "stop_on_no_potion": True,
    }


def _default_loot_filter() -> dict[str, Any]:
    return {
        "min_rarity": "plain",
        "min_level": 1,
        "blocked_slots": [],
    }


@dataclass
class PlayerProfile:
    """Core persistent RPG player record (Legacy 31 + SAO 37 fields)."""

    # Legacy 31 fields (exact order preserved)
    user_id: str
    display_name: str = ""
    class_id: str = "swordsman"
    promo_tier: int = 1
    level: int = 1
    exp: int = 0
    rebirth_count: int = 0
    gold: int = 350
    gems: int = 50
    stamina: int = 100
    stamina_updated_at: int = 0
    pickaxe_tier: int = 1
    mine_combo: int = 0
    last_mine_at: int = 0
    last_boss_at: int = 0
    abyss_floor: int = 1
    abyss_highest: int = 0
    active_title: str = ""
    gacha_pity_legendary: int = 0
    gacha_pity_mythic: int = 0
    checkin_streak: int = 0
    last_checkin_date: str = ""
    total_checkins: int = 0
    total_mines: int = 0
    total_dungeons: int = 0
    total_enhances: int = 0
    total_boss_damage: int = 0
    boss_kills_participated: int = 0
    combat_power: int = 0
    created_at: int = 0
    updated_at: int = 0
    # SAO fields (37)
    current_floor: int = 1
    highest_cleared_floor: int = 0
    zone: str = ZoneType.TOWN
    weapon_style: str = WeaponStyle.SWORD
    game_mode: str = GameMode.STANDARD
    cursor_color: str = CursorColor.GREEN
    karma: int = 0
    hp: int = 0
    sp: int = 100
    max_sp: int = 100
    miasma_stacks: int = 0
    miasma_exp_stacks: int = 0
    survival_config: dict[str, Any] = field(default_factory=_default_survival_config)
    loot_filter: dict[str, Any] = field(default_factory=_default_loot_filter)
    skill_slots: list[str] = field(default_factory=list)
    unique_skills: list[str] = field(default_factory=list)
    stat_points: int = 0
    talent_points: int = 0
    str_stat: int = 5
    agi_stat: int = 5
    vit_stat: int = 5
    dex_stat: int = 5
    luk_stat: int = 5
    downed_until: int = 0
    is_dead: bool = False
    survival_streak: int = 0
    last_death_log: str = ""
    guild_id: int | None = None
    guild_left_at: int = 0
    active_buffs: dict[str, Any] = field(default_factory=dict)
    world_boss_attempts: int = 3
    world_boss_attempts_date: str = ""
    story_choices: dict[str, str] = field(default_factory=dict)
    nightmare_highest: int = 0
    boss_rush_best: int = 0
    roguelike_best_score: int = 0
    in_boss_battle: bool = False

    @property
    def col(self) -> int:
        return self.gold

    @col.setter
    def col(self, value: int) -> None:
        self.gold = int(value)

    @property
    def equipped_title(self) -> str:
        return self.active_title

    @equipped_title.setter
    def equipped_title(self, value: str) -> None:
        self.active_title = value

    @property
    def max_unlocked_floor(self) -> int:
        return min(100, max(1, int(self.highest_cleared_floor) + 1))

    @max_unlocked_floor.setter
    def max_unlocked_floor(self, value: int) -> None:
        target = max(1, min(100, int(value)))
        self.highest_cleared_floor = max(self.highest_cleared_floor, target - 1)



@dataclass
class FloorDefinition:
    """Resolved deterministic blueprint for an Aincrad floor (F1..F100)."""

    floor: int
    tier: int
    biome_id: str
    biome_name: str
    town_name: str
    field_name: str
    labyrinth_name: str
    secret_realm_name: str = ""
    recommended_level: int = 1
    res_penetration: float = 0.0
    is_milestone: bool = False
    is_crystal_null: bool = False
    boss_id: str = ""
    field_boss_id: str = ""
    mob_pool: list[str] = field(default_factory=list)
    elite_pool: list[str] = field(default_factory=list)
    chest_table_id: str = ""
    ore_pool: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    lore_note: str = ""
    yui_log_id: str | None = None
    scaling_mult: float = 1.0


@dataclass
class BossCombatState:
    """Multi-bar, multi-phase state machine payload for solo or co-op SAO Boss encounters."""

    boss_id: str
    name: str
    floor: int
    mode: str = BossMode.NORMAL
    max_hp: int = 1000
    current_hp: int = 1000
    hp_bars: int = 3
    atk: int = 50
    defense: int = 20
    spd: int = 90
    damage_type: str = DamageType.SLASH
    weaknesses: list[str] = field(default_factory=list)
    resistances: dict[str, float] = field(default_factory=dict)
    current_phase: int = 1
    triggered_phases: list[int] = field(default_factory=list)
    phases: list[dict[str, Any]] = field(default_factory=list)
    stagger_max: int = 100
    stagger_current: int = 0
    is_broken: bool = False
    break_turns_left: int = 0
    telegraph_active: bool = False
    telegraph_skill_id: str = ""
    telegraph_skill_name: str = ""
    telegraph_damage_type: str = DamageType.SLASH
    telegraph_requires_switch: bool = False
    telegraph_requires_parry: bool = False
    telegraph_callout: str = ""
    debuffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    stun_immune_turns: int = 0
    adds: list[dict[str, Any]] = field(default_factory=list)
    shield_hp: int = 0
    anti_crystal_zone: bool = False
    enrage_turn: int = 25
    enraged: bool = False
    turn: int = 1
    observed_skills: list[str] = field(default_factory=list)
    la_bonus_item_id: str = ""
    last_attacker_id: str | None = None

    @property
    def hp_pct(self) -> float:
        if self.max_hp <= 0:
            return 0.0
        return max(0.0, min(100.0, (self.current_hp / self.max_hp) * 100.0))

    @property
    def current_bar(self) -> int:
        if self.current_hp <= 0 or self.max_hp <= 0:
            return 0
        bars = max(1, int(self.hp_bars))
        bar_size = self.max_hp / bars
        return min(bars, max(1, math.ceil(self.current_hp / bar_size)))

    @property
    def current_bar_color(self) -> str:
        pct = self.hp_pct
        if pct > 50.0:
            return "green"
        if pct > 20.0:
            return "yellow"
        return "red"


@dataclass
class CombatSession:
    """In-memory state for an active turn-based battle (Legacy dungeon/abyss + SAO solo combat)."""

    # Legacy 31 fields (exact order preserved)
    user_id: str
    mode: str  # "dungeon" | "abyss" | "field" | "labyrinth" | "boss" | "secret_realm"
    target_id: str
    difficulty: str
    title: str
    enemy_name: str
    enemy_emoji: str
    enemy_max_hp: int
    enemy_hp: int
    enemy_atk: int
    enemy_def: int
    enemy_level: int
    enemy_telegraph: bool = False
    enemy_telegraph_name: str = ""
    enemy_burn_turns: int = 0
    enemy_burn_dmg: int = 0
    enemy_shred_turns: int = 0
    player_max_hp: int = 100
    player_hp: int = 100
    player_max_mp: int = 50
    player_mp: int = 50
    player_shield: int = 0
    player_dodge_buff_turns: int = 0
    ult_cooldown: int = 0
    turn: int = 1
    stamina_spent: int = 0
    finished: bool = False
    victory: bool = False
    retreated: bool = False
    logs: list[str] = field(default_factory=list)
    rewards_summary: dict[str, Any] | None = None
    # SAO extension fields (18)
    floor: int = 1
    zone: str = ZoneType.FIELD
    weapon_style: str = WeaponStyle.SWORD
    damage_type: str = DamageType.SLASH
    enemy_damage_type: str = DamageType.SLASH
    enemy_weaknesses: list[str] = field(default_factory=list)
    player_sp: int = 100
    player_max_sp: int = 100
    player_debuffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    enemy_debuffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    skill_cooldowns: dict[str, int] = field(default_factory=dict)
    combo_count: int = 0
    is_sheathed: bool = False
    rigidity_turns: int = 0
    parry_active: bool = False
    anti_crystal_zone: bool = False
    boss_state: BossCombatState | None = None
    extra_enemies: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PartyMemberState:
    """Real-human member combat & lobby state inside a Party or Co-op Raid."""

    user_id: str
    display_name: str
    role: str = "dps"
    weapon_style: str = WeaponStyle.SWORD
    level: int = 1
    combat_power: int = 0
    is_ready: bool = False
    potion_sharing: bool = False
    frontline_stance: bool = False
    max_hp: int = 100
    hp: int = 100
    max_sp: int = 100
    sp: int = 100
    shield: int = 0
    aggro: float = 0.0
    damage_dealt: int = 0
    damage_taken: int = 0
    healing_done: int = 0
    switch_cd: int = 0
    skill_cooldowns: dict[str, int] = field(default_factory=dict)
    debuffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    is_downed: bool = False
    is_retreated: bool = False
    is_sleeping: bool = False
    consecutive_timeouts: int = 0
    joined_at: int = 0


@dataclass
class PartyLobby:
    """Persistent + in-memory multiplayer party lobby or Raid Alliance."""

    party_id: str
    leader_id: str
    floor: int
    boss_mode: str = BossMode.NORMAL
    max_size: int = 6
    is_raid_alliance: bool = False
    status: str = "lobby"  # "lobby" | "in_boss_room" | "in_combat" | "disbanded"
    members: dict[str, PartyMemberState] = field(default_factory=dict)
    channel_id: int | None = None
    message_id: int | None = None
    created_at: int = 0
    updated_at: int = 0


@dataclass
class CoopRaidSession:
    """Synchronized turn-based multi-human co-op Boss raid session."""

    raid_id: str
    party_id: str
    leader_id: str
    floor: int
    boss_mode: str = BossMode.NORMAL
    boss: BossCombatState = field(
        default_factory=lambda: BossCombatState(boss_id="", name="", floor=1)
    )
    members: dict[str, PartyMemberState] = field(default_factory=dict)
    turn: int = 1
    turn_started_at: int = 0
    turn_timeout_sec: int = 25
    pending_actions: dict[str, dict[str, Any]] = field(default_factory=dict)
    vanguard_user_id: str | None = None
    switch_chain: int = 0
    last_switch_user_id: str | None = None
    finished: bool = False
    victory: bool = False
    is_first_kill: bool = False
    la_user_id: str | None = None
    logs: list[str] = field(default_factory=list)
    rewards_by_user: dict[str, dict[str, Any]] = field(default_factory=dict)
    channel_id: int | None = None
    message_id: int | None = None
    started_at: int = 0


@dataclass
class RoguelikeRun:
    """Black Iron Palace Underground Roguelike run state."""

    run_id: str
    user_id: str
    depth: int = 1
    score: int = 0
    hp: int = 100
    max_hp: int = 100
    sp: int = 100
    max_sp: int = 100
    tokens: int = 0
    col_earned: int = 0
    buffs: list[dict[str, Any]] = field(default_factory=list)
    pending_nodes: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    finished: bool = False
    extracted: bool = False
    started_at: int = 0


@dataclass
class ActiveExpedition:
    user_id: str
    expedition_id: str
    started_at: int
    ends_at: int
    claimed: bool = False


@dataclass
class WorldBossState:
    id: int
    tier: int
    boss_id: str
    name: str
    max_hp: int
    current_hp: int
    atk: int
    def_: int
    status: str
    spawned_at: int
    defeated_at: int | None = None
    killer_user_id: str | None = None
    floor: int = 1
    accelerated_buff_hours: int = 2


@dataclass
class DuelSession:
    """Consent-gated real-human PvP Duel session (First-Strike or Full Duel)."""

    duel_id: str
    challenger_id: str
    challenger_name: str
    target_id: str
    target_name: str
    mode: str = "first_strike"  # "first_strike" | "full_duel"
    wager_col: int = 0
    zone: str = ZoneType.TOWN
    status: str = "pending"  # "pending" | "active" | "finished" | "declined"
    challenger_hp: int = 100
    challenger_max_hp: int = 100
    challenger_sp: int = 100
    challenger_max_sp: int = 100
    target_hp: int = 100
    target_max_hp: int = 100
    target_sp: int = 100
    target_max_sp: int = 100
    pending_actions: dict[str, dict[str, Any]] = field(default_factory=dict)
    turn: int = 1
    winner_id: str | None = None
    logs: list[str] = field(default_factory=list)
    created_at: int = 0
    finished_at: int | None = None


@dataclass
class GuildInfo:
    """SAO Guild persistent summary & configuration."""

    id: int
    name: str
    tag: str
    leader_id: str
    level: int = 1
    exp: int = 0
    vault_col: int = 0
    merit_points: int = 0
    ranks_config: dict[str, Any] = field(default_factory=dict)
    member_count: int = 0
    max_members: int = 20
    active_buff_id: str = ""
    active_buff_expires_at: int = 0
    raid_last_started_at: int = 0
    created_at: int = 0


@dataclass
class MarketListing:
    """Player Marketplace atomic escrow listing."""

    id: int
    seller_id: str
    seller_name: str = ""
    item_type: str = "equipment"  # "equipment" | "item"
    equipment_id: int | None = None
    item_id: str | None = None
    quantity: int = 1
    item_name: str = ""
    slot: str = ""
    weapon_style: str = ""
    rarity: str = ""
    affix_keys: list[str] = field(default_factory=list)
    item_snapshot: dict[str, Any] = field(default_factory=dict)
    price_col: int = 0
    status: str = "active"  # "active" | "sold" | "cancelled"
    buyer_id: str | None = None
    created_at: int = 0
    sold_at: int | None = None


@dataclass
class ActionResult:
    """Standardized domain action response payload."""

    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "data": dict(self.data),
            "error_code": self.error_code,
        }
