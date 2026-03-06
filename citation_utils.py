import re
from typing import Dict, List, Set


def check_citations(text: str, ref_count: int) -> Dict[str, List[int]]:
    """
    简单检查正文中的引用编号是否与参考文献列表对齐。

    - 支持两种形式的引用标记：
      - [1]
      - [Source_ID: 1]
    - 返回：
      - used_ids: 正文中实际出现过的编号集合（排序后）
      - invalid_ids: 超出参考文献数量范围的编号
      - unreferenced_ids: 参考文献中从未在正文被引用的编号
    """
    pattern = re.compile(r"\[(?:Source_ID:\s*)?(\d+)\]")
    used: Set[int] = set()

    for match in pattern.finditer(text):
        try:
            idx = int(match.group(1))
        except ValueError:
            continue
        used.add(idx)

    used_ids = sorted(used)
    invalid_ids = sorted(i for i in used if i < 1 or i > ref_count)
    unreferenced_ids = sorted(i for i in range(1, ref_count + 1) if i not in used)

    return {
        "used_ids": used_ids,
        "invalid_ids": invalid_ids,
        "unreferenced_ids": unreferenced_ids,
    }

