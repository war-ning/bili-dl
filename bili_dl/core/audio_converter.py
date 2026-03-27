"""音频转 MP3 + ID3 标签写入"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import av

from ..exceptions import ConversionError

_MP3_AVAILABLE: Optional[bool] = None


def is_mp3_available() -> bool:
    """检测 PyAV 是否支持 MP3 编码"""
    global _MP3_AVAILABLE
    if _MP3_AVAILABLE is None:
        try:
            codec = av.codec.Codec("libmp3lame", "w")
            _MP3_AVAILABLE = codec is not None
        except Exception:
            try:
                codec = av.codec.Codec("mp3", "w")
                _MP3_AVAILABLE = codec is not None
            except Exception:
                _MP3_AVAILABLE = False
    return _MP3_AVAILABLE


class AudioConverter:
    """音频转码与 ID3 标签管理"""

    def convert_to_mp3(
        self,
        input_path: Path,
        output_path: Path,
        bitrate: int = 192000,
    ) -> Path:
        """将 m4s/m4a 音频转为 MP3

        Returns:
            实际输出文件路径（可能是 .mp3 或 .m4a）
        """
        # #5: MP3 不可用时回退 M4A 并返回实际路径
        if not is_mp3_available():
            m4a_path = output_path.with_suffix(".m4a")
            self.remux_to_m4a(input_path, m4a_path)
            return m4a_path

        input_container = None
        output_container = None

        try:
            input_container = av.open(str(input_path))
            output_container = av.open(str(output_path), "w", format="mp3")

            in_stream = input_container.streams.audio[0]

            try:
                out_stream = output_container.add_stream("libmp3lame", rate=in_stream.rate)
            except Exception:
                out_stream = output_container.add_stream("mp3", rate=in_stream.rate)

            out_stream.bit_rate = bitrate

            for frame in input_container.decode(audio=0):
                for packet in out_stream.encode(frame):
                    output_container.mux(packet)

            for packet in out_stream.encode(None):
                output_container.mux(packet)

            return output_path

        except Exception as e:
            # #13: 清理失败的输出文件
            if output_container:
                output_container.close()
                output_container = None
            if output_path.exists():
                output_path.unlink(missing_ok=True)

            # #5: 回退到 M4A 并返回实际路径
            m4a_path = output_path.with_suffix(".m4a")
            try:
                actual = self.remux_to_m4a(input_path, m4a_path)
                return actual
            except Exception:
                raise ConversionError(f"音频转换失败: {e}") from e
        finally:
            if output_container:
                output_container.close()
            if input_container:
                input_container.close()

    def remux_to_m4a(
        self,
        input_path: Path,
        output_path: Path,
    ) -> Path:
        """直接 remux 为 M4A（不转码，保持 AAC）

        Returns:
            输出文件路径
        """
        input_container = None
        output_container = None

        try:
            input_container = av.open(str(input_path))
            output_container = av.open(str(output_path), "w", format="ipod")

            in_stream = input_container.streams.audio[0]
            out_stream = output_container.add_stream(
                in_stream.codec_context.name,
                rate=in_stream.codec_context.rate,
            )
            if in_stream.codec_context.extradata:
                out_stream.codec_context.extradata = in_stream.codec_context.extradata

            for packet in input_container.demux(in_stream):
                if packet.dts is None:
                    continue
                packet.stream = out_stream
                output_container.mux(packet)

            return output_path

        except Exception as e:
            # #13: 清理失败的输出文件
            if output_container:
                output_container.close()
                output_container = None
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            raise ConversionError(f"音频 remux 失败: {e}") from e
        finally:
            if output_container:
                output_container.close()
            if input_container:
                input_container.close()

    def extract_audio(
        self,
        input_path: Path,
        output_path: Path,
    ) -> Path:
        """从视频合流文件中提取音频轨道为 M4A

        用于 durl 格式（FLV/MP4 合流）中只需要音频的场景。
        """
        input_container = None
        output_container = None

        try:
            input_container = av.open(str(input_path))
            if not input_container.streams.audio:
                raise ConversionError("文件中无音频轨道")

            output_container = av.open(str(output_path), "w", format="ipod")

            in_stream = input_container.streams.audio[0]
            out_stream = output_container.add_stream(
                in_stream.codec_context.name,
                rate=in_stream.codec_context.rate,
            )
            if in_stream.codec_context.extradata:
                out_stream.codec_context.extradata = in_stream.codec_context.extradata

            for packet in input_container.demux(in_stream):
                if packet.dts is None:
                    continue
                packet.stream = out_stream
                output_container.mux(packet)

            return output_path

        except Exception as e:
            if output_container:
                output_container.close()
                output_container = None
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            raise ConversionError(f"提取音频失败: {e}") from e
        finally:
            if output_container:
                output_container.close()
            if input_container:
                input_container.close()

    def write_id3_tags(
        self,
        audio_path: Path,
        title: str,
        artist: str,
        cover_data: Optional[bytes] = None,
    ) -> None:
        """写入 ID3/MP4 标签（失败不影响下载结果）"""
        try:
            suffix = audio_path.suffix.lower()
            if suffix == ".mp3":
                self._write_mp3_tags(audio_path, title, artist, cover_data)
            elif suffix in (".m4a", ".mp4"):
                self._write_m4a_tags(audio_path, title, artist, cover_data)
        except Exception:
            pass  # 标签写入失败不影响音频文件本身

    def _write_mp3_tags(
        self,
        path: Path,
        title: str,
        artist: str,
        cover_data: Optional[bytes],
    ) -> None:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, TIT2, TPE1, APIC, ID3NoHeaderError

        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()

        tags.add(TIT2(encoding=3, text=title))
        tags.add(TPE1(encoding=3, text=artist))

        if cover_data:
            tags.add(APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,
                desc="Cover",
                data=cover_data,
            ))

        tags.save(str(path))

    def _write_m4a_tags(
        self,
        path: Path,
        title: str,
        artist: str,
        cover_data: Optional[bytes],
    ) -> None:
        from mutagen.mp4 import MP4, MP4Cover

        try:
            audio = MP4(str(path))
        except Exception:
            return

        audio["\xa9nam"] = [title]
        audio["\xa9ART"] = [artist]

        if cover_data:
            audio["covr"] = [MP4Cover(
                cover_data,
                imageformat=MP4Cover.FORMAT_JPEG,
            )]

        audio.save()
