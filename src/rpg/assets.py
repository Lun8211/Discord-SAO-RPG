"""Free, open-source RPG artwork & icon URL registry for Discord Embeds.

All artwork is served directly via GitHub's global Fastly CDN from an immutable
commit of The Battle for Wesnoth (https://github.com/wesnoth/wesnoth, GPL-2.0):
  - Equipment, pickaxe, potion, ring, helmet, armor icons: 60x60 / 72x72 PNG
  - Class promotions, Dungeon Bosses, World Bosses, SAO Aincrad Bosses: 450-500px WebP
  - Scene banners (Biomes, Towns, Forge, Dungeons, Mining Zones, Expeditions): WebP/JPG

Zero API keys required. Every path is pinned to an immutable commit SHA so
Discord's media proxy caches images reliably without link rot. Zero SVGs.
"""

from __future__ import annotations

import re

WESNOTH_COMMIT = "4536c331ac1e1470c13b5866b154395f50efbcfb"
WESNOTH_BASE = f"https://raw.githubusercontent.com/wesnoth/wesnoth/{WESNOTH_COMMIT}/data"
CORE_IMG = f"{WESNOTH_BASE}/core/images"

ASSET_CREDITS = (
    "RPG 裝備圖示、首領立繪與場景插畫來源：The Battle for Wesnoth 開源圖庫（GPL-2.0，免費免金鑰）"
)

_BIOME_TIER_RE = re.compile(r"^biome_t(\d+)")


def _core(rel_path: str) -> str:
    return f"{CORE_IMG}/{rel_path}"


def _data(rel_path: str) -> str:
    return f"{WESNOTH_BASE}/{rel_path}"


# =============================================================================
# 1. Equipment Icons by Gear Tier (T1 ~ T10) × Slot (8 SAO Slots + Legacy accessory)
# =============================================================================
EQUIPMENT_ICONS: dict[int, dict[str, str]] = {
    1: {  # T1 起始青銅
        "weapon": _core("attacks/sword-human-short.png"),
        "offhand": _core("icons/shield_polished.png"),
        "helmet": _core("icons/helmet_leather-cap.png"),
        "armor": _core("icons/armor_leather.png"),
        "gloves": _core("attacks/fist-human.png"),
        "boots": _core("icons/sandals.png"),
        "ring": _core("icons/stone_ring.png"),
        "necklace": _core("icons/jewelry_butterfly_pin.png"),
        "accessory": _core("icons/stone_ring.png"),
    },
    2: {  # T2 精鋼白銀 (拓荒者套裝)
        "weapon": _core("attacks/sword-steel.png"),
        "offhand": _core("icons/shield_polished.png"),
        "helmet": _core("icons/helmet_bascinet.png"),
        "armor": _core("icons/armor-chain.png"),
        "gloves": _core("attacks/tekko.png"),
        "boots": _core("attacks/foot-shoe.png"),
        "ring": _core("icons/ring_gold.png"),
        "necklace": _core("icons/jewelry_butterfly_pin.png"),
        "accessory": _core("icons/jewelry_butterfly_pin.png"),
    },
    3: {  # T3 熔炎秘銀 / 極光白銀
        "weapon": _core("attacks/sword-flaming.png"),
        "offhand": _core("icons/shield_polished.png"),
        "helmet": _core("icons/helmet_corinthian.png"),
        "armor": _core("icons/cuirass_muscled.png"),
        "gloves": _core("attacks/claws-fire-elemental.png"),
        "boots": _core("attacks/foot-boot.png"),
        "ring": _core("icons/ring_gold.png"),
        "necklace": _core("icons/jewelry_necklace_amber.png"),
        "accessory": _core("icons/jewelry_necklace_amber.png"),
    },
    4: {  # T4 霜星精金 / 幽影秘銀
        "weapon": _core("attacks/staff-elven-star.png"),
        "offhand": _core("icons/shield_polished.png"),
        "helmet": _core("icons/circlet_winged.png"),
        "armor": _core("icons/tunic_elven.png"),
        "gloves": _core("attacks/touch-faerie.png"),
        "boots": _core("icons/boots_elven.png"),
        "ring": _core("icons/jewelry_ring_prismatic.png"),
        "necklace": _core("icons/ankh_necklace.png"),
        "accessory": _core("icons/ankh_necklace.png"),
    },
    5: {  # T5 龍裔熾晶 / 阿爾格特精鋼
        "weapon": _core("attacks/greatsword-human.png"),
        "offhand": _core("icons/shield_polished.png"),
        "helmet": _core("icons/helmet_crested.png"),
        "armor": _core("icons/steel_armor.png"),
        "gloves": _core("attacks/claws-drake.png"),
        "boots": _core("icons/greaves.png"),
        "ring": _core("icons/skull_ring.png"),
        "necklace": _core("icons/jewelry_necklace_amber.png"),
        "accessory": _core("icons/skull_ring.png"),
    },
    6: {  # T6 星界虛空 / 水晶龍鋼
        "weapon": _core("attacks/sword-holy.png"),
        "offhand": _core("icons/shield_polished.png"),
        "helmet": _data("campaigns/Heir_To_The_Throne/images/icons/crown.png"),
        "armor": _core("icons/breastplate2.png"),
        "gloves": _core("attacks/claws-shadow.png"),
        "boots": _core("icons/boots_elven.png"),
        "ring": _core("icons/jewelry_ring_prismatic.png"),
        "necklace": _core("icons/ankh_necklace.png"),
        "accessory": _core("icons/jewelry_ring_prismatic.png"),
    },
    7: {  # T7 天界蒼穹 (F61-70)
        "weapon": _core("attacks/sword-flaming.png"),
        "offhand": _core("icons/shield_polished.png"),
        "helmet": _core("icons/circlet_winged.png"),
        "armor": _core("icons/steel_armor.png"),
        "gloves": _core("attacks/claws-drake.png"),
        "boots": _core("icons/boots_elven.png"),
        "ring": _core("icons/jewelry_ring_prismatic.png"),
        "necklace": _core("icons/ankh_necklace.png"),
        "accessory": _core("icons/jewelry_ring_prismatic.png"),
    },
    8: {  # T8 煉獄骸骨 (F71-80)
        "weapon": _core("attacks/greatsword-human.png"),
        "offhand": _core("icons/shield_polished.png"),
        "helmet": _core("icons/helmet_crested.png"),
        "armor": _core("icons/breastplate2.png"),
        "gloves": _core("attacks/claws-shadow.png"),
        "boots": _core("icons/greaves.png"),
        "ring": _core("icons/skull_ring.png"),
        "necklace": _core("icons/jewelry_necklace_amber.png"),
        "accessory": _core("icons/skull_ring.png"),
    },
    9: {  # T9 星辰虛空 (F81-90)
        "weapon": _core("attacks/sword-holy.png"),
        "offhand": _core("icons/shield_polished.png"),
        "helmet": _data("campaigns/Heir_To_The_Throne/images/icons/crown.png"),
        "armor": _core("icons/steel_armor.png"),
        "gloves": _core("attacks/claws-shadow.png"),
        "boots": _core("icons/boots_elven.png"),
        "ring": _core("icons/jewelry_ring_prismatic.png"),
        "necklace": _core("icons/ankh_necklace.png"),
        "accessory": _core("icons/jewelry_ring_prismatic.png"),
    },
    10: {  # T10 紅玉神域 (F91-100)
        "weapon": _core("attacks/sword-holy.png"),
        "offhand": _core("icons/shield_polished.png"),
        "helmet": _data("campaigns/Heir_To_The_Throne/images/icons/crown.png"),
        "armor": _core("icons/breastplate2.png"),
        "gloves": _core("attacks/claws-drake.png"),
        "boots": _core("icons/greaves.png"),
        "ring": _core("icons/jewelry_ring_prismatic.png"),
        "necklace": _core("icons/ankh_necklace.png"),
        "accessory": _core("icons/jewelry_ring_prismatic.png"),
    },
}

SLOT_DEFAULT_ICONS: dict[str, str] = {
    "weapon": _core("attacks/longsword.png"),
    "offhand": _core("icons/shield_polished.png"),
    "helmet": _core("icons/helmet_shiny.png"),
    "armor": _core("icons/breastplate.png"),
    "gloves": _core("attacks/fist-human.png"),
    "boots": _core("icons/greaves.png"),
    "ring": _core("icons/ring_gold.png"),
    "necklace": _core("icons/ankh_necklace.png"),
    "accessory": _core("icons/ring_gold.png"),  # Legacy alias preserved
}

# =============================================================================
# 2. Legacy Class Emblems & 3-Stage Promotion Portraits (Preserved for Compat)
# =============================================================================
CLASS_ICONS: dict[str, str] = {
    "swordsman": _core("attacks/greatsword-human.png"),
    "mage": _core("attacks/staff-elven-star.png"),
    "ranger": _core("attacks/bow-elven-magic.png"),
    "paladin": _core("icons/shield_polished.png"),
}

CLASS_PORTRAITS: dict[str, dict[int, str]] = {
    "swordsman": {
        1: _core("portraits/humans/swordsman.webp"),
        2: _core("portraits/humans/royal-guard.webp"),
        3: _core("portraits/humans/marshal.webp"),
    },
    "mage": {
        1: _core("portraits/humans/mage.webp"),
        2: _core("portraits/humans/mage-arch.webp"),
        3: _core("portraits/humans/mage-silver.webp"),
    },
    "ranger": {
        1: _core("portraits/humans/bowman.webp"),
        2: _core("portraits/humans/longbowman.webp"),
        3: _core("portraits/humans/master-bowman.webp"),
    },
    "paladin": {
        1: _core("portraits/humans/knight.webp"),
        2: _core("portraits/humans/paladin.webp"),
        3: _core("portraits/humans/grand-knight.webp"),
    },
}

# =============================================================================
# 3. Legacy Dungeon Bosses, World Bosses & Abyss Guardian Portraits (Preserved)
# =============================================================================
DUNGEON_BOSS_PORTRAITS: dict[str, str] = {
    "goblin_woods": _core("portraits/goblins/rouser.webp"),
    "undead_crypt": _core("portraits/undead/ancient-lich.webp"),
    "frost_cavern": _core("portraits/monsters/wyvern.webp"),
    "obsidian_fortress": _core("portraits/monsters/fire_guardian.webp"),
    "sunken_temple": _core("portraits/monsters/kraken.webp"),
    "crimson_castle": _core("portraits/undead/death-knight.webp"),
    "dragon_sanctum": _core("portraits/monsters/fire-dragon.webp"),
    "void_corridor": _core("portraits/undead/nightgaunt.webp"),
}

WORLD_BOSS_PORTRAITS: dict[str, str] = {
    "abyss_wyrm": _core("portraits/drakes/inferno.webp"),
    "star_titan": _core("portraits/trolls/troll-hero.webp"),
    "void_empress": _core("portraits/elves/sylph.webp"),
    "crimson_phoenix": _core("portraits/monsters/fire_wraith_A.webp"),
}

ABYSS_GUARDIAN_PORTRAITS: list[str] = [
    _core("portraits/undead/shadow.webp"),
    _core("portraits/undead/wraith.webp"),
    _core("portraits/undead/draug.webp"),
    _core("portraits/monsters/nightmare.webp"),
    _core("portraits/monsters/jinn.webp"),
    _core("portraits/monsters/war-harbinger.webp"),
    _core("portraits/undead/spectre.webp"),
    _core("portraits/drakes/blademaster.webp"),
]

# =============================================================================
# 4. Legacy Mining Zones, Pickaxes, Ores, Materials & SAO Consumables
# =============================================================================
MINE_ZONE_BANNERS: dict[str, str] = {
    "emerald_pit": _core("story/landscape-hills-01.webp"),
    "obsidian_cavern": _core("story/landscape-mountains-01.webp"),
    "crystal_grotto": _core("story/landscape-mountains-03.webp"),
    "mithril_abyss": _core("story/grim-altar.jpg"),
    "molten_vein": _core("story/landscape-lava.webp"),
    "astral_mantle": _core("story/landscape-mountains-05.webp"),
}

PICKAXE_ICONS: dict[int, str] = {
    1: _core("attacks/pick-axe.png"),
    2: _core("attacks/pick-axe.png"),
    3: _core("attacks/hammer.png"),
    4: _core("attacks/hammer-dwarven.png"),
    5: _core("attacks/hammer-dwarven-runic.png"),
    6: _core("items/hammer-runic.png"),
    7: _core("attacks/lightning.png"),
    8: _core("attacks/lightbeam.png"),
}

SAO_CRYSTAL_ICONS: dict[str, str] = {
    "healing_crystal": _core("icons/potion_red_medium.png"),
    "teleport_crystal": _core("items/ball-blue.png"),
    "antidote_crystal": _core("icons/potion_green_medium.png"),
    "corridor_crystal": _core("items/ball-magenta.png"),
}

ITEM_ICONS: dict[str, str] = {
    # Legacy Ores
    "copper_ore": _core("items/rock.png"),
    "iron_ore": _core("attacks/rock_thrown.png"),
    "silver_ore": _core("icons/coins_copper.png"),
    "magic_crystal": _core("items/ball-blue.png"),
    "mithril_ore": _core("attacks/iceball.png"),
    "adamantite_ore": _core("items/ball-magenta.png"),
    "dragon_crystal": _core("attacks/fireball.png"),
    "astral_ore": _core("attacks/faerie-fire.png"),
    "void_ether": _core("attacks/dark-missile.png"),
    # Legacy Upgrade & Boss Materials
    "enhance_stone": _core("items/ball-blue.png"),
    "adv_enhance_stone": _core("attacks/lightbeam.png"),
    "protect_scroll": _core("icons/scroll_red.png"),
    "boss_essence": _core("attacks/curse.png"),
    "mythic_core": _core("attacks/fire-blast.png"),
    # Legacy Consumables & Keys
    "hp_potion_s": _core("icons/potion_red_small.png"),
    "hp_potion_m": _core("icons/potion_red_medium.png"),
    "hp_potion_l": _core("items/holy-water.png"),
    "stamina_elixir": _core("icons/potion_green_medium.png"),
    "relic_key": _core("icons/key_silver.png"),
    "class_emblem": _core("misc/laurel.png"),
    # SAO Crystals & Consumables
    "healing_crystal": SAO_CRYSTAL_ICONS["healing_crystal"],
    "teleport_crystal": SAO_CRYSTAL_ICONS["teleport_crystal"],
    "antidote_crystal": SAO_CRYSTAL_ICONS["antidote_crystal"],
    "corridor_crystal": SAO_CRYSTAL_ICONS["corridor_crystal"],
    "bright_crystal_shard": _core("attacks/lightbeam.png"),
    "bright_crystal": _core("attacks/lightbeam.png"),
    "dark_crystal_shard": _core("attacks/dark-missile.png"),
    "dark_crystal": _core("attacks/dark-missile.png"),
    "dark_crystal_pure": _core("attacks/curse.png"),
    "protection_talisman": _core("icons/scroll_red.png"),
    "reroll_stone": _core("items/ball-magenta.png"),
    "swap_stone": _core("items/ball-blue.png"),
    "refine_stone": _core("attacks/faerie-fire.png"),
    "magic_stone_reroll": _core("items/ball-magenta.png"),
    "magic_stone_swap": _core("items/ball-blue.png"),
    "magic_stone_add": _core("attacks/faerie-fire.png"),
    "crystallite_ingot": _core("attacks/iceball.png"),
    "boar_meat": _core("icons/herb-bag.png"),
    "s_rank_ragout_rabbit": _core("items/holy-water.png"),
    "big_pot_stew": _core("items/holy-water.png"),
}

# =============================================================================
# 5. Expeditions, Shop Tabs, Leaderboards & General UI Artwork
# =============================================================================
EXPEDITION_BANNERS: dict[str, str] = {
    "forest_patrol": _core("story/wesmere.webp"),
    "ancient_mine_survey": _core("story/landscape-mountains-02.webp"),
    "mist_ruins": _core("story/swamp-01.webp"),
    "astral_rift_expedition": _core("story/landscape-mountains-04.webp"),
}

SHOP_TAB_ICONS: dict[str, str] = {
    "supply": _core("items/gold-coins-large.png"),
    "mystery": _core("items/ball-magenta.png"),
    "gacha": _core("items/chest.png"),
    "sell": _core("icons/coins_copper.png"),
}

LEADERBOARD_ICONS: dict[str, str] = {
    # Legacy categories
    "power": _core("icons/crossed_sword_and_hammer.png"),
    "level": _core("misc/laurel.png"),
    "abyss": _core("portraits/undead/nightgaunt.webp"),
    "gold": _core("items/gold-coins-large.png"),
    "mining": _core("attacks/pick-axe.png"),
    "boss": _core("portraits/monsters/fire-dragon.webp"),
    # SAO categories
    "floor": _core("story/landscape-castle.webp"),
    "world_boss": _core("portraits/monsters/fire-dragon.webp"),
    "guild": _core("icons/shield_polished.png"),
    "col": _core("items/gold-coins-large.png"),
    "survival": _core("misc/laurel.png"),
}

UI_ASSETS: dict[str, str] = {
    # Legacy keys (15)
    "welcome_banner": _core("story/wesmere.webp"),
    "help_banner": _core("story/landscape-bridge_sun.webp"),
    "dungeon_hall_banner": _core("story/landscape-castle.webp"),
    "forge_banner": _core("story/blacksmith.webp"),
    "expedition_default_banner": _core("story/landscape-plain.webp"),
    "rebirth_banner": _core("story/drake.webp"),
    "anvil_icon": _core("items/anvil.png"),
    "chest_closed": _core("items/chest.png"),
    "chest_open": _core("items/chest-open.png"),
    "bag_icon": _core("icons/bag.png"),
    "materials_icon": _core("icons/herb-bag.png"),
    "quest_scroll": _core("icons/scroll_red.png"),
    "achievement_laurel": _core("misc/laurel.png"),
    "gold_coins": _core("items/gold-coins-large.png"),
    "combat_swords": _core("icons/crossed_sword_and_hammer.png"),
    # SAO UI banners
    "ui_aincrad_banner": _core("story/landscape-castle.webp"),
    "aincrad_welcome_banner": _core("story/landscape-castle.webp"),
    "town_safe_zone_banner": _core("story/landscape-bridge_sun.webp"),
    "monument_of_life_banner": _core("story/grim-altar.jpg"),
    "argo_intel_banner": _core("story/wesmere.webp"),
    "yui_console_banner": _core("story/landscape-mountains-05.webp"),
    "guild_hall_banner": _core("story/landscape-castle.webp"),
    "market_banner": _core("story/landscape-plain.webp"),
    "party_lobby_banner": _core("story/landscape-hills-01.webp"),
    "raid_battle_banner": _core("story/drake.webp"),
    "secret_realm_banner": _core("story/swamp-01.webp"),
    "roguelike_banner": _core("story/grim-altar.jpg"),
    "cooking_banner": _core("story/blacksmith.webp"),
    "duel_banner": _core("story/landscape-mountains-01.webp"),
    "nightmare_banner": _core("story/landscape-lava.webp"),
    "boss_rush_banner": _core("story/drake.webp"),
}

# =============================================================================
# 6. SAO Aincrad 100-Floor Registries (100% Reused Verified Wesnoth Raster URLs)
# =============================================================================
BIOME_BANNERS_BY_TIER: dict[int, str] = {
    1: _core("story/landscape-plain.webp"),
    2: _core("story/wesmere.webp"),
    3: _core("story/landscape-mountains-03.webp"),
    4: _core("story/swamp-01.webp"),
    5: _core("story/landscape-bridge_sun.webp"),
    6: _core("story/landscape-lava.webp"),
    7: _core("story/landscape-mountains-04.webp"),
    8: _core("story/grim-altar.jpg"),
    9: _core("story/landscape-mountains-05.webp"),
    10: _core("story/landscape-castle.webp"),
}

BIOME_BANNERS: dict[str, str] = {
    # Canonical biome_t1..t10 keys
    "biome_t1_plains": BIOME_BANNERS_BY_TIER[1],
    "biome_t2_mist_woods": BIOME_BANNERS_BY_TIER[2],
    "biome_t3_glacial_lake": BIOME_BANNERS_BY_TIER[3],
    "biome_t3_frozen_lake": BIOME_BANNERS_BY_TIER[3],
    "biome_t4_shadow_keep": BIOME_BANNERS_BY_TIER[4],
    "biome_t5_iron_metropolis": BIOME_BANNERS_BY_TIER[5],
    "biome_t5_blossom_iron": BIOME_BANNERS_BY_TIER[5],
    "biome_t6_crystallite_peaks": BIOME_BANNERS_BY_TIER[6],
    "biome_t6_crystallite_lava": BIOME_BANNERS_BY_TIER[6],
    "biome_t7_sky_sanctum": BIOME_BANNERS_BY_TIER[7],
    "biome_t8_bone_wasteland": BIOME_BANNERS_BY_TIER[8],
    "biome_t8_bone_labyrinth": BIOME_BANNERS_BY_TIER[8],
    "biome_t9_astral_void": BIOME_BANNERS_BY_TIER[9],
    "biome_t10_ruby_palace": BIOME_BANNERS_BY_TIER[10],
}

SAO_BOSS_PORTRAITS: dict[str, str] = {
    # 14 Milestone Bosses (canonical IDs + boss_* asset keys + aliases)
    "illfang_kobold_lord": _core("portraits/goblins/rouser.webp"),
    "boss_illfang": _core("portraits/goblins/rouser.webp"),
    "kagachi_samurai_lord": _core("portraits/drakes/blademaster.webp"),
    "boss_kagachi": _core("portraits/drakes/blademaster.webp"),
    "valdoras_miasma_ent": _core("portraits/trolls/troll-hero.webp"),
    "boss_valdoras": _core("portraits/trolls/troll-hero.webp"),
    "abyssward_twin_mouthed": _core("portraits/monsters/war-harbinger.webp"),
    "boss_abyssward": _core("portraits/monsters/war-harbinger.webp"),
    "frost_kaiser": _core("portraits/monsters/wyvern.webp"),
    "boss_frost_kaiser": _core("portraits/monsters/wyvern.webp"),
    "feral_warder_chief": _core("portraits/undead/draug.webp"),
    "boss_feral_warder": _core("portraits/undead/draug.webp"),
    "steel_arbiter_algade": _core("portraits/humans/grand-knight.webp"),
    "boss_steel_arbiter": _core("portraits/humans/grand-knight.webp"),
    "ignis_crystallite_wyrm": _core("portraits/monsters/fire-dragon.webp"),
    "boss_ignis_wyrm": _core("portraits/monsters/fire-dragon.webp"),
    "astraea_sky_warden": _core("portraits/elves/sylph.webp"),
    "boss_astraea": _core("portraits/elves/sylph.webp"),
    "gleam_eyes": _core("portraits/drakes/inferno.webp"),
    "the_gleam_eyes": _core("portraits/drakes/inferno.webp"),
    "boss_gleam_eyes": _core("portraits/drakes/inferno.webp"),
    "skull_reaper": _core("portraits/undead/death-knight.webp"),
    "the_skull_reaper": _core("portraits/undead/death-knight.webp"),
    "boss_skull_reaper": _core("portraits/undead/death-knight.webp"),
    "mortis_pale_harvester": _core("portraits/undead/spectre.webp"),
    "boss_mortis": _core("portraits/undead/spectre.webp"),
    "chronos_astral_archon": _core("portraits/undead/ancient-lich.webp"),
    "boss_chronos": _core("portraits/undead/ancient-lich.webp"),
    "f100_incarnation_and_heathcliff": _core("portraits/humans/paladin.webp"),
    "boss_heathcliff_f100": _core("portraits/humans/paladin.webp"),
    "incarnation_of_radius": _core("portraits/monsters/jinn.webp"),
    "heathcliff_paladin": _core("portraits/humans/paladin.webp"),
}

MILESTONE_BOSS_BY_FLOOR: dict[int, str] = {
    1: "illfang_kobold_lord",
    10: "kagachi_samurai_lord",
    20: "valdoras_miasma_ent",
    25: "abyssward_twin_mouthed",
    30: "frost_kaiser",
    40: "feral_warder_chief",
    50: "steel_arbiter_algade",
    60: "ignis_crystallite_wyrm",
    70: "astraea_sky_warden",
    74: "gleam_eyes",
    75: "skull_reaper",
    80: "mortis_pale_harvester",
    90: "chronos_astral_archon",
    100: "f100_incarnation_and_heathcliff",
}

TIER_GUARDIAN_PORTRAITS: dict[str, str] = {
    "tier_1_guardian": _core("portraits/goblins/rouser.webp"),
    "tier_2_guardian": _core("portraits/monsters/kraken.webp"),
    "tier_3_guardian": _core("portraits/monsters/wyvern.webp"),
    "tier_4_guardian": _core("portraits/undead/shadow.webp"),
    "tier_5_guardian": _core("portraits/humans/royal-guard.webp"),
    "tier_6_guardian": _core("portraits/monsters/fire_guardian.webp"),
    "tier_7_guardian": _core("portraits/monsters/fire_wraith_A.webp"),
    "tier_8_guardian": _core("portraits/undead/wraith.webp"),
    "tier_9_guardian": _core("portraits/undead/nightgaunt.webp"),
    "tier_10_guardian": _core("portraits/monsters/nightmare.webp"),
    "boss_tier_1": _core("portraits/goblins/rouser.webp"),
    "boss_tier_2": _core("portraits/monsters/kraken.webp"),
    "boss_tier_3": _core("portraits/monsters/wyvern.webp"),
    "boss_tier_4": _core("portraits/undead/shadow.webp"),
    "boss_tier_5": _core("portraits/humans/royal-guard.webp"),
    "boss_tier_6": _core("portraits/monsters/fire_guardian.webp"),
    "boss_tier_7": _core("portraits/monsters/fire_wraith_A.webp"),
    "boss_tier_8": _core("portraits/undead/wraith.webp"),
    "boss_tier_9": _core("portraits/undead/nightgaunt.webp"),
    "boss_tier_10": _core("portraits/monsters/nightmare.webp"),
}

SAO_WORLD_BOSS_PORTRAITS: dict[str, str] = {
    "wb_iron_behemoth": _core("portraits/trolls/troll-hero.webp"),
    "wb_miasma_hydra": _core("portraits/monsters/kraken.webp"),
    "wb_aurora_leviathan": _core("portraits/monsters/wyvern.webp"),
    "wb_phantom_sovereign": _core("portraits/undead/ancient-lich.webp"),
    "wb_clockwork_titan": _core("portraits/monsters/fire_guardian.webp"),
    "wb_caldera_wyrm": _core("portraits/monsters/fire-dragon.webp"),
    "wb_tempest_seraph": _core("portraits/elves/sylph.webp"),
    "wb_pale_behemoth": _core("portraits/undead/death-knight.webp"),
    "wb_void_empress_sao": _core("portraits/undead/nightgaunt.webp"),
    "wb_cardinal_omega": _core("portraits/monsters/jinn.webp"),
    "wb_tier_1": _core("portraits/trolls/troll-hero.webp"),
    "wb_tier_2": _core("portraits/monsters/kraken.webp"),
    "wb_tier_3": _core("portraits/monsters/wyvern.webp"),
    "wb_tier_4": _core("portraits/undead/ancient-lich.webp"),
    "wb_tier_5": _core("portraits/monsters/fire_guardian.webp"),
    "wb_tier_6": _core("portraits/monsters/fire-dragon.webp"),
    "wb_tier_7": _core("portraits/elves/sylph.webp"),
    "wb_tier_8": _core("portraits/undead/death-knight.webp"),
    "wb_tier_9": _core("portraits/undead/nightgaunt.webp"),
    "wb_tier_10": _core("portraits/monsters/jinn.webp"),
}

WEAPON_STYLE_ICONS: dict[str, str] = {
    "sword": _core("attacks/longsword.png"),
    "rapier": _core("attacks/sword-steel.png"),
    "katana": _core("attacks/sword-flaming.png"),
    "axe": _core("attacks/greatsword-human.png"),
    "mace": _core("attacks/hammer-dwarven.png"),
    "holy": _core("icons/shield_polished.png"),
    "scythe": _core("attacks/claws-shadow.png"),
    "dagger": _core("attacks/sword-human-short.png"),
    "dual_blades": _core("attacks/sword-holy.png"),
    "holy_sword": _core("icons/crossed_sword_and_hammer.png"),
}

WEAPON_STYLE_PORTRAITS: dict[str, str] = {
    "sword": _core("portraits/humans/swordsman.webp"),
    "rapier": _core("portraits/humans/royal-guard.webp"),
    "katana": _core("portraits/humans/marshal.webp"),
    "axe": _core("portraits/trolls/troll-hero.webp"),
    "mace": _core("portraits/humans/knight.webp"),
    "holy": _core("portraits/humans/paladin.webp"),
    "scythe": _core("portraits/undead/wraith.webp"),
    "dagger": _core("portraits/humans/bowman.webp"),
    "dual_blades": _core("portraits/humans/marshal.webp"),
    "holy_sword": _core("portraits/humans/grand-knight.webp"),
}

CHEST_ICONS: dict[str, str] = {
    "wooden": _core("items/chest.png"),
    "iron": _core("items/chest.png"),
    "silver": _core("icons/key_silver.png"),
    "gold": _core("items/gold-coins-large.png"),
    "boss_relic": _core("items/chest-open.png"),
    "named_vault": _data("campaigns/Heir_To_The_Throne/images/icons/crown.png"),
    "mimic": _core("portraits/monsters/nightmare.webp"),
    "mimic_trap": _core("portraits/monsters/nightmare.webp"),
    "crystal_null_trap": _core("attacks/curse.png"),
    "chest_wooden": _core("items/chest.png"),
    "chest_iron": _core("items/chest.png"),
    "chest_silver": _core("icons/key_silver.png"),
    "chest_gold": _core("items/gold-coins-large.png"),
    "chest_boss_relic": _core("items/chest-open.png"),
    "chest_mimic": _core("portraits/monsters/nightmare.webp"),
}

MOB_CATEGORY_PORTRAITS: dict[str, str] = {
    # Category keys
    "beast": _core("portraits/goblins/rouser.webp"),
    "kobold": _core("portraits/goblins/rouser.webp"),
    "samurai": _core("portraits/drakes/blademaster.webp"),
    "insect": _core("portraits/monsters/fire_wraith_A.webp"),
    "treant": _core("portraits/trolls/troll-hero.webp"),
    "gargoyle": _core("portraits/monsters/fire_guardian.webp"),
    "lizard": _core("portraits/monsters/wyvern.webp"),
    "aquatic": _core("portraits/monsters/kraken.webp"),
    "frost": _core("portraits/monsters/wyvern.webp"),
    "undead": _core("portraits/undead/draug.webp"),
    "construct": _core("portraits/monsters/fire_guardian.webp"),
    "golem": _core("portraits/monsters/fire_guardian.webp"),
    "knight": _core("portraits/humans/royal-guard.webp"),
    "dragon": _core("portraits/monsters/wyvern.webp"),
    "demon": _core("portraits/drakes/inferno.webp"),
    "celestial": _core("portraits/elves/sylph.webp"),
    "void": _core("portraits/undead/nightgaunt.webp"),
    "humanoid": _core("portraits/humans/royal-guard.webp"),
    "mimic": _core("portraits/monsters/nightmare.webp"),
    "warden": _core("portraits/undead/death-knight.webp"),
    "boss_field": _core("portraits/monsters/war-harbinger.webp"),
    "boss_normal": _core("portraits/undead/death-knight.webp"),
    "boss_world": _core("portraits/monsters/fire-dragon.webp"),
    # Prefixed mob_* keys used by monsters.json
    "mob_beast": _core("portraits/goblins/rouser.webp"),
    "mob_kobold": _core("portraits/goblins/rouser.webp"),
    "mob_samurai": _core("portraits/drakes/blademaster.webp"),
    "mob_insect": _core("portraits/monsters/fire_wraith_A.webp"),
    "mob_treant": _core("portraits/trolls/troll-hero.webp"),
    "mob_gargoyle": _core("portraits/monsters/fire_guardian.webp"),
    "mob_lizard": _core("portraits/monsters/wyvern.webp"),
    "mob_aquatic": _core("portraits/monsters/kraken.webp"),
    "mob_frost": _core("portraits/monsters/wyvern.webp"),
    "mob_undead": _core("portraits/undead/draug.webp"),
    "mob_knight": _core("portraits/humans/royal-guard.webp"),
    "mob_golem": _core("portraits/monsters/fire_guardian.webp"),
    "mob_dragon": _core("portraits/monsters/wyvern.webp"),
    "mob_demon": _core("portraits/drakes/inferno.webp"),
    "mob_celestial": _core("portraits/elves/sylph.webp"),
    "mob_void": _core("portraits/undead/nightgaunt.webp"),
    "mob_mimic": _core("portraits/monsters/nightmare.webp"),
    "mob_warden": _core("portraits/undead/death-knight.webp"),
}

# Item category & named equipment keys referenced by JSON content files
_JSON_EXTRA_ASSETS: dict[str, str] = {
    # Weapon & Unique Skill prefixed keys
    "weapon_sword": WEAPON_STYLE_ICONS["sword"],
    "weapon_rapier": WEAPON_STYLE_ICONS["rapier"],
    "weapon_katana": WEAPON_STYLE_ICONS["katana"],
    "weapon_axe": WEAPON_STYLE_ICONS["axe"],
    "weapon_mace": WEAPON_STYLE_ICONS["mace"],
    "weapon_holy": WEAPON_STYLE_ICONS["holy"],
    "weapon_scythe": WEAPON_STYLE_ICONS["scythe"],
    "weapon_dagger": WEAPON_STYLE_ICONS["dagger"],
    "unique_dual_blades": WEAPON_STYLE_ICONS["dual_blades"],
    "unique_holy_sword": WEAPON_STYLE_ICONS["holy_sword"],
    # Slot prefixed keys
    "slot_weapon": SLOT_DEFAULT_ICONS["weapon"],
    "slot_offhand": SLOT_DEFAULT_ICONS["offhand"],
    "slot_helmet": SLOT_DEFAULT_ICONS["helmet"],
    "slot_armor": SLOT_DEFAULT_ICONS["armor"],
    "slot_gloves": SLOT_DEFAULT_ICONS["gloves"],
    "slot_boots": SLOT_DEFAULT_ICONS["boots"],
    "slot_ring": SLOT_DEFAULT_ICONS["ring"],
    "slot_necklace": SLOT_DEFAULT_ICONS["necklace"],
    # Named items (18)
    "named_coat_of_midnight": _core("icons/armor_leather.png"),
    "named_sensha_kagekiri": _core("attacks/sword-flaming.png"),
    "named_shinra_emerald_gauntlets": _core("attacks/touch-faerie.png"),
    "named_clearer_vanguard_badge": _core("icons/jewelry_butterfly_pin.png"),
    "named_aurora_frostcrown_boots": _core("icons/boots_elven.png"),
    "named_feral_warder_greataxe": _core("attacks/greatsword-human.png"),
    "named_elucidator": _core("attacks/sword-steel.png"),
    "named_crystallite_dragon_plate": _core("icons/steel_armor.png"),
    "named_celestial_flash_rapier": _core("attacks/sword-holy.png"),
    "named_gleam_eyes_obsidian_cloak": _core("icons/breastplate2.png"),
    "named_skull_reaper_scythe": _core("attacks/claws-shadow.png"),
    "named_pale_requiem_necklace": _core("icons/ankh_necklace.png"),
    "named_chronos_hourglass_ring": _core("icons/jewelry_ring_prismatic.png"),
    "named_ruby_heart_sacred_sword": _core("attacks/sword-holy.png"),
    "named_dark_repulser": _core("attacks/sword-flaming.png"),
    "named_lambent_light": _core("attacks/sword-holy.png"),
    "named_liberator_shield": _core("icons/shield_polished.png"),
    "named_reapers_crescent": _core("attacks/claws-shadow.png"),
    # Round 2 Expanded Named items (12 -> 30 total)
    "named_anneal_blade": _core("attacks/sword-human-short.png"),
    "named_kobold_sentinel_helm": _core("icons/helmet_bascinet.png"),
    "named_iron_oath_mace": _core("attacks/mace.png"),
    "named_shadow_fang_dagger": _core("attacks/dagger-human.png"),
    "named_wind_fleuret_rapier": _core("attacks/saber-human.png"),
    "named_emerald_bastion_helm": _core("icons/helmet_corinthian.png"),
    "named_frostbite_warhammer": _core("attacks/hammer-dwarven.png"),
    "named_bloodmoon_twin_dirk": _core("attacks/dagger-thrown-poison-human.png"),
    "named_lindarth_master_gauntlets": _core("attacks/tekko.png"),
    "named_valkyrie_sky_helm": _core("icons/circlet_winged.png"),
    "named_seraphim_judgement_mace": _core("attacks/hammer-troll.png"),
    "named_cardinal_genesis_crown": _data("campaigns/Heir_To_The_Throne/images/icons/crown.png"),
    # Item category keys
    "item_potion_hp": _core("icons/potion_red_medium.png"),
    "item_potion_sp": _core("items/ball-blue.png"),
    "item_crystal_red": SAO_CRYSTAL_ICONS["healing_crystal"],
    "item_crystal_blue": SAO_CRYSTAL_ICONS["teleport_crystal"],
    "item_crystal_green": SAO_CRYSTAL_ICONS["antidote_crystal"],
    "item_crystal_yellow": SAO_CRYSTAL_ICONS["corridor_crystal"],
    "item_bright_crystal": _core("attacks/lightbeam.png"),
    "item_dark_crystal": _core("attacks/dark-missile.png"),
    "item_talisman": _core("icons/scroll_red.png"),
    "item_magic_stone": _core("items/ball-magenta.png"),
    "item_expand_stone": _core("items/ball-green.png"),
    "item_socket_crystal": _core("items/ball-blue.png"),
    "item_forge_scrap": _core("items/armor.png"),
    "item_supply_crate": _core("items/chest-plain-closed.png"),
    "item_ore_common": _core("items/rock.png"),
    "item_ore_rare": _core("attacks/faerie-fire.png"),
    "item_ore_crystallite": _core("attacks/iceball.png"),
    "item_boss_crest": _core("attacks/curse.png"),
    "item_meat": _core("icons/herb-bag.png"),
    "item_dish": _core("items/holy-water.png"),
    "item_stew": _core("items/holy-water.png"),
    "item_misc": _core("icons/bag.png"),
}

# Unified SAO Asset Registry (guaranteed zero-SVG, pinned Wesnoth raster CDN)
SAO_ASSET_REGISTRY: dict[str, str] = {
    **UI_ASSETS,
    **BIOME_BANNERS,
    **SAO_BOSS_PORTRAITS,
    **TIER_GUARDIAN_PORTRAITS,
    **SAO_WORLD_BOSS_PORTRAITS,
    **WEAPON_STYLE_ICONS,
    **SAO_CRYSTAL_ICONS,
    **CHEST_ICONS,
    **MOB_CATEGORY_PORTRAITS,
    **SLOT_DEFAULT_ICONS,
    **ITEM_ICONS,
    **LEADERBOARD_ICONS,
    **_JSON_EXTRA_ASSETS,
}


# =============================================================================
# Public Helper Getters (Legacy + SAO — Safe Fallbacks Guaranteed)
# =============================================================================
def get_equipment_image_url(tier: int, slot: str) -> str:
    """Return the RPG artwork URL for an equipment item by tier (1..10) and slot."""
    clamped_tier = max(1, min(10, int(tier)))
    tier_map = EQUIPMENT_ICONS.get(clamped_tier, EQUIPMENT_ICONS[1])
    return tier_map.get(slot, SLOT_DEFAULT_ICONS.get(slot, SLOT_DEFAULT_ICONS["weapon"]))


def get_slot_icon_url(slot: str) -> str:
    return SLOT_DEFAULT_ICONS.get(slot, SLOT_DEFAULT_ICONS["weapon"])


def get_class_icon_url(class_id: str) -> str:
    return CLASS_ICONS.get(class_id, WEAPON_STYLE_ICONS.get(class_id, CLASS_ICONS["swordsman"]))


def get_class_portrait_url(class_id: str, promo_tier: int = 1) -> str:
    if class_id in CLASS_PORTRAITS:
        clamped = max(1, min(3, int(promo_tier)))
        tiers = CLASS_PORTRAITS[class_id]
        return tiers.get(clamped, tiers[1])
    if class_id in WEAPON_STYLE_PORTRAITS:
        return WEAPON_STYLE_PORTRAITS[class_id]
    clamped = max(1, min(3, int(promo_tier)))
    tiers = CLASS_PORTRAITS["swordsman"]
    return tiers.get(clamped, tiers[1])


def get_dungeon_boss_portrait_url(dungeon_id: str) -> str:
    return DUNGEON_BOSS_PORTRAITS.get(dungeon_id, DUNGEON_BOSS_PORTRAITS["goblin_woods"])


def get_world_boss_portrait_url(template_id: str) -> str:
    if template_id in SAO_WORLD_BOSS_PORTRAITS:
        return SAO_WORLD_BOSS_PORTRAITS[template_id]
    return WORLD_BOSS_PORTRAITS.get(template_id, WORLD_BOSS_PORTRAITS["abyss_wyrm"])


def get_abyss_guardian_portrait_url(floor: int) -> str:
    idx = max(0, (int(floor) - 1)) % len(ABYSS_GUARDIAN_PORTRAITS)
    return ABYSS_GUARDIAN_PORTRAITS[idx]


def get_mine_zone_banner_url(zone_id: str) -> str:
    return MINE_ZONE_BANNERS.get(zone_id, MINE_ZONE_BANNERS["emerald_pit"])


def get_pickaxe_icon_url(tier: int) -> str:
    clamped = max(1, min(8, int(tier)))
    return PICKAXE_ICONS.get(clamped, PICKAXE_ICONS[1])


def get_item_icon_url(item_id: str) -> str:
    return ITEM_ICONS.get(item_id, SAO_ASSET_REGISTRY.get(item_id, UI_ASSETS["materials_icon"]))


def get_expedition_banner_url(expedition_id: str) -> str:
    return EXPEDITION_BANNERS.get(expedition_id, UI_ASSETS["expedition_default_banner"])


def get_shop_tab_icon_url(tab: str) -> str:
    return SHOP_TAB_ICONS.get(tab, SHOP_TAB_ICONS["supply"])


def get_leaderboard_icon_url(category: str) -> str:
    return LEADERBOARD_ICONS.get(category, LEADERBOARD_ICONS["power"])


def get_ui_asset_url(key: str) -> str:
    return UI_ASSETS.get(key, UI_ASSETS["combat_swords"])


# --- New SAO Asset Helpers ---
def get_biome_banner_url(key_or_tier: str | int) -> str:
    if isinstance(key_or_tier, int) and not isinstance(key_or_tier, bool):
        tier = max(1, min(10, key_or_tier))
        return BIOME_BANNERS_BY_TIER[tier]
    key = str(key_or_tier)
    if key in BIOME_BANNERS:
        return BIOME_BANNERS[key]
    match = _BIOME_TIER_RE.match(key)
    if match:
        tier = max(1, min(10, int(match.group(1))))
        return BIOME_BANNERS_BY_TIER[tier]
    return BIOME_BANNERS["biome_t1_plains"]


def get_sao_boss_portrait_url(boss_id: str, floor: int = 1) -> str:
    if boss_id in SAO_BOSS_PORTRAITS:
        return SAO_BOSS_PORTRAITS[boss_id]
    if boss_id in TIER_GUARDIAN_PORTRAITS:
        return TIER_GUARDIAN_PORTRAITS[boss_id]
    if boss_id in SAO_WORLD_BOSS_PORTRAITS:
        return SAO_WORLD_BOSS_PORTRAITS[boss_id]
    milestone_key = MILESTONE_BOSS_BY_FLOOR.get(int(floor))
    if milestone_key and milestone_key in SAO_BOSS_PORTRAITS:
        return SAO_BOSS_PORTRAITS[milestone_key]
    tier = ((max(1, min(100, int(floor))) - 1) // 10) + 1
    return TIER_GUARDIAN_PORTRAITS[f"tier_{tier}_guardian"]


def get_weapon_style_icon_url(style_id: str) -> str:
    return WEAPON_STYLE_ICONS.get(style_id, WEAPON_STYLE_ICONS["sword"])


def get_weapon_style_portrait_url(style_id: str) -> str:
    return WEAPON_STYLE_PORTRAITS.get(style_id, WEAPON_STYLE_PORTRAITS["sword"])


def get_crystal_icon_url(crystal_id: str) -> str:
    return SAO_CRYSTAL_ICONS.get(crystal_id, SAO_CRYSTAL_ICONS["healing_crystal"])


def get_chest_icon_url(chest_tier: str) -> str:
    return CHEST_ICONS.get(chest_tier, CHEST_ICONS["wooden"])


def get_mob_portrait_url(category: str) -> str:
    return MOB_CATEGORY_PORTRAITS.get(category, MOB_CATEGORY_PORTRAITS["beast"])


def has_asset_key(key: str) -> bool:
    return key in SAO_ASSET_REGISTRY


def resolve_asset_key(asset_key: str) -> str | None:
    return SAO_ASSET_REGISTRY.get(asset_key)


def get_sao_asset_url(key: str, default_key: str = "ui_aincrad_banner") -> str:
    url = SAO_ASSET_REGISTRY.get(key)
    if url is not None:
        return url
    return SAO_ASSET_REGISTRY.get(default_key, UI_ASSETS["ui_aincrad_banner"])


def all_asset_urls() -> list[str]:
    """Return every unique asset URL registered in this module (used for verification/tests)."""
    urls: set[str] = set()
    for tier_map in EQUIPMENT_ICONS.values():
        urls.update(tier_map.values())
    urls.update(SLOT_DEFAULT_ICONS.values())
    urls.update(CLASS_ICONS.values())
    for portrait_map in CLASS_PORTRAITS.values():
        urls.update(portrait_map.values())
    urls.update(DUNGEON_BOSS_PORTRAITS.values())
    urls.update(WORLD_BOSS_PORTRAITS.values())
    urls.update(ABYSS_GUARDIAN_PORTRAITS)
    urls.update(MINE_ZONE_BANNERS.values())
    urls.update(PICKAXE_ICONS.values())
    urls.update(ITEM_ICONS.values())
    urls.update(EXPEDITION_BANNERS.values())
    urls.update(SHOP_TAB_ICONS.values())
    urls.update(LEADERBOARD_ICONS.values())
    urls.update(UI_ASSETS.values())
    urls.update(BIOME_BANNERS_BY_TIER.values())
    urls.update(BIOME_BANNERS.values())
    urls.update(SAO_BOSS_PORTRAITS.values())
    urls.update(TIER_GUARDIAN_PORTRAITS.values())
    urls.update(SAO_WORLD_BOSS_PORTRAITS.values())
    urls.update(WEAPON_STYLE_ICONS.values())
    urls.update(WEAPON_STYLE_PORTRAITS.values())
    urls.update(SAO_CRYSTAL_ICONS.values())
    urls.update(CHEST_ICONS.values())
    urls.update(MOB_CATEGORY_PORTRAITS.values())
    urls.update(SAO_ASSET_REGISTRY.values())
    return sorted(urls)
