"""
AI 冷知识视频生产线 - 网页版
打开浏览器即用，无需命令行操作。

部署：Streamlit Community Cloud（免费）
使用：填入 API Key → 点按钮 → 下载成果
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
import requests

# 页面配置
st.set_page_config(
    page_title="AI冷知识视频生产线",
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
    'clips_map': None,
    'clips_dir': None,
    'current_step': 0,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ============ 应用配置覆盖函数 ============
def apply_keys_to_config(pixabay_key, llm_key, pexels_key):
    """把用户输入的 key 写入 config 模块和环境变量。"""
    import config
    os.environ['PIXABAY_API_KEY'] = pixabay_key
    os.environ['PEXELS_API_KEY'] = pexels_key or ''
    os.environ['LLM_API_KEY'] = llm_key
    os.environ['LLM_API_BASE'] = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    os.environ['LLM_MODEL'] = 'qwen3.7-plus'
    # config 模块用 os.getenv，需要重新加载
    import importlib
    importlib.reload(config)
    return config


def apply_params_to_config(niche, target_duration, topic_count):
    import config
    config.NICHE = niche
    config.TARGET_DURATION = target_duration
    config.TOPIC_COUNT = topic_count
    return config


# ============ 顶部标题区 ============
st.markdown("""
<div style='background:linear-gradient(90deg,#667eea 0%,#764ba2 100%);
            padding:24px 32px;border-radius:16px;margin-bottom:24px;'>
    <h1 style='color:white;margin:0;font-size:32px;'>🎬 AI 冷知识视频生产线</h1>
    <p style='color:rgba(255,255,255,0.9);margin:8px 0 0 0;font-size:16px;'>
        抓取今日热点 → AI 生成选题 → 写分镜脚本 → 下载 CC0 素材 → 你只管剪辑发布
    </p>
</div>
""", unsafe_allow_html=True)


# ============ 侧边栏：配置区 ============
with st.sidebar:
    st.header("⚙️ API Key 配置")
    st.caption("Key 仅保存在本次会话，不会上传或落盘")

    pixabay_key = st.text_input(
        "Pixabay API Key *",
        type="password",
        help="必填。去 https://pixabay.com/api/docs/ 登录后即可看到"
    )
    llm_key = st.text_input(
        "Qwen API Key *",
        type="password",
        help="必填。阿里云百炼平台 https://bailian.console.aliyun.com/ 获取"
    )
    pexels_key = st.text_input(
        "Pexels API Key（选填）",
        type="password",
        help="选填。留空时只用 Pixabay 单源，去 https://www.pexels.com/api/ 申请"
    )

    if st.button("💾 保存配置", use_container_width=True, type="primary"):
        if pixabay_key and llm_key:
            apply_keys_to_config(pixabay_key, llm_key, pexels_key)
            st.session_state.keys_configured = True
            st.success("✅ 配置已保存，可以开始使用了！")
        else:
            st.error("❌ 必填项未填：Pixabay 和 Qwen Key 都是必填的")

    st.divider()
    st.header("🎛️ 参数设置")
    niche = st.text_input("赛道定位", value="冷知识/万物原理")
    target_duration = st.slider("视频目标时长（秒）", 120, 600, 240, 60)
    topic_count = st.slider("候选选题数量", 1, 5, 3)

    if st.button("💾 应用参数", use_container_width=True):
        apply_params_to_config(niche, target_duration, topic_count)
        st.success("参数已应用")

    st.divider()
    st.caption("📚 [使用教程](https://github.com/yunmm123/shipingwenan) | 部署于 Streamlit Cloud")


# ============ 主区域：未配置时显示引导 ============
if not st.session_state.keys_configured:
    st.info("👈 请先在左侧侧边栏配置 API Key（至少填 Pixabay 和 Qwen 两个）")
    st.markdown("""
    ### 📖 使用流程
    
    1. **配置 Key**：左侧填入 Pixabay 和 Qwen 的 API Key，点保存
    2. **抓取热点**：点按钮，自动抓取抖音/微博/知乎等平台热榜
    3. **生成选题**：AI 把热点转成"反常识钩子"冷知识选题
    4. **生成脚本**：选一个选题，AI 写出分镜脚本（分镜数由选题复杂度决定）
    5. **下载素材**：自动从 Pexels/Pixabay 下载 CC0 视频素材，并根据素材时长动态调整脚本
    6. **下载交付包**：一键打包 Word 文档+素材+剪辑建议，拖进剪映即可剪辑发布
    
    ### 🆕 本次更新亮点
    
    | 功能 | 说明 |
    |------|------|
    | 动态分镜数 | AI 根据选题复杂度自行决定 6-15 个分镜，不再固定 |
    | 文案匹配时长 | 解说文案严格按 4字/秒 匹配分镜时长，不出现错位 |
    | 素材动态调整 | 下载素材后根据实际时长调整脚本，给出裁剪/慢放建议 |
    | 剪辑建议 | 每个分镜都有专属剪辑建议（截取/转场/特效/节奏） |
    | Word 文档输出 | 交付包改为 .docx 格式，Word/WPS 直接打开 |
    
    ### 🔑 没有 Key？
    
    | Key | 免费获取地址 | 说明 |
    |-----|------------|------|
    | Pixabay | https://pixabay.com/accounts/register/ | 注册后访问 /api/docs/ 直接看到 |
    | Qwen | https://bailian.console.aliyun.com/ | 阿里云百炼，注册送额度 |
    | Pexels | https://www.pexels.com/api/ | 选填，可作为第二素材源 |
    """)
    st.stop()


# ============ 主区域：工作流 ============
# 步骤进度条
st.markdown("### 📊 进度")
step_cols = st.columns(5)
steps = ["抓热点", "生成选题", "选选题", "写脚本", "下素材"]
for i, (col, name) in enumerate(zip(step_cols, steps)):
    with col:
        if st.session_state.current_step > i:
            color = "green"
            icon = "✅"
        elif st.session_state.current_step == i:
            color = "blue"
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
st.header("💡 步骤 2：AI 生成冷知识选题")

if st.session_state.hot_topics_data:
    if st.button("🤖 AI 生成选题", use_container_width=False, type="primary"):
        with st.spinner("AI 正在把热点转成冷知识选题（约 20-40 秒）..."):
            try:
                import script_generator
                import hot_topics
                import importlib
                importlib.reload(script_generator)
                importlib.reload(hot_topics)
                filtered = hot_topics.keyword_filter(st.session_state.hot_topics_data['topics'])
                topics = script_generator.generate_topics(filtered, count=topic_count)
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
        with st.expander(f"选题 {i+1}：{title}", expanded=(i == 0)):
            cols = st.columns([3, 1])
            with cols[0]:
                st.write(f"**🎯 钩子**：{t.get('hook','')}")
                st.write(f"**🔬 切入角度**：{t.get('angle','')}")
                st.write(f"**🏷️ 关键词**：{', '.join(t.get('science_keywords',[]))}")
                st.write(f"**⏱️ 预计时长**：{t.get('duration_estimate','')} 秒")
                st.write(f"**🔥 来源热点**：{t.get('hot_source','')}")
            with cols[1]:
                if st.button(f"✅ 选这个", key=f"select_topic_{i}", use_container_width=True):
                    st.session_state.selected_topic_idx = i
                    st.session_state.current_step = 3
                    st.success(f"已选「{title}」，可进入步骤 3")
                    st.rerun()


# ============ Step 3: 生成脚本 ============
st.header("📝 步骤 3：生成分镜脚本")

if st.session_state.topics and st.session_state.selected_topic_idx is not None:
    selected = st.session_state.topics[st.session_state.selected_topic_idx]
    st.info(f"当前选题：**{selected.get('title','')}**")

    if st.button("🎬 AI 生成分镜脚本", use_container_width=False, type="primary"):
        with st.spinner("AI 正在写完整分镜脚本（约 30-60 秒）..."):
            try:
                import script_generator
                import importlib
                importlib.reload(script_generator)
                script = script_generator.generate_script(selected)
                st.session_state.script = script
                st.session_state.current_step = 4
                st.success(f"✅ 生成 {len(script.get('shots',[]))} 个分镜")
                # 同步生成发布文案
                try:
                    publish_info = script_generator.generate_publish_info(selected, script)
                    st.session_state.publish_info = publish_info
                    st.success("✅ 发布文案已生成")
                except Exception as pe:
                    st.warning(f"发布文案生成失败：{pe}")
            except Exception as e:
                st.error(f"生成失败：{e}")
                st.exception(e)
elif st.session_state.topics:
    st.info("请先在上方选择一个选题")
else:
    st.info("请先完成步骤 2")


# 展示脚本
if st.session_state.script:
    script = st.session_state.script
    st.subheader(f"📋 {script.get('title','分镜脚本')}")

    # 元信息
    meta_cols = st.columns(5)
    meta_cols[0].metric("计划时长", f"{script.get('total_duration','?')}秒")
    if script.get('actual_total_duration'):
        meta_cols[1].metric("实际时长", f"{script.get('actual_total_duration')}秒", delta=f"{script.get('duration_diff',0):+d}秒")
    else:
        meta_cols[1].metric("分镜数", len(script.get('shots',[])))
    meta_cols[2].metric("分镜数", len(script.get('shots',[])))
    meta_cols[3].metric("BGM 情绪", script.get('bgm_mood','curious'))
    meta_cols[4].metric("赛道", niche)

    # 完整解说文案
    st.subheader("🎙️ 完整解说文案（可直接复制到剪映 AI 配音）")
    narration = script.get('narration_full', '')
    st.text_area(
        "点击右下角复制按钮即可复制",
        value=narration,
        height=220,
        key="narration_display",
    )

    # 分镜表（含剪辑建议）
    st.subheader("🎬 分镜详情（含剪辑建议）")
    for shot in script.get('shots', []):
        # 如果有实际时长信息，显示在标题中
        if shot.get('actual_duration'):
            header = f"分镜 {shot['index']} ｜ 计划{shot.get('duration','?')}s → 实际{shot.get('actual_duration','?')}s ｜ 素材{shot.get('clip_duration','无')}s ｜ {shot.get('visual_note','')[:25]}"
        else:
            header = f"分镜 {shot['index']} ｜ {shot.get('duration','?')}秒 ｜ {shot.get('visual_note','')[:30]}"
        with st.expander(header, expanded=False):
            sc = st.columns([2, 1])
            with sc[0]:
                st.write(f"**🎤 解说词**（{len(shot.get('narration',''))}字，约{len(shot.get('narration',''))/4:.1f}秒）：")
                st.write(shot.get('narration', ''))
                st.write(f"**🎬 剪辑建议**：")
                st.info(shot.get('editing_tip', '无'))
            with sc[1]:
                st.write(f"**🖼️ 画面建议**：")
                st.write(shot.get('visual_note', ''))
                st.write(f"**🔍 搜索关键词**：")
                st.write(", ".join(shot.get('keywords', [])))
                # 如果有调整建议，显示
                if shot.get('adjust_tip'):
                    st.write(f"**🔧 素材调整建议**：")
                    st.warning(shot.get('adjust_tip', ''))


# ============ Step 3.5: 生成发布文案 ============
st.header("📣 步骤 3.5：生成抖音发布文案")

if st.session_state.script:
    if st.button("✍️ AI 生成发布文案（标题/描述/话题）", use_container_width=False, type="primary"):
        with st.spinner("AI 正在写发布文案（约 15-30 秒）..."):
            try:
                import script_generator
                import importlib
                importlib.reload(script_generator)
                selected = st.session_state.topics[st.session_state.selected_topic_idx]
                publish_info = script_generator.generate_publish_info(selected, st.session_state.script)
                st.session_state.publish_info = publish_info
                st.success("✅ 发布文案已生成，可打包下载")
                st.rerun()
            except Exception as e:
                st.error(f"生成失败：{e}")
                st.exception(e)
elif st.session_state.topics:
    st.info("请先生成分镜脚本")
else:
    st.info("请先完成步骤 3")


# ============ 发布文案展示 ============
if st.session_state.publish_info:
    publish_info = st.session_state.publish_info
    st.subheader("📣 发布文案（剪完直接用）")

    # 用三列展示核心信息
    p1, p2, p3 = st.columns(3)
    with p1:
        st.metric("标题字数", f"{len(publish_info.get('title',''))}/25")
    with p2:
        st.metric("描述字数", f"{len(publish_info.get('description',''))}/200")
    with p3:
        st.metric("话题数", f"{len(publish_info.get('hashtags',[]))}/5")

    with st.expander("📋 查看完整发布文案（点击展开复制）", expanded=True):
        st.write(f"**📌 作品标题**")
        st.code(publish_info.get('title', ''), language='text')

        st.write(f"**📝 作品描述**")
        st.code(publish_info.get('description', ''), language='text')

        st.write(f"**🏷️ 相关话题**")
        st.code(" ".join(publish_info.get('hashtags', [])), language='text')

        st.write(f"**🖼️ 封面建议**：{publish_info.get('cover_suggestion', '')}")
        st.write(f"**💡 发布建议**：{publish_info.get('publish_tips', '')}")



# ============ Step 4: 下载素材 + 打包 ============
st.header("🎥 步骤 4：下载 CC0 素材并打包")

st.info("""
🔒 **素材合规自动过滤已启用**：下载时会自动过滤以下不合规素材，遵守 Pexels/Pixabay 内容使用条款：
- ✗ 含可识别商标/品牌/标志的素材（不得用于商业目的）
- ✗ 涉及可识别人物的素材（肖像权风险）
- ✗ 可能涉及误导/欺骗性的素材（如虚假医疗宣传）
- ✗ 下载的素材仅用于二次创作发布，不得单独销售或作为商标使用
""")

if st.session_state.script:
    col_dl, col_pkg = st.columns(2)

    with col_dl:
        if st.button("⬇️ 下载 CC0 视频素材", use_container_width=True, type="primary"):
            with st.spinner("正在并发下载素材（约 1-2 分钟）..."):
                try:
                    import stock_api
                    import importlib
                    importlib.reload(stock_api)
                    clips_dir = Path(tempfile.gettempdir()) / f"clips_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    clips_map = stock_api.fetch_all_clips(
                        st.session_state.script['shots'],
                        clips_dir,
                    )
                    st.session_state.clips_map = clips_map
                    st.session_state.clips_dir = clips_dir
                    success = sum(1 for v in clips_map.values() if v)
                    total = len(st.session_state.script['shots'])
                    st.session_state.current_step = 5

                    # 根据实际素材动态调整脚本时长
                    try:
                        import script_generator
                        importlib.reload(script_generator)
                        st.session_state.script = script_generator.adjust_script_to_clips(
                            st.session_state.script, clips_map
                        )
                        actual_dur = st.session_state.script.get('actual_total_duration', '?')
                        planned_dur = st.session_state.script.get('planned_total_duration', '?')
                        diff = st.session_state.script.get('duration_diff', 0)
                        st.success(f"✅ {success}/{total} 个分镜抓到素材｜计划{planned_dur}s → 实际{actual_dur}s（{diff:+d}s）")
                        st.info("📐 脚本已根据实际素材时长动态调整，请查看各分镜的「素材调整建议」")
                    except Exception as adj_e:
                        st.warning(f"素材调整失败（不影响下载）：{adj_e}")
                        st.success(f"✅ {success}/{total} 个分镜抓到素材")
                except Exception as e:
                    st.error(f"下载失败：{e}")
                    st.exception(e)

    # 显示下载结果
    if st.session_state.clips_map:
        with st.expander(f"📊 素材下载情况（共 {len(st.session_state.clips_map)} 个分镜）"):
            for idx, clips in sorted(st.session_state.clips_map.items()):
                if clips:
                    c = clips[0]
                    st.write(f"✅ 分镜 {idx}: [{c['source']}] {c['width']}x{c['height']} {c.get('duration','?')}s")
                else:
                    st.write(f"❌ 分镜 {idx}: 未抓到（可手动去网站搜）")

    # 打包下载
    with col_pkg:
        if st.session_state.clips_map is not None:
            if st.button("📦 打包下载完整交付包", use_container_width=True, type="primary"):
                with st.spinner("正在打包（生成 Word 文档 + 素材）..."):
                    try:
                        import script_generator
                        import importlib
                        importlib.reload(script_generator)
                        selected = st.session_state.topics[st.session_state.selected_topic_idx]

                        # 生成 Word 文档（分镜脚本）
                        script_docx_buf = script_generator.script_to_docx(
                            selected,
                            st.session_state.script,
                            st.session_state.clips_map,
                        )

                        # 生成 manifest.csv
                        import csv
                        csv_buf = io.StringIO()
                        writer = csv.writer(csv_buf)
                        writer.writerow(["分镜序号", "计划时长", "实际时长", "素材时长", "素材文件名", "素材来源", "画面建议", "剪辑建议", "素材调整建议"])
                        for shot in st.session_state.script.get('shots', []):
                            idx = shot['index']
                            clips = st.session_state.clips_map.get(idx, [])
                            filename = ""
                            source = ""
                            if clips and 'local_path' in clips[0]:
                                filename = os.path.basename(clips[0]['local_path'])
                                source = clips[0]['source']
                            writer.writerow([
                                idx,
                                shot.get('duration',''),
                                shot.get('actual_duration', shot.get('duration','')),
                                shot.get('clip_duration', ''),
                                filename, source,
                                shot.get('visual_note','')[:50],
                                shot.get('editing_tip','')[:80],
                                shot.get('adjust_tip','')[:80],
                            ])

                        # BGM 推荐
                        import stock_api
                        import importlib
                        importlib.reload(stock_api)
                        bgm_mood = st.session_state.script.get('bgm_mood', 'curious')
                        bgm_recs = stock_api.recommend_bgm(bgm_mood)

                        # 创建 zip
                        zip_buf = io.BytesIO()
                        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                            # Word 文档（主交付格式）
                            zf.writestr("分镜脚本.docx", script_docx_buf.getvalue())

                            # JSON 结构化数据（备用）
                            zf.writestr("script.json", json.dumps(st.session_state.script, ensure_ascii=False, indent=2))

                            # 发布文案（Word 文档）
                            if st.session_state.publish_info:
                                publish_info = st.session_state.publish_info
                                publish_docx_buf = script_generator.publish_info_to_docx(publish_info)
                                zf.writestr("发布文案.docx", publish_docx_buf.getvalue())
                                zf.writestr("publish_info.json", json.dumps(publish_info, ensure_ascii=False, indent=2))

                            zf.writestr("manifest.csv", csv_buf.getvalue())
                            zf.writestr("bgm_suggestions.json", json.dumps({
                                "mood": bgm_mood,
                                "sources": bgm_recs,
                            }, ensure_ascii=False, indent=2))

                            # 快速开始说明
                            has_publish = "✅" if st.session_state.publish_info else "❌"
                            zf.writestr("快速开始.txt", f"""打包内容（Word 文档格式）：
- 分镜脚本.docx       分镜脚本（含剪辑建议、素材调整建议）✅
- 发布文案.docx       发布文案（标题/描述/话题，含复制清单）{has_publish}
- script.json         脚本结构化数据（备用）
- publish_info.json   发布文案结构化数据（备用）
- manifest.csv        剪辑清单（分镜对应哪个素材+剪辑建议）
- bgm_suggestions.json  配乐推荐
- clips/              已下载的 CC0 视频素材

【脚本说明】
- 分镜数量由选题复杂度决定（不固定）
- 解说文案字数严格匹配分镜时长（4字/秒）
- 下载素材后已根据实际时长动态调整，请看「素材调整建议」列

【剪辑阶段】
1. 打开「分镜脚本.docx」，查看每个分镜的剪辑建议
2. 打开剪映，把 clips/ 里的视频按 manifest.csv 顺序拖进去
3. 把脚本中的「完整解说文案」复制到剪映文本 → 智能配音
4. 按每个分镜的「剪辑建议」处理素材（截取/慢放/转场等）
5. 按「素材调整建议」处理文案与素材的时长差异
6. 按 bgm_suggestions.json 推荐下配乐
7. 字幕用思源黑体，加关键词高亮
8. 导出 1080p 横屏

【发布阶段】
9. 打开「发布文案.docx」，复制标题、描述、话题
10. 按封面建议做封面，按发布建议选时机
11. 发布到抖音
""") 
                            # 添加视频文件
                            for idx, clips in st.session_state.clips_map.items():
                                for clip in clips:
                                    if 'local_path' in clip and os.path.exists(clip['local_path']):
                                        arcname = f"clips/{os.path.basename(clip['local_path'])}"
                                        zf.write(clip['local_path'], arcname)

                        zip_buf.seek(0)
                        date_str = datetime.now().strftime('%Y%m%d')
                        st.download_button(
                            label="📥 下载交付包 ZIP",
                            data=zip_buf,
                            file_name=f"交付包_{date_str}.zip",
                            mime="application/zip",
                            use_container_width=True,
                        )
                        st.success("✅ 打包完成，点击上方按钮下载（Word 文档格式）")
                    except Exception as e:
                        st.error(f"打包失败：{e}")
                        st.exception(e)
else:
    st.info("请先完成步骤 3 生成脚本")


# ============ 底部说明 ============
st.divider()
st.caption("""
💡 **提示**：
- Key 只存在当前浏览器会话，关闭页面即清除，安全无忧
- 分镜数量由 AI 根据选题复杂度决定（6-15个），不固定
- 解说文案严格匹配分镜时长（4字/秒），不会出现文案与视频时长错位
- 下载素材后系统会根据实际素材时长动态调整脚本，请查看「素材调整建议」
- 每个分镜都有专属「剪辑建议」，告诉你怎么截取、转场、加特效
- 交付包为 Word 文档（.docx）格式，直接用 Word/WPS 打开
- 如果某分镜没抓到素材，可手动去 [Pexels](https://www.pexels.com/zh-cn/videos/) 或 [Pixabay](https://pixabay.com/videos/) 搜中文关键词
- 热点抓取失败是正常的，会自动降级到季节性种子话题，不影响使用
- 建议每天用一次，选题会跟着热点变化
""")
