"""
配置文件
所有 API Key 和可调参数集中管理。
使用前请把 .env.example 复制为 .env 并填入真实 Key。
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # 没装 python-dotenv 也能直接读环境变量

# ============ API Keys ============
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")

# LLM 配置：默认用 OpenAI 兼容接口，可换成 DeepSeek/豆包/Kimi 等
LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# ============ 热点源 ============
# DailyHotApi 自部署地址，默认官方演示站（限流，生产建议自部署）
# 自部署：git clone https://github.com/imsyy/DailyHotApi && 部署到 Vercel/Cloudflare
DAILYHOT_BASE = os.getenv("DAILYHOT_BASE", "https://api.vvhan.com")
# 优先抓这几个平台的热榜
HOT_SOURCES = ["douyin", "weibo", "zhihu", "baidu", "toutiao"]

# ============ 选题与脚本 ============
# 赛道定位，影响 AI prompt
NICHE = "B站叙事AI短片"
# 每次生成的选题数量
TOPIC_COUNT = 3
# 视频目标时长（秒），3-5 分钟区间，仅作参考，实际时长根据素材动态调整
TARGET_DURATION = 240  # 4 分钟（3-5 分钟区间基准）
# 中文旁白/对白语速（字/秒），用于严格匹配旁白与镜头时长
# 短视频解说一般 3.5-4.5 字/秒，取 4 为基准
NARRATION_CHARS_PER_SEC = 4
# 镜头数量范围（AI 根据剧本复杂度自行决定，不固定）
MIN_SHOTS = 6
MAX_SHOTS = 15
# 题材类型选项（叙事短片的题材分类）
GENRE_OPTIONS = ["科幻", "悬疑", "哲理", "奇幻", "都市", "恐怖"]
# 默认题材（选题未指定题材时使用）
DEFAULT_GENRE = "科幻"

# ============ 素材抓取 ============
# 每个分镜最多抓 N 个候选素材，选最好的 1 个
CLIPS_PER_SHOT = 3
# 视频时长范围（秒）
MIN_CLIP_DURATION = 5
MAX_CLIP_DURATION = 30
# 视频最小宽度（横屏）
MIN_WIDTH = 1280
# 优先横屏
ORIENTATION = "landscape"
# 并发下载数
MAX_CONCURRENT_DOWNLOADS = 4

# ============ 路径 ============
WORKSPACE = Path(__file__).parent
OUTPUT_DIR = WORKSPACE / "output"

# ============ 输出目录结构 ============
# output/
#   2026-07-19/
#     topic.json          # 选题 + 热点来源
#     script.md           # 分镜脚本
#     manifest.csv        # 剪辑清单（分镜序号/文件名/时长/建议）
#     clips/              # 下载好的视频素材
#       shot01_pexels_xxx.mp4
#       shot02_pixabay_xxx.mp4
#     bgm_suggestions.json # 推荐配乐
