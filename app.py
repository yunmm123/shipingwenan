"""
B站叙事AI短片生产线 - 网页版
热点 → 叙事短片剧本 → 角色设定卡 → 可灵提示词包 → 你用可灵生成视频 → 剪映成片

部署：Streamlit Community Cloud（免费）
使用：填入 API Key → 点按钮 → 下载拍摄指南 Word 文档
"""
import os
import sys
import io
import json
import zipfile
import tempfile
from pathlib import Path
from datetime import datetime

# 让模块能被导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

# 页面配置
st.set_page_config(
    page_title="B站叙事AI短片生产线",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============ Session State 初始化 ============
defaults = {
    'keys_configured': False,
    'hot_topics_data': None,
    'topics': None,
    'selected_topic_idx': None,
    'script': None,
    'publish_info': None,
    'character_cards': None,
    'scene_cards': None,
    'kling_groups': None,
    'current_step': 0,
    'selected_genre': '科幻',
    'selected_art_style': 'cinematic',
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ============ API Key 清洗 ============
def _sanitize_key(value: str) -> str:
    """清除 API Key 中的非 ASCII 字符（从 Word/PDF 复制时可能混入）。"""
    if not value:
        return value
    cleaned = value.strip()
    invisible = {"\ufeff", "\u200b", "\u200c", "\u200d", "\u200e", "\u200f", "\u00ad"}
    for ch in invisible:
        cleaned = cleaned.replace(ch, "")
    return "".join(c for c in cleaned if 0x20 <= ord(c) <= 0x7E)


def apply_keys_to_config(llm_key):
    """把用户输入的 key 写入 config 模块和环境变量。"""
    import config
    llm_key = _sanitize_key(llm_key) if llm_key else ""
    os.environ['LLM_API_KEY'] = llm_key
    os.environ['LLM_API_BASE'] = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    os.environ['LLM_MODEL'] = 'qwen3.7-plus'
    import importlib
    importlib.reload(config)
    return config


def apply_params_to_config(genre, art_style, target_duration):
    import config
    config.NICHE = "B站叙事AI短片"
    config.TARGET_DURATION = target_duration
    if genre:
        config.DEFAULT_GENRE = genre
    return config


# ============ 顶部标题区 ============
st.markdown("""
<div style='background:linear-gradient(90deg,#00A1D6 0%,#0E5E8F 100%);
            padding:24px 32px;border-radius:16px;margin-bottom:24px;'>
    <h1 style='color:white;margin:0;font-size:32px;'>🎬 B站叙事AI短片生产线</h1>
    <p style='color:rgba(255,255,255,0.9);margin:8px 0 0 0;font-size:16px;'>
        抓取热点 → AI 写叙事剧本 → 生成角色设定卡 → 生成可灵提示词包 → 你用可灵生成视频 → 剪映成片
    </p>
</div>
""", unsafe_allow_html=True)


# ============ 侧边栏：配置区 ============
with st.sidebar:
    st.header("⚙️ API Key 配置")
    st.caption("Key 仅保存在本次会话，不会上传或落盘")

    llm_key = st.text_input(
        "Qwen API Key *",
        type="password",
        help="必填。阿里云百炼平台 https://bailian.console.aliyun.com/ 获取（通义千问+通义万相同一账号）"
    )

    if st.button("💾 保存配置", use_container_width=True, type="primary"):
        if llm_key:
            warnings = []
            clean = _sanitize_key(llm_key)
            if len(clean) != len(llm_key.strip()):
                removed = len(llm_key.strip()) - len(clean)
                warnings.append(f"Qwen Key 清除了 {removed} 个隐藏字符")
            apply_keys_to_config(llm_key)
            st.session_state.keys_configured = True
            st.success("✅ 配置已保存，可以开始使用了！")
            if warnings:
                st.warning("⚠️ " + "；".join(warnings))
        else:
            st.error("❌ 必填项未填：Qwen Key 是必填的")

    st.divider()
    st.header("🎛️ 参数设置")
    genre_options = ["科幻", "悬疑", "哲理", "奇幻", "都市", "恐怖"]
    genre = st.selectbox("短片题材", genre_options, index=0)
    st.session_state.selected_genre = genre

    art_style_options = {
        "cinematic": "电影感（推荐）",
        "anime": "日系动画",
        "realistic": "超写实",
        "oil_painting": "油画风",
        "watercolor": "水彩风",
    }
    art_style = st.selectbox(
        "画面画风",
        options=list(art_style_options.keys()),
        format_func=lambda x: art_style_options[x],
        index=0,
    )
    st.session_state.selected_art_style = art_style

    target_duration = st.slider("短片目标时长（秒）", 120, 360, 240, 30)

    if st.button("💾 应用参数", use_container_width=True):
        apply_params_to_config(genre, art_style, target_duration)
        st.success("参数已应用")

    st.divider()
    st.caption("📚 [使用教程](https://github.com/yunmm123/shipingwenan)")


# ============ 主区域：未配置时显示引导 ============
if not st.session_state.keys_configured:
    st.info("👈 请先在左侧侧边栏配置 Qwen API Key")
    st.markdown("""
    ### 📖 工作流程

    1. **配置 Key**：左侧填入 Qwen API Key，点保存
    2. **抓取热点**：自动抓取多平台热榜
    3. **生成选题**：AI 把热点转成叙事短片构思（有主角、冲突、反转）
    4. **生成剧本**：AI 写出完整三幕剧剧本（角色、场景、分镜）
    5. **生成角色卡**：AI 生成角色设定卡绘画提示词（你拿去通义万相生成立绘）
    6. **生成可灵提示词包**：AI 把镜头转成可灵提示词，按场景分组
    7. **下载拍摄指南**：一键打包 Word 文档（剧本+角色卡+可灵提示词+发布文案）

    ### 🎬 你拿到拍摄指南后要做的

    1. 用角色卡提示词去通义万相生成主角立绘（免费）
    2. 用场景卡提示词去通义万相生成场景九宫格（免费）
    3. 去可灵 AI (https://klingai.com) 上传角色参考图
    4. 按拍摄指南的分组，复制提示词到可灵生成视频（每日66免费灵感值）
    5. 下载所有视频片段，用剪映拼接+配音+字幕
    6. 发布到 B站

    ### 🔑 没有 Key？

    | Key | 免费获取地址 | 说明 |
    |-----|------------|------|
    | Qwen | https://bailian.console.aliyun.com/ | 阿里云百炼，注册送额度，通义千问+通义万相同用 |
    | 可灵 | https://klingai.com | 注册即每日66灵感值，无需Key |

    ### 🆚 为什么从抖音转B站？

    - 抖音对AI内容强制标识+限流，完播率仅15-25%
    - B站1.9亿月活用户主动关注AI内容，官方UpDream工具扶持
    - B站用户审美要求高，但接受AI短片，只要叙事好就能火
    """)
    st.stop()


# ============ 主区域：工作流 ============
# 步骤进度条
st.markdown("### 📊 进度")
step_cols = st.columns(6)
steps = ["抓热点", "生成选题", "写剧本", "角色卡", "可灵包", "下载"]
for i, (col, name) in enumerate(zip(step_cols, steps)):
    with col:
        if st.session_state.current_step > i:
            color = "green"
            icon = "✅"
        elif st.session_state.current_step == i:
            color = "#00A1D6"
            icon = "🔄"
        else:
            color = "gray"
            icon = "⚪"
        st.markdown(
            f"<div style='text-align:center;padding:12px;border-radius:8px;"
            f"background:{color}20;border:2px solid {color};'>"
            f"<div style='font-size:24px'>{icon}</div>"
            f"<div style='font-size:12px;color:{color}'>{i+1}. {name}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

st.divider()


# ============ Step 1: 抓取热点 ============
st.header("📌 步骤 1：抓取今日热点")

col1, col2 = st.columns([1, 3])
with col1:
    if st.button("🔥 抓取热点", use_container_width=True, type="primary"):
        with st.spinner("正在抓取热点（约10秒）..."):
            try:
                import hot_topics
                import importlib
                importlib.reload(hot_topics)
                hot_data = hot_topics.fetch_all_hot_topics()
                if not hot_data["topics"]:
                    st.warning("外部热点源连不上，启用降级方案：季节性种子话题")
                    hot_data["topics"] = hot_topics.fallback_topics()
                st.session_state.hot_topics_data = hot_data
                st.session_state.current_step = 1
                st.success(f"✅ 抓到 {len(hot_data['topics'])} 条热点")
            except Exception as e:
                st.error(f"抓取失败：{e}")

with col2:
    if st.session_state.hot_topics_data:
        topics_list = st.session_state.hot_topics_data['topics']
        with st.expander(f"查看热点列表（共 {len(topics_list)} 条）", expanded=False):
            for i, t in enumerate(topics_list[:25], 1):
                st.write(f"{i:2d}. [{t['source']}] {t['title']}")


# ============ Step 2: AI 生成选题 ============
st.header("💡 步骤 2：AI 生成叙事短片选题")

if st.session_state.hot_topics_data:
    if st.button("🤖 AI 生成选题", use_container_width=False, type="primary"):
        with st.spinner("AI 正在把热点转成叙事短片构思（约 20-40 秒）..."):
            try:
                import script_generator
                import hot_topics
                import importlib
                importlib.reload(script_generator)
                importlib.reload(hot_topics)
                filtered = hot_topics.keyword_filter(st.session_state.hot_topics_data['topics'])
                topics = script_generator.generate_topics(filtered, count=3)
                st.session_state.topics = topics
                st.session_state.selected_topic_idx = None
                st.session_state.current_step = 2
                st.success(f"✅ 生成 {len(topics)} 个候选选题")
            except Exception as e:
                st.error(f"生成失败：{e}")
                st.exception(e)
else:
    st.info("请先完成步骤 1")


# 展示候选选题
if st.session_state.topics:
    st.subheader("📋 候选选题列表")
    for i, t in enumerate(st.session_state.topics):
        title = t.get('title', f'选题{i+1}')
        with st.expander(f"选题 {i+1}：{title} ｜ {t.get('genre','科幻')}", expanded=(i == 0)):
            cols = st.columns([3, 1])
            with cols[0]:
                st.write(f"**🎬 题材**：{t.get('genre','')}")
                st.write(f"**🎭 故事前提**：{t.get('premise','')}")
                st.write(f"**🎯 钩子**：{t.get('hook','')}")
                st.write(f"**📐 切入角度**：{t.get('angle','')}")
                st.write(f"**⏱️ 预计时长**：{t.get('duration_estimate','')} 秒")
                st.write(f"**🔥 来源热点**：{t.get('hot_source','')}")
            with cols[1]:
                if st.button(f"✅ 选这个", key=f"select_topic_{i}", use_container_width=True):
                    st.session_state.selected_topic_idx = i
                    st.session_state.current_step = 3
                    st.success(f"已选「{title}」，可进入步骤 3")
                    st.rerun()


# ============ Step 3: 生成剧本 ============
st.header("📝 步骤 3：生成叙事短片剧本")

if st.session_state.topics and st.session_state.selected_topic_idx is not None:
    selected = st.session_state.topics[st.session_state.selected_topic_idx]
    st.info(f"当前选题：**{selected.get('title','')}** ｜ 题材：{selected.get('genre', st.session_state.selected_genre)}")

    if st.button("🎬 AI 生成完整剧本", use_container_width=False, type="primary"):
        with st.spinner("AI 正在写三幕剧剧本（约 30-60 秒）..."):
            try:
                import script_generator
                import importlib
                importlib.reload(script_generator)
                script = script_generator.generate_script(selected)
                st.session_state.script = script
                st.session_state.current_step = 4
                st.success(f"✅ 剧本生成：{len(script.get('shots',[]))} 个镜头，{len(script.get('scenes',[]))} 个场景，{len(script.get('characters',[]))} 个角色")
                # 同步生成发布文案
                try:
                    publish_info = script_generator.generate_publish_info(selected, script)
                    st.session_state.publish_info = publish_info
                    st.success("✅ B站发布文案已生成")
                except Exception as pe:
                    st.warning(f"发布文案生成失败：{pe}")
            except Exception as e:
                st.error(f"生成失败：{e}")
                st.exception(e)
elif st.session_state.topics:
    st.info("请先在上方选择一个选题")
else:
    st.info("请先完成步骤 2")


# 展示剧本
if st.session_state.script:
    script = st.session_state.script
    st.subheader(f"📋 {script.get('title','叙事短片剧本')}")

    # 元信息
    meta_cols = st.columns(5)
    meta_cols[0].metric("总时长", f"{script.get('total_duration','?')}秒")
    meta_cols[1].metric("镜头数", len(script.get('shots',[])))
    meta_cols[2].metric("场景数", len(script.get('scenes',[])))
    meta_cols[3].metric("角色数", len(script.get('characters',[])))
    meta_cols[4].metric("题材", script.get('genre','?'))

    # 角色设定
    if script.get('characters'):
        st.subheader("👥 角色设定")
        for char in script['characters']:
            with st.expander(f"{char.get('name','?')}（{char.get('role','?')}）", expanded=False):
                st.write(f"**外貌**：{char.get('appearance','')}")
                st.write(f"**性格**：{char.get('personality','')}")
                st.write(f"**声音**：{char.get('voice','')}")

    # 场景设定
    if script.get('scenes'):
        st.subheader("🏞️ 场景设定")
        for scene in script['scenes']:
            with st.expander(f"场景{scene.get('id','?')}：{scene.get('name','')} ｜ {scene.get('location','')}", expanded=False):
                st.write(f"**时间**：{scene.get('time_of_day','')}")
                st.write(f"**天气/氛围**：{scene.get('weather','')}")
                st.write(f"**视觉描述**：{scene.get('description','')}")

    # 完整旁白
    st.subheader("🎙️ 完整旁白/对话（可直接复制到剪映 AI 配音）")
    st.text_area(
        "点击右下角复制按钮即可复制",
        value=script.get('narration_full', ''),
        height=220,
        key="narration_display",
    )

    # 分镜表
    st.subheader("🎬 分镜详情")
    for shot in script.get('shots', []):
        with st.expander(
            f"分镜 {shot['index']} ｜ 场景{shot.get('scene_id','?')} ｜ {shot.get('duration','?')}秒 ｜ {shot.get('visual_description','')[:30]}",
            expanded=False,
        ):
            sc = st.columns([2, 1])
            with sc[0]:
                st.write(f"**🎤 旁白/对话**（{len(shot.get('narration',''))}字）：")
                st.write(shot.get('narration', ''))
                st.write(f"**📷 镜头运动**：{shot.get('camera_movement','')}")
            with sc[1]:
                st.write(f"**🎬 画面描述**：")
                st.write(shot.get('visual_description', ''))
                st.write(f"**🎭 角色动作**：")
                st.write(shot.get('character_action', ''))
                st.write(f"**💧 情绪**：{shot.get('mood','')}")


# ============ Step 4: 生成角色设定卡 ============
st.header("🎨 步骤 4：生成角色设定卡和场景卡")

if st.session_state.script:
    st.info(f"""
    📐 将为 {len(st.session_state.script.get('characters',[]))} 个角色和 {len(st.session_state.script.get('scenes',[]))} 个场景生成设定卡绘画提示词。
    画风：**{st.session_state.selected_art_style}**
    你拿到提示词后去通义万相生成图片，作为可灵AI的主体参考图。
    """)

    if st.button("🎨 生成角色卡和场景卡", use_container_width=False, type="primary"):
        with st.spinner("AI 正在生成设定卡绘画提示词（约 20-40 秒）..."):
            try:
                import character_designer
                import importlib
                importlib.reload(character_designer)
                art_style = st.session_state.selected_art_style
                char_cards = character_designer.generate_character_cards(
                    st.session_state.script.get('characters', []),
                    art_style=art_style,
                )
                scene_cards = character_designer.generate_scene_cards(
                    st.session_state.script.get('scenes', []),
                    art_style=art_style,
                )
                st.session_state.character_cards = char_cards
                st.session_state.scene_cards = scene_cards
                st.session_state.current_step = 5
                st.success(f"✅ 生成 {len(char_cards)} 个角色卡 + {len(scene_cards)} 个场景卡")
            except Exception as e:
                st.error(f"生成失败：{e}")
                st.exception(e)

    # 展示角色卡
    if st.session_state.character_cards:
        st.subheader("👥 角色设定卡")
        for card in st.session_state.character_cards:
            with st.expander(f"{card.get('name','?')}（{card.get('role','?')}）设定卡", expanded=False):
                st.write(f"**主色调**：{card.get('color_palette','')}")
                st.write("**正面半身像提示词**（作为可灵主体参考图）：")
                st.code(card.get('portrait_prompt', ''), language='text')
                st.write("**三视图设定卡提示词**：")
                st.code(card.get('card_prompt', ''), language='text')
                if card.get('expression_prompts'):
                    st.write("**表情提示词**：")
                    for exp in card['expression_prompts']:
                        st.code(exp, language='text')

    # 展示场景卡
    if st.session_state.scene_cards:
        st.subheader("🏞️ 场景九宫格卡")
        for card in st.session_state.scene_cards:
            with st.expander(f"场景{card.get('scene_id','?')}：{card.get('scene_name','')} 九宫格", expanded=False):
                st.write(f"**主色调**：{card.get('color_palette','')}")
                st.write("**九宫格提示词**（9个视角锁死空间结构）：")
                st.code(card.get('grid_prompt', ''), language='text')
                st.write("**全景图提示词**：")
                st.code(card.get('wide_shot_prompt', ''), language='text')
else:
    st.info("请先完成步骤 3 生成剧本")


# ============ Step 5: 生成可灵提示词包 ============
st.header("🎥 步骤 5：生成可灵AI提示词包")

if st.session_state.script:
    st.info("""
    🔒 可灵3.0提示词包会把镜头按场景分组，每组3-4个镜头连续生成。
    - 同一场景的镜头一次性生成，保持角色和场景一致性
    - 每组消耗约10灵感值，每日66灵感值（约6组）
    - 你需要在可灵上传角色参考图作为"主体参考"
    """)

    if st.button("🎥 生成可灵提示词包", use_container_width=False, type="primary"):
        with st.spinner("正在生成可灵提示词包..."):
            try:
                import kling_prompter
                import importlib
                importlib.reload(kling_prompter)
                shot_groups = kling_prompter.generate_kling_shot_groups(
                    st.session_state.script.get('shots', []),
                    st.session_state.script.get('characters', []),
                )
                st.session_state.kling_groups = shot_groups
                st.session_state.current_step = 6
                total_groups = len(shot_groups)
                total_cost = sum(g.get('estimated_cost', 10) for g in shot_groups)
                days = (total_cost + 65) // 66  # 向上取整
                st.success(f"✅ 生成 {total_groups} 个镜头组，预计消耗 {total_cost} 灵感值，免费额度约需 {days} 天")
            except Exception as e:
                st.error(f"生成失败：{e}")
                st.exception(e)

    # 展示镜头组
    if st.session_state.kling_groups:
        st.subheader("📋 可灵拍摄指南")
        total_cost = sum(g.get('estimated_cost', 10) for g in st.session_state.kling_groups)
        st.write(f"**总览**：{len(st.session_state.kling_groups)} 组 ｜ 预计 {total_cost} 灵感值 ｜ 每日66点约需 {(total_cost+65)//66} 天")

        for group in st.session_state.kling_groups:
            with st.expander(
                f"组{group.get('group_id','?')}：{group.get('scene_name','')} ｜ {len(group.get('shots',[]))}镜头 ｜ {group.get('estimated_cost',10)}灵感值",
                expanded=False,
            ):
                # 镜头列表
                for shot in group.get('shots', []):
                    st.write(f"- 镜头{shot.get('index','?')}（{shot.get('duration','?')}s）：{shot.get('visual_description','')[:50]}")
                # 需要的角色参考图
                if group.get('character_refs'):
                    st.write(f"**需要上传的角色参考图**：{', '.join(group['character_refs'])}")
                # 合并提示词
                st.write("**合并提示词**（复制到可灵）：")
                st.code(group.get('combined_prompt', ''), language='text')
                # 操作建议
                if group.get('tips'):
                    st.info(group['tips'])
else:
    st.info("请先完成步骤 3 生成剧本")


# ============ Step 6: 打包下载 ============
st.header("📦 步骤 6：下载完整拍摄指南")

if st.session_state.script:
    if st.button("📦 打包下载完整拍摄指南", use_container_width=True, type="primary"):
        with st.spinner("正在打包 Word 文档..."):
            try:
                import script_generator
                import character_designer
                import kling_prompter
                import importlib
                importlib.reload(script_generator)
                importlib.reload(character_designer)
                importlib.reload(kling_prompter)

                selected = st.session_state.topics[st.session_state.selected_topic_idx]
                script = st.session_state.script

                # 创建 zip
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                    # 1. 剧本 Word 文档
                    script_docx = script_generator.script_to_docx(selected, script)
                    zf.writestr("1_剧本.docx", script_docx.getvalue())

                    # 2. 角色卡和场景卡 Word 文档
                    if st.session_state.character_cards or st.session_state.scene_cards:
                        cards_docx = character_designer.cards_to_docx(
                            st.session_state.character_cards or [],
                            st.session_state.scene_cards or [],
                            script.get('title', ''),
                        )
                        zf.writestr("2_角色场景设定卡.docx", cards_docx.getvalue())

                    # 3. 可灵提示词包 Word 文档
                    if st.session_state.kling_groups:
                        kling_docx = kling_prompter.kling_package_to_docx(
                            st.session_state.kling_groups,
                            script.get('title', ''),
                            len(script.get('shots', [])),
                        )
                        zf.writestr("3_可灵拍摄指南.docx", kling_docx.getvalue())

                    # 4. B站发布文案 Word 文档
                    if st.session_state.publish_info:
                        publish_docx = script_generator.publish_info_to_docx(st.session_state.publish_info)
                        zf.writestr("4_B站发布文案.docx", publish_docx.getvalue())

                    # 5. JSON 结构化数据（备用）
                    zf.writestr("script.json", json.dumps(script, ensure_ascii=False, indent=2))
                    if st.session_state.publish_info:
                        zf.writestr("publish_info.json", json.dumps(st.session_state.publish_info, ensure_ascii=False, indent=2))

                    # 6. 快速开始说明
                    has_cards = "✅" if st.session_state.character_cards else "❌"
                    has_kling = "✅" if st.session_state.kling_groups else "❌"
                    has_publish = "✅" if st.session_state.publish_info else "❌"
                    total_shots = len(script.get('shots', []))
                    total_groups = len(st.session_state.kling_groups or [])
                    total_cost = sum(g.get('estimated_cost', 10) for g in (st.session_state.kling_groups or []))
                    days = (total_cost + 65) // 66 if total_cost > 0 else 0

                    zf.writestr("0_快速开始.txt", f"""B站叙事AI短片 - 完整拍摄指南
============================================

打包内容（Word 文档格式）：
- 1_剧本.docx              完整三幕剧剧本（角色/场景/分镜）✅
- 2_角色场景设定卡.docx     角色立绘+场景九宫格的绘画提示词 {has_cards}
- 3_可灵拍摄指南.docx       可灵AI提示词包（按场景分组）{has_kling}
- 4_B站发布文案.docx        标题/简介/标签/分区 {has_publish}
- script.json              剧本结构化数据（备用）
- publish_info.json        发布文案结构化数据（备用）

数据概览：
- 总镜头数：{total_shots}
- 可灵分组数：{total_groups}
- 预计灵感值：{total_cost}（每日66免费额度，约需{days}天）

============================================
完整操作流程（按顺序执行）
============================================

【第一阶段：生成角色和场景参考图】（用通义万相，免费）
1. 打开 https://tongwan.aliyun.com/ （通义万相，用阿里云账号登录）
2. 打开「2_角色场景设定卡.docx」
3. 复制每个角色的"正面半身像提示词"到通义万相生成图片
   → 这张图将作为可灵的"主体参考图"，务必清晰
4. 复制每个角色的"三视图设定卡提示词"生成设定卡（备用）
5. 复制每个场景的"九宫格提示词"生成场景参考图
   → 这张图用于锁死空间结构，避免不同镜头场景不一致

【第二阶段：用可灵生成视频】（https://klingai.com，每日66免费灵感值）
6. 打开可灵 AI，注册登录
7. 上传主角的正面半身像作为"主体参考"
8. 打开「3_可灵拍摄指南.docx」
9. 按分组顺序，复制每组的"合并提示词"到可灵
10. 选择"多镜头连续生成"模式（同一场景的3-4个镜头一次生成）
11. 每组消耗约10灵感值，每日66点约可生成6组
12. 超出额度等次日继续，或开黄金会员（46元/月）
13. 下载所有生成的视频片段

【第三阶段：剪辑成片】（用剪映，免费）
14. 打开剪映，把所有视频片段按镜头序号拖进去
15. 打开「1_剧本.docx」，复制"完整旁白/对话"到剪映文本
16. 用剪映"智能配音"生成AI配音
17. 加字幕（思源黑体），关键词高亮
18. 按"镜头运动"列添加转场效果
19. 加BGM（按剧本bgm_mood标签去免费音乐站找）
20. 导出 1080p

【第四阶段：发布到B站】
21. 打开「4_B站发布文案.docx」
22. 复制标题、简介、标签
23. 按分区推荐选择B站分区
24. 上传视频，填写发布信息
25. 发布

============================================
常见问题
============================================

Q: 角色不一致怎么办？
A: 确保所有镜头都上传同一张主角参考图作为"主体参考"。
   可灵3.0的主体一致性>96%，但必须每批都上传参考图。

Q: 场景不一致怎么办？
A: 先用九宫格提示词生成场景参考图，在可灵生成时描述同一场景。
   同一场景的镜头用"多镜头连续生成"模式一次生成。

Q: 免费额度不够怎么办？
A: 每日66灵感值约生成6组。一条3分钟短片约需{total_groups}组，
   免费约需{days}天完成。急的话开黄金会员46元/月。

Q: 可以商用吗？
A: 可灵生成的视频内容，普通用户可用于个人创作发布。
   商业用途建议查看可灵最新授权条款。
""")

                zip_buf.seek(0)
                date_str = datetime.now().strftime('%Y%m%d')
                st.download_button(
                    label="📥 下载拍摄指南 ZIP",
                    data=zip_buf,
                    file_name=f"B站短片拍摄指南_{date_str}.zip",
                    mime="application/zip",
                    use_container_width=True,
                )
                st.success("✅ 打包完成，点击上方按钮下载")
            except Exception as e:
                st.error(f"打包失败：{e}")
                st.exception(e)
else:
    st.info("请先完成步骤 3 生成剧本")


# ============ 底部说明 ============
st.divider()
st.caption("""
💡 **提示**：
- Key 只存在当前浏览器会话，关闭页面即清除，安全无忧
- 剧本是三幕剧叙事结构（有主角、冲突、反转），不是配图解说
- 角色卡提示词用于通义万相生成参考图，场景卡用于锁死空间结构
- 可灵提示词按场景分组，同场景镜头一次生成保持一致性
- 每日66免费灵感值约生成6组视频，一条短片约需几天
- 所有文档为 Word 格式（.docx），Word/WPS 直接打开
- 建议每天用一次，选题会跟着热点变化
""")
