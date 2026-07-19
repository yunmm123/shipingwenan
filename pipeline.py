"""
编排主控模块
把 5 个步骤串成一条流水线，输出完整的交付包到 output/{date}/

用法：
  python pipeline.py                 # 全自动跑完整流程
  python pipeline.py --topic-only    # 只到选题，不抓素材（省时间预览）
  python pipeline.py --dry-run       # 不下载素材，只生成脚本和清单
"""
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import config
import hot_topics
import stock_api
import script_generator


def ensure_output_dir() -> Path:
    """创建当日输出目录。"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    out = config.OUTPUT_DIR / date_str
    (out / "clips").mkdir(parents=True, exist_ok=True)
    return out


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[输出] {path}")


def save_text(path: Path, text: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[输出] {path}")


def build_manifest(shots: list, clips_map: dict) -> str:
    """生成剪辑清单 CSV，用户照着这个拖素材进剪映。"""
    rows = [["分镜序号", "时长(秒)", "解说词摘要", "素材文件名", "素材来源", "画面建议"]]
    for shot in shots:
        idx = shot["index"]
        clips = clips_map.get(idx, [])
        filename = clips[0]["local_path"].split("/")[-1] if clips else "（未抓到素材）"
        source = clips[0]["source"] if clips else ""
        narration = shot.get("narration", "")[:40] + "..."
        rows.append([
            idx,
            shot.get("duration", ""),
            narration,
            filename,
            source,
            shot.get("visual_note", ""),
        ])
    # 写成字符串
    import io
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


def run_pipeline(topic_only: bool = False, dry_run: bool = False, pick_index: int = None):
    """主流程。"""
    print("=" * 60)
    print(f"AI 冷知识视频生产线 启动 @ {datetime.now().isoformat(timespec='seconds')}")
    print(f"赛道：{config.NICHE}  目标时长：{config.TARGET_DURATION}s")
    print("=" * 60)

    out_dir = ensure_output_dir()

    # ===== Step 1: 抓取热点 =====
    print("\n▶ STEP 1/5 抓取当日热点")
    hot_data = hot_topics.fetch_all_hot_topics()
    save_json(out_dir / "hot_topics_raw.json", hot_data)

    if not hot_data["topics"]:
        print("[警告] 所有外部热点源都连不上，启用降级方案：用季节性种子话题")
        hot_data["topics"] = hot_topics.fallback_topics()
        hot_data["fallback"] = True

    # 规则预过滤
    filtered = hot_topics.keyword_filter(hot_data["topics"])
    print(f"[热点] 规则过滤后保留 {len(filtered)} 条")

    # ===== Step 2+3: AI 生成选题 =====
    print("\n▶ STEP 2/5 AI 匹配热点 → 生成冷知识选题")
    topics = script_generator.generate_topics(filtered, count=config.TOPIC_COUNT)
    save_json(out_dir / "topics.json", {
        "date": hot_data["date"],
        "fetched_at": hot_data["fetched_at"],
        "candidates": topics,
    })

    if topic_only:
        print("\n[完成] --topic-only 模式，仅生成选题，结束。")
        print(f"查看：{out_dir / 'topics.json'}")
        return topics

    # 选一个执行（默认第一个，可指定）
    idx = pick_index if pick_index is not None else 0
    chosen = topics[idx]
    print(f"\n[选定] 执行第 {idx+1} 个选题：{chosen.get('title')}")

    # ===== Step 4: 生成分镜脚本 =====
    print("\n▶ STEP 3/6 生成分镜脚本")
    script = script_generator.generate_script(chosen)
    md = script_generator.script_to_markdown(chosen, script)
    save_text(out_dir / "script.md", md)
    save_json(out_dir / "script.json", script)

    # ===== Step 4.5: 生成发布信息 =====
    print("\n▶ STEP 4/6 生成抖音发布文案（标题/描述/话题）")
    publish_info = script_generator.generate_publish_info(chosen, script)
    save_json(out_dir / "publish_info.json", publish_info)
    publish_md = script_generator.publish_info_to_markdown(publish_info)
    save_text(out_dir / "发布文案.md", publish_md)

    # ===== Step 5: 抓取素材 =====
    if dry_run:
        print("\n▶ STEP 5/6 [跳过] --dry-run 模式，不下载素材")
        clips_map = {}
    else:
        print("\n▶ STEP 5/6 并发抓取素材（Pexels + Pixabay）")
        clips_map = stock_api.fetch_all_clips(script["shots"], out_dir / "clips")
        success = sum(1 for v in clips_map.values() if v)
        total = len(script["shots"])
        print(f"[素材] {success}/{total} 个分镜成功抓到素材")

    # ===== 生成清单 + BGM 推荐 =====
    print("\n▶ STEP 6/6 生成剪辑清单与配乐推荐")
    manifest = build_manifest(script["shots"], clips_map)
    save_text(out_dir / "manifest.csv", manifest)

    bgm_mood = script.get("bgm_mood", "curious")
    bgm = stock_api.recommend_bgm(bgm_mood)
    save_json(out_dir / "bgm_suggestions.json", {"mood": bgm_mood, "sources": bgm})

    # ===== 汇总 =====
    print("\n" + "=" * 60)
    print("✅ 生产线完成！交付包位置：")
    print(f"   {out_dir}")
    print("=" * 60)
    print(f"""
📁 目录结构：
  {out_dir}/
  ├── topics.json           # 所有候选选题（{len(topics)} 个）
  ├── script.md             # 分镜脚本（人类可读，剪辑对照用）
  ├── script.json           # 分镜脚本（结构化）
  ├── publish_info.json     # 发布文案（标题/描述/话题，结构化）
  ├── 发布文案.md           # 发布文案（人类可读，含复制清单）
  ├── manifest.csv          # 剪辑清单（分镜→素材文件名映射）
  ├── bgm_suggestions.json  # 配乐推荐
  ├── hot_topics_raw.json   # 原始热点数据
  └── clips/                # 已下载的 CC0 素材
      {len([f for f in (out_dir / 'clips').glob('*.mp4')])} 个文件

🎬 下一步（手动 5 分钟）：
  【剪辑阶段】
  1. 打开剪映，把 clips/ 里的视频按 manifest.csv 顺序拖进去
  2. 把 script.md 里「完整解说文案」复制到剪映文本 → 智能配音
  3. 按 bgm_suggestions.json 推荐去对应站点下配乐
  4. 加字幕（思源黑体）+ 关键词高亮
  5. 导出 1080p 横屏

  【发布阶段】
  6. 打开「发布文案.md」，复制标题、描述、话题
  7. 按封面建议做封面，按发布建议选时机
  8. 发布到抖音
""")
    return {"out_dir": str(out_dir), "topic": chosen, "script": script, "clips": clips_map, "publish_info": publish_info}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI 冷知识视频生产线")
    parser.add_argument("--topic-only", action="store_true", help="只生成选题，不抓素材")
    parser.add_argument("--dry-run", action="store_true", help="生成脚本但不下载素材")
    parser.add_argument("--pick", type=int, default=None, help="指定执行第几个选题（从0开始）")
    args = parser.parse_args()

    run_pipeline(topic_only=args.topic_only, dry_run=args.dry_run, pick_index=args.pick)
