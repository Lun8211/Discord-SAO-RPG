from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ComputedStats:
    """Total computed combat & utility stats for a player."""

    max_hp: int
    max_mp: int
    atk: int
    def_: int
    crit_rate: float
    crit_dmg: float
    dodge: float
    lifesteal: float
    gold_bonus: float
    exp_bonus: float
    drop_bonus: float
    mine_bonus: float
    skill_dmg_bonus: float
    dmg_reduction: float
    combat_power: int
    active_sets: List[str] = field(default_factory=list)


@dataclass
class EquipmentItem:
    """An individual owned equipment piece persisted in SQLite."""

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
    affixes: Dict[str, float]
    is_equipped: bool = False
    is_locked: bool = False
    created_at: int = 0

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
    def hp(self) -> int:
        return int(round(self.base_hp * self.enhance_multiplier()))

    @property
    def mp(self) -> int:
        return int(round(self.base_mp * self.enhance_multiplier()))

    @property
    def atk(self) -> int:
        return int(round(self.base_atk * self.enhance_multiplier()))

    @property
    def def_(self) -> int:
        return int(round(self.base_def * self.enhance_multiplier()))

    @property
    def power_score(self) -> int:
        affix_score = 0.0
        for key, val in self.affixes.items():
            if key in ("atk_pct", "def_pct", "hp_pct"):
                affix_score += val * 800
            elif key in ("crit_rate", "dodge", "lifesteal"):
                affix_score += val * 1200
            elif key == "crit_dmg":
                affix_score += val * 450
            else:
                affix_score += val * 300
        return int(
            self.atk * 5
            + self.def_ * 4
            + self.hp * 0.6
            + self.mp * 1.2
            + affix_score
        )


@dataclass
class PlayerProfile:
    """Core persistent RPG player record."""

    user_id: str
    display_name: str
    class_id: str
    promo_tier: int
    level: int
    exp: int
    rebirth_count: int
    gold: int
    gems: int
    stamina: int
    stamina_updated_at: int
    pickaxe_tier: int
    mine_combo: int
    last_mine_at: int
    last_boss_at: int
    abyss_floor: int
    abyss_highest: int
    active_title: str
    gacha_pity_legendary: int
    gacha_pity_mythic: int
    checkin_streak: int
    last_checkin_date: str
    total_checkins: int
    total_mines: int
    total_dungeons: int
    total_enhances: int
    total_boss_damage: int
    boss_kills_participated: int
    combat_power: int
    created_at: int
    updated_at: int


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
    defeated_at: Optional[int] = None
    killer_user_id: Optional[str] = None


@dataclass
class CombatSession:
    """In-memory state for an active turn-based battle (dungeon or abyss)."""

    user_id: str
    mode: str  # "dungeon" | "abyss"
    target_id: str  # dungeon_id or floor string
    difficulty: str  # "normal" | "hard" | "hell" | "abyss"
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
    logs: List[str] = field(default_factory=list)
    rewards_summary: Optional[dict] = None
