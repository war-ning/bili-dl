"""自定义异常"""


class BiliDLError(Exception):
    """基础异常"""


class BiliAPIError(BiliDLError):
    """API 返回非 0 code"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"API Error [{code}]: {message}")


class ChargeVideoError(BiliDLError):
    """充电视频无法下载"""


class CookieExpiredError(BiliDLError):
    """Cookie 已过期"""


class RateLimitError(BiliDLError):
    """被风控/频率限制"""


class MergeError(BiliDLError):
    """PyAV 合并失败"""


class ConversionError(BiliDLError):
    """音频转换失败"""


class QualityNotAvailable(BiliDLError):
    """请求的画质不可用"""
