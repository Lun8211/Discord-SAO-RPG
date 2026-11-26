"""Compatibility facade re-exporting all split SAO Discord UI Views from src.rpg.ui."""

from src.rpg.ui.views_core import OwnerView, ProfileView
from src.rpg.ui.views_party import CoopRaidView, DuelView, PartyLobbyView, WorldBossView
from src.rpg.ui.views_social import DailyQuestView, LeaderboardView, ShopView
from src.rpg.ui.views_tower import (
    ChestView,
    FloorSelect,
    RoguelikeView,
    SoloCombatView,
    TierSelect,
    TowerFloorView,
)

__all__ = [
    "ChestView",
    "CoopRaidView",
    "DailyQuestView",
    "DuelView",
    "FloorSelect",
    "LeaderboardView",
    "OwnerView",
    "PartyLobbyView",
    "ProfileView",
    "RoguelikeView",
    "ShopView",
    "SoloCombatView",
    "TierSelect",
    "TowerFloorView",
    "WorldBossView",
]
