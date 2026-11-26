"""SAO Social & Economy Systems: Guilds (5 Ranks, Warehouse, Buffs, Raids) & Atomic Marketplace Escrow (ZERO discord imports)."""

from __future__ import annotations

import time
from typing import Any

from src.rpg.content.loader import SAOContentBundle
from src.rpg.database import RPGDatabase
from src.rpg.models import CombatSession, GameError, PlayerProfile, Rarity, ZoneType

GUILD_REJOIN_COOLDOWN_SEC = 12 * 3600  # 12 hours
DEFAULT_GUILD_RANKS: dict[str, dict[str, Any]] = {
    "leader": {"label": "會長", "manage_ranks": True, "warehouse_withdraw": True, "activate_buff": True, "start_raid": True},
    "vice_leader": {"label": "副會長", "manage_ranks": True, "warehouse_withdraw": True, "activate_buff": True, "start_raid": True},
    "officer": {"label": "幹部", "manage_ranks": False, "warehouse_withdraw": True, "activate_buff": True, "start_raid": True},
    "elite": {"label": "菁英", "manage_ranks": False, "warehouse_withdraw": True, "activate_buff": False, "start_raid": False},
    "member": {"label": "成員", "manage_ranks": False, "warehouse_withdraw": False, "activate_buff": False, "start_raid": False},
}
RANK_ALIASES: dict[str, str] = {
    "會長": "leader",
    "團長": "leader",
    "leader": "leader",
    "副會長": "vice_leader",
    "副團長": "vice_leader",
    "vice_leader": "vice_leader",
    "vice": "vice_leader",
    "幹部": "officer",
    "攻略幹部": "officer",
    "officer": "officer",
    "菁英": "elite",
    "菁英成員": "elite",
    "elite": "elite",
    "成員": "member",
    "正式成員": "member",
    "member": "member",
}


def _now(now_ts: int | None) -> int:
    return int(now_ts if now_ts is not None else time.time())


def _normalize_rank(rank_name: str) -> str:
    key = str(rank_name or "").strip().lower()
    if key in RANK_ALIASES:
        return RANK_ALIASES[key]
    raw = str(rank_name or "").strip()
    if raw in RANK_ALIASES:
        return RANK_ALIASES[raw]
    raise GameError(
        f"無效的公會階級名稱：{rank_name}（支援：會長／副會長／幹部／菁英／成員）",
        code="INVALID_GUILD_RANK",
    )


def _get_member_rank(db: RPGDatabase, guild_id: int, user_id: str) -> str | None:
    for m in db.get_guild_members(guild_id):
        if str(m["user_id"]) == str(user_id):
            return str(m["rank_name"])
    return None


def _has_perm(rank_name: str | None, perm: str) -> bool:
    if not rank_name:
        return False
    cfg = DEFAULT_GUILD_RANKS.get(rank_name, DEFAULT_GUILD_RANKS["member"])
    return bool(cfg.get(perm, False))


def _require_town(player: PlayerProfile, label: str) -> None:
    if player.in_boss_battle:
        raise GameError(f"頭目戰進行中無法操作{label}！", code="ACTION_BLOCKED_IN_BOSS")
    if player.zone != ZoneType.TOWN:
        raise GameError(f"{label}僅能在城鎮安全區（圈內）執行！", code="TOWN_ONLY_ACTION")


# =============================================================================
# Guild System (公會)
# =============================================================================
def create_guild(
    db: RPGDatabase,
    user_id: str,
    name: str,
    tag: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Create a new SAO Guild with 5 customizable ranks."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.guild_id is not None:
        raise GameError("你已經所屬公會，請先退出目前公會再創立新公會！", code="ALREADY_IN_GUILD")
    if player.guild_left_at > 0 and (ts - player.guild_left_at) < GUILD_REJOIN_COOLDOWN_SEC:
        rem = GUILD_REJOIN_COOLDOWN_SEC - (ts - player.guild_left_at)
        raise GameError(f"退出公會後需等待 12 小時冷卻（尚餘 {rem // 60} 分鐘）！", code="GUILD_REJOIN_COOLDOWN")

    clean_name = str(name or "").strip()
    clean_tag = str(tag or "").strip().upper()
    if len(clean_name) < 2 or len(clean_name) > 24:
        raise GameError("公會名稱長度需為 2～24 字元。", code="INVALID_GUILD_NAME")
    if len(clean_tag) < 2 or len(clean_tag) > 6:
        raise GameError("公會簡稱標籤需為 2～6 字元。", code="INVALID_GUILD_TAG")

    guild = db.create_guild(clean_name, clean_tag, user_id, DEFAULT_GUILD_RANKS, ts)
    db.add_guild_log(guild.id, user_id, "create", f"{player.display_name} 創立公會 [{guild.tag}] {guild.name}", ts)
    db.unlock_achievement(user_id, "sao_ach_guild", ts)
    return {
        "ok": True,
        "guild_id": guild.id,
        "guild": guild,
        "ranks": list(DEFAULT_GUILD_RANKS.keys()),
        "message": f"🏰 公會 [{guild.tag}]【{guild.name}】正式成立！已設立 5 階級權限與公會倉庫。",
    }


def join_guild(
    db: RPGDatabase,
    user_id: str,
    guild_id: int,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Join an existing SAO Guild (enforcing 12-hour rejoin cooldown & member capacity)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.guild_id is not None:
        raise GameError("你目前已經加入其他公會！", code="ALREADY_IN_GUILD")
    if player.guild_left_at > 0 and (ts - player.guild_left_at) < GUILD_REJOIN_COOLDOWN_SEC:
        rem = GUILD_REJOIN_COOLDOWN_SEC - (ts - player.guild_left_at)
        raise GameError(f"退會冷卻時間尚未結束（需滿 12 小時，尚餘 {rem // 60} 分鐘）！", code="GUILD_REJOIN_COOLDOWN")

    guild = db.get_guild(int(guild_id))
    if guild is None:
        raise GameError(f"找不到指定的公會編號：{guild_id}", code="GUILD_NOT_FOUND")
    if guild.member_count >= guild.max_members:
        raise GameError(f"公會【{guild.name}】成員已達上限（{guild.max_members} 人）！", code="GUILD_FULL")

    db.add_guild_member(guild.id, user_id, "member", ts)
    db.add_guild_log(guild.id, user_id, "join", f"{player.display_name} 加入公會", ts)
    db.unlock_achievement(user_id, "sao_ach_guild", ts)
    updated = db.get_guild(guild.id)
    return {
        "ok": True,
        "guild_id": guild.id,
        "guild": updated,
        "rank": "member",
        "message": f"🤝 歡迎加入公會 [{guild.tag}]【{guild.name}】！",
    }


def leave_guild(
    db: RPGDatabase,
    user_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Leave current guild (Leader MUST transfer leadership if other members remain; triggers 12h cooldown)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    if player.guild_id is None:
        raise GameError("你目前尚未加入任何公會。", code="NOT_IN_GUILD")

    guild = db.get_guild(player.guild_id)
    if guild is None:
        player.guild_id = None
        db.save_player(player)
        raise GameError("公會資料不存在。", code="GUILD_NOT_FOUND")

    members = db.get_guild_members(guild.id)
    if guild.leader_id == user_id and len(members) > 1:
        raise GameError(
            "會長在仍有其他公會成員時無法直接退會！請先將「會長」職位轉交給其他成員。",
            code="LEADER_MUST_TRANSFER",
        )

    db.remove_guild_member(guild.id, user_id, ts)
    db.add_guild_log(guild.id, user_id, "leave", f"{player.display_name} 離開公會", ts)
    return {
        "ok": True,
        "guild_id": guild.id,
        "rejoin_available_at": ts + GUILD_REJOIN_COOLDOWN_SEC,
        "message": f"🚪 已退出公會【{guild.name}】（12 小時內無法重新加入其他公會）。",
    }


def set_guild_rank(
    db: RPGDatabase,
    leader_id: str,
    target_id: str,
    rank_name: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Assign one of the 5 Guild Ranks (supports leadership transfer)."""
    ts = _now(now_ts)
    actor = db.get_player(leader_id)
    if actor is None or actor.guild_id is None:
        raise GameError("你目前沒有加入任何公會。", code="NOT_IN_GUILD")
    guild = db.get_guild(actor.guild_id)
    if guild is None:
        raise GameError("找不到公會資料。", code="GUILD_NOT_FOUND")

    actor_rank = _get_member_rank(db, guild.id, leader_id)
    if not _has_perm(actor_rank, "manage_ranks"):
        raise GameError("權限不足！僅會長或副會長可指派公會階級。", code="GUILD_PERMISSION_DENIED")

    target_rank_cur = _get_member_rank(db, guild.id, target_id)
    if target_rank_cur is None:
        raise GameError("目標玩家不在此公會中。", code="TARGET_NOT_IN_GUILD")

    norm_rank = _normalize_rank(rank_name)
    if norm_rank == "leader":
        if guild.leader_id != leader_id:
            raise GameError("只有現任會長能轉移會長職位！", code="GUILD_PERMISSION_DENIED")
        guild.leader_id = str(target_id)
        db.update_guild(guild)
        db.update_guild_member(guild.id, leader_id, rank_name="vice_leader")
        db.update_guild_member(guild.id, target_id, rank_name="leader")
    else:
        if target_id == guild.leader_id:
            raise GameError("無法直接降級現任會長。", code="CANNOT_DEMOTE_LEADER")
        db.update_guild_member(guild.id, target_id, rank_name=norm_rank)

    label = DEFAULT_GUILD_RANKS[norm_rank]["label"]
    db.add_guild_log(guild.id, leader_id, "set_rank", f"指派 {target_id} 為 {label} ({norm_rank})", ts)
    return {
        "ok": True,
        "guild_id": guild.id,
        "target_id": target_id,
        "rank_name": norm_rank,
        "rank_label": label,
        "message": f"🎖️ 已將公會成員指派為【{label}】！",
    }


def guild_contribute(
    db: RPGDatabase,
    user_id: str,
    col_amount: int,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Donate Col to the Guild Contribution Vault (`公會貢獻金庫`), earning Merit & Guild EXP."""
    ts = _now(now_ts)
    if isinstance(col_amount, bool) or not isinstance(col_amount, int) or col_amount <= 0:
        raise GameError("貢獻金額必須為正整數柯爾。", code="INVALID_CONTRIBUTION")

    player = db.get_player(user_id)
    if player is None or player.guild_id is None:
        raise GameError("你目前沒有所屬公會。", code="NOT_IN_GUILD")
    if player.col < col_amount:
        raise GameError(f"柯爾不足！目前僅有 {player.col} 柯爾。", code="INSUFFICIENT_COL")

    guild = db.get_guild(player.guild_id)
    if guild is None:
        raise GameError("找不到公會資料。", code="GUILD_NOT_FOUND")

    merit_gain = max(1, col_amount // 10)
    exp_gain = max(1, col_amount // 5)
    with db.transaction():
        player.col -= col_amount
        player.updated_at = ts
        db.save_player(player)
        guild.vault_col += col_amount
        guild.merit_points += merit_gain
        guild.exp += exp_gain
        while guild.exp >= guild.level * 1000:
            guild.exp -= guild.level * 1000
            guild.level += 1
            guild.max_members = min(50, 20 + (guild.level - 1) * 5)
        db.update_guild(guild)
        db.update_guild_member(guild.id, user_id, add_col=col_amount, add_merit=merit_gain)
        db.add_guild_log(guild.id, user_id, "contribute", f"{player.display_name} 捐獻 {col_amount} 柯爾", ts)

    return {
        "ok": True,
        "guild_id": guild.id,
        "contributed_col": col_amount,
        "merit_gain": merit_gain,
        "vault_col": guild.vault_col,
        "guild_level": guild.level,
        "guild": guild,
        "message": f"💰 感謝捐獻 {col_amount} 柯爾至公會金庫（現有 {guild.vault_col} 柯爾，公會 Lv.{guild.level}，獲得 {merit_gain} 貢獻值）！",
    }


def guild_warehouse_deposit(
    db: RPGDatabase,
    user_id: str,
    item_uid: int,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Deposit an unequipped unlocked non-Named equipment piece into the Guild Warehouse (`公會倉庫`)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None or player.guild_id is None:
        raise GameError("你目前沒有所屬公會。", code="NOT_IN_GUILD")
    _require_town(player, "公會倉庫")

    eq = db.get_equipment_by_id(user_id, int(item_uid), include_escrowed=False)
    if eq is None:
        raise GameError(f"找不到欲存入公會倉庫的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
    if eq.is_equipped:
        raise GameError("裝備中的物品無法存入公會倉庫！", code="CANNOT_DEPOSIT_EQUIPPED")
    if eq.is_locked:
        raise GameError("已鎖定的裝備無法存入公會倉庫！", code="CANNOT_DEPOSIT_LOCKED")
    if eq.is_named or eq.rarity == Rarity.NAMED or eq.is_bound:
        raise GameError("名品或綁定裝備不可存入公會倉庫！", code="CANNOT_DEPOSIT_NAMED")

    snapshot = {
        "name": eq.name,
        "slot": eq.slot,
        "rarity": eq.rarity,
        "tier": eq.tier,
        "enhance_level": eq.enhance_level,
    }
    wh_id = db.deposit_guild_warehouse_equipment(player.guild_id, user_id, eq.id, snapshot, ts)
    db.add_guild_log(player.guild_id, user_id, "warehouse_deposit", f"{player.display_name} 存入【{eq.name}】(#{wh_id})", ts)
    return {
        "ok": True,
        "guild_id": player.guild_id,
        "warehouse_id": wh_id,
        "item_uid": eq.id,
        "item_name": eq.name,
        "logs": db.get_guild_logs(player.guild_id, limit=10),
        "message": f"📦 已將【{eq.name}】存入公會倉庫（倉儲編號 #{wh_id}）！",
    }


def guild_warehouse_withdraw(
    db: RPGDatabase,
    active_combats: dict[str, CombatSession],
    user_id: str,
    warehouse_id: int,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Withdraw gear from Guild Warehouse (Town-only, blocked mid-Boss, authorized ranks only)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None or player.guild_id is None:
        raise GameError("你目前沒有所屬公會。", code="NOT_IN_GUILD")
    if player.in_boss_battle or (user_id in active_combats and not active_combats[user_id].finished):
        raise GameError("頭目戰或戰鬥進行中禁止提領公會倉庫物資！", code="WAREHOUSE_BLOCKED_IN_BOSS")
    _require_town(player, "公會倉庫提領")

    rank = _get_member_rank(db, player.guild_id, user_id)
    if not _has_perm(rank, "warehouse_withdraw"):
        raise GameError("權限不足！一般成員無權提領公會倉庫，請聯絡幹部以上人員。", code="GUILD_PERMISSION_DENIED")

    res = db.withdraw_guild_warehouse_item(player.guild_id, user_id, int(warehouse_id), ts)
    iname = str((res.get("snapshot") or {}).get("name", f"#{warehouse_id}"))
    db.add_guild_log(player.guild_id, user_id, "warehouse_withdraw", f"{player.display_name} 提領【{iname}】(#{warehouse_id})", ts)
    return {
        "ok": True,
        "guild_id": player.guild_id,
        "warehouse_id": int(warehouse_id),
        "equipment_id": res.get("equipment_id"),
        "logs": db.get_guild_logs(player.guild_id, limit=10),
        "message": f"📤 已從公會倉庫提領【{iname}】並寫入公會異動紀錄！",
    }


def guild_activate_buff(
    db: RPGDatabase,
    user_id: str,
    buff_id: str = "rally",
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Activate Guild Rally (`集結`) buff for all guild members (authorized ranks only)."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None or player.guild_id is None:
        raise GameError("你目前沒有所屬公會。", code="NOT_IN_GUILD")
    guild = db.get_guild(player.guild_id)
    if guild is None:
        raise GameError("找不到公會資料。", code="GUILD_NOT_FOUND")

    rank = _get_member_rank(db, guild.id, user_id)
    if not _has_perm(rank, "activate_buff"):
        raise GameError("權限不足！僅會長、副會長或幹部可啟動公會【集結】增益。", code="GUILD_PERMISSION_DENIED")

    bid = str(buff_id or "rally").strip().lower()
    if bid not in ("rally", "vanguard", "fortune"):
        raise GameError(f"未知的公會增益種類：{buff_id}", code="INVALID_GUILD_BUFF")

    guild.active_buff_id = bid
    guild.active_buff_expires_at = ts + 7200
    db.update_guild(guild)
    db.add_guild_log(guild.id, user_id, "buff", f"{player.display_name} 啟動公會增益【{bid}】", ts)
    return {
        "ok": True,
        "guild_id": guild.id,
        "buff_id": bid,
        "expires_at": guild.active_buff_expires_at,
        "bonuses": {"atk_pct": 0.10, "def_pct": 0.10, "exp_bonus": 0.15},
        "message": f"🚩 公會號角響起！【集結（{bid}）】全體增益已啟動（持續 2 小時，攻防 +10%、經驗 +15%）！",
    }


def start_guild_raid(
    db: RPGDatabase,
    user_id: str,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Launch a timed Guild Raid (`限時公會討伐戰`) awarding guild EXP & merit."""
    ts = _now(now_ts)
    player = db.get_player(user_id)
    if player is None or player.guild_id is None:
        raise GameError("你目前沒有所屬公會。", code="NOT_IN_GUILD")
    guild = db.get_guild(player.guild_id)
    if guild is None:
        raise GameError("找不到公會資料。", code="GUILD_NOT_FOUND")

    rank = _get_member_rank(db, guild.id, user_id)
    if not _has_perm(rank, "start_raid"):
        raise GameError("權限不足！僅幹部以上可發起限時公會討伐戰。", code="GUILD_PERMISSION_DENIED")

    guild.raid_last_started_at = ts
    guild.exp += 250
    guild.merit_points += 50
    db.update_guild(guild)
    db.add_guild_log(guild.id, user_id, "guild_raid", f"{player.display_name} 發起限時公會討伐戰", ts)
    graid_id = f"graid_{guild.id}_{ts}"
    ends_at = ts + 1800
    return {
        "ok": True,
        "guild_id": guild.id,
        "guild_raid_id": graid_id,
        "raid_id": graid_id,
        "raid_started_at": ts,
        "raid_expires_at": ends_at,
        "ends_at": ends_at,
        "boss": {
            "name": f"公會討伐首領・第 {guild.level} 階守護者",
            "hp": 10000 * max(1, guild.level),
            "max_hp": 10000 * max(1, guild.level),
        },
        "guild_exp": guild.exp,
        "merit_points": guild.merit_points,
        "message": f"⚔️ 公會 [{guild.tag}]【{guild.name}】限時公會討伐戰已開戰（限時 30 分鐘，公會經驗 +250、榮耀 +50）！",
    }


# =============================================================================
# Player Marketplace (`市集`) — Atomic Escrow & Multi-Affix Search
# =============================================================================
def list_market_item(
    db: RPGDatabase,
    content: SAOContentBundle,
    seller_id: str,
    *,
    item_uid: int | None = None,
    item_id: str | None = None,
    qty: int = 1,
    price_col: int,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """List an equipment piece or stackable item/dish on the Player Marketplace with atomic escrow."""
    ts = _now(now_ts)
    if isinstance(price_col, bool) or not isinstance(price_col, int) or price_col <= 0:
        raise GameError("市集售價必須為正整數柯爾！", code="INVALID_PRICE")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        raise GameError("上架數量必須為正整數！", code="INVALID_QUANTITY")

    seller = db.get_player(seller_id)
    if seller is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(seller, "玩家市集上架")

    if item_uid is not None:
        eq = db.get_equipment_by_id(seller_id, int(item_uid), include_escrowed=False)
        if eq is None:
            raise GameError(f"找不到欲上架的裝備編號：{item_uid}", code="EQUIPMENT_NOT_FOUND")
        if eq.is_equipped:
            raise GameError("裝備中的物品無法上架市集，請先卸下！", code="LISTING_EQUIPPED_DENIED")
        if eq.is_locked:
            raise GameError("已鎖定的裝備受保護無法上架市集！", code="LISTING_LOCKED_DENIED")
        if eq.is_named or eq.rarity == Rarity.NAMED or eq.is_bound:
            raise GameError("名品（Named）與角色綁定裝備禁止上架交易市集！", code="LISTING_NAMED_DENIED")

        listing = db.create_market_listing(
            seller_id,
            seller.display_name,
            item_type="equipment",
            price_col=price_col,
            now_ts=ts,
            equipment_id=eq.id,
            item_name=eq.name,
            slot=eq.slot,
            weapon_style=eq.weapon_style,
            rarity=eq.rarity,
            affix_keys=list(eq.affixes.keys()),
            item_snapshot={"enhance_level": eq.enhance_level, "tier": eq.tier, "affixes": eq.affixes},
        )
        lowest = db.get_lowest_market_price(slot=eq.slot, rarity=eq.rarity)
        return {
            "ok": True,
            "listing_id": listing.id,
            "listing": listing,
            "lowest_price": lowest,
            "message": f"🏪 裝備【{eq.name}】已託管上架市集，定價 {price_col} 柯爾（同類最低參考價：{lowest or price_col} 柯爾）！",
        }

    if item_id is not None:
        spec = content.items_crystals.get(item_id)
        if not isinstance(spec, dict):
            raise GameError(f"未知的市集物品編號：{item_id}", code="UNKNOWN_ITEM")
        listing = db.create_market_listing(
            seller_id,
            seller.display_name,
            item_type="item",
            price_col=price_col,
            now_ts=ts,
            item_id=item_id,
            quantity=qty,
            item_name=str(spec.get("name", item_id)),
            slot=str(spec.get("category", "item")),
            rarity="plain",
            item_snapshot={"category": spec.get("category", "item")},
        )
        lowest = db.get_lowest_market_price(item_id=item_id)
        return {
            "ok": True,
            "listing_id": listing.id,
            "listing": listing,
            "lowest_price": lowest,
            "message": f"🏪 物品【{listing.item_name}】x{qty} 已託管上架市集，定價 {price_col} 柯爾！",
        }

    raise GameError("請提供要上架的裝備編號（item_uid）或物品編號（item_id）。", code="MISSING_LISTING_TARGET")


def search_market(
    db: RPGDatabase,
    *,
    weapon_class: str | None = None,
    rarity: str | None = None,
    affix1: str | None = None,
    affix2: str | None = None,
    slot: str | None = None,
    max_price: int | None = None,
) -> dict[str, Any]:
    """Search active marketplace listings by weapon class, rarity, slot, max price, and up to 2 affixes."""
    listings = db.search_market_listings(
        weapon_style=weapon_class,
        slot=slot,
        rarity=rarity,
        affix1=affix1,
        affix2=affix2,
        max_price=max_price,
        limit=25,
    )
    lowest_price = min((lt.price_col for lt in listings), default=None)
    return {
        "ok": True,
        "listings": listings,
        "count": len(listings),
        "lowest_price": lowest_price,
        "message": f"🔎 市集檢索完成，共找到 {len(listings)} 筆上架商品" + (f"（最低價 {lowest_price} 柯爾）。" if lowest_price else "。"),
    }


def buy_market_item(
    db: RPGDatabase,
    buyer_id: str,
    listing_id: int,
    *,
    now_ts: int | None = None,
) -> dict[str, Any]:
    """Atomically purchase an active Marketplace listing under BEGIN IMMEDIATE (Town-only)."""
    ts = _now(now_ts)
    buyer = db.get_player(buyer_id)
    if buyer is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    _require_town(buyer, "玩家市集購買")

    sold = db.buy_market_listing(int(listing_id), buyer_id, ts)
    return {
        "ok": True,
        "listing_id": sold.id,
        "listing": sold,
        "price_col": sold.price_col,
        "item_name": sold.item_name,
        "equipment_id": sold.equipment_id,
        "item_id": sold.item_id,
        "quantity": sold.quantity,
        "message": f"🤝 交易成交！已支付 {sold.price_col} 柯爾購得【{sold.item_name}】！",
    }


def cancel_market_listing(
    db: RPGDatabase,
    seller_id: str,
    listing_id: int,
) -> dict[str, Any]:
    """Cancel an active listing and return escrowed equipment/items to seller."""
    seller = db.get_player(seller_id)
    if seller is None:
        raise GameError("尚未建立艾恩葛朗特角色。", code="PLAYER_NOT_FOUND")
    cancelled = db.cancel_market_listing(int(listing_id), seller_id)
    return {
        "ok": True,
        "listing_id": cancelled.id,
        "listing": cancelled,
        "status": cancelled.status,
        "message": f"↩️ 已下架商品【{cancelled.item_name}】，物品已全數退回背包！",
    }
