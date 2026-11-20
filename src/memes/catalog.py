"""Online free open-source Chinese anime meme databases (zero API key required).

Connects to curated community GitHub meme repositories via ``raw.githubusercontent.com``
(no GitHub REST API rate limit, no API key, completely free), caches the unified index
in memory with stale-while-revalidate refresh, applies SFW filtering and deduplication,
and falls back gracefully to a built-in pool of verified URLs if offline.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import json
import logging
import random
import re
import time
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote

import aiohttp

logger = logging.getLogger("rpg-dc-bot")

VALID_IMAGE_EXTS: Tuple[str, ...] = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# Categories excluded to keep random memes SFW and appropriate for all Discord servers.
BLOCKED_CATEGORIES = frozenset({"color", "nsfw", "r18", "adult", "sexy", "needs_review"})

# Explicit adult/profane phrases excluded from public random draws.
BLOCKED_KEYWORDS: Tuple[str, ...] = (
    "色情",
    "涩图",
    "澀圖",
    "射爆",
    "裸体",
    "裸體",
    "露骨",
    "黄梗",
    "黃梗",
    "r18",
    "nsfw",
    "牛子",
    "他妈",
    "他媽",
)

# Balanced theme weights used when category == "all" and no keyword is specified.
THEME_WEIGHTS: Dict[str, float] = {
    "acg_mix": 0.35,
    "anime_classic": 0.35,
    "deepseek": 0.30,
}

THEME_LABELS: Dict[str, str] = {
    "all": "🎲 隨機全部",
    "acg_mix": "🎀 二次元綜合梗圖",
    "anime_classic": "✨ 經典動漫梗圖",
    "deepseek": "🐋 藍色大肥魚／DeepSeek娘",
    "gif": "🎞️ 二次元動態 GIF",
}

THEME_COLORS: Dict[str, int] = {
    "acg_mix": 0xFF6B9D,
    "anime_classic": 0x9B59B6,
    "deepseek": 0x3498DB,
    "gif": 0x1ABC9C,
}

# Pure anime/ACG folders inside zhaoolee/ChineseBQB (mirrored & cleaned in DumKing/ChineseBQB-AstrBot).
CHINESEBQB_ANIME_FOLDERS: Dict[str, str] = {
    "068Aqua": "阿庫婭",
    "070JOJO": "JOJO 的奇妙冒險",
    "071辉夜大小姐": "輝夜大小姐",
    "075Vtuber": "VTuber",
    "076Moe": "可愛蘿莉",
    "078BeiFang": "北方栖姬",
    "080GuiMie": "鬼滅之刃",
    "082AttackOnTitan": "進擊的巨人",
    "090SailorMoon": "美少女戰士",
    "095GenShin": "原神",
    "098spyxfamily": "間諜過家家",
    "101ChainsawMan": "電鋸人",
    "106_Frieren": "芙莉蓮",
}

# Semantic emotion tags mapped to friendly Traditional/Simplified search terms.
CATEGORY_KEYWORDS: Dict[str, str] = {
    "angry": "生氣 愤怒 怒 氣 罵 抗議",
    "baka": "笨蛋 吐槽 傻 呆",
    "confused": "疑惑 問號 困惑 不懂 啥",
    "cpu": "當機 卡頓 燒腦 思考 加載",
    "daily": "日常 摸魚 聊天",
    "food": "吃飯 乾飯 白飯 食物 餓 投餵",
    "fool": "裝傻 搞笑 賣傻 沙雕",
    "givemoney": "要錢 給錢 爆金幣 發財",
    "greeting": "打招呼 你好 早安 哈囉",
    "happy": "開心 笑 高興 得意 好耶 快樂",
    "like": "喜歡 愛心 貼貼 誇讚 讚",
    "affection": "喜歡 愛心 貼貼 誇讚 可愛",
    "meow": "賣萌 貓娘 喵 可愛",
    "money": "錢 token 漲價 省錢 窮",
    "morning": "早安 起床 早上好",
    "portrait": "立繪 角色",
    "reply": "回覆 收到 確認",
    "sad": "難過 哭 委屈 崩潰 累 悲傷",
    "see": "暗中觀察 偷看 盯 吃瓜",
    "shy": "害羞 臉紅 傲嬌",
    "sigh": "無語 嘆氣 擺爛 算了",
    "sleep": "睡覺 犯困 躺平 擺爛 晚安 摸魚",
    "surprised": "震驚 驚訝 嚇到",
    "teasing": "嘲諷 囂張 得意 挑釁 壞笑",
    "tech": "程式 代碼 AI 模型 思考",
    "work": "上班 下班 加班 摸魚 工作 班味",
    "apology": "道歉 對不起 錯了 投降",
    "approval": "贊同 覺得很讚 沒錯 好",
    "thinking": "思考 想一想 思索",
}

# Pair-safe Traditional -> Simplified mapping so Traditional Chinese searches
# match Simplified Chinese captions/tags from upstream databases without extra dependencies.
_TRAD_SIMP_PAIRS: Tuple[str, ...] = (
    "愛爱", "罷罢", "擺摆", "辦办", "幫帮", "寶宝", "報报", "備备", "貝贝", "變变",
    "標标", "錶表", "別别", "彆别", "餅饼", "補补", "參参", "倉仓", "產产", "長长",
    "場场", "廠厂", "車车", "陳陈", "稱称", "誠诚", "遲迟", "衝冲", "蟲虫", "寵宠",
    "醜丑", "觸触", "處处", "傳传", "創创", "詞词", "從从", "叢丛", "錯错", "達达",
    "帶带", "單单", "當当", "檔档", "黨党", "導导", "點点", "電电", "癲癫", "諜谍",
    "東东", "動动", "鬥斗", "獨独", "讀读", "對对", "隊队", "奪夺", "餓饿", "兒儿",
    "發发", "髮发", "罰罚", "飯饭", "飛飞", "廢废", "費费", "風风", "瘋疯", "豐丰",
    "鳳凤", "負负", "復复", "該该", "乾干", "幹干", "剛刚", "綱纲", "鋼钢", "個个",
    "給给", "夠够", "構构", "購购", "觀观", "關关", "館馆", "廣广", "歸归", "龜龟",
    "國国", "過过", "還还", "漢汉", "號号", "鶴鹤", "紅红", "後后", "護护", "畫画",
    "華华", "話话", "懷怀", "壞坏", "歡欢", "環环", "換换", "黃黄", "輝辉", "會会",
    "繪绘", "渾浑", "擊击", "積积", "極极", "機机", "雞鸡", "幾几", "際际", "記记",
    "繼继", "夾夹", "價价", "駕驾", "間间", "簡简", "見见", "將将", "獎奖", "講讲",
    "膠胶", "覺觉", "節节", "結结", "潔洁", "進进", "驚惊", "經经", "靜静", "鏡镜",
    "淨净", "競竞", "舊旧", "舉举", "劇剧", "據据", "開开", "顆颗", "課课", "殼壳",
    "塊块", "誇夸", "寬宽", "礦矿", "虧亏", "庫库", "來来", "藍蓝", "攔拦", "懶懒",
    "爛烂", "勞劳", "樂乐", "類类", "離离", "禮礼", "裡里", "裏里", "歷历", "麗丽",
    "連连", "臉脸", "練练", "涼凉", "兩两", "輛辆", "療疗", "蓮莲", "鈴铃", "靈灵",
    "龍龙", "樓楼", "錄录", "陸陆", "亂乱", "論论", "蘿萝", "媽妈", "瑪玛", "嗎吗",
    "罵骂", "買买", "賣卖", "滿满", "貓猫", "麼么", "沒没", "門门", "們们", "夢梦",
    "彌弥", "麵面", "滅灭", "銘铭", "鳴鸣", "難难", "腦脑", "內内", "擬拟", "膩腻",
    "鳥鸟", "寧宁", "農农", "濃浓", "歐欧", "盤盘", "龐庞", "噴喷", "鵬鹏", "騙骗",
    "評评", "憑凭", "撲扑", "僕仆", "齊齐", "氣气", "棄弃", "簽签", "錢钱", "淺浅",
    "槍枪", "強强", "牆墙", "搶抢", "橋桥", "喬乔", "親亲", "輕轻", "傾倾", "請请",
    "慶庆", "窮穷", "區区", "驅驱", "趨趋", "權权", "勸劝", "確确", "讓让", "熱热",
    "認认", "榮荣", "軟软", "銳锐", "賽赛", "殺杀", "紗纱", "傷伤", "賞赏", "燒烧",
    "設设", "誰谁", "審审", "勝胜", "師师", "詩诗", "實实", "時时", "識识", "勢势",
    "試试", "視视", "適适", "釋释", "飾饰", "壽寿", "書书", "輸输", "術术", "樹树",
    "數数", "帥帅", "雙双", "稅税", "順顺", "說说", "絲丝", "訴诉", "蘇苏", "肅肃",
    "雖虽", "歲岁", "孫孙", "損损", "縮缩", "鎖锁", "臺台", "態态", "壇坛", "嘆叹",
    "湯汤", "討讨", "騰腾", "題题", "體体", "條条", "貼贴", "聽听", "鐵铁", "廳厅",
    "頭头", "圖图", "塗涂", "團团", "脫脱", "襪袜", "萬万", "網网", "衛卫", "為为",
    "偽伪", "圍围", "維维", "偉伟", "溫温", "聞闻", "問问", "窩窝", "臥卧", "烏乌",
    "無无", "吳吴", "誤误", "戲戏", "細细", "蝦虾", "嚇吓", "險险", "現现", "獻献",
    "鄉乡", "響响", "項项", "蕭萧", "銷销", "曉晓", "寫写", "謝谢", "興兴", "學学",
    "尋寻", "訊讯", "壓压", "鴉鸦", "亞亚", "婭娅", "嚴严", "顏颜", "驗验", "厭厌",
    "揚扬", "陽阳", "養养", "樣样", "藥药", "爺爷", "頁页", "業业", "葉叶", "醫医",
    "儀仪", "遺遗", "義义", "議议", "藝艺", "譯译", "異异", "陰阴", "銀银", "飲饮",
    "隱隐", "應应", "營营", "贏赢", "擁拥", "優优", "憂忧", "郵邮", "猶犹", "遊游",
    "魚鱼", "娛娱", "與与", "語语", "獄狱", "預预", "員员", "圓圆", "園园", "願愿",
    "約约", "雲云", "運运", "雜杂", "災灾", "載载", "暫暂", "讚赞", "髒脏", "臟脏",
    "責责", "擇择", "則则", "贈赠", "戰战", "張张", "漲涨", "帳帐", "這这", "針针",
    "偵侦", "診诊", "陣阵", "鎮镇", "爭争", "睜睁", "證证", "織织", "職职", "執执",
    "紙纸", "製制", "質质", "鐘钟", "種种", "終终", "眾众", "週周", "豬猪", "諸诸",
    "築筑", "裝装", "壯壮", "狀状", "準准", "著着", "總总", "縱纵", "組组", "鑽钻",
    "鋸锯", "鷹鹰", "螢萤", "熒荧", "囂嚣", "鯨鲸", "嗚呜", "淚泪", "惱恼", "捲卷",
    "僅仅", "卻却", "絕绝", "聖圣", "俠侠", "劍剑", "輩辈", "嬌娇", "禦御", "廚厨",
    "綠绿", "銅铜", "淵渊", "峽峡", "嶺岭", "島岛", "灣湾", "粵粤", "註注", "詳详",
    "頻频", "敗败", "癒愈", "紋纹", "鎧铠", "褲裤", "領领", "鏈链", "墜坠", "鋒锋",
    "錘锤", "鐮镰", "傘伞", "燈灯", "燭烛", "爐炉", "鍋锅", "壺壶", "紙纸", "筆笔",
    "硯砚", "軸轴", "冊册", "籤签", "鈔钞", "櫃柜", "籃篮", "籠笼", "繩绳", "鑰钥",
    "錦锦", "繡绣", "綢绸", "緞缎", "綿绵", "絨绒", "鱗鳞", "齒齿", "鬚须", "鬢鬓",
    "頰颊", "顎颚", "脈脉", "絡络", "腸肠", "膽胆", "腎肾", "軀躯", "鍵键", "盤盘",
)
_TRAD_TO_SIMP = str.maketrans({pair[0]: pair[1] for pair in _TRAD_SIMP_PAIRS if len(pair) == 2})

_FILENAME_HASH_RE = re.compile(r"^[0-9a-fA-F_\-]{12,}$")
_TECHNICAL_STEM_RE = re.compile(
    r"^(?:sticker|file|img|image|meme|photo|pic|agad)[_\-a-z0-9]*$",
    re.IGNORECASE,
)


def normalize_search_text(text: str) -> str:
    """Normalize text for case-insensitive Traditional/Simplified Chinese matching."""
    return text.strip().lower().translate(_TRAD_TO_SIMP)


def _is_valid_image_url(url: str) -> bool:
    if not url or not url.startswith("https://"):
        return False
    base = url.split("?", 1)[0].lower()
    return base.endswith(VALID_IMAGE_EXTS)


def _is_sfw(category: str, text: str) -> bool:
    if category.strip().lower() in BLOCKED_CATEGORIES:
        return False
    norm = normalize_search_text(text)
    return not any(bad in norm for bad in BLOCKED_KEYWORDS)


def _raw_github_url(repo: str, ref: str, rel_path: str) -> str:
    cleaned = rel_path.lstrip("/")
    return f"https://raw.githubusercontent.com/{repo}/{ref}/{quote(cleaned, safe='/')}"


def _clean_title(raw: str, fallback: str) -> str:
    text = " ".join((raw or "").replace("\r", " ").replace("\n", " ").split()).strip()
    if not text:
        return fallback
    # Strip verbose auto-generated semantic prefixes from semantic_metadata descriptions.
    if text.startswith("以当前分类"):
        return fallback
    if len(text) > 72:
        text = text[:71].rstrip() + "…"
    return text


def _filename_to_title(filename: str, fallback: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0].strip()
    # Drop numeric prefix like "0004_" or "原神00001-"
    if "-" in stem:
        right = stem.split("-", 1)[1].strip()
        if right:
            return _clean_title(right, fallback)
    if "_" in stem:
        parts = stem.split("_", 1)
        if parts[0].isdigit() and parts[1]:
            stem = parts[1].strip()
    if (
        not stem
        or stem.isdigit()
        or _FILENAME_HASH_RE.match(stem)
        or _TECHNICAL_STEM_RE.match(stem)
    ):
        return fallback
    return _clean_title(stem, fallback)


@dataclass(frozen=True)
class MemeEntry:
    """Single anime meme image record."""

    url: str
    title: str
    source_name: str
    source_repo: str
    theme: str  # "acg_mix" | "anime_classic" | "deepseek"
    is_gif: bool
    search_text: str
    content_hash: str = ""


@dataclass(frozen=True)
class MemeSourceSpec:
    """Declarative descriptor for a free online GitHub-hosted meme JSON index."""

    source_id: str
    name: str
    repo: str
    ref: str
    index_path: str
    parser_kind: str  # "semantic_metadata" | "source_index" | "chinesebqb_anime" | "blue_fish_archive" | "dsh_stickers"
    theme: str

    @property
    def index_url(self) -> str:
        return _raw_github_url(self.repo, self.ref, self.index_path)


# 10 curated, free, zero-API-key open-source Chinese anime meme databases on GitHub.
MEME_SOURCES: Tuple[MemeSourceSpec, ...] = (
    MemeSourceSpec(
        source_id="astrbot-semantic-01",
        name="二次元綜合梗圖庫",
        repo="DDZS987/astrbot-meme-pack-semantic-01",
        ref="v1.1.0",
        index_path="semantic_metadata.json",
        parser_kind="semantic_metadata",
        theme="acg_mix",
    ),
    MemeSourceSpec(
        source_id="izumi-hiyori",
        name="和泉妃愛二次元梗圖",
        repo="NooAcc/astrbot-meme-IzumiHiyori",
        ref="v1.0.2",
        index_path="semantic_metadata.json",
        parser_kind="semantic_metadata",
        theme="acg_mix",
    ),
    MemeSourceSpec(
        source_id="juxueli",
        name="橘雪莉表情包",
        repo="anka-afk/juxueli-meme-pack",
        ref="v1.0.0",
        index_path="source_index.json",
        parser_kind="source_index",
        theme="acg_mix",
    ),
    MemeSourceSpec(
        source_id="congyu",
        name="叢雨二次元表情包",
        repo="anka-afk/congyu-meme-pack",
        ref="v1.0.0",
        index_path="source_index.json",
        parser_kind="source_index",
        theme="acg_mix",
    ),
    MemeSourceSpec(
        source_id="clover-days",
        name="鷹倉杏鈴萌系表情包",
        repo="anka-afk/clover-days-meme-pack",
        ref="v1.0.0",
        index_path="source_index.json",
        parser_kind="source_index",
        theme="acg_mix",
    ),
    MemeSourceSpec(
        source_id="chinesebqb-anime",
        name="ChineseBQB 經典動漫梗圖",
        repo="DumKing/ChineseBQB-AstrBot",
        ref="v1.1.0",
        index_path="source_index.json",
        parser_kind="chinesebqb_anime",
        theme="anime_classic",
    ),
    MemeSourceSpec(
        source_id="blue-fish-archive",
        name="藍色大肥魚檔案館",
        repo="EDMOK/blue-fish-archive",
        ref="main",
        index_path="stickers/index.json",
        parser_kind="blue_fish_archive",
        theme="deepseek",
    ),
    MemeSourceSpec(
        source_id="deepseek-fanart",
        name="DeepSeek娘 二創梗圖",
        repo="anka-afk/deepseek-fanart-meme-pack",
        ref="v1.0.0",
        index_path="source_index.json",
        parser_kind="source_index",
        theme="deepseek",
    ),
    MemeSourceSpec(
        source_id="blue-fat-fish-gif",
        name="藍色大肥魚動態表情包",
        repo="anka-afk/blue-fat-fish-meme-pack",
        ref="v1.0.0",
        index_path="source_index.json",
        parser_kind="source_index",
        theme="deepseek",
    ),
    MemeSourceSpec(
        source_id="dsh-meme-packs",
        name="DSH 二次元表情包圖庫",
        repo="yyh-001/dsh-meme-packs",
        ref="main",
        index_path="stickers.json",
        parser_kind="dsh_stickers",
        theme="deepseek",
    ),
)


def _make_fallback(
    url: str,
    title: str,
    source_name: str,
    source_repo: str,
    theme: str,
    extra_keywords: str = "",
) -> MemeEntry:
    is_gif = url.lower().endswith(".gif")
    search_blob = normalize_search_text(f"{title} {source_name} {theme} {extra_keywords}")
    return MemeEntry(
        url=url,
        title=title,
        source_name=source_name,
        source_repo=source_repo,
        theme=theme,
        is_gif=is_gif,
        search_text=search_blob,
    )


# Verified, 100% live SFW fallback memes used only if all remote JSON index fetches fail.
FALLBACK_MEMES: Tuple[MemeEntry, ...] = (
    _make_fallback(
        "https://raw.githubusercontent.com/DDZS987/astrbot-meme-pack-semantic-01/v1.1.0/memes/angry/0FFD1AFA5CD0866B1065AEAF45D4066A.jpg",
        "小筆載治，別讓我逮到你",
        "二次元綜合梗圖庫",
        "DDZS987/astrbot-meme-pack-semantic-01",
        "acg_mix",
        "貓娘 柴郡 生氣 警告",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/DDZS987/astrbot-meme-pack-semantic-01/v1.1.0/memes/angry/1739433869_1.jpg",
        "怎麼辦？只有殺",
        "二次元綜合梗圖庫",
        "DDZS987/astrbot-meme-pack-semantic-01",
        "acg_mix",
        "生氣 無奈 決絕",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/DDZS987/astrbot-meme-pack-semantic-01/v1.1.0/memes/angry/1739434222_1.jpg",
        "幹什麼！",
        "二次元綜合梗圖庫",
        "DDZS987/astrbot-meme-pack-semantic-01",
        "acg_mix",
        "生氣 吐槽",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/NooAcc/astrbot-meme-IzumiHiyori/v1.0.2/memes/like/AgADjhQAAglkwFQ.png",
        "我喜歡你，你是世上最好的人",
        "和泉妃愛二次元梗圖",
        "NooAcc/astrbot-meme-IzumiHiyori",
        "acg_mix",
        "喜歡 誇獎 貼貼 和泉妃愛",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/NooAcc/astrbot-meme-IzumiHiyori/v1.0.2/memes/sleep/AgAD7AEAAsGyKEc.png",
        "遇到困難擺大爛",
        "和泉妃愛二次元梗圖",
        "NooAcc/astrbot-meme-IzumiHiyori",
        "acg_mix",
        "擺爛 躺平 睡覺 和泉妃愛",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/NooAcc/astrbot-meme-IzumiHiyori/v1.0.2/memes/fool/AgADkRYAAvGBsFY.png",
        "肉包，兄弟",
        "和泉妃愛二次元梗圖",
        "NooAcc/astrbot-meme-IzumiHiyori",
        "acg_mix",
        "吃飯 搞笑 賣傻 和泉妃愛",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/DumKing/ChineseBQB-AstrBot/v1.1.0/memes/teasing/c911309d5f0ddcad2b748e4c0b72df7bb10edfba8f10992d4e052c4992893be0.jpg",
        "態度極其囂張",
        "ChineseBQB · 原神",
        "DumKing/ChineseBQB-AstrBot",
        "anime_classic",
        "原神 熒 囂張 得意",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/DumKing/ChineseBQB-AstrBot/v1.1.0/memes/angry/385d23fd9c7eac5ea1fed03d605cb7b9f33bc075012943e951f2c8c8f167fc40.gif",
        "趕快給我交往啊",
        "ChineseBQB · 芙莉蓮",
        "DumKing/ChineseBQB-AstrBot",
        "anime_classic",
        "芙莉蓮 葬送的芙莉蓮 催婚 動圖",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/DumKing/ChineseBQB-AstrBot/v1.1.0/memes/like/929b60066b4d2ff6c9110c0ebc995212bcad262a950addbd98613eede90ae59d.jpg",
        "那個世界居然有如此美麗的人",
        "ChineseBQB · 北方栖姬",
        "DumKing/ChineseBQB-AstrBot",
        "anime_classic",
        "北方栖姬 艦娘 誇獎",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/DumKing/ChineseBQB-AstrBot/v1.1.0/memes/sad/5bedf9786f57a71461bf1361f21e6b6a7eb540db47898bda435573f02d840e5e.png",
        "我可是女神啊",
        "ChineseBQB · 阿庫婭",
        "DumKing/ChineseBQB-AstrBot",
        "anime_classic",
        "阿庫婭 智障女神 委屈",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/DumKing/ChineseBQB-AstrBot/v1.1.0/memes/approval/54bfbcc16d8e88a770cc8c78f45096ec3814579136c82f8a314f1e4e25e5b015.jpg",
        "吉良吉影覺得很讚",
        "ChineseBQB · JOJO 的奇妙冒險",
        "DumKing/ChineseBQB-AstrBot",
        "anime_classic",
        "jojo 很讚 認同",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/DumKing/ChineseBQB-AstrBot/v1.1.0/memes/teasing/1298e0a5c5d18bf4d725222bba3b02b737d9c8c24458791f3951dd84d59bf0a1.jpg",
        "我是你媽殺人如麻",
        "ChineseBQB · 間諜過家家",
        "DumKing/ChineseBQB-AstrBot",
        "anime_classic",
        "間諜過家家 約兒 霸氣",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/anka-afk/deepseek-fanart-meme-pack/v1.0.0/memes/food/0017_sticker_bf_022.png",
        "你罵我也沒用，因為我是吃白飯的藍色大肥魚",
        "DeepSeek娘 二創梗圖",
        "anka-afk/deepseek-fanart-meme-pack",
        "deepseek",
        "deepseek 大肥魚 吃白飯 鯨魚娘 摸魚",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/anka-afk/deepseek-fanart-meme-pack/v1.0.0/memes/food/0031_sticker_bf_043.webp",
        "我能去你家吃飯嗎，就一碗！",
        "DeepSeek娘 二創梗圖",
        "anka-afk/deepseek-fanart-meme-pack",
        "deepseek",
        "deepseek 大肥魚 吃飯 蹭飯 鯨魚娘",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/anka-afk/deepseek-fanart-meme-pack/v1.0.0/memes/angry/0004_sticker_bf_006.webp",
        "用戶徹底怒了",
        "DeepSeek娘 二創梗圖",
        "anka-afk/deepseek-fanart-meme-pack",
        "deepseek",
        "deepseek 大肥魚 生氣 鯨魚娘",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/anka-afk/deepseek-fanart-meme-pack/v1.0.0/memes/happy/0008_sticker_bf_010.webp",
        "最強！",
        "DeepSeek娘 二創梗圖",
        "anka-afk/deepseek-fanart-meme-pack",
        "deepseek",
        "deepseek 大肥魚 最強 得意 鯨魚娘",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/EDMOK/blue-fish-archive/main/media/chatgpt-lingbao-zhishi.png",
        "今日班味，已自動加載",
        "藍色大肥魚檔案館",
        "EDMOK/blue-fish-archive",
        "deepseek",
        "chatgpt娘 工作 上班 班味 ai娘化",
    ),
    _make_fallback(
        "https://raw.githubusercontent.com/anka-afk/blue-fat-fish-meme-pack/v1.0.0/memes/surprised/0001_Bug.gif",
        "藍色大肥魚 · Bug",
        "藍色大肥魚動態表情包",
        "anka-afk/blue-fat-fish-meme-pack",
        "deepseek",
        "deepseek 大肥魚 bug 震驚 動圖",
    ),
)


def parse_source_payload(data: Any, spec: MemeSourceSpec) -> List[MemeEntry]:
    """Parse raw JSON payload from one configured open-source database into MemeEntry items."""
    if spec.parser_kind == "semantic_metadata":
        return _parse_semantic_metadata(data, spec)
    if spec.parser_kind == "source_index":
        return _parse_source_index(data, spec)
    if spec.parser_kind == "chinesebqb_anime":
        return _parse_chinesebqb_anime(data, spec)
    if spec.parser_kind == "blue_fish_archive":
        return _parse_blue_fish_archive(data, spec)
    if spec.parser_kind == "dsh_stickers":
        return _parse_dsh_stickers(data, spec)
    return []


def _parse_semantic_metadata(data: Any, spec: MemeSourceSpec) -> List[MemeEntry]:
    if not isinstance(data, dict) or not isinstance(data.get("images"), dict):
        return []
    entries: List[MemeEntry] = []
    for item in data["images"].values():
        if not isinstance(item, dict):
            continue
        rel_path = str(item.get("relative_path") or "").strip()
        category = str(item.get("category") or "").strip().lower()
        if not rel_path:
            continue
        url = _raw_github_url(spec.repo, spec.ref, rel_path)
        if not _is_valid_image_url(url):
            continue

        visible_text = str(item.get("visible_text") or item.get("manual_visible_text") or "").strip()
        caption = str(item.get("caption") or item.get("manual_caption") or "").strip()
        tags = item.get("tags") or item.get("auto_tags") or []
        tags_str = " ".join(str(t) for t in tags if t) if isinstance(tags, list) else str(tags)

        safety_blob = f"{visible_text} {caption} {tags_str}"
        if not _is_sfw(category, safety_blob):
            continue

        title = _clean_title(visible_text, "") or _clean_title(caption, spec.name)
        cat_kw = CATEGORY_KEYWORDS.get(category, category)
        search_blob = normalize_search_text(
            f"{title} {visible_text} {caption} {tags_str} {spec.name} {category} {cat_kw}"
        )
        entries.append(
            MemeEntry(
                url=url,
                title=title,
                source_name=spec.name,
                source_repo=spec.repo,
                theme=spec.theme,
                is_gif=url.lower().endswith(".gif"),
                search_text=search_blob,
                content_hash=str(item.get("content_sha256") or ""),
            )
        )
    return entries


def _parse_source_index(data: Any, spec: MemeSourceSpec) -> List[MemeEntry]:
    if not isinstance(data, dict) or not isinstance(data.get("images"), list):
        return []
    entries: List[MemeEntry] = []
    for item in data["images"]:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").strip().lower()
        rel_path = str(item.get("path") or item.get("relative_path") or "").strip()
        filename = str(item.get("filename") or "").strip()
        if not rel_path and category and filename:
            rel_path = f"memes/{category}/{filename}"
        if not rel_path:
            continue
        url = _raw_github_url(spec.repo, spec.ref, rel_path)
        if not _is_valid_image_url(url):
            continue

        source_name_raw = str(item.get("source_name") or filename or rel_path)
        if not _is_sfw(category, f"{source_name_raw} {filename}"):
            continue

        title = _filename_to_title(filename or source_name_raw, spec.name)
        cat_kw = CATEGORY_KEYWORDS.get(category, category)
        search_blob = normalize_search_text(
            f"{title} {source_name_raw} {filename} {spec.name} {category} {cat_kw}"
        )
        entries.append(
            MemeEntry(
                url=url,
                title=title,
                source_name=spec.name,
                source_repo=spec.repo,
                theme=spec.theme,
                is_gif=url.lower().endswith(".gif"),
                search_text=search_blob,
                content_hash=str(item.get("sha256") or ""),
            )
        )
    return entries


def _parse_chinesebqb_anime(data: Any, spec: MemeSourceSpec) -> List[MemeEntry]:
    if not isinstance(data, dict) or not isinstance(data.get("images"), list):
        return []
    entries: List[MemeEntry] = []
    prefixes = tuple(CHINESEBQB_ANIME_FOLDERS.items())
    for item in data["images"]:
        if not isinstance(item, dict):
            continue
        upstream_path = str(item.get("upstream_path") or "").strip()
        rel_path = str(item.get("relative_path") or "").strip()
        if not upstream_path or not rel_path:
            continue

        matched_series: Optional[str] = None
        for prefix, series_label in prefixes:
            if upstream_path.startswith(prefix):
                matched_series = series_label
                break
        if matched_series is None:
            continue

        url = _raw_github_url(spec.repo, spec.ref, rel_path)
        if not _is_valid_image_url(url):
            continue

        parts = rel_path.split("/")
        category = parts[1].lower() if len(parts) >= 3 else ""
        if not _is_sfw(category, upstream_path):
            continue

        source_label = f"ChineseBQB · {matched_series}"
        title = _filename_to_title(upstream_path, source_label)
        cat_kw = CATEGORY_KEYWORDS.get(category, category)
        search_blob = normalize_search_text(
            f"{title} {matched_series} {upstream_path} {source_label} {category} {cat_kw}"
        )
        entries.append(
            MemeEntry(
                url=url,
                title=title,
                source_name=source_label,
                source_repo=spec.repo,
                theme=spec.theme,
                is_gif=url.lower().endswith(".gif"),
                search_text=search_blob,
                content_hash=str(item.get("sha256") or ""),
            )
        )
    return entries


def _parse_blue_fish_archive(data: Any, spec: MemeSourceSpec) -> List[MemeEntry]:
    if not isinstance(data, dict) or not isinstance(data.get("stickers"), list):
        return []
    entries: List[MemeEntry] = []
    for item in data["stickers"]:
        if not isinstance(item, dict):
            continue
        original = str(item.get("original") or "").strip()
        if original.startswith("https://fisharchive.cc/"):
            rel_path = original[len("https://fisharchive.cc/") :].lstrip("/")
            url = _raw_github_url(spec.repo, spec.ref, rel_path)
        elif original.startswith("https://raw.githubusercontent.com/"):
            url = original
        else:
            continue

        if not _is_valid_image_url(url):
            continue

        alt = str(item.get("alt") or "").strip()
        tags = item.get("tags") or []
        tags_str = " ".join(str(t) for t in tags if t) if isinstance(tags, list) else str(tags)
        if not _is_sfw("", f"{alt} {tags_str}"):
            continue

        title = _clean_title(alt, spec.name)
        search_blob = normalize_search_text(
            f"{title} {alt} {tags_str} {spec.name} deepseek 蓝色大肥鱼 鲸鱼娘 ai娘化"
        )
        entries.append(
            MemeEntry(
                url=url,
                title=title,
                source_name=spec.name,
                source_repo=spec.repo,
                theme=spec.theme,
                is_gif=url.lower().endswith(".gif"),
                search_text=search_blob,
            )
        )
    return entries


def _parse_dsh_stickers(data: Any, spec: MemeSourceSpec) -> List[MemeEntry]:
    if not isinstance(data, dict) or not isinstance(data.get("stickers"), list):
        return []
    entries: List[MemeEntry] = []
    for item in data["stickers"]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("imageUrl") or "").strip()
        # Keep only direct GitHub raw CDN links for maximum uptime and zero third-party ad risk.
        if not url.startswith("https://raw.githubusercontent.com/"):
            continue
        if not _is_valid_image_url(url):
            continue

        tag = str(item.get("tag") or "").strip().lower()
        name = str(item.get("name") or "").strip()
        text = str(item.get("text") or "").strip()
        caption = str(item.get("caption") or "").strip()
        description = str(item.get("description") or "").strip()
        keywords = item.get("keywords") or []
        kw_str = " ".join(str(k) for k in keywords if k) if isinstance(keywords, list) else str(keywords)

        safety_blob = f"{name} {text} {caption} {description} {kw_str}"
        if not _is_sfw(tag, safety_blob):
            continue

        title = _clean_title(text, "") or _clean_title(name, "") or _clean_title(caption, spec.name)
        cat_kw = CATEGORY_KEYWORDS.get(tag, tag)
        search_blob = normalize_search_text(
            f"{title} {name} {text} {caption} {description} {kw_str} {spec.name} {tag} {cat_kw}"
        )
        entries.append(
            MemeEntry(
                url=url,
                title=title,
                source_name=spec.name,
                source_repo=spec.repo,
                theme=spec.theme,
                is_gif=url.lower().endswith(".gif"),
                search_text=search_blob,
            )
        )
    return entries


class AnimeMemeService:
    """Async multi-source online anime meme provider with caching and anti-repeat selection."""

    def __init__(
        self,
        sources: Sequence[MemeSourceSpec] = MEME_SOURCES,
        *,
        cache_ttl_seconds: float = 6 * 3600.0,
        request_timeout_seconds: float = 10.0,
        history_size: int = 60,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.sources: Tuple[MemeSourceSpec, ...] = tuple(sources)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.history_size = max(1, history_size)
        self._rng = rng or random.Random()

        self._entries: List[MemeEntry] = []
        self._by_theme: Dict[str, List[MemeEntry]] = {}
        self._loaded_at: float = 0.0
        self._using_fallback: bool = True
        self._online_sources_loaded: int = 0
        self._lock = asyncio.Lock()
        self._refresh_task: Optional[asyncio.Task[None]] = None
        self._recent_by_channel: Dict[str, Deque[str]] = {}

    @property
    def is_loaded(self) -> bool:
        return bool(self._entries)

    @property
    def is_stale(self) -> bool:
        if not self._entries:
            return True
        if self._using_fallback:
            # Retry online sources sooner (5 minutes) when currently on fallback pool.
            return (time.monotonic() - self._loaded_at) >= 300.0
        return (time.monotonic() - self._loaded_at) >= self.cache_ttl_seconds

    @property
    def using_fallback(self) -> bool:
        return self._using_fallback

    @property
    def total_count(self) -> int:
        return len(self._entries) if self._entries else len(FALLBACK_MEMES)

    def _set_pool(self, entries: Iterable[MemeEntry], *, using_fallback: bool, online_sources: int) -> None:
        deduped: List[MemeEntry] = []
        seen_urls: set[str] = set()
        seen_hashes: set[str] = set()
        for entry in entries:
            if entry.url in seen_urls:
                continue
            if entry.content_hash and entry.content_hash in seen_hashes:
                continue
            seen_urls.add(entry.url)
            if entry.content_hash:
                seen_hashes.add(entry.content_hash)
            deduped.append(entry)

        by_theme: Dict[str, List[MemeEntry]] = {}
        for entry in deduped:
            by_theme.setdefault(entry.theme, []).append(entry)

        self._entries = deduped
        self._by_theme = by_theme
        self._using_fallback = using_fallback
        self._online_sources_loaded = online_sources
        self._loaded_at = time.monotonic()

    async def _fetch_source(
        self, session: aiohttp.ClientSession, spec: MemeSourceSpec
    ) -> List[MemeEntry]:
        async with session.get(spec.index_url) as resp:
            if resp.status != 200:
                logger.warning("二次元梗圖圖庫 %s 回應 HTTP %d", spec.source_id, resp.status)
                return []
            raw = await resp.read()
        data = json.loads(raw.decode("utf-8-sig"))
        return parse_source_payload(data, spec)

    async def refresh(self) -> int:
        """Fetch all configured free online anime meme databases concurrently."""
        async with self._lock:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
            headers = {"User-Agent": "AstralChronicle-DiscordBot/1.0"}
            collected: List[MemeEntry] = []
            ok_sources = 0
            try:
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    results = await asyncio.gather(
                        *(self._fetch_source(session, spec) for spec in self.sources),
                        return_exceptions=True,
                    )
                for spec, res in zip(self.sources, results):
                    if isinstance(res, Exception):
                        logger.warning("載入二次元梗圖圖庫 %s 失敗: %s", spec.source_id, res)
                        continue
                    if res:
                        ok_sources += 1
                        collected.extend(res)
            except Exception as exc:
                logger.warning("連線載入線上二次元梗圖資料庫時發生錯誤: %s", exc)

            if collected:
                self._set_pool(collected, using_fallback=False, online_sources=ok_sources)
                logger.info(
                    "🎭 已從 %d/%d 個免費開源線上圖庫載入 %d 張二次元梗圖",
                    ok_sources,
                    len(self.sources),
                    len(self._entries),
                )
            elif not self._entries:
                self._set_pool(FALLBACK_MEMES, using_fallback=True, online_sources=0)
                logger.warning(
                    "⚠️ 線上梗圖資料庫暫時無法連線，已自動切換為內建 %d 張備援二次元梗圖",
                    len(self._entries),
                )
            else:
                # Keep previously cached online entries and postpone next retry.
                self._loaded_at = time.monotonic()
            return len(self._entries)

    async def ensure_loaded(self) -> int:
        """Ensure at least one load has completed; triggers background refresh if stale."""
        if not self._entries:
            return await self.refresh()
        self.trigger_background_refresh_if_stale()
        return len(self._entries)

    def trigger_background_refresh_if_stale(self) -> None:
        """Refresh expired cache asynchronously without blocking the user command."""
        if not self.is_stale:
            return
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._refresh_task = loop.create_task(self.refresh())

    def get_stats(self) -> Dict[str, Any]:
        pool = self._entries if self._entries else list(FALLBACK_MEMES)
        counts: Dict[str, int] = {}
        gif_count = 0
        for item in pool:
            counts[item.theme] = counts.get(item.theme, 0) + 1
            if item.is_gif:
                gif_count += 1
        return {
            "total": len(pool),
            "by_theme": counts,
            "gif_count": gif_count,
            "online_sources_loaded": self._online_sources_loaded,
            "using_fallback": self._using_fallback,
        }

    def _pick_avoiding_recent(
        self, candidates: Sequence[MemeEntry], history_key: str
    ) -> Optional[MemeEntry]:
        if not candidates:
            return None
        history = self._recent_by_channel.setdefault(
            history_key, deque(maxlen=self.history_size)
        )
        recent_set = set(history)
        fresh = [m for m in candidates if m.url not in recent_set]
        pool = fresh if fresh else candidates
        chosen = self._rng.choice(pool)
        history.append(chosen.url)
        return chosen

    def pick_random(
        self,
        *,
        category: str = "all",
        keyword: Optional[str] = None,
        history_key: str = "global",
    ) -> Tuple[Optional[MemeEntry], int, int]:
        """Select a random anime meme.

        Returns ``(meme_or_none, matched_count, total_pool_count)``.
        When ``category == "all"`` and no keyword is given, balances draws across themes
        so no single repository overwhelms the random feed.
        """
        pool = self._entries if self._entries else list(FALLBACK_MEMES)
        total = len(pool)
        cat = (category or "all").strip().lower()
        kw_raw = (keyword or "").strip()

        if cat == "gif":
            scoped = [m for m in pool if m.is_gif]
        elif cat in ("acg_mix", "anime_classic", "deepseek"):
            scoped = [m for m in pool if m.theme == cat]
        else:
            scoped = pool

        if kw_raw:
            tokens = [t for t in normalize_search_text(kw_raw).split() if t]
            matched = [
                m for m in scoped if all(tok in m.search_text for tok in tokens)
            ]
            chosen = self._pick_avoiding_recent(matched, history_key)
            return chosen, len(matched), total

        if cat == "all":
            # Balanced weighted draw across available themes
            buckets: Dict[str, List[MemeEntry]] = {}
            for m in scoped:
                buckets.setdefault(m.theme, []).append(m)
            available_themes = [t for t, items in buckets.items() if items]
            if not available_themes:
                return None, 0, total
            weights = [THEME_WEIGHTS.get(t, 0.25) for t in available_themes]
            chosen_theme = self._rng.choices(available_themes, weights=weights, k=1)[0]
            chosen = self._pick_avoiding_recent(buckets[chosen_theme], history_key)
            return chosen, len(scoped), total

        chosen = self._pick_avoiding_recent(scoped, history_key)
        return chosen, len(scoped), total
