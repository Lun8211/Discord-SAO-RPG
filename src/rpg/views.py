"""Compatibility facade re-exporting all split SAO Discord UI Views from src.rpg.ui."""

from src.rpg.ui.views_core import BagEquipView, OwnerView, ProfileView
from src.rpg.ui.views_party import (
    CoopRaidView,
    DuelView,
    PartyLobbyView,
    PostCoopRaidView,
    WorldBossView,
)
from src.rpg.ui.views_social import (
    DailyQuestView,
    LeaderboardView,
    ShopView,
    WorkshopView,
)
from src.rpg.ui.views_tower import (
    ChestView,
    FloorSelect,
    PostCombatView,
    RoguelikeView,
    SecretRealmView,
    SoloCombatView,
    TierSelect,
    TowerFloorView,
)

__all__ = [
    "BagEquipView",
    "ChestView",
    "CoopRaidView",
    "DailyQuestView",
    "DuelView",
    "FloorSelect",
    "LeaderboardView",
    "OwnerView",
    "PartyLobbyView",
    "PostCombatView",
    "PostCoopRaidView",
    "ProfileView",
    "RoguelikeView",
    "SecretRealmView",
    "ShopView",
    "SoloCombatView",
    "TierSelect",
    "TowerFloorView",
    "WorkshopView",
    "WorldBossView",
]
