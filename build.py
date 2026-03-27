#!/usr/bin/env python3
"""打包脚本 - 使用 PyInstaller 生成独立可执行文件

使用方法:
    python build.py          # 打包当前平台
    python build.py --clean  # 清理打包产物后重新打包

需要先安装: pip install pyinstaller
"""

import os
import platform
import shutil
import subprocess
import sys


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

    system = platform.system().lower()
    name = "bili-dl" if system != "windows" else "bili-dl.exe"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "bili-dl",
        "--console",
        # 收集 bilibili-api-python 的数据文件
        "--collect-all", "bilibili_api",
        # 收集 PyAV 的共享库
        "--collect-all", "av",
        # 隐式导入
        "--hidden-import", "mutagen.mp3",
        "--hidden-import", "mutagen.id3",
        "--hidden-import", "mutagen.mp4",
        "--hidden-import", "PIL",
        "--hidden-import", "questionary",
        "--hidden-import", "rich",
        "--hidden-import", "httpx",
        "--hidden-import", "anyio",
        "--hidden-import", "anyio._backends",
        "--hidden-import", "anyio._backends._asyncio",
        "main.py",
    ]

    print(f"正在打包 ({platform.system()} {platform.machine()})...")
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
    print(f"\n运行: ./{os.path.basename(output)}" if system != "windows" else f"\n运行: {os.path.basename(output)}")


if __name__ == "__main__":
    main()
