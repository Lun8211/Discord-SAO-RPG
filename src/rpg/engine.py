"""Unified SAO Aincrad 100-Floor RPGEngine public facade (ZERO discord imports)."""

from __future__ import annotations

import re
import time
from typing import Any

from src.rpg.content.loader import SAOContentBundle, load_and_validate_all
from src.rpg.database import RPGDatabase
from src.rpg.models import (
    BASE_WEAPON_STYLES,
    BossMode,
    CombatSession,
    CursorColor,
    GameError,
    GameMode,
    RoguelikeRun,
    ZoneType,
)
from src.rpg.systems import (
    combat as combat_sys,
)
from src.rpg.systems import (
    economy as economy_sys,
)
from src.rpg.systems import (
    party as party_sys,
)
from src.rpg.systems import (
    progression as prog_sys,
)
from src.rpg.systems import (
    social as social_sys,
)
from src.rpg.systems import (
    tower as tower_sys,
)

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_SEVEN_LIFE_SKILLS: tuple[str, ...] = (
    "battle_regen",
    "searching",
    "stealth",
    "appraisal",
    "blacksmithing",
    "cooking",
    "mining",
)
_KARMA_DECAY_INTERVAL_SEC = 3600 * 6  # +5 karma recovery every 6 hours toward Green cursor


def _now(now_ts: int | None) -> int:
    return int(now_ts if now_ts is not None else time.time())


class RPGEngine:
    """Pure UI-agnostic facade integrating all SAO Aincrad 100-Floor multiplayer RPG systems."""

    def __init__(
        self,
        db: RPGDatabase,
        content: SAOContentBundle | None = None,
        *,
        timezone_offset_hours: int = 8,
    ) -> None:
        self.db = db
        self.content: SAOContentBundle = content if content is not None else load_and_validate_all()
        self.timezone_offset_hours = int(timezone_offset_hours)
        self.active_combats: dict[str, CombatSession] = {}
        self.active_roguelikes: dict[str, RoguelikeRun] = {}
        self.multiplayer = party_sys.MultiplayerCoordinator(self.db, self.content)

    # =========================================================================
    # Core / World
    # =========================================================================
    def create_character(
        self,
        user_id: str,
        display_name: str,
        weapon_style: str = "sword",
        mode: str = "standard",
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        """Link Start! Register a new player in Floor 1 Town of Beginnings."""
        ts = _now(now_ts)
        uid = str(user_id or "").strip()
        if not uid:
            raise GameError("玩家識別編號不可為空。", code="INVALID_USER_ID")
        if self.db.get_player(uid) is not None:
            raise GameError("你已經登入艾恩葛朗特並建立了角色，無法重複創角！", code="ALREADY_REGISTERED")

        raw_name = str(display_name if display_name is not None else "")
        if _CONTROL_CHAR_RE.search(raw_name):
            raise GameError("角色名稱不可包含控制字元！", code="INVALID_DISPLAY_NAME")
        clean_name = raw_name.strip()
        if not clean_name or len(clean_name) > 32:
            raise GameError("角色名稱不可空白且長度須為 1～32 字元。", code="INVALID_DISPLAY_NAME")

        style = str(weapon_style or "").strip().lower()
        if style not in BASE_WEAPON_STYLES:
            raise GameError(
                f"無效的初始武器流派：{weapon_style}（艾恩葛朗特沒有魔法職業；僅支援 {', '.join(BASE_WEAPON_STYLES)}）。",
                code="INVALID_WEAPON_STYLE",
            )

        norm_mode = str(mode or "").strip().lower()
        if norm_mode not in (GameMode.STANDARD, GameMode.HARDCORE):
            raise GameError(
                f"無效的遊戲模式：{mode}（僅支援 standard 一般模式 或 hardcore 死亡遊戲一命模式）。",
                code="INVALID_GAME_MODE",
            )

        player = self.db.create_player(
            uid,
            clean_name,
            class_id=style,
            now_ts=ts,
            weapon_style=style,
            game_mode=norm_mode,
        )
        # Equip authentic starter skills & starting Col / supplies
        wspec = self.content.weapons_equipment.get("weapon_classes", {}).get(style, {})
        player.skill_slots = list(wspec.get("starter_skill_ids") or ["slant"])[:3]
        player.col = 500
        player.current_floor = 1
        player.highest_cleared_floor = 0
        player.zone = ZoneType.TOWN
        player.cursor_color = CursorColor.GREEN
        player.karma = 0
        player.stat_points = 5
        player.talent_points = 1
        player.world_boss_attempts = 3
        player.world_boss_attempts_date = time.strftime("%Y-%m-%d", time.gmtime(ts))

        stats = combat_sys.compute_full_player_stats(self.db, self.content, player, floor=1, now_ts=ts)
        player.hp = stats.max_hp
        player.sp = stats.max_sp
        player.max_sp = stats.max_sp
        player.combat_power = stats.combat_power
        player.updated_at = ts
        self.db.save_player(player)

        # Starter supplies + 7 life skills initialized at Lv.1 + Yui F1 log
        self.db.add_item(uid, "hp_potion_t1", 3)
        self.db.upsert_mastery(uid, style, 1, 0)
        for sk in _SEVEN_LIFE_SKILLS:
            self.db.upsert_mastery(uid, sk, 1, 0)
        self.db.unlock_yui_log(uid, "yui_log_f01", ts)

        mode_zh = "死亡遊戲一命模式（Hardcore）" if norm_mode == GameMode.HARDCORE else "標準攻略模式（Standard）"
        return {
            "ok": True,
            "user_id": uid,
            "display_name": clean_name,
            "weapon_style": style,
            "game_mode": norm_mode,
            "floor": 1,
            "current_floor": 1,
            "max_unlocked_floor": 1,
            "zone": ZoneType.TOWN,
            "col": player.col,
            "cursor_color": CursorColor.GREEN,
            "skill_slots": list(player.skill_slots),
            "player": player,
            "stats": stats,
            "message": (
                f"⚔️ 【Link Start！】歡迎登入浮游城艾恩葛朗特第 1 層【起始之鎮】！\n"
                f"卡迪納爾系統已登錄攻略者【{clean_name}】｜流派：{wspec.get('name', style)}｜模式：{mode_zh}｜"
                f"初始資金 500 柯爾（本世界不存在玩家魔法，以純粹劍技攻略至第 100 層紅玉宮吧！）。"
            ),
        }

    def get_profile(self, user_id: str, now_ts: int | None = None) -> dict[str, Any]:
        ts = _now(now_ts)
        player = self.db.get_player(user_id)
        if player is None:
            raise GameError("尚未建立艾恩葛朗特角色，請先執行 Link Start 創角！", code="PLAYER_NOT_FOUND")

        # Karma decay/redemption over elapsed time toward Green cursor
        if player.karma < 0 and player.updated_at > 0 and ts > player.updated_at:
            elapsed = ts - player.updated_at
            steps = elapsed // _KARMA_DECAY_INTERVAL_SEC
            if steps > 0:
                player.karma = min(0, player.karma + int(steps) * 10)
                if player.karma >= 0:
                    player.cursor_color = CursorColor.GREEN
                elif player.karma > -25:
                    player.cursor_color = CursorColor.ORANGE
                player.updated_at = ts
                self.db.save_player(player)
        elif player.cursor_color not in (CursorColor.GREEN, CursorColor.ORANGE, CursorColor.RED):
            player.cursor_color = CursorColor.GREEN
            self.db.save_player(player)

        stats = combat_sys.compute_full_player_stats(self.db, self.content, player, floor=player.current_floor, now_ts=ts)
        if stats.combat_power != player.combat_power:
            player.combat_power = stats.combat_power
            self.db.save_player(player)

        equipment = self.db.get_equipment(user_id, equipped_only=False, include_escrowed=False)
        inventory = self.db.get_inventory(user_id)
        mastery = self.db.get_mastery(user_id)
        life_skills = {
            sk: {
                "level": int(mastery.get(sk, {"level": 1, "exp": 0})["level"]),
                "exp": int(mastery.get(sk, {"level": 1, "exp": 0})["exp"]),
            }
            for sk in _SEVEN_LIFE_SKILLS
        }
        talents = self.db.get_talents(user_id)
        loadouts = self.db.get_gear_loadouts(user_id)
        pending_loot = self.db.get_pending_loot(user_id, unclaimed_only=True)
        guild = self.db.get_guild(player.guild_id) if player.guild_id is not None else None
        party = self.db.get_user_active_party(user_id)
        miasma_exp_bonus = round(player.miasma_exp_stacks * 0.15, 2)
        flt = dict(player.loot_filter or {"min_rarity": "plain", "min_level": 1, "blocked_slots": []})

        return {
            "ok": True,
            "user_id": player.user_id,
            "display_name": player.display_name,
            "level": player.level,
            "exp": player.exp,
            "col": player.col,
            "gold": player.gold,
            "current_floor": player.current_floor,
            "highest_cleared_floor": player.highest_cleared_floor,
            "max_unlocked_floor": player.max_unlocked_floor,
            "zone": player.zone,
            "weapon_style": player.weapon_style,
            "game_mode": player.game_mode,
            "cursor_color": player.cursor_color,
            "karma": player.karma,
            "hp": player.hp or stats.max_hp,
            "max_hp": stats.max_hp,
            "sp": player.sp,
            "max_sp": stats.max_sp,
            "miasma_stacks": player.miasma_stacks,
            "miasma_exp_stacks": player.miasma_exp_stacks,
            "miasma_exp_bonus": miasma_exp_bonus,
            "exp_multiplier": round(1.0 + miasma_exp_bonus, 2),
            "stat_points": player.stat_points,
            "unspent_stat_points": player.stat_points,
            "talent_points": player.talent_points,
            "unspent_talent_points": player.talent_points,
            "str_stat": player.str_stat,
            "agi_stat": player.agi_stat,
            "vit_stat": player.vit_stat,
            "dex_stat": player.dex_stat,
            "luk_stat": player.luk_stat,
            "skill_slots": list(player.skill_slots),
            "unique_skills": list(player.unique_skills),
            "active_title": player.active_title,
            "rebirth_count": player.rebirth_count,
            "combat_power": stats.combat_power,
            "survival_streak": player.survival_streak,
            "survival_config": dict(player.survival_config),
            "loot_filter": flt,
            "min_rarity": flt.get("min_rarity", "plain"),
            "min_level": flt.get("min_level", 1),
            "is_dead": player.is_dead,
            "downed_until": player.downed_until,
            "last_death_log": player.last_death_log,
            "world_boss_attempts": player.world_boss_attempts,
            "equipment": equipment,
            "inventory": inventory,
            "mastery": mastery,
            "life_skills": life_skills,
            "talents": talents,
            "loadouts": loadouts,
            "pending_loot_count": len(pending_loot),
            "pending_loot": pending_loot,
            "guild": guild,
            "party": party,
            "player": player,
            "stats": stats,
            "computed_stats": stats,
            "message": f"🪪 攻略者【{player.display_name}】Lv.{player.level}｜第 {player.current_floor} 層（{player.zone}）｜戰力 {stats.combat_power}｜{player.col} 柯爾",
        }

    def travel_zone(self, user_id: str, zone: str, now_ts: int | None = None) -> dict[str, Any]:
        in_combat = user_id in self.active_combats and not self.active_combats[user_id].finished
        return tower_sys.travel_zone(self.db, self.content, user_id, zone, now_ts=now_ts, in_active_combat=in_combat)

    def teleport_floor(self, user_id: str, target_floor: int, now_ts: int | None = None) -> dict[str, Any]:
        in_combat = user_id in self.active_combats and not self.active_combats[user_id].finished
        return tower_sys.teleport_floor(self.db, self.content, user_id, target_floor, now_ts=now_ts, in_active_combat=in_combat)

    def get_monument_of_life(self, limit: int = 10, now_ts: int | None = None) -> dict[str, Any]:
        return tower_sys.get_monument_of_life(self.db, limit=limit, now_ts=now_ts)

    def get_argo_intel(self, user_id: str | None = None, floor: int | None = None) -> dict[str, Any]:
        return tower_sys.get_argo_intel(self.db, self.content, user_id=user_id, floor=floor)

    def get_yui_logs(self, user_id: str) -> dict[str, Any]:
        return tower_sys.get_yui_logs(self.db, self.content, user_id)

    def set_survival_config(
        self,
        user_id: str,
        *,
        auto_potion_pct: float | None = None,
        auto_crystal_pct: float | None = None,
        auto_retreat_pct: float | None = None,
        stop_on_no_potion: bool | None = None,
    ) -> dict[str, Any]:
        return tower_sys.set_survival_config(
            self.db,
            user_id,
            auto_potion_pct=auto_potion_pct,
            auto_crystal_pct=auto_crystal_pct,
            auto_retreat_pct=auto_retreat_pct,
            stop_on_no_potion=stop_on_no_potion,
        )

    # =========================================================================
    # 100-Floor Tower & Exploration
    # =========================================================================
    def get_floor_info(self, floor: int, user_id: str | None = None) -> dict[str, Any]:
        return tower_sys.get_floor_info(self.db, self.content, floor, user_id=user_id)

    def explore_floor(
        self,
        user_id: str,
        steps: int = 1,
        now_ts: int | None = None,
        rng_seed: int | None = None,
    ) -> dict[str, Any]:
        return tower_sys.explore_floor(
            self.db, self.content, self.active_combats, user_id, steps=steps, now_ts=now_ts, rng_seed=rng_seed
        )

    def open_chest(
        self,
        user_id: str,
        action: str = "open",
        now_ts: int | None = None,
        rng_seed: int | None = None,
    ) -> dict[str, Any]:
        return tower_sys.open_chest(
            self.db, self.content, self.active_combats, user_id, action=action, now_ts=now_ts, rng_seed=rng_seed
        )

    def enter_secret_realm(
        self,
        user_id: str,
        action: str = "explore",
        now_ts: int | None = None,
        rng_seed: int | None = None,
    ) -> dict[str, Any]:
        return tower_sys.enter_secret_realm(
            self.db, self.content, user_id, action=action, now_ts=now_ts, rng_seed=rng_seed
        )

    def start_roguelike(
        self,
        user_id: str,
        now_ts: int | None = None,
        rng_seed: int | None = None,
    ) -> dict[str, Any]:
        return tower_sys.start_roguelike(
            self.db, self.content, self.active_roguelikes, user_id, now_ts=now_ts, rng_seed=rng_seed
        )

    def step_roguelike(
        self,
        user_id: str,
        node_index: int = 0,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        return tower_sys.step_roguelike(
            self.db, self.content, self.active_roguelikes, self.active_combats, user_id, node_index=node_index, now_ts=now_ts
        )

    def extract_roguelike(self, user_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return tower_sys.extract_roguelike(
            self.db, self.active_roguelikes, self.active_combats, user_id, now_ts=now_ts
        )

    # =========================================================================
    # Combat, Bosses & Skills
    # =========================================================================
    def start_floor_boss(
        self,
        user_id: str,
        floor: int | None = None,
        mode: str = BossMode.NORMAL,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        return combat_sys.start_floor_boss(
            self.db, self.content, self.active_combats, user_id, floor=floor, mode=mode, now_ts=now_ts
        )

    def combat_action(
        self,
        user_id: str,
        action: str,
        skill_id: str | None = None,
        item_id: str | None = None,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        return combat_sys.combat_action(
            self.db,
            self.content,
            self.active_combats,
            self.active_roguelikes,
            user_id,
            action,
            skill_id=skill_id,
            item_id=item_id,
            now_ts=now_ts,
        )

    def claim_pending_loot(self, user_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return tower_sys.claim_pending_loot(self.db, user_id, now_ts=now_ts)

    def switch_weapon_style(self, user_id: str, weapon_style: str) -> dict[str, Any]:
        return combat_sys.switch_weapon_style(self.db, self.content, self.active_combats, user_id, weapon_style)

    def set_skill_slots(self, user_id: str, skill_ids: list[str]) -> dict[str, Any]:
        return combat_sys.set_skill_slots(self.db, self.content, self.active_combats, user_id, skill_ids)

    def unlock_unique_skill(self, user_id: str, unique_skill_id: str) -> dict[str, Any]:
        return combat_sys.unlock_unique_skill(self.db, self.content, user_id, unique_skill_id)

    def allocate_stats(self, user_id: str, stat_deltas: dict[str, int]) -> dict[str, Any]:
        return prog_sys.allocate_stats(self.db, self.content, user_id, stat_deltas)

    def allocate_talent(self, user_id: str, talent_id: str) -> dict[str, Any]:
        return prog_sys.allocate_talent(self.db, self.content, user_id, talent_id)

    def respec_talents(self, user_id: str) -> dict[str, Any]:
        return prog_sys.respec_talents(self.db, self.content, self.active_combats, user_id)

    # =========================================================================
    # Real-Human Multiplayer Co-op, World Boss & Duels
    # =========================================================================
    def create_party(
        self,
        leader_id: str,
        floor: int,
        boss_mode: str = BossMode.NORMAL,
        max_size: int = 6,
        is_raid_alliance: bool = False,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        return self.multiplayer.create_party(
            leader_id,
            floor,
            boss_mode=boss_mode,
            max_size=max_size,
            is_raid_alliance=is_raid_alliance,
            now_ts=now_ts,
        )

    def join_party(
        self, party_id: str, user_id: str, role: str = "dps", now_ts: int | None = None
    ) -> dict[str, Any]:
        return self.multiplayer.join_party(party_id, user_id, role=role, now_ts=now_ts)

    def leave_party(self, party_id: str, user_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return self.multiplayer.leave_party(party_id, user_id, now_ts=now_ts)

    def set_party_role(self, party_id: str, user_id: str, role: str) -> dict[str, Any]:
        return self.multiplayer.set_party_role(party_id, user_id, role)

    def set_party_ready(self, party_id: str, user_id: str, ready: bool) -> dict[str, Any]:
        return self.multiplayer.set_party_ready(party_id, user_id, ready)

    def toggle_potion_sharing(self, party_id: str, user_id: str, enabled: bool) -> dict[str, Any]:
        return self.multiplayer.toggle_potion_sharing(party_id, user_id, enabled)

    def enter_boss_room(self, party_id: str, leader_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return self.multiplayer.enter_boss_room(party_id, leader_id, now_ts=now_ts)

    def start_party_raid(self, party_id: str, leader_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return self.multiplayer.start_party_raid(party_id, leader_id, now_ts=now_ts)

    def submit_raid_action(
        self,
        raid_id: str,
        user_id: str,
        action: str,
        skill_id: str | None = None,
        item_id: str | None = None,
        target_idx: int = 0,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        return self.multiplayer.submit_raid_action(
            raid_id,
            user_id,
            action,
            skill_id=skill_id,
            item_id=item_id,
            target_idx=target_idx,
            now_ts=now_ts,
        )

    def resolve_raid_round(
        self,
        raid_id: str,
        requester_id: str | None = None,
        force_timeout: bool = False,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        return self.multiplayer.resolve_raid_round(
            raid_id, requester_id=requester_id, force_timeout=force_timeout, now_ts=now_ts
        )

    def party_group_teleport(
        self, party_id: str, leader_id: str, target_floor: int, now_ts: int | None = None
    ) -> dict[str, Any]:
        return self.multiplayer.party_group_teleport(party_id, leader_id, target_floor, now_ts=now_ts)

    def rescue_downed_player(
        self, rescuer_id: str, target_user_id: str, now_ts: int | None = None
    ) -> dict[str, Any]:
        return self.multiplayer.rescue_downed_player(rescuer_id, target_user_id, now_ts=now_ts)

    def attack_floor_world_boss(
        self, user_id: str, party_id: str | None = None, now_ts: int | None = None
    ) -> dict[str, Any]:
        return self.multiplayer.attack_floor_world_boss(user_id, party_id=party_id, now_ts=now_ts)

    def challenge_duel(
        self,
        challenger_id: str,
        target_id: str,
        mode: str = "first_strike",
        wager_col: int = 0,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        return self.multiplayer.challenge_duel(
            challenger_id,
            target_id,
            mode=mode,
            wager_col=wager_col,
            now_ts=now_ts,
            active_combats=self.active_combats,
        )

    def accept_duel(self, duel_id: str, target_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return self.multiplayer.accept_duel(duel_id, target_id, now_ts=now_ts)

    def duel_action(
        self,
        duel_id: str,
        user_id: str,
        action: str,
        skill_id: str | None = None,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        return self.multiplayer.duel_action(duel_id, user_id, action, skill_id=skill_id, now_ts=now_ts)

    # =========================================================================
    # Equipment, Workshop, Cooking, Gathering & Shop
    # =========================================================================
    def equip_item(self, user_id: str, item_uid: int) -> dict[str, Any]:
        return economy_sys.equip_item(self.db, self.content, self.active_combats, user_id, item_uid)

    def toggle_lock_item(self, user_id: str, item_uid: int) -> dict[str, Any]:
        return economy_sys.toggle_lock_item(self.db, user_id, item_uid)

    def save_loadout(self, user_id: str, slot_index: int, name: str) -> dict[str, Any]:
        return economy_sys.save_loadout(self.db, user_id, slot_index, name)

    def apply_loadout(self, user_id: str, slot_index: int) -> dict[str, Any]:
        return economy_sys.apply_loadout(self.db, self.content, self.active_combats, user_id, slot_index)

    def set_loot_filter(
        self,
        user_id: str,
        *,
        min_rarity: str | None = None,
        min_level: int | None = None,
        blocked_slots: list[str] | None = None,
    ) -> dict[str, Any]:
        return economy_sys.set_loot_filter(
            self.db, user_id, min_rarity=min_rarity, min_level=min_level, blocked_slots=blocked_slots
        )

    def mine_gather(
        self,
        user_id: str,
        floor: int | None = None,
        now_ts: int | None = None,
        rng_seed: int | None = None,
    ) -> dict[str, Any]:
        return prog_sys.mine_gather(
            self.db, self.content, self.active_combats, user_id, floor=floor, now_ts=now_ts, rng_seed=rng_seed
        )

    def forge_craft(self, user_id: str, recipe_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return economy_sys.forge_craft(self.db, self.content, user_id, recipe_id, now_ts=now_ts)

    def enhance_equipment(
        self,
        user_id: str,
        item_uid: int,
        use_protection: bool = False,
        now_ts: int | None = None,
        rng_seed: int | None = None,
    ) -> dict[str, Any]:
        return economy_sys.enhance_equipment(
            self.db,
            self.content,
            user_id,
            item_uid,
            use_protection=use_protection,
            now_ts=now_ts,
            rng_seed=rng_seed,
        )

    def apply_magic_stone(
        self, user_id: str, item_uid: int, stone_id: str, rng_seed: int | None = None
    ) -> dict[str, Any]:
        return economy_sys.apply_magic_stone(
            self.db, self.content, user_id, item_uid, stone_id, rng_seed=rng_seed
        )

    def fuse_items(self, user_id: str, recipe_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return economy_sys.fuse_items(self.db, self.content, user_id, recipe_id, now_ts=now_ts)

    def cook_dish(
        self,
        user_id: str,
        recipe_id: str,
        timing_perfect: bool = False,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        return economy_sys.cook_dish(
            self.db, self.content, user_id, recipe_id, timing_perfect=timing_perfect, now_ts=now_ts
        )

    def start_big_pot_stew(
        self,
        user_id: str,
        recipe_id: str,
        party_or_guild_id: str,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        return economy_sys.start_big_pot_stew(
            self.db, self.content, user_id, recipe_id, party_or_guild_id, now_ts=now_ts
        )

    def claim_stew(self, user_id: str, stew_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return economy_sys.claim_stew(self.db, self.content, user_id, stew_id, now_ts=now_ts)

    def buy_shop_item(
        self, user_id: str, item_id: str, qty: int = 1, now_ts: int | None = None
    ) -> dict[str, Any]:
        return economy_sys.buy_shop_item(self.db, self.content, user_id, item_id, qty=qty, now_ts=now_ts)

    def gacha_pull(
        self,
        user_id: str,
        chest_type: str = "standard",
        count: int = 1,
        now_ts: int | None = None,
        rng_seed: int | None = None,
    ) -> dict[str, Any]:
        return economy_sys.gacha_pull(
            self.db, self.content, user_id, chest_type=chest_type, count=count, now_ts=now_ts, rng_seed=rng_seed
        )

    # =========================================================================
    # Guilds, Marketplace, Quests, Achievements & Endgame
    # =========================================================================
    def create_guild(self, user_id: str, name: str, tag: str, now_ts: int | None = None) -> dict[str, Any]:
        return social_sys.create_guild(self.db, user_id, name, tag, now_ts=now_ts)

    def join_guild(self, user_id: str, guild_id: int, now_ts: int | None = None) -> dict[str, Any]:
        return social_sys.join_guild(self.db, user_id, guild_id, now_ts=now_ts)

    def leave_guild(self, user_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return social_sys.leave_guild(self.db, user_id, now_ts=now_ts)

    def set_guild_rank(self, leader_id: str, target_id: str, rank_name: str) -> dict[str, Any]:
        return social_sys.set_guild_rank(self.db, leader_id, target_id, rank_name)

    def guild_contribute(self, user_id: str, col_amount: int, now_ts: int | None = None) -> dict[str, Any]:
        return social_sys.guild_contribute(self.db, user_id, col_amount, now_ts=now_ts)

    def guild_warehouse_deposit(self, user_id: str, item_uid: int, now_ts: int | None = None) -> dict[str, Any]:
        return social_sys.guild_warehouse_deposit(self.db, user_id, item_uid, now_ts=now_ts)

    def guild_warehouse_withdraw(self, user_id: str, warehouse_id: int, now_ts: int | None = None) -> dict[str, Any]:
        return social_sys.guild_warehouse_withdraw(self.db, self.active_combats, user_id, warehouse_id, now_ts=now_ts)

    def guild_activate_buff(self, user_id: str, buff_id: str = "rally", now_ts: int | None = None) -> dict[str, Any]:
        return social_sys.guild_activate_buff(self.db, user_id, buff_id=buff_id, now_ts=now_ts)

    def start_guild_raid(self, user_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return social_sys.start_guild_raid(self.db, user_id, now_ts=now_ts)

    def list_market_item(
        self,
        seller_id: str,
        *,
        item_uid: int | None = None,
        item_id: str | None = None,
        qty: int = 1,
        price_col: int,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        return social_sys.list_market_item(
            self.db,
            self.content,
            seller_id,
            item_uid=item_uid,
            item_id=item_id,
            qty=qty,
            price_col=price_col,
            now_ts=now_ts,
        )

    def search_market(
        self,
        *,
        weapon_class: str | None = None,
        rarity: str | None = None,
        affix1: str | None = None,
        affix2: str | None = None,
        slot: str | None = None,
        max_price: int | None = None,
    ) -> dict[str, Any]:
        return social_sys.search_market(
            self.db,
            weapon_class=weapon_class,
            rarity=rarity,
            affix1=affix1,
            affix2=affix2,
            slot=slot,
            max_price=max_price,
        )

    def buy_market_item(self, buyer_id: str, listing_id: int, now_ts: int | None = None) -> dict[str, Any]:
        return social_sys.buy_market_item(self.db, buyer_id, listing_id, now_ts=now_ts)

    def cancel_market_listing(self, seller_id: str, listing_id: int) -> dict[str, Any]:
        return social_sys.cancel_market_listing(self.db, seller_id, listing_id)

    def claim_daily(self, user_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return prog_sys.claim_daily(self.db, self.content, user_id, now_ts=now_ts)

    def get_quests(self, user_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return prog_sys.get_quests(self.db, self.content, user_id, now_ts=now_ts)

    def choose_story_option(
        self, user_id: str, chapter_id: str, choice_id: str, now_ts: int | None = None
    ) -> dict[str, Any]:
        return prog_sys.choose_story_option(self.db, self.content, user_id, chapter_id, choice_id, now_ts=now_ts)

    def claim_quest(self, user_id: str, quest_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return prog_sys.claim_quest(self.db, self.content, user_id, quest_id, now_ts=now_ts)

    def start_expedition(self, user_id: str, expedition_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return prog_sys.start_expedition(self.db, self.content, user_id, expedition_id, now_ts=now_ts)

    def claim_expedition(self, user_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return prog_sys.claim_expedition(self.db, self.content, user_id, now_ts=now_ts)

    def turn_in_achievement_gear(self, user_id: str, item_uid: int) -> dict[str, Any]:
        return prog_sys.turn_in_achievement_gear(self.db, self.content, user_id, item_uid)

    def claim_achievement(self, user_id: str, achievement_id: str) -> dict[str, Any]:
        return prog_sys.claim_achievement(self.db, self.content, user_id, achievement_id)

    def equip_title(self, user_id: str, title_id: str) -> dict[str, Any]:
        return prog_sys.equip_title(self.db, self.content, user_id, title_id)

    def rebirth_player(self, user_id: str, confirm: bool = False, now_ts: int | None = None) -> dict[str, Any]:
        return prog_sys.rebirth_player(self.db, self.content, self.active_combats, user_id, confirm=confirm, now_ts=now_ts)

    def start_boss_rush(self, user_id: str, now_ts: int | None = None) -> dict[str, Any]:
        return prog_sys.start_boss_rush(self.db, self.content, self.active_combats, user_id, now_ts=now_ts)

    def enter_nightmare_floor(
        self, user_id: str, nightmare_floor: int, now_ts: int | None = None
    ) -> dict[str, Any]:
        return prog_sys.enter_nightmare_floor(
            self.db, self.content, self.active_combats, user_id, nightmare_floor, now_ts=now_ts
        )

    def get_leaderboard(self, category: str, limit: int = 10) -> dict[str, Any]:
        return prog_sys.get_leaderboard(self.db, category, limit=limit)


RPGError = GameError

__all__ = ["GameError", "RPGEngine", "RPGError"]
