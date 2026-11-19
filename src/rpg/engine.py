"""Core RPG game engine: stats, combat, mining, forging, dungeons, abyss, world boss, shop & quests."""

from __future__ import annotations

import datetime
import math
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from src.rpg.data import (
    ABYSS_STAMINA_COST,
    ACHIEVEMENTS,
    ACHIEVEMENTS_BY_ID,
    AFFIX_DEFS,
    ALL_QUESTS_BY_ID,
    BOSS_COOLDOWN_SECONDS,
    BOSS_STAMINA_COST,
    CLASSES,
    DAILY_CHECKIN_REWARDS,
    DAILY_QUESTS,
    DIFFICULTIES,
    DUNGEONS,
    DUNGEONS_BY_ID,
    ENHANCE_TABLE,
    EQUIPMENT_SETS,
    EXPEDITIONS_BY_ID,
    GEAR_TIERS,
    ITEMS,
    MAX_ENHANCE_LEVEL,
    MAX_EQUIPMENT_CAPACITY,
    MAX_LEVEL,
    MINE_COOLDOWN_SECONDS,
    MINE_STAMINA_COST,
    MINE_ZONES,
    MINE_ZONES_BY_ID,
    MYSTERY_SHOP_REFRESH_SECONDS,
    PICKAXES,
    PROMOTION_REQUIREMENTS,
    RARITIES,
    RARITY_ORDER,
    SLOT_BASE_STATS,
    SLOT_NAMES_BY_TIER,
    SLOT_ORDER,
    SLOTS,
    STAMINA_REGEN_SECONDS,
    SUPPLY_SHOP_BY_ID,
    WEEKLY_QUESTS,
    WORLD_BOSS_POOL,
    exp_needed_for_level,
    get_class_title,
    max_stamina_for_player,
)
from src.rpg.database import RPGDatabase
from src.rpg.models import (
    ActiveExpedition,
    CombatSession,
    ComputedStats,
    EquipmentItem,
    PlayerProfile,
    WorldBossState,
)


class RPGError(Exception):
    """User-facing game rule error (insufficient gold/stamina/level, etc.)."""


class RPGEngine:
    """Stateless-on-disk game engine backed by RPGDatabase."""

    def __init__(self, db: RPGDatabase, timezone_offset_hours: int = 8) -> None:
        self.db = db
        self.tz = datetime.timezone(datetime.timedelta(hours=timezone_offset_hours))
        self.active_combats: Dict[str, CombatSession] = {}

    # =========================================================================
    # Time & Period Helpers
    # =========================================================================
    def now(self) -> int:
        return int(time.time())

    def today_key(self, now_ts: Optional[int] = None) -> str:
        ts = self.now() if now_ts is None else now_ts
        dt = datetime.datetime.fromtimestamp(ts, tz=self.tz)
        return dt.strftime("%Y-%m-%d")

    def yesterday_key(self, now_ts: Optional[int] = None) -> str:
        ts = self.now() if now_ts is None else now_ts
        dt = datetime.datetime.fromtimestamp(ts, tz=self.tz) - datetime.timedelta(days=1)
        return dt.strftime("%Y-%m-%d")

    def week_key(self, now_ts: Optional[int] = None) -> str:
        ts = self.now() if now_ts is None else now_ts
        dt = datetime.datetime.fromtimestamp(ts, tz=self.tz)
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    # =========================================================================
    # Player Lifecycle, Stamina & Stat Computation
    # =========================================================================
    def register_player(
        self,
        user_id: str,
        display_name: str,
        class_id: str,
        now_ts: Optional[int] = None,
    ) -> PlayerProfile:
        uid = str(user_id)
        if class_id not in CLASSES:
            raise RPGError("無效的職業選擇。")
        existing = self.db.get_player(uid)
        if existing is not None:
            raise RPGError("你已經建立過角色了！請使用 `/rpg profile` 查看你的角色。")

        ts = self.now() if now_ts is None else now_ts
        with self.db.transaction():
            player = self.db.create_player(uid, display_name, class_id, ts)
            # Starter weapon + starter supplies
            starter_weapon = self._build_equipment_obj(
                user_id=uid,
                tier=1,
                slot="weapon",
                rarity="uncommon",
                now_ts=ts,
            )
            starter_weapon.is_equipped = True
            self.db.add_equipment(starter_weapon)
            self.db.add_item(uid, "hp_potion_s", 5)
            self.db.add_item(uid, "enhance_stone", 5)
            self.db.add_item(uid, "stamina_elixir", 1)
            stats = self.compute_stats(player)
            player.combat_power = stats.combat_power
            self.db.save_player(player)
        return player

    def require_player(
        self,
        user_id: str,
        display_name: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> PlayerProfile:
        uid = str(user_id)
        player = self.db.get_player(uid)
        if player is None:
            raise RPGError("你還沒踏上冒險旅程！請先使用 `/rpg start` 建立角色並選擇職業。")

        ts = self.now() if now_ts is None else now_ts
        changed = False
        if display_name and display_name[:64] != player.display_name:
            player.display_name = display_name[:64]
            changed = True
        if self._apply_stamina_regen(player, ts):
            changed = True
        if changed:
            self.db.save_player(player)
        return player

    def _apply_stamina_regen(self, player: PlayerProfile, now_ts: int) -> bool:
        max_stam = max_stamina_for_player(player.level, player.rebirth_count)
        if player.stamina >= max_stam:
            if player.stamina_updated_at < now_ts:
                player.stamina_updated_at = now_ts
                return True
            return False
        elapsed = max(0, now_ts - player.stamina_updated_at)
        ticks = elapsed // STAMINA_REGEN_SECONDS
        if ticks <= 0:
            return False
        player.stamina = min(max_stam, player.stamina + ticks)
        if player.stamina >= max_stam:
            player.stamina_updated_at = now_ts
        else:
            player.stamina_updated_at += ticks * STAMINA_REGEN_SECONDS
        return True

    def next_stamina_in(self, player: PlayerProfile, now_ts: Optional[int] = None) -> int:
        max_stam = max_stamina_for_player(player.level, player.rebirth_count)
        if player.stamina >= max_stam:
            return 0
        ts = self.now() if now_ts is None else now_ts
        elapsed = max(0, ts - player.stamina_updated_at)
        rem = STAMINA_REGEN_SECONDS - (elapsed % STAMINA_REGEN_SECONDS)
        return rem

    def compute_stats(self, player: PlayerProfile) -> ComputedStats:
        cls_def = CLASSES.get(player.class_id, CLASSES["swordsman"])
        base = cls_def["base"]
        per_lv = cls_def["per_level"]
        lv_delta = max(0, player.level - 1)

        raw_hp = base["hp"] + per_lv["hp"] * lv_delta
        raw_mp = base["mp"] + per_lv["mp"] * lv_delta
        raw_atk = base["atk"] + per_lv["atk"] * lv_delta
        raw_def = base["def"] + per_lv["def"] * lv_delta

        crit_rate = float(base["crit"])
        crit_dmg = float(base["crit_dmg"])
        dodge = float(base["dodge"])
        lifesteal = 0.0
        gold_bonus = 0.12 * player.rebirth_count
        exp_bonus = 0.12 * player.rebirth_count
        drop_bonus = 0.0
        mine_bonus = 0.0
        skill_dmg_bonus = 0.0
        dmg_reduction = 0.0

        atk_pct = 0.0
        def_pct = 0.0
        hp_pct = 0.0

        # Class passive by promo tier
        passive = cls_def["passive"].get(player.promo_tier, {})
        lifesteal += passive.get("lifesteal", 0.0)
        atk_pct += passive.get("atk_pct", 0.0)
        def_pct += passive.get("def_pct", 0.0)
        hp_pct += passive.get("hp_pct", 0.0)
        skill_dmg_bonus += passive.get("skill_dmg", 0.0)
        crit_dmg += passive.get("crit_dmg", 0.0)
        crit_rate += passive.get("crit_rate", 0.0)
        dodge += passive.get("dodge", 0.0)
        drop_bonus += passive.get("drop_bonus", 0.0)
        dmg_reduction += passive.get("dmg_reduction", 0.0)

        # Equipment stats & set counting
        equipped = self.db.get_equipment(player.user_id, equipped_only=True)
        set_counts: Dict[str, int] = {}
        for eq in equipped:
            raw_hp += eq.hp
            raw_mp += eq.mp
            raw_atk += eq.atk
            raw_def += eq.def_
            if eq.set_id:
                set_counts[eq.set_id] = set_counts.get(eq.set_id, 0) + 1
            for k, v in eq.affixes.items():
                if k == "atk_pct":
                    atk_pct += v
                elif k == "def_pct":
                    def_pct += v
                elif k == "hp_pct":
                    hp_pct += v
                elif k == "crit_rate":
                    crit_rate += v
                elif k == "crit_dmg":
                    crit_dmg += v
                elif k == "dodge":
                    dodge += v
                elif k == "lifesteal":
                    lifesteal += v
                elif k == "gold_bonus":
                    gold_bonus += v
                elif k == "exp_bonus":
                    exp_bonus += v
                elif k == "mine_bonus":
                    mine_bonus += v

        # Active Set Bonuses (2-piece and 4-piece)
        active_sets: List[str] = []
        for set_id, count in set_counts.items():
            sdef = EQUIPMENT_SETS.get(set_id)
            if not sdef:
                continue
            for req_cnt in (2, 4):
                if count >= req_cnt and req_cnt in sdef["bonuses"]:
                    active_sets.append(f"{sdef['emoji']} {sdef['name']} ({req_cnt}件)")
                    for k, v in sdef["bonuses"][req_cnt].items():
                        if k == "atk_pct":
                            atk_pct += v
                        elif k == "def_pct":
                            def_pct += v
                        elif k == "hp_pct":
                            hp_pct += v
                        elif k == "crit_rate":
                            crit_rate += v
                        elif k == "crit_dmg":
                            crit_dmg += v
                        elif k == "dodge":
                            dodge += v
                        elif k == "lifesteal":
                            lifesteal += v
                        elif k == "exp_bonus":
                            exp_bonus += v
                        elif k == "mine_bonus":
                            mine_bonus += v
                        elif k == "drop_bonus":
                            drop_bonus += v
                        elif k == "skill_dmg":
                            skill_dmg_bonus += v

        # Account-wide unlocked achievements permanent passive bonuses
        unlocked_achs = self.db.get_achievements(player.user_id)
        for ach_id in unlocked_achs:
            adef = ACHIEVEMENTS_BY_ID.get(ach_id)
            if not adef:
                continue
            for k, v in adef.get("bonus", {}).items():
                if k == "atk_pct":
                    atk_pct += v
                elif k == "def_pct":
                    def_pct += v
                elif k == "hp_pct":
                    hp_pct += v
                elif k == "crit_rate":
                    crit_rate += v
                elif k == "crit_dmg":
                    crit_dmg += v
                elif k == "gold_bonus":
                    gold_bonus += v
                elif k == "exp_bonus":
                    exp_bonus += v
                elif k == "mine_bonus":
                    mine_bonus += v
                elif k == "drop_bonus":
                    drop_bonus += v

        # Rebirth multiplicative scaling (+18% per rebirth!)
        rebirth_mult = 1.0 + 0.18 * player.rebirth_count

        max_hp = max(50, int(round(raw_hp * (1.0 + hp_pct) * rebirth_mult)))
        max_mp = max(30, int(round(raw_mp * (1.0 + 0.06 * player.rebirth_count))))
        atk = max(10, int(round(raw_atk * (1.0 + atk_pct) * rebirth_mult)))
        def_ = max(5, int(round(raw_def * (1.0 + def_pct) * rebirth_mult)))

        crit_rate = min(0.85, max(0.05, crit_rate))
        crit_dmg = min(4.20, max(1.50, crit_dmg))
        dodge = min(0.45, max(0.01, dodge))
        lifesteal = min(0.35, max(0.0, lifesteal))
        dmg_reduction = min(0.40, max(0.0, dmg_reduction))

        # Comprehensive Combat Power score for leaderboards & display
        cp = int(
            round(
                atk * 5.5
                + def_ * 4.2
                + max_hp * 0.65
                + max_mp * 1.1
                + (crit_rate * 100) * 14
                + ((crit_dmg - 1.5) * 100) * 8
                + (dodge * 100) * 12
                + (lifesteal * 100) * 18
                + (dmg_reduction * 100) * 20
            )
        )

        return ComputedStats(
            max_hp=max_hp,
            max_mp=max_mp,
            atk=atk,
            def_=def_,
            crit_rate=crit_rate,
            crit_dmg=crit_dmg,
            dodge=dodge,
            lifesteal=lifesteal,
            gold_bonus=gold_bonus,
            exp_bonus=exp_bonus,
            drop_bonus=drop_bonus,
            mine_bonus=mine_bonus,
            skill_dmg_bonus=skill_dmg_bonus,
            dmg_reduction=dmg_reduction,
            combat_power=cp,
            active_sets=active_sets,
        )

    def _sync_combat_power(self, player: PlayerProfile) -> ComputedStats:
        stats = self.compute_stats(player)
        player.combat_power = stats.combat_power
        return stats

    def _grant_exp(self, player: PlayerProfile, raw_exp: int, stats: ComputedStats) -> Tuple[int, int]:
        """Grant EXP with bonus multiplier. Returns (actual_exp_gained, levels_gained)."""
        gained = max(1, int(round(raw_exp * (1.0 + stats.exp_bonus))))
        if player.level >= MAX_LEVEL:
            return 0, 0
        player.exp += gained
        levels_gained = 0
        while player.level < MAX_LEVEL:
            needed = exp_needed_for_level(player.level)
            if player.exp >= needed:
                player.exp -= needed
                player.level += 1
                levels_gained += 1
                # Bonus stamina on level-up!
                player.stamina += 30
            else:
                break
        if player.level >= MAX_LEVEL:
            player.exp = 0
        return gained, levels_gained

    def _record_quest_event(
        self, user_id: str, event: str, delta: int = 1, now_ts: Optional[int] = None
    ) -> None:
        ts = self.now() if now_ts is None else now_ts
        dkey = self.today_key(ts)
        wkey = self.week_key(ts)
        for q in DAILY_QUESTS:
            if q["event"] == event:
                self.db.increment_quest(user_id, "daily", dkey, q["id"], q["target"], delta)
        for q in WEEKLY_QUESTS:
            if q["event"] == event:
                self.db.increment_quest(user_id, "weekly", wkey, q["id"], q["target"], delta)

    def check_achievements(
        self, player: PlayerProfile, now_ts: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Check and unlock any newly satisfied achievements, crediting Star Gems."""
        ts = self.now() if now_ts is None else now_ts
        unlocked = self.db.get_achievements(player.user_id)
        max_enh = self.db.get_max_enhance_level(player.user_id)

        conditions: Dict[str, bool] = {
            "ach_mine_10": player.total_mines >= 10,
            "ach_mine_100": player.total_mines >= 100,
            "ach_mine_500": player.total_mines >= 500,
            "ach_dungeon_1": player.total_dungeons >= 1,
            "ach_dungeon_30": player.total_dungeons >= 30,
            "ach_dungeon_150": player.total_dungeons >= 150,
            "ach_enhance_10": max_enh >= 10,
            "ach_enhance_15": max_enh >= 15,
            "ach_abyss_10": player.abyss_highest >= 10,
            "ach_abyss_30": player.abyss_highest >= 30,
            "ach_abyss_60": player.abyss_highest >= 60,
            "ach_boss_kill_1": player.boss_kills_participated >= 1,
            "ach_level_50": player.level >= 50 or player.rebirth_count >= 1,
            "ach_level_100": player.level >= 100 or player.rebirth_count >= 1,
            "ach_rebirth_1": player.rebirth_count >= 1,
            "ach_gold_100k": player.gold >= 100_000,
            "ach_checkin_7": player.total_checkins >= 7,
        }

        newly_unlocked: List[Dict[str, Any]] = []
        for ach in ACHIEVEMENTS:
            aid = ach["id"]
            if aid in unlocked:
                continue
            if conditions.get(aid, False):
                if self.db.unlock_achievement(player.user_id, aid, ts):
                    player.gems += int(ach["gems"])
                    if not player.active_title:
                        player.active_title = ach["title"]
                    newly_unlocked.append(ach)
        return newly_unlocked

    # =========================================================================
    # Equipment Generation & Forge / Enhance / Dismantle
    # =========================================================================
    def _pick_weighted(self, pairs: List[Tuple[str, int]]) -> str:
        total = sum(w for _, w in pairs)
        r = random.uniform(0, total)
        upto = 0.0
        for val, w in pairs:
            upto += w
            if r <= upto:
                return val
        return pairs[-1][0]

    def _build_equipment_obj(
        self,
        user_id: str,
        tier: int,
        slot: Optional[str] = None,
        rarity: Optional[str] = None,
        rarity_shift: int = 0,
        now_ts: Optional[int] = None,
    ) -> EquipmentItem:
        tier = max(1, min(6, tier))
        tdef = GEAR_TIERS[tier]
        chosen_slot = slot if slot in SLOTS else random.choice(SLOT_ORDER)

        if rarity is None:
            rarity = self._pick_weighted(tdef["rarity_weights"])
            if rarity_shift > 0:
                idx = RARITY_ORDER.index(rarity)
                rarity = RARITY_ORDER[min(len(RARITY_ORDER) - 1, idx + rarity_shift)]

        rdef = RARITIES[rarity]
        scale = tdef["scale"] * rdef["mult"]
        slot_base = SLOT_BASE_STATS[chosen_slot]

        def _roll_stat(val: int) -> int:
            return max(1, int(round(val * scale * random.uniform(0.92, 1.08))))

        affix_min, affix_max = rdef["affix_range"]
        affix_count = random.randint(affix_min, affix_max)
        affix_keys = random.sample(list(AFFIX_DEFS.keys()), k=min(affix_count, len(AFFIX_DEFS)))
        affixes: Dict[str, float] = {}
        tier_affix_mult = 1.0 + (tier - 1) * 0.14
        rarity_affix_mult = 0.85 + rdef["order"] * 0.12
        for ak in affix_keys:
            lo, hi = AFFIX_DEFS[ak]["base_range"]
            val = random.uniform(lo, hi) * tier_affix_mult * rarity_affix_mult
            affixes[ak] = round(val, 4)

        name = SLOT_NAMES_BY_TIER[tier][chosen_slot]
        set_id = tdef["set_id"] if rarity in ("rare", "epic", "legendary", "mythic") and tdef["set_id"] else ""

        return EquipmentItem(
            id=0,
            user_id=str(user_id),
            template_id=f"t{tier}_{chosen_slot}",
            name=name,
            slot=chosen_slot,
            rarity=rarity,
            tier=tier,
            set_id=set_id,
            enhance_level=0,
            enhance_pity=0,
            base_hp=_roll_stat(slot_base["hp"]),
            base_mp=_roll_stat(slot_base["mp"]),
            base_atk=_roll_stat(slot_base["atk"]),
            base_def=_roll_stat(slot_base["def"]),
            affixes=affixes,
            is_equipped=False,
            is_locked=rarity in ("legendary", "mythic"),
            created_at=self.now() if now_ts is None else now_ts,
        )

    def _try_add_equipment(
        self,
        user_id: str,
        tier: int,
        slot: Optional[str] = None,
        rarity: Optional[str] = None,
        rarity_shift: int = 0,
        now_ts: Optional[int] = None,
    ) -> Tuple[Optional[EquipmentItem], int]:
        """Add generated gear to player bag; if full, auto-convert into gold so nothing is wasted."""
        existing = self.db.get_equipment(user_id)
        item = self._build_equipment_obj(
            user_id=user_id,
            tier=tier,
            slot=slot,
            rarity=rarity,
            rarity_shift=rarity_shift,
            now_ts=now_ts,
        )
        if len(existing) >= MAX_EQUIPMENT_CAPACITY:
            fallback_gold = self.equipment_sell_value(item)
            return None, fallback_gold
        saved = self.db.add_equipment(item)
        return saved, 0

    def equipment_sell_value(self, item: EquipmentItem) -> int:
        rdef = RARITIES[item.rarity]
        return int(round((80 * (item.tier ** 1.7)) * rdef["sell_mult"] * (1 + 0.15 * item.enhance_level)))

    def equip_item(self, user_id: str, item_id: int) -> Tuple[EquipmentItem, ComputedStats]:
        player = self.require_player(user_id)
        with self.db.transaction():
            item = self.db.equip_item(player.user_id, item_id)
            if item is None:
                raise RPGError(f"找不到編號 `#{item_id}` 的裝備。")
            stats = self._sync_combat_power(player)
            self.db.save_player(player)
        return item, stats

    def toggle_lock_equipment(self, user_id: str, item_id: int) -> EquipmentItem:
        player = self.require_player(user_id)
        with self.db.transaction():
            item = self.db.get_equipment_by_id(player.user_id, item_id)
            if item is None:
                raise RPGError(f"找不到編號 `#{item_id}` 的裝備。")
            item.is_locked = not item.is_locked
            self.db.update_equipment(item)
        return item

    def auto_equip_best(self, user_id: str) -> Tuple[List[EquipmentItem], ComputedStats]:
        player = self.require_player(user_id)
        with self.db.transaction():
            all_gear = self.db.get_equipment(player.user_id)
            best_by_slot: Dict[str, EquipmentItem] = {}
            for eq in all_gear:
                cur = best_by_slot.get(eq.slot)
                if cur is None or eq.power_score > cur.power_score:
                    best_by_slot[eq.slot] = eq
            equipped_list: List[EquipmentItem] = []
            for slot in SLOT_ORDER:
                best = best_by_slot.get(slot)
                if best:
                    self.db.equip_item(player.user_id, best.id)
                    best.is_equipped = True
                    equipped_list.append(best)
            stats = self._sync_combat_power(player)
            self.db.save_player(player)
        return equipped_list, stats

    def enhance_equipment(
        self,
        user_id: str,
        item_id: int,
        use_protect: bool = False,
        now_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, now_ts=ts)
        with self.db.transaction():
            item = self.db.get_equipment_by_id(player.user_id, item_id)
            if item is None:
                raise RPGError(f"找不到編號 `#{item_id}` 的裝備。")
            if item.enhance_level >= MAX_ENHANCE_LEVEL:
                raise RPGError(f"**{item.name}** 已經強化至最高等級 `+{MAX_ENHANCE_LEVEL}`！")

            target_lv = item.enhance_level + 1
            cfg = ENHANCE_TABLE[target_lv]
            gold_cost = int(round(cfg["gold"] * (1.0 + 0.25 * (item.tier - 1))))
            stone_id = cfg["stone"]
            stone_qty = cfg["stone_qty"]

            if player.gold < gold_cost:
                raise RPGError(f"金幣不足！強化至 `+{target_lv}` 需要 **{gold_cost:,} 金幣**（目前 `{player.gold:,}`）。")
            if self.db.get_item_qty(player.user_id, stone_id) < stone_qty:
                sname = ITEMS[stone_id]["name"]
                have = self.db.get_item_qty(player.user_id, stone_id)
                raise RPGError(f"材料不足！需要 **{sname} x{stone_qty}**（目前 `{have}`）。")

            actually_used_protect = False
            if use_protect and cfg["downgrade"]:
                if self.db.get_item_qty(player.user_id, "protect_scroll") < 1:
                    raise RPGError("你沒有 **強化保護卷軸**！可於 `/rpg shop` 購買。")
                self.db.add_item(player.user_id, "protect_scroll", -1)
                actually_used_protect = True

            player.gold -= gold_cost
            self.db.add_item(player.user_id, stone_id, -stone_qty)
            player.total_enhances += 1

            pity_bonus = item.enhance_pity / 100.0
            effective_rate = 1.0 if item.enhance_pity >= 100 else min(1.0, cfg["rate"] + pity_bonus * 0.35)
            success = random.random() < effective_rate

            downgraded = False
            old_lv = item.enhance_level
            if success:
                item.enhance_level = target_lv
                item.enhance_pity = 0
            else:
                item.enhance_pity = min(100, item.enhance_pity + (18 if target_lv >= 11 else 15))
                if cfg["downgrade"] and not actually_used_protect and item.enhance_level > 10:
                    item.enhance_level -= 1
                    downgraded = True

            self.db.update_equipment(item)
            self._record_quest_event(player.user_id, "forge_or_enhance", 1, ts)
            new_achs = self.check_achievements(player, ts)
            stats = self._sync_combat_power(player)
            self.db.save_player(player)

        return {
            "item": item,
            "success": success,
            "old_level": old_lv,
            "new_level": item.enhance_level,
            "downgraded": downgraded,
            "used_protect": actually_used_protect,
            "effective_rate": effective_rate,
            "gold_cost": gold_cost,
            "stone_name": ITEMS[stone_id]["name"],
            "stone_qty": stone_qty,
            "stats": stats,
            "achievements": new_achs,
        }

    def forge_equipment(
        self, user_id: str, tier: int, slot: Optional[str] = None, now_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, now_ts=ts)
        if tier not in GEAR_TIERS:
            raise RPGError("無效的裝備階級（支援 T1 ~ T6）。")
        tdef = GEAR_TIERS[tier]
        if player.level < tdef["min_level"] and player.rebirth_count == 0:
            raise RPGError(f"鍛造 **T{tier} {tdef['name']}** 裝備需要達到 **Lv.{tdef['min_level']}**。")
        if len(self.db.get_equipment(player.user_id)) >= MAX_EQUIPMENT_CAPACITY:
            raise RPGError(f"裝備背包已滿（上限 {MAX_EQUIPMENT_CAPACITY} 件），請先分解或出售多餘裝備！")

        with self.db.transaction():
            gold_cost = tdef["forge_gold"]
            if player.gold < gold_cost:
                raise RPGError(f"金幣不足！需要 **{gold_cost:,} 金幣**（目前 `{player.gold:,}`）。")
            mats: Dict[str, int] = tdef["forge_materials"]
            missing = []
            for mid, qty in mats.items():
                have = self.db.get_item_qty(player.user_id, mid)
                if have < qty:
                    missing.append(f"{ITEMS[mid]['emoji']} {ITEMS[mid]['name']} `{have}/{qty}`")
            if missing:
                raise RPGError("鍛造材料不足：\n" + "\n".join(missing))

            player.gold -= gold_cost
            self.db.consume_items(player.user_id, mats)
            item = self._build_equipment_obj(
                user_id=player.user_id,
                tier=tier,
                slot=slot,
                now_ts=ts,
            )
            saved = self.db.add_equipment(item)
            self._record_quest_event(player.user_id, "forge_or_enhance", 1, ts)
            self.db.save_player(player)

        return {"item": saved, "gold_cost": gold_cost, "materials": mats}

    def upgrade_pickaxe(self, user_id: str, now_ts: Optional[int] = None) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, now_ts=ts)
        next_tier = player.pickaxe_tier + 1
        if next_tier not in PICKAXES:
            raise RPGError("你的礦鎬已經升級至最高階級 **T8 永恆創世神鎬**！")

        pdef = PICKAXES[next_tier]
        with self.db.transaction():
            if player.gold < pdef["gold"]:
                raise RPGError(
                    f"金幣不足！鍛造 **T{next_tier} {pdef['name']}** 需要 **{pdef['gold']:,} 金幣**（目前 `{player.gold:,}`）。"
                )
            mats: Dict[str, int] = pdef["materials"]
            missing = []
            for mid, qty in mats.items():
                have = self.db.get_item_qty(player.user_id, mid)
                if have < qty:
                    missing.append(f"{ITEMS[mid]['emoji']} {ITEMS[mid]['name']} `{have}/{qty}`")
            if missing:
                raise RPGError("升級礦鎬材料不足：\n" + "\n".join(missing))

            player.gold -= pdef["gold"]
            self.db.consume_items(player.user_id, mats)
            player.pickaxe_tier = next_tier
            self._record_quest_event(player.user_id, "forge_or_enhance", 1, ts)
            self.db.save_player(player)

        return {"new_tier": next_tier, "pickaxe": pdef}

    def dismantle_equipment(self, user_id: str, item_id: int) -> Dict[str, Any]:
        player = self.require_player(user_id)
        with self.db.transaction():
            item = self.db.get_equipment_by_id(player.user_id, item_id)
            if item is None:
                raise RPGError(f"找不到編號 `#{item_id}` 的裝備。")
            if item.is_equipped:
                raise RPGError("無法分解穿戴中的裝備，請先更換其他裝備。")
            if item.is_locked:
                raise RPGError("此裝備已鎖定 🔒，請先解鎖後再分解。")

            stones, adv_stones, gold = self._dismantle_yield(item)
            self.db.delete_equipment(player.user_id, [item.id])
            if stones > 0:
                self.db.add_item(player.user_id, "enhance_stone", stones)
            if adv_stones > 0:
                self.db.add_item(player.user_id, "adv_enhance_stone", adv_stones)
            player.gold += gold
            self.db.save_player(player)

        return {
            "count": 1,
            "stones": stones,
            "adv_stones": adv_stones,
            "gold": gold,
            "item_name": item.name,
        }

    def bulk_dismantle(self, user_id: str, max_rarity: str = "rare") -> Dict[str, Any]:
        if max_rarity not in RARITIES:
            raise RPGError("無效的稀有度篩選。")
        max_order = RARITIES[max_rarity]["order"]
        player = self.require_player(user_id)
        with self.db.transaction():
            all_gear = self.db.get_equipment(player.user_id)
            targets = [
                eq
                for eq in all_gear
                if not eq.is_equipped
                and not eq.is_locked
                and RARITIES[eq.rarity]["order"] <= max_order
            ]
            if not targets:
                raise RPGError(
                    f"背包中沒有可分解的未穿戴、未鎖定且品質為 **{RARITIES[max_rarity]['name']}以下** 的裝備。"
                )

            total_stones = 0
            total_adv = 0
            total_gold = 0
            for eq in targets:
                s, adv, g = self._dismantle_yield(eq)
                total_stones += s
                total_adv += adv
                total_gold += g

            self.db.delete_equipment(player.user_id, [eq.id for eq in targets])
            if total_stones > 0:
                self.db.add_item(player.user_id, "enhance_stone", total_stones)
            if total_adv > 0:
                self.db.add_item(player.user_id, "adv_enhance_stone", total_adv)
            player.gold += total_gold
            self.db.save_player(player)

        return {
            "count": len(targets),
            "stones": total_stones,
            "adv_stones": total_adv,
            "gold": total_gold,
        }

    @staticmethod
    def _dismantle_yield(item: EquipmentItem) -> Tuple[int, int, int]:
        rdef = RARITIES[item.rarity]
        stones = rdef["dismantle_stones"] + item.enhance_level
        adv_stones = 0
        if item.tier >= 4 and item.rarity in ("epic", "legendary", "mythic"):
            adv_stones = max(1, rdef["order"] - 3)
        gold = int(45 * item.tier * rdef["sell_mult"])
        return stones, adv_stones, gold

    # =========================================================================
    # Mining System
    # =========================================================================
    def get_best_unlocked_mine(self, player: PlayerProfile) -> Dict[str, Any]:
        best = MINE_ZONES[0]
        for z in MINE_ZONES:
            lv_ok = player.level >= z["min_level"] or player.rebirth_count > 0
            if lv_ok and player.pickaxe_tier >= z["min_pickaxe"]:
                best = z
        return best

    def mine(
        self,
        user_id: str,
        display_name: Optional[str] = None,
        zone_id: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, display_name=display_name, now_ts=ts)

        zone = MINE_ZONES_BY_ID.get(zone_id) if zone_id else self.get_best_unlocked_mine(player)
        if zone is None:
            raise RPGError("找不到指定的礦區。")

        if player.level < zone["min_level"] and player.rebirth_count == 0:
            raise RPGError(f"進入 **{zone['emoji']} {zone['name']}** 需要 **Lv.{zone['min_level']}**。")
        if player.pickaxe_tier < zone["min_pickaxe"]:
            req_pick = PICKAXES[zone["min_pickaxe"]]["name"]
            raise RPGError(
                f"進入 **{zone['emoji']} {zone['name']}** 需要 **T{zone['min_pickaxe']} {req_pick}** 以上（請於 `/rpg forge` 升級礦鎬）。"
            )

        cd_left = (player.last_mine_at + MINE_COOLDOWN_SECONDS) - ts
        if cd_left > 0:
            raise RPGError(f"剛揮完鎬子喘口氣！請等待 **{cd_left} 秒**後再挖礦。")

        if player.stamina < MINE_STAMINA_COST:
            wait = self.next_stamina_in(player, ts)
            raise RPGError(
                f"體力不足！挖礦需要 `{MINE_STAMINA_COST}` 體力（目前 `{player.stamina}`，約 {wait // 60} 分 {wait % 60} 秒回復 1 點，或使用體力恢復劑）。"
            )

        with self.db.transaction():
            stats = self.compute_stats(player)
            pick = PICKAXES[player.pickaxe_tier]

            # Maintain combo if mined within 10 minutes
            if player.last_mine_at > 0 and (ts - player.last_mine_at) <= 600:
                player.mine_combo = min(10, player.mine_combo + 1)
            else:
                player.mine_combo = 1

            player.stamina -= MINE_STAMINA_COST
            player.last_mine_at = ts
            player.total_mines += 1

            combo_mult = 1.0 + 0.02 * player.mine_combo
            yield_mult = pick["yield_mult"] * combo_mult * (1.0 + stats.mine_bonus)
            is_double = random.random() < pick["double_chance"]
            if is_double:
                yield_mult *= 2.0

            loot: Dict[str, int] = {}
            for item_id, lo, hi, base_chance in zone["drops"]:
                chance = min(1.0, base_chance + pick["rare_bonus"] * (1.0 - base_chance))
                if random.random() <= chance:
                    qty = max(1, int(round(random.randint(lo, hi) * yield_mult)))
                    loot[item_id] = loot.get(item_id, 0) + qty

            raw_gold = random.randint(*zone["gold"])
            gold_gain = max(1, int(round(raw_gold * combo_mult * (1.0 + stats.gold_bonus))))
            raw_exp = random.randint(*zone["exp"])

            # Random Mining Events (~24% chance)
            event_text: Optional[str] = None
            bonus_gems = 0
            bonus_gear: Optional[EquipmentItem] = None
            roll = random.random()
            if roll < 0.07:
                # Rich vein
                for k in list(loot.keys()):
                    loot[k] *= 2
                event_text = "✨ **奇遇【黃金富礦脈】**：一鎬敲出閃耀主礦脈，本次所有礦石產量 **雙倍**！"
            elif roll < 0.13:
                bonus_gems = random.randint(6, 18)
                player.gems += bonus_gems
                loot["enhance_stone"] = loot.get("enhance_stone", 0) + 2
                event_text = f"💎 **奇遇【遠古星晶簇】**：額外採獲 **{bonus_gems} 星鑽** 與 **初級強化石 x2**！"
            elif roll < 0.18:
                zone_idx = MINE_ZONES.index(zone)
                gear_tier = min(6, zone_idx + 1)
                eq, fb_gold = self._try_add_equipment(player.user_id, tier=gear_tier, now_ts=ts)
                if eq:
                    bonus_gear = eq
                    rdef = RARITIES[eq.rarity]
                    event_text = f"🧰 **奇遇【遠古礦工寶箱】**：挖出了 {rdef['emoji']} **[{rdef['name']}] {eq.name}**！"
                else:
                    gold_gain += fb_gold
                    event_text = f"🧰 **奇遇【遠古礦工寶箱】**：背包已滿，自動折算為 **+{fb_gold:,} 金幣**！"
            elif roll < 0.22:
                extra_gold = int(gold_gain * 1.4)
                gold_gain += extra_gold
                event_text = f"👺 **奇遇【寶藏哥布林】**：擊退偷礦的哥布林，奪回額外 **+{extra_gold:,} 金幣**！"
            elif roll < 0.26:
                player.stamina += 8
                event_text = "🌋 **奇遇【地脈靈氣湧動】**：清新靈氣湧入體內，立即回復 **+8 體力**！"

            for item_id, qty in loot.items():
                self.db.add_item(player.user_id, item_id, qty)

            player.gold += gold_gain
            exp_gain, lv_up = self._grant_exp(player, raw_exp, stats)
            self._record_quest_event(player.user_id, "mine", 1, ts)
            new_achs = self.check_achievements(player, ts)
            new_stats = self._sync_combat_power(player)
            self.db.save_player(player)

        return {
            "player": player,
            "zone": zone,
            "pickaxe": pick,
            "loot": loot,
            "gold_gain": gold_gain,
            "exp_gain": exp_gain,
            "levels_gained": lv_up,
            "is_double": is_double,
            "combo": player.mine_combo,
            "event_text": event_text,
            "bonus_gems": bonus_gems,
            "bonus_gear": bonus_gear,
            "achievements": new_achs,
            "stats": new_stats,
        }

    # =========================================================================
    # Dungeons, Interactive Turn-Based Combat, Sweep & Endless Abyss
    # =========================================================================
    def start_dungeon_combat(
        self,
        user_id: str,
        dungeon_id: str,
        difficulty: str = "normal",
        display_name: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> CombatSession:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, display_name=display_name, now_ts=ts)

        ddef = DUNGEONS_BY_ID.get(dungeon_id)
        if ddef is None:
            raise RPGError("找不到指定的副本。")
        if difficulty not in DIFFICULTIES:
            raise RPGError("無效的副本難度（支援 normal / hard / hell）。")

        clears = self.db.get_dungeon_clears(player.user_id)
        if difficulty == "hard" and clears.get((dungeon_id, "normal"), 0) == 0:
            raise RPGError(f"請先通關 **{ddef['name']}（普通）** 才能解鎖困難難度！")
        if difficulty == "hell" and clears.get((dungeon_id, "hard"), 0) == 0:
            raise RPGError(f"請先通關 **{ddef['name']}（困難）** 才能解鎖地獄難度！")

        diff_cfg = DIFFICULTIES[difficulty]
        stam_cost = diff_cfg["stamina"]
        if player.stamina < stam_cost:
            raise RPGError(f"體力不足！挑戰需要 `{stam_cost}` 體力（目前 `{player.stamina}`）。")

        with self.db.transaction():
            player.stamina -= stam_cost
            stats = self._sync_combat_power(player)
            self.db.save_player(player)

        mult = diff_cfg["stat_mult"]
        session = CombatSession(
            user_id=player.user_id,
            mode="dungeon",
            target_id=dungeon_id,
            difficulty=difficulty,
            title=f"{ddef['emoji']} {ddef['name']}（{diff_cfg['emoji']} {diff_cfg['name']}）",
            enemy_name=ddef["boss_name"],
            enemy_emoji=ddef["boss_emoji"],
            enemy_max_hp=int(round(ddef["hp"] * mult)),
            enemy_hp=int(round(ddef["hp"] * mult)),
            enemy_atk=int(round(ddef["atk"] * mult)),
            enemy_def=int(round(ddef["def"] * mult)),
            enemy_level=ddef["rec_level"],
            enemy_telegraph_name=ddef["telegraph_name"],
            player_max_hp=stats.max_hp,
            player_hp=stats.max_hp,
            player_max_mp=stats.max_mp,
            player_mp=stats.max_mp,
            stamina_spent=stam_cost,
            logs=[
                f"⚔️ 你踏入了 **{ddef['name']}（{diff_cfg['name']}）**，迎戰 **{ddef['boss_name']}**！",
                "💡 提示：當首領出現「蓄力警告」時，按下 **🛡️ 防禦反擊** 可大幅減傷並反擊！",
            ],
        )
        self.active_combats[player.user_id] = session
        return session

    def start_abyss_combat(
        self,
        user_id: str,
        floor: Optional[int] = None,
        display_name: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> CombatSession:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, display_name=display_name, now_ts=ts)

        target_floor = floor if floor is not None else max(1, player.abyss_highest + 1)
        if target_floor < 1:
            raise RPGError("深淵層數必須大於等於 1。")
        if target_floor > player.abyss_highest + 1:
            raise RPGError(f"你目前最高已通關第 **{player.abyss_highest}** 層，下一層為第 **{player.abyss_highest + 1}** 層。")

        if player.stamina < ABYSS_STAMINA_COST:
            raise RPGError(f"體力不足！挑戰無盡深淵需要 `{ABYSS_STAMINA_COST}` 體力（目前 `{player.stamina}`）。")

        with self.db.transaction():
            player.stamina -= ABYSS_STAMINA_COST
            stats = self._sync_combat_power(player)
            self.db.save_player(player)

        is_boss_floor = target_floor % 5 == 0
        scale = (1.135 ** (target_floor - 1)) * (1.0 + 0.08 * target_floor)
        boss_mult = 1.35 if is_boss_floor else 1.0
        enemy_hp = int(round(260 * scale * boss_mult))
        enemy_atk = int(round(26 * (1.115 ** (target_floor - 1)) * (1.15 if is_boss_floor else 1.0)))
        enemy_def = int(round(10 * (1.105 ** (target_floor - 1))))

        guardians = [
            ("深淵哨兵", "👁️"),
            ("虛空魔像", "🗿"),
            ("墮落劍靈", "⚔️"),
            ("暗影法妖", "🔮"),
            ("深淵守門王", "👑"),
        ]
        ename, eemoji = guardians[4] if is_boss_floor else guardians[(target_floor - 1) % 4]

        session = CombatSession(
            user_id=player.user_id,
            mode="abyss",
            target_id=str(target_floor),
            difficulty="abyss",
            title=f"🗼 無盡深淵・第 {target_floor} 層" + ("【守門王】" if is_boss_floor else ""),
            enemy_name=f"深淵第 {target_floor} 層・{ename}",
            enemy_emoji=eemoji,
            enemy_max_hp=enemy_hp,
            enemy_hp=enemy_hp,
            enemy_atk=enemy_atk,
            enemy_def=enemy_def,
            enemy_level=min(999, target_floor * 2),
            enemy_telegraph_name="深淵湮滅衝擊",
            player_max_hp=stats.max_hp,
            player_hp=stats.max_hp,
            player_max_mp=stats.max_mp,
            player_mp=stats.max_mp,
            stamina_spent=ABYSS_STAMINA_COST,
            logs=[
                f"🗼 進入 **無盡深淵 第 {target_floor} 層**！迎戰 **{ename}**！"
                + ("（🌟 守門王層：首通必得大量星鑽與高階裝備！）" if is_boss_floor else "")
            ],
        )
        self.active_combats[player.user_id] = session
        return session

    def combat_action(
        self, user_id: str, action: str, now_ts: Optional[int] = None
    ) -> CombatSession:
        uid = str(user_id)
        session = self.active_combats.get(uid)
        if session is None or session.finished:
            raise RPGError("目前沒有進行中的戰鬥。")

        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(uid, now_ts=ts)
        stats = self.compute_stats(player)

        if action == "retreat":
            refund = session.stamina_spent // 2
            with self.db.transaction():
                player.stamina += refund
                self.db.save_player(player)
            session.finished = True
            session.retreated = True
            session.logs.append(f"🏃 你安全撤退了，退還 **{refund} 點體力**。")
            return session

        if action == "auto":
            safety_turns = 40
            while not session.finished and safety_turns > 0:
                safety_turns -= 1
                chosen = self._choose_auto_action(player, session)
                self._execute_combat_turn(player, stats, session, chosen, ts)
            return session

        self._execute_combat_turn(player, stats, session, action, ts)
        return session

    def _choose_auto_action(self, player: PlayerProfile, session: CombatSession) -> str:
        cls_def = CLASSES[player.class_id]
        # Heal if HP low and has potion
        if session.player_hp < session.player_max_hp * 0.35:
            for pid in ("hp_potion_l", "hp_potion_m", "hp_potion_s"):
                if self.db.get_item_qty(player.user_id, pid) > 0:
                    return "potion"
        if session.enemy_telegraph:
            return "defend"
        if (
            player.level >= 15 or player.rebirth_count > 0
        ) and session.ult_cooldown == 0 and session.player_mp >= cls_def["ultimate"]["mp"]:
            return "ultimate"
        if session.player_mp >= cls_def["skill"]["mp"]:
            return "skill"
        return "attack"

    def _calc_damage(
        self,
        atk: float,
        target_def: float,
        crit_rate: float,
        crit_dmg: float,
        def_ignore: float = 0.0,
        guaranteed_crit: bool = False,
    ) -> Tuple[int, bool]:
        eff_def = max(0.0, target_def * (1.0 - def_ignore))
        mitigation = 100.0 / (100.0 + eff_def * 1.4)
        dmg = atk * mitigation * random.uniform(0.92, 1.08)
        is_crit = guaranteed_crit or (random.random() < crit_rate)
        if is_crit:
            dmg *= crit_dmg
        return max(1, int(round(dmg))), is_crit

    def _execute_combat_turn(
        self,
        player: PlayerProfile,
        stats: ComputedStats,
        session: CombatSession,
        action: str,
        now_ts: int,
    ) -> None:
        cls_def = CLASSES[player.class_id]
        turn_logs: List[str] = [f"**── 第 {session.turn} 回合 ──**"]
        defending = False
        enemy_eff_def = session.enemy_def * (0.8 if session.enemy_shred_turns > 0 else 1.0)

        # 1. Player Action
        if action == "potion":
            used_pid = None
            for pid in ("hp_potion_l", "hp_potion_m", "hp_potion_s"):
                if self.db.get_item_qty(player.user_id, pid) > 0:
                    used_pid = pid
                    break
            if used_pid is None:
                turn_logs.append("⚠️ 背包沒有生命藥水！改為普通攻擊。")
                action = "attack"
            else:
                self.db.add_item(player.user_id, used_pid, -1)
                pinfo = ITEMS[used_pid]
                heal = int(session.player_max_hp * pinfo["heal_pct"] + pinfo["heal_flat"])
                session.player_hp = min(session.player_max_hp, session.player_hp + heal)
                mp_note = ""
                if used_pid == "hp_potion_l":
                    session.player_mp = min(session.player_max_mp, session.player_mp + 30)
                    mp_note = " 與 **30 MP**"
                turn_logs.append(f"{pinfo['emoji']} 飲用 **{pinfo['name']}**，回復 **{heal:,} HP**{mp_note}！")

        if action == "defend":
            defending = True
            mp_gain = 18
            session.player_mp = min(session.player_max_mp, session.player_mp + mp_gain)
            turn_logs.append(f"🛡️ 採取 **防禦反擊架勢**（本回合減傷 60%、回復 +{mp_gain} MP）！")

        elif action == "skill":
            sk = cls_def["skill"]
            if session.player_mp < sk["mp"]:
                turn_logs.append(f"⚠️ MP 不足（需 {sk['mp']} MP），改為普通攻擊。")
                action = "attack"
            else:
                session.player_mp -= sk["mp"]
                sk_mult = 1.0 + stats.skill_dmg_bonus
                if player.class_id == "swordsman":
                    dmg, crit = self._calc_damage(stats.atk * 1.75 * sk_mult, enemy_eff_def, stats.crit_rate, stats.crit_dmg)
                    session.enemy_hp = max(0, session.enemy_hp - dmg)
                    session.enemy_shred_turns = 2
                    heal = int(dmg * stats.lifesteal)
                    session.player_hp = min(session.player_max_hp, session.player_hp + heal)
                    turn_logs.append(f"⚔️ 施放【{sk['name']}】造成 **{dmg:,}**{'💥暴擊' if crit else ''} 傷害並破甲！" + (f"（吸血 +{heal:,}）" if heal > 0 else ""))
                elif player.class_id == "mage":
                    dmg, crit = self._calc_damage(stats.atk * 2.15 * sk_mult, enemy_eff_def, stats.crit_rate, stats.crit_dmg, def_ignore=0.25)
                    session.enemy_hp = max(0, session.enemy_hp - dmg)
                    turn_logs.append(f"🔮 施放【{sk['name']}】貫穿防禦，造成 **{dmg:,}**{'💥暴擊' if crit else ''} 傷害！")
                elif player.class_id == "ranger":
                    total_dmg = 0
                    crits = 0
                    for _ in range(3):
                        d, c = self._calc_damage(stats.atk * 0.68 * sk_mult, enemy_eff_def, stats.crit_rate, stats.crit_dmg)
                        total_dmg += d
                        if c:
                            crits += 1
                    session.enemy_hp = max(0, session.enemy_hp - total_dmg)
                    turn_logs.append(f"🏹 施放【{sk['name']}】3 連射共造成 **{total_dmg:,}** 傷害（{crits} 箭暴擊）！")
                else:  # paladin
                    dmg, crit = self._calc_damage(stats.atk * 1.55 * sk_mult, enemy_eff_def, stats.crit_rate, stats.crit_dmg)
                    true_bonus = int(stats.def_ * 0.45)
                    total = dmg + true_bonus
                    session.enemy_hp = max(0, session.enemy_hp - total)
                    shield = int(session.player_max_hp * 0.20)
                    session.player_shield += shield
                    turn_logs.append(f"🛡️ 施放【{sk['name']}】造成 **{total:,}**{'💥暴擊' if crit else ''} 傷害，並獲得 **{shield:,}** 護盾！")

        elif action == "ultimate":
            ult = cls_def["ultimate"]
            if player.level < 15 and player.rebirth_count == 0:
                turn_logs.append("⚠️ 終極奧義於 **Lv.15** 解鎖！改為普通攻擊。")
                action = "attack"
            elif session.ult_cooldown > 0:
                turn_logs.append(f"⚠️ 終極奧義冷卻中（剩餘 {session.ult_cooldown} 回合），改為普通攻擊。")
                action = "attack"
            elif session.player_mp < ult["mp"]:
                turn_logs.append(f"⚠️ MP 不足（需 {ult['mp']} MP），改為普通攻擊。")
                action = "attack"
            else:
                session.player_mp -= ult["mp"]
                session.ult_cooldown = ult["cooldown"] + 1  # decrements at end of turn
                sk_mult = 1.0 + stats.skill_dmg_bonus
                if player.class_id == "swordsman":
                    dmg, crit = self._calc_damage(stats.atk * 2.75 * sk_mult, enemy_eff_def, stats.crit_rate, stats.crit_dmg)
                    session.enemy_hp = max(0, session.enemy_hp - dmg)
                    heal = int(session.player_max_hp * 0.15 + dmg * stats.lifesteal)
                    session.player_hp = min(session.player_max_hp, session.player_hp + heal)
                    turn_logs.append(f"🌟 終極奧義【{ult['name']}】造成 **{dmg:,}**{'💥暴擊' if crit else ''} 傷害，回復 **{heal:,} HP**！")
                elif player.class_id == "mage":
                    dmg, crit = self._calc_damage(stats.atk * 3.20 * sk_mult, enemy_eff_def, stats.crit_rate, stats.crit_dmg, def_ignore=0.30)
                    session.enemy_hp = max(0, session.enemy_hp - dmg)
                    session.enemy_burn_turns = 2
                    session.enemy_burn_dmg = int(stats.atk * 0.35 * sk_mult)
                    turn_logs.append(f"🌟 終極奧義【{ult['name']}】造成 **{dmg:,}**{'💥暴擊' if crit else ''} 毀滅傷害並附加灼燒！")
                elif player.class_id == "ranger":
                    dmg, _ = self._calc_damage(stats.atk * 2.45 * sk_mult, enemy_eff_def, stats.crit_rate, stats.crit_dmg, guaranteed_crit=True)
                    session.enemy_hp = max(0, session.enemy_hp - dmg)
                    session.player_dodge_buff_turns = 2
                    turn_logs.append(f"🌟 終極奧義【{ult['name']}】必中暴擊 **{dmg:,}** 傷害，並獲得 2 回合閃避 +25%！")
                else:  # paladin
                    heal = int(session.player_max_hp * 0.35)
                    shield = int(session.player_max_hp * 0.30)
                    session.player_hp = min(session.player_max_hp, session.player_hp + heal)
                    session.player_shield += shield
                    dmg, crit = self._calc_damage(stats.atk * 2.10 * sk_mult, enemy_eff_def, stats.crit_rate, stats.crit_dmg)
                    session.enemy_hp = max(0, session.enemy_hp - dmg)
                    turn_logs.append(f"🌟 終極奧義【{ult['name']}】回復 **{heal:,} HP**、獲得 **{shield:,} 護盾**，並反擊 **{dmg:,}**{'💥' if crit else ''} 傷害！")

        if action == "attack":
            session.player_mp = min(session.player_max_mp, session.player_mp + 10)
            dmg, crit = self._calc_damage(stats.atk, enemy_eff_def, stats.crit_rate, stats.crit_dmg)
            session.enemy_hp = max(0, session.enemy_hp - dmg)
            heal = int(dmg * stats.lifesteal)
            if heal > 0:
                session.player_hp = min(session.player_max_hp, session.player_hp + heal)
            turn_logs.append(
                f"⚔️ 普通攻擊造成 **{dmg:,}**{'💥暴擊' if crit else ''} 傷害（+10 MP）"
                + (f"，吸血 +{heal:,}" if heal > 0 else "")
                + "。"
            )

        # Enemy burn DOT
        if session.enemy_hp > 0 and session.enemy_burn_turns > 0:
            burn = session.enemy_burn_dmg
            session.enemy_hp = max(0, session.enemy_hp - burn)
            session.enemy_burn_turns -= 1
            turn_logs.append(f"🔥 灼燒對 **{session.enemy_name}** 造成 **{burn:,}** 持續傷害！")

        # Check Victory!
        if session.enemy_hp <= 0:
            session.finished = True
            session.victory = True
            rewards = self._grant_combat_victory_rewards(player, stats, session, now_ts)
            session.rewards_summary = rewards
            turn_logs.append(f"🎉 **勝利！** 成功擊敗 **{session.enemy_name}**！")
            session.logs = (session.logs + turn_logs)[-10:]
            return

        # 2. Enemy Turn
        eff_dodge = min(0.70, stats.dodge + (0.25 if session.player_dodge_buff_turns > 0 else 0.0))
        is_heavy = session.enemy_telegraph
        session.enemy_telegraph = False

        if random.random() < eff_dodge:
            turn_logs.append(f"💨 靈巧閃避了 **{session.enemy_name}** 的{'強力大招' if is_heavy else '攻擊'}！")
        else:
            raw_enemy_atk = session.enemy_atk * (1.75 if is_heavy else 1.0)
            edmg, _ = self._calc_damage(raw_enemy_atk, stats.def_, 0.08, 1.35)
            edmg = max(1, int(round(edmg * (1.0 - stats.dmg_reduction))))
            if defending:
                edmg = max(1, int(round(edmg * 0.40)))
            absorbed = min(session.player_shield, edmg)
            session.player_shield -= absorbed
            hp_loss = edmg - absorbed
            session.player_hp = max(0, session.player_hp - hp_loss)
            move_label = f"大招【{session.enemy_telegraph_name}】" if is_heavy else "攻擊"
            shield_note = f"（護盾吸收 {absorbed:,}）" if absorbed > 0 else ""
            turn_logs.append(
                f"{session.enemy_emoji} **{session.enemy_name}** 發動{move_label}，造成 **{hp_loss:,}** 傷害{shield_note}！"
            )

            # Counterattack if defending!
            if defending and session.player_hp > 0:
                cdmg, _ = self._calc_damage(stats.atk * 0.55, enemy_eff_def, stats.crit_rate, stats.crit_dmg)
                session.enemy_hp = max(0, session.enemy_hp - cdmg)
                turn_logs.append(f"⚡ 抓準破綻反擊，造成 **{cdmg:,}** 傷害！")
                if session.enemy_hp <= 0:
                    session.finished = True
                    session.victory = True
                    rewards = self._grant_combat_victory_rewards(player, stats, session, now_ts)
                    session.rewards_summary = rewards
                    turn_logs.append(f"🎉 **反擊絕殺！** 成功擊敗 **{session.enemy_name}**！")
                    session.logs = (session.logs + turn_logs)[-10:]
                    return

        # Check Defeat
        if session.player_hp <= 0:
            session.finished = True
            session.victory = False
            turn_logs.append("💀 體力耗盡敗陣了……強化裝備或帶些藥水再來挑戰吧！")
            session.logs = (session.logs + turn_logs)[-10:]
            return

        # Tick cooldowns & prepare next turn telegraph
        if session.ult_cooldown > 0:
            session.ult_cooldown -= 1
        if session.enemy_shred_turns > 0:
            session.enemy_shred_turns -= 1
        if session.player_dodge_buff_turns > 0:
            session.player_dodge_buff_turns -= 1

        session.turn += 1
        if session.turn % 3 == 0:
            session.enemy_telegraph = True
            turn_logs.append(
                f"⚠️ **危險警告**：{session.enemy_name} 正在蓄力【{session.enemy_telegraph_name}】！下回合建議使用 **🛡️ 防禦反擊**！"
            )

        session.logs = (session.logs + turn_logs)[-10:]

    def _grant_combat_victory_rewards(
        self,
        player: PlayerProfile,
        stats: ComputedStats,
        session: CombatSession,
        now_ts: int,
    ) -> Dict[str, Any]:
        with self.db.transaction():
            # Refresh player from DB inside transaction
            player = self.db.get_player(player.user_id) or player
            loot: Dict[str, int] = {}
            gear_drops: List[EquipmentItem] = []
            gems_gain = 0
            first_clear = False
            stamina_refund = 0

            if session.mode == "dungeon":
                ddef = DUNGEONS_BY_ID[session.target_id]
                diff = DIFFICULTIES[session.difficulty]
                rmult = diff["reward_mult"]
                gold_gain = int(round(ddef["gold"] * rmult * (1.0 + stats.gold_bonus) * random.uniform(0.92, 1.10)))
                raw_exp = int(round(ddef["exp"] * rmult))

                for item_id, lo, hi, chance in ddef["drops"]:
                    eff_chance = min(1.0, chance * (1.0 + stats.drop_bonus))
                    if random.random() <= eff_chance:
                        qty = max(1, int(round(random.randint(lo, hi) * (1.0 + 0.45 * (rmult - 1.0)))))
                        loot[item_id] = loot.get(item_id, 0) + qty

                # Gear drop roll
                gear_chance = min(1.0, diff["gear_chance"] * (1.0 + stats.drop_bonus))
                if random.random() <= gear_chance:
                    eq, fb_gold = self._try_add_equipment(
                        player.user_id,
                        tier=ddef["gear_tier"],
                        rarity_shift=diff["rarity_shift"],
                        now_ts=now_ts,
                    )
                    if eq:
                        gear_drops.append(eq)
                    else:
                        gold_gain += fb_gold

                first_clear = self.db.record_dungeon_clear(
                    player.user_id, session.target_id, session.difficulty, now_ts
                )
                if first_clear:
                    gems_gain += int(round(ddef["first_clear_gems"] * (1.0 + 0.5 * diff["rarity_shift"])))

                player.total_dungeons += 1
                self._record_quest_event(player.user_id, "dungeon_clear", 1, now_ts)

            else:
                # Endless Abyss rewards
                floor = int(session.target_id)
                is_boss_floor = floor % 5 == 0
                gold_gain = int(round((260 * (1.11 ** floor)) * (1.0 + stats.gold_bonus) * (2.0 if is_boss_floor else 1.0)))
                raw_exp = int(round(140 * (1.10 ** floor) * (1.8 if is_boss_floor else 1.0)))
                loot["enhance_stone"] = max(1, floor // 4 + (3 if is_boss_floor else 1))
                if floor >= 15:
                    loot["adv_enhance_stone"] = max(1, floor // 15 + (2 if is_boss_floor else 0))
                if is_boss_floor and floor >= 20:
                    loot["mythic_core"] = max(1, floor // 25)

                if floor > player.abyss_highest:
                    first_clear = True
                    player.abyss_highest = floor
                    player.abyss_floor = floor + 1
                    stamina_refund = 5
                    player.stamina += stamina_refund
                    gems_gain += (40 + floor * 2) if is_boss_floor else (10 + floor // 3)

                gear_tier = min(6, max(1, 1 + floor // 14))
                if is_boss_floor or random.random() < (0.45 + stats.drop_bonus):
                    eq, fb_gold = self._try_add_equipment(
                        player.user_id,
                        tier=gear_tier,
                        rarity_shift=1 if is_boss_floor else 0,
                        now_ts=now_ts,
                    )
                    if eq:
                        gear_drops.append(eq)
                    else:
                        gold_gain += fb_gold

                self._record_quest_event(player.user_id, "boss_or_abyss", 1, now_ts)

            for item_id, qty in loot.items():
                self.db.add_item(player.user_id, item_id, qty)

            player.gold += gold_gain
            player.gems += gems_gain
            exp_gain, levels_gained = self._grant_exp(player, raw_exp, stats)
            new_achs = self.check_achievements(player, now_ts)
            self._sync_combat_power(player)
            self.db.save_player(player)

        return {
            "gold": gold_gain,
            "gems": gems_gain,
            "exp": exp_gain,
            "levels_gained": levels_gained,
            "loot": loot,
            "gear": gear_drops,
            "first_clear": first_clear,
            "stamina_refund": stamina_refund,
            "achievements": new_achs,
        }

    def sweep_dungeon(
        self,
        user_id: str,
        dungeon_id: str,
        difficulty: str = "normal",
        times: int = 1,
        now_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        times = max(1, min(5, times))
        player = self.require_player(user_id, now_ts=ts)
        ddef = DUNGEONS_BY_ID.get(dungeon_id)
        if ddef is None or difficulty not in DIFFICULTIES:
            raise RPGError("無效的副本或難度。")

        clears = self.db.get_dungeon_clears(player.user_id)
        if clears.get((dungeon_id, difficulty), 0) < 1:
            raise RPGError("必須先手動通關該難度至少 1 次，才能解鎖快速掃蕩！")

        diff = DIFFICULTIES[difficulty]
        total_stam = diff["stamina"] * times
        if player.stamina < total_stam:
            raise RPGError(f"體力不足！掃蕩 {times} 次需要 `{total_stam}` 體力（目前 `{player.stamina}`）。")

        with self.db.transaction():
            stats = self.compute_stats(player)
            player.stamina -= total_stam
            rmult = diff["reward_mult"]
            total_gold = 0
            total_raw_exp = 0
            total_loot: Dict[str, int] = {}
            gear_drops: List[EquipmentItem] = []

            for _ in range(times):
                total_gold += int(round(ddef["gold"] * rmult * (1.0 + stats.gold_bonus) * random.uniform(0.92, 1.08)))
                total_raw_exp += int(round(ddef["exp"] * rmult))
                for item_id, lo, hi, chance in ddef["drops"]:
                    if random.random() <= min(1.0, chance * (1.0 + stats.drop_bonus)):
                        qty = max(1, int(round(random.randint(lo, hi) * (1.0 + 0.45 * (rmult - 1.0)))))
                        total_loot[item_id] = total_loot.get(item_id, 0) + qty
                if random.random() <= min(1.0, diff["gear_chance"] * (1.0 + stats.drop_bonus)):
                    eq, fb_gold = self._try_add_equipment(
                        player.user_id,
                        tier=ddef["gear_tier"],
                        rarity_shift=diff["rarity_shift"],
                        now_ts=ts,
                    )
                    if eq:
                        gear_drops.append(eq)
                    else:
                        total_gold += fb_gold
                self.db.record_dungeon_clear(player.user_id, dungeon_id, difficulty, ts)

            for item_id, qty in total_loot.items():
                self.db.add_item(player.user_id, item_id, qty)

            player.gold += total_gold
            player.total_dungeons += times
            exp_gain, levels_gained = self._grant_exp(player, total_raw_exp, stats)
            self._record_quest_event(player.user_id, "dungeon_clear", times, ts)
            new_achs = self.check_achievements(player, ts)
            self._sync_combat_power(player)
            self.db.save_player(player)

        return {
            "dungeon": ddef,
            "difficulty": diff,
            "times": times,
            "gold": total_gold,
            "exp": exp_gain,
            "levels_gained": levels_gained,
            "loot": total_loot,
            "gear": gear_drops,
            "achievements": new_achs,
        }

    # =========================================================================
    # Server World Boss (Shared Persistent Co-op Raid!)
    # =========================================================================
    def get_or_spawn_world_boss(self, now_ts: Optional[int] = None) -> WorldBossState:
        ts = self.now() if now_ts is None else now_ts
        active = self.db.get_active_world_boss()
        if active is not None:
            return active
        next_tier = self.db.get_latest_world_boss_tier() + 1
        tpl = WORLD_BOSS_POOL[(next_tier - 1) % len(WORLD_BOSS_POOL)]
        hp = int(round(tpl["base_hp"] * (1.38 ** (next_tier - 1))))
        atk = int(round(tpl["base_atk"] * (1.18 ** (next_tier - 1))))
        def_ = int(round(tpl["base_def"] * (1.15 ** (next_tier - 1))))
        return self.db.create_world_boss(
            tier=next_tier,
            boss_id=tpl["id"],
            name=f"Lv.{next_tier * 10} {tpl['name']}（第 {next_tier} 階）",
            max_hp=hp,
            atk=atk,
            def_=def_,
            now_ts=ts,
        )

    def attack_world_boss(
        self,
        user_id: str,
        display_name: Optional[str] = None,
        now_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, display_name=display_name, now_ts=ts)

        cd_left = (player.last_boss_at + BOSS_COOLDOWN_SECONDS) - ts
        if cd_left > 0:
            raise RPGError(f"世界王討伐整備中，請等待 **{cd_left} 秒**後再發起進攻！")
        if player.stamina < BOSS_STAMINA_COST:
            raise RPGError(f"體力不足！挑戰世界王需要 `{BOSS_STAMINA_COST}` 體力（目前 `{player.stamina}`）。")

        with self.db.transaction():
            boss = self.get_or_spawn_world_boss(ts)
            stats = self.compute_stats(player)
            player.stamina -= BOSS_STAMINA_COST
            player.last_boss_at = ts

            # Simulate an intense 5-turn raid clash
            hp = stats.max_hp
            total_dmg = 0
            crits = 0
            turns_survived = 0
            for turn_i in range(1, 6):
                turns_survived = turn_i
                mult = 2.4 if turn_i == 5 else (1.65 if turn_i % 2 == 0 else 1.0)
                dmg, is_crit = self._calc_damage(
                    stats.atk * mult * (1.0 + stats.skill_dmg_bonus * 0.5),
                    boss.def_,
                    stats.crit_rate,
                    stats.crit_dmg,
                )
                total_dmg += dmg
                if is_crit:
                    crits += 1
                heal = int(dmg * stats.lifesteal)
                hp = min(stats.max_hp, hp + heal)

                # Boss strikes back
                if random.random() >= stats.dodge:
                    bdmg, _ = self._calc_damage(boss.atk, stats.def_, 0.1, 1.35)
                    bdmg = max(1, int(round(bdmg * (1.0 - stats.dmg_reduction))))
                    hp -= bdmg
                    if hp <= 0:
                        break

            dealt = min(boss.current_hp, max(1, total_dmg))
            boss.current_hp = max(0, boss.current_hp - dealt)

            # Immediate hit reward
            gold_gain = int(round((220 + dealt * 0.18 + boss.tier * 120) * (1.0 + stats.gold_bonus)))
            raw_exp = int(round(120 + boss.tier * 85 + dealt * 0.05))
            essence_gain = 1 + (1 if dealt >= boss.max_hp * 0.03 else 0)

            player.gold += gold_gain
            player.total_boss_damage += dealt
            self.db.add_item(player.user_id, "boss_essence", essence_gain)
            self.db.record_world_boss_damage(
                boss.id, player.user_id, player.display_name, dealt, ts
            )
            self._record_quest_event(player.user_id, "boss_or_abyss", 1, ts)

            boss_killed = False
            next_boss: Optional[WorldBossState] = None
            mvp_rewards: List[Dict[str, Any]] = []

            if boss.current_hp <= 0:
                boss_killed = True
                boss.status = "defeated"
                boss.defeated_at = ts
                boss.killer_user_id = player.user_id
                self.db.update_world_boss(boss)

                # Credit kill & MVP rewards to ALL participants atomically!
                rankings = self.db.get_world_boss_rankings(boss.id, limit=50)
                base_kill_gold = 1500 * boss.tier
                base_kill_gems = 45 + 15 * boss.tier
                for rank_idx, entry in enumerate(rankings, start=1):
                    p = self.db.get_player(entry["user_id"])
                    if p is None:
                        continue
                    bonus_gems = 60 if rank_idx == 1 else (35 if rank_idx == 2 else (20 if rank_idx == 3 else 0))
                    bonus_keys = 2 if rank_idx == 1 else (1 if rank_idx <= 3 else 0)
                    p.gold += base_kill_gold
                    p.gems += base_kill_gems + bonus_gems
                    p.boss_kills_participated += 1
                    self.db.add_item(p.user_id, "boss_essence", 3 + boss.tier)
                    if boss.tier >= 2:
                        self.db.add_item(p.user_id, "mythic_core", max(1, boss.tier // 2))
                    if bonus_keys > 0:
                        self.db.add_item(p.user_id, "relic_key", bonus_keys)
                    self.check_achievements(p, ts)
                    self.db.save_player(p)
                    if rank_idx <= 5:
                        mvp_rewards.append(
                            {
                                "rank": rank_idx,
                                "display_name": entry["display_name"],
                                "damage": entry["total_damage"],
                                "gems": base_kill_gems + bonus_gems,
                                "keys": bonus_keys,
                            }
                        )

                # Reload current player after crediting kill reward
                player = self.db.get_player(player.user_id) or player
                # Spawn next higher tier boss immediately!
                next_boss = self.get_or_spawn_world_boss(ts)
            else:
                self.db.update_world_boss(boss)

            exp_gain, levels_gained = self._grant_exp(player, raw_exp, stats)
            new_achs = self.check_achievements(player, ts)
            self._sync_combat_power(player)
            self.db.save_player(player)

        return {
            "boss": boss,
            "next_boss": next_boss,
            "dealt": dealt,
            "crits": crits,
            "turns_survived": turns_survived,
            "gold": gold_gain,
            "exp": exp_gain,
            "levels_gained": levels_gained,
            "essence": essence_gain,
            "boss_killed": boss_killed,
            "mvp_rewards": mvp_rewards,
            "rankings": self.db.get_world_boss_rankings(boss.id, limit=5),
            "achievements": new_achs,
        }

    # =========================================================================
    # Shop, Rotating Mystery Shop, Relic Chests (Gacha) & Selling
    # =========================================================================
    def buy_supply_item(
        self, user_id: str, offer_id: str, now_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, now_ts=ts)
        offer = SUPPLY_SHOP_BY_ID.get(offer_id)
        if offer is None:
            raise RPGError("找不到此商店商品。")

        bucket = f"daily:{self.today_key(ts)}"
        with self.db.transaction():
            bought = self.db.get_shop_purchased_qty(player.user_id, bucket, offer_id)
            if offer["daily_limit"] > 0 and bought >= offer["daily_limit"]:
                raise RPGError(f"此商品今日限購 **{offer['daily_limit']}** 次，請明日再來！")

            currency = offer["currency"]
            price = offer["price"]
            if currency == "gold":
                if player.gold < price:
                    raise RPGError(f"金幣不足！需要 **{price:,} 金幣**（目前 `{player.gold:,}`）。")
                player.gold -= price
            else:
                if player.gems < price:
                    raise RPGError(f"星鑽不足！需要 **{price:,} 星鑽**（目前 `{player.gems:,}`）。")
                player.gems -= price

            self.db.add_item(player.user_id, offer["item_id"], offer["qty"])
            self.db.record_shop_purchase(player.user_id, bucket, offer_id, 1)
            self.db.save_player(player)

        return {
            "offer": offer,
            "item": ITEMS[offer["item_id"]],
            "player": player,
        }

    def get_mystery_shop(
        self, player: PlayerProfile, now_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        epoch = ts // MYSTERY_SHOP_REFRESH_SECONDS
        resets_at = (epoch + 1) * MYSTERY_SHOP_REFRESH_SECONDS
        bucket = f"mystery:{epoch}"
        rng = random.Random(f"val-dc-mystery-{epoch}")

        # Deterministic 5 rotating discounted offers per 6-hour epoch
        pool: List[Dict[str, Any]] = [
            {"key": "ms_stones_12", "name": "折扣強化石禮包 (初級強化石 x12)", "type": "item", "item_id": "enhance_stone", "qty": 12, "currency": "gold", "price": 1950, "discount": "32% OFF"},
            {"key": "ms_adv_stones_4", "name": "折扣星輝石禮包 (星輝強化石 x4)", "type": "item", "item_id": "adv_enhance_stone", "qty": 4, "currency": "gold", "price": 6200, "discount": "31% OFF"},
            {"key": "ms_stamina_2", "name": "特惠體力包 (體力恢復劑 x2)", "type": "item", "item_id": "stamina_elixir", "qty": 2, "currency": "gold", "price": 1650, "discount": "31% OFF"},
            {"key": "ms_protect_1", "name": "特價強化保護卷軸 x1", "type": "item", "item_id": "protect_scroll", "qty": 1, "currency": "gems", "price": 30, "discount": "33% OFF"},
            {"key": "ms_relic_key_1", "name": "特價星界秘寶鑰匙 x1", "type": "item", "item_id": "relic_key", "qty": 1, "currency": "gems", "price": 65, "discount": "28% OFF"},
            {"key": "ms_mithril_15", "name": "商隊秘銀礦石組 (秘銀礦 x15)", "type": "item", "item_id": "mithril_ore", "qty": 15, "currency": "gold", "price": 4200, "discount": "25% OFF"},
            {"key": "ms_dragon_10", "name": "走私龍血晶石組 (龍血晶石 x10)", "type": "item", "item_id": "dragon_crystal", "qty": 10, "currency": "gold", "price": 7800, "discount": "25% OFF"},
            {"key": "ms_boss_ess_8", "name": "黑市首領魂晶組 (首領魂晶 x8)", "type": "item", "item_id": "boss_essence", "qty": 8, "currency": "gold", "price": 4800, "discount": "30% OFF"},
            {"key": "ms_epic_gear", "name": "神秘鑑定裝備箱 (必得史詩以上)", "type": "gear_box", "min_rarity": "epic", "currency": "gems", "price": 75, "discount": "限定特惠"},
        ]
        offers = rng.sample(pool, k=5)
        purchased = self.db.get_shop_bucket_purchases(player.user_id, bucket)
        return {
            "bucket": bucket,
            "resets_at": resets_at,
            "offers": offers,
            "purchased": purchased,
        }

    def buy_mystery_offer(
        self, user_id: str, offer_key: str, now_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, now_ts=ts)
        mshop = self.get_mystery_shop(player, ts)
        offer = next((o for o in mshop["offers"] if o["key"] == offer_key), None)
        if offer is None:
            raise RPGError("此神秘商店商品已過期或不存在，請重新開啟商店。")

        bucket = mshop["bucket"]
        with self.db.transaction():
            if self.db.get_shop_purchased_qty(player.user_id, bucket, offer_key) >= 1:
                raise RPGError("本輪神秘商店已購買過此特惠商品，請等待下次刷新！")

            price = offer["price"]
            if offer["currency"] == "gold":
                if player.gold < price:
                    raise RPGError(f"金幣不足！需要 **{price:,} 金幣**。")
                player.gold -= price
            else:
                if player.gems < price:
                    raise RPGError(f"星鑽不足！需要 **{price:,} 星鑽**。")
                player.gems -= price

            gear_reward: Optional[EquipmentItem] = None
            if offer["type"] == "item":
                self.db.add_item(player.user_id, offer["item_id"], offer["qty"])
            else:
                tier = min(6, max(1, 1 + player.level // 18 + (1 if player.rebirth_count > 0 else 0)))
                rarity = self._pick_weighted([("epic", 60), ("legendary", 32), ("mythic", 8)])
                eq, fb_gold = self._try_add_equipment(player.user_id, tier=tier, rarity=rarity, now_ts=ts)
                if eq:
                    gear_reward = eq
                else:
                    player.gold += fb_gold

            self.db.record_shop_purchase(player.user_id, bucket, offer_key, 1)
            self.db.save_player(player)

        return {"offer": offer, "gear": gear_reward, "player": player}

    def open_chest(
        self, user_id: str, chest_type: str = "wooden", now_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, now_ts=ts)
        if len(self.db.get_equipment(player.user_id)) >= MAX_EQUIPMENT_CAPACITY:
            raise RPGError(f"裝備背包已滿（{MAX_EQUIPMENT_CAPACITY} 件），請先清理背包再抽箱！")

        tier = min(6, max(1, 1 + player.level // 18 + (1 if player.rebirth_count > 0 else 0)))
        with self.db.transaction():
            used_currency = ""
            bonus_items: Dict[str, int] = {}
            if chest_type == "wooden":
                cost = 1500
                if player.gold < cost:
                    raise RPGError(f"金幣不足！開啟冒險者木箱需要 **{cost:,} 金幣**。")
                player.gold -= cost
                used_currency = f"{cost:,} 金幣"
                rarity = self._pick_weighted([("uncommon", 42), ("rare", 38), ("epic", 16), ("legendary", 4)])
                bonus_items["enhance_stone"] = random.randint(1, 3)
            elif chest_type == "astral":
                if self.db.get_item_qty(player.user_id, "relic_key") >= 1:
                    self.db.add_item(player.user_id, "relic_key", -1)
                    used_currency = "🗝️ 星界秘寶鑰匙 x1"
                elif player.gems >= 100:
                    player.gems -= 100
                    used_currency = "💎 100 星鑽"
                else:
                    raise RPGError("星鑽或鑰匙不足！開啟星界秘寶箱需要 **1 把星界秘寶鑰匙** 或 **100 星鑽**。")

                player.gacha_pity_legendary += 1
                player.gacha_pity_mythic += 1

                if player.gacha_pity_mythic >= 30:
                    rarity = "mythic"
                elif player.gacha_pity_legendary >= 10:
                    rarity = self._pick_weighted([("legendary", 85), ("mythic", 15)])
                else:
                    rarity = self._pick_weighted([("rare", 35), ("epic", 42), ("legendary", 18), ("mythic", 5)])

                if rarity == "mythic":
                    player.gacha_pity_mythic = 0
                    player.gacha_pity_legendary = 0
                elif rarity == "legendary":
                    player.gacha_pity_legendary = 0

                bonus_items["enhance_stone"] = random.randint(3, 6)
                if rarity in ("legendary", "mythic"):
                    bonus_items["adv_enhance_stone"] = random.randint(1, 2)
            else:
                raise RPGError("無效的寶箱類型。")

            item = self._build_equipment_obj(
                user_id=player.user_id, tier=tier, rarity=rarity, now_ts=ts
            )
            saved = self.db.add_equipment(item)
            for iid, q in bonus_items.items():
                self.db.add_item(player.user_id, iid, q)
            self.db.save_player(player)

        return {
            "chest_type": chest_type,
            "used_currency": used_currency,
            "gear": saved,
            "bonus_items": bonus_items,
            "pity_legendary": player.gacha_pity_legendary,
            "pity_mythic": player.gacha_pity_mythic,
        }

    def sell_ores(self, user_id: str, keep_each: int = 10) -> Dict[str, Any]:
        """Sell excess ores while keeping `keep_each` of every ore type for crafting."""
        player = self.require_player(user_id)
        with self.db.transaction():
            inv = self.db.get_inventory(player.user_id)
            sold_items: Dict[str, int] = {}
            total_gold = 0
            for item_id, qty in inv.items():
                meta = ITEMS.get(item_id)
                if not meta or meta["category"] != "ore":
                    continue
                sell_qty = max(0, qty - keep_each)
                if sell_qty <= 0:
                    continue
                self.db.add_item(player.user_id, item_id, -sell_qty)
                earned = sell_qty * int(meta["sell"])
                total_gold += earned
                sold_items[item_id] = sell_qty

            if not sold_items:
                raise RPGError(f"沒有可出售的多餘礦石（會自動保留每種礦石各 {keep_each} 個供鍛造使用）。")

            player.gold += total_gold
            new_achs = self.check_achievements(player)
            self.db.save_player(player)

        return {"sold_items": sold_items, "gold": total_gold, "achievements": new_achs}

    def use_consumable(
        self, user_id: str, item_id: str, now_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, now_ts=ts)
        if item_id != "stamina_elixir":
            raise RPGError("此道具僅限在戰鬥中自動/手動使用，或請使用對應系統指令。")
        with self.db.transaction():
            if self.db.get_item_qty(player.user_id, "stamina_elixir") < 1:
                raise RPGError("你沒有 **⚡ 體力恢復劑**！可於 `/rpg shop` 購買或完成每日簽到獲得。")
            self.db.add_item(player.user_id, "stamina_elixir", -1)
            gain = ITEMS["stamina_elixir"]["stamina"]
            player.stamina += gain
            self.db.save_player(player)
        return {"stamina_gained": gain, "new_stamina": player.stamina}

    # =========================================================================
    # Daily Check-in, Quests, Expeditions, Promotion, Class Change & Rebirth
    # =========================================================================
    def daily_checkin(
        self, user_id: str, display_name: Optional[str] = None, now_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, display_name=display_name, now_ts=ts)
        today = self.today_key(ts)
        yesterday = self.yesterday_key(ts)

        if player.last_checkin_date == today:
            raise RPGError("你今天已經簽到過了！明天再來領取連續簽到獎勵吧 📅")

        with self.db.transaction():
            if player.last_checkin_date == yesterday:
                player.checkin_streak += 1
            else:
                player.checkin_streak = 1
            player.last_checkin_date = today
            player.total_checkins += 1

            cycle_day = ((player.checkin_streak - 1) % 7) + 1
            reward = DAILY_CHECKIN_REWARDS[cycle_day - 1]
            gold_gain = int(round(reward["gold"] * (1.0 + 0.04 * min(player.level, 100))))
            gems_gain = reward["gems"]

            player.gold += gold_gain
            player.gems += gems_gain
            for iid, q in reward["items"].items():
                self.db.add_item(player.user_id, iid, q)

            new_achs = self.check_achievements(player, ts)
            self.db.save_player(player)

        return {
            "streak": player.checkin_streak,
            "cycle_day": cycle_day,
            "total_checkins": player.total_checkins,
            "gold": gold_gain,
            "gems": gems_gain,
            "items": reward["items"],
            "achievements": new_achs,
        }

    def get_quests_status(
        self, user_id: str, now_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, now_ts=ts)
        dkey = self.today_key(ts)
        wkey = self.week_key(ts)
        d_rows = self.db.get_quests(player.user_id, "daily", dkey)
        w_rows = self.db.get_quests(player.user_id, "weekly", wkey)

        daily_list = []
        for q in DAILY_QUESTS:
            st = d_rows.get(q["id"], {"progress": 0, "target": q["target"], "claimed": False})
            daily_list.append({**q, **st, "period_type": "daily", "period_key": dkey})

        weekly_list = []
        for q in WEEKLY_QUESTS:
            st = w_rows.get(q["id"], {"progress": 0, "target": q["target"], "claimed": False})
            weekly_list.append({**q, **st, "period_type": "weekly", "period_key": wkey})

        return {"daily": daily_list, "weekly": weekly_list}

    def claim_all_quests(
        self, user_id: str, now_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, now_ts=ts)
        status = self.get_quests_status(player.user_id, ts)
        claimable = [
            q
            for q in (status["daily"] + status["weekly"])
            if q["progress"] >= q["target"] and not q["claimed"]
        ]
        if not claimable:
            raise RPGError("目前沒有已完成且尚未領取的任務獎勵！")

        with self.db.transaction():
            stats = self.compute_stats(player)
            total_gold = 0
            total_gems = 0
            total_raw_exp = 0
            total_items: Dict[str, int] = {}

            for q in claimable:
                self.db.mark_quest_claimed(
                    player.user_id, q["period_type"], q["period_key"], q["id"]
                )
                total_gold += q["gold"]
                total_gems += q["gems"]
                total_raw_exp += q["exp"]
                for iid, qty in q["items"].items():
                    total_items[iid] = total_items.get(iid, 0) + qty

            player.gold += total_gold
            player.gems += total_gems
            for iid, qty in total_items.items():
                self.db.add_item(player.user_id, iid, qty)
            exp_gain, levels_gained = self._grant_exp(player, total_raw_exp, stats)
            new_achs = self.check_achievements(player, ts)
            self._sync_combat_power(player)
            self.db.save_player(player)

        return {
            "claimed_count": len(claimable),
            "claimed_names": [q["name"] for q in claimable],
            "gold": total_gold,
            "gems": total_gems,
            "exp": exp_gain,
            "levels_gained": levels_gained,
            "items": total_items,
            "achievements": new_achs,
        }

    def start_expedition(
        self, user_id: str, expedition_id: str, now_ts: Optional[int] = None
    ) -> ActiveExpedition:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, now_ts=ts)
        edef = EXPEDITIONS_BY_ID.get(expedition_id)
        if edef is None:
            raise RPGError("找不到指定的冒險派遣任務。")
        if player.level < edef["min_level"] and player.rebirth_count == 0:
            raise RPGError(f"派遣 **{edef['name']}** 需要 **Lv.{edef['min_level']}**。")
        cur = self.db.get_expedition(player.user_id)
        if cur is not None:
            raise RPGError("你目前已經有進行中的冒險派遣！請等待完成後領取獎勵。")

        ends_at = ts + edef["duration_sec"]
        self.db.set_expedition(player.user_id, expedition_id, ts, ends_at)
        return ActiveExpedition(
            user_id=player.user_id,
            expedition_id=expedition_id,
            started_at=ts,
            ends_at=ends_at,
            claimed=False,
        )

    def claim_expedition(
        self, user_id: str, now_ts: Optional[int] = None
    ) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, now_ts=ts)
        exp_obj = self.db.get_expedition(player.user_id)
        if exp_obj is None:
            raise RPGError("你目前沒有進行中的冒險派遣。")
        if ts < exp_obj.ends_at:
            rem = exp_obj.ends_at - ts
            mins = max(1, (rem + 59) // 60)
            raise RPGError(f"冒險派遣尚未歸來！預計還需約 **{mins} 分鐘**（<t:{exp_obj.ends_at}:R>）。")

        edef = EXPEDITIONS_BY_ID[exp_obj.expedition_id]
        with self.db.transaction():
            stats = self.compute_stats(player)
            lv_scale = 1.0 + 0.03 * player.level
            gold_gain = int(round(edef["base_gold"] * lv_scale * (1.0 + stats.gold_bonus)))
            raw_exp = int(round(edef["base_exp"] * lv_scale))
            ore_id = random.choice(edef["ore_pool"])
            ore_qty = random.randint(*edef["ore_qty"])
            loot = {ore_id: ore_qty, "enhance_stone": max(1, edef["duration_sec"] // 3600)}

            gear_reward: Optional[EquipmentItem] = None
            if random.random() <= edef["gear_chance"]:
                tier = min(6, max(1, 1 + player.level // 18))
                eq, fb_gold = self._try_add_equipment(player.user_id, tier=tier, now_ts=ts)
                if eq:
                    gear_reward = eq
                else:
                    gold_gain += fb_gold

            for iid, q in loot.items():
                self.db.add_item(player.user_id, iid, q)
            player.gold += gold_gain
            exp_gain, levels_gained = self._grant_exp(player, raw_exp, stats)
            self.db.clear_expedition(player.user_id)
            new_achs = self.check_achievements(player, ts)
            self._sync_combat_power(player)
            self.db.save_player(player)

        return {
            "expedition": edef,
            "gold": gold_gain,
            "exp": exp_gain,
            "levels_gained": levels_gained,
            "loot": loot,
            "gear": gear_reward,
            "achievements": new_achs,
        }

    def promote_class(self, user_id: str) -> Dict[str, Any]:
        player = self.require_player(user_id)
        next_tier = player.promo_tier + 1
        if next_tier not in PROMOTION_REQUIREMENTS:
            raise RPGError("你的職業已經達到最高階級（三轉終極稱號）！")

        req = PROMOTION_REQUIREMENTS[next_tier]
        if player.level < req["min_level"] and player.rebirth_count == 0:
            raise RPGError(f"進行 {next_tier} 轉需要達到 **Lv.{req['min_level']}**。")
        if player.gold < req["gold"]:
            raise RPGError(f"金幣不足！需要 **{req['gold']:,} 金幣**。")

        with self.db.transaction():
            missing = []
            for mid, qty in req["materials"].items():
                have = self.db.get_item_qty(player.user_id, mid)
                if have < qty:
                    missing.append(f"{ITEMS[mid]['emoji']} {ITEMS[mid]['name']} `{have}/{qty}`")
            if missing:
                raise RPGError("轉職材料不足：\n" + "\n".join(missing))

            player.gold -= req["gold"]
            self.db.consume_items(player.user_id, req["materials"])
            old_title = get_class_title(player.class_id, player.promo_tier)
            player.promo_tier = next_tier
            new_title = get_class_title(player.class_id, player.promo_tier)
            stats = self._sync_combat_power(player)
            self.db.save_player(player)

        return {"old_title": old_title, "new_title": new_title, "stats": stats}

    def change_class(self, user_id: str, new_class_id: str) -> Dict[str, Any]:
        if new_class_id not in CLASSES:
            raise RPGError("無效的職業。")
        player = self.require_player(user_id)
        if player.class_id == new_class_id:
            raise RPGError("你目前已經是這個職業了！")

        with self.db.transaction():
            if self.db.get_item_qty(player.user_id, "class_emblem") < 1:
                raise RPGError("轉換職業需要 **🎖️ 轉職徽章 x1**（可於 `/rpg shop` 購買）。")
            self.db.add_item(player.user_id, "class_emblem", -1)
            old_title = get_class_title(player.class_id, player.promo_tier)
            player.class_id = new_class_id
            new_title = get_class_title(player.class_id, player.promo_tier)
            stats = self._sync_combat_power(player)
            self.db.save_player(player)

        return {"old_title": old_title, "new_title": new_title, "stats": stats}

    def rebirth(self, user_id: str, now_ts: Optional[int] = None) -> Dict[str, Any]:
        ts = self.now() if now_ts is None else now_ts
        player = self.require_player(user_id, now_ts=ts)
        if player.level < MAX_LEVEL:
            raise RPGError(f"必須達到滿級 **Lv.{MAX_LEVEL}** 才能進行星界轉生（目前 Lv.{player.level}）！")

        with self.db.transaction():
            player.rebirth_count += 1
            player.level = 1
            player.exp = 0
            bonus_gems = 200 + 50 * player.rebirth_count
            player.gems += bonus_gems
            player.stamina = max_stamina_for_player(1, player.rebirth_count)
            player.stamina_updated_at = ts
            new_achs = self.check_achievements(player, ts)
            stats = self._sync_combat_power(player)
            self.db.save_player(player)

        return {
            "rebirth_count": player.rebirth_count,
            "bonus_gems": bonus_gems,
            "stats": stats,
            "achievements": new_achs,
        }

    def set_active_title(self, user_id: str, achievement_id: str) -> str:
        player = self.require_player(user_id)
        if achievement_id == "none":
            player.active_title = ""
            self.db.save_player(player)
            return ""
        unlocked = self.db.get_achievements(player.user_id)
        if achievement_id not in unlocked or achievement_id not in ACHIEVEMENTS_BY_ID:
            raise RPGError("你尚未解鎖此成就稱號！")
        title = ACHIEVEMENTS_BY_ID[achievement_id]["title"]
        player.active_title = title
        self.db.save_player(player)
        return title
