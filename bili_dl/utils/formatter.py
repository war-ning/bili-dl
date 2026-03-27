"""格式化工具函数"""


def format_duration(seconds: int) -> str:
    """120 -> '2:00', 3661 -> '1:01:01'"""
    if seconds < 0:
        return "0:00"
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_count(n: int) -> str:
    """12345 -> '1.2万', 1234567 -> '123.5万'"""
    if n < 0:
        return "0"
    if n < 10000:
        return str(n)
    wan = n / 10000
    return f"{wan:.1f}万"


def format_size(bytes_: int) -> str:
    """1048576 -> '1.0 MB'"""
    if bytes_ < 1024:
        return f"{bytes_} B"
    elif bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.1f} KB"
    elif bytes_ < 1024 * 1024 * 1024:
        return f"{bytes_ / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_ / (1024 * 1024 * 1024):.2f} GB"


def format_speed(bps: float) -> str:
    """2621440.0 -> '2.5 MB/s'"""
    if bps <= 0:
        return "0 B/s"
    return format_size(int(bps)) + "/s"


def parse_duration_str(s: str) -> int:
    """'5:30' -> 330, '1:01:01' -> 3661"""
    if not s or s == "0":
        return 0
    parts = s.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        else:
            return int(parts[0])
    except (ValueError, IndexError):
        return 0
