#!/usr/bin/env python3
"""打包脚本 - 使用 PyInstaller 生成独立可执行文件

使用方法:
    python build.py          # 打包当前平台
    python build.py --clean  # 清理打包产物后重新打包

前置条件:
    pip install -r requirements.txt
    pip install pyinstaller
"""

import os
import platform
import shutil
import subprocess
import sys

# 动态读取版本号
sys.path.insert(0, os.path.dirname(__file__))
from bili_dl import __version__


def check_dependencies():
    """检查必要依赖是否已安装"""
    missing = []
    for mod in ["bilibili_api", "httpx", "rich", "questionary", "av", "mutagen", "PIL"]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)

    if missing:
        print(f"[错误] 以下依赖未安装: {', '.join(missing)}")
        print(f"请先执行: pip install -r requirements.txt")
        sys.exit(1)

    try:
        __import__("PyInstaller")
    except ImportError:
        print("[错误] PyInstaller 未安装")
        print("请先执行: pip install pyinstaller")
        sys.exit(1)

    print("依赖检查通过")


def _parse_version(v: str) -> tuple[int, int, int, int]:
    """解析版本字符串 '0.3.0' → (0, 3, 0, 0)"""
    parts = v.strip().split(".")
    nums = []
    for p in parts:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums[:4])  # type: ignore


def _write_version_file(ver: tuple[int, int, int, int]) -> str:
    """生成 Windows version resource 文件，返回路径"""
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver},
    prodvers={ver},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '080404B0',
          [
            StringStruct('CompanyName', 'Bili-DL'),
            StringStruct('FileDescription', 'Bilibili 视频/音频/封面下载工具'),
            StringStruct('FileVersion', '{ver[0]}.{ver[1]}.{ver[2]}'),
            StringStruct('InternalName', 'bili-dl'),
            StringStruct('LegalCopyright', 'MIT License'),
            StringStruct('OriginalFilename', 'bili-dl.exe'),
            StringStruct('ProductName', 'Bili-DL'),
            StringStruct('ProductVersion', '{ver[0]}.{ver[1]}.{ver[2]}'),
          ]
        ),
      ]
    ),
    VarFileInfo([VarStruct('Translation', [0x0804, 0x04B0])]),
  ]
)
"""
    path = os.path.join(os.path.dirname(__file__) or ".", "version_info.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def main():
    clean = "--clean" in sys.argv

    if clean:
        for d in ["build"]:
            if os.path.exists(d):
                shutil.rmtree(d)
                print(f"已清理 {d}/")
        for f in os.listdir("."):
            if f.endswith(".spec"):
                os.remove(f)
                print(f"已清理 {f}")

    check_dependencies()

    system = platform.system().lower()
    ver_tuple = _parse_version(__version__)
    exe_name = f"bili-dl_v{__version__}"

    # Windows 版本资源文件
    version_file = None
    if system == "windows":
        version_file = _write_version_file(ver_tuple)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", exe_name,
        "--console",
        # 收集 bilibili-api-python 的数据文件
        "--collect-all", "bilibili_api",
        # 收集 mutagen 的全部模块
        "--collect-all", "mutagen",
        # 隐式导入
        "--hidden-import", "PIL",
        "--hidden-import", "questionary",
        "--hidden-import", "rich",
        "--hidden-import", "httpx",
        "--hidden-import", "anyio",
        "--hidden-import", "anyio._backends",
        "--hidden-import", "anyio._backends._asyncio",
        # 二维码登录依赖
        "--hidden-import", "qrcode",
        "--hidden-import", "qrcode_terminal",
        "--hidden-import", "Cryptodome",
        "--hidden-import", "bili_dl.utils.login_helper",
        "--collect-all", "qrcode",
        "--collect-all", "qrcode_terminal",
    ]

    # PyAV: 在不同平台上收集方式不同
    # av 可能是 .so/.pyd 扩展模块而非 package，collect-all 会跳过
    # 需要用 collect-binaries + hidden-import
    cmd.extend([
        "--hidden-import", "av",
        "--collect-binaries", "av",
    ])

    # 尝试找到 av 的动态库所在目录
    try:
        import av
        av_dir = os.path.dirname(av.__file__)
        # 把 av 目录下的所有 dll/so 文件加进来
        for f in os.listdir(av_dir):
            if f.endswith((".dll", ".so", ".dylib", ".pyd")):
                src = os.path.join(av_dir, f)
                cmd.extend(["--add-binary", f"{src}{os.pathsep}av"])
        # av 的 libs 子目录（Windows 上有 ffmpeg dll）
        libs_dir = os.path.join(av_dir, "libs")
        if os.path.isdir(libs_dir):
            for f in os.listdir(libs_dir):
                src = os.path.join(libs_dir, f)
                if os.path.isfile(src):
                    cmd.extend(["--add-binary", f"{src}{os.pathsep}av/libs"])
    except Exception:
        pass

    if version_file:
        cmd.extend(["--version-file", version_file])

    cmd.append("main.py")

    print(f"\n正在打包 Bili-DL v{__version__} ({platform.system()} {platform.machine()})...")
    print(f"命令: {' '.join(cmd)}\n")

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("\n打包失败!")
        sys.exit(1)

    ext = ".exe" if system == "windows" else ""
    output = os.path.join("dist", f"{exe_name}{ext}")

    size_mb = os.path.getsize(output) / (1024 * 1024)
    print(f"\n打包成功! Bili-DL v{__version__}")
    print(f"  文件: {output}")
    print(f"  大小: {size_mb:.1f} MB")
    print(f"\n运行: {os.path.basename(output)}")

    # 清理临时版本文件
    if version_file and os.path.exists(version_file):
        os.remove(version_file)

    # 复制 ffmpeg 至 dist/（PyAV mux 有 bug，视频合并依赖 FFmpeg）
    ffmpeg_src = shutil.which("ffmpeg")
    if ffmpeg_src:
        ffmpeg_dst = os.path.join("dist", f"ffmpeg{ext}")
        if os.path.abspath(ffmpeg_src) != os.path.abspath(ffmpeg_dst):
            shutil.copy2(ffmpeg_src, ffmpeg_dst)
            print(f"已复制 ffmpeg 至 {ffmpeg_dst}")


if __name__ == "__main__":
    main()
