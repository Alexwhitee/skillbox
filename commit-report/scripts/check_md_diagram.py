#!/usr/bin/env python3
"""检查 markdown 里的图表能否在最老的渲染环境里也正常显示。

用法:
    python check_md_diagram.py <file.md> [更多文件...]

ERROR 一定会出问题，必须改：
  1. 用了 flowchart（mermaid 8.4 及以下不认）
  2. 每行没有顶格（行首空格会被某些编辑器改写成 &#160;，整张图不渲染）
  3. 标签（引号外）里有全角标点、①、≥、×、分号、& 等老版本会报错或卡死的字符
  4. 标签里有 ( ) [ ] { } | 这类会破坏语法的字符
  5. 用了新版才有的图表类型（xychart-beta / quadrantChart / mindmap / timeline 等）
  6. 文字条形表格（█）的长度和标注的换算规则对不上

WARN 只在老版本或个别编辑器里有风险，能改则改：
  - 引号标签、<br/>、style、classDef、subgraph、& 并列、pie/erDiagram 等

退出码: 0 表示没有 ERROR，1 表示有 ERROR。
"""

import re
import sys
from pathlib import Path

# 最早可用的图表类型（mermaid 7.1 起）
SAFE_TYPES = ("graph", "sequenceDiagram", "classDiagram", "gantt")

# 需要较新版本，只提醒
VERSIONED_TYPES = {
    "pie": "mermaid 8.4+",
    "erDiagram": "mermaid 8.6+",
    "stateDiagram-v2": "mermaid 8.6+",
    "journey": "mermaid 8.6+",
    "gitGraph": "mermaid 9.0+",
    "C4Context": "mermaid 9.0+",
}

# 老环境基本一定失败，必须换成别的写法
BAD_TYPES = {
    "flowchart": "改成 graph（8.4 及以下不认 flowchart）",
    "quadrantChart": "改成两行两列的表",
    "xychart-beta": "改成表格加 █ 条形",
    "mindmap": "改成嵌套列表",
    "timeline": "改成表格",
    "sankey-beta": "改成表格",
    "block-beta": "改成 graph 或表格",
    "requirementDiagram": "改成表",
    "zenuml": "不支持",
}

# 引号外出现就会挂的字符（这些字符不会出现在合法语法里）
GLOBAL_BANNED_RE = re.compile(
    "[\u3000-\u303F"      # 中文标点：，。：；、（）《》【】「」等
    "\uFF00-\uFF65"       # 全角字符
    "\u2460-\u24FF"       # ① ② ⑪
    "\u2190-\u21FF"       # 箭头 →
    "\u2018-\u201F"       # 弯引号 ‘ ’ “ ”
    "\u2026\u00D7\u00B7\u2264\u2265\u2212\u00B1]"
    "|[;~@]"              # 分号 / 波浪号 / @
)

# 标签里额外不能出现的字符（在语法里有别的含义）
LABEL_BANNED = set("()[]{}|")

QUOTED_RE = re.compile(r'"[^"\n]*"')

LABEL_RES = (
    re.compile(r"\[([^\]\n]*)\]"),
    re.compile(r"\{([^}\n]*)\}"),
    re.compile(r"\(([^)\n]*)\)"),
    re.compile(r"\|([^|\n]*)\|"),
    re.compile(r"--\s*([^-][^|\n]*?)\s*-->"),
)

# (正则, 名称, 改法, 级别)
FEATURE_RES = (
    (re.compile(r"^\s*style\s+\S+"), "style 上色", "老版本能认，但有的渲染器会丢掉颜色；用加粗或文字区分重点更稳", "WARN"),
    (re.compile(r"^\s*classDef\b"), "classDef", "同上，建议删掉", "WARN"),
    (re.compile(r"^\s*class\s+\S+\s+\S+"), "class", "同上，建议删掉", "WARN"),
    (re.compile(r"^\s*subgraph\b"), "subgraph 分组", "mermaid 8.4+ 才有；把组名写进节点文字更稳", "WARN"),
    (re.compile(r"^\s*(click|linkStyle)\b"), "click/linkStyle", "删掉", "WARN"),
    (re.compile(r"%%\{"), "init 指令", "删掉", "ERROR"),
    (re.compile(r"<br\s*/?>", re.I), "<br/> 换行", "mermaid 7.1+ 能认，但个别编辑器会转义；改成一行的空格，细节放到图下面的列表里", "WARN"),
    (re.compile(r"&(?!amp;|lt;|gt;|#\d+;)"), "& 号", "老版本不支持 & 并列，也可能被当成 HTML 实体；拆成两条边", "WARN"),
)

BAR_ROW_RE = re.compile(
    r"^\|\s*(?P<name>.+?)\s*\|\s*(?P<val>\*{0,2}[\d.]+\*{0,2})\s*\|\s*(?P<bar>\*{0,2}█+\*{0,2})\s*\|"
)
SCALE_RE = re.compile(
    r"(?:从\s*(?P<base>[\d.]+)\s*起算[，,、]?\s*)?每格\s*(?P<step>[\d.]+)"
)


class Report:
    def __init__(self, path):
        self.path = path
        self.errors = 0
        self.warns = 0

    def add(self, line_no, level, msg, fix=""):
        if level == "ERROR":
            self.errors += 1
        else:
            self.warns += 1
        tail = f" -> {fix}" if fix else ""
        where = f"第 {line_no} 行" if line_no else "文件级"
        print(f"  [{level}] {where} {msg}{tail}")


def find_blocks(lines):
    """返回 [(代码块开始行号, 块内各行)]，行号从 1 开始。"""
    blocks = []
    i = 0
    while i < len(lines):
        head = lines[i].strip()
        if head.startswith("```mermaid") or head.startswith("~~~mermaid"):
            fence = head[:3]
            j = i + 1
            while j < len(lines) and lines[j].strip() not in ("```", "~~~"):
                j += 1
            blocks.append((i + 1, lines[i + 1 : j]))
            i = j + 1
        else:
            i += 1
    return blocks


def check_block(rep, start_line, body):
    first = next((k for k, ln in enumerate(body) if ln.strip()), None)
    if first is None:
        rep.add(start_line, "ERROR", "空的 mermaid 块", "删掉这个代码块")
        return

    head = body[first].strip()
    keyword = head.split()[0] if head.split() else ""
    if keyword in BAD_TYPES:
        rep.add(start_line + first + 1, "ERROR", f"图表类型 {keyword} 在老环境里显示不出来", BAD_TYPES[keyword])
    elif keyword in SAFE_TYPES:
        if keyword == "graph" and not re.match(r"^graph\s+(LR|RL|TB|BT)$", head):
            rep.add(start_line + first + 1, "ERROR", f"方向写法不规范：{head}", "改成 graph LR / graph TB 这类写法")
    elif keyword in VERSIONED_TYPES:
        rep.add(start_line + first + 1, "WARN", f"图表类型 {keyword} 需要 {VERSIONED_TYPES[keyword]}", "目标编辑器不确定时改用表格")
    else:
        rep.add(start_line + first + 1, "ERROR", f"未知或不兼容的图表类型 {keyword}", "只用 graph / sequenceDiagram / classDiagram / gantt")

    quote_lines = []
    for k, raw in enumerate(body):
        line_no = start_line + k + 1
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        if re.search(r"[\u00A0\u200B-\u200D\uFEFF\u3000]", line):
            rep.add(line_no, "ERROR", "含不换行空格或零宽字符", "删掉重打这一行")
            continue
        if line[:1] in (" ", "\t"):
            rep.add(line_no, "ERROR", "行首有空白", "这一行顶格写，缩进会被某些编辑器改成 &#160;，图就不渲染了")
        if "\t" in line:
            rep.add(line_no, "ERROR", "含制表符", "改成空格")

        for rx, name, fix, level in FEATURE_RES:
            if rx.search(line):
                rep.add(line_no, level, f"用了 {name}", fix)

        # 引号内的文字单独看：老版本 7.1+ 都能解析，只是编辑器可能把引号转义
        if QUOTED_RE.search(line):
            quote_lines.append(line_no)
        bare = QUOTED_RE.sub("", line)

        bad_chars = sorted(set(GLOBAL_BANNED_RE.findall(bare)))
        if bad_chars:
            shown = " ".join(c for c in bad_chars if c.strip())
            if keyword == "sequenceDiagram":
                rep.add(line_no, "WARN", f"消息文字里有标点 {shown}", "实测 sequenceDiagram 消息可以带中文标点，但换成空格最稳")
            else:
                rep.add(line_no, "ERROR", f"含老版本会报错或卡死的字符 {shown}", "换成空格，或改写这句话")

        if keyword == "graph":
            texts = []
            for rx in LABEL_RES:
                texts.extend(rx.findall(bare))
            for t in texts:
                bad = sorted({c for c in t if c in LABEL_BANNED})
                if bad:
                    shown = " ".join(bad)
                    rep.add(line_no, "ERROR", f"标签里有会破坏语法的字符 {shown}", "删掉这些字符或换成空格")

    if quote_lines:
        shown = "、".join(str(n) for n in quote_lines[:6])
        more = "" if len(quote_lines) <= 6 else f" 等 {len(quote_lines)} 处"
        rep.add(quote_lines[0], "WARN", f"标签用了引号（第 {shown}{more}）",
                "标准 mermaid 7.1+ 都支持，但个别编辑器会把引号转义成 &quot;；去掉引号更稳")


def check_bar_tables(rep, lines):
    """每张带 █ 的表格，用表格上方那行"条长从 X 起算，每格 Y"核对条长。"""
    idx = 0
    while idx < len(lines):
        if not lines[idx].startswith("|"):
            idx += 1
            continue
        table_start = idx
        while idx < len(lines) and lines[idx].startswith("|"):
            idx += 1

        scale = None
        for back in range(table_start - 1, max(-1, table_start - 6), -1):
            s = SCALE_RE.search(lines[back])
            if s:
                base = float(s.group("base")) if s.group("base") else 0.0
                scale = (base, float(s.group("step")))
                break
            if lines[back].strip().startswith("|"):
                break

        for r in range(table_start, idx):
            m = BAR_ROW_RE.match(lines[r].rstrip("\r"))
            if not m:
                continue
            name = m.group("name").replace("*", "").strip()
            value = float(m.group("val").replace("*", ""))
            bars = len(m.group("bar").replace("*", ""))
            if scale is None:
                rep.add(r + 1, "WARN", f"条形表格 {name} 上方没写换算规则", "加一行：条长从 X 起算，每格 Y")
                continue
            base, step = scale
            expect = round((value - base) / step)
            if expect < 1:
                rep.add(r + 1, "WARN", f"{name} 的数值 {value} 低于起算值 {base}", "把起算值改小，或去掉这一行")
            elif expect != bars:
                rep.add(r + 1, "ERROR", f"条形长度不对：{value} 应为 {expect} 格，实际 {bars} 格", f"改成 {'█' * expect}")


def check_file(path):
    p = Path(path)
    if not p.exists():
        print(f"找不到文件: {path}")
        return 1
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.split("\n")
    rep = Report(p)
    print(f"{p.name}")
    blocks = find_blocks(lines)
    if not blocks:
        print("  没有 mermaid 代码块")
    for start, body in blocks:
        check_block(rep, start, body)
    check_bar_tables(rep, lines)
    if not rep.errors and not rep.warns:
        print("  通过")
    print(f"  {len(blocks)} 个 mermaid 块，{rep.errors} 个 ERROR，{rep.warns} 个 WARN")
    return 1 if rep.errors else 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    code = 0
    for arg in sys.argv[1:]:
        code |= check_file(arg)
        print()
    return code


if __name__ == "__main__":
    sys.exit(main())
