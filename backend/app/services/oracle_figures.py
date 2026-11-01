"""Who the Oracle desk follows, where each one's signals come from, and their portrait.

Chosen 2026-10-29 for a primary source that reaches this server, not for fame alone:
  * movers  — what they say moves other companies' stock (posts, deals). Read through
              news + the LLM filter; their OWN company is excluded (`own`), because
              Huang praising Nvidia was 40 of his 54 "signals" and none of them news.
  * funds   — 13F holdings each quarter (positions changed by ≥1% of the portfolio),
              ARK's daily trade file, Burry's Substack since Scion closed in 2025.
  * congress— House Periodic Transaction Reports with machine-readable PDFs. Khanna and
              McCaul file scanned images (no text), so they cannot be followed here.
  * media   — TV and online voices with large followings, via news and YouTube.
X itself is not reachable without a paid API key (`X_BEARER_TOKEN`); the x sources stay
configured and switch on when one is set. Free stand-ins (checked 2026-11-01): Musk's
posts via the fan-run Telegram mirror @ElonMusk_posts; Serenity via Chinese flash-news
feeds that quote him. Nitter mirrors and the Bluesky copies of these accounts are dead.

Dropped: Lisa Su — after removing AMD (her own company) she had two calls in a month.

Portraits are free-licensed Wikimedia Commons files, saved under frontend/public/figures
with their credit; `avatar` is a drawn placeholder for people with no free photo.
"""
from __future__ import annotations

# (license, author, Commons page) — CC BY / BY-SA need this credit shown on the page
_C = "https://commons.wikimedia.org/wiki/File:"
PHOTO = {
    "trump": ("Public domain", "Daniel Torok", _C + "Official_Presidential_Portrait_of_President_Donald_J._Trump_(2025).jpg"),
    "musk": ("CC BY-SA 4.0", "Gage Skidmore", _C + "Elon_Musk_-_54820081119_(3x4_cropped,_Rule_of_thirds).jpg"),
    "huang": ("CC BY-SA 4.0", "Anderseidesvik", _C + "Jensen_Huang_Stanford_2026-04-30_010_(cropped).jpg"),
    "altman": ("CC BY 2.0", "TechCrunch", _C + "Sam_Altman_CropEdit_James_Tamim.jpg"),
    "wood": ("CC BY-SA 4.0", "Caroline Wood", _C + "Cathie_Wood_ARK_Invest_Photo.jpg"),
    "pelosi": ("Public domain", "John Harrington", _C + "Official_photo_of_Speaker_Nancy_Pelosi_in_2019.jpg"),
    "gottheimer": ("Public domain", "U.S. House Office of Photography", _C + "Josh_Gottheimer,_official_portrait,_115th_Congress_(cropped).jpg"),
    "donalds": ("Public domain", "United States Congress", _C + "Rep._Byron_Donalds_official_photo,_117th_Congress.jpg"),
    "fields": ("Public domain", "House Creative Services", _C + "Fields_Cleo_119th_Congress_(4x5_cropped).jpg"),
    "buffett": ("Public domain", "U.S. International Trade Administration", _C + "Warren_Buffett_at_the_2015_SelectUSA_Investment_Summit_(cropped).jpg"),
    "ackman": ("CC BY 2.0", "Senate Democrats", _C + "Valeant_Pharmaceuticals%27_Business_Model_(headshot).jpg"),
    "tepper": ("CC BY-SA 3.0", "Appaloosa Management", _C + "David_Tepper_01.jpg"),
    "klarman": ("CC BY 2.0", "Maryland GovPics", _C + "Seth_Klarman_at_147th_Preakness_Stakes.jpg"),
    "icahn": ("CC0", "AviateHistory", _C + "Carl_Icahn,_1980s.jpg"),
    "pabrai": ("CC BY-SA 3.0", "Fabarsi", _C + "Mohnish_Pabrai.jpg"),
    "cramer": ("CC BY 2.0", "Bear Bull Traders", _C + "Andrew_Aziz_Cramer_(cropped).jpg"),
    "tomlee": ("CC BY-SA 4.0", "Xuthoria", _C + "Consensus_2026_-_Tom_Lee_04_(cropped).jpg"),
    "oleary": ("CC BY-SA 4.0", "Philip Romano", _C + "KevinOLeary2023_(3x4_cropped).jpg"),
    "chamath": ("CC BY-SA 4.0", "Cmichel67", _C + "Chamath_Palihapitiya_in_2025.jpg"),
}
# where the face sits in a non-square photo (CSS object-position)
FOCUS = {"klarman": "50% 12%", "icahn": "40% 25%", "tepper": "50% 30%", "chamath": "50% 15%"}
AVATAR = {"burry": "/avatars/burry.svg", "serenity": "/avatars/serenity.svg"}


def _gn(*q, hl: str = "en-US") -> dict:
    return {"type": "gnews", "queries": list(q), "hl": hl}


def _f13(cik: int | list[int], fund: str) -> dict:
    return {"type": "f13", "cik": cik, "fund": fund}


FIGURES: dict[str, dict] = {
    # ── movers ──
    "trump": {"name": "Donald Trump", "zh": "特朗普", "group": "movers", "type": "policy", "emoji": "🇺🇸", "cadence": "live",
              "why": "Truth Social posts, tariffs and deals", "why_zh": "Truth Social 发帖、关税与交易",
              "own": ["DJT"],
              "sources": [{"type": "trumparchive"}, {"type": "truth", "handle": "realDonaldTrump"},
                          {"type": "x", "handle": "realDonaldTrump"}, _gn("Trump says company stock", "Trump tariff stock")]},
    "musk": {"name": "Elon Musk", "zh": "马斯克", "group": "movers", "type": "x_mover", "emoji": "🚀", "cadence": "live",
             "why": "Companies he names or deals with (not Tesla itself)", "why_zh": "他点名或合作的公司（不含特斯拉本身）",
             "own": ["TSLA"],
             "sources": [{"type": "tg", "channel": "ElonMusk_posts", "skip": "Reposted"}, {"type": "x", "handle": "elonmusk"},
                         _gn("Elon Musk says stock", "Musk xAI deal stock")]},
    "huang": {"name": "Jensen Huang", "zh": "黄仁勋", "group": "movers", "type": "tech_ceo", "emoji": "🟢", "cadence": "live",
              "why": "Partners and suppliers he names (not Nvidia itself)", "why_zh": "他点名的合作伙伴与供应商（不含英伟达本身）",
              "own": ["NVDA"],
              "sources": [_gn("Jensen Huang says stock", "Nvidia Huang partnership stock"), {"type": "news", "queries": ["Jensen Huang says"]}]},
    "altman": {"name": "Sam Altman", "zh": "奥特曼", "group": "movers", "type": "tech_ceo", "emoji": "🤖", "cadence": "live",
               "why": "OpenAI compute deals move the partners", "why_zh": "OpenAI 的算力合同会带动合作方股价",
               "own": [],
               "sources": [{"type": "x", "handle": "sama"}, _gn("Sam Altman OpenAI deal stock", "OpenAI agreement shares jump")]},
    # ── funds ──
    "wood": {"name": "Cathie Wood", "zh": "木头姐", "group": "funds", "type": "fund", "emoji": "📈", "cadence": "daily",
             "why": "ARK's daily trade file", "why_zh": "ARK 每日交易披露",
             "own": ["ARKK", "ARKW", "ARKG", "ARKQ", "ARKF", "ARKX"],
             "sources": [{"type": "ark"}, {"type": "x", "handle": "CathieDWood"}, _gn("Cathie Wood ARK buys")]},
    "buffett": {"name": "Warren Buffett", "zh": "巴菲特", "group": "funds", "type": "value", "emoji": "💰", "cadence": "quarterly",
                "why": "Berkshire Hathaway's 13F", "why_zh": "伯克希尔 13F 持仓",
                "own": ["BRK-B", "BRK-A"],
                "sources": [_f13(1067983, "Berkshire Hathaway"), {"type": "edgar", "cik": "1067983"}, _gn("Berkshire Hathaway stake buys")]},
    "ackman": {"name": "Bill Ackman", "zh": "阿克曼", "group": "funds", "type": "activist", "emoji": "🎯", "cadence": "quarterly",
               "why": "Pershing Square 13F and 13D stakes", "why_zh": "潘兴广场 13F 与 13D 举牌",
               "sources": [_f13([2026053, 1336528], "Pershing Square"), {"type": "edgar", "cik": "1336528"},
                           {"type": "x", "handle": "BillAckman"}, _gn("Bill Ackman stake")]},
    "druckenmiller": {"name": "Stanley Druckenmiller", "zh": "德鲁肯米勒", "group": "funds", "type": "fund13f", "emoji": "🦅",
                      "cadence": "quarterly", "why": "Duquesne Family Office 13F", "why_zh": "杜肯家族办公室 13F",
                      "sources": [_f13(1536411, "Duquesne Family Office"), _gn("Druckenmiller stake", "Druckenmiller says")]},
    "tepper": {"name": "David Tepper", "zh": "泰珀", "group": "funds", "type": "fund13f", "emoji": "🏈", "cadence": "quarterly",
               "why": "Appaloosa 13F", "why_zh": "Appaloosa 13F",
               "sources": [_f13(1656456, "Appaloosa"), _gn("David Tepper stake", "David Tepper says")]},
    "lilu": {"name": "Li Lu", "zh": "李录", "group": "funds", "type": "value", "emoji": "🏔", "cadence": "quarterly",
             "why": "Himalaya Capital 13F (Munger's pick)", "why_zh": "喜马拉雅资本 13F（芒格托付的人）",
             "sources": [_f13(1709323, "Himalaya Capital"), _gn("李录 喜马拉雅 持仓", hl="zh-CN")]},
    "duan": {"name": "Duan Yongping", "zh": "段永平", "group": "funds", "type": "value", "emoji": "🀄", "cadence": "quarterly",
             "why": "H&H International 13F", "why_zh": "H&H International 13F（大道）",
             "sources": [_f13(1759760, "H&H International"), _gn("段永平 买入", "段永平 持仓", hl="zh-CN")]},
    "klarman": {"name": "Seth Klarman", "zh": "克拉曼", "group": "funds", "type": "value", "emoji": "📚", "cadence": "quarterly",
                "why": "Baupost Group 13F", "why_zh": "Baupost 13F",
                "sources": [_f13(1061768, "Baupost"), _gn("Baupost Klarman stake")]},
    "einhorn": {"name": "David Einhorn", "zh": "艾因霍恩", "group": "funds", "type": "contrarian", "emoji": "🃏", "cadence": "quarterly",
                "why": "Greenlight (DME Capital) 13F and public shorts", "why_zh": "绿光资本（DME）13F 与公开做空",
                "sources": [_f13(1489933, "Greenlight / DME Capital"), _gn("David Einhorn Greenlight")]},
    "loeb": {"name": "Dan Loeb", "zh": "勒布", "group": "funds", "type": "activist", "emoji": "✉️", "cadence": "quarterly",
             "why": "Third Point 13F and activist letters", "why_zh": "Third Point 13F 与维权信",
             "sources": [_f13(1040273, "Third Point"), _gn("Dan Loeb Third Point stake")]},
    "icahn": {"name": "Carl Icahn", "zh": "伊坎", "group": "funds", "type": "activist", "emoji": "⚔️", "cadence": "quarterly",
              "why": "Icahn 13F and 13D stakes", "why_zh": "伊坎 13F 与 13D 举牌",
              "own": ["IEP"],
              "sources": [_f13(921669, "Icahn"), {"type": "edgar", "cik": "921669"}, _gn("Carl Icahn stake")]},
    "coleman": {"name": "Chase Coleman", "zh": "科尔曼", "group": "funds", "type": "fund13f", "emoji": "🐯", "cadence": "quarterly",
                "why": "Tiger Global 13F", "why_zh": "老虎环球 13F",
                "sources": [_f13(1167483, "Tiger Global"), _gn("Tiger Global stake")]},
    "laffont": {"name": "Philippe Laffont", "zh": "拉方特", "group": "funds", "type": "fund13f", "emoji": "🧭", "cadence": "quarterly",
                "why": "Coatue 13F", "why_zh": "Coatue 13F",
                "sources": [_f13(1135730, "Coatue"), _gn("Coatue stake")]},
    "pabrai": {"name": "Mohnish Pabrai", "zh": "帕伯莱", "group": "funds", "type": "value", "emoji": "🎲", "cadence": "quarterly",
               "why": "Dalal Street 13F", "why_zh": "Dalal Street 13F",
               "sources": [_f13(1549575, "Dalal Street"), _gn("Mohnish Pabrai stake")]},
    "burry": {"name": "Michael Burry", "zh": "迈克尔·伯里", "group": "funds", "type": "contrarian", "emoji": "🐻", "cadence": "live",
              "why": "Substack 'Cassandra Unchained' (Scion closed in 2025)", "why_zh": "Substack「Cassandra Unchained」（Scion 已于 2025 年关闭）",
              "sources": [{"type": "rss", "url": "https://michaeljburry.substack.com/feed"}, {"type": "x", "handle": "michaeljburry"},
                          _gn("Michael Burry short", "Michael Burry Substack")]},
    # ── congress ──
    "pelosi": {"name": "Nancy Pelosi", "zh": "佩洛西", "group": "congress", "type": "congress", "emoji": "🏛", "cadence": "filing",
               "why": "House trade disclosures (often options)", "why_zh": "众议院交易披露（常用期权）",
               "sources": [{"type": "congress", "name": "Pelosi", "first": "Nancy"}]},
    "gottheimer": {"name": "Josh Gottheimer", "zh": "戈特海默", "group": "congress", "type": "congress", "emoji": "🏛", "cadence": "filing",
                   "why": "House trade disclosures (managed account)", "why_zh": "众议院交易披露（券商代管账户）",
                   "sources": [{"type": "congress", "name": "Gottheimer", "first": "Josh"}]},
    "donalds": {"name": "Byron Donalds", "zh": "唐纳兹", "group": "congress", "type": "congress", "emoji": "🏛", "cadence": "filing",
                "why": "House trade disclosures", "why_zh": "众议院交易披露",
                "sources": [{"type": "congress", "name": "Donalds", "first": "Byron"}]},
    "fields": {"name": "Cleo Fields", "zh": "克莱奥·菲尔兹", "group": "congress", "type": "congress", "emoji": "🏛", "cadence": "filing",
               "why": "House trade disclosures (big-tech buyer)", "why_zh": "众议院交易披露（频繁买入科技股）",
               "sources": [{"type": "congress", "name": "Fields", "first": "Cleo"}]},
    # ── media ──
    "cramer": {"name": "Jim Cramer", "zh": "克莱默", "group": "media", "type": "tv", "emoji": "📺", "cadence": "live",
               "why": "Mad Money calls (the 'inverse Cramer' meme)", "why_zh": "Mad Money 节目荐股（「反向克莱默」梗）",
               "sources": [_gn("Jim Cramer says buy", "Jim Cramer says sell", "Cramer stock pick")]},
    "ives": {"name": "Dan Ives", "zh": "艾夫斯", "group": "media", "type": "tv", "emoji": "🎤", "cadence": "live",
             "why": "Wedbush tech analyst, TV's loudest AI bull", "why_zh": "Wedbush 科技分析师，电视上最高调的 AI 多头",
             "own": ["IVES"],
             "sources": [_gn("Dan Ives says", "Wedbush Ives price target")]},
    "tomlee": {"name": "Tom Lee", "zh": "汤姆·李", "group": "media", "type": "tv", "emoji": "🧮", "cadence": "live",
               "why": "Fundstrat strategist, BitMine chair", "why_zh": "Fundstrat 策略师、BitMine 董事长",
               "own": ["BMNR", "GRNY"],
               "sources": [_gn("Tom Lee Fundstrat says", "Tom Lee stock pick")]},
    "oleary": {"name": "Kevin O'Leary", "zh": "奥利里", "group": "media", "type": "tv", "emoji": "🦈", "cadence": "live",
               "why": "'Mr. Wonderful' of Shark Tank", "why_zh": "《创智赢家》里的「美妙先生」",
               "sources": [_gn("Kevin O'Leary says stock", "Kevin O'Leary buying")]},
    "chamath": {"name": "Chamath Palihapitiya", "zh": "查马斯", "group": "media", "type": "creator", "emoji": "🎙", "cadence": "live",
                "why": "All-In podcast host", "why_zh": "All-In 播客主持人",
                "sources": [{"type": "youtube", "channel": "UCESLZhusAkFfsNsApnjF_Cg"}, _gn("Chamath says stock")]},
    "serenity": {"name": "Serenity", "zh": "白毛股神 Serenity", "group": "media", "type": "x_trader", "emoji": "🐦", "cadence": "live",
                 "why": "@aleabitoreddit — AI supply-chain 'bottleneck' picks", "why_zh": "@aleabitoreddit，AI 供应链「瓶颈股」",
                 "sources": [{"type": "x", "handle": "aleabitoreddit"}, _gn("Serenity aleabitoreddit"),
                             {"type": "kwfeed", "keys": ["aleabitoreddit", "Serenity", "白毛股神", "白发股神"]},
                             _gn("白毛股神 Serenity", "Serenity 美股 推荐", hl="zh-CN")]},
    "tomnash": {"name": "Tom Nash", "zh": "Tom Nash", "group": "media", "type": "creator", "emoji": "▶️", "cadence": "live",
                "why": "YouTube growth-stock picks", "why_zh": "YouTube 成长股推荐",
                "sources": [{"type": "youtube", "channel": "UCJwKCyEIFHwUOPQQ-4kC1Zw"}]},
    "lefebvre": {"name": "Jeremy Lefebvre", "zh": "Jeremy Lefebvre", "group": "media", "type": "creator", "emoji": "▶️", "cadence": "live",
                 "why": "Financial Education on YouTube", "why_zh": "YouTube 频道 Financial Education",
                 "sources": [{"type": "youtube", "channel": "UCCmJVw9xQfYuuAAwZGedKRg"}]},
}

# the ten figures before 2026-10-29 — anything else is new and starts switched on
LEGACY = {"trump", "huang", "serenity", "musk", "su", "wood", "ackman", "pelosi", "buffett", "burry"}


def portrait(key: str) -> dict | None:
    if key in PHOTO:
        lic, who, page = PHOTO[key]
        return {"src": f"/figures/{key}.jpg", "license": lic, "author": who, "page": page,
                "focus": FOCUS.get(key)}
    if key in AVATAR:
        return {"src": AVATAR[key], "license": None, "author": None, "page": None, "focus": None}
    return None
