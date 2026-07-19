"""
素材抓取模块
数据源：Pexels Videos API + Pixabay Video API
都是 CC0 / 免版税协议，可商用二创。

=== Pexels Videos API ===
- 文档：https://www.pexels.com/api/documentation/#videos-search
- 鉴权：Header Authorization: {API_KEY}（必须配置，匿名调用带筛选参数会返回 401）
- 端点（新版，推荐）：GET https://api.pexels.com/v1/videos/search
- 端点（旧版，即将废弃）：GET https://api.pexels.com/videos/search
- 关键参数：query, orientation, size, locale, page, per_page
  注意：search 端点不支持 min_duration/max_duration，需客户端过滤
- 限流：免费账户 200 req/h

=== Pixabay Video API ===
- 文档：https://pixabay.com/api/videos/
- 鉴权：Query param key={API_KEY}
- 端点：GET https://pixabay.com/api/videos/
- 关键参数：q, video_type, category, min_width, per_page
- 限流：100 req/min
"""
import os
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import config


# ===================== 合规过滤（Pexels/Pixabay 内容使用条款）=====================

# 涉及可识别人物的关键词 → 规则3：不能以不道德或非法方式使用涉及可识别人物的内容
# 涉及商标/品牌的关键词 → 规则2：含可识别商标标志的内容不得用于商业目的
# 涉及误导性内容的关键词 → 规则4：不能以误导或欺骗方式使用
HUMAN_RELATED_KEYWORDS = [
    "face", "portrait", "selfie", "person face", "celebrity", "actor",
    "actress", "politician", "famous person", "crowd face",
    "明星", "人脸", "肖像", "自拍照",
]

BRAND_RELATED_KEYWORDS = [
    "logo", "brand", "trademark", "coca cola", "nike", "adidas", "apple logo",
    "mcdonalds", "starbucks", "brand name", "product label",
    "商标", "品牌", "标志",
]

MISLEADING_RELATED_KEYWORDS = [
    "fake", "deceptive", "misleading", "scam", "fraud",
    "medical claim", "cure", "miracle", "guaranteed",
    "虚假", "欺骗", "误导", "神效", "包治",
]


def is_compliant_clip(clip: Dict[str, Any], search_query: str = "") -> tuple:
    """
    检查素材是否符合 Pexels/Pixabay 内容使用条款。
    返回 (是否合规, 原因说明)。
    """
    # 合并搜索词和素材自身字段做检查
    check_text = (
        f"{search_query} "
        f"{clip.get('search_query', '')} "
        f"{clip.get('tags', '')} "
        f"{clip.get('page_url', '')} "
        f"{clip.get('preview_url', '')} "
        f"{clip.get('download_url', '')}"
    ).lower()

    # 规则3：涉及可识别人物的内容需谨慎
    for kw in HUMAN_RELATED_KEYWORDS:
        if kw.lower() in check_text:
            return False, f"涉及可识别人物（关键词：{kw}），按条款3需谨慎使用"

    # 规则2：含可识别商标/品牌的内容不得用于商业目的
    for kw in BRAND_RELATED_KEYWORDS:
        if kw.lower() in check_text:
            return False, f"含可识别商标/品牌（关键词：{kw}），按条款2不得用于商业目的"

    # 规则4：不能以误导或欺骗方式使用
    for kw in MISLEADING_RELATED_KEYWORDS:
        if kw.lower() in check_text:
            return False, f"可能涉及误导性内容（关键词：{kw}），按条款4禁止"

    return True, "合规"


def filter_compliant_clips(clips: List[Dict[str, Any]], search_query: str = "") -> List[Dict[str, Any]]:
    """过滤出符合使用条款的素材。"""
    compliant = []
    for clip in clips:
        ok, reason = is_compliant_clip(clip, search_query)
        if ok:
            compliant.append(clip)
        else:
            print(f"[合规] 过滤掉素材 #{clip.get('id','?')}: {reason}")
    return compliant


# ===================== API Key 清洗 =====================

def _sanitize_key(value: str) -> str:
    """
    清除 API Key 中的非 ASCII 字符。
    防止从 Word/PDF 复制的 Key 含隐藏字符导致请求失败。
    """
    if not value:
        return value
    cleaned = value.strip()
    invisible = {"\ufeff", "\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u00ad"}
    for ch in invisible:
        cleaned = cleaned.replace(ch, "")
    return "".join(c for c in cleaned if 0x20 <= ord(c) <= 0x7E)


# ===================== Pexels =====================

def pexels_search(query: str, per_page: int = 5) -> List[Dict[str, Any]]:
    """
    搜索 Pexels 视频，返回标准化结果列表。
    新版端点：https://api.pexels.com/v1/videos/search（旧版 /videos/ 即将废弃）
    必须配置 PEXELS_API_KEY。匿名调用只能简单查询，带 orientation/size 筛选时返回 401。
    """
    pexels_key = _sanitize_key(config.PEXELS_API_KEY)
    if not pexels_key:
        print("[素材] Pexels API Key 未配置，跳过（新版端点要求鉴权）")
        return []

    # 新版端点（官方推荐）
    url = "https://api.pexels.com/v1/videos/search"
    params = {
        "query": query,
        "orientation": config.ORIENTATION,
        "size": "large",
        "per_page": min(per_page, 80),
    }
    # 注意：search 端点不支持 min_duration/max_duration 参数（只有 popular 端点支持）
    # 所以这里不再传时长过滤，改为拿到结果后在客户端过滤
    headers = {"Authorization": pexels_key}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[素材] Pexels 搜索 '{query}' 失败: {e}")
        return []

    results = []
    for v in data.get("videos", []):
        # 客户端时长过滤（search 端点不支持服务端时长过滤）
        duration = v.get("duration", 0)
        if duration < config.MIN_CLIP_DURATION or duration > config.MAX_CLIP_DURATION:
            continue
        # 选最大分辨率的文件
        best_file = max(
            v.get("video_files", []),
            key=lambda f: f.get("width", 0) * f.get("height", 0),
            default=None,
        )
        if not best_file or best_file.get("width", 0) < config.MIN_WIDTH:
            continue
        results.append({
            "source": "pexels",
            "id": v["id"],
            "width": best_file["width"],
            "height": best_file["height"],
            "duration": duration,
            "download_url": best_file["link"],
            "preview_url": v.get("image", ""),
            "page_url": v.get("url", ""),
            "search_query": query,
            "tags": "",  # Pexels search 端点不返回 tags，留空
        })
    return results


# ===================== Pixabay =====================

def pixabay_search(query: str, per_page: int = 5) -> List[Dict[str, Any]]:
    """搜索 Pixabay 视频，返回标准化结果列表。"""
    pixabay_key = _sanitize_key(config.PIXABAY_API_KEY)
    if not pixabay_key:
        print("[素材] Pixabay API Key 未配置，跳过")
        return []

    url = "https://pixabay.com/api/videos/"
    # Pixabay 分类映射（query 是自由文本，category 是枚举）
    params = {
        "key": pixabay_key,
        "q": query,
        "video_type": "all",
        "per_page": min(per_page, 200),
        "min_width": config.MIN_WIDTH,
        "safesearch": "true",
        "lang": "en",  # 英文搜索结果更丰富
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[素材] Pixabay 搜索 '{query}' 失败: {e}")
        return []

    results = []
    for v in data.get("hits", []):
        # Pixabay 返回 multiple resolutions: large/medium/small/tiny
        videos = v.get("videos", {})
        best_res = videos.get("large") or videos.get("medium") or videos.get("small")
        if not best_res:
            continue
        if best_res.get("width", 0) < config.MIN_WIDTH:
            continue
        # 时长过滤
        duration = v.get("duration", 0)
        if duration < config.MIN_CLIP_DURATION or duration > config.MAX_CLIP_DURATION:
            continue
        results.append({
            "source": "pixabay",
            "id": v["id"],
            "width": best_res["width"],
            "height": best_res["height"],
            "duration": duration,
            "download_url": best_res["url"],
            "preview_url": v.get("previewImage", v.get("userImageURL", "")),
            "page_url": v.get("pageURL", ""),
            "search_query": query,
            "tags": v.get("tags", ""),  # Pixabay 返回逗号分隔的标签字符串，用于合规检查
        })
    return results


# ===================== 聚合搜索 + 下载 =====================

def search_clips(query: str, per_source: int = 3) -> List[Dict[str, Any]]:
    """
    双源聚合搜索，合并去重，按分辨率降序。
    自动过滤不合规素材（Pexels/Pixabay 内容使用条款）。
    """
    pexels = pexels_search(query, per_page=per_source)
    pixabay = pixabay_search(query, per_page=per_source)
    merged = pexels + pixabay

    # 合规过滤（Pexels/Pixabay 内容使用条款 5 条禁止使用规则）
    total_before = len(merged)
    merged = filter_compliant_clips(merged, query)
    total_after = len(merged)
    if total_before > total_after:
        print(f"[合规] '{query}': 过滤掉 {total_before - total_after} 个不合规素材，剩余 {total_after} 个")

    # 按分辨率（像素总数）降序
    merged.sort(key=lambda x: x["width"] * x["height"], reverse=True)
    return merged


def download_clip(clip: Dict[str, Any], save_path: Path) -> bool:
    """下载单个视频到本地。返回是否成功。"""
    save_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(clip["download_url"], stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        clip["local_path"] = str(save_path)
        print(f"[素材] 下载完成: {save_path.name} ({clip['source']}, {clip['width']}x{clip['height']})")
        return True
    except Exception as e:
        print(f"[素材] 下载失败 {clip['download_url']}: {e}")
        return False


def fetch_clips_for_shot(
    shot_index: int,
    keywords: List[str],
    clips_dir: Path,
    max_clips: int = 1,
) -> List[Dict[str, Any]]:
    """
    为单个分镜抓取并下载素材。
    keywords: 该分镜的多个搜索关键词（AI 生成脚本时会给出）
    返回已下载的素材信息列表（通常 1 个，失败时可能 0 个）。
    """
    # 对每个关键词都搜一遍，取合集（search_clips 已内置合规过滤）
    all_candidates = []
    for kw in keywords:
        candidates = search_clips(kw, per_source=config.CLIPS_PER_SHOT)
        all_candidates.extend(candidates)
        if len(all_candidates) >= 15:
            break  # 合规候选够多了

    if not all_candidates:
        print(f"[素材] 分镜 {shot_index}: 所有关键词均无合规素材 {keywords}")
        print(f"[素材]   → 所有结果被合规过滤（人物/商标/误导），该分镜将无素材")
        return []

    # 选最好的 max_clips 个
    selected = all_candidates[:max_clips]
    downloaded = []
    for i, clip in enumerate(selected):
        ext = "mp4"
        filename = f"shot{shot_index:02d}_{clip['source']}_{clip['id']}.{ext}"
        save_path = clips_dir / filename
        if download_clip(clip, save_path):
            downloaded.append(clip)
    return downloaded


def fetch_all_clips(shots: List[Dict[str, Any]], clips_dir: Path) -> Dict[int, List[Dict[str, Any]]]:
    """
    并发为所有分镜抓取素材。
    shots: [{"index": 1, "keywords": ["ocean wave", "sea"], ...}, ...]
    返回 {shot_index: [clip_info, ...]}
    """
    results: Dict[int, List[Dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_DOWNLOADS) as pool:
        futures = {
            pool.submit(fetch_clips_for_shot, s["index"], s["keywords"], clips_dir, 1): s["index"]
            for s in shots
        }
        for fut in as_completed(futures):
            shot_idx = futures[fut]
            try:
                results[shot_idx] = fut.result()
            except Exception as e:
                print(f"[素材] 分镜 {shot_idx} 抓取异常: {e}")
                results[shot_idx] = []
    return results


# ===================== BGM 推荐（不下载，只给链接）=====================

def recommend_bgm(mood: str = "curious") -> List[Dict[str, Any]]:
    """
    推荐 CC0 配乐。这里不调 API（Mixkit 无开放 API），直接给手动挑选的高频站点链接。
    用户可去对应站点按 mood 关键词搜索下载。
    """
    bgm_sources = [
        {
            "name": "Mixkit Music",
            "url": f"https://mixkit.co/free-stock-music/tag/{mood}/",
            "license": "Mixkit Free License（可商用，无需署名）",
            "note": f"直接访问上方链接，已是 '{mood}' 标签的曲库",
        },
        {
            "name": "Audionautix",
            "url": f"https://audionautix.com/?genre=&mood={mood}&tempo=",
            "license": "CC0（100% 免版权）",
            "note": f"按 Mood={mood} 筛选，全曲可商用",
        },
        {
            "name": "Pixabay Music",
            "url": f"https://pixabay.com/music/search/mood/{mood}/",
            "license": "Pixabay Content License（可商用）",
            "note": f"已是 '{mood}' mood 搜索结果页",
        },
        {
            "name": "Free Music Archive (FMA)",
            "url": f"https://freemusicarchive.org/search?adv=1&quicksearch={mood}",
            "license": "混合协议，需看单曲授权",
            "note": f"已用 '{mood}' 关键词搜索，选 CC0 / CC-BY 曲目",
        },
    ]
    return bgm_sources


if __name__ == "__main__":
    # 自测：搜索 "ocean wave" 并下载 1 个到 /tmp
    print("=== 测试 Pexels 搜索 ===")
    pexels_results = pexels_search("ocean wave", per_page=3)
    for r in pexels_results:
        print(f"  {r['source']} #{r['id']} {r['width']}x{r['height']} {r['duration']}s")

    print("\n=== 测试 Pixabay 搜索 ===")
    pixabay_results = pixabay_search("ocean wave", per_page=3)
    for r in pixabay_results:
        print(f"  {r['source']} #{r['id']} {r['width']}x{r['height']} {r['duration']}s")

    print("\n=== 测试下载 ===")
    if pexels_results:
        test_dir = Path("/tmp/test_clips")
        download_clip(pexels_results[0], test_dir / "test.mp4")
