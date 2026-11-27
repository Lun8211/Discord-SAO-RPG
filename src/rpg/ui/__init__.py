"""Split SAO Aincrad Discord Embeds & Interactive Views package."""

from src.rpg.ui.embeds_core import (
    build_bag_embed,
    build_error_embed,
    build_help_embed,
    build_leaderboard_embed,
    build_monument_embed,
    build_profile_embed,
    build_skills_embed,
    build_start_embed,
    build_yui_embed,
)
from src.rpg.ui.embeds_party import (
    build_coop_raid_embed,
    build_duel_embed,
    build_party_lobby_embed,
    build_world_boss_embed,
)
from src.rpg.ui.embeds_social import (
    build_cooking_embed,
    build_guild_embed,
    build_market_embed,
    build_quests_embed,
    build_shop_embed,
    build_workshop_embed,
)
from src.rpg.ui.embeds_tower import (
    build_argo_intel_embed,
    build_combat_embed,
    build_roguelike_embed,
    build_secret_realm_embed,
    build_tower_embed,
)
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
    PostCombatView,
    RoguelikeView,
    SecretRealmView,
    SoloCombatView,
    TowerFloorView,
)

__all__ = [
    "BagEquipView",
    "ChestView",
    "CoopRaidView",
    "DailyQuestView",
    "DuelView",
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
    "TowerFloorView",
    "WorkshopView",
    "WorldBossView",
    "build_argo_intel_embed",
    "build_bag_embed",
    "build_combat_embed",
    "build_cooking_embed",
    "build_coop_raid_embed",
    "build_duel_embed",
    "build_error_embed",
    "build_guild_embed",
    "build_help_embed",
    "build_leaderboard_embed",
    "build_market_embed",
    "build_monument_embed",
    "build_party_lobby_embed",
    "build_profile_embed",
    "build_quests_embed",
    "build_roguelike_embed",
    "build_secret_realm_embed",
    "build_shop_embed",
    "build_skills_embed",
    "build_start_embed",
    "build_tower_embed",
    "build_workshop_embed",
    "build_world_boss_embed",
    "build_yui_embed",
]
