"""
AI 选题与脚本生成模块
用 LLM（OpenAI 兼容接口）完成两步：
1. 热点 → 冷知识选题（Step 2 + Step 3）
2. 选题 → 分镜脚本（Step 4）

输出结构化 JSON，方便后续素材抓取模块直接消费。
"""
import json
from typing import List, Dict, Any
import config

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    OpenAI = None


def _get_client():
    if not HAS_OPENAI:
        raise RuntimeError("未安装 openai 包，请 pip install openai")
    if not config.LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY 未配置，请检查 .env")
    return OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_API_BASE)


def _chat(system: str, user: str, temperature: float = 0.8) -> str:
    """统一的 chat 调用封装。"""
    client = _get_client()
    resp = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return resp.choices[0].message.content


# ===================== Step 2+3: 热点 → 选题 =====================

def generate_topics(hot_topics: List[Dict[str, Any]], count: int = None) -> List[Dict[str, Any]]:
    """
    输入热点列表，输出可科普化的冷知识选题。
    每个选题包含：title, hook, angle, hot_source, science_keywords
    """
    count = count or config.TOPIC_COUNT

    # 只取标题给 LLM，避免 token 浪费
    hot_titles = [t["title"] for t in hot_topics[:30]]

    system = f"""你是一位专注于「{config.NICHE}」赛道的抖音爆款选题策划师。
你的任务：从给定的当日热点中，找出能做"冷知识/万物原理"切入的角度，
把时事热点转写成"反常识钩子 + 科普解读"的短视频选题。

选题原则：
1. 必须有强反差/反常识——"你以为了解X，其实……"
2. 必须有信息密度——观众看完能记住一个硬核知识点
3. 必须能在 3-5 分钟讲清楚，不要宏大叙事
4. 必须能用通用空镜素材配解说完成（不依赖特定人物/事件画面）
5. 优先选与"科学/自然/历史/技术/原理"相关的热点

输出严格的 JSON 数组，每个元素包含：
- title: 选题标题（15字以内，带悬念）
- hook: 开场钩子（前3秒话术，必须抓人）
- angle: 科普切入角度（一句话说明从哪个冷知识点讲起）
- hot_source: 对应的原始热点标题
- science_keywords: 3-5 个英文关键词（用于后续搜索素材，如 ["ocean","bioluminescence"]）
- duration_estimate: 预计时长（秒）

只输出 JSON，不要任何解释文字。"""

    user = f"今日热点列表：\n" + "\n".join(f"{i+1}. {t}" for i, t in enumerate(hot_titles)) + \
           f"\n\n请从中挑选 {count} 个最适合做冷知识科普的，按上述格式输出 JSON 数组。"

    raw = _chat(system, user, temperature=0.85)

    # 容错：LLM 可能包 ```json ... ``` 或带多余文字
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        topics = json.loads(raw)
    except json.JSONDecodeError:
        # 尝试找第一个 [ 到最后一个 ]
        start, end = raw.find("["), raw.rfind("]")
        if start >= 0 and end > start:
            topics = json.loads(raw[start : end + 1])
        else:
            raise

    print(f"[选题] 生成 {len(topics)} 个选题")
    for t in topics:
        print(f"  - {t.get('title')}（关键词: {t.get('science_keywords')}）")
    return topics


# ===================== Step 4: 选题 → 分镜脚本 =====================

def generate_script(topic: Dict[str, Any]) -> Dict[str, Any]:
    """
    输入选题，输出完整分镜脚本。
    返回结构：
    {
      "title": "...",
      "total_duration": 240,
      "narration_full": "完整解说文案（可直接配音）",
      "shots": [
        {
          "index": 1,
          "duration": 8,
          "narration": "这一段的解说词",
          "keywords": ["ocean wave", "sea underwater"],  # 素材搜索词
          "visual_note": "画面建议（空镜描述）"
        },
        ...
      ],
      "bgm_mood": "curious"
    }
    """
    target = config.TARGET_DURATION

    system = f"""你是一位抖音冷知识短视频脚本作家，专攻「{config.NICHE}」赛道。
你要把一个选题拆解成完整的分镜脚本，用于"空镜素材 + AI配音 + 字幕"的成片方式。

脚本结构公式（总时长约 {target} 秒）：
- 开场钩子（5-8秒）：强悬念，留住 3 秒完播
- 现象铺垫（20-30秒）：把观众代入日常认知
- 反转揭秘（40-60秒）：抛出反常识真相
- 深度展开（60-90秒）：讲清楚原理，给硬核知识点
- 延伸彩蛋（20-30秒）：一个让人想转发的冷知识
- 收尾引导（10-15秒）：引导关注，预告下期

每个分镜要求：
1. duration: 该分镜时长（秒），所有分镜加起来约等于 {target}
2. narration: 这一段的解说词（口语化，适合AI配音，每秒约4个字）
3. keywords: 2-3 个英文搜索词，用于在 Pexels/Pixabay 搜空镜（要具体，如 "ocean wave" 比 "water" 好）
4. visual_note: 画面建议（一句话描述理想空镜）

输出严格 JSON，结构如下：
{{
  "title": "选题标题",
  "total_duration": {target},
  "narration_full": "把所有分镜的 narration 拼起来的完整解说文案",
  "shots": [
    {{"index": 1, "duration": 8, "narration": "...", "keywords": ["..."], "visual_note": "..."}}
  ],
  "bgm_mood": "curious|ambient|chill|epic|mysterious"
}}

只输出 JSON，不要解释。"""

    user = f"""请为以下选题生成分镜脚本：

选题标题：{topic.get('title')}
开场钩子：{topic.get('hook')}
科普角度：{topic.get('angle')}
推荐素材关键词参考：{topic.get('science_keywords')}

要求：分镜数量 8-12 个，总时长接近 {target} 秒。"""

    raw = _chat(system, user, temperature=0.8)

    # 容错解析
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        script = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            script = json.loads(raw[start : end + 1])
        else:
            raise

    print(f"[脚本] 生成 {len(script.get('shots', []))} 个分镜，总时长 {script.get('total_duration')}s")
    return script


def script_to_markdown(topic: Dict[str, Any], script: Dict[str, Any]) -> str:
    """把脚本转成易读的 Markdown 文档，方便用户剪辑时对照。"""
    lines = [
        f"# {script.get('title', topic.get('title', '未命名选题'))}",
        "",
        f"**赛道**：{config.NICHE}",
        f"**对应热点**：{topic.get('hot_source', '无')}",
        f"**预计时长**：{script.get('total_duration', '?')} 秒",
        f"**BGM 情绪标签**：{script.get('bgm_mood', 'curious')}",
        "",
        "## 完整解说文案（可直接复制到剪映做 AI 配音）",
        "",
        script.get("narration_full", ""),
        "",
        "## 分镜表",
        "",
        "| 序号 | 时长 | 解说词 | 画面建议 | 搜索关键词 |",
        "|------|------|--------|----------|-----------|",
    ]
    for shot in script.get("shots", []):
        narration = shot.get("narration", "").replace("|", "/").replace("\n", " ")
        note = shot.get("visual_note", "").replace("|", "/").replace("\n", " ")
        keywords = ", ".join(shot.get("keywords", []))
        lines.append(
            f"| {shot['index']} | {shot.get('duration', '?')}s | {narration} | {note} | {keywords} |"
        )
    lines.extend([
        "",
        "## 剪辑流程",
        "",
        "1. 把 `clips/` 目录下 `shotXX_*.mp4` 按序号拖进剪映",
        "2. 把上方「完整解说文案」粘贴到剪映「文本」→「智能配音」",
        "3. 按 `bgm_suggestions.json` 推荐去对应站点下载配乐",
        "4. 字幕用思源黑体，加关键词高亮",
        "5. 导出 1080p 横屏，发布到抖音",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    # 自测：用 mock 热点跑一遍
    mock_hot = [
        {"title": "深海发现新物种发光水母", "source": "zhihu"},
        {"title": "某明星官宣结婚", "source": "weibo"},
        {"title": "火星探测新突破发现液态水痕迹", "source": "douyin"},
    ]
    print("=== 测试选题生成 ===")
    topics = generate_topics(mock_hot, count=2)
    print(json.dumps(topics, ensure_ascii=False, indent=2))

    if topics:
        print("\n=== 测试脚本生成 ===")
        script = generate_script(topics[0])
        print(json.dumps(script, ensure_ascii=False, indent=2))
        print("\n=== Markdown 输出 ===")
        print(script_to_markdown(topics[0], script))
