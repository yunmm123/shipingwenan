# AI 冷知识视频生产线

把"抓热点 → 选选题 → 写脚本 → 下素材"四步用 AI 自动化，你只需做最后的剪辑和发布。

## 🌐 在线使用（推荐）

**打开即用，无需安装任何东西：**

👉 **[https://cold-knowledge.streamlit.app/](https://cold-knowledge.streamlit.app/)**

在网页左侧填入 API Key → 按 5 步点击 → 下载交付包 → 拖进剪映发布。

## 📥 离线使用

**不想用网页？下载打包好的 zip 本地跑：**

1. 访问本仓库的 **[Releases 页面](../../releases)**
2. 下载最新版 `shipingwenan.zip`
3. 解压后按里面的「快速开始.txt」操作

或者去 **[Actions 页面](../../actions)** → 点最新一次运行 → 下拉到 Artifacts 下载。

## 适用场景

- 抖音"冷知识 / 万物原理"赛道（不露脸、纯二创）
- 没有原创拍摄素材，靠 CC0 空镜 + AI 配音 + 字幕成片
- 想借助当日热点提升完播率和关注转化

## 架构

```
热点源 ──► 规则过滤 ──► AI 选题 ──► AI 脚本 ──► 素材 API ──► 交付包
(8个官方源)   (黑白名单)   (LLM)      (LLM)    (Pexels+Pixabay)  (output/)
```

## 热点数据源（8 个官方源 + 备用）

| 优先级 | 数据源 | 抓取方式 | 单次数据量 |
|--------|--------|---------|-----------|
| 1 | 百度热搜 | 官方页面爬取 | ~50 条 |
| 2 | 今日头条热榜 | 官方 JSON API | ~50 条 |
| 3 | 抖音热搜 | 官方 API | ~50 条 |
| 4 | 知乎热榜 | 官方 API | ~30 条 |
| 5 | B站热搜 | 官方 API | ~30 条 |
| 6 | 澎湃新闻热榜 | 官方 API | ~20 条 |
| 7 | 豆瓣热门电影 | 官方 API | ~20 条 |
| 8 | IT之家热榜 | 官方 API | ~10 条 |
| 备用 | DailyHotApi 聚合站 | 第三方站 | 视情况 |

**实测在沙箱环境可抓取 250+ 条真实热点**，每条带真实热度值，AI 会从中挑选最适合做冷知识科普的选题。
                                                                  ↓
                                                          你手动剪辑发布
```

## 快速开始

### 1. 装 Python 包

```bash
cd ai-cold-knowledge-pipeline
pip install -r requirements.txt
```

### 2. 申请 3 个免费 API Key

| Key | 申请地址 | 用途 | 免费额度 |
|-----|---------|------|---------|
| Pexels API | https://www.pexels.com/api/ | 视频素材搜索 | 200 req/h |
| Pixabay API | https://pixabay.com/accounts/register/ | 视频素材搜索 | 100 req/min |
| LLM API | https://platform.deepseek.com/（或豆包/Kimi） | 选题+脚本生成 | 注册送额度 |

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入上面 3 个 Key
```

### 4. 一键运行

```bash
# 全自动：抓热点 → 选题 → 脚本 → 下素材
python pipeline.py

# 只生成选题，快速预览（不下素材）
python pipeline.py --topic-only

# 生成脚本但不下素材（省时间看脚本质量）
python pipeline.py --dry-run

# 指定用第 2 个候选选题执行（从 0 开始）
python pipeline.py --pick 1
```

运行完成后，交付包在 `output/YYYY-MM-DD/`。

## 输出文件说明

| 文件 | 用途 |
|------|------|
| `topics.json` | 所有候选选题（含热点来源、科普关键词） |
| `script.md` | 人类可读的分镜脚本，剪辑时对照用 |
| `script.json` | 结构化脚本（程序消费用） |
| `manifest.csv` | 剪辑清单：每个分镜对应哪个素材文件 |
| `clips/` | 已下载的 CC0 视频素材 |
| `bgm_suggestions.json` | 配乐推荐（按脚本情绪标签） |
| `hot_topics_raw.json` | 原始热点数据（留档） |

## 剪辑发布流程（手动 5 分钟）

1. 打开**剪映**，新建横屏项目（16:9）
2. 把 `clips/` 里的视频按 `manifest.csv` 的分镜序号顺序拖进去
3. 把 `script.md` 里「完整解说文案」整段复制到剪映文本框 → 点「智能配音」
4. 按 `bgm_suggestions.json` 推荐去 Mixkit / Audionautix 下一首配乐
5. 字幕用**思源黑体**，关键词加高亮色
6. 导出 1080p 横屏，标题用选题标题，发布到抖音

## 进阶配置

编辑 `config.py` 可调：

- `NICHE`：赛道定位（改成"宇宙探秘""历史奇闻"等）
- `TARGET_DURATION`：目标视频时长（秒）
- `HOT_SOURCES`：热点平台列表（支持 douyin/weibo/zhihu/baidu/toutiao/bilibili 等）
- `MIN_WIDTH` / `ORIENTATION`：素材分辨率和方向
- `MAX_CONCURRENT_DOWNLOADS`：并发下载数

## 自部署热点源（推荐生产用）

默认用的 `api.vvhan.com` 是公共演示站，有限流。长期用建议自部署 DailyHotApi：

```bash
# Vercel 一键部署
git clone https://github.com/imsyy/DailyHotApi
cd DailyHotApi
# 按 README 部署到 Vercel，拿到自己的域名后填到 .env
# DAILYHOT_BASE=https://your-dailyhot.vercel.app
```

## 常见问题

**Q: Pexels/Pixabay 搜不到某个关键词的素材？**
A: 关键词用英文更准。脚本生成时已强制要求 AI 给英文关键词。若某分镜无结果，会在 `manifest.csv` 标注「未抓到素材」，可手动去 Pexels 网站搜中文备选。

**Q: AI 生成的脚本配音听起来不像人？**
A: 剪映的"智能配音"选「电台男声」或「纪录片解说」音色最自然。语速调到 1.1x。

**Q: 会不会被判搬运？**
A: 不会。流程产出的是"AI 解说文案 + CC0 空镜 + 自己的字幕"，属于原创二创。不要直接用原纪录片画面+原声。

**Q: 每天能跑几次？**
A: Pexels 200 req/h、Pixabay 100 req/min、LLM 看你的额度。一条视频约消耗 20-30 次 API 调用，一天跑 5-10 条无压力。

## 文件结构

```
ai-cold-knowledge-pipeline/
├── config.py              # 配置中心
├── hot_topics.py          # Step 1-2: 热点抓取 + 规则过滤
├── stock_api.py           # Step 5: Pexels + Pixabay 素材抓取
├── script_generator.py    # Step 3-4: AI 选题 + 脚本生成
├── pipeline.py            # 主控编排
├── requirements.txt
├── .env.example
├── README.md
└── output/                # 运行产物（自动生成）
    └── 2026-07-19/
        ├── topics.json
        ├── script.md
        ├── manifest.csv
        ├── clips/
        └── ...
```

## License

代码 MIT。素材授权遵循各平台协议（Pexels/Pixabay 均 CC0 可商用）。
