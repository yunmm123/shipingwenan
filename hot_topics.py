"""
热点抓取模块（多源稳定版）
直连官方页面/API，8 个数据源按优先级自动切换，保证热点丰富度。

数据源（按优先级）：
1. 百度热搜（官方页面爬取）— 稳定性最高
2. 今日头条热榜（官方 JSON API）— 稳定性高
3. 抖音热搜（官方 API）— 短视频热点
4. 知乎热榜（官方 API）— 深度话题
5. B站热搜（官方 API）— 年轻人热点
6. 澎湃新闻热榜（官方 API）— 时政社会
7. 豆瓣热门电影（官方 API）— 影视文娱
8. IT之家热榜（官方 API）— 科技数码
9. DailyHotApi 聚合站 — 备用
10. 季节性种子话题 — 最终兜底
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


# ============ 数据源 1: 百度热搜 ============

def fetch_baidu() -> List[Dict[str, Any]]:
    """百度热搜官方页面爬取。"""
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


# ============ 数据源 2: 今日头条热榜 ============

def fetch_toutiao() -> List[Dict[str, Any]]:
    """今日头条热榜官方 JSON API。"""
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


# ============ 数据源 3: 抖音热搜 ============

def fetch_douyin() -> List[Dict[str, Any]]:
    """抖音热搜官方 API。"""
    try:
        r = requests.get(
            'https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/',
            headers=HEADERS, timeout=15
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[热点] 抖音热搜抓取失败: {e}")
        return []

    result = []
    for item in data.get('word_list', []):
        title = item.get('word', '')
        if not title:
            continue
        result.append({
            "title": title,
            "hot": str(item.get('hot_value', '')),
            "url": "",
            "source": "douyin",
            "desc": "",
        })
    print(f"[热点] 抖音热搜: 抓到 {len(result)} 条")
    return result


# ============ 数据源 4: 知乎热榜 ============

def fetch_zhihu() -> List[Dict[str, Any]]:
    """知乎热榜官方 API。"""
    try:
        r = requests.get(
            'https://api.zhihu.com/topstory/hot-list?limit=50',
            headers=HEADERS, timeout=15
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[热点] 知乎热榜抓取失败: {e}")
        return []

    result = []
    for item in data.get('data', []):
        target = item.get('target', {})
        title = target.get('title', '')
        if not title:
            continue
        detail = item.get('detail_text', '')
        result.append({
            "title": title,
            "hot": detail,
            "url": target.get('url', ''),
            "source": "zhihu",
            "desc": target.get('excerpt', '')[:100],
        })
    print(f"[热点] 知乎热榜: 抓到 {len(result)} 条")
    return result


# ============ 数据源 5: B站热搜 ============

def fetch_bilibili() -> List[Dict[str, Any]]:
    """B站热搜官方 API。"""
    try:
        r = requests.get(
            'https://api.bilibili.com/x/web-interface/wbi/search/square?limit=30',
            headers={**HEADERS, 'Referer': 'https://www.bilibili.com'},
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[热点] B站热搜抓取失败: {e}")
        return []

    result = []
    trending = data.get('data', {}).get('trending', {})
    for item in trending.get('list', []):
        title = item.get('keyword', '')
        if not title:
            continue
        result.append({
            "title": title,
            "hot": str(item.get('hot_id', '')),
            "url": item.get('uri', ''),
            "source": "bilibili",
            "desc": "",
        })
    print(f"[热点] B站热搜: 抓到 {len(result)} 条")
    return result


# ============ 数据源 6: 澎湃新闻热榜 ============

def fetch_thepaper() -> List[Dict[str, Any]]:
    """澎湃新闻热榜官方 API。"""
    try:
        r = requests.get(
            'https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar',
            headers=HEADERS, timeout=15
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[热点] 澎湃热榜抓取失败: {e}")
        return []

    result = []
    hot_news = data.get('data', {}).get('hotNews', [])
    for item in hot_news:
        title = item.get('name', '')
        if not title:
            continue
        result.append({
            "title": title,
            "hot": str(item.get('nodeId', '')),
            "url": item.get('contId', ''),
            "source": "thepaper",
            "desc": "",
        })
    print(f"[热点] 澎湃热榜: 抓到 {len(result)} 条")
    return result


# ============ 数据源 7: 豆瓣热门电影 ============

def fetch_douban() -> List[Dict[str, Any]]:
    """豆瓣热门电影官方 API。"""
    try:
        r = requests.get(
            'https://movie.douban.com/j/search_subjects',
            params={'type': 'movie', 'tag': '热门', 'page_limit': 20, 'page_start': 0},
            headers=HEADERS, timeout=15
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[热点] 豆瓣电影抓取失败: {e}")
        return []

    result = []
    for item in data.get('subjects', []):
        title = item.get('title', '')
        if not title:
            continue
        result.append({
            "title": f"电影《{title}》评分{item.get('rate','?')}",
            "hot": item.get('rate', ''),
            "url": item.get('url', ''),
            "source": "douban",
            "desc": "",
        })
    print(f"[热点] 豆瓣电影: 抓到 {len(result)} 条")
    return result


# ============ 数据源 8: IT之家热榜 ============

def fetch_ithome() -> List[Dict[str, Any]]:
    """IT之家热榜官方 API。"""
    try:
        r = requests.get(
            'https://api.ithome.com/json/newslist/news?r=0',
            headers=HEADERS, timeout=15
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[热点] IT之家抓取失败: {e}")
        return []

    result = []
    toplist = data.get('toplist', []) if isinstance(data, dict) else []
    for item in toplist:
        title = item.get('title', '')
        if not title:
            continue
        result.append({
            "title": title,
            "hot": str(item.get('postid', '')),
            "url": item.get('url', ''),
            "source": "ithome",
            "desc": item.get('digest', '')[:100],
        })
    print(f"[热点] IT之家: 抓到 {len(result)} 条")
    return result


# ============ 数据源 9: DailyHotApi 聚合站（备用）============

def fetch_dailyhot(source: str) -> List[Dict[str, Any]]:
    """DailyHotApi 聚合站（备用）。"""
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
    聚合抓取所有数据源（8 个官方源 + 1 个备用聚合站）。
    每个源独立失败不影响其他源，至少保证 1 个源成功。
    """
    print("[热点] 开始抓取多源热点（8 个官方源）...")

    all_topics = []
    sources_used = []
    sources_failed = []

    # 8 个官方源，按优先级
    fetchers = [
        ("baidu", fetch_baidu),
        ("toutiao", fetch_toutiao),
        ("douyin", fetch_douyin),
        ("zhihu", fetch_zhihu),
        ("bilibili", fetch_bilibili),
        ("thepaper", fetch_thepaper),
        ("douban", fetch_douban),
        ("ithome", fetch_ithome),
    ]

    for name, fetcher in fetchers:
        try:
            items = fetcher()
            if items:
                all_topics.extend(items)
                sources_used.append(name)
            else:
                sources_failed.append(name)
        except Exception as e:
            print(f"[热点] {name} 异常: {e}")
            sources_failed.append(name)

    # 备用：DailyHotApi 聚合站（补抓平台）
    if len(all_topics) < 50:
        for src in ["weibo", "kuaishou"]:
            items = fetch_dailyhot(src)
            if items:
                all_topics.extend(items)
                sources_used.append(src)

    print(f"[热点] 共抓到 {len(all_topics)} 条")
    print(f"[热点] 成功源 ({len(sources_used)}): {sources_used}")
    if sources_failed:
        print(f"[热点] 失败源 ({len(sources_failed)}): {sources_failed}")

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "sources_used": sources_used,
        "sources_failed": sources_failed,
        "topics": all_topics,
    }


def fallback_topics() -> List[Dict[str, Any]]:
    """最终兜底方案：季节性种子话题。"""
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
    """规则预过滤：剔除不适合冷知识的热点，给科学相关热点加分。"""
    blacklist = [
        "出轨", "离婚", "恋情", "官宣", "结婚", "分手", "baby", "网红",
        "直播带货", "粉丝", "应援", "塌房", "番位",
    ]
    whitelist = [
        "发现", "首次", "突破", "研究", "科学", "技术", "宇宙", "病毒",
        "动物", "植物", "历史", "文物", "考古", "气象", "地质", "化学",
        "物理", "生物", "医学", "太空", "深海", "发明", "原理", "现象",
        "机器人", "AI", "人工智能", "火箭", "卫星", "芯片", "量子",
        "基因", "大脑", "神经", "免疫", "细胞",
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
    print(f"失败源: {result['sources_failed']}")
    print(f"共 {len(result['topics'])} 条\n")
    # 按来源分组统计
    from collections import Counter
    src_count = Counter(t['source'] for t in result['topics'])
    for src, count in src_count.most_common():
        print(f"  [{src:10s}] {count} 条")

    print("\n=== 各源 Top 3 ===")
    for src in result['sources_used']:
        print(f"\n[{src}]")
        src_topics = [t for t in result['topics'] if t['source'] == src][:3]
        for i, t in enumerate(src_topics, 1):
            print(f"  {i}. {t['title'][:40]}  (热度: {t['hot'][:15]})")
