"""SAO Multi-Human Co-op Party, Raid Alliance, Synchronized Raid Combat, World Boss & PvP Duels (ZERO discord imports)."""

from __future__ import annotations

import copy
import random
import threading
import time
import uuid
import zlib
from typing import Any

from src.rpg.content.loader import SAOContentBundle, resolve_floor_config
from src.rpg.database import RPGDatabase
from src.rpg.models import (
    BossCombatState,
    BossMode,
    CombatSession,
    CoopRaidSession,
    DamageType,
    DuelSession,
    GameError,
    GameMode,
    PartyLobby,
    PartyMemberState,
    PlayerProfile,
    Rarity,
    ZoneType,
)
from src.rpg.systems.boss_engine import (
    apply_damage_to_boss,
    build_boss_state,
    get_boss_skill_id,
    get_current_phase_spec,
    step_boss_turn,
)
from src.rpg.systems.combat import (
    CRYSTAL_IDS,
    _find_best_potion,
    _skill_compatible_with_player,
    apply_debuff,
    apply_exp_and_level_up,
    calculate_enemy_hit,
    calculate_player_hit,
    compute_full_player_stats,
)
from src.rpg.systems.tower import (
    enhance_crystal_for_tier,
    generate_equipment_item,
    generate_named_equipment,
    grant_or_queue_equipment,
)


def _public_boss_snapshot(boss: BossCombatState) -> BossCombatState:
    """Return a shallow UI-safe boss snapshot without leaking unrevealed future phases or stale telegraphs."""
    snap = copy.copy(boss)
    snap.phases = []
    if not boss.telegraph_active:
        snap.telegraph_skill_name = ""
        snap.telegraph_callout = ""
    return snap


def _public_raid_snapshot(raid: CoopRaidSession, round_logs: list[str]) -> CoopRaidSession:
    """Return a shallow UI-safe raid snapshot scoped to the current round's logs and active telegraph."""
    snap = copy.copy(raid)
    snap.boss = _public_boss_snapshot(raid.boss)
    snap.logs = list(round_logs)
    return snap

ROLE_ALIASES: dict[str, str] = {
    "tank": "tank",
    "前排坦": "tank",
    "坦": "tank",
    "dps": "dps",
    "輸出": "dps",
    "breaker": "breaker",
    "破防": "breaker",
    "support": "support",
    "輔助": "support",
}
VALID_RAID_ACTIONS: frozenset[str] = frozenset(
    {"attack", "skill", "switch", "defend", "parry", "item", "crystal", "retreat"}
)
VALID_DUEL_MODES: dict[str, str] = {
    "first_strike": "first_strike",
    "first": "first_strike",
    "初擊勝負": "first_strike",
    "full": "full_duel",
    "full_duel": "full_duel",
    "完全勝負": "full_duel",
}


def _now(now_ts: int | None) -> int:
    return int(now_ts if now_ts is not None else time.time())


def _normalize_role(role: str) -> str:
    r = str(role or "dps").strip().lower()
    if r in ROLE_ALIASES:
        return ROLE_ALIASES[r]
    raw = str(role or "").strip()
    if raw in ROLE_ALIASES:
        return ROLE_ALIASES[raw]
    raise GameError(f"無效的隊伍職責：{role}（支援：前排坦 tank／輸出 dps／破防 breaker／輔助 support）", code="INVALID_PARTY_ROLE")


class MultiplayerCoordinator:
    """Thread-safe coordinator managing real-human parties, co-op raids, world bosses, and duels."""

    def __init__(self, db: RPGDatabase, content: SAOContentBundle) -> None:
        self.db = db
        self.content = content
        self._global_lock = threading.RLock()
        self._party_locks: dict[str, threading.RLock] = {}
        self.active_raids: dict[str, CoopRaidSession] = {}
        self.active_duels: dict[str, DuelSession] = {}

    def _lock_for(self, key: str) -> threading.RLock:
        with self._global_lock:
            lk = self._party_locks.get(key)
            if lk is None:
                lk = threading.RLock()
                self._party_locks[key] = lk
            return lk

    def _build_member_state(
        self, player: PlayerProfile, *, role: str = "dps", floor: int = 1, now_ts: int = 0
    ) -> PartyMemberState:
        stats = compute_full_player_stats(self.db, self.content, player, floor=floor, now_ts=now_ts)
        return PartyMemberState(
            user_id=player.user_id,
            display_name=player.display_name,
            role=role,
            weapon_style=player.weapon_style,
            level=player.level,
            combat_power=stats.combat_power,
            is_ready=False,
            potion_sharing=False,
            frontline_stance=(role == "tank"),
            max_hp=stats.max_hp,
            hp=stats.max_hp,
            max_sp=stats.max_sp,
            sp=stats.max_sp,
            aggro=50.0 if role == "tank" else 10.0,
            joined_at=now_ts,
        )

    def _propagate_party_miasma(self, party: PartyLobby, ts: int) -> int:
        """If any party member carries Miasma, spread stacks to teammates WITHOUT granting EXP bonus."""
        players = [self.db.get_player(uid) for uid in party.members]
        valid_players = [p for p in players if p is not None]
        max_miasma = max((p.miasma_stacks for p in valid_players), default=0)
        if max_miasma > 0:
            for p in valid_players:
                if p.miasma_stacks < max_miasma:
                    p.miasma_stacks = max_miasma
                    # Strictly NO free miasma_exp_stacks from contagion!
                    p.updated_at = ts
                    self.db.save_player(p)
        return max_miasma

    # =========================================================================
    # Party Lobby & Raid Alliance
    # =========================================================================
    def create_party(
        self,
        leader_id: str,
        floor: int,
        *,
        boss_mode: str = BossMode.NORMAL,
        max_size: int = 6,
        is_raid_alliance: bool = False,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        ts = _now(now_ts)
        if isinstance(floor, bool) or not isinstance(floor, int) or not (1 <= floor <= 100):
            raise GameError(f"無效的攻略樓層：{floor}（必須為 1～100）", code="INVALID_FLOOR")
        norm_mode = str(boss_mode or BossMode.NORMAL).strip().lower()
        if norm_mode not in (BossMode.FIRST_KILL, BossMode.NORMAL, BossMode.TEAM_BOSS, BossMode.WORLD_BOSS):
            raise GameError(f"不支援的頭目挑戰模式：{boss_mode}", code="INVALID_BOSS_MODE")

        cap_limit = 24 if is_raid_alliance else 6
        if isinstance(max_size, bool) or not isinstance(max_size, int) or max_size < 2 or max_size > cap_limit:
            raise GameError(
                f"隊伍人數上限無效（一般隊伍 2～6 人，大型攻略團 2～24 人）：{max_size}",
                code="INVALID_PARTY_SIZE",
            )

        with self._global_lock:
            leader = self.db.get_player(leader_id)
            if leader is None:
                raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
            if leader.is_dead:
                raise GameError("硬派角色已陣亡，無法建立組隊大廳。", code="HARDCORE_DEAD")
            if floor > leader.max_unlocked_floor:
                raise GameError(f"你尚未解鎖第 {floor} 層，無法建立該層攻略隊伍！", code="FLOOR_LOCKED")
            existing = self.db.get_user_active_party(leader_id)
            if existing is not None:
                raise GameError(f"你已經在隊伍【{existing.party_id}】中，請先離隊再建立新隊伍！", code="ALREADY_IN_PARTY")

            pid = f"pty_{uuid.uuid4().hex[:8]}"
            mstate = self._build_member_state(leader, role="dps", floor=floor, now_ts=ts)
            lobby = PartyLobby(
                party_id=pid,
                leader_id=leader_id,
                floor=floor,
                boss_mode=norm_mode,
                max_size=max_size,
                is_raid_alliance=bool(is_raid_alliance),
                status="lobby",
                members={leader_id: mstate},
                created_at=ts,
                updated_at=ts,
            )
            self.db.save_party(lobby)
            label = "大型攻略團（Raid Alliance）" if is_raid_alliance else "真人共鬥隊伍"
            return {
                "ok": True,
                "party_id": pid,
                "party": lobby,
                "lobby": lobby,
                "floor": floor,
                "boss_mode": norm_mode,
                "max_size": max_size,
                "is_raid_alliance": bool(is_raid_alliance),
                "message": f"🚩 已建立第 {floor} 層【{label}】（編號 `{pid}`，上限 {max_size} 人）！",
            }

    def join_party(
        self,
        party_id: str,
        user_id: str,
        *,
        role: str = "dps",
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        ts = _now(now_ts)
        norm_role = _normalize_role(role)
        with self._lock_for(party_id):
            lobby = self.db.get_party(party_id)
            if lobby is None or lobby.status == "disbanded":
                raise GameError(f"找不到組隊大廳：{party_id}", code="PARTY_NOT_FOUND")
            if lobby.status != "lobby":
                raise GameError("此隊伍已進入頭目房或正在激戰中，無法中途加入！", code="PARTY_LOCKED")
            if user_id in lobby.members:
                raise GameError("你已經在這支隊伍裡面了！", code="ALREADY_IN_PARTY")
            other = self.db.get_user_active_party(user_id)
            if other is not None and other.party_id != party_id:
                raise GameError(f"你已在其他隊伍【{other.party_id}】中，請先離隊！", code="ALREADY_IN_OTHER_PARTY")
            if len(lobby.members) >= lobby.max_size:
                raise GameError(f"隊伍已滿員（{len(lobby.members)}/{lobby.max_size}）！", code="PARTY_FULL")

            player = self.db.get_player(user_id)
            if player is None:
                raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
            if player.is_dead:
                raise GameError("硬派角色已陣亡，無法加入攻略隊。", code="HARDCORE_DEAD")

            lobby.members[user_id] = self._build_member_state(player, role=norm_role, floor=lobby.floor, now_ts=ts)
            lobby.updated_at = ts
            self.db.save_party(lobby)
            contagion = self._propagate_party_miasma(lobby, ts)
            extra = f"（⚠️ 秘境瘴氣傳染：全隊承受 {contagion} 層瘴氣增傷，但無額外經驗加成！）" if contagion > 0 else ""
            return {
                "ok": True,
                "party_id": party_id,
                "party": lobby,
                "member_count": len(lobby.members),
                "role": norm_role,
                "miasma_contagion": contagion,
                "message": f"🤝 {player.display_name} 加入隊伍 `{party_id}`（職責：{norm_role}，{len(lobby.members)}/{lobby.max_size}）！{extra}",
            }

    def leave_party(
        self,
        party_id: str,
        user_id: str,
        *,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        ts = _now(now_ts)
        with self._lock_for(party_id):
            lobby = self.db.get_party(party_id)
            if lobby is None:
                raise GameError(f"找不到組隊大廳：{party_id}", code="PARTY_NOT_FOUND")
            if user_id not in lobby.members:
                raise GameError("你並不在此隊伍中。", code="NOT_IN_PARTY")
            if lobby.status == "in_combat":
                raise GameError("頭目激戰進行中無法直接離隊，請在戰鬥內執行撤退！", code="CANNOT_LEAVE_IN_COMBAT")

            lobby.members.pop(user_id, None)
            if not lobby.members:
                self.db.delete_party(party_id)
                return {
                    "ok": True,
                    "party_id": party_id,
                    "disbanded": True,
                    "new_leader_id": None,
                    "message": f"💨 隊伍 `{party_id}` 所有成員已離開，隊伍自動解散。",
                }

            promoted: str | None = None
            if lobby.leader_id == user_id:
                ordered = sorted(lobby.members.values(), key=lambda m: (m.joined_at, m.user_id))
                lobby.leader_id = ordered[0].user_id
                promoted = lobby.leader_id
            lobby.updated_at = ts
            self.db.save_party(lobby)
            extra = f"隊長已自動移交給 `{promoted}`。" if promoted else ""
            return {
                "ok": True,
                "party_id": party_id,
                "disbanded": False,
                "new_leader_id": lobby.leader_id,
                "party": lobby,
                "message": f"🚪 已離開隊伍 `{party_id}`。{extra}",
            }

    def set_party_role(self, party_id: str, user_id: str, role: str) -> dict[str, Any]:
        norm_role = _normalize_role(role)
        with self._lock_for(party_id):
            lobby = self.db.get_party(party_id)
            if lobby is None:
                raise GameError(f"找不到組隊大廳：{party_id}", code="PARTY_NOT_FOUND")
            if user_id not in lobby.members:
                raise GameError("你並不在此隊伍中。", code="NOT_IN_PARTY")
            lobby.members[user_id].role = norm_role
            lobby.members[user_id].frontline_stance = norm_role == "tank"
            self.db.save_party(lobby)
            return {
                "ok": True,
                "party_id": party_id,
                "user_id": user_id,
                "role": norm_role,
                "party": lobby,
                "message": f"🎯 隊伍職責已設定為【{norm_role}】！",
            }

    def set_party_ready(self, party_id: str, user_id: str, ready: bool) -> dict[str, Any]:
        if not isinstance(ready, bool):
            raise GameError("準備狀態必須為布林值。", code="INVALID_READY_STATE")
        with self._lock_for(party_id):
            lobby = self.db.get_party(party_id)
            if lobby is None:
                raise GameError(f"找不到組隊大廳：{party_id}", code="PARTY_NOT_FOUND")
            if user_id not in lobby.members:
                raise GameError("你並不在此隊伍中。", code="NOT_IN_PARTY")
            lobby.members[user_id].is_ready = ready
            self.db.save_party(lobby)
            ready_cnt = sum(1 for m in lobby.members.values() if m.is_ready)
            return {
                "ok": True,
                "party_id": party_id,
                "user_id": user_id,
                "is_ready": ready,
                "ready_count": ready_cnt,
                "total_members": len(lobby.members),
                "party": lobby,
                "message": f"{'✅ 已完成整備！' if ready else '⏸️ 已取消準備'}（目前準備人數 {ready_cnt}/{len(lobby.members)}）",
            }

    def toggle_potion_sharing(self, party_id: str, user_id: str, enabled: bool) -> dict[str, Any]:
        with self._lock_for(party_id):
            lobby = self.db.get_party(party_id)
            if lobby is None:
                raise GameError(f"找不到組隊大廳：{party_id}", code="PARTY_NOT_FOUND")
            if user_id not in lobby.members:
                raise GameError("你並不在此隊伍中。", code="NOT_IN_PARTY")
            lobby.members[user_id].potion_sharing = bool(enabled)
            self.db.save_party(lobby)
            # Also sync into any active raid for this party
            for raid in self.active_raids.values():
                if raid.party_id == party_id and user_id in raid.members:
                    raid.members[user_id].potion_sharing = bool(enabled)
            return {
                "ok": True,
                "party_id": party_id,
                "user_id": user_id,
                "potion_sharing": bool(enabled),
                "message": f"🧪 藥水共享【我要出藥】已{'開啟（隊友重傷時將自動捐贈回復藥水）' if enabled else '關閉'}！",
            }

    def enter_boss_room(
        self,
        party_id: str,
        leader_id: str,
        *,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        """Separate step 1: Leader opens the Floor Boss Room doors for the whole party."""
        ts = _now(now_ts)
        with self._lock_for(party_id):
            lobby = self.db.get_party(party_id)
            if lobby is None:
                raise GameError(f"找不到組隊大廳：{party_id}", code="PARTY_NOT_FOUND")
            if lobby.leader_id != leader_id:
                raise GameError("僅隊長可下令進入頭目房！", code="LEADER_ONLY_ACTION")
            if lobby.status == "in_combat":
                raise GameError("隊伍已經在頭目戰中！", code="ALREADY_IN_COMBAT")

            contagion = self._propagate_party_miasma(lobby, ts)
            lobby.status = "in_boss_room"
            lobby.updated_at = ts
            self.db.save_party(lobby)
            for uid in lobby.members:
                p = self.db.get_player(uid)
                if p:
                    p.current_floor = lobby.floor
                    p.zone = ZoneType.BOSS_ROOM
                    p.updated_at = ts
                    self.db.save_player(p)

            fcfg = resolve_floor_config(lobby.floor, self.content)
            return {
                "ok": True,
                "party_id": party_id,
                "status": lobby.status,
                "floor": lobby.floor,
                "boss_name": fcfg["boss"]["name"],
                "miasma_warning": contagion > 0,
                "miasma_stacks": contagion,
                "party": lobby,
                "message": f"🚪 攻略隊全體踏入第 {lobby.floor} 層頭目房【{fcfg['boss']['name']}】！請隊長確認陣型後下令開戰！",
            }

    def start_party_raid(
        self,
        party_id: str,
        leader_id: str,
        *,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        """Separate step 2: Engage the Floor Boss in synchronized multi-human turn-based combat."""
        ts = _now(now_ts)
        with self._lock_for(party_id):
            lobby = self.db.get_party(party_id)
            if lobby is None:
                raise GameError(f"找不到組隊大廳：{party_id}", code="PARTY_NOT_FOUND")
            if lobby.leader_id != leader_id:
                raise GameError("僅隊長可下令正式開戰！", code="LEADER_ONLY_ACTION")
            if lobby.status == "in_combat":
                raise GameError("隊伍已在頭目激戰中！", code="ALREADY_IN_COMBAT")
            if lobby.status != "in_boss_room":
                raise GameError("請先由隊長下令進入頭目房（enter_boss_room），再正式開戰！", code="NOT_IN_BOSS_ROOM")
            unready = [m.display_name for m in lobby.members.values() if not m.is_ready]
            if unready:
                raise GameError(
                    f"尚有隊員未完成整備準備（{', '.join(unready)}），無法開戰！",
                    code="MEMBERS_NOT_READY",
                )

            self._propagate_party_miasma(lobby, ts)
            boss = build_boss_state(
                lobby.floor,
                mode=lobby.boss_mode,
                party_size=len(lobby.members),
                bundle=self.content,
            )
            p1 = get_current_phase_spec(boss)
            p1_sid = get_boss_skill_id(boss, p1)
            boss.observed_skills.append(p1_sid)

            raid_members: dict[str, PartyMemberState] = {}
            vanguard_id: str | None = None
            for uid, m in lobby.members.items():
                p = self.db.get_player(uid)
                if p is None:
                    continue
                stats = compute_full_player_stats(self.db, self.content, p, floor=lobby.floor, now_ts=ts)
                rm = PartyMemberState(
                    user_id=uid,
                    display_name=p.display_name,
                    role=m.role,
                    weapon_style=p.weapon_style,
                    level=p.level,
                    combat_power=stats.combat_power,
                    is_ready=True,
                    potion_sharing=m.potion_sharing,
                    frontline_stance=(m.role == "tank"),
                    max_hp=stats.max_hp,
                    hp=stats.max_hp,
                    max_sp=stats.max_sp,
                    sp=stats.max_sp,
                    aggro=100.0 if m.role == "tank" else 20.0,
                    joined_at=m.joined_at,
                )
                raid_members[uid] = rm
                if m.role == "tank" and vanguard_id is None:
                    vanguard_id = uid
                p.current_floor = lobby.floor
                p.zone = ZoneType.BOSS_ROOM
                p.in_boss_battle = True
                p.updated_at = ts
                self.db.save_player(p)
                self.db.record_boss_intel_seen(uid, boss.boss_id, p1_sid, ts)

            if vanguard_id is None and raid_members:
                vanguard_id = leader_id if leader_id in raid_members else next(iter(raid_members))

            raid_id = f"raid_{uuid.uuid4().hex[:10]}"
            intro = str(p1.get("on_enter_broadcast") or f"⚔️ 多人攻略戰開打！第 {lobby.floor} 層頭目【{boss.name}】降臨！")
            raid = CoopRaidSession(
                raid_id=raid_id,
                party_id=party_id,
                leader_id=leader_id,
                floor=lobby.floor,
                boss_mode=lobby.boss_mode,
                boss=boss,
                members=raid_members,
                turn=1,
                turn_started_at=ts,
                turn_timeout_sec=25,
                pending_actions={},
                vanguard_user_id=vanguard_id,
                switch_chain=0,
                last_switch_user_id=None,
                finished=False,
                victory=False,
                logs=[intro],
                started_at=ts,
            )
            self.active_raids[raid_id] = raid
            lobby.status = "in_combat"
            lobby.updated_at = ts
            self.db.save_party(lobby)
            pub_boss = _public_boss_snapshot(boss)
            pub_raid = _public_raid_snapshot(raid, [intro])
            return {
                "ok": True,
                "raid_id": raid_id,
                "party_id": party_id,
                "floor": lobby.floor,
                "boss_mode": lobby.boss_mode,
                "hp_bars": boss.hp_bars,
                "boss_state": pub_boss,
                "boss": pub_boss,
                "vanguard_user_id": vanguard_id,
                "raid": pub_raid,
                "in_combat": True,
                "message": intro,
            }

    # =========================================================================
    # Synchronized Turn-Based Multi-Human Co-op Combat
    # =========================================================================
    def submit_raid_action(
        self,
        raid_id: str,
        user_id: str,
        action: str,
        *,
        skill_id: str | None = None,
        item_id: str | None = None,
        target_idx: int = 0,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        # Capture caller's observed turn epoch BEFORE waiting on the per-raid lock so concurrent
        # double-clicks from Round N cannot bleed into Round N+1 after immediate auto-resolution.
        pre_raid = self.active_raids.get(raid_id)
        observed_turn = pre_raid.turn if pre_raid is not None else None
        ts = _now(now_ts)
        act = str(action or "").strip().lower()
        if act not in VALID_RAID_ACTIONS:
            raise GameError(f"無效的共鬥指令：{action}", code="INVALID_RAID_ACTION")

        with self._lock_for(raid_id):
            raid = self.active_raids.get(raid_id)
            if raid is None or raid.finished:
                raise GameError("此多人攻略戰已結束或不存在。", code="RAID_NOT_ACTIVE")
            if user_id not in raid.members:
                raise GameError("你並非此攻略團成員。", code="NOT_IN_RAID")
            if observed_turn is not None and raid.turn != observed_turn:
                raise GameError(
                    f"第 {observed_turn} 回合已結算完成，重複提交指令已攔截，請於第 {raid.turn} 回合重新行動！",
                    code="STALE_ROUND_SUBMISSION",
                )

            member = raid.members[user_id]
            if member.is_downed or member.is_retreated:
                raise GameError("你目前處於瀕死倒地或已撤退狀態，無法行動！", code="MEMBER_CANNOT_ACT")
            if user_id in raid.pending_actions:
                raise GameError("你本回合已經提交過行動指令，請等待其他隊友！", code="DUPLICATE_RAID_ACTION")

            # Stunned player cannot execute Switch!
            if act == "switch":
                if "stun" in member.debuffs:
                    raise GameError("你正處於暈眩狀態，動不了，無法執行交換（Switch）！", code="STUNNED_SWITCH_BLOCKED")
                alive_others = [
                    m for uid, m in raid.members.items() if uid != user_id and not m.is_downed and not m.is_retreated
                ]
                if not alive_others:
                    raise GameError("場上沒有其他存活隊友可供交換（Switch）！", code="NO_ALLY_FOR_SWITCH")

            # Validate crystal-null / F100 retreat & crystals upfront WITHOUT consuming items
            if act == "retreat" and (raid.boss.anti_crystal_zone or raid.floor == 100):
                raise GameError("🚨 此頭目房處於水晶無效化封鎖區，無法撤退！", code="RETREAT_BLOCKED")

            if act in ("item", "crystal"):
                if not item_id:
                    raise GameError("請指定要使用的道具或水晶編號。", code="MISSING_ITEM_ID")
                is_crys = item_id in CRYSTAL_IDS or self.content.items_crystals.get(item_id, {}).get("category") == "crystal"
                if act == "crystal" and not is_crys:
                    raise GameError("指定物品不是 SAO 水晶！", code="NOT_A_CRYSTAL")
                if is_crys and (raid.boss.anti_crystal_zone or raid.floor == 100):
                    raise GameError("🚨 此區域處於【水晶無效化空間】，水晶無法發動（未消耗任何水晶）！", code="CRYSTAL_NULL_BLOCKED")
                if self.db.get_item_qty(user_id, item_id) <= 0:
                    raise GameError("背包內道具數量不足！", code="INSUFFICIENT_ITEM")

            if act == "skill":
                if not skill_id:
                    raise GameError("請指定劍技編號。", code="MISSING_SKILL_ID")
                spec = self.content.sword_skills.get(skill_id)
                p = self.db.get_player(user_id)
                if not isinstance(spec, dict) or p is None:
                    raise GameError(f"未知的劍技：{skill_id}", code="UNKNOWN_SKILL")
                if not _skill_compatible_with_player(p, spec):
                    raise GameError(f"流派無法施放劍技【{spec.get('name', skill_id)}】！", code="INCOMPATIBLE_WEAPON_SKILL")
                if int(member.skill_cooldowns.get(skill_id, 0)) > 0:
                    raise GameError(f"劍技【{spec['name']}】冷卻中！", code="SKILL_ON_COOLDOWN")
                if member.sp < int(spec.get("sp_cost", 15)):
                    raise GameError(f"SP 不足，無法施放【{spec['name']}】！", code="INSUFFICIENT_SP")

            # Wake sleeping player if they manually submit an action again
            member.is_sleeping = False
            member.consecutive_timeouts = 0
            raid.pending_actions[user_id] = {
                "action": act,
                "skill_id": skill_id,
                "item_id": item_id,
                "target_idx": int(target_idx),
                "submitted_at": ts,
            }

            # Check if all active non-sleeping humans have submitted
            required_ids = [
                uid
                for uid, m in raid.members.items()
                if not m.is_downed and not m.is_retreated and not m.is_sleeping
            ]
            if all(uid in raid.pending_actions for uid in required_ids):
                return self._resolve_round_locked(raid, ts, force_timeout=False)

            wait_msg = f"✅ {member.display_name} 已鎖定指令【{act}】（{len(raid.pending_actions)}/{len(required_ids)} 人已行動）。"
            return {
                "ok": True,
                "raid_id": raid_id,
                "turn": raid.turn,
                "round_resolved": False,
                "submitted_count": len(raid.pending_actions),
                "required_count": len(required_ids),
                "finished": False,
                "in_combat": True,
                "raid": _public_raid_snapshot(raid, [wait_msg]),
                "message": wait_msg,
            }

    def resolve_raid_round(
        self,
        raid_id: str,
        *,
        requester_id: str | None = None,
        force_timeout: bool = False,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        """Resolve current raid round (supports 25s AFK timeout auto-Guard & 2-strike `沉睡/託管`)."""
        ts = _now(now_ts)
        with self._lock_for(raid_id):
            raid = self.active_raids.get(raid_id)
            if raid is None or raid.finished:
                raise GameError("此多人攻略戰已結束或不存在。", code="RAID_NOT_ACTIVE")

            elapsed = ts - raid.turn_started_at
            required_ids = [
                uid
                for uid, m in raid.members.items()
                if not m.is_downed and not m.is_retreated and not m.is_sleeping
            ]
            all_submitted = all(uid in raid.pending_actions for uid in required_ids)
            if not all_submitted and not force_timeout and elapsed < raid.turn_timeout_sec:
                if requester_id is not None and requester_id != raid.leader_id:
                    raise GameError("尚有隊友未提交指令且未達 25 秒逾時，非隊長無法強制結算回合！", code="ROUND_NOT_READY")
                if requester_id is None:
                    raise GameError("尚有隊友未提交指令且未達 25 秒回合逾時！", code="ROUND_NOT_READY")

            return self._resolve_round_locked(raid, ts, force_timeout=(not all_submitted))

    def _resolve_round_locked(
        self, raid: CoopRaidSession, ts: int, *, force_timeout: bool
    ) -> dict[str, Any]:
        rgen = random.Random(ts + raid.turn * 97 + zlib.crc32(raid.raid_id.encode("utf-8")) % 997)
        round_logs: list[str] = [f"━━━ 第 {raid.turn} 回合結算（{raid.boss.name}）━━━"]

        # 1. Assign auto-Guard to AFK / sleeping members & update 2-strike sleep flag
        active_members = [m for m in raid.members.values() if not m.is_downed and not m.is_retreated]
        stats_by_uid: dict[str, Any] = {}
        players_by_uid: dict[str, PlayerProfile] = {}
        for m in active_members:
            p = self.db.get_player(m.user_id)
            if p is None:
                continue
            players_by_uid[m.user_id] = p
            stats_by_uid[m.user_id] = compute_full_player_stats(
                self.db, self.content, p, floor=raid.floor, now_ts=ts
            )
            # Tick skill CDs
            for sk in list(m.skill_cooldowns.keys()):
                m.skill_cooldowns[sk] -= 1
                if m.skill_cooldowns[sk] <= 0:
                    m.skill_cooldowns.pop(sk, None)

            if m.user_id not in raid.pending_actions:
                if force_timeout and not m.is_sleeping:
                    m.consecutive_timeouts += 1
                    if m.consecutive_timeouts >= 2:
                        m.is_sleeping = True
                        round_logs.append(f"💤 {m.display_name} 連續 2 回合未行動，已標記為【沉睡/託管】自動防禦！")
                    else:
                        round_logs.append(f"⏱️ {m.display_name} 回合逾時，自動採取防禦姿態！")
                raid.pending_actions[m.user_id] = {"action": "defend", "auto_afk": True}

        # 2. Deterministic ordering: Switch actions first (sorted by SPD/AGI desc, user_id asc), then rest by SPD desc
        def _sort_key(uid: str) -> tuple[int, int, str]:
            act = str(raid.pending_actions.get(uid, {}).get("action", "defend"))
            prio = 0 if act == "switch" else (1 if act in ("defend", "parry", "item", "crystal") else 2)
            spd = stats_by_uid[uid].spd if uid in stats_by_uid else 100
            return (prio, -spd, uid)

        ordered_uids = sorted(
            [m.user_id for m in active_members if m.user_id in players_by_uid],
            key=_sort_key,
        )

        defending_uids: set[str] = set()
        parrying_uids: set[str] = set()
        switch_count_this_round = 0
        boss_killed = False

        for uid in ordered_uids:
            m = raid.members[uid]
            p = players_by_uid[uid]
            st = stats_by_uid[uid]
            cmd = raid.pending_actions.get(uid, {"action": "defend"})
            act = str(cmd.get("action", "defend"))

            if act == "retreat":
                m.is_retreated = True
                p.in_boss_battle = False
                p.zone = ZoneType.TOWN
                p.updated_at = ts
                self.db.save_player(p)
                round_logs.append(f"🏃 {m.display_name} 撤離了頭目戰。")
                continue

            if act == "defend":
                defending_uids.add(uid)
                m.sp = min(m.max_sp, m.sp + 18)
                if m.role == "tank":
                    m.aggro += 40.0
                continue

            if act == "parry":
                parrying_uids.add(uid)
                m.sp = min(m.max_sp, m.sp + 12)
                m.aggro += 30.0
                continue

            if act in ("item", "crystal"):
                iid = str(cmd.get("item_id") or "")
                spec = self.content.items_crystals.get(iid, {})
                eff = spec.get("effect") or {}
                if self.db.consume_items(uid, {iid: 1}):
                    if iid == "healing_crystal" or eff.get("full_heal"):
                        heal = m.max_hp - m.hp
                        m.hp = m.max_hp
                        m.debuffs.pop("doom", None)
                        m.healing_done += max(0, heal)
                        round_logs.append(f"❤️ {m.display_name} 使用回復水晶完全回復並淨化死宣！")
                    elif iid == "antidote_crystal" or eff.get("cleanse_all"):
                        m.debuffs.clear()
                        round_logs.append(f"💚 {m.display_name} 使用解毒水晶淨化所有異常狀態！")
                    elif iid == "teleport_crystal":
                        m.is_retreated = True
                        p.in_boss_battle = False
                        p.zone = ZoneType.TOWN
                        self.db.save_player(p)
                        round_logs.append(f"💎 {m.display_name} 使用轉移水晶安全撤回城鎮！")
                    else:
                        heal = max(1, round(m.max_hp * float(eff.get("heal_hp_pct", 0.3))) + int(eff.get("heal_hp_flat", 100)))
                        m.hp = min(m.max_hp, m.hp + heal)
                        m.healing_done += heal
                        round_logs.append(f"🧪 {m.display_name} 喝下藥水回復 {heal} 生命！")
                continue

            if act == "switch":
                switch_count_this_round += 1
                raid.switch_chain = min(3, raid.switch_chain + 1)
                raid.vanguard_user_id = uid
                raid.last_switch_user_id = uid
                m.aggro += 120.0 * st.aggro_mult
                m.frontline_stance = True
                w_dtype = str(st.active_passives.get("dmg_type", DamageType.SLASH))
                dmg, _crit, _weak = calculate_player_hit(
                    st,
                    raid.boss.defense,
                    dmg_type=w_dtype,
                    target_weaknesses=raid.boss.weaknesses,
                    skill_mult=1.25,
                    switch_chain=raid.switch_chain,
                    target_debuffs=raid.boss.debuffs,
                    rng=rgen,
                )
                bres = apply_damage_to_boss(
                    raid.boss,
                    dmg,
                    attacker_id=uid,
                    dmg_type=w_dtype,
                    break_power=32,
                    switch_chain=raid.switch_chain,
                    bundle=self.content,
                )
                m.damage_dealt += int(bres["damage"])
                round_logs.append(
                    f"⇄ 【SWITCH 連攜 x{raid.switch_chain}！】{m.display_name} 切入前排接手仇恨並斬出 {bres['damage']} 傷害"
                    f"（+{min(75, raid.switch_chain * 25)}% 連攜加成）！"
                )
                round_logs.extend(bres["logs"])
                if bres["killed"]:
                    boss_killed = True
                    break
                continue

            # Attack or Sword Skill
            is_backstab = (
                raid.vanguard_user_id is not None
                and raid.vanguard_user_id != uid
                and raid.vanguard_user_id in raid.members
                and not raid.members[raid.vanguard_user_id].is_downed
            )
            if act == "skill":
                sid = str(cmd.get("skill_id") or "")
                spec = self.content.sword_skills[sid]
                sp_cost = int(spec.get("sp_cost", 15))
                m.sp = max(0, m.sp - sp_cost)
                cd_t = int(spec.get("cooldown_turns", 0))
                if cd_t > 0:
                    m.skill_cooldowns[sid] = cd_t + 1
                dtype = str(spec.get("dmg_type") or st.active_passives.get("dmg_type", DamageType.SLASH))
                mult = float(spec.get("damage_mult", 1.5))
                bp = int(spec.get("break_power", 22))
                is_unique = bool(spec.get("unique_skill", False))
                dmg, crit, _weak = calculate_player_hit(
                    st,
                    raid.boss.defense,
                    dmg_type=dtype,
                    target_weaknesses=raid.boss.weaknesses,
                    skill_mult=mult,
                    is_backstab=is_backstab,
                    switch_chain=raid.switch_chain,
                    target_debuffs=raid.boss.debuffs,
                    rng=rgen,
                )
                bres = apply_damage_to_boss(
                    raid.boss,
                    dmg,
                    attacker_id=uid,
                    dmg_type=dtype,
                    break_power=bp,
                    switch_chain=raid.switch_chain,
                    is_unique_skill=is_unique,
                    bundle=self.content,
                )
                m.damage_dealt += int(bres["damage"])
                m.aggro += int(bres["damage"]) * 0.25 * st.aggro_mult
                round_logs.append(
                    f"⚔️ {m.display_name} 施放【{spec['name']}】造成 {bres['damage']} 傷害"
                    f"{' 🗡️背刺！' if is_backstab else ''}{' 💥暴擊！' if crit else ''}！"
                )
                round_logs.extend(bres["logs"])
                deb = spec.get("debuff")
                if deb and not bres["killed"]:
                    dmsg = apply_debuff(
                        raid.boss.debuffs,
                        str(deb),
                        turns=2,
                        dmg=max(10, round(st.atk * 0.3)),
                        is_boss=True,
                        stun_immune_turns=raid.boss.stun_immune_turns,
                    )
                    if dmsg:
                        round_logs.append(dmsg)
                if bres["killed"]:
                    boss_killed = True
                    break
            else:
                dtype = str(st.active_passives.get("dmg_type", DamageType.SLASH))
                m.sp = min(m.max_sp, m.sp + 10)
                dmg, crit, _weak = calculate_player_hit(
                    st,
                    raid.boss.defense,
                    dmg_type=dtype,
                    target_weaknesses=raid.boss.weaknesses,
                    skill_mult=1.0,
                    is_backstab=is_backstab,
                    switch_chain=raid.switch_chain,
                    target_debuffs=raid.boss.debuffs,
                    rng=rgen,
                )
                bres = apply_damage_to_boss(
                    raid.boss,
                    dmg,
                    attacker_id=uid,
                    dmg_type=dtype,
                    break_power=14,
                    switch_chain=raid.switch_chain,
                    bundle=self.content,
                )
                m.damage_dealt += int(bres["damage"])
                m.aggro += int(bres["damage"]) * 0.2 * st.aggro_mult
                round_logs.append(
                    f"🗡️ {m.display_name} 斬擊造成 {bres['damage']} 傷害{' 🗡️背刺！' if is_backstab else ''}！"
                )
                round_logs.extend(bres["logs"])
                if bres["killed"]:
                    boss_killed = True
                    break

        if switch_count_this_round == 0:
            raid.switch_chain = 0

        # 3. Check Raid Victory!
        if boss_killed or raid.boss.current_hp <= 0:
            return self._settle_raid_victory_locked(raid, ts, round_logs)

        # 4. Boss Turn against party!
        bturn = step_boss_turn(raid.boss)
        round_logs.extend(bturn["logs"])
        if bturn.get("observed_skill_id"):
            for uid in raid.members:
                self.db.record_boss_intel_seen(uid, raid.boss.boss_id, str(bturn["observed_skill_id"]), ts)

        alive_targets = [
            m for m in raid.members.values() if not m.is_downed and not m.is_retreated and m.user_id in stats_by_uid
        ]
        if bturn["acted"] and alive_targets:
            # Determine targets: AoE hits up to all alive (mitigated slightly for backline), else vanguard/highest aggro
            if bturn.get("is_aoe"):
                targets = alive_targets
            else:
                vanguard = (
                    raid.members.get(raid.vanguard_user_id)
                    if raid.vanguard_user_id and raid.vanguard_user_id in raid.members
                    else None
                )
                if vanguard and not vanguard.is_downed and not vanguard.is_retreated:
                    targets = [vanguard]
                else:
                    targets = [max(alive_targets, key=lambda x: x.aggro)]

            # Dual-tank cleave check on F75 Skull Reaper: 2+ frontline/defending members halve cleave damage
            tank_defenders = sum(
                1 for t in alive_targets if t.role == "tank" or t.user_id in defending_uids or t.user_id in parrying_uids
            )
            cleave_mult = 0.65 if (bturn.get("mechanic") == "dual_tank_front_cleave" and tank_defenders >= 2) else 1.0

            for tm in targets:
                tp = players_by_uid[tm.user_id]
                tst = stats_by_uid[tm.user_id]
                if bturn.get("is_aoe"):
                    is_front = tm.user_id == raid.vanguard_user_id or tm.role == "tank"
                    aoe_mult = 0.72 if is_front else 0.52
                else:
                    aoe_mult = 1.0
                raw_hit = round(int(bturn["raw_atk"]) * cleave_mult * aoe_mult)
                edmg, dodged = calculate_enemy_hit(
                    raw_hit,
                    str(bturn["damage_type"]),
                    tst,
                    floor=raid.floor,
                    miasma_stacks=tp.miasma_stacks,
                    is_defending=(tm.user_id in defending_uids),
                    is_parrying=(tm.user_id in parrying_uids),
                    player_debuffs=tm.debuffs,
                    rng=rgen,
                )
                if dodged:
                    round_logs.append(f"💨 {tm.display_name} 閃避了頭目攻擊！")
                else:
                    tm.hp = max(0, tm.hp - edmg)
                    tm.damage_taken += edmg
                    if bturn.get("inflict_debuff") and tm.user_id not in parrying_uids:
                        deb_name = str(bturn["inflict_debuff"])
                        if deb_name == "stun":
                            if (
                                bturn.get("is_telegraphed_burst")
                                and switch_count_this_round == 0
                                and tm.user_id not in defending_uids
                            ):
                                apply_debuff(tm.debuffs, "stun", turns=2, dmg=0)
                        else:
                            apply_debuff(tm.debuffs, deb_name, turns=3, dmg=max(5, round(edmg * 0.12)))
                    if tm.hp <= 0:
                        tm.is_downed = True
                        round_logs.append(f"🩸 {tm.display_name} 遭到重擊倒地（瀕死狀態）！")
                # Authentic SAO Parry Counter-Slash when surviving a parried Boss strike!
                if tm.user_id in parrying_uids and not tm.is_downed and raid.boss.current_hp > 0:
                    c_dtype = str(tst.active_passives.get("dmg_type", DamageType.SLASH))
                    cdmg, _ccrit, _cweak = calculate_player_hit(
                        tst,
                        raid.boss.defense,
                        dmg_type=c_dtype,
                        target_weaknesses=raid.boss.weaknesses,
                        skill_mult=1.15,
                        switch_chain=raid.switch_chain,
                        target_debuffs=raid.boss.debuffs,
                        rng=rgen,
                    )
                    cres = apply_damage_to_boss(
                        raid.boss,
                        cdmg,
                        attacker_id=tm.user_id,
                        dmg_type=c_dtype,
                        break_power=22,
                        switch_chain=raid.switch_chain,
                        bundle=self.content,
                    )
                    tm.damage_dealt += int(cres["damage"])
                    round_logs.append(f"🛡️⚡ 【彈反反擊！】{tm.display_name} 架開頭目攻勢並反斬 {cres['damage']} 傷害！")
                    round_logs.extend(cres["logs"])
                    if cres["killed"]:
                        return self._settle_raid_victory_locked(raid, ts, round_logs)

        # 5. Party Potion Sharing (`我要出藥`) for injured alive teammates (<50% HP)
        potion_shares: list[dict[str, Any]] = []
        for injured in raid.members.values():
            if injured.is_downed or injured.is_retreated:
                continue
            if injured.hp < round(injured.max_hp * 0.50):
                for donor in raid.members.values():
                    if donor.user_id == injured.user_id or donor.is_downed or donor.is_retreated:
                        continue
                    if not donor.potion_sharing:
                        continue
                    pid = _find_best_potion(self.db, self.content, donor.user_id)
                    if pid and self.db.consume_items(donor.user_id, {pid: 1}):
                        pspec = self.content.items_crystals.get(pid, {})
                        eff = pspec.get("effect") or {}
                        heal = max(1, round(injured.max_hp * float(eff.get("heal_hp_pct", 0.35))) + int(eff.get("heal_hp_flat", 150)))
                        injured.hp = min(injured.max_hp, injured.hp + heal)
                        donor.healing_done += heal
                        potion_shares.append(
                            {"donor_id": donor.user_id, "recipient_id": injured.user_id, "item_id": pid, "heal": heal}
                        )
                        round_logs.append(
                            f"💚 【藥水共享】{donor.display_name} 立即丟出【{pspec.get('name', pid)}】為 {injured.display_name} 回復 {heal} 點生命！"
                        )
                        break

        # 6. Tick member debuffs
        for m in raid.members.values():
            if m.is_downed or m.is_retreated:
                continue
            for dn, di in list(m.debuffs.items()):
                tl = int(di.get("turns", 1)) - 1
                if tl <= 0:
                    m.debuffs.pop(dn, None)
                else:
                    di["turns"] = tl

        raid.pending_actions.clear()
        raid.turn += 1
        raid.turn_started_at = ts

        # 7. Check Full Party Wipe
        still_standing = [m for m in raid.members.values() if not m.is_downed and not m.is_retreated]
        if not still_standing:
            return self._settle_raid_defeat_locked(raid, ts, round_logs)

        raid.logs.extend(round_logs)
        pub_boss = _public_boss_snapshot(raid.boss)
        pub_raid = _public_raid_snapshot(raid, round_logs)
        return {
            "ok": True,
            "raid_id": raid.raid_id,
            "turn": raid.turn,
            "round_resolved": True,
            "finished": False,
            "victory": False,
            "defeat": False,
            "in_combat": True,
            "switch_chain": raid.switch_chain,
            "vanguard_user_id": raid.vanguard_user_id,
            "potion_shares": potion_shares,
            "boss_state": pub_boss,
            "boss": pub_boss,
            "members": raid.members,
            "raid": pub_raid,
            "logs": round_logs,
            "message": round_logs[-1],
        }

    def _settle_raid_victory_locked(
        self, raid: CoopRaidSession, ts: int, round_logs: list[str]
    ) -> dict[str, Any]:
        raid.finished = True
        raid.victory = True
        raid.la_user_id = raid.boss.last_attacker_id or raid.leader_id
        participant_ids = list(raid.members.keys())
        la_member = raid.members.get(raid.la_user_id)
        la_name = la_member.display_name if la_member else raid.la_user_id
        leader_m = raid.members.get(raid.leader_id)
        leader_name = leader_m.display_name if leader_m else raid.leader_id

        # Atomic SQLite First-Kill PK claim across all concurrent parties!
        is_first_kill = self.db.claim_server_floor_first_kill(
            floor=raid.floor,
            boss_id=raid.boss.boss_id,
            boss_name=raid.boss.name,
            leader_id=raid.leader_id,
            leader_name=leader_name,
            la_user_id=raid.la_user_id,
            la_user_name=la_name,
            participant_ids=participant_ids,
            cleared_at=ts,
        )
        raid.is_first_kill = is_first_kill

        fcfg = resolve_floor_config(raid.floor, self.content)
        today_key = time.strftime("%Y-%m-%d", time.gmtime(ts))
        week_key = time.strftime("%Y-W%W", time.gmtime(ts))
        rgen = random.Random(ts + raid.floor)

        rewards_by_user: dict[str, dict[str, Any]] = {}
        for uid, m in raid.members.items():
            p = self.db.get_player(uid)
            if p is None:
                continue
            clear_info = self.db.record_tower_clear(
                uid,
                raid.floor,
                ts,
                turns=raid.turn,
                is_team_boss=(raid.boss_mode == BossMode.TEAM_BOSS),
                today_key=today_key,
            )
            team_boosted = (
                raid.boss_mode == BossMode.TEAM_BOSS and int(clear_info.get("daily_team_clears", 0)) <= 3
            )
            drop_mult = 1.6 if team_boosted else 1.0
            exp_gain = max(10, round(int(fcfg["exp_base"]) * 6.5 * drop_mult))
            col_gain = max(30, round(int(fcfg["col_base"]) * 8.5 * drop_mult))

            apply_exp_and_level_up(p, exp_gain)
            p.col += col_gain
            p.in_boss_battle = False
            p.zone = ZoneType.TOWN
            p.boss_kills_participated += 1
            p.total_dungeons += 1
            p.survival_streak += 1
            p.highest_cleared_floor = max(p.highest_cleared_floor, raid.floor)

            # Materials + enhance crystals + forge scraps
            tier = int(fcfg["tier"])
            crys_id = enhance_crystal_for_tier(tier)
            mats: dict[str, int] = {}
            for mat in fcfg["boss"].get("guaranteed_materials", []):
                mid = str(mat["item_id"])
                qty = max(1, round(rgen.randint(int(mat.get("min", 1)), int(mat.get("max", 1))) * drop_mult))
                self.db.add_item(uid, mid, qty)
                mats[mid] = mats.get(mid, 0) + qty
            if crys_id in self.content.items_crystals:
                cqty = 3 if team_boosted else 2
                self.db.add_item(uid, crys_id, cqty)
                mats[crys_id] = mats.get(crys_id, 0) + cqty
            if "forge_scrap" in self.content.items_crystals:
                self.db.add_item(uid, "forge_scrap", 2)
                mats["forge_scrap"] = mats.get("forge_scrap", 0) + 2

            # Guaranteed per-member co-op participation equipment drop (never Named so LA stays strictly exclusive!)
            member_drops: list[dict[str, Any]] = []
            m_roll = rgen.random()
            if team_boosted:
                m_rarity = Rarity.LEGENDARY if m_roll < 0.25 else (Rarity.SET if m_roll < 0.65 else Rarity.RARE)
            else:
                m_rarity = Rarity.LEGENDARY if m_roll < 0.12 else (Rarity.SET if m_roll < 0.45 else (Rarity.RARE if m_roll < 0.85 else Rarity.FINE))
            coop_eq = generate_equipment_item(
                uid, raid.floor, self.content, rarity=m_rarity, weapon_style=p.weapon_style, now_ts=ts, rng=rgen
            )
            member_drop = grant_or_queue_equipment(
                self.db, p, coop_eq, source=f"第{raid.floor}層共鬥頭目討伐", now_ts=ts, apply_filter=True
            )
            member_drops.append(member_drop)

            # Last Attack (LA) Named Bonus drop strictly to la_user_id
            la_drop: dict[str, Any] | None = None
            if uid == raid.la_user_id:
                if raid.boss.la_bonus_item_id and raid.boss.la_bonus_item_id in self.content.weapons_equipment.get("named_items", {}):
                    named_eq = generate_named_equipment(uid, raid.boss.la_bonus_item_id, self.content, now_ts=ts)
                    la_drop = grant_or_queue_equipment(
                        self.db, p, named_eq, source=f"第{raid.floor}層共鬥尾刀獎勵(LA)", now_ts=ts, apply_filter=False
                    )
                else:
                    eq = generate_equipment_item(
                        uid, raid.floor, self.content, rarity=Rarity.LEGENDARY, weapon_style=p.weapon_style, now_ts=ts, rng=rgen
                    )
                    la_drop = grant_or_queue_equipment(
                        self.db, p, eq, source=f"第{raid.floor}層共鬥尾刀獎勵(LA)", now_ts=ts, apply_filter=False
                    )
                member_drops.append(la_drop)

            # Unlock Yui logs & milestone achievements
            for log_id, lspec in self.content.quests_events.get("yui_logs", {}).items():
                if int(lspec.get("unlock_floor", 999)) <= raid.floor:
                    self.db.unlock_yui_log(uid, log_id, ts)
            ach_map = {1: "sao_ach_f01", 10: "sao_ach_f10", 25: "sao_ach_f25", 50: "sao_ach_f50", 74: "sao_ach_f74", 75: "sao_ach_f75", 100: "sao_ach_f100"}
            if raid.floor in ach_map:
                self.db.unlock_achievement(uid, ach_map[raid.floor], ts)
            for obs in raid.boss.observed_skills:
                self.db.record_boss_intel_seen(uid, raid.boss.boss_id, obs, ts)
            self.db.increment_quest(uid, "daily", today_key, "dq_boss_1", 1, delta=1)
            self.db.increment_quest(uid, "weekly", week_key, "wq_boss_10", 10, delta=1)
            if len(raid.members) >= 2:
                self.db.increment_quest(uid, "weekly", week_key, "wq_coop_5", 5, delta=1)

            st = compute_full_player_stats(self.db, self.content, p, floor=raid.floor, now_ts=ts)
            p.combat_power = st.combat_power
            p.updated_at = ts
            self.db.save_player(p)

            rewards_by_user[uid] = {
                "user_id": uid,
                "exp_gain": exp_gain,
                "col_gain": col_gain,
                "materials": mats,
                "is_la": uid == raid.la_user_id,
                "la_reward": la_drop,
                "equipment_drops": member_drops,
                "team_boosted": team_boosted,
                "daily_team_clears": int(clear_info.get("daily_team_clears", 0)),
                "damage_dealt": m.damage_dealt,
                "damage_taken": m.damage_taken,
                "healing_done": m.healing_done,
            }

        raid.rewards_by_user = rewards_by_user
        self.db.record_raid_history(
            raid_id=raid.raid_id,
            party_id=raid.party_id,
            floor=raid.floor,
            boss_id=raid.boss.boss_id,
            boss_mode=raid.boss_mode,
            victory=True,
            is_first_kill=is_first_kill,
            la_user_id=raid.la_user_id,
            participants=participant_ids,
            turns_taken=raid.turn,
            started_at=raid.started_at,
            ended_at=ts,
        )
        # Return party lobby back to lobby status so team can continue climbing!
        lobby = self.db.get_party(raid.party_id)
        if lobby is not None:
            lobby.status = "lobby"
            lobby.updated_at = ts
            self.db.save_party(lobby)

        any_team_boosted = any(bool(r.get("team_boosted", False)) for r in rewards_by_user.values())
        fk_banner = " 👑【全服首殺達成！】" if is_first_kill else ""
        msg = f"🏆 第 {raid.floor} 層頭目【{raid.boss.name}】討伐成功！{fk_banner}尾刀（LA）由 {la_name} 奪得！"
        round_logs.append(msg)
        raid.logs.extend(round_logs)
        pub_boss = _public_boss_snapshot(raid.boss)
        pub_raid = _public_raid_snapshot(raid, round_logs)
        return {
            "ok": True,
            "raid_id": raid.raid_id,
            "turn": raid.turn,
            "round_resolved": True,
            "finished": True,
            "victory": True,
            "defeat": False,
            "in_combat": False,
            "is_first_kill": is_first_kill,
            "boosted_drop": any_team_boosted,
            "daily_boost": any_team_boosted,
            "la_user_id": raid.la_user_id,
            "la_user_name": la_name,
            "rewards_by_user": rewards_by_user,
            "boss_state": pub_boss,
            "raid": pub_raid,
            "logs": round_logs,
            "message": msg,
        }

    def _settle_raid_defeat_locked(
        self, raid: CoopRaidSession, ts: int, round_logs: list[str]
    ) -> dict[str, Any]:
        raid.finished = True
        raid.victory = False
        last_logs = list(round_logs[-5:])
        for uid, m in raid.members.items():
            p = self.db.get_player(uid)
            if p is None:
                continue
            p.in_boss_battle = False
            p.survival_streak = 0
            p.last_death_log = " | ".join(last_logs)
            if m.is_downed:
                if p.game_mode == GameMode.HARDCORE:
                    p.is_dead = True
                    p.hp = 0
                    self.db.record_monument_event(
                        uid, p.display_name, "fallen", raid.floor, GameMode.HARDCORE,
                        f"多人攻略戰敗於第 {raid.floor} 層【{raid.boss.name}】", last_logs, ts,
                    )
                else:
                    p.downed_until = ts + 300
                    p.hp = 1
                    self.db.record_monument_event(
                        uid, p.display_name, "downed", raid.floor, GameMode.STANDARD,
                        f"多人攻略戰重傷於第 {raid.floor} 層【{raid.boss.name}】", last_logs, ts,
                    )
            p.updated_at = ts
            self.db.save_player(p)

        lobby = self.db.get_party(raid.party_id)
        if lobby is not None:
            lobby.status = "lobby"
            lobby.updated_at = ts
            self.db.save_party(lobby)

        msg = f"💀 全體攻略成員倒下，第 {raid.floor} 層【{raid.boss.name}】攻略失敗！"
        round_logs.append(msg)
        raid.logs.extend(round_logs)
        return {
            "ok": True,
            "raid_id": raid.raid_id,
            "round_resolved": True,
            "finished": True,
            "victory": False,
            "defeat": True,
            "in_combat": False,
            "raid": _public_raid_snapshot(raid, round_logs),
            "logs": round_logs,
            "message": msg,
        }

    # =========================================================================
    # Group Teleport & Downed Teammate Rescue
    # =========================================================================
    def party_group_teleport(
        self,
        party_id: str,
        leader_id: str,
        target_floor: int,
        *,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        ts = _now(now_ts)
        if isinstance(target_floor, bool) or not isinstance(target_floor, int) or not (1 <= target_floor <= 100):
            raise GameError(f"無效的集體傳送樓層：{target_floor}", code="INVALID_FLOOR")

        with self._lock_for(party_id):
            lobby = self.db.get_party(party_id)
            if lobby is None:
                raise GameError(f"找不到隊伍：{party_id}", code="PARTY_NOT_FOUND")
            if lobby.leader_id != leader_id:
                raise GameError("僅隊長可發動隊伍集體傳送！", code="LEADER_ONLY_ACTION")

            # Check if party is in an active anti-crystal raid or any member is stunned
            active_raid = next(
                (r for r in self.active_raids.values() if r.party_id == party_id and not r.finished),
                None,
            )
            if active_raid is not None:
                if active_raid.boss.anti_crystal_zone or active_raid.floor == 100:
                    raise GameError("🚨 頭目房處於【水晶無效化空間】，禁止發動集體轉移！", code="CRYSTAL_NULL_BLOCKED")
                stunned = [
                    m.display_name for m in active_raid.members.values() if "stun" in m.debuffs and not m.is_downed
                ]
                if stunned:
                    raise GameError(
                        f"⚡ 隊友【{', '.join(stunned)}】正處於暈眩狀態無法跟隨集體傳送！",
                        code="MEMBER_STUNNED_TELEPORT_BLOCKED",
                    )

            leader_p = self.db.get_player(leader_id)
            if leader_p is None or target_floor > leader_p.max_unlocked_floor:
                raise GameError(f"隊長尚未解鎖第 {target_floor} 層轉移門！", code="FLOOR_LOCKED")

            teleported: list[str] = []
            stragglers: list[str] = []
            for uid in lobby.members:
                p = self.db.get_player(uid)
                if p is None:
                    continue
                if target_floor > p.max_unlocked_floor:
                    stragglers.append(uid)
                    continue
                p.current_floor = target_floor
                p.zone = ZoneType.TOWN
                p.in_boss_battle = False
                p.miasma_stacks = 0
                p.miasma_exp_stacks = 0
                p.updated_at = ts
                self.db.save_player(p)
                teleported.append(uid)

            if active_raid is not None:
                active_raid.finished = True
            lobby.floor = target_floor
            lobby.status = "lobby"
            lobby.updated_at = ts
            self.db.save_party(lobby)
            return {
                "ok": True,
                "party_id": party_id,
                "target_floor": target_floor,
                "teleported": teleported,
                "stragglers": stragglers,
                "message": (
                    f"🌀 集體轉移成功！已將 {len(teleported)} 名成員傳送至第 {target_floor} 層城鎮"
                    + (f"（{len(stragglers)} 人尚未解鎖該層留守原處）。" if stragglers else "！")
                ),
            }

    def rescue_downed_player(
        self,
        rescuer_id: str,
        target_user_id: str,
        *,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        """Spend 1 Teleport Crystal to rescue a Downed teammate back to Town Safe Zone."""
        ts = _now(now_ts)
        rescuer = self.db.get_player(rescuer_id)
        target = self.db.get_player(target_user_id)
        if rescuer is None or target is None:
            raise GameError("找不到救援者或目標玩家資料。", code="PLAYER_NOT_FOUND")
        if target.is_dead:
            raise GameError("目標為硬派模式已殞落角色，無法透過轉移水晶復活。", code="HARDCORE_DEAD_UNRESCUABLE")
        if target.downed_until <= 0:
            raise GameError(f"{target.display_name} 目前並未處於瀕死倒地狀態，無需救援！", code="TARGET_NOT_DOWNED")
        if self.db.get_item_qty(rescuer_id, "teleport_crystal") <= 0:
            raise GameError("你的背包缺少【轉移水晶（teleport_crystal）】，無法實施救援！", code="INSUFFICIENT_CRYSTAL")

        with self.db.transaction():
            if not self.db.consume_items(rescuer_id, {"teleport_crystal": 1}):
                raise GameError("轉移水晶扣除失敗！", code="INSUFFICIENT_CRYSTAL")
            stats = compute_full_player_stats(self.db, self.content, target, floor=target.current_floor, now_ts=ts)
            target.downed_until = 0
            target.zone = ZoneType.TOWN
            target.in_boss_battle = False
            target.miasma_stacks = 0
            target.miasma_exp_stacks = 0
            target.hp = stats.max_hp
            target.sp = stats.max_sp
            target.updated_at = ts
            self.db.save_player(target)

        return {
            "ok": True,
            "rescuer_id": rescuer_id,
            "target_user_id": target_user_id,
            "target_zone": target.zone,
            "crystals_remaining": self.db.get_item_qty(rescuer_id, "teleport_crystal"),
            "message": f"💎 救援成功！{rescuer.display_name} 消耗 1 顆轉移水晶將瀕死的 {target.display_name} 安全送回城鎮圈內！",
        }

    # =========================================================================
    # Floor World Boss & Accelerated World Server Buff
    # =========================================================================
    def _refresh_world_boss_attempts(self, player: PlayerProfile, ts: int) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime(ts))
        if not player.world_boss_attempts_date:
            player.world_boss_attempts_date = today
            player.world_boss_attempts = max(0, min(9, player.world_boss_attempts))
            return
        if player.world_boss_attempts_date != today:
            try:
                prev_day = time.strptime(player.world_boss_attempts_date, "%Y-%m-%d")
                cur_day = time.strptime(today, "%Y-%m-%d")
                days_diff = max(1, int((time.mktime(cur_day) - time.mktime(prev_day)) // 86400))
            except ValueError:
                days_diff = 1
            if days_diff == 1:
                player.world_boss_attempts = min(6, player.world_boss_attempts + 3)
            else:
                player.world_boss_attempts = min(9, player.world_boss_attempts + 3 * days_diff)
            player.world_boss_attempts_date = today

    def attack_floor_world_boss(
        self,
        user_id: str,
        *,
        party_id: str | None = None,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        """Attack shared server Floor World Boss; defeating it activates server-wide `加速世界` buff."""
        ts = _now(now_ts)
        with self._lock_for("world_boss"):
            player = self.db.get_player(user_id)
            if player is None:
                raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
            if player.is_dead:
                raise GameError("硬派角色已陣亡，無法挑戰世界王。", code="HARDCORE_DEAD")

            self._refresh_world_boss_attempts(player, ts)
            if player.world_boss_attempts <= 0:
                raise GameError("今日樓層世界王挑戰次數已用盡（每日補充 3 次，最多累積 6～9 次）！", code="NO_WORLD_BOSS_ATTEMPTS")

            wb = self.db.get_active_world_boss()
            if wb is None:
                frontline = self.db.get_server_frontline_floor()
                fcfg = resolve_floor_config(frontline, self.content)
                wb_id = str(fcfg["world_boss_id"])
                wspec = self.content.bosses[wb_id]
                wb = self.db.create_world_boss(
                    tier=int(fcfg["tier"]),
                    boss_id=wb_id,
                    name=str(wspec["name"]),
                    max_hp=int(wspec.get("base_hp", 25000)),
                    atk=int(wspec.get("base_atk", 150)),
                    def_=int(wspec.get("base_def", 60)),
                    now_ts=ts,
                    floor=frontline,
                    accelerated_buff_hours=2,
                )

            stats = compute_full_player_stats(self.db, self.content, player, floor=wb.floor, now_ts=ts)
            party_bonus = 1.25 if (party_id and self.db.get_party(party_id) is not None) else 1.0
            dmg = max(50, round((stats.atk * 3.8 + stats.combat_power * 0.25) * party_bonus))

            wb.current_hp = max(0, wb.current_hp - dmg)
            player.world_boss_attempts -= 1
            player.total_boss_damage += dmg
            player.last_boss_at = ts
            col_gain = max(120, round(dmg * 0.15))
            exp_gain = max(60, round(dmg * 0.10))
            apply_exp_and_level_up(player, exp_gain)
            player.col += col_gain

            self.db.record_world_boss_damage(wb.id, user_id, player.display_name, dmg, ts)
            week_key = time.strftime("%Y-W%W", time.gmtime(ts))
            self.db.increment_quest(user_id, "weekly", week_key, "wq_world_boss_5", 5, delta=1)

            defeated = wb.current_hp <= 0
            accelerated_buff_id: int | None = None
            items_gained: dict[str, int] = {}
            equipment_drops: list[dict[str, Any]] = []
            if defeated:
                wb.status = "defeated"
                wb.defeated_at = ts
                wb.killer_user_id = user_id
                player.boss_kills_participated += 1
                accelerated_buff_id = self.db.create_world_buff(
                    buff_key="accelerated_world",
                    scope_type="server",
                    scope_id="global",
                    name="加速世界（Accelerated World）",
                    payload={"exp_bonus": 0.20, "col_bonus": 0.20, "drop_bonus": 0.15, "atk_pct": 0.08},
                    expires_at=ts + wb.accelerated_buff_hours * 3600,
                    now_ts=ts,
                    created_by=user_id,
                    charges=-1,
                )
                rgen = random.Random(ts + wb.id + wb.floor)
                wspec = self.content.bosses.get(wb.boss_id, {})
                crys_id = enhance_crystal_for_tier(wb.tier)
                rankings_all = self.db.get_world_boss_rankings(wb.id, limit=50)
                participant_uids = {str(r["user_id"]) for r in rankings_all} | {str(user_id)}
                for puid in participant_uids:
                    for mat in wspec.get("guaranteed_materials", []):
                        mid = str(mat["item_id"])
                        if mid in self.content.items_crystals:
                            qty = rgen.randint(int(mat.get("min", 1)), int(mat.get("max", 1)))
                            self.db.add_item(puid, mid, qty)
                            if puid == str(user_id):
                                items_gained[mid] = items_gained.get(mid, 0) + qty
                    if crys_id in self.content.items_crystals:
                        self.db.add_item(puid, crys_id, 3)
                        if puid == str(user_id):
                            items_gained[crys_id] = items_gained.get(crys_id, 0) + 3
                    tp = player if puid == str(user_id) else self.db.get_player(puid)
                    if tp is not None:
                        wb_rarity = Rarity.LEGENDARY if (puid == str(user_id) or rgen.random() < 0.35) else Rarity.SET
                        wb_gear = generate_equipment_item(
                            puid, max(1, wb.floor), self.content, rarity=wb_rarity, weapon_style=tp.weapon_style, now_ts=ts, rng=rgen
                        )
                        gres = grant_or_queue_equipment(
                            self.db, tp, wb_gear, source=f"第{wb.floor}層世界王討伐({wb.name})", now_ts=ts, apply_filter=False
                        )
                        if puid == str(user_id):
                            equipment_drops.append(gres)
            self.db.update_world_boss(wb)
            player.updated_at = ts
            self.db.save_player(player)

            rankings = self.db.get_world_boss_rankings(wb.id, limit=10)
            gear_note = f"，並獲得【{equipment_drops[0]['item_name']}】" if equipment_drops else ""
            msg = (
                f"🌍 【樓層世界王討伐完成！】{player.display_name} 造成 {dmg} 傷害並擊殺【{wb.name}】{gear_note}，全服啟動【加速世界】增益 2 小時！"
                if defeated
                else f"🌍 對第 {wb.floor} 層世界王【{wb.name}】造成 {dmg} 傷害！（剩餘 HP {wb.current_hp}/{wb.max_hp}，剩餘次數 {player.world_boss_attempts}）"
            )
            return {
                "ok": True,
                "world_boss": wb,
                "damage": dmg,
                "defeated": defeated,
                "accelerated_world_active": defeated,
                "accelerated_buff_id": accelerated_buff_id,
                "attempts_remaining": player.world_boss_attempts,
                "col_gain": col_gain,
                "exp_gain": exp_gain,
                "items": items_gained,
                "equipment_drops": equipment_drops,
                "rankings": rankings,
                "message": msg,
            }

    # =========================================================================
    # PvP Duels (`決鬥`: 初擊勝負 / 完全勝負)
    # =========================================================================
    def challenge_duel(
        self,
        challenger_id: str,
        target_id: str,
        *,
        mode: str = "first_strike",
        wager_col: int = 0,
        now_ts: int | None = None,
        active_combats: dict[str, CombatSession] | None = None,
    ) -> dict[str, Any]:
        ts = _now(now_ts)
        if str(challenger_id) == str(target_id):
            raise GameError("無法向自己發起決鬥！", code="SELF_DUEL_FORBIDDEN")
        norm_mode = VALID_DUEL_MODES.get(str(mode or "first_strike").strip().lower())
        if norm_mode is None:
            raise GameError(f"不支援的決鬥模式：{mode}（支援：first_strike／full）", code="INVALID_DUEL_MODE")
        if isinstance(wager_col, bool) or not isinstance(wager_col, int) or wager_col < 0:
            raise GameError("決鬥賭注不可為負數！", code="INVALID_WAGER")

        with self._global_lock:
            c = self.db.get_player(challenger_id)
            t = self.db.get_player(target_id)
            if c is None or t is None:
                raise GameError("找不到決鬥發起者或目標玩家。", code="PLAYER_NOT_FOUND")
            if c.is_dead or t.is_dead:
                raise GameError("已殞落的硬派角色無法參與決鬥。", code="HARDCORE_DEAD")
            if c.in_boss_battle or t.in_boss_battle:
                raise GameError("目標或你正在頭目戰中，無法發起決鬥！", code="PLAYER_IN_COMBAT")
            if active_combats:
                for uid in (challenger_id, target_id):
                    if uid in active_combats and not active_combats[uid].finished:
                        raise GameError("玩家正在戰鬥中，無法發起決鬥！", code="PLAYER_IN_COMBAT")
            for d in self.active_duels.values():
                if d.status in ("pending", "active") and {challenger_id, target_id} & {d.challenger_id, d.target_id}:
                    raise GameError("雙方其中一人已有進行中或待接受的決鬥！", code="ALREADY_IN_DUEL")
            if wager_col > c.col or wager_col > t.col:
                raise GameError("雙方其中一方的柯爾不足以支付決鬥賭注！", code="INSUFFICIENT_WAGER_COL")

            cs = compute_full_player_stats(self.db, self.content, c, floor=c.current_floor, now_ts=ts)
            ts_stats = compute_full_player_stats(self.db, self.content, t, floor=t.current_floor, now_ts=ts)
            did = f"duel_{uuid.uuid4().hex[:8]}"
            duel = DuelSession(
                duel_id=did,
                challenger_id=challenger_id,
                challenger_name=c.display_name,
                target_id=target_id,
                target_name=t.display_name,
                mode=norm_mode,
                wager_col=wager_col,
                zone=c.zone,
                status="pending",
                challenger_hp=cs.max_hp,
                challenger_max_hp=cs.max_hp,
                challenger_sp=cs.max_sp,
                challenger_max_sp=cs.max_sp,
                target_hp=ts_stats.max_hp,
                target_max_hp=ts_stats.max_hp,
                target_sp=ts_stats.max_sp,
                target_max_sp=ts_stats.max_sp,
                created_at=ts,
            )
            self.active_duels[did] = duel
            m_zh = "初擊勝負（50% HP 判定）" if norm_mode == "first_strike" else "完全勝負（1 HP 安全保護判定）"
            return {
                "ok": True,
                "duel_id": did,
                "mode": norm_mode,
                "wager_col": wager_col,
                "status": duel.status,
                "duel": duel,
                "message": f"⚔️ {c.display_name} 向 {t.display_name} 發起【{m_zh}】決鬥申請（賭注 {wager_col} 柯爾，圈內不致死、保持綠色光標）！",
            }

    def accept_duel(
        self,
        duel_id: str,
        target_id: str,
        *,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        ts = _now(now_ts)
        with self._lock_for(duel_id):
            duel = self.active_duels.get(duel_id)
            if duel is None or duel.status != "pending":
                raise GameError("找不到待接受的決鬥邀請。", code="DUEL_NOT_PENDING")
            if str(target_id) != duel.target_id:
                raise GameError("僅受邀決鬥對象本人可接受此決鬥！", code="NOT_DUEL_TARGET")

            c = self.db.get_player(duel.challenger_id)
            t = self.db.get_player(duel.target_id)
            if c is None or t is None:
                raise GameError("決鬥雙方角色不存在。", code="PLAYER_NOT_FOUND")
            if duel.wager_col > 0:
                if c.col < duel.wager_col or t.col < duel.wager_col:
                    raise GameError("雙方其中一方柯爾不足，無法託管決鬥賭注！", code="INSUFFICIENT_WAGER_COL")
                with self.db.transaction():
                    c.col -= duel.wager_col
                    t.col -= duel.wager_col
                    c.updated_at = ts
                    t.updated_at = ts
                    self.db.save_player(c)
                    self.db.save_player(t)

            duel.status = "active"
            duel.logs.append(f"⚔️ 決鬥正式開始！{duel.challenger_name} VS {duel.target_name}！")
            return {
                "ok": True,
                "duel_id": duel_id,
                "status": duel.status,
                "wager_col": duel.wager_col,
                "duel": duel,
                "message": duel.logs[-1],
            }

    def duel_action(
        self,
        duel_id: str,
        user_id: str,
        action: str,
        *,
        skill_id: str | None = None,
        now_ts: int | None = None,
    ) -> dict[str, Any]:
        ts = _now(now_ts)
        act = str(action or "attack").strip().lower()
        if act not in ("attack", "skill", "defend", "parry"):
            raise GameError(f"無效的決鬥指令：{action}", code="INVALID_DUEL_ACTION")

        with self._lock_for(duel_id):
            duel = self.active_duels.get(duel_id)
            if duel is None or duel.status != "active":
                raise GameError("此決鬥尚未開始或已結束。", code="DUEL_NOT_ACTIVE")
            if user_id not in (duel.challenger_id, duel.target_id):
                raise GameError("你並非此決鬥參賽者。", code="NOT_IN_DUEL")

            is_challenger = user_id == duel.challenger_id
            opp_id = duel.target_id if is_challenger else duel.challenger_id
            actor = self.db.get_player(user_id)
            opp = self.db.get_player(opp_id)
            if actor is None or opp is None:
                raise GameError("找不到決鬥玩家資料。", code="PLAYER_NOT_FOUND")

            ast = compute_full_player_stats(self.db, self.content, actor, floor=actor.current_floor, now_ts=ts)
            ost = compute_full_player_stats(self.db, self.content, opp, floor=opp.current_floor, now_ts=ts)
            rgen = random.Random(ts + duel.turn * 17)

            mult = 1.0
            dtype = str(ast.active_passives.get("dmg_type", DamageType.SLASH))
            label = "斬擊"
            if act == "skill" and skill_id:
                spec = self.content.sword_skills.get(skill_id)
                if not isinstance(spec, dict):
                    raise GameError(f"未知劍技：{skill_id}", code="UNKNOWN_SKILL")
                mult = float(spec.get("damage_mult", 1.4))
                dtype = str(spec.get("dmg_type") or dtype)
                label = str(spec.get("name", skill_id))
            elif act in ("defend", "parry"):
                mult = 0.35
                label = "彈反架勢" if act == "parry" else "格擋反擊"

            dmg, _crit, _ = calculate_player_hit(
                ast, ost.defense, dmg_type=dtype, target_weaknesses=[], skill_mult=mult, rng=rgen
            )
            # Safe-zone non-lethal clamp: HP NEVER drops below 1 in a duel!
            if is_challenger:
                duel.target_hp = max(1, duel.target_hp - dmg)
                opp_hp = duel.target_hp
                opp_max = duel.target_max_hp
            else:
                duel.challenger_hp = max(1, duel.challenger_hp - dmg)
                opp_hp = duel.challenger_hp
                opp_max = duel.challenger_max_hp

            duel.turn += 1
            duel.logs.append(f"⚔️ {actor.display_name} 使出【{label}】造成 {dmg} 傷害（對手剩餘 HP {opp_hp}/{opp_max}）！")

            threshold = (opp_max * 0.50) if duel.mode == "first_strike" else 1
            won = opp_hp <= threshold
            if won:
                duel.status = "finished"
                duel.winner_id = user_id
                duel.finished_at = ts
                payout = duel.wager_col * 2
                if payout > 0:
                    actor.col += payout
                    actor.updated_at = ts
                    self.db.save_player(actor)
                self.db.record_duel_result(
                    duel_id=duel.duel_id,
                    challenger_id=duel.challenger_id,
                    target_id=duel.target_id,
                    mode=duel.mode,
                    wager_col=duel.wager_col,
                    winner_id=user_id,
                    turns=duel.turn,
                    now_ts=ts,
                )
                msg = f"🏆 【決鬥分出勝負！】{actor.display_name} 擊敗 {opp.display_name} 獲勝" + (
                    f"，贏得 {payout} 柯爾！" if payout > 0 else "！"
                )
                duel.logs.append(msg)
                return {
                    "ok": True,
                    "duel_id": duel.duel_id,
                    "finished": True,
                    "victory": True,
                    "winner_id": user_id,
                    "wager_payout": payout,
                    "duel": duel,
                    "message": msg,
                }

            return {
                "ok": True,
                "duel_id": duel.duel_id,
                "finished": False,
                "winner_id": None,
                "damage": dmg,
                "challenger_hp": duel.challenger_hp,
                "target_hp": duel.target_hp,
                "duel": duel,
                "message": duel.logs[-1],
            }
