"""
热点抓取模块（稳定版）
直连官方页面/API，无需第三方聚合站，避免 DNS 失败问题。

数据源（按优先级）：
1. 百度热搜（官方页面爬取）— 稳定性最高
2. 今日头条热榜（官方 JSON API）— 稳定性高
3. 微博热搜（移动版 API）— 备用
4. DailyHotApi 聚合站 — 备用（依赖第三方部署）
5. 季节性种子话题 — 最终兜底
"""
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from datetime import datetime
import json
import config


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


# ============ 数据源 1: 百度热搜（官方页面，最稳定）============

def fetch_baidu() -> List[Dict[str, Any]]:
    """抓取百度热搜官方页面，返回标准化列表。"""
    try:
        r = requests.get('https://top.baidu.com/board?tab=realtime',
                         headers=HEADERS, timeout=15)
        r.raise_for_status()
        r.encoding = 'utf-8'
    except Exception as e:
        print(f"[热点] 百度热搜抓取失败: {e}")
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    items = soup.select('.category-wrap_iQLoo')
    result = []
    for item in items:
        title_el = item.select_one('.c-single-text-ellipsis')
        hot_el = item.select_one('.hot-index_1Bl1a')
        desc_el = item.select_one('.hot-desc_1m_ji')
        title = title_el.text.strip() if title_el else ''
        if not title:
            continue
        result.append({
            "title": title,
            "hot": hot_el.text.strip() if hot_el else "",
            "url": "",
            "source": "baidu",
            "desc": desc_el.text.strip() if desc_el else "",
        })
    print(f"[热点] 百度热搜: 抓到 {len(result)} 条")
    return result


# ============ 数据源 2: 今日头条热榜（官方 JSON API）============

def fetch_toutiao() -> List[Dict[str, Any]]:
    """抓取今日头条热榜官方 API，返回标准化列表。"""
    try:
        r = requests.get(
            'https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc',
            headers=HEADERS, timeout=15
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[热点] 今日头条抓取失败: {e}")
        return []

    result = []
    for item in data.get('data', []):
        title = item.get('Title', '')
        if not title:
            continue
        result.append({
            "title": title,
            "hot": str(item.get('HotValue', '')),
            "url": item.get('Url', ''),
            "source": "toutiao",
            "desc": item.get('Label', ''),
        })
    print(f"[热点] 今日头条: 抓到 {len(result)} 条")
    return result


# ============ 数据源 3: 微博热搜（移动版 API）============

def fetch_weibo() -> List[Dict[str, Any]]:
    """抓取微博热搜移动版 API。"""
    try:
        r = requests.get(
            'https://m.weibo.cn/api/container/getIndex',
            params={'containerid': '106003type%3D25%26t%3D3%26disable_hot%3D1%26filter_type%3Drealtimehot'},
            headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)'},
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[热点] 微博热搜抓取失败: {e}")
        return []

    result = []
    cards = data.get('data', {}).get('cards', [])
    for card in cards:
        for item in card.get('card_group', []):
            desc = item.get('desc', '')
            if desc and item.get('desc_extr'):  # 有热度的才是热搜
                result.append({
                    "title": desc,
                    "hot": str(item.get('desc_extr', '')),
                    "url": item.get('scheme', ''),
                    "source": "weibo",
                    "desc": "",
                })
                if len(result) >= 30:
                    break
    print(f"[热点] 微博热搜: 抓到 {len(result)} 条")
    return result


# ============ 数据源 4: DailyHotApi 聚合站（备用）============

def fetch_dailyhot(source: str) -> List[Dict[str, Any]]:
    """从 DailyHotApi 聚合站抓取（在 Streamlit Cloud 环境可能可用）。"""
    base = config.DAILYHOT_BASE
    url = f"{base.rstrip('/')}/{source}"
    try:
        r = requests.get(url, timeout=10, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[热点] DailyHotApi/{source} 抓取失败: {e}")
        return []

    items = data.get("data", []) if isinstance(data, dict) else data
    result = []
    for item in items[:20]:
        result.append({
            "title": item.get("title") or item.get("name", ""),
            "hot": str(item.get("hot") or item.get("hotValue", "")),
            "url": item.get("url") or item.get("mobileUrl", ""),
            "source": source,
            "desc": "",
        })
    return result


# ============ 聚合抓取 ============

def fetch_all_hot_topics() -> Dict[str, Any]:
    """
    聚合抓取所有数据源，按优先级尝试，至少保证一个源成功。
    返回结构：
    {
      "date": "2026-07-19",
      "fetched_at": "...",
      "sources_used": ["baidu", "toutiao"],
      "topics": [...]
    }
    """
    print("[热点] 开始抓取多源热点...")

    # 按优先级抓取
    all_topics = []
    sources_used = []

    # 源1: 百度热搜（最稳定）
    baidu = fetch_baidu()
    if baidu:
        all_topics.extend(baidu)
        sources_used.append("baidu")

    # 源2: 今日头条热榜
    toutiao = fetch_toutiao()
    if toutiao:
        all_topics.extend(toutiao)
        sources_used.append("toutiao")

    # 源3: 微博热搜（备用，可能失败）
    if len(all_topics) < 30:
        weibo = fetch_weibo()
        if weibo:
            all_topics.extend(weibo)
            sources_used.append("weibo")

    # 源4: DailyHotApi（备用，沙箱环境可能 DNS 失败）
    if len(all_topics) < 20:
        for src in ["zhihu", "douyin", "bilibili"]:
            items = fetch_dailyhot(src)
            if items:
                all_topics.extend(items)
                sources_used.append(src)
                if len(all_topics) >= 40:
                    break

    print(f"[热点] 共抓到 {len(all_topics)} 条，使用源: {sources_used}")

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "sources_used": sources_used,
        "topics": all_topics,
    }


def fallback_topics() -> List[Dict[str, Any]]:
    """
    最终兜底方案：当所有外部源都连不上时，返回季节性种子话题。
    理论上百度热搜几乎不会挂，这个函数只是最后保险。
    """
    now = datetime.now()
    month = now.month
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
    return [{"title": s, "hot": "fallback", "url": "", "source": "fallback", "desc": ""} for s in seeds]


def keyword_filter(topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    规则预过滤：剔除明显不适合做冷知识科普的热点。
    """
    blacklist = [
        "出轨", "离婚", "恋情", "官宣", "结婚", "分手", "baby", "网红",
        "直播带货", "粉丝", "应援", "塌房", "番位",
    ]
    whitelist = [
        "发现", "首次", "突破", "研究", "科学", "技术", "宇宙", "病毒",
        "动物", "植物", "历史", "文物", "考古", "气象", "地质", "化学",
        "物理", "生物", "医学", "太空", "深海", "发明", "原理", "现象",
        "机器人", "AI", "人工智能", "火箭", "卫星",
    ]

    filtered = []
    for t in topics:
        title = t["title"]
        if any(k in title for k in blacklist):
            continue
        white_hits = sum(1 for k in whitelist if k in title)
        t["science_score"] = white_hits
        filtered.append(t)

    filtered.sort(key=lambda x: x["science_score"], reverse=True)
    return filtered


if __name__ == "__main__":
    result = fetch_all_hot_topics()
    print(f"\n=== {result['date']} 热点抓取结果 ===")
    print(f"使用源: {result['sources_used']}")
    print(f"共 {len(result['topics'])} 条\n")
    for i, t in enumerate(result["topics"][:15], 1):
        print(f"{i:2d}. [{t['source']:8s}] {t['title'][:40]}  (热度: {t['hot']})")

    print("\n=== 规则过滤后（Top 10）===")
    filtered = keyword_filter(result["topics"])
    for i, t in enumerate(filtered[:10], 1):
        print(f"{i:2d}. [{t['source']:8s}] {t['title'][:40]}  (科普分: {t['science_score']})")
