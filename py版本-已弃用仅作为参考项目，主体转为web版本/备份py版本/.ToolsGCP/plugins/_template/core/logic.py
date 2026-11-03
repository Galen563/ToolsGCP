"""功能与逻辑算法

界面代码不写业务逻辑，全放这里 —— 好测试、好复用，界面换皮时不用动它。
下面两个函数是示例，换成你自己的业务即可。
"""

from collections import Counter


def categories_of(item: dict) -> list:
    """取一条资源的类别列表（兼容两种形态）

    ⚠️ `category` 从 schema 2.1.0 起是列表，老数据是逗号拼接的字符串，两种都要认。
    """
    value = (item or {}).get("category")
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value or "").replace("，", ",").replace("、", ",")
            .replace("；", ",").replace(";", ",").split(",") if p.strip()]



class Logic:
    """插件业务逻辑"""

    def __init__(self, context):
        self.context = context

    def resources(self) -> list:
        """拿到 ToolsGCP 的整个资源库"""
        return self.context.get_resources()

    def count_by_category(self) -> list:
        """按类别统计数量，返回 [(类别, 数量), ...]，多的在前"""
        counter = Counter()
        for item in self.resources():
            for name in categories_of(item) or ["其他"]:
                counter[name] += 1
        return counter.most_common()

    def count_by_tag(self, top: int = 12) -> list:
        """按标签统计，取前 top 个"""
        counter = Counter()
        for item in self.resources():
            for tag in item.get("tags") or []:
                counter[str(tag)] += 1
        return counter.most_common(top)

    def search(self, keyword: str) -> list:
        """在自己的逻辑里做一次搜索（大小写不敏感，匹配名称/简介/标签/编码）"""
        keyword = str(keyword or "").strip().lower()
        if not keyword:
            return []
        result = []
        for item in self.resources():
            haystack = " ".join([
                str(item.get("name", "")),
                str(item.get("description", "")),
                str(item.get("code", "")),
                # 关键词 = 类别 ∪ 标签（tags 里已不含类别值，两者都要带）
                " ".join(categories_of(item)),
                " ".join(str(t) for t in (item.get("tags") or [])),
            ]).lower()
            if keyword in haystack:
                result.append(item)
        return result

    def summary(self) -> dict:
        """整体概况，给首页用"""
        items = self.resources()
        return {
            "total": len(items),
            "categories": len({name for r in items for name in categories_of(r)}),
            "with_site": len([r for r in items if r.get("url")]),
            "with_repo": len([r for r in items if r.get("github")]),
        }
