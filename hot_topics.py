"""
热点抓取模块
数据源：DailyHotApi（开源聚合，支持抖音/微博/知乎/百度/头条等 50+ 平台）
项目地址：https://github.com/imsyy/DailyHotApi

DailyHotApi 返回结构示例（以 /douyin 为例）：
{
  "code": 200,
  "name": "抖音热搜",
  "data": [
    {"title": "热点标题", "hot": "1234万", "url": "...", "mobileUrl": "..."},
    ...
  ]
}

备选数据源（无需自部署）：
- 韩小韩 API：https://api.vvhan.com/api/hotlist/{type}
- 今日热榜官方：https://www.tophubdata.com/
"""
import requests
from typing import List, Dict, Any
from datetime import datetime
import config


def fetch_one_source(source: str, base: str = config.DAILYHOT_BASE) -> List[Dict[str, Any]]:
    """
    抓取单个平台热榜。
    source: douyin / weibo / zhihu / baidu / toutiao / bilibili / ...
    返回标准化后的列表：[{title, hot, url, source}]
    """
    # DailyHotApi 路径：{base}/{source}
    url = f"{base.rstrip('/')}/{source}"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[热点] {source} 抓取失败: {e}")
        # 降级：尝试 vvhan 备用接口
        try:
            backup = f"https://api.vvhan.com/api/hotlist/{source}"
            resp = requests.get(backup, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            data = resp.json()
        except Exception as e2:
            print(f"[热点] {source} 备用接口也失败: {e2}")
            return []

    items = data.get("data", []) if isinstance(data, dict) else data
    result = []
    for item in items[:20]:  # 每个平台只取 Top 20
        result.append({
            "title": item.get("title") or item.get("name", ""),
            "hot": item.get("hot") or item.get("hotValue", ""),
            "url": item.get("url") or item.get("mobileUrl", ""),
            "source": source,
        })
    return result


def fetch_all_hot_topics() -> Dict[str, Any]:
    """
    抓取所有配置平台的热榜，返回聚合结果。
    返回结构：
    {
      "date": "2026-07-19",
      "fetched_at": "2026-07-19T15:30:00",
      "topics": [
        {"title": "...", "hot": "...", "url": "...", "source": "douyin"},
        ...
      ]
    }
    """
    all_topics = []
    for source in config.HOT_SOURCES:
        items = fetch_one_source(source)
        all_topics.extend(items)
        print(f"[热点] {source}: 抓到 {len(items)} 条")
    print(f"[热点] 共抓取 {len(all_topics)} 条热点")

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "topics": all_topics,
    }


def fallback_topics() -> List[Dict[str, Any]]:
    """
    降级方案：当所有外部热点源都连不上时，返回一组季节性/普适冷知识种子话题。
    这些话题不依赖当日热点，但 AI 仍可基于它们生成选题，保证闭环可运行。
    用户在自己机器上配好 DailyHotApi 后会自动用真实热点覆盖。
    """
    now = datetime.now()
    month = now.month
    # 按季节给不同种子
    seasonal = {
        3: "春季万物复苏", 4: "春季万物复苏", 5: "春季万物复苏",
        6: "夏季高温现象", 7: "夏季高温现象", 8: "夏季高温现象",
        9: "秋季落叶迁徙", 10: "秋季落叶迁徙", 11: "秋季落叶迁徙",
        12: "冬季严寒现象", 1: "冬季严寒现象", 2: "冬季严寒现象",
    }
    theme = seasonal.get(month, "日常生活现象")
    seeds = [
        f"{theme}背后的科学原理",
        "深海生物为什么长得那么奇怪",
        "人体每天在做的10个你不知道的事",
        "日常用品的设计暗藏的物理学",
        "宇宙中最反常识的现象",
        "动物界违背常理的生存策略",
        "食物背后的化学反应",
        "古代发明比现代还先进的瞬间",
        "天气现象的科学解释",
        "大脑骗你的那些视觉错觉",
    ]
    return [{"title": s, "hot": "fallback", "url": "", "source": "fallback"} for s in seeds]


def keyword_filter(topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    规则预过滤：剔除明显不适合做冷知识科普的热点（娱乐八卦、明星、纯事件性新闻）。
    这一步在调用 LLM 前先做，省 token。
    """
    # 黑名单关键词
    blacklist = [
        "出轨", "离婚", "恋情", "官宣", "结婚", "分手", "baby", "网红",
        "直播带货", "粉丝", "应援", "塌房", "番位",
    ]
    # 白名单关键词（含这些词的优先保留，更可能挖出冷知识角度）
    whitelist = [
        "发现", "首次", "突破", "研究", "科学", "技术", "宇宙", "病毒",
        "动物", "植物", "历史", "文物", "考古", "气象", "地质", "化学",
        "物理", "生物", "医学", "太空", "深海", "发明", "原理", "现象",
    ]

    filtered = []
    for t in topics:
        title = t["title"]
        # 命中黑名单直接跳过
        if any(k in title for k in blacklist):
            continue
        # 计算白名单命中数，用于排序
        white_hits = sum(1 for k in whitelist if k in title)
        t["science_score"] = white_hits
        filtered.append(t)

    # 白名单命中多的排前面
    filtered.sort(key=lambda x: x["science_score"], reverse=True)
    return filtered


if __name__ == "__main__":
    result = fetch_all_hot_topics()
    print(f"\n=== {result['date']} 热点抓取结果 ===")
    for i, t in enumerate(result["topics"][:15], 1):
        print(f"{i:2d}. [{t['source']}] {t['title']}  (热度: {t['hot']})")

    print("\n=== 规则预过滤后（Top 10）===")
    filtered = keyword_filter(result["topics"])
    for i, t in enumerate(filtered[:10], 1):
        print(f"{i:2d}. [{t['source']}] {t['title']}  (科普分: {t['science_score']})")
