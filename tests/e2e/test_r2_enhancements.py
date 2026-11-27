"""Round 2 Comprehensive E2E Tests: Post-Combat Continue-Exploring UX, Multi-Channel Gear Drops,
5-Axis Equipment Upgrading, Interactive Workshop/Bag/Shop Views & Adversarial Security Hardening.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import discord
import pytest

from src.rpg.database import RPGDatabase
from src.rpg.engine import GameError, RPGEngine
from src.rpg.models import EquipmentItem
from src.rpg.systems.stats import compute_player_stats
from src.rpg.ui import (
    BagEquipView,
    ChestView,
    CoopRaidView,
    PostCombatView,
    PostCoopRaidView,
    RoguelikeView,
    SecretRealmView,
    ShopView,
    SoloCombatView,
    TowerFloorView,
    WorkshopView,
    build_combat_embed,
)

NOW_TS = 1_760_000_000


class FakeUser:
    def __init__(self, user_id: str, display_name: str = "Kirito") -> None:
        self.id = int(user_id)
        self.display_name = display_name


class FakeResponse:
    def __init__(self) -> None:
        self._done = False
        self.edits: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.deferred = False

    def is_done(self) -> bool:
        return self._done

    async def edit_message(self, **kwargs: Any) -> None:
        self._done = True
        self.edits.append(kwargs)

    async def send_message(self, content: Any = None, **kwargs: Any) -> None:
        self._done = True
        self.messages.append({"content": content, **kwargs})

    async def defer(self, **kwargs: Any) -> None:
        self._done = True
        self.deferred = True


class FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send(self, content: Any = None, **kwargs: Any) -> None:
        self.messages.append({"content": content, **kwargs})


class FakeInteraction:
    def __init__(self, user_id: str, display_name: str = "Kirito") -> None:
        self.user = FakeUser(user_id, display_name)
        self.response = FakeResponse()
        self.followup = FakeFollowup()


def _find_button(view: discord.ui.View, *, custom_id: str | None = None, label_contains: str | None = None) -> discord.ui.Button[Any]:
    for child in view.children:
        if isinstance(child, discord.ui.Button):
            if custom_id and child.custom_id == custom_id:
                return child
            if label_contains and child.label and label_contains in child.label:
                return child
    labels = [getattr(c, "label", None) or getattr(c, "custom_id", None) for c in view.children]
    raise AssertionError(f"Button not found (custom_id={custom_id}, label={label_contains}) in {labels}")


def _make_engine(tmp_path: Path, name: str = "r2.db") -> tuple[RPGDatabase, RPGEngine]:
    db = RPGDatabase(tmp_path / name)
    return db, RPGEngine(db)


def _seed_rich_player(eng: RPGEngine, uid: str = "9001", style: str = "sword", level: int = 10, floor: int = 1) -> None:
    eng.create_character(uid, f"Player{uid}", weapon_style=style, now_ts=NOW_TS)
    p = eng.db.get_player(uid)
    assert p is not None
    p.level = level
    p.col = 500_000
    p.current_floor = floor
    p.highest_cleared_floor = max(floor, 10)
    p.str_stat = 60
    p.agi_stat = 45
    p.vit_stat = 60
    p.dex_stat = 45
    p.luk_stat = 40
    p.zone = "town"
    eng.db.save_player(p)
    # Give abundant upgrade materials
    for iid, qty in {
        "bright_crystal_shard": 120,
        "bright_crystal": 80,
        "dark_crystal_shard": 60,
        "dark_crystal": 40,
        "dark_crystal_pure": 25,
        "forge_scrap": 100,
        "protection_talisman": 10,
        "reroll_stone": 5,
        "swap_stone": 5,
        "refine_stone": 5,
        "expand_stone": 5,
        "socket_crystal_crimson": 3,
        "socket_crystal_aegis": 3,
        "socket_crystal_gale": 2,
        "gear_supply_crate_t1": 3,
        "gear_supply_crate_t2": 2,
        "gacha_relic_ticket": 3,
        "copper_vein_ore": 40,
        "iron_vein_ore": 40,
        "boar_meat": 20,
        "spice_pack": 20,
        "hp_potion_t1": 20,
        "healing_crystal": 10,
        "teleport_crystal": 10,
    }.items():
        eng.db.add_item(uid, iid, qty)


# =============================================================================
# 1. Starter Gear, Style-Authentic Generation & Multi-Channel Equipment Drops
# =============================================================================
def test_r2_starter_weapon_and_non_shield_offhand_passives(tmp_path: Path) -> None:
    db, eng = _make_engine(tmp_path, "starter.db")
    try:
        styles = ("sword", "rapier", "katana", "axe", "mace", "holy", "scythe", "dagger")
        for idx, style in enumerate(styles, start=101):
            uid = str(idx)
            eng.create_character(uid, f"Hero{style}", weapon_style=style, now_ts=NOW_TS)
            prof = eng.get_profile(uid, now_ts=NOW_TS)
            eqs = prof["equipment"]
            assert len(eqs) == 1
            w = eqs[0]
            assert w.slot == "weapon"
            assert w.is_equipped is True
            assert w.weapon_style == style
            assert w.base_atk <= 10 and w.base_hp <= 15 and w.base_def <= 2
            assert prof["inventory"].get("bright_crystal_shard", 0) >= 2

        # Dagger / Dual Blades offhand weapon must NOT trigger shield speed penalty
        from src.rpg.systems.tower import generate_equipment_item

        dag_player = eng.db.get_player("108")
        assert dag_player is not None
        off_dag = generate_equipment_item("108", 25, eng.content, slot="offhand", weapon_style="dagger", now_ts=NOW_TS)
        assert "盾" not in off_dag.name
        s_bare = compute_player_stats(dag_player, [], eng.content)
        s_off = compute_player_stats(dag_player, [off_dag], eng.content)
        assert s_off.spd >= s_bare.spd
        assert s_off.atk > s_bare.atk
    finally:
        db.close()


def test_r2_multi_channel_drops_pity_chests_secret_roguelike_expedition_boss_raid_wb(tmp_path: Path) -> None:
    db, eng = _make_engine(tmp_path, "drops.db")
    try:
        _seed_rich_player(eng, "2001", style="sword", level=35, floor=1)
        _seed_rich_player(eng, "2002", style="rapier", level=35, floor=1)

        # 1) Road mob 4-kill drop pity guarantees at least 1 equipment drop within 4 kills
        gear_drops_from_mobs = 0
        kills = 0
        seed = 1
        while kills < 4 and seed < 60:
            res = eng.explore_floor("2001", steps=1, now_ts=NOW_TS + seed, rng_seed=seed)
            seed += 1
            if res.get("chest"):
                eng.open_chest("2001", action="leave", now_ts=NOW_TS + seed)
                continue
            if res.get("in_combat"):
                c = eng.active_combats["2001"]
                c.enemy_hp = 1
                end = eng.combat_action("2001", "attack", now_ts=NOW_TS + seed)
                assert end["finished"] is True and end["victory"] is True
                assert "mode" in end and "floor" in end and "rewards" in end
                kills += 1
                gear_drops_from_mobs += len(end["rewards"].get("equipment_drops", []))
        assert kills == 4
        assert gear_drops_from_mobs >= 1, "4-kill road mob pity MUST guarantee at least 1 gear drop"

        # 2) Chest loot weights parser & crystal bonus across all 6 tiers via public open_chest()
        for idx_c, ctier in enumerate(("wooden", "iron", "silver", "gold", "boss_relic", "named_vault"), start=1):
            eng.db.save_floor_exploration(
                "2001",
                1,
                50,
                False,
                False,
                {"chest_tier": ctier, "name": f"測試寶箱_{ctier}", "trap_type": "none", "floor": 1},
                NOW_TS + 80 + idx_c,
            )
            loot = eng.open_chest("2001", action="open", now_ts=NOW_TS + 80 + idx_c, rng_seed=42 + idx_c)
            assert loot["ok"] is True
            assert loot.get("col_gain", 0) > 0
            assert len(loot.get("equipment_drops", [])) >= 1

        # 3) Secret realm drops gear & crystals at Miasma >= 3
        eng.enter_secret_realm("2001", action="enter", now_ts=NOW_TS + 100)
        got_secret_loot = False
        for step_i in range(8):
            sr = eng.enter_secret_realm("2001", action="explore", now_ts=NOW_TS + 101 + step_i, rng_seed=step_i + 10)
            if sr.get("equipment_drops") or sr.get("items"):
                got_secret_loot = True
        assert got_secret_loot is True
        eng.travel_zone("2001", "town", now_ts=NOW_TS + 200)

        # 4) Roguelike depth-scaled extract gear & wq_roguelike_3 quest tracking
        eng.start_roguelike("2001", now_ts=NOW_TS + 210, rng_seed=9)
        run = eng.active_roguelikes["2001"]
        run.depth = 6
        run.score = 450
        ext = eng.extract_roguelike("2001", now_ts=NOW_TS + 220)
        assert ext["ok"] is True
        assert len(ext.get("equipment_drops", [])) >= 1
        q_after_rl = eng.get_quests("2001", now_ts=NOW_TS + 220)
        wq_rl = next(q for q in q_after_rl["weekly"] if q["id"] == "wq_roguelike_3")
        assert wq_rl["progress"] >= 1

        # 5) Offline expedition yields tier-scaled equipment & crystal
        eng.start_expedition("2001", "exp_tolbana_patrol", now_ts=NOW_TS + 300)
        got_exp_gear = False
        for try_seed in range(1, 15):
            exp_row = eng.db.get_expedition("2001")
            assert exp_row is not None
            with eng.db.transaction():
                eng.db._conn.execute(
                    "UPDATE expeditions SET ends_at = ?, claimed = 0 WHERE user_id = '2001'",
                    (NOW_TS + 250,),
                )
            claim = eng.claim_expedition("2001", now_ts=NOW_TS + 400 + try_seed)
            if claim.get("equipment_drops"):
                got_exp_gear = True
                break
            eng.start_expedition("2001", "exp_tolbana_patrol", now_ts=NOW_TS + 400 + try_seed)
        assert got_exp_gear is True

        # 6) Solo floor boss drops LA Named + personal First-Clear Set + dq_boss_1 quest progress
        p2001 = eng.db.get_player("2001")
        assert p2001 is not None
        p2001.highest_cleared_floor = 0
        eng.db.save_player(p2001)
        eng.db.save_floor_exploration("2001", 1, 100, True, True, None, NOW_TS + 500)
        eng.start_floor_boss("2001", floor=1, mode="normal", now_ts=NOW_TS + 501)
        boss_end: dict[str, Any] = {"finished": False}
        for turn_i in range(12):
            if "2001" in eng.active_combats:
                eng.active_combats["2001"].enemy_hp = 1
                if eng.active_combats["2001"].boss_state is not None:
                    eng.active_combats["2001"].boss_state.hp = 1
            boss_end = eng.combat_action("2001", "attack", now_ts=NOW_TS + 502 + turn_i)
            if boss_end.get("finished"):
                break
        assert boss_end["victory"] is True
        assert len(boss_end["rewards"]["equipment_drops"]) >= 2  # LA Named + personal First-Clear Set
        q_after_boss = eng.get_quests("2001", now_ts=NOW_TS + 520)
        dq_boss = next(q for q in q_after_boss["daily"] if q["id"] == "dq_boss_1")
        assert dq_boss["progress"] >= 1

        # 7) Co-op Raid grants EVERY teammate floor-tier gear while LA keeps exclusive Named + wq_coop_5
        eng.travel_zone("2001", "town", now_ts=NOW_TS + 600)
        eng.travel_zone("2002", "town", now_ts=NOW_TS + 600)
        pty = eng.create_party("2001", floor=1, now_ts=NOW_TS + 601)
        eng.join_party(pty["party_id"], "2002", now_ts=NOW_TS + 602)
        eng.set_party_ready(pty["party_id"], "2001", True)
        eng.set_party_ready(pty["party_id"], "2002", True)
        eng.enter_boss_room(pty["party_id"], "2001", now_ts=NOW_TS + 603)
        raid_start = eng.start_party_raid(pty["party_id"], "2001", now_ts=NOW_TS + 604)
        rid = str(raid_start["raid_id"])
        raid_end: dict[str, Any] = {"finished": False}
        for turn_i in range(12):
            rsess = eng.multiplayer.active_raids.get(rid)
            if rsess is None or rsess.finished:
                break
            rsess.boss_hp = 1
            bstate = getattr(rsess, "boss_state", None)
            if bstate is not None:
                bstate.hp = 1
            eng.submit_raid_action(rid, "2001", "attack", now_ts=NOW_TS + 605 + turn_i * 2)
            raid_end = eng.submit_raid_action(rid, "2002", "attack", now_ts=NOW_TS + 606 + turn_i * 2)
            if raid_end.get("finished"):
                break
        assert raid_end["victory"] is True
        rewards_by_user = raid_end.get("rewards_by_user", {})
        assert "2001" in rewards_by_user and "2002" in rewards_by_user
        assert len(rewards_by_user["2001"]["equipment_drops"]) >= 1
        assert len(rewards_by_user["2002"]["equipment_drops"]) >= 1
        # Verify LA Named exclusivity (only LA winner gets Named)
        la_uid = str(raid_end.get("la_user_id", ""))
        non_la_uid = "2002" if la_uid == "2001" else "2001"
        assert rewards_by_user[la_uid]["la_reward"] is not None
        assert rewards_by_user[non_la_uid]["la_reward"] is None
        q_coop = eng.get_quests("2001", now_ts=NOW_TS + 650)
        wq_coop = next(q for q in q_coop["weekly"] if q["id"] == "wq_coop_5")
        assert wq_coop["progress"] >= 1

        # 8) World boss kill drops guaranteed materials + Set/Legendary + tracks wq_world_boss_5
        eng.travel_zone("2001", "town", now_ts=NOW_TS + 700)
        wb1 = eng.attack_floor_world_boss("2001", now_ts=NOW_TS + 701)
        wb_row = eng.db.get_active_world_boss()
        assert wb_row is not None
        with eng.db.transaction():
            eng.db._conn.execute("UPDATE world_boss SET current_hp = 1 WHERE id = ?", (wb_row.id,))
        wb_kill = eng.attack_floor_world_boss("2001", now_ts=NOW_TS + 765)
        assert wb_kill["defeated"] is True
        assert len(wb_kill.get("equipment_drops", [])) >= 1
        assert wb1["ok"] is True
        q_wb = eng.get_quests("2001", now_ts=NOW_TS + 765)
        wq_wb = next(q for q in q_wb["weekly"] if q["id"] == "wq_world_boss_5")
        assert wq_wb["progress"] >= 2
    finally:
        db.close()


# =============================================================================
# 2. All 12 New RPGEngine Methods, 5-Axis Upgrading & Wired Quests/Achievements
# =============================================================================
def test_r2_five_axis_equipment_upgrading_and_economy_lifecycle(tmp_path: Path) -> None:
    db, eng = _make_engine(tmp_path, "upgrade.db")
    try:
        _seed_rich_player(eng, "3001", style="sword", level=25, floor=1)

        # 1) Buy shop equipment + verify TIER_LOCKED anti-skip + open supply crate + ticket gacha pull
        with pytest.raises(GameError):
            eng.buy_shop_equipment("3001", slot="weapon", tier=3, rng_seed=5, now_ts=NOW_TS)
        shop_eq = eng.buy_shop_equipment("3001", slot="weapon", tier=2, rng_seed=5, now_ts=NOW_TS)
        assert shop_eq["ok"] is True
        shop_uid = int(shop_eq["equipment_result"]["item_uid"])

        crate_res = eng.open_supply_crate("3001", "gear_supply_crate_t1", slot="armor", rng_seed=7, now_ts=NOW_TS)
        assert crate_res["ok"] is True
        assert crate_res["equipment_result"]["slot"] == "armor"

        ticket_before = eng.db.get_item_qty("3001", "gacha_relic_ticket")
        col_before = eng.db.get_player("3001").col  # type: ignore[union-attr]
        gacha_res = eng.gacha_pull("3001", count=1, use_ticket=True, rng_seed=11, now_ts=NOW_TS)
        assert gacha_res["ok"] is True
        assert eng.db.get_item_qty("3001", "gacha_relic_ticket") == ticket_before - 1
        assert eng.db.get_player("3001").col == col_before  # type: ignore[union-attr]

        # 2) Named forge craft validates & produces authentic Named item (anneal_blade)
        named_craft = eng.forge_craft("3001", "forge_anneal_blade", rng_seed=13, now_ts=NOW_TS)
        assert named_craft["ok"] is True
        named_uid = int(named_craft["equipment_result"]["item_uid"])
        named_item = eng.db.get_equipment_by_id("3001", named_uid)
        assert named_item is not None and named_item.rarity == "named" and named_item.template_id == "anneal_blade"

        # Slot-targeted forge craft
        slot_craft = eng.forge_craft("3001", "forge_t1_gear", slot="helmet", rng_seed=15, now_ts=NOW_TS)
        assert slot_craft["equipment_result"]["slot"] == "helmet"

        # 3) Batch enhance (+0 -> +5) & dq_enhance_1 tracking
        be = eng.batch_enhance_equipment("3001", shop_uid, target_level=5, rng_seed=21, now_ts=NOW_TS)
        assert be["ok"] is True and be["end_level"] == 5 and be["attempts"] >= 5
        q_enh = eng.get_quests("3001", now_ts=NOW_TS)
        assert next(q for q in q_enh["daily"] if q["id"] == "dq_enhance_1")["progress"] >= 1

        # 4) Temper ★0 -> ★5 (works on BOTH regular gear AND Named gear!)
        for star in range(1, 6):
            tr = eng.temper_equipment("3001", named_uid, now_ts=NOW_TS)
            assert tr["temper_level"] == star
        with pytest.raises(GameError):
            eng.temper_equipment("3001", named_uid, now_ts=NOW_TS)

        # 5) Tier evolution (T2 -> T3) and Rarity promotion (plain/fine -> next rarity)
        ev = eng.evolve_equipment_tier("3001", shop_uid, now_ts=NOW_TS)
        assert ev["old_tier"] == 2 and ev["new_tier"] == 3
        old_rar = eng.db.get_equipment_by_id("3001", shop_uid).rarity  # type: ignore[union-attr]
        if old_rar != "legendary":
            pr = eng.promote_equipment_rarity("3001", shop_uid, rng_seed=31, now_ts=NOW_TS)
            assert pr["new_rarity"] != pr["old_rarity"]

        # 6) Socket crystal -> zero-destruction swap -> unsocket
        sk1 = eng.socket_equipment_crystal("3001", shop_uid, "socket_crystal_crimson", now_ts=NOW_TS)
        assert sk1["crystal_id"] == "socket_crystal_crimson" and not sk1.get("returned_crystal_id")
        crim_after_socket = eng.db.get_item_qty("3001", "socket_crystal_crimson")
        sk2 = eng.socket_equipment_crystal("3001", shop_uid, "socket_crystal_aegis", now_ts=NOW_TS)
        assert sk2["crystal_id"] == "socket_crystal_aegis" and sk2["returned_crystal_id"] == "socket_crystal_crimson"
        assert eng.db.get_item_qty("3001", "socket_crystal_crimson") == crim_after_socket + 1
        unsk = eng.unsocket_equipment_crystal("3001", shop_uid, now_ts=NOW_TS)
        assert unsk["returned_crystal_id"] == "socket_crystal_aegis"

        # 7) Expand stone (+1 affix up to 4) & targeted swap_stone
        eq_before_stone = eng.db.get_equipment_by_id("3001", shop_uid)
        assert eq_before_stone is not None
        if len(eq_before_stone.affixes) < 4:
            old_cnt = len(eq_before_stone.affixes)
            exp_res = eng.apply_magic_stone("3001", shop_uid, "expand_stone", rng_seed=41)
            assert len(exp_res["affixes"]) == old_cnt + 1
        first_key = next(iter(eng.db.get_equipment_by_id("3001", shop_uid).affixes.keys()))  # type: ignore[union-attr]
        sw_res = eng.apply_magic_stone("3001", shop_uid, "swap_stone", target_affix_key=first_key, rng_seed=43)
        assert first_key not in sw_res["affixes"]

        # 8) Transfer enhance + temper from shop_uid to another unequipped item
        eng.temper_equipment("3001", shop_uid, now_ts=NOW_TS)
        target_eq = eng.buy_shop_equipment("3001", slot="weapon", tier=2, rng_seed=45, now_ts=NOW_TS)
        target_uid = int(target_eq["equipment_result"]["item_uid"])
        tf = eng.transfer_enhance("3001", shop_uid, target_uid, include_temper=True, now_ts=NOW_TS)
        assert tf["ok"] is True
        src_after = eng.db.get_equipment_by_id("3001", shop_uid)
        dst_after = eng.db.get_equipment_by_id("3001", target_uid)
        assert src_after is not None and src_after.enhance_level == 0 and src_after.temper_level == 0
        assert dst_after is not None and dst_after.enhance_level == 5 and dst_after.temper_level == 1

        # 9) Auto-equip best strictly upgrades or maintains CP
        ae = eng.auto_equip_best("3001", now_ts=NOW_TS)
        assert ae["ok"] is True and ae["combat_power_after"] >= ae["combat_power_before"]

        # 10) Dismantle single & bulk dismantle (protects +5+, tempered, socketed, locked, equipped, set/legendary/named)
        dism_res = eng.dismantle_equipment("3001", shop_uid, now_ts=NOW_TS)
        assert dism_res["ok"] is True and dism_res["items_gained"].get("forge_scrap", 0) >= 1

        junk1 = eng.db.add_equipment(
            EquipmentItem(0, "3001", "j1", "舊皮甲", "armor", "plain", 1, "", 0, 0, 10, 0, 0, 3, {}, created_at=NOW_TS)
        )
        junk2 = eng.db.add_equipment(
            EquipmentItem(0, "3001", "j2", "舊布靴", "boots", "fine", 1, "", 0, 0, 10, 0, 0, 3, {}, created_at=NOW_TS)
        )
        safe_tempered = eng.db.add_equipment(
            EquipmentItem(0, "3001", "j3", "淬鍊短靴", "boots", "plain", 1, "", 0, 0, 10, 0, 0, 3, {}, temper_level=1, created_at=NOW_TS)
        )
        safe_locked = eng.db.add_equipment(
            EquipmentItem(0, "3001", "j4", "鎖定短靴", "boots", "plain", 1, "", 0, 0, 10, 0, 0, 3, {}, is_locked=True, created_at=NOW_TS)
        )
        bulk = eng.bulk_dismantle_equipment("3001", max_rarity="fine", now_ts=NOW_TS)
        assert junk1.id in bulk["dismantled_uids"]
        assert junk2.id in bulk["dismantled_uids"]
        assert safe_tempered.id not in bulk["dismantled_uids"]
        assert safe_locked.id not in bulk["dismantled_uids"]
        assert eng.db.get_equipment_by_id("3001", safe_tempered.id) is not None
        assert eng.db.get_equipment_by_id("3001", safe_locked.id) is not None

        # 11) Mine & cook wired quests (dq_mine_3, dq_cook_1)
        eng.mine_gather("3001", floor=1, now_ts=NOW_TS + 10)
        eng.cook_dish("3001", "cook_boar_roast", now_ts=NOW_TS + 15)
        q_life = eng.get_quests("3001", now_ts=NOW_TS + 15)
        assert next(q for q in q_life["daily"] if q["id"] == "dq_mine_3")["progress"] >= 1
        assert next(q for q in q_life["daily"] if q["id"] == "dq_cook_1")["progress"] >= 1
    finally:
        db.close()


# =============================================================================
# 3. End-to-End Async Discord View Tests (Continue-Exploring, Chest, Raid, UIs)
# =============================================================================
def test_r2_post_combat_continue_exploring_button_loop_async(tmp_path: Path) -> None:
    db, eng = _make_engine(tmp_path, "ux_loop.db")
    try:
        _seed_rich_player(eng, "4001", style="sword", level=25, floor=1)

        async def _run() -> None:
            # Find a combat encounter on Floor 1
            seed = 1
            res: dict[str, Any] = {}
            while seed < 40:
                res = eng.explore_floor("4001", steps=1, now_ts=NOW_TS + seed, rng_seed=seed)
                seed += 1
                if res.get("chest"):
                    eng.open_chest("4001", action="leave", now_ts=NOW_TS + seed)
                    continue
                if res.get("in_combat"):
                    break
            assert res.get("in_combat") is True

            # Set enemy HP to 1 so clicking Attack in SoloCombatView kills the mob!
            eng.active_combats["4001"].enemy_hp = 1
            combat_view = SoloCombatView(eng, "4001")
            atk_btn = _find_button(combat_view, label_contains="斬擊")
            inter1 = FakeInteraction("4001")
            await atk_btn.callback(inter1)

            assert len(inter1.response.edits) == 1
            edit1 = inter1.response.edits[0]
            post_view = edit1["view"]
            assert isinstance(post_view, PostCombatView)
            embed1 = edit1["embed"]
            assert isinstance(embed1, discord.Embed)
            # Build combat embed preserves victory message & floor progress
            assert any("戰利品" in (f.name or "") or "探索進度" in (f.name or "") for f in embed1.fields)

            # Click "🧭 繼續探索" WITHOUT ever calling /tower again!
            cont_btn = _find_button(post_view, custom_id="sao_post:explore")
            assert "繼續探索" in (cont_btn.label or "")
            inter2 = FakeInteraction("4001")
            await cont_btn.callback(inter2)
            assert len(inter2.response.edits) == 1
            next_view = inter2.response.edits[0]["view"]
            assert isinstance(next_view, (SoloCombatView, ChestView, PostCombatView))

            # Clean up combat/pending chest if opened
            eng.active_combats.pop("4001", None)
            eng.db.save_floor_exploration(
                "4001",
                1,
                100,
                True,
                True,
                {"chest_tier": "iron", "name": "精鋼寶箱", "trap_type": "none", "floor": 1},
                NOW_TS + 100,
            )

            # Test ChestView open -> transitions cleanly to PostCombatView (never view=None!)
            chest_view = ChestView(eng, "4001")
            open_btn = _find_button(chest_view, label_contains="開啟寶箱")
            inter_c = FakeInteraction("4001")
            await open_btn.callback(inter_c)
            assert isinstance(inter_c.response.edits[0]["view"], PostCombatView)

            # Test Boss Gate -> Boss button -> Multi-phase Floor Boss victory -> Next Floor button -> Floor 2 TowerFloorView
            eng.db.save_floor_exploration("4001", 1, 100, True, True, None, NOW_TS + 200)
            gate_post = PostCombatView(eng, "4001", combat_mode="field", floor=1, outcome="victory", boss_gate_unlocked=True)
            boss_btn = _find_button(gate_post, custom_id="sao_post:boss")
            inter_b = FakeInteraction("4001")
            await boss_btn.callback(inter_b)
            cur_view: discord.ui.View = inter_b.response.edits[0]["view"]
            assert isinstance(cur_view, SoloCombatView)

            for _ in range(12):
                if not isinstance(cur_view, SoloCombatView):
                    break
                if "4001" in eng.active_combats:
                    eng.active_combats["4001"].enemy_hp = 1
                    if eng.active_combats["4001"].boss_state is not None:
                        eng.active_combats["4001"].boss_state.hp = 1
                inter_step = FakeInteraction("4001")
                await _find_button(cur_view, label_contains="斬擊").callback(inter_step)
                cur_view = inter_step.response.edits[0]["view"]
            assert isinstance(cur_view, PostCombatView)
            next_fl_btn = _find_button(cur_view, custom_id="sao_post:next_floor")
            inter_nf = FakeInteraction("4001")
            await next_fl_btn.callback(inter_nf)
            assert isinstance(inter_nf.response.edits[0]["view"], TowerFloorView)
            assert eng.db.get_player("4001").current_floor == 2  # type: ignore[union-attr]

            # Test Standard Defeat prioritizes Town Rest (heals back to full HP)
            p = eng.db.get_player("4001")
            assert p is not None
            p.hp = 1
            p.zone = "field"
            eng.db.save_player(p)
            defeat_view = PostCombatView(eng, "4001", combat_mode="field", floor=2, outcome="defeat", hp_ratio=0.01)
            town_btn = _find_button(defeat_view, custom_id="sao_post:town")
            assert "回城" in (town_btn.label or "")
            inter_t = FakeInteraction("4001")
            await town_btn.callback(inter_t)
            assert isinstance(inter_t.response.edits[0]["view"], TowerFloorView)
            prof_healed = eng.get_profile("4001")
            assert prof_healed["zone"] == "town" and prof_healed["hp"] == prof_healed["max_hp"]

            # Test Hardcore Permadeath strictly OMITS explore and shows Monument
            hc_view = PostCombatView(eng, "4001", combat_mode="field", floor=2, outcome="defeat", is_hardcore_dead=True)
            cids = {getattr(c, "custom_id", "") for c in hc_view.children}
            assert "sao_post:explore" not in cids
            assert "sao_post:monument" in cids

            # Test F100 clear shows Nightmare button
            f100_view = PostCombatView(eng, "4001", combat_mode="boss", floor=100, outcome="victory", unlocked_next_floor=100)
            assert any(str(getattr(c, "custom_id", "")).startswith("sao_post:nightmare:101") for c in f100_view.children)

        asyncio.run(_run())
    finally:
        db.close()


def test_r2_roguelike_secret_realm_and_post_coop_raid_views_async(tmp_path: Path) -> None:
    db, eng = _make_engine(tmp_path, "ux_modes.db")
    try:
        _seed_rich_player(eng, "5001", style="sword", level=35, floor=1)
        _seed_rich_player(eng, "5002", style="rapier", level=35, floor=1)

        async def _run() -> None:
            # 1) Roguelike dynamic node buttons + extract -> PostCombatView
            rl_res = eng.start_roguelike("5001", now_ts=NOW_TS, rng_seed=5)
            rl_view = RoguelikeView(eng, "5001", nodes=rl_res["nodes"])
            node_btns = [c for c in rl_view.children if str(getattr(c, "custom_id", "")).startswith("sao_rl:node:")]
            assert len(node_btns) == len(rl_res["nodes"])
            ext_btn = _find_button(rl_view, custom_id="sao_rl:extract")
            inter_ext = FakeInteraction("5001")
            await ext_btn.callback(inter_ext)
            assert isinstance(inter_ext.response.edits[0]["view"], PostCombatView)

            # 2) SecretRealmView explore & return-to-town cleanses miasma
            eng.enter_secret_realm("5001", action="enter", now_ts=NOW_TS + 10)
            sr_view = SecretRealmView(eng, "5001")
            inter_sr = FakeInteraction("5001")
            await _find_button(sr_view, label_contains="繼續探索秘境").callback(inter_sr)
            assert isinstance(inter_sr.response.edits[0]["view"], SecretRealmView)
            inter_clean = FakeInteraction("5001")
            await _find_button(sr_view, label_contains="淨化瘴氣").callback(inter_clean)
            assert isinstance(inter_clean.response.edits[0]["view"], TowerFloorView)
            assert eng.db.get_player("5001").miasma_stacks == 0  # type: ignore[union-attr]

            # 3) Co-op Raid completion transitions to PUBLIC PostCoopRaidView
            eng.db.save_floor_exploration("5001", 1, 100, True, True, None, NOW_TS + 20)
            pty = eng.create_party("5001", floor=1, now_ts=NOW_TS + 21)
            eng.join_party(pty["party_id"], "5002", now_ts=NOW_TS + 22)
            eng.set_party_ready(pty["party_id"], "5001", True)
            eng.set_party_ready(pty["party_id"], "5002", True)
            eng.enter_boss_room(pty["party_id"], "5001", now_ts=NOW_TS + 23)
            raid_st = eng.start_party_raid(pty["party_id"], "5001", now_ts=NOW_TS + 24)
            rid = str(raid_st["raid_id"])

            cur_raid_view: discord.ui.View = CoopRaidView(eng, rid)
            for _ in range(12):
                if not isinstance(cur_raid_view, CoopRaidView):
                    break
                rsess = eng.multiplayer.active_raids.get(rid)
                if rsess is not None:
                    rsess.boss_hp = 1
                    bstate = getattr(rsess, "boss_state", None)
                    if bstate is not None:
                        bstate.hp = 1
                inter_p1 = FakeInteraction("5001")
                await _find_button(cur_raid_view, label_contains="普通斬擊").callback(inter_p1)
                inter_p2 = FakeInteraction("5002")
                await _find_button(cur_raid_view, label_contains="普通斬擊").callback(inter_p2)
                if inter_p2.response.edits:
                    cur_raid_view = inter_p2.response.edits[0]["view"]
            assert isinstance(cur_raid_view, PostCoopRaidView)
            # Public view allows ANY member (both 5001 and 5002)
            assert await cur_raid_view.interaction_check(FakeInteraction("5002")) is True
            # Member opens personal tower HUD ephemerally
            inter_hud = FakeInteraction("5002")
            await _find_button(cur_raid_view, custom_id="sao_post_raid:my_tower").callback(inter_hud)
            assert len(inter_hud.response.messages) == 1
            assert inter_hud.response.messages[0]["ephemeral"] is True
            assert isinstance(inter_hud.response.messages[0]["view"], TowerFloorView)

        asyncio.run(_run())
    finally:
        db.close()


def test_r2_interactive_workshop_bag_and_shop_views_async(tmp_path: Path) -> None:
    db, eng = _make_engine(tmp_path, "ux_dashboards.db")
    try:
        _seed_rich_player(eng, "6001", style="sword", level=25, floor=1)

        async def _run() -> None:
            # 1) WorkshopView: enhance +1, toggle protection, temper, craft, switch to BagEquipView
            wview = WorkshopView(eng, "6001")
            assert wview.selected_item_uid is not None
            inter_enh = FakeInteraction("6001")
            await _find_button(wview, label_contains="強化 +1").callback(inter_enh)
            assert len(inter_enh.response.edits) == 1
            assert isinstance(inter_enh.response.edits[0]["view"], WorkshopView)

            prot_btn = _find_button(wview, label_contains="保護符")
            inter_prot = FakeInteraction("6001")
            await prot_btn.callback(inter_prot)
            assert wview.protection_on is True
            assert "開" in (prot_btn.label or "")

            inter_tmp = FakeInteraction("6001")
            await _find_button(wview, label_contains="鍛星淬鍊").callback(inter_tmp)
            assert eng.db.get_equipment_by_id("6001", wview.selected_item_uid).temper_level >= 1  # type: ignore[union-attr]

            # Transition Workshop -> BagEquipView -> Auto-Equip Best -> Back to WorkshopView
            inter_bag = FakeInteraction("6001")
            await _find_button(wview, label_contains="切換裝備背包").callback(inter_bag)
            bview = inter_bag.response.edits[0]["view"]
            assert isinstance(bview, BagEquipView)

            inter_best = FakeInteraction("6001")
            await _find_button(bview, label_contains="一鍵裝備最強").callback(inter_best)
            assert isinstance(inter_best.response.edits[0]["view"], BagEquipView)

            inter_back = FakeInteraction("6001")
            await _find_button(bview, label_contains="開啟莉茲貝特工坊").callback(inter_back)
            assert isinstance(inter_back.response.edits[0]["view"], WorkshopView)

            # 2) ShopView: buy x1, buy floor weapon, open supply crate, gacha ticket pull
            sview = ShopView(eng, "6001", category="potions_crystals")
            inter_buy = FakeInteraction("6001")
            await _find_button(sview, label_contains="購買 x1").callback(inter_buy)
            assert isinstance(inter_buy.response.edits[0]["view"], ShopView)

            inter_weap = FakeInteraction("6001")
            await _find_button(sview, label_contains="購買樓層武器").callback(inter_weap)
            assert isinstance(inter_weap.response.edits[0]["view"], ShopView)

            inter_crate = FakeInteraction("6001")
            await _find_button(sview, label_contains="開啟補給箱").callback(inter_crate)
            assert isinstance(inter_crate.response.edits[0]["view"], ShopView)

            inter_tkt = FakeInteraction("6001")
            await _find_button(sview, label_contains="秘寶券抽取").callback(inter_tkt)
            assert isinstance(inter_tkt.response.edits[0]["view"], ShopView)

        asyncio.run(_run())
    finally:
        db.close()


# =============================================================================
# 4. Adversarial Lockouts, Immutability, Ownership & Double-Click Concurrency
# =============================================================================
def test_r2_adversarial_lockouts_immutability_and_double_click_safety(tmp_path: Path) -> None:
    db, eng = _make_engine(tmp_path, "adv.db")
    try:
        _seed_rich_player(eng, "7001", style="sword", level=30, floor=1)
        craft = eng.forge_craft("7001", "forge_anneal_blade", rng_seed=1, now_ts=NOW_TS)
        named_uid = int(craft["equipment_result"]["item_uid"])
        w2 = eng.buy_shop_equipment("7001", slot="weapon", tier=1, rng_seed=2, now_ts=NOW_TS)
        w2_uid = int(w2["equipment_result"]["item_uid"])

        # 1) Named gear strictly blocks expand_stone & promote_equipment_rarity
        with pytest.raises(GameError):
            eng.apply_magic_stone("7001", named_uid, "expand_stone")
        with pytest.raises(GameError):
            eng.promote_equipment_rarity("7001", named_uid, now_ts=NOW_TS)

        # 2) Locked & Equipped gear strictly blocks dismantle & transfer_enhance source
        eng.toggle_lock_item("7001", w2_uid)
        with pytest.raises(GameError):
            eng.dismantle_equipment("7001", w2_uid, now_ts=NOW_TS)
        with pytest.raises(GameError):
            eng.transfer_enhance("7001", w2_uid, named_uid, now_ts=NOW_TS)
        eng.toggle_lock_item("7001", w2_uid)

        # 3) Bulk dismantle rejects set/legendary/named max_rarity
        for bad_rar in ("set", "legendary", "named"):
            with pytest.raises(GameError):
                eng.bulk_dismantle_equipment("7001", max_rarity=bad_rar, now_ts=NOW_TS)

        # 4) Mid-boss combat lockouts on ALL Round 2 workshop/shop/equip mutations
        eng.db.save_floor_exploration("7001", 1, 100, True, True, None, NOW_TS + 10)
        eng.start_floor_boss("7001", floor=1, mode="normal", now_ts=NOW_TS + 11)
        for fn in (
            lambda: eng.batch_enhance_equipment("7001", w2_uid),
            lambda: eng.temper_equipment("7001", w2_uid),
            lambda: eng.evolve_equipment_tier("7001", w2_uid),
            lambda: eng.promote_equipment_rarity("7001", w2_uid),
            lambda: eng.socket_equipment_crystal("7001", w2_uid, "socket_crystal_crimson"),
            lambda: eng.transfer_enhance("7001", w2_uid, named_uid),
            lambda: eng.dismantle_equipment("7001", w2_uid),
            lambda: eng.bulk_dismantle_equipment("7001", max_rarity="fine"),
            lambda: eng.auto_equip_best("7001"),
            lambda: eng.buy_shop_equipment("7001", slot="weapon"),
            lambda: eng.open_supply_crate("7001", "gear_supply_crate_t1"),
        ):
            with pytest.raises(GameError):
                fn()
        eng.combat_action("7001", "retreat", now_ts=NOW_TS + 15)
        eng.travel_zone("7001", "town", now_ts=NOW_TS + 20)

        # 5) OwnerView rejects intruder & PostCombatView double-click transitions ONCE
        async def _check_concurrency() -> None:
            pv = PostCombatView(eng, "7001", combat_mode="field", floor=1, outcome="victory")
            intruder = FakeInteraction("9999", "PKer")
            assert await pv.interaction_check(intruder) is False
            assert len(intruder.response.messages) == 1 and intruder.response.messages[0]["ephemeral"] is True

            cont_btn = _find_button(pv, custom_id="sao_post:explore")
            i1, i2 = FakeInteraction("7001"), FakeInteraction("7001")
            await asyncio.gather(cont_btn.callback(i1), cont_btn.callback(i2))
            total_edits = len(i1.response.edits) + len(i2.response.edits)
            assert total_edits == 1, f"Double-click must transition exactly ONCE, got {total_edits}"
            assert pv._transitioned is True

            # Verify build_combat_embed preserves message even when logs non-empty
            em = build_combat_embed({"message": "🎉 頭目討伐成功！", "logs": ["第一擊 100 傷害"]})
            assert "頭目討伐成功" in (em.description or "")

        asyncio.run(_check_concurrency())
    finally:
        db.close()
