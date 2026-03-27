# Bilibili 视频下载工具 - 设计文档

## 1. 项目概述

一个基于 Python 的 Bilibili 视频/音频/封面下载工具，提供终端交互界面（TUI），支持搜索 UP 主、浏览视频列表、多选下载，并具备下载历史记录与失败重试功能。

## 2. 核心功能

### 2.1 搜索 UP 主
- 输入关键词搜索 UP 主
- 展示搜索结果：头像、昵称、粉丝数、视频数、简介
- 选择目标 UP 主进入视频列表

### 2.2 视频列表展示
- 分页加载指定 UP 主的全部视频
- 每条显示：序号、标题、时长、播放量、发布日期、是否充电专属
- 充电计划视频高亮标识（如 `[充电]` 标签），支持一键筛选隐藏
- 支持按发布时间/播放量排序

### 2.3 多选下载
- 支持多选视频（可全选/反选）
- 每个视频可独立选择下载类型：
  - **视频**（视频流 + 音频流合并为 MP4）
  - **仅音频**（MP3/M4A）
  - **封面图片**（原图）
- 也可统一设置下载类型，批量应用

### 2.4 封面处理
- 下载原始封面图片
- 可选功能：将封面填充为正方形（以原图短边为基准，长边方向两侧填充纯色/模糊背景居中）
- 填充颜色默认为黑色，可配置

### 2.5 下载管理
- 显示整体进度与单文件进度（进度条 + 百分比 + 速度）
- 不支持单文件断点续传
- 并发下载（可配置并发数，默认 3）

### 2.6 下载历史与重试
- 以 JSON 文件记录每次下载历史（状态、时间、路径、错误信息）
- 状态：`completed` / `failed` / `skipped`
- 提供查看历史、筛选失败记录、手动重试失败项的功能
- 重复下载时自动检测已下载文件，跳过已完成项

### 2.7 文件组织
- 目录结构：`<下载根目录>/<UP主名称>/`
- 文件命名：`<视频标题>_<BV号>.<扩展名>`
  - 视频：`.mp4`
  - 音频：`.mp3` 或 `.m4a`
  - 封面：`.jpg` / `_square.jpg`（正方形版本）
- 文件创建时间（mtime）设置为视频的发布时间

## 3. 技术架构

### 3.1 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.10+ | 异步支持好，生态丰富 |
| HTTP 客户端 | `httpx` | 支持异步、HTTP/2，性能优于 requests |
| TUI 框架 | `rich` + `questionary` | rich 提供美观表格/进度条，questionary 提供交互选择 |
| 视频合并 | `ffmpeg`（外部依赖） | 合并 DASH 视频流和音频流 |
| 图片处理 | `Pillow` | 封面填充为正方形 |
| 数据存储 | JSON 文件 | 下载历史、配置，无需数据库 |

### 3.2 项目结构

```
bili-downloader/
├── main.py                  # 入口，主交互流程
├── config.py                # 配置管理
├── requirements.txt         # 依赖列表
│
├── api/                     # Bilibili API 封装
│   ├── __init__.py
│   ├── client.py            # HTTP 客户端基类（统一 headers、cookie、限速）
│   ├── auth.py              # WBI 签名、Cookie 管理
│   ├── search.py            # 搜索 UP 主
│   ├── space.py             # 获取 UP 主视频列表
│   └── video.py             # 获取视频详情、播放地址、cid
│
├── core/                    # 核心业务逻辑
│   ├── __init__.py
│   ├── downloader.py        # 下载引擎（视频/音频/封面下载、合并）
│   ├── history.py           # 下载历史管理
│   └── cover.py             # 封面图片处理（正方形填充）
│
├── ui/                      # 终端交互界面
│   ├── __init__.py
│   ├── search_view.py       # 搜索 UP 主界面
│   ├── video_list_view.py   # 视频列表 & 多选界面
│   ├── download_view.py     # 下载进度界面
│   └── history_view.py      # 下载历史 & 重试界面
│
├── utils/                   # 工具函数
│   ├── __init__.py
│   ├── file_utils.py        # 文件命名清洗、时间戳设置
│   └── format_utils.py      # 格式化时长、文件大小等
│
└── data/                    # 运行时数据（自动生成）
    ├── config.json           # 用户配置
    └── history.json          # 下载历史
```

### 3.3 模块设计

#### 3.3.1 API 层 (`api/`)

**`client.py` - HTTP 客户端**
```
class BiliClient:
    - base_url = "https://api.bilibili.com"
    - 统一 headers: User-Agent, Referer
    - Cookie 管理（SESSDATA 可选，影响画质上限）
    - 请求限速（默认间隔 300ms，防封）
    - 自动重试（网络错误重试 3 次）
    - 统一响应解析：检查 code == 0
```

**`auth.py` - WBI 签名**
```
class WbiSigner:
    - fetch_wbi_keys()        # 从 /x/web-interface/nav 获取 img_key、sub_key
    - generate_w_rid(params)  # 根据参数计算 w_rid 签名
    - 缓存 key（有效期内不重复获取）
```

**`search.py` - 搜索**
```
async search_users(keyword, page=1, page_size=20) -> SearchResult:
    # GET /x/web-interface/search/type?search_type=bili_user
    # 返回: [{mid, uname, fans, videos, usign, upic, level}, ...]
```

**`space.py` - UP 主空间**
```
async get_user_videos(mid, page=1, page_size=50, order="pubdate") -> VideoListResult:
    # GET /x/space/wbi/arc/search（需 WBI 签名）
    # 返回: {videos: [{bvid, title, pic, length, created, play, is_charge_plus}, ...], total}

async get_all_user_videos(mid) -> list[VideoInfo]:
    # 自动分页，获取全部视频
```

**`video.py` - 视频详情 & 播放地址**
```
async get_video_pages(bvid) -> list[PageInfo]:
    # GET /x/player/pagelist?bvid=xxx
    # 返回: [{cid, page, part, duration}, ...]

async get_play_url(bvid, cid, quality=80) -> PlayUrlResult:
    # GET /x/player/playurl?bvid=xxx&cid=xxx&fnval=16
    # 返回: {video_urls: [...], audio_urls: [...], quality, accept_quality}
```

#### 3.3.2 核心层 (`core/`)

**`downloader.py` - 下载引擎**
```
class Downloader:
    - max_concurrent: int = 3                 # 最大并发数
    - download_dir: str                       # 下载根目录

    async download_video(task: DownloadTask):
        1. 获取 video pages (cid)
        2. 获取 DASH 播放地址
        3. 选择最高可用画质的视频流
        4. 下载视频流 -> temp_video.m4s
        5. 下载音频流 -> temp_audio.m4s
        6. ffmpeg 合并 -> output.mp4
        7. 清理临时文件
        8. 设置文件 mtime 为发布时间

    async download_audio_only(task: DownloadTask):
        1. 获取播放地址
        2. 下载最高质量音频流
        3. 保存为 .m4a
        4. 设置文件 mtime

    async download_cover(task: DownloadTask, make_square=False):
        1. 从 pic URL 下载原图
        2. 如果 make_square=True，调用 cover.py 处理
        3. 设置文件 mtime

    async batch_download(tasks: list[DownloadTask], progress_callback):
        # 使用 asyncio.Semaphore 控制并发
        # 逐个汇报进度
```

**`history.py` - 下载历史**
```
class DownloadHistory:
    - history_file: str = "data/history.json"

    add_record(record: HistoryRecord)
    get_all() -> list[HistoryRecord]
    get_failed() -> list[HistoryRecord]
    is_downloaded(bvid, download_type) -> bool
    update_status(record_id, status, error_msg=None)
    clear_history()

HistoryRecord:
    - id: str (uuid)
    - bvid: str
    - title: str
    - author: str (UP主)
    - download_type: "video" | "audio" | "cover"
    - status: "completed" | "failed" | "skipped"
    - file_path: str
    - file_size: int
    - created_at: str (下载时间)
    - video_publish_time: int (视频发布时间戳)
    - error_msg: str | None
```

**`cover.py` - 封面处理**
```
def make_square(image_path, output_path, fill_color=(0, 0, 0)):
    # 1. 打开图片，获取宽高
    # 2. 取 max(width, height) 作为正方形边长
    # 3. 创建正方形画布，填充 fill_color
    # 4. 将原图居中粘贴
    # 5. 保存
```

#### 3.3.3 UI 层 (`ui/`)

**主交互流程 (`main.py`)**
```
┌─────────────────────────────────────┐
│           主菜单                     │
│  1. 搜索 UP 主                       │
│  2. 查看下载历史                     │
│  3. 重试失败下载                     │
│  4. 设置                            │
│  0. 退出                            │
└──────────┬──────────────────────────┘
           │ 选择 1
           ▼
┌─────────────────────────────────────┐
│        搜索 UP 主                    │
│  输入关键词: ____                    │
│  结果列表（表格形式）                 │
│  > [1] 张三  粉丝:100w  视频:500    │
│    [2] 李四  粉丝:50w   视频:200    │
│  选择 UP 主序号: _                   │
└──────────┬──────────────────────────┘
           │ 选择 UP 主
           ▼
┌─────────────────────────────────────┐
│        视频列表                      │
│  UP主: 张三  共 500 个视频           │
│                                     │
│  筛选: [x] 隐藏充电专属视频          │
│                                     │
│  ┌──┬───────────┬────┬──────┬────┐  │
│  │  │ 标题      │时长│ 播放 │日期 │  │
│  ├──┼───────────┼────┼──────┼────┤  │
│  │☐ │ 视频标题1 │5:30│ 10w  │3/25│  │
│  │☐ │ 视频标题2 │3:20│ 5w   │3/24│  │
│  │🔒│[充电]标题3│8:00│  -   │3/23│  │
│  │☐ │ 视频标题4 │4:15│ 8w   │3/22│  │
│  └──┴───────────┴────┴──────┴────┘  │
│                                     │
│  操作: [a]全选 [n]反选 [f]筛选       │
│        [Enter]确认选择               │
└──────────┬──────────────────────────┘
           │ 确认选择
           ▼
┌─────────────────────────────────────┐
│        下载选项                      │
│  已选择 5 个视频                     │
│  下载类型:                           │
│    [x] 视频 (MP4)                   │
│    [x] 音频 (M4A)                   │
│    [x] 封面                         │
│    [x] 封面填充为正方形              │
│  画质偏好: 1080P                     │
│  确认开始下载? [Y/n]                 │
└──────────┬──────────────────────────┘
           │ 确认
           ▼
┌─────────────────────────────────────┐
│        下载进度                      │
│  总进度: [████████░░░░] 8/20  40%   │
│                                     │
│  [下载中] 视频标题1 - 视频           │
│           [██████░░░░] 60% 2.5MB/s  │
│  [下载中] 视频标题2 - 音频           │
│           [████░░░░░░] 40% 1.2MB/s  │
│  [完成 ✓] 视频标题3 - 封面           │
│  [失败 ✗] 视频标题4 - 视频 (超时)    │
│                                     │
│  下载完成! 成功:17 失败:2 跳过:1     │
└─────────────────────────────────────┘
```

## 4. 数据结构

### 4.1 配置文件 (`data/config.json`)
```json
{
  "download_dir": "./downloads",
  "max_concurrent": 3,
  "preferred_quality": 80,
  "request_interval_ms": 300,
  "cover_square_fill_color": [0, 0, 0],
  "sessdata": "",
  "bili_jct": "",
  "buvid3": "",
  "ffmpeg_path": "ffmpeg"
}
```

### 4.2 下载历史 (`data/history.json`)
```json
{
  "records": [
    {
      "id": "uuid-xxxx",
      "bvid": "BV1xx411c7XY",
      "cid": 123456,
      "title": "视频标题",
      "author": "UP主名称",
      "author_mid": 12345678,
      "download_type": "video",
      "status": "completed",
      "file_path": "downloads/UP主名称/视频标题_BV1xx411c7XY.mp4",
      "file_size": 104857600,
      "quality": 80,
      "created_at": "2026-03-26T10:00:00",
      "video_publish_time": 1690000000,
      "error_msg": null
    }
  ]
}
```

## 5. 关键 API 对接

### 5.1 API 端点清单

| 功能 | 端点 | 是否需要认证 |
|------|------|-------------|
| 搜索 UP 主 | `GET /x/web-interface/search/type?search_type=bili_user` | 建议带 Cookie |
| UP 主视频列表 | `GET /x/space/wbi/arc/search` | 需要 WBI 签名 |
| 视频分 P 信息 | `GET /x/player/pagelist` | 不需要 |
| 视频播放地址 | `GET /x/player/playurl?fnval=16` | 影响画质上限 |
| WBI 密钥 | `GET /x/web-interface/nav` | 不需要 |

### 5.2 WBI 签名流程
1. 请求 `/x/web-interface/nav` 获取 `wbi_img.img_url` 和 `wbi_img.sub_url`
2. 提取两个 URL 的文件名部分（去掉路径和扩展名），拼接为原始 key
3. 使用固定的 64 位重排表对原始 key 进行字符重排，取前 32 位作为 `mixin_key`
4. 将所有请求参数按 key 字典序排列，拼接为 `key=value&...` 格式
5. 末尾追加 `mixin_key`，计算 MD5 得到 `w_rid`
6. 请求参数中附带 `w_rid` 和 `wts`（当前时间戳）

### 5.3 请求头要求
```
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...
Referer: https://www.bilibili.com
```
- 所有 API 请求必须携带以上两个 Header
- 下载 CDN 资源时 `Referer` 为 **必须**，否则 403

### 5.4 充电视频识别
- 视频列表 API 响应中的 `is_charge_plus` 字段，值为 `1` 表示充电专属
- 充电视频在未订阅状态下无法获取播放地址，应跳过

## 6. 关键流程

### 6.1 视频下载流程
```
1. get_video_pages(bvid)           → 获取 cid 列表
2. get_play_url(bvid, cid, fnval=16) → 获取 DASH 视频流/音频流 URL
3. 选择最高画质视频流 (按 bandwidth 降序)
4. 选择最高质量音频流 (优先 30280, 其次 30232)
5. httpx 下载视频流 → {bvid}_video.m4s (流式写入，回调进度)
6. httpx 下载音频流 → {bvid}_audio.m4s
7. ffmpeg -i video.m4s -i audio.m4s -c copy output.mp4
8. 删除临时 .m4s 文件
9. os.utime() 设置文件 mtime 为 video_publish_time
```

### 6.2 音频提取流程
```
1. get_video_pages(bvid) → cid
2. get_play_url(bvid, cid, fnval=16) → 音频流 URL
3. 下载最高质量音频流 → output.m4a
4. 设置 mtime
```

### 6.3 封面下载与正方形填充流程
```
1. 从视频信息中获取 pic URL
2. httpx 下载原图 → cover.jpg
3. 如果启用正方形填充:
   a. Pillow 打开图片
   b. size = max(width, height)
   c. 创建 size×size 画布，填充背景色
   d. 原图居中粘贴到画布
   e. 保存为 cover_square.jpg
4. 设置 mtime
```

## 7. 文件命名与清洗规则

- 替换文件名中的非法字符：`\ / : * ? " < > |` → `_`
- 去除首尾空白
- 文件名过长时截断（保留前 80 字符 + BV 号）
- 保证同目录下不重名（重名时追加序号 `_2`、`_3`）

## 8. 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| 网络超时 | 自动重试 3 次，间隔递增（1s, 2s, 4s） |
| API 返回非 0 code | 记录错误码和消息，标记为 failed |
| 充电视频无法下载 | 识别后跳过，标记为 skipped |
| ffmpeg 合并失败 | 保留原始流文件，标记为 failed，记录 stderr |
| 磁盘空间不足 | 下载前不做预检，写入失败时捕获 IOError |
| Cookie 过期 | 提示用户更新 Cookie |
| 被风控/频率限制 | 自动降速或暂停后重试，提示用户 |

## 9. 依赖清单

```
httpx>=0.27
rich>=13.0
questionary>=2.0
Pillow>=10.0
```

外部依赖：
- **ffmpeg**：系统已安装，用于合并视频音频流

## 10. 使用流程示例

```bash
# 安装依赖
pip install -r requirements.txt

# 首次运行，配置 Cookie（可选，影响画质上限）
python main.py --setup

# 正常使用
python main.py

# 直接搜索 UP 主
python main.py --search "UP主名称"

# 查看/重试失败下载
python main.py --retry
```

## 11. 后续可扩展方向（不在本期范围）

- 支持收藏夹/合集批量下载
- 支持弹幕下载（XML/ASS）
- 支持字幕下载
- 单文件断点续传
- Web UI 界面
- 定时订阅下载（新视频自动下载）
