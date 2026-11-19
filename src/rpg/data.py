"""Static game data tables for the val-dc persistent RPG."""

from typing import Any, Dict, List, Tuple

# =============================================================================
# Core Constants
# =============================================================================
MAX_LEVEL = 100
STAMINA_REGEN_SECONDS = 240  # 1 stamina every 4 minutes
MINE_STAMINA_COST = 5
MINE_COOLDOWN_SECONDS = 3
BOSS_STAMINA_COST = 8
BOSS_COOLDOWN_SECONDS = 20
ABYSS_STAMINA_COST = 10
MAX_ENHANCE_LEVEL = 15
MYSTERY_SHOP_REFRESH_SECONDS = 6 * 3600  # Refreshes every 6 hours
MAX_EQUIPMENT_CAPACITY = 80

# =============================================================================
# Rarities & Equipment Slots
# =============================================================================
RARITIES: Dict[str, Dict[str, Any]] = {
    "common": {
        "name": "普通",
        "emoji": "⬜",
        "color": 0x95A5A6,
        "mult": 1.00,
        "affix_range": (0, 1),
        "sell_mult": 1.0,
        "dismantle_stones": 1,
        "order": 1,
    },
    "uncommon": {
        "name": "精良",
        "emoji": "🟩",
        "color": 0x2ECC71,
        "mult": 1.25,
        "affix_range": (1, 1),
        "sell_mult": 1.8,
        "dismantle_stones": 2,
        "order": 2,
    },
    "rare": {
        "name": "稀有",
        "emoji": "🟦",
        "color": 0x3498DB,
        "mult": 1.55,
        "affix_range": (1, 2),
        "sell_mult": 3.2,
        "dismantle_stones": 4,
        "order": 3,
    },
    "epic": {
        "name": "史詩",
        "emoji": "🟪",
        "color": 0x9B59B6,
        "mult": 1.95,
        "affix_range": (2, 2),
        "sell_mult": 6.0,
        "dismantle_stones": 8,
        "order": 4,
    },
    "legendary": {
        "name": "傳說",
        "emoji": "🟧",
        "color": 0xF39C12,
        "mult": 2.50,
        "affix_range": (3, 3),
        "sell_mult": 12.0,
        "dismantle_stones": 16,
        "order": 5,
    },
    "mythic": {
        "name": "神話",
        "emoji": "🟥",
        "color": 0xE74C3C,
        "mult": 3.25,
        "affix_range": (3, 4),
        "sell_mult": 25.0,
        "dismantle_stones": 32,
        "order": 6,
    },
}

RARITY_ORDER: List[str] = [
    "common",
    "uncommon",
    "rare",
    "epic",
    "legendary",
    "mythic",
]

SLOTS: Dict[str, Dict[str, str]] = {
    "weapon": {"name": "武器", "emoji": "⚔️"},
    "helmet": {"name": "頭盔", "emoji": "🪖"},
    "armor": {"name": "護甲", "emoji": "🛡️"},
    "gloves": {"name": "護手", "emoji": "🧤"},
    "boots": {"name": "戰靴", "emoji": "🥾"},
    "accessory": {"name": "飾品", "emoji": "💍"},
}

SLOT_ORDER: List[str] = ["weapon", "helmet", "armor", "gloves", "boots", "accessory"]

# =============================================================================
# Classes & 3-Stage Promotions
# =============================================================================
CLASSES: Dict[str, Dict[str, Any]] = {
    "swordsman": {
        "name": "劍士",
        "emoji": "⚔️",
        "desc": "攻防均衡的近戰勇者，具備穩定吸血與破甲爆發，適合穩健推進各類副本。",
        "tiers": {
            1: "見習劍士",
            2: "烈焰劍聖",
            3: "星辰劍帝",
        },
        "base": {"hp": 145, "mp": 60, "atk": 24, "def": 14, "crit": 0.10, "crit_dmg": 1.60, "dodge": 0.05},
        "per_level": {"hp": 22, "mp": 4, "atk": 4.4, "def": 2.6},
        "passive": {
            1: {"lifesteal": 0.05},
            2: {"lifesteal": 0.08, "atk_pct": 0.08},
            3: {"lifesteal": 0.12, "atk_pct": 0.15, "hp_pct": 0.10},
        },
        "skill": {
            "name": "裂空斬",
            "mp": 18,
            "desc": "造成 175% 攻擊傷害，並使敵人破甲（防禦 -20%）持續 2 回合。",
        },
        "ultimate": {
            "name": "星殞連斬",
            "mp": 35,
            "cooldown": 3,
            "desc": "發動 3 段斬擊造成 275% 攻擊傷害，並回復 15% 最大生命。",
        },
    },
    "mage": {
        "name": "法師",
        "emoji": "🔮",
        "desc": "掌握星界秘法的高爆發輸出，技能倍率極高且可貫穿敵方防禦。",
        "tiers": {
            1: "秘法學徒",
            2: "大魔導師",
            3: "虛空星界使",
        },
        "base": {"hp": 115, "mp": 95, "atk": 28, "def": 10, "crit": 0.12, "crit_dmg": 1.75, "dodge": 0.05},
        "per_level": {"hp": 16, "mp": 7, "atk": 5.2, "def": 1.9},
        "passive": {
            1: {"skill_dmg": 0.20},
            2: {"skill_dmg": 0.28, "crit_dmg": 0.20},
            3: {"skill_dmg": 0.38, "crit_dmg": 0.35, "atk_pct": 0.12},
        },
        "skill": {
            "name": "隕星爆裂",
            "mp": 22,
            "desc": "造成 215% 攻擊傷害，並無視敵方 25% 防禦。",
        },
        "ultimate": {
            "name": "超新星審判",
            "mp": 40,
            "cooldown": 3,
            "desc": "降下星界爆破造成 320% 攻擊傷害，並附加 2 回合灼燒（每回合 35% 攻擊傷害）。",
        },
    },
    "ranger": {
        "name": "遊俠",
        "emoji": "🏹",
        "desc": "迅捷致命的神射手，擁有高暴擊率、高閃避與額外掉寶加成。",
        "tiers": {
            1: "荒野獵手",
            2: "疾風神射手",
            3: "蒼穹逐星者",
        },
        "base": {"hp": 125, "mp": 70, "atk": 25, "def": 11, "crit": 0.20, "crit_dmg": 1.70, "dodge": 0.12},
        "per_level": {"hp": 18, "mp": 5, "atk": 4.7, "def": 2.1},
        "passive": {
            1: {"drop_bonus": 0.08},
            2: {"drop_bonus": 0.14, "crit_rate": 0.05, "dodge": 0.04},
            3: {"drop_bonus": 0.22, "crit_rate": 0.10, "dodge": 0.08, "crit_dmg": 0.25},
        },
        "skill": {
            "name": "連珠箭雨",
            "mp": 16,
            "desc": "連射 3 箭（每箭 68% 攻擊傷害），每箭獨立判定暴擊。",
        },
        "ultimate": {
            "name": "致命狙擊",
            "mp": 32,
            "cooldown": 3,
            "desc": "必定暴擊的 245% 攻擊穿刺射擊，並使自身閃避 +25% 持續 2 回合。",
        },
    },
    "paladin": {
        "name": "聖騎士",
        "emoji": "🛡️",
        "desc": "銅牆鐵壁的聖光守護者，擅長護盾、治療與防禦轉傷害，越級挑戰首選。",
        "tiers": {
            1: "見習騎士",
            2: "聖光守護者",
            3: "永恆聖輝王",
        },
        "base": {"hp": 180, "mp": 70, "atk": 20, "def": 20, "crit": 0.08, "crit_dmg": 1.55, "dodge": 0.03},
        "per_level": {"hp": 28, "mp": 5, "atk": 3.7, "def": 3.6},
        "passive": {
            1: {"dmg_reduction": 0.10},
            2: {"dmg_reduction": 0.14, "def_pct": 0.12, "hp_pct": 0.10},
            3: {"dmg_reduction": 0.20, "def_pct": 0.22, "hp_pct": 0.20},
        },
        "skill": {
            "name": "聖光審判",
            "mp": 18,
            "desc": "造成 155% 攻擊 + 45% 防禦真實傷害，並獲得 20% 最大生命的聖光護盾。",
        },
        "ultimate": {
            "name": "神聖庇護",
            "mp": 34,
            "cooldown": 3,
            "desc": "回復 35% 最大生命、獲得 30% 最大生命護盾，並對敵人造成 210% 攻擊反擊傷害。",
        },
    },
}

PROMOTION_REQUIREMENTS: Dict[int, Dict[str, Any]] = {
    2: {"min_level": 30, "gold": 5000, "materials": {"mithril_ore": 15, "boss_essence": 5}},
    3: {"min_level": 70, "gold": 35000, "materials": {"dragon_crystal": 20, "boss_essence": 20}},
}

# =============================================================================
# Items (Ores, Boss Materials, Consumables, Upgrade Materials)
# =============================================================================
ITEMS: Dict[str, Dict[str, Any]] = {
    # --- Ores ---
    "copper_ore": {"name": "銅礦石", "emoji": "🪨", "category": "ore", "sell": 18, "tier": 1, "desc": "淺礦坑常見的基礎金屬礦石。"},
    "iron_ore": {"name": "鐵礦石", "emoji": "⛓️", "category": "ore", "sell": 36, "tier": 2, "desc": "鍛造精良裝備與礦鎬的重要原料。"},
    "silver_ore": {"name": "白銀礦", "emoji": "🥈", "category": "ore", "sell": 65, "tier": 2, "desc": "散發銀光的金屬，附魔與鍛造皆宜。"},
    "magic_crystal": {"name": "魔力水晶", "emoji": "💠", "category": "ore", "sell": 115, "tier": 3, "desc": "蘊含濃縮元素魔力的天然結晶。"},
    "mithril_ore": {"name": "秘銀礦", "emoji": "🔷", "category": "ore", "sell": 185, "tier": 4, "desc": "輕盈卻無比堅硬的傳奇金屬。"},
    "adamantite_ore": {"name": "精金礦", "emoji": "🟪", "category": "ore", "sell": 310, "tier": 5, "desc": "深淵地層淬鍊出的暗紫神金。"},
    "dragon_crystal": {"name": "龍血晶石", "emoji": "🔺", "category": "ore", "sell": 520, "tier": 5, "desc": "流淌炙熱龍息的熔核結晶。"},
    "astral_ore": {"name": "星界原礦", "emoji": "✨", "category": "ore", "sell": 860, "tier": 6, "desc": "來自星界裂隙的稀世原礦。"},
    "void_ether": {"name": "虛空以太晶", "emoji": "🌌", "category": "ore", "sell": 1450, "tier": 6, "desc": "蘊含宇宙本源能量的頂級神材。"},

    # --- Upgrade & Boss Materials ---
    "enhance_stone": {"name": "初級強化石", "emoji": "🔹", "category": "material", "sell": 80, "tier": 1, "desc": "用於裝備 +1 ~ +10 強化。"},
    "adv_enhance_stone": {"name": "星輝強化石", "emoji": "🌟", "category": "material", "sell": 350, "tier": 4, "desc": "用於裝備 +10 ~ +15 進階強化。"},
    "protect_scroll": {"name": "強化保護卷軸", "emoji": "📜", "category": "material", "sell": 500, "tier": 4, "desc": "裝備 +10 以上強化失敗時防止掉階。"},
    "boss_essence": {"name": "首領魂晶", "emoji": "💀", "category": "material", "sell": 220, "tier": 3, "desc": "副本與世界王掉落的強大魂晶，用於鍛造套裝與轉職。"},
    "mythic_core": {"name": "神話核心", "emoji": "❤️‍🔥", "category": "material", "sell": 1200, "tier": 6, "desc": "地獄副本、無盡深淵與世界王掉落的頂級核心。"},

    # --- Consumables & Keys ---
    "hp_potion_s": {"name": "小型生命藥水", "emoji": "🧪", "category": "consumable", "sell": 35, "heal_pct": 0.35, "heal_flat": 80, "desc": "戰鬥中使用，回復 35% 最大生命 (+80)。"},
    "hp_potion_m": {"name": "中型生命藥水", "emoji": "⚗️", "category": "consumable", "sell": 120, "heal_pct": 0.55, "heal_flat": 250, "desc": "戰鬥中使用，回復 55% 最大生命 (+250)。"},
    "hp_potion_l": {"name": "星光神聖藥水", "emoji": "🏺", "category": "consumable", "sell": 320, "heal_pct": 0.85, "heal_flat": 650, "desc": "戰鬥中使用，回復 85% 最大生命 (+650) 並回復 30 MP。"},
    "stamina_elixir": {"name": "體力恢復劑", "emoji": "⚡", "category": "consumable", "sell": 150, "stamina": 50, "desc": "使用後立即回復 50 點體力。"},
    "relic_key": {"name": "星界秘寶鑰匙", "emoji": "🗝️", "category": "key", "sell": 400, "desc": "可免費開啟一次「星界秘寶箱」（取代 100 星鑽）。"},
    "class_emblem": {"name": "轉職徽章", "emoji": "🎖️", "category": "consumable", "sell": 600, "desc": "可於 `/class` 自由轉換職業（保留轉職階級）。"},
}

# =============================================================================
# Pickaxes (T1 ~ T8)
# =============================================================================
PICKAXES: Dict[int, Dict[str, Any]] = {
    1: {
        "name": "新手木鎬",
        "emoji": "🪵",
        "yield_mult": 1.0,
        "rare_bonus": 0.00,
        "double_chance": 0.05,
        "gold": 0,
        "materials": {},
    },
    2: {
        "name": "精鋼礦鎬",
        "emoji": "⛏️",
        "yield_mult": 1.25,
        "rare_bonus": 0.06,
        "double_chance": 0.10,
        "gold": 600,
        "materials": {"copper_ore": 18, "iron_ore": 6},
    },
    3: {
        "name": "銀紋共振鎬",
        "emoji": "🥈",
        "yield_mult": 1.55,
        "rare_bonus": 0.12,
        "double_chance": 0.15,
        "gold": 2500,
        "materials": {"iron_ore": 25, "silver_ore": 18},
    },
    4: {
        "name": "水晶秘法鎬",
        "emoji": "💠",
        "yield_mult": 1.90,
        "rare_bonus": 0.18,
        "double_chance": 0.20,
        "gold": 7500,
        "materials": {"magic_crystal": 28, "mithril_ore": 15},
    },
    5: {
        "name": "精金破岩鎬",
        "emoji": "🟪",
        "yield_mult": 2.35,
        "rare_bonus": 0.25,
        "double_chance": 0.26,
        "gold": 22000,
        "materials": {"mithril_ore": 35, "adamantite_ore": 22, "boss_essence": 6},
    },
    6: {
        "name": "龍晶鑽頭鎬",
        "emoji": "🔥",
        "yield_mult": 2.90,
        "rare_bonus": 0.32,
        "double_chance": 0.32,
        "gold": 60000,
        "materials": {"adamantite_ore": 40, "dragon_crystal": 30, "boss_essence": 15},
    },
    7: {
        "name": "星界裂空鎬",
        "emoji": "✨",
        "yield_mult": 3.60,
        "rare_bonus": 0.40,
        "double_chance": 0.38,
        "gold": 150000,
        "materials": {"dragon_crystal": 45, "astral_ore": 35, "mythic_core": 6},
    },
    8: {
        "name": "永恆創世神鎬",
        "emoji": "🌌",
        "yield_mult": 4.50,
        "rare_bonus": 0.50,
        "double_chance": 0.48,
        "gold": 400000,
        "materials": {"astral_ore": 60, "void_ether": 45, "mythic_core": 18},
    },
}

# =============================================================================
# Mining Zones (6 Progressive Zones)
# =============================================================================
MINE_ZONES: List[Dict[str, Any]] = [
    {
        "id": "emerald_pit",
        "name": "翠綠淺礦坑",
        "emoji": "🪨",
        "min_level": 1,
        "min_pickaxe": 1,
        "exp": (18, 28),
        "gold": (35, 65),
        "drops": [
            ("copper_ore", 2, 4, 1.00),
            ("iron_ore", 1, 2, 0.42),
            ("enhance_stone", 1, 1, 0.14),
        ],
    },
    {
        "id": "obsidian_cavern",
        "name": "黑岩深礦洞",
        "emoji": "⛰️",
        "min_level": 10,
        "min_pickaxe": 2,
        "exp": (48, 72),
        "gold": (90, 155),
        "drops": [
            ("iron_ore", 2, 4, 1.00),
            ("silver_ore", 1, 3, 0.65),
            ("magic_crystal", 1, 1, 0.20),
            ("enhance_stone", 1, 2, 0.22),
        ],
    },
    {
        "id": "crystal_grotto",
        "name": "晶瑩水晶窟",
        "emoji": "💎",
        "min_level": 22,
        "min_pickaxe": 3,
        "exp": (115, 165),
        "gold": (210, 340),
        "drops": [
            ("silver_ore", 2, 4, 0.85),
            ("magic_crystal", 2, 4, 1.00),
            ("mithril_ore", 1, 2, 0.45),
            ("enhance_stone", 1, 3, 0.30),
        ],
    },
    {
        "id": "mithril_abyss",
        "name": "秘銀幽暗淵",
        "emoji": "🌌",
        "min_level": 38,
        "min_pickaxe": 4,
        "exp": (250, 360),
        "gold": (480, 740),
        "drops": [
            ("mithril_ore", 2, 4, 1.00),
            ("adamantite_ore", 1, 3, 0.55),
            ("enhance_stone", 2, 4, 0.35),
            ("adv_enhance_stone", 1, 1, 0.12),
        ],
    },
    {
        "id": "molten_vein",
        "name": "熔核龍晶脈",
        "emoji": "🔥",
        "min_level": 58,
        "min_pickaxe": 5,
        "exp": (520, 740),
        "gold": (1050, 1580),
        "drops": [
            ("adamantite_ore", 2, 4, 1.00),
            ("dragon_crystal", 2, 3, 0.72),
            ("astral_ore", 1, 2, 0.25),
            ("adv_enhance_stone", 1, 2, 0.24),
        ],
    },
    {
        "id": "astral_mantle",
        "name": "星界原初脈",
        "emoji": "✨",
        "min_level": 80,
        "min_pickaxe": 6,
        "exp": (1050, 1480),
        "gold": (2200, 3400),
        "drops": [
            ("dragon_crystal", 2, 4, 0.85),
            ("astral_ore", 2, 4, 1.00),
            ("void_ether", 1, 3, 0.58),
            ("adv_enhance_stone", 2, 3, 0.35),
            ("mythic_core", 1, 1, 0.08),
        ],
    },
]

MINE_ZONES_BY_ID: Dict[str, Dict[str, Any]] = {z["id"]: z for z in MINE_ZONES}

# =============================================================================
# Equipment Sets & Affixes
# =============================================================================
EQUIPMENT_SETS: Dict[str, Dict[str, Any]] = {
    "pioneer": {
        "name": "拓荒者套裝",
        "emoji": "🌿",
        "bonuses": {
            2: {"hp_pct": 0.12, "exp_bonus": 0.10},
            4: {"atk_pct": 0.15, "mine_bonus": 0.15},
        },
        "desc_2": "生命 +12%、經驗獲取 +10%",
        "desc_4": "攻擊 +15%、挖礦產量 +15%",
    },
    "inferno": {
        "name": "熔炎戰神套裝",
        "emoji": "🔥",
        "bonuses": {
            2: {"atk_pct": 0.18, "crit_rate": 0.06},
            4: {"crit_dmg": 0.30, "lifesteal": 0.05},
        },
        "desc_2": "攻擊 +18%、暴擊率 +6%",
        "desc_4": "暴擊傷害 +30%、吸血 +5%",
    },
    "froststar": {
        "name": "霜星秘法套裝",
        "emoji": "❄️",
        "bonuses": {
            2: {"def_pct": 0.20, "hp_pct": 0.15},
            4: {"atk_pct": 0.25, "dodge": 0.08, "skill_dmg": 0.15},
        },
        "desc_2": "防禦 +20%、生命 +15%",
        "desc_4": "攻擊 +25%、閃避 +8%、技能傷害 +15%",
    },
    "dragonlord": {
        "name": "龍裔支配者套裝",
        "emoji": "🐉",
        "bonuses": {
            2: {"atk_pct": 0.20, "def_pct": 0.20, "hp_pct": 0.20},
            4: {"crit_rate": 0.12, "crit_dmg": 0.45, "lifesteal": 0.06},
        },
        "desc_2": "全基礎屬性 +20%",
        "desc_4": "暴擊率 +12%、暴擊傷害 +45%、吸血 +6%",
    },
    "astral_void": {
        "name": "虛空星界套裝",
        "emoji": "🌌",
        "bonuses": {
            2: {"atk_pct": 0.28, "def_pct": 0.28, "hp_pct": 0.28},
            4: {"atk_pct": 0.35, "crit_rate": 0.15, "crit_dmg": 0.60, "drop_bonus": 0.20},
        },
        "desc_2": "全基礎屬性 +28%",
        "desc_4": "攻擊 +35%、暴擊率 +15%、暴擊傷害 +60%、掉寶率 +20%",
    },
}

AFFIX_DEFS: Dict[str, Dict[str, Any]] = {
    "atk_pct": {"name": "攻擊力", "fmt": "pct", "base_range": (0.03, 0.08)},
    "def_pct": {"name": "防禦力", "fmt": "pct", "base_range": (0.03, 0.08)},
    "hp_pct": {"name": "最大生命", "fmt": "pct", "base_range": (0.04, 0.10)},
    "crit_rate": {"name": "暴擊率", "fmt": "pct", "base_range": (0.02, 0.05)},
    "crit_dmg": {"name": "暴擊傷害", "fmt": "pct", "base_range": (0.06, 0.16)},
    "dodge": {"name": "閃避率", "fmt": "pct", "base_range": (0.015, 0.04)},
    "lifesteal": {"name": "生命偷取", "fmt": "pct", "base_range": (0.01, 0.03)},
    "gold_bonus": {"name": "金幣掉落", "fmt": "pct", "base_range": (0.04, 0.12)},
    "exp_bonus": {"name": "經驗加成", "fmt": "pct", "base_range": (0.04, 0.12)},
    "mine_bonus": {"name": "挖礦產量", "fmt": "pct", "base_range": (0.04, 0.12)},
}

# Equipment Tiers (T1 ~ T6): defines base stats per slot & forging recipes
GEAR_TIERS: Dict[int, Dict[str, Any]] = {
    1: {
        "name": "青銅拓荒",
        "prefix": "青銅",
        "min_level": 1,
        "set_id": "",
        "scale": 1.0,
        "forge_gold": 350,
        "forge_materials": {"copper_ore": 12, "iron_ore": 4},
        "rarity_weights": [("common", 25), ("uncommon", 45), ("rare", 23), ("epic", 6), ("legendary", 1)],
    },
    2: {
        "name": "精鋼白銀",
        "prefix": "白銀",
        "min_level": 12,
        "set_id": "pioneer",
        "scale": 2.2,
        "forge_gold": 1400,
        "forge_materials": {"iron_ore": 18, "silver_ore": 12},
        "rarity_weights": [("uncommon", 30), ("rare", 45), ("epic", 19), ("legendary", 5), ("mythic", 1)],
    },
    3: {
        "name": "熔炎秘銀",
        "prefix": "熔炎",
        "min_level": 28,
        "set_id": "inferno",
        "scale": 4.4,
        "forge_gold": 5500,
        "forge_materials": {"magic_crystal": 20, "mithril_ore": 14, "boss_essence": 3},
        "rarity_weights": [("rare", 38), ("epic", 40), ("legendary", 18), ("mythic", 4)],
    },
    4: {
        "name": "霜星精金",
        "prefix": "霜星",
        "min_level": 48,
        "set_id": "froststar",
        "scale": 8.2,
        "forge_gold": 18000,
        "forge_materials": {"mithril_ore": 24, "adamantite_ore": 18, "boss_essence": 8},
        "rarity_weights": [("rare", 22), ("epic", 46), ("legendary", 25), ("mythic", 7)],
    },
    5: {
        "name": "龍裔熾晶",
        "prefix": "龍裔",
        "min_level": 70,
        "set_id": "dragonlord",
        "scale": 14.5,
        "forge_gold": 52000,
        "forge_materials": {"adamantite_ore": 26, "dragon_crystal": 22, "boss_essence": 14, "mythic_core": 2},
        "rarity_weights": [("epic", 42), ("legendary", 42), ("mythic", 16)],
    },
    6: {
        "name": "星界虛空",
        "prefix": "星界",
        "min_level": 88,
        "set_id": "astral_void",
        "scale": 24.0,
        "forge_gold": 140000,
        "forge_materials": {"astral_ore": 30, "void_ether": 22, "boss_essence": 20, "mythic_core": 6},
        "rarity_weights": [("epic", 24), ("legendary", 48), ("mythic", 28)],
    },
}

SLOT_BASE_STATS: Dict[str, Dict[str, int]] = {
    "weapon": {"hp": 10, "mp": 6, "atk": 18, "def": 2},
    "helmet": {"hp": 42, "mp": 10, "atk": 4, "def": 9},
    "armor": {"hp": 72, "mp": 6, "atk": 3, "def": 14},
    "gloves": {"hp": 26, "mp": 6, "atk": 11, "def": 6},
    "boots": {"hp": 36, "mp": 8, "atk": 6, "def": 8},
    "accessory": {"hp": 30, "mp": 18, "atk": 10, "def": 5},
}

SLOT_NAMES_BY_TIER: Dict[int, Dict[str, str]] = {
    1: {"weapon": "青銅長刃", "helmet": "青銅戰盔", "armor": "青銅胸甲", "gloves": "青銅護手", "boots": "青銅輕靴", "accessory": "旅人護符"},
    2: {"weapon": "拓荒白銀劍", "helmet": "拓荒頭盔", "armor": "拓荒鎖甲", "gloves": "拓荒戰手套", "boots": "拓荒疾靴", "accessory": "拓荒星紋戒"},
    3: {"weapon": "熔炎破滅刃", "helmet": "熔炎戰神盔", "armor": "熔炎重鎧", "gloves": "熔炎拳鎧", "boots": "熔炎烈焰靴", "accessory": "炎核吊墜"},
    4: {"weapon": "霜星秘法杖刃", "helmet": "霜星冠冕", "armor": "霜星符文袍甲", "gloves": "霜星靈紋手", "boots": "霜星踏空靴", "accessory": "極寒星晶戒"},
    5: {"weapon": "龍裔滅世大劍", "helmet": "龍裔角盔", "armor": "龍裔鱗神鎧", "gloves": "龍裔龍爪護手", "boots": "龍裔翔空戰靴", "accessory": "古龍之心墜飾"},
    6: {"weapon": "虛空星界聖器", "helmet": "星界王冠", "armor": "星界永恆神鎧", "gloves": "星界支配護手", "boots": "星界躍遷戰靴", "accessory": "宇宙本源星環"},
}

# Enhancement table: target_level -> (success_rate, gold_mult, stone_item, stone_qty, ore_qty)
ENHANCE_TABLE: Dict[int, Dict[str, Any]] = {
    1: {"rate": 1.00, "gold": 120, "stone": "enhance_stone", "stone_qty": 1, "downgrade": False},
    2: {"rate": 1.00, "gold": 220, "stone": "enhance_stone", "stone_qty": 2, "downgrade": False},
    3: {"rate": 1.00, "gold": 360, "stone": "enhance_stone", "stone_qty": 3, "downgrade": False},
    4: {"rate": 1.00, "gold": 550, "stone": "enhance_stone", "stone_qty": 4, "downgrade": False},
    5: {"rate": 1.00, "gold": 820, "stone": "enhance_stone", "stone_qty": 5, "downgrade": False},
    6: {"rate": 0.85, "gold": 1250, "stone": "enhance_stone", "stone_qty": 6, "downgrade": False},
    7: {"rate": 0.75, "gold": 1800, "stone": "enhance_stone", "stone_qty": 8, "downgrade": False},
    8: {"rate": 0.65, "gold": 2600, "stone": "enhance_stone", "stone_qty": 10, "downgrade": False},
    9: {"rate": 0.55, "gold": 3800, "stone": "enhance_stone", "stone_qty": 12, "downgrade": False},
    10: {"rate": 0.45, "gold": 5600, "stone": "enhance_stone", "stone_qty": 15, "downgrade": False},
    11: {"rate": 0.38, "gold": 8500, "stone": "adv_enhance_stone", "stone_qty": 4, "downgrade": True},
    12: {"rate": 0.30, "gold": 13000, "stone": "adv_enhance_stone", "stone_qty": 6, "downgrade": True},
    13: {"rate": 0.24, "gold": 20000, "stone": "adv_enhance_stone", "stone_qty": 9, "downgrade": True},
    14: {"rate": 0.18, "gold": 32000, "stone": "adv_enhance_stone", "stone_qty": 12, "downgrade": True},
    15: {"rate": 0.12, "gold": 50000, "stone": "adv_enhance_stone", "stone_qty": 16, "downgrade": True},
}

# =============================================================================
# 8 Progressive Dungeons × 3 Difficulties
# =============================================================================
DIFFICULTIES: Dict[str, Dict[str, Any]] = {
    "normal": {
        "name": "普通",
        "emoji": "🟢",
        "stat_mult": 1.0,
        "reward_mult": 1.0,
        "stamina": 12,
        "gear_chance": 0.45,
        "rarity_shift": 0,
    },
    "hard": {
        "name": "困難",
        "emoji": "🟠",
        "stat_mult": 1.75,
        "reward_mult": 1.9,
        "stamina": 16,
        "gear_chance": 0.70,
        "rarity_shift": 1,
    },
    "hell": {
        "name": "地獄",
        "emoji": "🔴",
        "stat_mult": 2.95,
        "reward_mult": 3.3,
        "stamina": 20,
        "gear_chance": 0.95,
        "rarity_shift": 2,
    },
}

DUNGEONS: List[Dict[str, Any]] = [
    {
        "id": "goblin_woods",
        "name": "哥布林密林",
        "emoji": "🌲",
        "rec_level": 1,
        "gear_tier": 1,
        "boss_name": "哥布林督軍・格魯克",
        "boss_emoji": "👺",
        "telegraph_name": "狂暴重槌",
        "hp": 220,
        "atk": 22,
        "def": 8,
        "exp": 95,
        "gold": 240,
        "first_clear_gems": 35,
        "drops": [("copper_ore", 2, 5, 0.8), ("enhance_stone", 1, 2, 0.65), ("hp_potion_s", 1, 2, 0.5)],
    },
    {
        "id": "undead_crypt",
        "name": "亡靈古墓",
        "emoji": "🦴",
        "rec_level": 12,
        "gear_tier": 2,
        "boss_name": "骸骨領主・莫德雷",
        "boss_emoji": "💀",
        "telegraph_name": "亡靈收割",
        "hp": 680,
        "atk": 58,
        "def": 24,
        "exp": 320,
        "gold": 680,
        "first_clear_gems": 50,
        "drops": [("iron_ore", 3, 6, 0.8), ("silver_ore", 2, 4, 0.65), ("boss_essence", 1, 2, 0.6), ("enhance_stone", 2, 3, 0.7)],
    },
    {
        "id": "frost_cavern",
        "name": "永凍冰原洞窟",
        "emoji": "❄️",
        "rec_level": 25,
        "gear_tier": 3,
        "boss_name": "霜翼冰龍・弗洛斯特",
        "boss_emoji": "🐉",
        "telegraph_name": "絕對零度吐息",
        "hp": 1850,
        "atk": 135,
        "def": 56,
        "exp": 950,
        "gold": 1750,
        "first_clear_gems": 70,
        "drops": [("magic_crystal", 3, 6, 0.8), ("mithril_ore", 2, 4, 0.55), ("boss_essence", 2, 3, 0.75), ("enhance_stone", 3, 5, 0.8)],
    },
    {
        "id": "obsidian_fortress",
        "name": "黑曜熔岩要塞",
        "emoji": "🌋",
        "rec_level": 40,
        "gear_tier": 3,
        "boss_name": "炎魔鍛造師・卡爾薩斯",
        "boss_emoji": "👹",
        "telegraph_name": "熔岩滅世爆裂",
        "hp": 4200,
        "atk": 270,
        "def": 115,
        "exp": 2400,
        "gold": 4200,
        "first_clear_gems": 90,
        "drops": [("mithril_ore", 3, 6, 0.85), ("adamantite_ore", 2, 4, 0.55), ("boss_essence", 2, 4, 0.85), ("adv_enhance_stone", 1, 2, 0.35)],
    },
    {
        "id": "sunken_temple",
        "name": "沉沒海神殿",
        "emoji": "🌊",
        "rec_level": 55,
        "gear_tier": 4,
        "boss_name": "深海克拉肯・利維坦",
        "boss_emoji": "🐙",
        "telegraph_name": "滅世海嘯觸擊",
        "hp": 9200,
        "atk": 490,
        "def": 210,
        "exp": 5600,
        "gold": 9200,
        "first_clear_gems": 115,
        "drops": [("adamantite_ore", 3, 6, 0.85), ("dragon_crystal", 2, 4, 0.55), ("boss_essence", 3, 5, 0.9), ("adv_enhance_stone", 1, 3, 0.50)],
    },
    {
        "id": "crimson_castle",
        "name": "血月吸血鬼古堡",
        "emoji": "🏰",
        "rec_level": 70,
        "gear_tier": 5,
        "boss_name": "緋紅伯爵・德古拉",
        "boss_emoji": "🧛",
        "telegraph_name": "血月猩紅審判",
        "hp": 19500,
        "atk": 860,
        "def": 370,
        "exp": 12500,
        "gold": 19500,
        "first_clear_gems": 145,
        "drops": [("dragon_crystal", 3, 6, 0.85), ("astral_ore", 2, 4, 0.50), ("boss_essence", 4, 6, 0.95), ("mythic_core", 1, 1, 0.25)],
    },
    {
        "id": "dragon_sanctum",
        "name": "龍骨天穹聖殿",
        "emoji": "🐲",
        "rec_level": 85,
        "gear_tier": 5,
        "boss_name": "古代熾焰巨龍・巴哈姆特",
        "boss_emoji": "🔥",
        "telegraph_name": "天穹龍焰焚世",
        "hp": 38000,
        "atk": 1480,
        "def": 620,
        "exp": 26000,
        "gold": 38000,
        "first_clear_gems": 180,
        "drops": [("astral_ore", 3, 6, 0.9), ("void_ether", 2, 4, 0.55), ("adv_enhance_stone", 2, 4, 0.75), ("mythic_core", 1, 2, 0.45)],
    },
    {
        "id": "void_corridor",
        "name": "虛空裂隙・終焉迴廊",
        "emoji": "🌌",
        "rec_level": 95,
        "gear_tier": 6,
        "boss_name": "虛空星神化身・阿撒托斯",
        "boss_emoji": "👁️",
        "telegraph_name": "終焉星界坍縮",
        "hp": 72000,
        "atk": 2450,
        "def": 1050,
        "exp": 52000,
        "gold": 72000,
        "first_clear_gems": 250,
        "drops": [("astral_ore", 4, 8, 0.95), ("void_ether", 3, 6, 0.85), ("mythic_core", 1, 3, 0.65), ("protect_scroll", 1, 1, 0.20)],
    },
]

DUNGEONS_BY_ID: Dict[str, Dict[str, Any]] = {d["id"]: d for d in DUNGEONS}

# =============================================================================
# World Boss Templates (Rotating & Infinite Tier Scaling)
# =============================================================================
WORLD_BOSS_POOL: List[Dict[str, Any]] = [
    {"id": "abyss_wyrm", "name": "深淵噬界魔龍・尼德霍格", "emoji": "🐉", "base_hp": 50000, "base_atk": 160, "base_def": 65},
    {"id": "star_titan", "name": "星穹毀滅泰坦・克羅諾斯", "emoji": "🗿", "base_hp": 65000, "base_atk": 185, "base_def": 80},
    {"id": "void_empress", "name": "永恆虛空女皇・瑟拉菲娜", "emoji": "👑", "base_hp": 58000, "base_atk": 210, "base_def": 70},
    {"id": "crimson_phoenix", "name": "赤紅災厄鳳凰・不死鳥", "emoji": "🔥", "base_hp": 62000, "base_atk": 195, "base_def": 75},
]

# =============================================================================
# Permanent Supply Shop
# =============================================================================
SUPPLY_SHOP: List[Dict[str, Any]] = [
    {"id": "buy_hp_s", "item_id": "hp_potion_s", "qty": 3, "currency": "gold", "price": 240, "daily_limit": 0},
    {"id": "buy_hp_m", "item_id": "hp_potion_m", "qty": 3, "currency": "gold", "price": 850, "daily_limit": 0},
    {"id": "buy_hp_l", "item_id": "hp_potion_l", "qty": 2, "currency": "gold", "price": 1800, "daily_limit": 0},
    {"id": "buy_stamina", "item_id": "stamina_elixir", "qty": 1, "currency": "gold", "price": 1200, "daily_limit": 3},
    {"id": "buy_stone", "item_id": "enhance_stone", "qty": 5, "currency": "gold", "price": 1200, "daily_limit": 5},
    {"id": "buy_adv_stone", "item_id": "adv_enhance_stone", "qty": 2, "currency": "gold", "price": 4500, "daily_limit": 3},
    {"id": "buy_protect", "item_id": "protect_scroll", "qty": 1, "currency": "gems", "price": 45, "daily_limit": 5},
    {"id": "buy_key", "item_id": "relic_key", "qty": 1, "currency": "gems", "price": 90, "daily_limit": 3},
    {"id": "buy_emblem", "item_id": "class_emblem", "qty": 1, "currency": "gold", "price": 6000, "daily_limit": 1},
]

SUPPLY_SHOP_BY_ID: Dict[str, Dict[str, Any]] = {s["id"]: s for s in SUPPLY_SHOP}

# =============================================================================
# Daily Check-in 7-Day Cycle
# =============================================================================
DAILY_CHECKIN_REWARDS: List[Dict[str, Any]] = [
    {"day": 1, "gold": 600, "gems": 25, "items": {"hp_potion_s": 3}},
    {"day": 2, "gold": 1000, "gems": 30, "items": {"stamina_elixir": 1}},
    {"day": 3, "gold": 1500, "gems": 40, "items": {"enhance_stone": 6}},
    {"day": 4, "gold": 2200, "gems": 50, "items": {"stamina_elixir": 2, "hp_potion_m": 3}},
    {"day": 5, "gold": 3200, "gems": 65, "items": {"enhance_stone": 10, "protect_scroll": 1}},
    {"day": 6, "gold": 4800, "gems": 80, "items": {"adv_enhance_stone": 3, "relic_key": 1}},
    {"day": 7, "gold": 8000, "gems": 180, "items": {"relic_key": 2, "protect_scroll": 1, "stamina_elixir": 2}},
]

# =============================================================================
# Daily & Weekly Quests
# =============================================================================
DAILY_QUESTS: List[Dict[str, Any]] = [
    {"id": "daily_mine", "name": "勤勞礦工", "desc": "前往礦場挖礦 5 次", "event": "mine", "target": 5, "gold": 800, "gems": 20, "exp": 200, "items": {"enhance_stone": 3}},
    {"id": "daily_dungeon", "name": "副本清道夫", "desc": "通關任意副本 2 次", "event": "dungeon_clear", "target": 2, "gold": 1400, "gems": 30, "exp": 450, "items": {"stamina_elixir": 1}},
    {"id": "daily_enhance", "name": "鐵匠常客", "desc": "強化裝備或鍛造 1 次", "event": "forge_or_enhance", "target": 1, "gold": 1000, "gems": 20, "exp": 250, "items": {"enhance_stone": 4}},
    {"id": "daily_boss", "name": "討伐先鋒", "desc": "挑戰世界王或無盡深淵 1 次", "event": "boss_or_abyss", "target": 1, "gold": 1200, "gems": 25, "exp": 350, "items": {"hp_potion_m": 2}},
]

WEEKLY_QUESTS: List[Dict[str, Any]] = [
    {"id": "weekly_mine", "name": "礦脈開拓大師", "desc": "本週累計挖礦 35 次", "event": "mine", "target": 35, "gold": 6500, "gems": 100, "exp": 2200, "items": {"adv_enhance_stone": 3}},
    {"id": "weekly_dungeon", "name": "百戰勇者", "desc": "本週累計通關副本 12 次", "event": "dungeon_clear", "target": 12, "gold": 9500, "gems": 130, "exp": 3600, "items": {"relic_key": 2}},
    {"id": "weekly_boss", "name": "世界王剋星", "desc": "本週挑戰世界王或無盡深淵 8 次", "event": "boss_or_abyss", "target": 8, "gold": 8000, "gems": 120, "exp": 3000, "items": {"protect_scroll": 2}},
]

ALL_QUESTS_BY_ID: Dict[str, Dict[str, Any]] = {
    q["id"]: q for q in (DAILY_QUESTS + WEEKLY_QUESTS)
}

# =============================================================================
# Timed Idle Expeditions (Restart-Safe Timestamp Progression)
# =============================================================================
EXPEDITIONS: List[Dict[str, Any]] = [
    {
        "id": "forest_patrol",
        "name": "森林邊境巡邏",
        "emoji": "🌲",
        "duration_sec": 3600,  # 1 hour
        "min_level": 1,
        "base_gold": 450,
        "base_exp": 260,
        "ore_pool": ["copper_ore", "iron_ore", "silver_ore"],
        "ore_qty": (4, 8),
        "gear_chance": 0.25,
    },
    {
        "id": "ancient_mine_survey",
        "name": "古代礦區探勘",
        "emoji": "⛰️",
        "duration_sec": 3 * 3600,  # 3 hours
        "min_level": 10,
        "base_gold": 1400,
        "base_exp": 850,
        "ore_pool": ["iron_ore", "silver_ore", "magic_crystal", "mithril_ore"],
        "ore_qty": (8, 15),
        "gear_chance": 0.50,
    },
    {
        "id": "mist_ruins",
        "name": "迷霧遺跡遠征",
        "emoji": "🏛️",
        "duration_sec": 6 * 3600,  # 6 hours
        "min_level": 25,
        "base_gold": 3400,
        "base_exp": 2100,
        "ore_pool": ["magic_crystal", "mithril_ore", "adamantite_ore", "dragon_crystal"],
        "ore_qty": (14, 24),
        "gear_chance": 0.75,
    },
    {
        "id": "astral_rift_expedition",
        "name": "星界裂隙深度調查",
        "emoji": "🌌",
        "duration_sec": 12 * 3600,  # 12 hours
        "min_level": 50,
        "base_gold": 8200,
        "base_exp": 5200,
        "ore_pool": ["adamantite_ore", "dragon_crystal", "astral_ore", "void_ether"],
        "ore_qty": (22, 36),
        "gear_chance": 1.00,
    },
]

EXPEDITIONS_BY_ID: Dict[str, Dict[str, Any]] = {e["id"]: e for e in EXPEDITIONS}

# =============================================================================
# Achievements & Titles (Account-Wide Permanent Bonuses!)
# =============================================================================
ACHIEVEMENTS: List[Dict[str, Any]] = [
    {"id": "ach_mine_10", "name": "初入礦坑", "title": "⛏️ 掘金學徒", "desc": "累計挖礦達 10 次", "gems": 30, "bonus": {"mine_bonus": 0.03}},
    {"id": "ach_mine_100", "name": "地脈掘進者", "title": "💎 礦脈獵人", "desc": "累計挖礦達 100 次", "gems": 100, "bonus": {"mine_bonus": 0.08}},
    {"id": "ach_mine_500", "name": "傳奇礦神", "title": "👑 傳奇礦神", "desc": "累計挖礦達 500 次", "gems": 250, "bonus": {"mine_bonus": 0.15, "gold_bonus": 0.05}},
    {"id": "ach_dungeon_1", "name": "初次凱旋", "title": "⚔️ 新星冒險者", "desc": "首次通關任意副本", "gems": 40, "bonus": {"atk_pct": 0.02}},
    {"id": "ach_dungeon_30", "name": "副本征服者", "title": "🏰 副本征服者", "desc": "累計通關副本達 30 次", "gems": 120, "bonus": {"atk_pct": 0.04, "drop_bonus": 0.05}},
    {"id": "ach_dungeon_150", "name": "百戰不殆", "title": "🔥 百戰霸主", "desc": "累計通關副本達 150 次", "gems": 280, "bonus": {"atk_pct": 0.07, "hp_pct": 0.07}},
    {"id": "ach_enhance_10", "name": "神兵初成", "title": "🔨 鍛造名匠", "desc": "將任意裝備強化至 +10", "gems": 150, "bonus": {"atk_pct": 0.05, "def_pct": 0.05}},
    {"id": "ach_enhance_15", "name": "登峰造極", "title": "🌟 鍛造宗師", "desc": "將任意裝備強化至 +15", "gems": 400, "bonus": {"atk_pct": 0.10, "def_pct": 0.10, "crit_dmg": 0.15}},
    {"id": "ach_abyss_10", "name": "深淵初探", "title": "🗼 深淵行者", "desc": "無盡深淵突破第 10 層", "gems": 80, "bonus": {"hp_pct": 0.05}},
    {"id": "ach_abyss_30", "name": "深淵征服者", "title": "🌌 深淵征服者", "desc": "無盡深淵突破第 30 層", "gems": 200, "bonus": {"atk_pct": 0.06, "crit_rate": 0.03}},
    {"id": "ach_abyss_60", "name": "星界審判官", "title": "⚡ 星界審判官", "desc": "無盡深淵突破第 60 層", "gems": 450, "bonus": {"atk_pct": 0.10, "crit_rate": 0.05, "crit_dmg": 0.20}},
    {"id": "ach_boss_kill_1", "name": "共鬥屠龍", "title": "🐉 屠龍勇者", "desc": "參與擊殺 1 次伺服器世界王", "gems": 100, "bonus": {"atk_pct": 0.04}},
    {"id": "ach_level_50", "name": "半百歷練", "title": "⭐ 資深戰士", "desc": "角色等級達到 Lv.50", "gems": 120, "bonus": {"exp_bonus": 0.06}},
    {"id": "ach_level_100", "name": "登頂巔峰", "title": "🏆 巔峰王者", "desc": "角色等級達到 Lv.100", "gems": 300, "bonus": {"atk_pct": 0.08, "def_pct": 0.08, "hp_pct": 0.08}},
    {"id": "ach_rebirth_1", "name": "星界飛升", "title": "✨ 星界飛升者", "desc": "完成首次轉生飛升", "gems": 350, "bonus": {"atk_pct": 0.08, "gold_bonus": 0.08, "exp_bonus": 0.08}},
    {"id": "ach_gold_100k", "name": "黃金大亨", "title": "💰 黃金大亨", "desc": "身上持有超過 100,000 金幣", "gems": 100, "bonus": {"gold_bonus": 0.08}},
    {"id": "ach_checkin_7", "name": "持之以恆", "title": "📅 永恆旅人", "desc": "累計簽到滿 7 天", "gems": 100, "bonus": {"exp_bonus": 0.05, "gold_bonus": 0.05}},
]

ACHIEVEMENTS_BY_ID: Dict[str, Dict[str, Any]] = {a["id"]: a for a in ACHIEVEMENTS}


def exp_needed_for_level(level: int) -> int:
    """Experience required to advance from `level` to `level + 1`."""
    if level >= MAX_LEVEL:
        return 0
    return int(100 * (level ** 1.65) + 40 * level)


def max_stamina_for_player(level: int, rebirth_count: int) -> int:
    return 100 + min(50, level // 2) + min(100, rebirth_count * 5)


def format_affix(key: str, value: float) -> str:
    meta = AFFIX_DEFS.get(key, {"name": key, "fmt": "pct"})
    if meta.get("fmt") == "pct":
        return f"{meta['name']} +{value * 100:.1f}%"
    return f"{meta['name']} +{value:.0f}"


def get_class_title(class_id: str, promo_tier: int) -> str:
    cls_def = CLASSES.get(class_id, CLASSES["swordsman"])
    return cls_def["tiers"].get(promo_tier, cls_def["name"])
