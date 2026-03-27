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


def main():
    clean = "--clean" in sys.argv

    if clean:
        for d in ["build", "dist"]:
            if os.path.exists(d):
                shutil.rmtree(d)
                print(f"已清理 {d}/")
        for f in ["bili-dl.spec"]:
            if os.path.exists(f):
                os.remove(f)

    check_dependencies()

    system = platform.system().lower()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "bili-dl",
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

    cmd.append("main.py")

    print(f"\n正在打包 ({platform.system()} {platform.machine()})...")
    print(f"命令: {' '.join(cmd)}\n")

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("\n打包失败!")
        sys.exit(1)

    output = os.path.join("dist", "bili-dl")
    if system == "windows":
        output += ".exe"

    size_mb = os.path.getsize(output) / (1024 * 1024)
    print(f"\n打包成功!")
    print(f"  文件: {output}")
    print(f"  大小: {size_mb:.1f} MB")
    if system != "windows":
        print(f"\n运行: ./{os.path.basename(output)}")
    else:
        print(f"\n运行: {os.path.basename(output)}")


if __name__ == "__main__":
    main()
