# Bili-DL 部署与启动指南

## 环境要求

- Python 3.10+
- pip（Python 包管理器）
- 网络可访问 bilibili.com 及其 CDN

## 部署步骤

### 1. 获取项目文件

将整个 `bili-dl/` 目录复制到目标服务器：

```bash
# 方式一：scp 传输
scp -r bili-dl/ user@your-server:/path/to/

# 方式二：rsync（推荐，排除缓存文件）
rsync -av --exclude='__pycache__' --exclude='data/' bili-dl/ user@your-server:/path/to/bili-dl/

# 方式三：打包后传输
tar czf bili-dl.tar.gz --exclude='__pycache__' --exclude='data/' bili-dl/
scp bili-dl.tar.gz user@your-server:/path/to/
ssh user@your-server "cd /path/to && tar xzf bili-dl.tar.gz"
```

### 2. 安装依赖

```bash
cd /path/to/bili-dl

# 建议使用虚拟环境（可选但推荐）
python3 -m venv venv
source venv/bin/activate    # Linux/Mac
# venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

#### 依赖说明

| 包名 | 用途 |
|------|------|
| bilibili-api-python | B 站 API 封装 |
| httpx | HTTP 客户端，用于流式下载 |
| rich | 终端美化（表格、进度条） |
| questionary | 终端交互（选择、多选、输入） |
| av (PyAV) | 视频音频合并/转码，内置 ffmpeg 库 |
| mutagen | MP3/M4A 音频标签写入 |
| Pillow | 封面图片处理 |

> PyAV 已内置 ffmpeg 库，无需额外安装系统级 ffmpeg。

### 3. 启动

```bash
cd /path/to/bili-dl
python3 main.py
```

如果使用了虚拟环境：

```bash
cd /path/to/bili-dl
source venv/bin/activate
python3 main.py
```

## 首次运行

首次启动会进入配置引导：

1. **下载目录** — 输入文件保存路径（默认 `./downloads`）
2. **Cookie 配置**（可选）— 影响最高可用画质：
   - 不配置：最高 480P
   - 配置 SESSDATA 等：最高 1080P
   - 大会员账号：最高 4K/HDR

### 获取 Cookie 的方法

1. 浏览器登录 [bilibili.com](https://www.bilibili.com)
2. 按 `F12` 打开开发者工具
3. 切换到 `Application`（Chrome）或 `Storage`（Firefox）标签
4. 左侧选择 `Cookies` → `https://www.bilibili.com`
5. 找到并复制以下字段的值：

| Cookie 名 | 必填 | 说明 |
|-----------|------|------|
| SESSDATA | 是 | 登录凭证，最关键 |
| bili_jct | 推荐 | CSRF Token |
| buvid3 | 推荐 | 设备指纹 |
| DedeUserID | 可选 | 用户 ID |

> Cookie 会过期，失效后在程序 `设置` 菜单中重新配置即可。

## 使用流程

```
主菜单
 ├── 搜索 UP 主并下载
 │    ├── 输入关键词搜索
 │    ├── 选择 UP 主
 │    ├── 浏览视频列表（支持隐藏充电视频）
 │    ├── 多选要下载的视频
 │    ├── 选择下载类型（视频/音频/封面）
 │    └── 开始下载（显示进度条）
 ├── 查看下载历史
 │    ├── 按状态筛选（全部/完成/失败）
 │    └── 对失败记录重新下载
 ├── 设置
 │    ├── 修改下载目录
 │    ├── 调整并发数/画质
 │    ├── 封面填充模式（纯色/模糊）
 │    └── 更新 Cookie
 └── 退出
```

## 下载文件说明

### 目录结构

```
downloads/
└── UP主名称/
    ├── 视频标题_BV号.mp4          # 视频
    ├── 视频标题_BV号.mp3          # 音频（含 ID3 标签）
    ├── 视频标题_BV号.jpg          # 封面原图
    └── 视频标题_BV号_square.jpg   # 封面正方形版本
```

### 文件特性

- 文件按 UP 主名称分文件夹存放
- 文件修改时间（mtime）设置为视频的发布时间
- MP3 文件包含 ID3 标签：标题、作者、封面图
- 正方形封面支持纯色填充（默认黑色）和模糊背景填充

## 配置文件

运行后自动生成 `data/config.json`：

```json
{
  "download_dir": "./downloads",
  "max_concurrent": 3,
  "preferred_quality": 80,
  "request_interval_ms": 300,
  "cover_fill_mode": "solid_color",
  "cover_fill_color": [0, 0, 0],
  "cover_blur_radius": 40,
  "sessdata": "",
  "bili_jct": "",
  "buvid3": "",
  "dedeuserid": "",
  "ac_time_value": "",
  "data_dir": "./data"
}
```

可直接编辑此文件修改配置，也可在程序内通过 `设置` 菜单修改。

### 画质对照表

| 配置值 | 画质 | 要求 |
|--------|------|------|
| 16 | 360P | 无需登录 |
| 32 | 480P | 无需登录 |
| 64 | 720P | 需登录 |
| 80 | 1080P | 需登录（默认） |
| 112 | 1080P+ | 需大会员 |
| 120 | 4K | 需大会员 |

## 常见问题

### Q: 提示 "搜索失败" 或 API 错误

请求过于频繁被风控。等待几分钟后重试，或增大 `request_interval_ms` 配置值。

### Q: 下载的视频只有 480P

未配置 Cookie 或 Cookie 已过期。在 `设置` 中重新配置 SESSDATA。

### Q: MP3 转码失败

PyAV 的 MP3 编码器不可用时，程序会自动回退为 M4A 格式（AAC 音频，质量相同，兼容性略低）。

### Q: 充电视频无法下载

充电专属视频需要订阅对应 UP 主的充电计划。程序会自动标识并跳过这些视频。

### Q: Windows 下中文显示乱码

建议使用 Windows Terminal 或 PowerShell 7+ 运行，不要使用旧版 cmd.exe。

### Q: 如何迁移到另一台机器

复制整个 `bili-dl/` 目录即可（包含 `data/` 目录可保留历史记录和配置）。在新机器上重新 `pip install -r requirements.txt`。
