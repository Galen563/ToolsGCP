"""GCP-AI 的产品边界依据：读磁盘上的用户协议 / 隐私政策全文。
========== 为什么单独一个模块 ==========
用户要求：AI 必须能看到《ToolsGCP 用户协议》《ToolsGCP 隐私政策及免责声明》这两份
txt，当用户的要求越过 ToolsGCP 的边界时，AI 要能指出触发了哪一条、解释为什么不能做，
并给出合规的替代做法。同时明确要求：
    不要内嵌入到代码中 要让AI看到我这个2个txt，系统提示词之类的是可以写进代码中的
所以：**协议正文只存在于 .ToolsGCP/legal/*.txt**，代码里只放"怎么用这两份文件"的
系统提示词（见 prompt.LEGAL_RULES）。改条款时只改 txt，不用改代码、不用重新打包 Python。
========== 文件在哪 ==========
    <程序目录>/.ToolsGCP/legal/ToolsGCP_User Agreement.txt
    <程序目录>/.ToolsGCP/legal/ToolsGCP_Privacy Policy and Disclaimer.txt
程序目录旁的 `.ToolsGCP` 是**资源目录**（随程序发布，不随数据根迁移），界面上也能通过
/res/legal/... 直接打开这两份文件（webhost.py 的 /res/<path> 路由）。
========== 读取策略 ==========
· 按 (mtime_ns, size) 缓存：协议文件没变就只读一次磁盘；
· 单个文件超过 MAX_FILE_CHARS 时截断并在末尾标注"（以下截断）"，避免把上下文撑爆；
· 任何异常都只让调用方拿到空列表 —— AI 少一段参考可以，启动失败不行。
"""

import os
import re

from ...constants import CONFIG_DIR

# 协议目录（资源目录，随程序走）
LEGAL_DIR = os.path.join(CONFIG_DIR, "legal")

# 固定顺序 + 固定显示名：标题写进提示词，模型引用条款时用它区分两份文件
LEGAL_FILES = (
    ("ToolsGCP 用户协议", "ToolsGCP_User Agreement.txt"),
    ("ToolsGCP 隐私政策及免责声明", "ToolsGCP_Privacy Policy and Disclaimer.txt"),
)

# 单文件最多喂给模型多少字（两份合计约 1.4 万字符，正常不会触发截断）
MAX_FILE_CHARS = 16000

# (mtime_ns, size) -> [(title, filename, text)]
_cache = {}


def legal_dir() -> str:
    """协议目录的绝对路径（日志/诊断用）"""
    return LEGAL_DIR


def _read_one(filename: str) -> str:
    path = os.path.join(LEGAL_DIR, filename)
    try:
        stat = os.stat(path)
    except OSError:
        return ""
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _cache.get(path)
    if cached and cached[0] == key:
        return cached[1]
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > MAX_FILE_CHARS:
        text = text[:MAX_FILE_CHARS] + "\n……（以下内容因长度限制被截断）"
    _cache[path] = (key, text)
    return text


def documents():
    """返回 [(标题, 文件名, 全文)]；缺失的文件直接跳过（不抛异常）"""
    result = []
    for title, filename in LEGAL_FILES:
        text = _read_one(filename)
        if text:
            result.append((title, filename, text))
    return result


def missing_files():
    """返回缺失的文件名列表（启动日志/诊断用；正常构建里应为空）"""
    return [filename for _, filename in LEGAL_FILES
            if not os.path.isfile(os.path.join(LEGAL_DIR, filename))]


def build_legal_prompt(max_total_chars: int = 32000) -> str:
    """把两份协议拼成一段可直接塞进 system 消息的文本
    返回空串 = 两份都没读到（调用方会跳过这一节，并在日志里记一条 warn）。
    """
    docs = documents()
    if not docs:
        return ""
    budget = max(2000, int(max_total_chars or 0))
    chunks = []
    for title, filename, text in docs:
        body = text
        if len(body) > budget:
            body = body[:budget] + "\n……（以下内容因总长度限制被截断）"
        chunks.append("===== 《%s》（%s）=====\n%s" % (title, filename, body))
        budget -= len(body)
        if budget <= 0:
            break
    return "\n\n".join(chunks)


# ==========================================================================
# 条号目录（本轮新增 —— 需求：不再每次注入全文，省 token）
# ==========================================================================
# 用户原话：「我之前写了每次对话开始都给AI植入2份用户协议和隐私政策，导致大量文本
#   消耗太多token问题。现在我决定 AI 可以主动找到这个协议，不是必须发送的文本提示词，
#   但要让 AI 知道这个的存在，提示词限制下不要让 AI 阅读这个文本，只是告诉他有这个东西，
#   必要时允许查阅」。
#
# 所以这一节只给**目录**：每份文件的 条号 + 条标题（正文一个字都不给）。
# 两份协议合计约 5000 字符 → 目录只要 ~400 字符，**每条消息省 ~4600 字符**
# （目录里"第 3.2 条 禁止性行为"这类标题本身就足以让模型判断"这事触边界、该查阅"，
#   所以砍掉正文并没有砍掉判断力，只是砍掉了 token）。
#
# 标题怎么认（两种编号体系都覆盖，且刻意**保守**）：
#   · 中文式 `第X条 标题` → 整行就是标题；
#   · 数字式 `N.M 正文…`  → 这一条的标题取**它后面第一条中文式标题之前的第一句**？
#     不，那样会把整段正文当标题。实际两份文件的结构是「第X条 标题」在前、
#     后面跟若干 `N.M 正文`，所以数字式**只列条号不配标题**（宁缺毋滥）。
_HEADING_RE = re.compile(r"^(第\s*[一二三四五六七八九十百零〇\d]+\s*[条章节])\s*(.{0,40})$")
# 目录最多列多少行（防御：协议文件被换成超大/畸形内容时不至于把提示词撑爆）
INDEX_MAX_LINES = 40


def build_legal_index() -> str:
    """两份协议的**条号目录**（只含条号与标题，不含正文）。

    返回空串 = 一份都没读到（调用方退回 LEGAL_MISSING_HINT）。
    """
    lines = []
    for title, _filename, text in documents():
        lines.append("《%s》" % title)
        count = 0
        for raw in text.split("\n"):
            line = raw.strip()
            if not line:
                continue
            m = _HEADING_RE.match(line)
            if not m:
                continue
            head = m.group(1).replace(" ", "")
            name = (m.group(2) or "").strip()
            lines.append("  %s%s" % (head, ("　" + name) if name else ""))
            count += 1
            if count >= INDEX_MAX_LINES:
                lines.append("  …（其余条目从略）")
                break
    if not lines:
        return ""
    return "\n".join(lines)


def clause_count() -> int:
    """目录里一共识别出多少条（诊断/日志用；0 = 协议没读到或格式不认）"""
    index = build_legal_index()
    if not index:
        return 0
    return sum(1 for line in index.split("\n") if line.startswith("  第"))
