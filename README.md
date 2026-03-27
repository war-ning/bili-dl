# Bili-DL

Bilibili 视频、音频、封面下载工具。终端交互界面（TUI），支持搜索 UP 主、浏览视频列表、多选批量下载。

## 功能

- **搜索 UP 主** — 按关键词搜索，展示粉丝数、视频数、简介
- **视频列表浏览** — 分页展示，充电专属视频标识并可筛选
- **多选批量下载** — 跨页选择，支持全选/取消，已选状态跨页保持
- **多种下载类型**
  - 视频（MP4）— DASH 视频+音频流自动合并
  - 音频（MP3）— 转码 + ID3 标签（标题、作者、封面）
  - 音频（M4A）— 不转码直接 remux，极快
  - 封面（原图 / 正方形填充）— 纯色或模糊背景填充
- **下载管理** — 并发下载、进度条、自动重试、失败直接重试
- **下载历史** — JSON 记录，分页查看、筛选、删除、重新下载
- **充电视频下载** — 配置 Cookie 后支持下载已订阅的充电专属视频
- **文件组织** — 按 UP 主分文件夹，文件修改时间设为视频发布时间
- **文件命名可配置** — 支持 `{title}` `{bvid}` `{author}` `{date}` 变量

## 环境要求

- Python 3.10+
- 无需安装 ffmpeg（PyAV 内置）

## 安装

```bash
# 克隆项目
git clone <repo-url>
cd bili-dl

# 建议使用虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt
```

## 使用

### 方式一：直接运行（需要 Python 环境）

```bash
python3 main.py
```

### 方式二：打包为独立可执行文件（无需 Python 环境）

打包后生成单个文件，拷贝到任意机器直接运行，不需要安装 Python 和依赖。

```bash
# 安装打包工具
pip install pyinstaller

# 打包（在项目根目录执行）
python3 build.py

# 打包产物在 dist/ 目录下
# Linux:   dist/bili-dl
# Windows: dist/bili-dl.exe
```

运行打包后的文件：

```bash
# Linux / Mac
./dist/bili-dl

# Windows
dist\bili-dl.exe
```

> **注意：** PyInstaller 只能打包当前平台的可执行文件。要打 Windows 包需要在 Windows 上执行 `python build.py`，要打 Linux 包需要在 Linux 上执行。

首次运行会引导配置下载目录和 Cookie（可选）。

### 操作流程

```
主菜单
├── 搜索 UP 主并下载
│   ├── 输入关键词搜索
│   ├── 选择 UP 主
│   ├── 浏览视频列表 (上一步 → 重新搜索)
│   ├── 选择下载类型   (上一步 → 重选视频)
│   └── 执行下载 → 失败可直接重试
│       └── 继续下载该 UP 主 / 返回主菜单
├── 下载充电专属视频 (需配置 Cookie)
├── 查看下载历史
│   ├── 按状态筛选 (全部/完成/失败/跳过)
│   ├── 重新下载失败记录
│   ├── 打开下载目录
│   └── 删除记录 / 清空历史
├── 设置
│   ├── 下载目录、并发数、画质偏好
│   ├── 封面填充模式和颜色
│   ├── 文件命名模板
│   └── Cookie 配置
└── 退出
```

### Cookie 配置（可选）

配置 Cookie 可解锁更高画质（无 Cookie 最高 480P，有 Cookie 最高 1080P）。

1. 浏览器登录 [bilibili.com](https://www.bilibili.com)
2. F12 → Application → Cookies
3. 复制 `SESSDATA`、`bili_jct`、`buvid3`、`DedeUserID` 的值
4. 在程序 **设置 → Cookie 设置** 中填入

### 文件命名模板

默认 `{title}_{bvid}`，可在设置中修改。支持变量：

| 变量 | 含义 | 示例 |
|------|------|------|
| `{title}` | 视频标题 | 如何学习编程 |
| `{bvid}` | BV 号 | BV1xx411c7XY |
| `{author}` | UP 主名 | 张三 |
| `{date}` | 发布日期 | 2026-03-27 |

示例：`{date}_{title}` → `2026-03-27_如何学习编程.mp4`

## 下载文件结构

```
downloads/
└── UP主名称/
    ├── 视频标题_BV号.mp4
    ├── 视频标题_BV号.mp3       # 或 .m4a
    ├── 视频标题_BV号.jpg
    └── 视频标题_BV号_square.jpg
```

## 依赖

| 包 | 用途 |
|---|---|
| bilibili-api-python | B 站 API 封装 |
| httpx | HTTP 客户端 |
| rich | 终端表格、进度条 |
| questionary | 终端交互选择 |
| av (PyAV) | 视频音频合并/转码（内置 ffmpeg） |
| mutagen | 音频标签写入 |
| Pillow | 封面图片处理 |

## 许可

MIT
