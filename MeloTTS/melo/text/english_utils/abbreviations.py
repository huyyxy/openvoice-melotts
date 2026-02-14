import re

# ============================================================
# 第一类：全大写缩写 —— 逐字母拼读（字母之间加空格）
# 这些缩写在英语中通常按字母逐个读出，而不是作为单词发音。
# ============================================================
abbreviations_spell_out = [
    (re.compile(r'\b%s\b' % x[0]), x[1])
    for x in [
        # 技术术语
        ("API",  "A P I"),
        ("SDK",  "S D K"),
        ("NFT",  "N F T"),
        ("GPU",  "G P U"),
        ("CPU",  "C P U"),
        ("SSD",  "S S D"),
        ("HDD",  "H D D"),
        ("USB",  "U S B"),
        ("URL",  "U R L"),
        ("HTML", "H T M L"),
        ("CSS",  "C S S"),
        ("SQL",  "S Q L"),
        ("PDF",  "P D F"),
        ("ATM",  "A T M"),
        ("STM",  "S T M"),
        # 人工智能
        ("AI",   "A I"),
        ("ML",   "M L"),
        ("NLP",  "N L P"),
        ("LLM",  "L L M"),
        ("TTS",  "T T S"),
        ("ASR",  "A S R"),
        # 组织与机构
        ("FBI",  "F B I"),
        ("CIA",  "C I A"),
        ("WHO",  "W H O"),
        ("UN",   "U N"),
        ("EU",   "E U"),
        ("IT",   "I T"),
        ("HR",   "H R"),
        ("PR",   "P R"),
        # 通信与网络
        ("IP",   "I P"),
        ("TCP",  "T C P"),
        ("UDP",  "U D P"),
        ("VPN",  "V P N"),
        ("DNS",  "D N S"),
        ("HTTP", "H T T P"),
        ("SSH",  "S S H"),
        ("IoT",  "I o T"),
        # 其他常见
        ("CEO",  "C E O"),
        ("CTO",  "C T O"),
        ("CFO",  "C F O"),
        ("COO",  "C O O"),
        ("ID",   "I D"),
        ("OK",   "O K"),
        ("TV",   "T V"),
        ("DJ",   "D J"),
        ("GPS",  "G P S"),
        ("PIN",  "P I N"),
        ("LED",  "L E D"),
        ("LCD",  "L C D"),
    ]
]

# ============================================================
# 第二类：通用缩写 —— 展开为完整英文单词
# ============================================================
abbreviations_general = [
    (re.compile(r'\betc\.\b',  re.IGNORECASE), 'etcetera'),
    (re.compile(r'\be\.g\.\b', re.IGNORECASE), 'for example'),
    (re.compile(r'\bi\.e\.\b', re.IGNORECASE), 'that is'),
    (re.compile(r'\bvs\.\b',   re.IGNORECASE), 'versus'),
    (re.compile(r'\bext\.\b',  re.IGNORECASE), 'extension'),
    (re.compile(r'\bno\.\b',   re.IGNORECASE), 'number'),
    (re.compile(r'\bvol\.\b',  re.IGNORECASE), 'volume'),
    (re.compile(r'\bdept\.\b', re.IGNORECASE), 'department'),
    (re.compile(r'\bapprox\.\b', re.IGNORECASE), 'approximately'),
    (re.compile(r'\binc\.\b',  re.IGNORECASE), 'incorporated'),
    (re.compile(r'\bcorp\.\b', re.IGNORECASE), 'corporation'),
]

# ============================================================
# 第三类：称谓与军衔缩写 —— 原有缩写词典（带句点后缀）
# ============================================================
abbreviations_en = [
    (re.compile("\\b%s\\." % x[0], re.IGNORECASE), x[1])
    for x in [
        ("mrs", "misess"),
        ("mr", "mister"),
        ("dr", "doctor"),
        ("st", "saint"),
        ("co", "company"),
        ("jr", "junior"),
        ("maj", "major"),
        ("gen", "general"),
        ("drs", "doctors"),
        ("rev", "reverend"),
        ("lt", "lieutenant"),
        ("hon", "honorable"),
        ("sgt", "sergeant"),
        ("capt", "captain"),
        ("esq", "esquire"),
        ("ltd", "limited"),
        ("col", "colonel"),
        ("ft", "fort"),
    ]
]

def expand_abbreviations(text, lang="en"):
    if lang == "en":
        # 按顺序应用三类缩写规则：
        # 1. 先处理全大写缩写（逐字母拼读），避免被后续规则干扰
        for regex, replacement in abbreviations_spell_out:
            text = re.sub(regex, replacement, text)
        # 2. 处理通用缩写（展开为完整单词）
        for regex, replacement in abbreviations_general:
            text = re.sub(regex, replacement, text)
        # 3. 处理称谓/军衔缩写
        for regex, replacement in abbreviations_en:
            text = re.sub(regex, replacement, text)
    else:
        raise NotImplementedError()
    return text
