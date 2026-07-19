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


def _sanitize_ascii(value: str, field_name: str = "API Key") -> str:
    """
    清除字符串中的非 ASCII 字符。
    用户从 Word/PDF/网页复制 API Key 时，可能混入不可见的特殊字符
    （如 U+F0B7 Symbol 字体的项目符号、零宽空格 U+200B、BOM U+FEFF 等），
    这些字符会导致 httpx 构造 HTTP 头时报 UnicodeEncodeError。
    """
    if not value:
        return value
    # 去掉首尾空白（包括不可见空白字符）
    cleaned = value.strip()
    # 去掉零宽字符、BOM、软连字符等不可见字符
    invisible_chars = {
        "\ufeff",  # BOM / Zero Width No-Break Space
        "\u200b",  # Zero Width Space
        "\u200c",  # Zero Width Non-Joiner
        "\u200d",  # Zero Width Joiner
        "\u200e",  # Left-to-Right Mark
        "\u200f",  # Right-to-Left Mark
        "\u00ad",  # Soft Hyphen
    }
    for ch in invisible_chars:
        cleaned = cleaned.replace(ch, "")
    # 只保留 ASCII 可见字符（0x20-0x7E）
    ascii_only = "".join(c for c in cleaned if 0x20 <= ord(c) <= 0x7E)
    if len(ascii_only) != len(cleaned):
        removed = len(cleaned) - len(ascii_only)
        print(f"[配置] ⚠️ {field_name} 含 {removed} 个非 ASCII 字符，已自动清除")
    return ascii_only


def _get_client():
    if not HAS_OPENAI:
        raise RuntimeError("未安装 openai 包，请 pip install openai")
    if not config.LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY 未配置，请检查 .env")
    # 清除 API Key 和 Base URL 中可能混入的非 ASCII 字符
    clean_key = _sanitize_ascii(config.LLM_API_KEY, "LLM_API_KEY")
    clean_base = _sanitize_ascii(config.LLM_API_BASE, "LLM_API_BASE")
    if not clean_key:
        raise RuntimeError("LLM_API_KEY 清除非 ASCII 字符后为空，请检查是否复制完整")
    return OpenAI(api_key=clean_key, base_url=clean_base)


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
    分镜数量不固定，AI 根据选题复杂度自行决定（6-15个）。
    解说文案严格按字数=时长×4字/秒 匹配，避免文案与视频时长错位。

    返回结构：
    {
      "title": "...",
      "total_duration": 240,
      "narration_full": "完整解说文案（可直接配音）",
      "shots": [
        {
          "index": 1,
          "duration": 8,
          "narration": "这一段的解说词（字数≈duration×4）",
          "keywords": ["ocean wave", "sea underwater"],
          "visual_note": "画面建议（空镜描述）",
          "editing_tip": "剪辑建议：如何处理这个分镜的素材"
        },
        ...
      ],
      "bgm_mood": "curious"
    }
    """
    target = config.TARGET_DURATION
    cps = config.NARRATION_CHARS_PER_SEC  # 字/秒
    min_shots = config.MIN_SHOTS
    max_shots = config.MAX_SHOTS

    system = f"""你是一位抖音冷知识短视频脚本作家，专攻「{config.NICHE}」赛道。
你要把一个选题拆解成完整的分镜脚本，用于"空镜素材 + AI配音 + 字幕"的成片方式。

【分镜数量——由选题复杂度决定，不固定】
根据选题的信息量自行决定分镜数量，范围 {min_shots}-{max_shots} 个：
- 简单科普选题（1个核心知识点）：{min_shots}-{min_shots+2} 个分镜即可
- 中等复杂度（2-3个知识点）：{min_shots+3}-{min_shots+6} 个分镜
- 复杂选题（多角度、有对比、有实验）：{min_shots+7}-{max_shots} 个分镜
不要为了凑数而拆分，每个分镜必须有独立的信息价值。

【解说文案——严格匹配时长，这是硬性要求】
中文解说语速约 {cps} 字/秒。每个分镜的 narration 字数必须严格等于 duration × {cps}（允许±2字误差）。
公式：narration字数 = duration × {cps}
举例：duration=8秒 → narration约{8*cps}字；duration=15秒 → narration约{15*cps}字
绝对不能出现文案太长（视频不够用）或文案太短（视频空窗）的情况。

【脚本结构公式（总时长约 {target} 秒，仅参考，可浮动）】
- 开场钩子（5-10秒）：强悬念，留住3秒完播
- 现象铺垫（20-40秒）：把观众代入日常认知
- 反转揭秘（40-70秒）：抛出反常识真相
- 深度展开（60-100秒）：讲清楚原理，给硬核知识点
- 延伸彩蛋（20-40秒）：让人想转发的冷知识
- 收尾引导（10-20秒）：引导关注，预告下期
实际总时长可以浮动 ±30秒，以内容完整性为准，不要为了凑时长而注水。

【每个分镜要求】
1. duration: 该分镜时长（秒），整数
2. narration: 解说词（口语化，适合AI配音，字数严格=duration×{cps}）
3. keywords: 2-3 个英文搜索词，用于在 Pexels/Pixabay 搜空镜（要具体，如 "ocean wave" 比 "water" 好）
4. visual_note: 画面建议（一句话描述理想空镜画面）
5. editing_tip: 剪辑建议（告诉剪辑者怎么处理这个分镜的素材），包括：
   - 素材使用方式（如"截取素材前5秒的平静海面""用慢动作处理2-3秒的浪花特写"）
   - 转场建议（如"硬切""叠化""缩放推入"）
   - 字幕/特效建议（如"关键词高亮放大""加箭头标注""数据用动态数字"）
   - 节奏提示（如"快节奏剪辑，每2秒切一个画面""留2秒静帧让观众消化"）

输出严格 JSON，结构如下：
{{
  "title": "选题标题",
  "total_duration": 实际总时长,
  "narration_full": "把所有分镜的 narration 拼起来的完整解说文案",
  "shots": [
    {{"index": 1, "duration": 8, "narration": "约32字的解说词", "keywords": ["..."], "visual_note": "...", "editing_tip": "..."}}
  ],
  "bgm_mood": "curious|ambient|chill|epic|mysterious"
}}

只输出 JSON，不要解释。"""

    user = f"""请为以下选题生成分镜脚本：

选题标题：{topic.get('title')}
开场钩子：{topic.get('hook')}
科普角度：{topic.get('angle')}
推荐素材关键词参考：{topic.get('science_keywords')}

要求：
1. 分镜数量由选题复杂度决定（{min_shots}-{max_shots}个），不要固定数字
2. 每个分镜的 narration 字数严格等于 duration×{cps}（±2字）
3. 每个分镜必须包含 editing_tip 剪辑建议
4. 总时长接近 {target} 秒，可浮动 ±30秒"""

    raw = _chat(system, user, temperature=0.8)
    script = _robust_json_loads(raw, expect_type=dict)

    # 后处理：校验并修正解说文案字数
    _validate_and_fix_narration_length(script, cps)

    print(f"[脚本] 生成 {len(script.get('shots', []))} 个分镜，总时长 {script.get('total_duration')}s")
    return script


def _validate_and_fix_narration_length(script: Dict[str, Any], cps: int):
    """
    校验每个分镜的解说文案字数是否匹配时长。
    不匹配时打印警告（不强制截断，保留 AI 原文，但标记差异供后续调整）。
    """
    shots = script.get("shots", [])
    issues = []
    for shot in shots:
        duration = shot.get("duration", 0)
        narration = shot.get("narration", "")
        actual_len = len(narration)
        target_len = duration * cps
        if abs(actual_len - target_len) > 5:
            issues.append(
                f"  分镜{shot.get('index')}: 时长{duration}s 需约{target_len}字，实际{actual_len}字（差{actual_len-target_len:+d}）"
            )
            # 标记到分镜中，供 adjust 阶段参考
            shot["narration_length_issue"] = {
                "target": target_len,
                "actual": actual_len,
                "diff": actual_len - target_len,
            }

    if issues:
        print(f"[脚本] ⚠️ {len(issues)} 个分镜解说字数与时长不匹配：")
        for issue in issues:
            print(issue)
    else:
        print(f"[脚本] ✅ 所有分镜解说字数与时长匹配")


# ===================== Step 4.6: 根据实际素材调整脚本 =====================

def adjust_script_to_clips(
    script: Dict[str, Any],
    clips_map: Dict[int, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """
    根据实际下载的视频素材，动态调整脚本时长和解说建议。

    参数：
    - script: generate_script() 的输出
    - clips_map: {shot_index: [clip_info, ...]}，clip_info 含 duration 字段

    返回调整后的 script（新增 actual_duration, duration_adjustment, adjust_tip 字段）。
    """
    cps = config.NARRATION_CHARS_PER_SEC
    shots = script.get("shots", [])
    adjusted_shots = []
    total_adjusted = 0

    for shot in shots:
        idx = shot.get("index")
        planned_duration = shot.get("duration", 0)
        planned_narration = shot.get("narration", "")
        narration_len = len(planned_narration)

        clips = clips_map.get(idx, [])
        clip_duration = clips[0].get("duration", 0) if clips else 0

        if not clips:
            # 没抓到素材，保留原计划
            shot["actual_duration"] = planned_duration
            shot["duration_adjustment"] = "no_clip"
            shot["adjust_tip"] = (
                f"⚠️ 未抓到素材，需手动找视频。计划时长{planned_duration}秒，"
                f"解说{narration_len}字（约{narration_len/cps:.1f}秒）。"
            )
            total_adjusted += planned_duration
            adjusted_shots.append(shot)
            continue

        # 计算解说需要的时长
        narration_duration = narration_len / cps

        # 策略：以解说时长为准，调整素材使用方式
        if clip_duration >= narration_duration:
            # 素材够长，截取解说时长对应的片段
            actual_duration = round(narration_duration)
            trim = round(clip_duration - narration_duration)
            if trim > 2:
                adjust_tip = (
                    f"✅ 素材{clip_duration}秒 > 解说需{narration_duration:.1f}秒。"
                    f"截取素材精华{actual_duration}秒，剪掉末尾{trim}秒冗余。"
                    f"建议取素材中最精彩的{actual_duration}秒段落。"
                )
            else:
                adjust_tip = (
                    f"✅ 素材{clip_duration}秒 ≈ 解说需{narration_duration:.1f}秒，"
                    f"直接使用，无需裁剪。"
                )
            shot["actual_duration"] = actual_duration
            shot["duration_adjustment"] = f"trim_{trim}s"
        else:
            # 素材不够长，需要处理
            gap = round(narration_duration - clip_duration)
            if gap <= 3:
                # 差距小，素材可适当放慢或重复片段
                adjust_tip = (
                    f"⚠️ 素材{clip_duration}秒 < 解说需{narration_duration:.1f}秒（差{gap}秒）。"
                    f"建议：素材末尾做0.5倍速慢放{gap}秒，或循环播放最后2秒填补。"
                )
                shot["actual_duration"] = round(narration_duration)
                shot["duration_adjustment"] = f"extend_{gap}s"
            else:
                # 差距大，建议精简解说
                target_narration_len = int(clip_duration * cps)
                adjust_tip = (
                    f"⚠️ 素材仅{clip_duration}秒，但解说需{narration_duration:.1f}秒（差{gap}秒）。"
                    f"建议方案A：精简解说至约{target_narration_len}字（删减{narration_len-target_narration_len}字）。"
                    f"建议方案B：补1-2个B-roll空镜填补{gap}秒。"
                )
                shot["actual_duration"] = clip_duration
                shot["duration_adjustment"] = f"shorten_narration_{gap}s"

        shot["adjust_tip"] = adjust_tip
        shot["clip_duration"] = clip_duration
        shot["clip_source"] = clips[0].get("source", "")
        total_adjusted += shot["actual_duration"]
        adjusted_shots.append(shot)

    # 更新脚本
    script["shots"] = adjusted_shots
    script["actual_total_duration"] = total_adjusted
    script["planned_total_duration"] = script.get("total_duration", 0)
    duration_diff = total_adjusted - script.get("total_duration", 0)
    script["duration_diff"] = duration_diff

    print(f"[调整] 计划总时长 {script.get('total_duration',0)}s → 实际总时长 {total_adjusted}s（{duration_diff:+d}s）")
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
    ]
    # 如果有调整后的实际时长，也显示
    if script.get("actual_total_duration"):
        lines.append(f"**实际时长（根据素材调整）**：{script.get('actual_total_duration')} 秒（原计划 {script.get('planned_total_duration','?')} 秒，差 {script.get('duration_diff', 0):+d} 秒）")
    lines.extend([
        f"**BGM 情绪标签**：{script.get('bgm_mood', 'curious')}",
        "",
        "## 完整解说文案（可直接复制到剪映做 AI 配音）",
        "",
        script.get("narration_full", ""),
        "",
        "## 分镜表",
        "",
    ])
    # 根据是否有调整信息决定表头
    has_adjust = any(s.get("adjust_tip") for s in script.get("shots", []))
    if has_adjust:
        lines.append("| 序号 | 计划时长 | 实际时长 | 素材时长 | 解说词 | 画面建议 | 剪辑建议 | 素材调整建议 |")
        lines.append("|------|---------|---------|---------|--------|----------|---------|------------|")
    else:
        lines.append("| 序号 | 时长 | 解说词 | 画面建议 | 剪辑建议 | 搜索关键词 |")
        lines.append("|------|------|--------|----------|---------|-----------|")
    for shot in script.get("shots", []):
        narration = shot.get("narration", "").replace("|", "/").replace("\n", " ")
        note = shot.get("visual_note", "").replace("|", "/").replace("\n", " ")
        editing = shot.get("editing_tip", "").replace("|", "/").replace("\n", " ")
        keywords = ", ".join(shot.get("keywords", []))
        if has_adjust:
            actual = shot.get("actual_duration", "?")
            clip_dur = shot.get("clip_duration", "无素材")
            adjust = shot.get("adjust_tip", "").replace("|", "/").replace("\n", " ")
            lines.append(
                f"| {shot['index']} | {shot.get('duration', '?')}s | {actual}s | {clip_dur}s | {narration} | {note} | {editing} | {adjust} |"
            )
        else:
            lines.append(
                f"| {shot['index']} | {shot.get('duration', '?')}s | {narration} | {note} | {editing} | {keywords} |"
            )
    lines.extend([
        "",
        "## 剪辑流程",
        "",
        "1. 把 `clips/` 目录下 `shotXX_*.mp4` 按序号拖进剪映",
        "2. 把上方「完整解说文案」粘贴到剪映「文本」→「智能配音」",
        "3. 按每个分镜的「剪辑建议」处理素材（截取/慢放/转场等）",
        "4. 按「素材调整建议」处理文案与素材的时长差异",
        "5. 按 `bgm_suggestions.json` 推荐去对应站点下载配乐",
        "6. 字幕用思源黑体，加关键词高亮",
        "7. 导出 1080p 横屏，发布到抖音",
    ])
    return "\n".join(lines)


# ===================== Word 文档生成（.docx）=====================

def _get_docx():
    """延迟导入 python-docx，未安装时给出友好提示。"""
    try:
        from docx import Document
        from docx.shared import Pt, Inches, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT
        return Document, Pt, Inches, Cm, RGBColor, WD_ALIGN_PARAGRAPH, WD_TABLE_ALIGNMENT
    except ImportError:
        raise RuntimeError("未安装 python-docx 包，请 pip install python-docx")


def _set_cell_font(cell, text, bold=False, size=10, color=None):
    """设置单元格字体（支持中文）。"""
    Document, Pt, Inches, Cm, RGBColor, _, _ = _get_docx()
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = "Microsoft YaHei"
    run._element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", "Microsoft YaHei")
    if color:
        run.font.color.rgb = RGBColor(*color)


def script_to_docx(
    topic: Dict[str, Any],
    script: Dict[str, Any],
    clips_map: Dict[int, List[Dict[str, Any]]] = None,
) -> "bytes":
    """
    把脚本转成 Word 文档（.docx），返回 BytesIO。
    包含：元信息、完整解说文案、分镜表（含剪辑建议和素材调整建议）、剪辑流程。
    """
    import io
    Document, Pt, Inches, Cm, RGBColor, WD_ALIGN_PARAGRAPH, WD_TABLE_ALIGNMENT = _get_docx()

    doc = Document()

    # 设置默认字体
    style = doc.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(11)
    style._element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", "Microsoft YaHei")

    # === 标题 ===
    title = doc.add_heading(script.get("title", topic.get("title", "未命名选题")), level=0)
    for run in title.runs:
        run.font.name = "Microsoft YaHei"
        run._element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", "Microsoft YaHei")

    # === 元信息 ===
    doc.add_paragraph(f"赛道：{config.NICHE}")
    doc.add_paragraph(f"对应热点：{topic.get('hot_source', '无')}")
    planned_dur = script.get("total_duration", "?")
    doc.add_paragraph(f"计划时长：{planned_dur} 秒")
    if script.get("actual_total_duration"):
        actual_dur = script.get("actual_total_duration")
        diff = script.get("duration_diff", 0)
        p = doc.add_paragraph()
        run = p.add_run(f"实际时长（根据素材调整）：{actual_dur} 秒")
        run.font.bold = True
        if diff > 0:
            run.font.color.rgb = RGBColor(0xE7, 0x4C, 0x3C)  # 红色：变长
        elif diff < 0:
            run.font.color.rgb = RGBColor(0x34, 0x98, 0xDB)  # 蓝色：变短
        else:
            run.font.color.rgb = RGBColor(0x27, 0xAE, 0x60)  # 绿色：一致
        p.add_run(f"（原计划 {planned_dur} 秒，差 {diff:+d} 秒）")
    doc.add_paragraph(f"BGM 情绪标签：{script.get('bgm_mood', 'curious')}")
    doc.add_paragraph(f"分镜数量：{len(script.get('shots', []))} 个（由选题复杂度决定）")

    doc.add_paragraph()  # 空行

    # === 完整解说文案 ===
    doc.add_heading("完整解说文案（可直接复制到剪映做 AI 配音）", level=1)
    narration = script.get("narration_full", "")
    p = doc.add_paragraph(narration)
    for run in p.runs:
        run.font.size = Pt(12)

    doc.add_paragraph()  # 空行

    # === 分镜表 ===
    has_adjust = any(s.get("adjust_tip") for s in script.get("shots", []))

    if has_adjust:
        doc.add_heading("分镜详情表（含剪辑建议和素材调整）", level=1)
        headers = ["序号", "计划", "实际", "素材", "解说词", "画面建议", "剪辑建议", "素材调整建议"]
        col_widths = [Cm(1.0), Cm(1.2), Cm(1.2), Cm(1.2), Cm(5.0), Cm(3.5), Cm(4.0), Cm(4.0)]
    else:
        doc.add_heading("分镜详情表（含剪辑建议）", level=1)
        headers = ["序号", "时长", "解说词", "画面建议", "剪辑建议", "搜索关键词"]
        col_widths = [Cm(1.0), Cm(1.5), Cm(5.5), Cm(3.5), Cm(4.5), Cm(3.0)]

    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # 表头
    hdr_cells = table.rows[0].cells
    for i, (header, width) in enumerate(zip(headers, col_widths)):
        hdr_cells[i].width = width
        _set_cell_font(hdr_cells[i], header, bold=True, size=10, color=(0xFF, 0xFF, 0xFF))

    # 数据行
    for shot in script.get("shots", []):
        row_cells = table.add_row().cells
        if has_adjust:
            data = [
                str(shot.get("index", "")),
                f"{shot.get('duration', '?')}s",
                f"{shot.get('actual_duration', '?')}s",
                f"{shot.get('clip_duration', '?')}s",
                shot.get("narration", ""),
                shot.get("visual_note", ""),
                shot.get("editing_tip", ""),
                shot.get("adjust_tip", ""),
            ]
        else:
            data = [
                str(shot.get("index", "")),
                f"{shot.get('duration', '?')}s",
                shot.get("narration", ""),
                shot.get("visual_note", ""),
                shot.get("editing_tip", ""),
                ", ".join(shot.get("keywords", [])),
            ]
        for i, (cell, text, width) in enumerate(zip(row_cells, data, col_widths)):
            cell.width = width
            # 序号和时长列加粗居中
            if i < (4 if has_adjust else 2):
                _set_cell_font(cell, text, bold=True, size=9)
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            else:
                _set_cell_font(cell, text, size=9)

    doc.add_paragraph()  # 空行

    # === 剪辑流程 ===
    doc.add_heading("剪辑流程", level=1)
    steps = [
        "1. 把 clips/ 目录下 shotXX_*.mp4 按序号拖进剪映",
        "2. 把上方「完整解说文案」粘贴到剪映「文本」→「智能配音」",
        "3. 按每个分镜的「剪辑建议」处理素材（截取/慢放/转场等）",
        "4. 按「素材调整建议」处理文案与素材的时长差异",
        "5. 按 bgm_suggestions.json 推荐去对应站点下载配乐",
        "6. 字幕用思源黑体，加关键词高亮",
        "7. 导出 1080p 横屏，发布到抖音",
    ]
    for step in steps:
        doc.add_paragraph(step)

    # === 字数匹配说明 ===
    doc.add_heading("解说文案与时长匹配说明", level=1)
    cps = config.NARRATION_CHARS_PER_SEC
    doc.add_paragraph(f"中文解说语速基准：{cps} 字/秒。每个分镜的解说字数 ≈ 时长 × {cps}。")
    doc.add_paragraph("如果实际素材时长与计划不符，请参考「素材调整建议」列的方案处理：")
    doc.add_paragraph("  ✅ 素材够长：截取精华段落，剪掉冗余")
    doc.add_paragraph("  ⚠️ 素材略短：末尾慢放或循环填补")
    doc.add_paragraph("  ⚠️ 素材太短：精简解说字数或补 B-roll 空镜")

    # 输出到 BytesIO
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def publish_info_to_docx(info: Dict[str, Any]) -> "bytes":
    """把发布信息转成 Word 文档（.docx），返回 BytesIO。"""
    import io
    Document, Pt, Inches, Cm, RGBColor, WD_ALIGN_PARAGRAPH, _ = _get_docx()

    doc = Document()

    # 设置默认字体
    style = doc.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(11)
    style._element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", "Microsoft YaHei")

    # === 标题 ===
    heading = doc.add_heading("抖音发布文案（直接复制使用）", level=0)
    for run in heading.runs:
        run.font.name = "Microsoft YaHei"
        run._element.rPr.rFonts.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", "Microsoft YaHei")

    # === 作品标题 ===
    doc.add_heading("作品标题", level=1)
    p = doc.add_paragraph()
    run = p.add_run(info.get("title", ""))
    run.font.bold = True
    run.font.size = Pt(14)

    # === 作品描述 ===
    doc.add_heading("作品描述", level=1)
    doc.add_paragraph(info.get("description", ""))

    # === 相关话题 ===
    doc.add_heading("相关话题（发布时填到话题栏）", level=1)
    p = doc.add_paragraph(" ".join(info.get("hashtags", [])))
    for run in p.runs:
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0x00, 0x77, 0xCC)

    # === 封面建议 ===
    doc.add_heading("封面建议", level=1)
    doc.add_paragraph(f"封面文字突出：{info.get('cover_suggestion', '')}")

    # === 发布建议 ===
    doc.add_heading("发布建议", level=1)
    doc.add_paragraph(info.get("publish_tips", ""))

    # === 复制清单 ===
    doc.add_heading("复制清单", level=1)

    doc.add_heading("标题（复制到标题栏）", level=2)
    p = doc.add_paragraph(info.get("title", ""))
    p.style = doc.styles["Normal"]
    for run in p.runs:
        run.font.size = Pt(12)

    doc.add_heading("描述（复制到描述栏）", level=2)
    p = doc.add_paragraph(info.get("description", ""))
    for run in p.runs:
        run.font.size = Pt(12)

    doc.add_heading("话题（复制到话题栏）", level=2)
    p = doc.add_paragraph(" ".join(info.get("hashtags", [])))
    for run in p.runs:
        run.font.size = Pt(12)

    # 输出到 BytesIO
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


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
