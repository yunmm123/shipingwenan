"""
AI 选题与脚本生成模块
用 LLM（OpenAI 兼容接口）完成两步：
1. 热点 → 冷知识选题（Step 2 + Step 3）
2. 选题 → 分镜脚本（Step 4）

输出结构化 JSON，方便后续素材抓取模块直接消费。
"""
import json
import re
from typing import List, Dict, Any, Union
import config


# ===================== JSON 健壮解析器 =====================

def _robust_json_loads(raw: str, expect_type: type = None) -> Union[List, Dict]:
    """
    多策略 JSON 解析器，专治 LLM 输出的"不标准 JSON"。
    按顺序尝试 5 种修复策略，全部失败才抛异常。

    常见 LLM JSON 问题：
    1. 包 ```json ... ``` 代码块
    2. 前后带解释文字
    3. 字符串值里含未转义的双引号
    4. 字符串值里含未转义的换行
    5. 尾部多余的逗号
    6. 单引号代替双引号
    """
    raw = raw.strip() if raw else ""

    # 策略1：去掉 markdown 代码块标记
    if raw.startswith("```"):
        # 去掉首行 ``` 或 ```json
        lines = raw.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # 去掉末尾 ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    # 策略2：直接尝试解析
    try:
        result = json.loads(raw)
        if _check_type(result, expect_type):
            return result
    except json.JSONDecodeError:
        pass

    # 策略3：提取首个 [ 到末尾 ] 或首个 { 到末尾 }
    open_char = "[" if expect_type == list else "{"
    close_char = "]" if expect_type == list else "}"
    # 如果没指定类型，优先尝试从第一个 { 或 [ 开始
    if expect_type is None:
        first_obj = raw.find("{")
        first_arr = raw.find("[")
        if first_obj >= 0 and (first_arr < 0 or first_obj < first_arr):
            open_char, close_char = "{", "}"
        elif first_arr >= 0:
            open_char, close_char = "[", "]"

    start = raw.find(open_char)
    end = raw.rfind(close_char)
    if start >= 0 and end > start:
        candidate = raw[start : end + 1]
        try:
            result = json.loads(candidate)
            if _check_type(result, expect_type):
                return result
        except json.JSONDecodeError:
            pass

        # 策略4：修复常见 JSON 格式问题后重试
        fixed = _fix_common_json_issues(candidate)
        try:
            result = json.loads(fixed)
            if _check_type(result, expect_type):
                return result
        except json.JSONDecodeError:
            pass

        # 策略5：用正则逐个提取键值对（最后兜底，针对 dict）
        if expect_type == dict or (expect_type is None and open_char == "{"):
            result = _regex_extract_dict(candidate)
            if result and _check_type(result, expect_type):
                return result

    # 全部失败，抛出带原始内容的异常，方便调试
    raise json.JSONDecodeError(
        f"无法解析 LLM 输出为 JSON。原始内容前 300 字符：\n{raw[:300]}",
        raw, 0
    )


def _check_type(result, expect_type) -> bool:
    """检查解析结果类型是否符合预期。"""
    if expect_type is None:
        return True
    if expect_type == list:
        return isinstance(result, list)
    if expect_type == dict:
        return isinstance(result, dict)
    return True


def _fix_common_json_issues(s: str) -> str:
    """修复 LLM 输出 JSON 时的常见格式问题。"""
    # 1. 去掉尾部多余的逗号（}, ] 前的逗号）
    s = re.sub(r",\s*([}\]])", r"\1", s)

    # 2. 单引号转双引号（注意不能误伤已经是双引号的内容）
    # 这个操作比较危险，只在纯单引号场景下做
    if "'" in s and '"' not in s:
        s = s.replace("'", '"')

    # 3. 修复字符串值内未转义的换行符
    # 找到所有双引号字符串，把内部的换行替换成 \n
    def fix_string_newlines(match):
        content = match.group(1)
        # 把实际换行替换成转义换行
        content = content.replace("\n", "\\n").replace("\r", "\\r")
        return f'"{content}"'
    # 匹配 "..." 但不匹配已经被转义的
    s = re.sub(r'"((?:[^"\\]|\\.)*?)(?<!\\)"', fix_string_newlines, s, flags=re.DOTALL)

    # 4. 修复键名没加引号的情况 {title: "..."} → {"title": "..."}
    s = re.sub(r'(\{|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', s)

    # 5. 把中文引号统一成英文双引号
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", '"').replace("\u2019", '"')

    return s


def _regex_extract_dict(s: str) -> Dict:
    """最后兜底：用正则逐个提取顶层键值对，构造 dict。"""
    result = {}
    # 匹配 "key": "value" 或 "key": number 或 "key": [...] 或 "key": {...}
    # 这个方法比较粗糙，但能救回一些极端情况
    pattern = r'"([^"]+)"\s*:\s*("(?:[^"\\]|\\.)*"|[\d.]+|\[[\s\S]*?\]|\{[\s\S]*?\}|true|false|null)'
    for match in re.finditer(pattern, s):
        key = match.group(1)
        val_str = match.group(2).strip()
        # 尝试解析值
        try:
            val = json.loads(val_str)
        except json.JSONDecodeError:
            # 去掉首尾引号当作字符串
            if val_str.startswith('"') and val_str.endswith('"'):
                val = val_str[1:-1]
            else:
                val = val_str
        # 同名 key 只取第一个
        if key not in result:
            result[key] = val
    return result


# ===================== LLM 调用封装 =====================

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
    topics = _robust_json_loads(raw, expect_type=list)

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
    script = _robust_json_loads(raw, expect_type=dict)

    print(f"[脚本] 生成 {len(script.get('shots', []))} 个分镜，总时长 {script.get('total_duration')}s")
    return script


# ===================== Step 4.5: 生成发布信息 =====================

def generate_publish_info(topic: Dict[str, Any], script: Dict[str, Any]) -> Dict[str, Any]:
    """
    基于选题和脚本，生成抖音发布所需的作品信息。
    返回结构：
    {
      "title": "25字以内的作品标题",
      "description": "200字以内的作品描述",
      "hashtags": ["#话题1", "#话题2", "#话题3", "#话题4", "#话题5"],
      "cover_suggestion": "封面文字建议",
      "publish_tips": "发布时机和注意事项建议"
    }
    """
    system = f"""你是一位抖音冷知识赛道的爆款运营专家，精通抖音算法和用户心理。
你要为一条已经写好的冷知识短视频生成发布所需的文案。

抖音发布文案规则：
1. 作品标题（≤25字）：必须有强悬念或反差，不能直接剧透答案，激发点击欲
2. 作品描述（≤200字）：第一句必须是钩子，中间补充知识点背景，结尾引导互动（评论/收藏/关注）
3. 相关话题（≤5个）：1-2个赛道大词（如#冷知识 #科普）+ 2-3个选题相关词 + 1个蹭热点词
4. 话题要真实存在且有热度，不要生造
5. 不要用"震惊""不转不是X"等低质诱导词

输出严格 JSON：
{{
  "title": "作品标题，≤25字",
  "description": "作品描述，≤200字",
  "hashtags": ["#话题1", "#话题2", "#话题3", "#话题4", "#话题5"],
  "cover_suggestion": "封面应该突出的关键词或文字（10字以内）",
  "publish_tips": "发布时机和注意事项（一句话）"
}}

只输出 JSON，不要解释。"""

    user = f"""请为以下视频生成发布文案：

选题标题：{topic.get('title')}
开场钩子：{topic.get('hook')}
科普角度：{topic.get('angle')}
对应热点：{topic.get('hot_source', '无')}
BGM情绪：{script.get('bgm_mood', 'curious')}
视频时长：{script.get('total_duration', 240)}秒

解说文案摘要（前100字）：
{script.get('narration_full', '')[:100]}

要求：
- 标题≤25字，带强悬念
- 描述≤200字，首句钩子+结尾互动引导
- 5个话题，含1-2个赛道大词+蹭热点词
- 整体风格符合抖音冷知识爆款调性"""

    raw = _chat(system, user, temperature=0.85)
    info = _robust_json_loads(raw, expect_type=dict)

    # 安全校验：超长截断，话题数限制
    info["title"] = info.get("title", "")[:25]
    info["description"] = info.get("description", "")[:200]
    info["hashtags"] = info.get("hashtags", [])[:5]
    info.setdefault("cover_suggestion", "")
    info.setdefault("publish_tips", "")

    print(f"[发布] 标题({len(info['title'])}字): {info['title']}")
    print(f"[发布] 描述({len(info['description'])}字)")
    print(f"[发布] 话题: {' '.join(info['hashtags'])}")
    return info


def publish_info_to_markdown(info: Dict[str, Any]) -> str:
    """把发布信息转成易读的 Markdown 文档。"""
    lines = [
        "# 📱 抖音发布文案（直接复制使用）",
        "",
        "## 作品标题",
        "",
        f"**{info.get('title', '')}**",
        "",
        "## 作品描述",
        "",
        info.get("description", ""),
        "",
        "## 相关话题（发布时填到话题栏）",
        "",
        " ".join(info.get("hashtags", [])),
        "",
        "## 封面建议",
        "",
        f"封面文字突出：**{info.get('cover_suggestion', '')}**",
        "",
        "## 发布建议",
        "",
        info.get("publish_tips", ""),
        "",
        "---",
        "",
        "## 📋 复制清单",
        "",
        "### 标题（复制到标题栏）",
        "```",
        info.get("title", ""),
        "```",
        "",
        "### 描述（复制到描述栏）",
        "```",
        info.get("description", ""),
        "```",
        "",
        "### 话题（复制到话题栏）",
        "```",
        " ".join(info.get("hashtags", [])),
        "```",
    ]
    return "\n".join(lines)


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
