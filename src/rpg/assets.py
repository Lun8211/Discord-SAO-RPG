"""Free, open-source RPG artwork & icon URL registry for Discord Embeds.

All artwork is served directly via GitHub's global Fastly CDN from an immutable
commit of The Battle for Wesnoth (https://github.com/wesnoth/wesnoth, GPL-2.0):
  - Equipment, pickaxe, potion, ring, helmet, armor icons: 60x60 / 72x72 PNG
  - Class promotions, Dungeon Bosses, World Bosses, Abyss Guardians: 450-500px WebP
  - Scene banners (Forge, Dungeons, Mining Zones, Expeditions, Rebirth): WebP/JPG

Zero API keys required. Every path is pinned to an immutable commit SHA so
Discord's media proxy caches images reliably without link rot.
"""

from __future__ import annotations

from typing import Dict, List

WESNOTH_COMMIT = "4536c331ac1e1470c13b5866b154395f50efbcfb"
WESNOTH_BASE = f"https://raw.githubusercontent.com/wesnoth/wesnoth/{WESNOTH_COMMIT}/data"
CORE_IMG = f"{WESNOTH_BASE}/core/images"

ASSET_CREDITS = (
    "RPG 裝備圖示、首領立繪與場景插畫來源：The Battle for Wesnoth 開源圖庫（GPL-2.0，免費免金鑰）"
)


def _core(rel_path: str) -> str:
    return f"{CORE_IMG}/{rel_path}"


def _data(rel_path: str) -> str:
    return f"{WESNOTH_BASE}/{rel_path}"


# =============================================================================
# 1. Equipment Icons by Gear Tier (T1 ~ T6) × Slot (6 Slots = 36 Distinct Looks)
# =============================================================================
EQUIPMENT_ICONS: Dict[int, Dict[str, str]] = {
    1: {  # T1 青銅拓荒
        "weapon": _core("attacks/sword-human-short.png"),
        "helmet": _core("icons/helmet_leather-cap.png"),
        "armor": _core("icons/armor_leather.png"),
        "gloves": _core("attacks/fist-human.png"),
        "boots": _core("icons/sandals.png"),
        "accessory": _core("icons/stone_ring.png"),
    },
    2: {  # T2 精鋼白銀 (拓荒者套裝)
        "weapon": _core("attacks/sword-steel.png"),
        "helmet": _core("icons/helmet_bascinet.png"),
        "armor": _core("icons/armor-chain.png"),
        "gloves": _core("attacks/tekko.png"),
        "boots": _core("attacks/foot-shoe.png"),
        "accessory": _core("icons/jewelry_butterfly_pin.png"),
    },
    3: {  # T3 熔炎秘銀 (熔炎戰神套裝)
        "weapon": _core("attacks/sword-flaming.png"),
        "helmet": _core("icons/helmet_corinthian.png"),
        "armor": _core("icons/cuirass_muscled.png"),
        "gloves": _core("attacks/claws-fire-elemental.png"),
        "boots": _core("attacks/foot-boot.png"),
        "accessory": _core("icons/jewelry_necklace_amber.png"),
    },
    4: {  # T4 霜星精金 (霜星秘法套裝)
        "weapon": _core("attacks/staff-elven-star.png"),
        "helmet": _core("icons/circlet_winged.png"),
        "armor": _core("icons/tunic_elven.png"),
        "gloves": _core("attacks/touch-faerie.png"),
        "boots": _core("icons/boots_elven.png"),
        "accessory": _core("icons/ankh_necklace.png"),
    },
    5: {  # T5 龍裔熾晶 (龍裔支配者套裝)
        "weapon": _core("attacks/greatsword-human.png"),
        "helmet": _core("icons/helmet_crested.png"),
        "armor": _core("icons/steel_armor.png"),
        "gloves": _core("attacks/claws-drake.png"),
        "boots": _core("icons/greaves.png"),
        "accessory": _core("icons/skull_ring.png"),
    },
    6: {  # T6 星界虛空 (虛空星界套裝)
        "weapon": _core("attacks/sword-holy.png"),
        "helmet": _data("campaigns/Heir_To_The_Throne/images/icons/crown.png"),
        "armor": _core("icons/breastplate2.png"),
        "gloves": _core("attacks/claws-shadow.png"),
        "boots": _core("icons/boots_elven.png"),
        "accessory": _core("icons/jewelry_ring_prismatic.png"),
    },
}

SLOT_DEFAULT_ICONS: Dict[str, str] = {
    "weapon": _core("attacks/longsword.png"),
    "helmet": _core("icons/helmet_shiny.png"),
    "armor": _core("icons/breastplate.png"),
    "gloves": _core("attacks/fist-human.png"),
    "boots": _core("icons/greaves.png"),
    "accessory": _core("icons/ring_gold.png"),
}

# =============================================================================
# 2. Class Emblems (Small Icons) & 3-Stage Promotion Portraits (450-500px WebP)
# =============================================================================
CLASS_ICONS: Dict[str, str] = {
    "swordsman": _core("attacks/greatsword-human.png"),
    "mage": _core("attacks/staff-elven-star.png"),
    "ranger": _core("attacks/bow-elven-magic.png"),
    "paladin": _core("icons/shield_polished.png"),
}

CLASS_PORTRAITS: Dict[str, Dict[int, str]] = {
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
# 3. Dungeon Bosses, World Bosses & Endless Abyss Guardian Portraits
# =============================================================================
DUNGEON_BOSS_PORTRAITS: Dict[str, str] = {
    "goblin_woods": _core("portraits/goblins/rouser.webp"),
    "undead_crypt": _core("portraits/undead/ancient-lich.webp"),
    "frost_cavern": _core("portraits/monsters/wyvern.webp"),
    "obsidian_fortress": _core("portraits/monsters/fire_guardian.webp"),
    "sunken_temple": _core("portraits/monsters/kraken.webp"),
    "crimson_castle": _core("portraits/undead/death-knight.webp"),
    "dragon_sanctum": _core("portraits/monsters/fire-dragon.webp"),
    "void_corridor": _core("portraits/undead/nightgaunt.webp"),
}

WORLD_BOSS_PORTRAITS: Dict[str, str] = {
    "abyss_wyrm": _core("portraits/drakes/inferno.webp"),
    "star_titan": _core("portraits/trolls/troll-hero.webp"),
    "void_empress": _core("portraits/elves/sylph.webp"),
    "crimson_phoenix": _core("portraits/monsters/fire_wraith_A.webp"),
}

ABYSS_GUARDIAN_PORTRAITS: List[str] = [
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
# 4. Mining Zones, Pickaxes, Ores, Materials & Consumables
# =============================================================================
MINE_ZONE_BANNERS: Dict[str, str] = {
    "emerald_pit": _core("story/landscape-hills-01.webp"),
    "obsidian_cavern": _core("story/landscape-mountains-01.webp"),
    "crystal_grotto": _core("story/landscape-mountains-03.webp"),
    "mithril_abyss": _core("story/grim-altar.jpg"),
    "molten_vein": _core("story/landscape-lava.webp"),
    "astral_mantle": _core("story/landscape-mountains-05.webp"),
}

PICKAXE_ICONS: Dict[int, str] = {
    1: _core("attacks/pick-axe.png"),
    2: _core("attacks/pick-axe.png"),
    3: _core("attacks/hammer.png"),
    4: _core("attacks/hammer-dwarven.png"),
    5: _core("attacks/hammer-dwarven-runic.png"),
    6: _core("items/hammer-runic.png"),
    7: _core("attacks/lightning.png"),
    8: _core("attacks/lightbeam.png"),
}

ITEM_ICONS: Dict[str, str] = {
    # Ores
    "copper_ore": _core("items/rock.png"),
    "iron_ore": _core("attacks/rock_thrown.png"),
    "silver_ore": _core("icons/coins_copper.png"),
    "magic_crystal": _core("items/ball-blue.png"),
    "mithril_ore": _core("attacks/iceball.png"),
    "adamantite_ore": _core("items/ball-magenta.png"),
    "dragon_crystal": _core("attacks/fireball.png"),
    "astral_ore": _core("attacks/faerie-fire.png"),
    "void_ether": _core("attacks/dark-missile.png"),
    # Upgrade & Boss Materials
    "enhance_stone": _core("items/ball-blue.png"),
    "adv_enhance_stone": _core("attacks/lightbeam.png"),
    "protect_scroll": _core("icons/scroll_red.png"),
    "boss_essence": _core("attacks/curse.png"),
    "mythic_core": _core("attacks/fire-blast.png"),
    # Consumables & Keys
    "hp_potion_s": _core("icons/potion_red_small.png"),
    "hp_potion_m": _core("icons/potion_red_medium.png"),
    "hp_potion_l": _core("items/holy-water.png"),
    "stamina_elixir": _core("icons/potion_green_medium.png"),
    "relic_key": _core("icons/key_silver.png"),
    "class_emblem": _core("misc/laurel.png"),
}

# =============================================================================
# 5. Expeditions, Shop Tabs, Leaderboards & General UI Artwork
# =============================================================================
EXPEDITION_BANNERS: Dict[str, str] = {
    "forest_patrol": _core("story/wesmere.webp"),
    "ancient_mine_survey": _core("story/landscape-mountains-02.webp"),
    "mist_ruins": _core("story/swamp-01.webp"),
    "astral_rift_expedition": _core("story/landscape-mountains-04.webp"),
}

SHOP_TAB_ICONS: Dict[str, str] = {
    "supply": _core("items/gold-coins-large.png"),
    "mystery": _core("items/ball-magenta.png"),
    "gacha": _core("items/chest.png"),
    "sell": _core("icons/coins_copper.png"),
}

LEADERBOARD_ICONS: Dict[str, str] = {
    "power": _core("icons/crossed_sword_and_hammer.png"),
    "level": _core("misc/laurel.png"),
    "abyss": _core("portraits/undead/nightgaunt.webp"),
    "gold": _core("items/gold-coins-large.png"),
    "mining": _core("attacks/pick-axe.png"),
    "boss": _core("portraits/monsters/fire-dragon.webp"),
}

UI_ASSETS: Dict[str, str] = {
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
}


# =============================================================================
# Public Helper Getters (Safe Fallbacks Guaranteed)
# =============================================================================
def get_equipment_image_url(tier: int, slot: str) -> str:
    """Return the RPG artwork URL for an equipment item by tier (1..6) and slot."""
    clamped_tier = max(1, min(6, int(tier)))
    tier_map = EQUIPMENT_ICONS.get(clamped_tier, EQUIPMENT_ICONS[1])
    return tier_map.get(slot, SLOT_DEFAULT_ICONS.get(slot, SLOT_DEFAULT_ICONS["weapon"]))


def get_slot_icon_url(slot: str) -> str:
    return SLOT_DEFAULT_ICONS.get(slot, SLOT_DEFAULT_ICONS["weapon"])


def get_class_icon_url(class_id: str) -> str:
    return CLASS_ICONS.get(class_id, CLASS_ICONS["swordsman"])


def get_class_portrait_url(class_id: str, promo_tier: int = 1) -> str:
    clamped = max(1, min(3, int(promo_tier)))
    tiers = CLASS_PORTRAITS.get(class_id, CLASS_PORTRAITS["swordsman"])
    return tiers.get(clamped, tiers[1])


def get_dungeon_boss_portrait_url(dungeon_id: str) -> str:
    return DUNGEON_BOSS_PORTRAITS.get(dungeon_id, DUNGEON_BOSS_PORTRAITS["goblin_woods"])


def get_world_boss_portrait_url(template_id: str) -> str:
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
    return ITEM_ICONS.get(item_id, UI_ASSETS["materials_icon"])


def get_expedition_banner_url(expedition_id: str) -> str:
    return EXPEDITION_BANNERS.get(expedition_id, UI_ASSETS["expedition_default_banner"])


def get_shop_tab_icon_url(tab: str) -> str:
    return SHOP_TAB_ICONS.get(tab, SHOP_TAB_ICONS["supply"])


def get_leaderboard_icon_url(category: str) -> str:
    return LEADERBOARD_ICONS.get(category, LEADERBOARD_ICONS["power"])


def get_ui_asset_url(key: str) -> str:
    return UI_ASSETS.get(key, UI_ASSETS["combat_swords"])


def all_asset_urls() -> List[str]:
    """Return every unique asset URL registered in this module (used for verification/tests)."""
    urls = set()
    for tier_map in EQUIPMENT_ICONS.values():
        urls.update(tier_map.values())
    urls.update(SLOT_DEFAULT_ICONS.values())
    urls.update(CLASS_ICONS.values())
    for tier_map in CLASS_PORTRAITS.values():
        urls.update(tier_map.values())
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
    return sorted(urls)
