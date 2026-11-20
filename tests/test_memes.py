"""Unit tests for the `/p` anime meme command and free online meme database client."""

from __future__ import annotations

import asyncio
import random
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import discord
import pytest

import bot as bot_module
from src.memes import (
    FALLBACK_MEMES,
    MEME_SOURCES,
    AnimeMemeService,
    AnimeMemeView,
    MemeEntry,
    MemeSourceSpec,
    build_meme_embed,
    normalize_search_text,
)
from src.memes.catalog import parse_source_payload


def _is_valid_meme_url(url: str) -> bool:
    return url.startswith("https://") and url.split("?", 1)[0].lower().endswith(
        (".png", ".jpg", ".jpeg", ".gif", ".webp")
    )


def test_p_slash_command_registered_with_choices() -> None:
    cmd = bot_module.bot.tree.get_command("p")
    assert cmd is not None
    payload = cmd.to_dict(bot_module.bot.tree)
    assert payload["name"] == "p"
    assert payload["type"] == 1

    cat_param = cmd.get_parameter("category")
    kw_param = cmd.get_parameter("keyword")
    assert cat_param is not None and not cat_param.required
    assert kw_param is not None and not kw_param.required

    choice_values = {c.value for c in cat_param.choices}
    assert choice_values == {"all", "acg_mix", "anime_classic", "deepseek", "gif"}


def test_fallback_memes_and_source_specs_format() -> None:
    assert len(MEME_SOURCES) >= 8
    for spec in MEME_SOURCES:
        assert spec.index_url.startswith("https://raw.githubusercontent.com/")
        assert spec.theme in {"acg_mix", "anime_classic", "deepseek"}

    assert len(FALLBACK_MEMES) >= 15
    themes_present = set()
    gifs_present = False
    for meme in FALLBACK_MEMES:
        assert _is_valid_meme_url(meme.url), f"Invalid fallback URL: {meme.url}"
        assert meme.title
        assert meme.source_name
        themes_present.add(meme.theme)
        if meme.is_gif:
            gifs_present = True
    assert themes_present == {"acg_mix", "anime_classic", "deepseek"}
    assert gifs_present is True


def test_trad_to_simp_normalization_matches_anime_terms() -> None:
    cases = [
        ("芙莉蓮", "芙莉莲"),
        ("大肥魚", "大肥鱼"),
        ("貓娘", "猫娘"),
        ("生氣", "生气"),
        ("吃飯", "吃饭"),
        ("鯨魚娘", "鲸鱼娘"),
        ("輝夜大小姐", "辉夜大小姐"),
        ("間諜過家家", "间谍过家家"),
        ("電鋸人", "电锯人"),
        ("鬼滅之刃", "鬼灭之刃"),
        ("進擊的巨人", "进击的巨人"),
        ("阿庫婭", "阿库娅"),
        ("可愛蘿莉", "可爱萝莉"),
        ("擺爛", "摆烂"),
        ("問號", "问号"),
        ("摸魚", "摸鱼"),
        ("最強", "最强"),
        ("女僕", "女仆"),
    ]
    for trad, simp in cases:
        assert normalize_search_text(trad) == simp


def test_parsers_handle_all_five_online_schemas_and_sfw_filtering() -> None:
    # 1. semantic_metadata parser (excludes `color` and NSFW keywords)
    sem_spec = MemeSourceSpec("s1", "綜合圖庫", "owner/sem", "v1.0.0", "semantic_metadata.json", "semantic_metadata", "acg_mix")
    sem_data = {
        "images": {
            "ok1": {
                "relative_path": "memes/angry/catgirl.jpg",
                "category": "angry",
                "visible_text": "你骂谁二次元呢",
                "caption": "猫娘生气",
                "tags": ["猫娘", "生气"],
                "content_sha256": "hash-1",
            },
            "blocked_cat": {
                "relative_path": "memes/color/spicy.jpg",
                "category": "color",
                "visible_text": "色气图",
                "caption": "色情内容",
            },
            "blocked_kw": {
                "relative_path": "memes/angry/bad.jpg",
                "category": "angry",
                "visible_text": "电你牛子",
                "caption": "不雅内容",
            },
        }
    }
    sem_entries = parse_source_payload(sem_data, sem_spec)
    assert len(sem_entries) == 1
    assert sem_entries[0].title == "你骂谁二次元呢"
    assert sem_entries[0].url == "https://raw.githubusercontent.com/owner/sem/v1.0.0/memes/angry/catgirl.jpg"
    assert "猫娘" in sem_entries[0].search_text

    # 2. source_index parser (both `path` and `category + filename`, percent-encoding spaces/CJK)
    src_spec = MemeSourceSpec("s2", "大肥魚動圖", "owner/bff", "v1.0.0", "source_index.json", "source_index", "deepseek")
    src_data = {
        "images": [
            {"category": "affection", "filename": "0001_爱心 1.gif", "path": "memes/affection/0001_爱心 1.gif", "sha256": "h2"},
            {"category": "happy", "filename": "0002_sticker_issue_13_001.png"},
        ]
    }
    src_entries = parse_source_payload(src_data, src_spec)
    assert len(src_entries) == 2
    assert src_entries[0].is_gif is True
    assert "%E7%88%B1%E5%BF%83%201.gif" in src_entries[0].url
    assert src_entries[0].title == "爱心 1"
    # Technical sticker_issue filename cleanly falls back to source name
    assert src_entries[1].title == "大肥魚動圖"
    assert src_entries[1].url.endswith("/memes/happy/0002_sticker_issue_13_001.png")

    # 3. chinesebqb_anime parser (keeps anime folders, drops non-anime folders)
    cb_spec = MemeSourceSpec("s3", "ChineseBQB", "DumKing/ChineseBQB-AstrBot", "v1.1.0", "source_index.json", "chinesebqb_anime", "anime_classic")
    cb_data = {
        "images": [
            {"upstream_path": "095GenShin_原神_BQB/原神00001-态度极其嚣张.jpg", "relative_path": "memes/teasing/abc.jpg", "sha256": "h3"},
            {"upstream_path": "106_Frieren_芙莉莲🪄_BQB/芙莉莲00001-赶快给我交往啊.gif", "relative_path": "memes/angry/def.gif", "sha256": "h4"},
            {"upstream_path": "064Trump_特朗普BQB/trump001.jpg", "relative_path": "memes/teasing/ghi.jpg", "sha256": "h5"},
        ]
    }
    cb_entries = parse_source_payload(cb_data, cb_spec)
    assert len(cb_entries) == 2
    assert cb_entries[0].source_name == "ChineseBQB · 原神"
    assert cb_entries[0].title == "态度极其嚣张"
    assert cb_entries[1].source_name == "ChineseBQB · 芙莉蓮"
    assert cb_entries[1].is_gif is True

    # 4. blue_fish_archive parser (rewrites fisharchive.cc -> raw.githubusercontent.com)
    bfa_spec = MemeSourceSpec("s4", "藍色大肥魚檔案館", "EDMOK/blue-fish-archive", "main", "stickers/index.json", "blue_fish_archive", "deepseek")
    bfa_data = {
        "stickers": [
            {
                "alt": "deepseek娘抱碗开吃：饭呢？",
                "tags": ["吃饭", "搞笑"],
                "original": "https://fisharchive.cc/media/ds-eat.png",
            }
        ]
    }
    bfa_entries = parse_source_payload(bfa_data, bfa_spec)
    assert len(bfa_entries) == 1
    assert bfa_entries[0].url == "https://raw.githubusercontent.com/EDMOK/blue-fish-archive/main/media/ds-eat.png"
    assert "吃饭" in bfa_entries[0].search_text

    # 5. dsh_stickers parser (only keeps raw.githubusercontent.com URLs)
    dsh_spec = MemeSourceSpec("s5", "DSH圖庫", "yyh-001/dsh-meme-packs", "main", "stickers.json", "dsh_stickers", "deepseek")
    dsh_data = {
        "stickers": [
            {
                "name": "免死鲸牌",
                "text": "免死鲸牌放你一马",
                "tag": "angry",
                "keywords": ["鲸鱼娘", "免死"],
                "imageUrl": "https://raw.githubusercontent.com/yyh-001/dsh-meme-packs/main/previews/test/a.jpg",
            },
            {
                "name": "外部連結應略過",
                "text": "skip",
                "tag": "daily",
                "imageUrl": "https://third-party.example.com/001.webp",
            },
        ]
    }
    dsh_entries = parse_source_payload(dsh_data, dsh_spec)
    assert len(dsh_entries) == 1
    assert dsh_entries[0].title == "免死鲸牌放你一马"


def test_service_dedup_search_antirepeat_and_fallback() -> None:
    svc = AnimeMemeService(sources=(), rng=random.Random(42))

    # Empty sources refresh falls back gracefully to FALLBACK_MEMES
    loaded = asyncio.run(svc.refresh())
    assert loaded == len(FALLBACK_MEMES)
    assert svc.using_fallback is True

    # Traditional Chinese keyword search matches Simplified/Traditional captions
    meme_frieren, mcnt, total = svc.pick_random(keyword="芙莉蓮", history_key="ch1")
    assert meme_frieren is not None
    assert mcnt >= 1
    assert total == len(FALLBACK_MEMES)
    assert "芙莉蓮" in meme_frieren.source_name

    # GIF filter returns only .gif memes
    meme_gif, gif_cnt, _ = svc.pick_random(category="gif", history_key="ch1")
    assert meme_gif is not None and meme_gif.is_gif is True
    assert gif_cnt >= 2

    # Nonexistent keyword returns None cleanly
    missing, zero, _ = svc.pick_random(keyword="絕對找不到的冷門詞xyz999", history_key="ch1")
    assert missing is None and zero == 0

    # Deduplication by URL & sha256 + anti-repeat window across consecutive draws
    e1 = MemeEntry("https://raw.githubusercontent.com/a/b/main/1.png", "圖一", "src", "a/b", "acg_mix", False, "图一", "dup-hash")
    e1_dup = MemeEntry("https://raw.githubusercontent.com/a/b/main/1_copy.png", "圖一重複", "src", "a/b", "acg_mix", False, "图一", "dup-hash")
    e2 = MemeEntry("https://raw.githubusercontent.com/a/b/main/2.png", "圖二", "src", "a/b", "acg_mix", False, "图二", "hash-2")
    svc._set_pool([e1, e1_dup, e2], using_fallback=False, online_sources=1)
    assert svc.total_count == 2

    pick1, _, _ = svc.pick_random(category="acg_mix", history_key="chan_x")
    pick2, _, _ = svc.pick_random(category="acg_mix", history_key="chan_x")
    assert pick1 is not None and pick2 is not None
    assert pick1.url != pick2.url


def test_meme_embed_view_and_slash_command_execution() -> None:
    svc = AnimeMemeService(sources=(), rng=random.Random(7))
    svc._set_pool(FALLBACK_MEMES, using_fallback=False, online_sources=10)

    sample = FALLBACK_MEMES[0]
    embed = build_meme_embed(sample, total_count=3043, match_count=3043, category="all")
    d = embed.to_dict()
    assert d["title"].startswith("🎭 ")
    assert d["image"]["url"] == sample.url
    assert "3,043" in d["footer"]["text"]

    async def _exercise_view_and_command() -> None:
        view = AnimeMemeView(svc, invoker_id=1001, category="all", meme_url=sample.url)
        assert len(view.children) == 3
        link_buttons = [c for c in view.children if isinstance(c, discord.ui.Button) and c.style == discord.ButtonStyle.link]
        assert len(link_buttons) == 1 and link_buttons[0].url == sample.url
        view.stop()

        # Execute `/p` slash command callback directly with mocked Interaction
        from src.memes.commands import create_meme_commands

        p_cmd = create_meme_commands(svc)[0]
        sent: List[Dict[str, Any]] = []

        async def fake_send(*args: Any, **kwargs: Any) -> None:
            sent.append(kwargs)

        interaction = SimpleNamespace(
            user=SimpleNamespace(id=1001, display_name="Tester"),
            channel_id=555,
            response=SimpleNamespace(send_message=AsyncMock(side_effect=fake_send), defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock(side_effect=fake_send)),
        )

        # Warm cache -> instant response (no defer needed)
        await p_cmd.callback(interaction, category="deepseek", keyword="吃飯")
        assert interaction.response.defer.await_count == 0
        assert len(sent) == 1
        assert isinstance(sent[0]["embed"], discord.Embed)
        assert _is_valid_meme_url(sent[0]["embed"].image.url)
        sent[0]["view"].stop()

        # Keyword miss -> friendly ephemeral reply
        sent.clear()
        await p_cmd.callback(interaction, category="all", keyword="完全不存在的關鍵字zzz")
        assert len(sent) == 1
        assert sent[0].get("ephemeral") is True

        # Cold-start service -> defers first, loads fallback, sends via followup
        cold_svc = AnimeMemeService(sources=(), rng=random.Random(9))
        cold_cmd = create_meme_commands(cold_svc)[0]
        sent.clear()
        interaction2 = SimpleNamespace(
            user=SimpleNamespace(id=2002, display_name="ColdTester"),
            channel_id=777,
            response=SimpleNamespace(send_message=AsyncMock(side_effect=fake_send), defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock(side_effect=fake_send)),
        )
        await cold_cmd.callback(interaction2, category="all", keyword=None)
        assert interaction2.response.defer.await_count == 1
        assert interaction2.followup.send.await_count == 1
        assert len(sent) == 1
        sent[0]["view"].stop()

    asyncio.run(_exercise_view_and_command())
