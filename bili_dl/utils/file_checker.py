"""下载文件诊断工具：检查视频文件是否有效"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

console = Console()

# 常见视频容器魔数
_MAGIC_BYTES: dict[bytes, str] = {
    b"\x00\x00\x00\x1c\x66\x74\x79\x70": "MP4 (ISOBMFF)",
    b"\x00\x00\x00\x20\x66\x74\x79\x70": "MP4 (ISOBMFF)",
    b"\x46\x4c\x56\x01": "FLV",
    b"\x1a\x45\xdf\xa3": "MKV/WebM (EBML)",
    b"\x00\x00\x01\xba": "MPEG-PS",
    b"\x00\x00\x01\xb3": "MPEG (H.264)",
    b"\xff\xd8\xff": "JPEG",
    b"\x89\x50\x4e\x47": "PNG",
    b"\x49\x44\x33": "MP3 (ID3)",
}


def check_video_file(path: str) -> None:
    """诊断视频文件，打印格式、编码等信息"""
    p = Path(path)
    if not p.exists():
        console.print(f"[red]文件不存在: {path}")
        return
    if not p.is_file():
        console.print(f"[red]不是文件: {path}")
        return

    size = p.stat().st_size
    console.print(f"\n[bold]文件诊断:[/bold] {path}")
    console.print(f"  大小: [cyan]{size:,}[/cyan] 字节 ({size / 1024 / 1024:.2f} MB)")

    if size == 0:
        console.print("[red]  文件为空! 下载失败。")
        return

    # 魔数检测
    with open(p, "rb") as f:
        header = f.read(16)
    console.print(f"  前 16 字节: [dim]{header.hex(' ')}[/dim]")

    detected = "未知格式"
    for magic, name in _MAGIC_BYTES.items():
        if header.startswith(magic):
            detected = name
            break
    console.print(f"  魔数检测: [cyan]{detected}[/cyan]")

    # PyAV 探测
    try:
        import av
        with av.open(str(p)) as container:
            console.print(f"  容器格式: [green]{container.format.name}[/green]")
            console.print(f"  时长: [cyan]{container.duration / 1_000_000 if container.duration else 0:.1f}[/cyan] 秒")
            for i, stream in enumerate(container.streams):
                stype = stream.type
                info = f"  Stream #{i}: [{stype}]"
                if stype == "video":
                    codec = stream.codec_context.name if stream.codec_context else "?"
                    w = stream.codec_context.width if stream.codec_context else 0
                    h = stream.codec_context.height if stream.codec_context else 0
                    info += f" {codec} {w}x{h}"
                    if stream.duration:
                        info += f" {stream.duration * stream.time_base:.1f}s"
                elif stype == "audio":
                    codec = stream.codec_context.name if stream.codec_context else "?"
                    ch = getattr(stream.codec_context, "channels", "?") if stream.codec_context else "?"
                    rate = getattr(stream.codec_context, "rate", "?") if stream.codec_context else "?"
                    info += f" {codec} {ch}ch {rate}Hz"
                    if stream.duration:
                        info += f" {stream.duration * stream.time_base:.1f}s"
                console.print(info)
    except Exception as e:
        console.print(f"  [red]PyAV 无法打开: {e}")
        console.print("  [yellow]文件可能已损坏或是不支持的格式")
        # 尝试检测是否为纯文本（错误响应）
        try:
            with open(p, "rb") as f:
                tail = f.read(1024)
            sample = header + tail
            # 检查是否像 HTTP 错误响应
            text = sample.decode("utf-8", errors="replace")
            if any(kw in text[:200] for kw in ("<html", "<?xml", "<!DOC", "Error", "error", "{", "[")):
                console.print("  [yellow]文件内容疑似非二进制数据（可能是错误响应）")
                console.print(f"  [dim]内容片段: {text[:200]}[/dim]")
        except Exception:
            pass

    console.print()
