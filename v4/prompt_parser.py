"""
prompt_parser.py - 解析 V3 prompter 生成的 prompt.txt
=====================================================
从 prompt.txt 提取 V4 内核所需的三部分:
  - role_text : ##role## 段(角色设定)
  - categories: ##意图库## 段解析出的全部意图, 每个含
                {label, name, l1(一级分组), definition, full_desc}
  - aux_text  : ##路由规则## ~ ##输出格式## 段(规则/约束/示例/输出格式),
                作为 Layer_2 的辅助信息原样复用, 保持与 V3 一致

注: prompt.txt 中 【意图x.y】 为意图头, 按头切分可拿到全部 32 类
    (规避 texts.txt 漏 ---SEP--- 致 2.10 缺失的问题)。
"""

import re
from pathlib import Path

LABEL_RE = re.compile(r"(【意图[\d.]+】)")
_GROUP_RE = re.compile(r"^[一二三四五六七八九十]+、(.+?)\(\d+个场景\)\s*$", re.MULTILINE)
_SECTION_RE = re.compile(r"^##(.+?)##\s*$", re.MULTILINE)


def _split_sections(text: str) -> dict[str, str]:
    """按 ##xxx## 标记切分, 返回 {段名: 段体(不含标记行)}。"""
    marks = list(_SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for i, m in enumerate(marks):
        name = m.group(1).strip()
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        sections[name] = text[start:end].strip()
    return sections


def _parse_categories(lib_text: str) -> list[dict]:
    """从意图库段解析出类别列表。

    每个类别块 = 从一个 【意图x.y】 头到下一个意图头(或段尾)。
    块尾可能粘连下一个分组头(如 '二、售前服务(10个场景)')与分隔线, 需切掉。
    一级分组 l1 取自该意图之前最近的分组头。
    """
    # 所有分组头位置 -> 分组名
    groups = [(m.start(), m.group(1).strip()) for m in _GROUP_RE.finditer(lib_text)]
    # 所有意图头位置
    intent_starts = [m.start() for m in LABEL_RE.finditer(lib_text)]

    cats: list[dict] = []
    for i, start in enumerate(intent_starts):
        end = intent_starts[i + 1] if i + 1 < len(intent_starts) else len(lib_text)
        block = lib_text[start:end]
        # 切掉块尾粘连的下一分组头 + 分隔线
        cut = re.search(r"\n\s*={3,}\s*\n\s*[一二三四五六七八九十]+、", block)
        if cut:
            block = block[: cut.start()]
        block = block.strip()
        if not block:
            continue

        lm = LABEL_RE.match(block)
        if not lm:
            continue
        label = lm.group(1)
        rest = block[lm.end():].strip()
        name = rest.split("\n", 1)[0].strip()
        dm = re.search(r"^定义：(.+)$", block, re.MULTILINE)
        definition = dm.group(1).strip() if dm else ""

        # l1 = 本意图之前最近的分组头
        l1 = ""
        for gpos, gname in groups:
            if gpos < start:
                l1 = gname
            else:
                break

        cats.append(
            {
                "label": label,
                "name": name,
                "l1": l1,
                "definition": definition,
                "full_desc": block,
            }
        )
    return cats


def parse_prompt(prompt_text: str) -> dict:
    """解析 prompt.txt 全文, 返回 {role_text, aux_text, categories, ...}。"""
    sections = _split_sections(prompt_text)

    role_text = "##role##\n" + sections.get("role", "")
    lib_text = sections.get("意图库", "")
    categories = _parse_categories(lib_text)

    # aux_text = 路由规则 + 约束 + samples + 输出格式 (V3 原样, Layer_2 复用)
    aux_parts = []
    for name in ("路由规则", "约束", "samples", "输出格式"):
        if name in sections:
            aux_parts.append(f"##{name}##\n{sections[name]}")
    aux_text = "\n\n".join(aux_parts)

    return {
        "role_text": role_text.strip(),
        "aux_text": aux_text.strip(),
        "categories": categories,
        "label_to_cat": {c["label"]: c for c in categories},
        "name_to_label": {c["name"]: c["label"] for c in categories},
    }


def parse_prompt_file(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return parse_prompt(f.read())


if __name__ == "__main__":
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else __file__.replace("prompt_parser.py", "prompt.txt")
    parsed = parse_prompt_file(p)
    print(f"role_text: {len(parsed['role_text'])} chars")
    print(f"aux_text:  {len(parsed['aux_text'])} chars")
    print(f"categories: {len(parsed['categories'])}")
    for c in parsed["categories"]:
        print(f"  {c['label']}{c['name']:<12} l1={c['l1']:<8} def={len(c['definition'])}字 full={len(c['full_desc'])}字")
