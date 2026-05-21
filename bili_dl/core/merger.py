"""FFmpeg / PyAV 媒体流合并与拼接

PyAV 17 对 DASH fMP4 → MP4 转封装有 mux 数据损坏 bug，
优先使用 FFmpeg CLI（PATH 或 exe 旁），不可用时回退 PyAV。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import av

from ..exceptions import MergeError


def _find_ffmpeg() -> str | None:
    """查找可用 ffmpeg 的路径"""
    # 1. exe 同目录下的 ffmpeg.exe
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        bundled = exe_dir / "ffmpeg.exe"
        if bundled.exists():
            return str(bundled)
    # 2. PATH 中的 ffmpeg
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(path) / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if candidate.exists():
            return str(candidate)
    # 3. shutil.which
    found = shutil.which("ffmpeg")
    return found


_FFMPEG = _find_ffmpeg()


class VideoMerger:
    """媒体流合并/拼接——优先 FFmpeg CLI，回退 PyAV"""

    def merge(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
    ) -> None:
        """将分离的视频和音频流合并为单个 MP4（不重编码）"""
        if _FFMPEG:
            self._ffmpeg_merge(video_path, audio_path, output_path)
        else:
            self._pyav_merge(video_path, audio_path, output_path)

    def remux_to_mp4(self, input_path: Path, output_path: Path) -> None:
        """将任意格式视频转封装为 MP4（不重编码）"""
        if _FFMPEG:
            self._ffmpeg_remux(input_path, output_path)
        else:
            self._pyav_remux(input_path, output_path)

    def concat_videos(self, input_paths: list[Path], output_path: Path) -> None:
        """将多个 MP4 文件拼接为一个（不重编码）"""
        if not input_paths:
            raise MergeError("没有文件可拼接")
        if len(input_paths) == 1:
            shutil.copy2(str(input_paths[0]), str(output_path))
            return
        if _FFMPEG:
            self._ffmpeg_concat(input_paths, output_path)
        else:
            self._pyav_concat_videos(input_paths, output_path)

    def concat_audios(
        self, input_paths: list[Path], output_path: Path,
        output_format: str = "ipod",
    ) -> None:
        """将多个音频文件拼接为一个（不重编码）"""
        if not input_paths:
            raise MergeError("没有文件可拼接")
        if len(input_paths) == 1:
            shutil.copy2(str(input_paths[0]), str(output_path))
            return
        if _FFMPEG:
            self._ffmpeg_concat(input_paths, output_path, is_audio=True)
        else:
            self._pyav_concat_audios(input_paths, output_path, output_format)

    # ─── FFmpeg 实现 ───

    @staticmethod
    def _ffmpeg_merge(video_path: Path, audio_path: Path, output_path: Path) -> None:
        cmd = [
            _FFMPEG, "-y",
            "-i", str(video_path), "-i", str(audio_path),
            "-c", "copy", "-movflags", "+faststart",
            str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise MergeError(f"FFmpeg 合并失败: {r.stderr[-300:]}")

    @staticmethod
    def _ffmpeg_remux(input_path: Path, output_path: Path) -> None:
        cmd = [
            _FFMPEG, "-y",
            "-i", str(input_path),
            "-c", "copy", "-movflags", "+faststart",
            str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise MergeError(f"FFmpeg 转封装失败: {r.stderr[-300:]}")

    @staticmethod
    def _ffmpeg_concat(
        paths: list[Path], output_path: Path, is_audio: bool = False,
    ) -> None:
        # 用 concat demuxer
        concat_list = output_path.parent / ".ffconcat.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in paths:
                f.write(f"file '{p.as_posix()}'\n")
        cmd = [
            _FFMPEG, "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy", str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        concat_list.unlink(missing_ok=True)
        if r.returncode != 0:
            raise MergeError(f"FFmpeg 拼接失败: {r.stderr[-300:]}")

    # ─── PyAV 回退实现 ───

    @staticmethod
    def _pyav_merge(video_path: Path, audio_path: Path, output_path: Path) -> None:
        input_video = None; input_audio = None; output = None
        try:
            input_video = av.open(str(video_path))
            input_audio = av.open(str(audio_path))
            output = av.open(str(output_path), "w", format="mp4")

            in_v = input_video.streams.video[0]
            in_a = input_audio.streams.audio[0]
            v_ctx, a_ctx = in_v.codec_context, in_a.codec_context

            out_v = output.add_stream(v_ctx.name)
            if v_ctx.extradata:
                out_v.codec_context.extradata = v_ctx.extradata
            out_v.width = v_ctx.width; out_v.height = v_ctx.height

            out_a = output.add_stream(a_ctx.name)
            if a_ctx.extradata:
                out_a.codec_context.extradata = a_ctx.extradata
            out_a.rate = a_ctx.rate

            for pkt in input_video.demux(in_v):
                if pkt.dts is None: continue
                pkt.stream = out_v; output.mux(pkt)
            for pkt in input_audio.demux(in_a):
                if pkt.dts is None: continue
                pkt.stream = out_a; output.mux(pkt)
        except Exception as e:
            if output: output.close(); output = None
            if output_path.exists(): output_path.unlink(missing_ok=True)
            raise MergeError(f"PyAV 合并失败: {e}") from e
        finally:
            if output: output.close()
            if input_video: input_video.close()
            if input_audio: input_audio.close()

    @staticmethod
    def _pyav_remux(input_path: Path, output_path: Path) -> None:
        inp = None; out = None
        try:
            inp = av.open(str(input_path))
            out = av.open(str(output_path), "w", format="mp4")
            stream_map = {}
            for s in inp.streams:
                if s.type not in ("video", "audio"): continue
                ctx = s.codec_context
                ost = out.add_stream(ctx.name)
                if ctx.extradata:
                    ost.codec_context.extradata = ctx.extradata
                if s.type == "video":
                    ost.width = ctx.width; ost.height = ctx.height
                elif s.type == "audio":
                    ost.rate = ctx.rate
                stream_map[s.index] = ost
            for pkt in inp.demux():
                if pkt.dts is None: continue
                ost = stream_map.get(pkt.stream.index)
                if ost is None: continue
                pkt.stream = ost; out.mux(pkt)
        except Exception as e:
            if out: out.close(); out = None
            if output_path.exists(): output_path.unlink(missing_ok=True)
            raise MergeError(f"PyAV 转封装失败: {e}") from e
        finally:
            if out: out.close()
            if inp: inp.close()

    @staticmethod
    def _pyav_concat_videos(input_paths: list[Path], output_path: Path) -> None:
        output = None; inputs = []
        try:
            first = av.open(str(input_paths[0])); inputs.append(first)
            output = av.open(str(output_path), "w", format="mp4")
            has_v, has_a = len(first.streams.video) > 0, len(first.streams.audio) > 0
            out_vs = out_as = None
            if has_v:
                vs = first.streams.video[0]; ctx = vs.codec_context
                out_vs = output.add_stream(ctx.name)
                if ctx.extradata: out_vs.codec_context.extradata = ctx.extradata
                out_vs.width = ctx.width; out_vs.height = ctx.height
            if has_a:
                ast = first.streams.audio[0]; ctx = ast.codec_context
                out_as = output.add_stream(ctx.name)
                if ctx.extradata: out_as.codec_context.extradata = ctx.extradata
                out_as.rate = ctx.rate
            first.close(); inputs.clear()
            v_off = a_off = 0
            for path in input_paths:
                inp = av.open(str(path)); inputs.append(inp)
                if has_v and out_vs:
                    mx = v_off
                    for pkt in inp.demux(inp.streams.video[0]):
                        if pkt.dts is None: continue
                        pkt.pts += v_off; pkt.dts += v_off
                        mx = max(mx, pkt.pts)
                        pkt.stream = out_vs; output.mux(pkt)
                    v_off = mx + 1
                if has_a and out_as:
                    mx = a_off
                    for pkt in inp.demux(inp.streams.audio[0]):
                        if pkt.dts is None: continue
                        pkt.pts += a_off; pkt.dts += a_off
                        mx = max(mx, pkt.pts)
                        pkt.stream = out_as; output.mux(pkt)
                    a_off = mx + 1
                inp.close(); inputs.pop()
        except Exception as e:
            if output: output.close(); output = None
            if output_path.exists(): output_path.unlink(missing_ok=True)
            raise MergeError(f"PyAV 拼接失败: {e}") from e
        finally:
            if output: output.close()
            for i in inputs:
                try: i.close()
                except: pass

    @staticmethod
    def _pyav_concat_audios(
        input_paths: list[Path], output_path: Path, fmt: str = "ipod",
    ) -> None:
        output = None; inputs = []
        try:
            first = av.open(str(input_paths[0])); inputs.append(first)
            output = av.open(str(output_path), "w", format=fmt)
            ast = first.streams.audio[0]; ctx = ast.codec_context
            out_as = output.add_stream(ctx.name)
            if ctx.extradata: out_as.codec_context.extradata = ctx.extradata
            out_as.rate = ctx.rate
            first.close(); inputs.clear()
            a_off = 0
            for path in input_paths:
                inp = av.open(str(path)); inputs.append(inp)
                mx = a_off
                for pkt in inp.demux(inp.streams.audio[0]):
                    if pkt.dts is None: continue
                    pkt.pts += a_off; pkt.dts += a_off
                    mx = max(mx, pkt.pts)
                    pkt.stream = out_as; output.mux(pkt)
                a_off = mx + 1
                inp.close(); inputs.pop()
        except Exception as e:
            if output: output.close(); output = None
            if output_path.exists(): output_path.unlink(missing_ok=True)
            raise MergeError(f"PyAV 拼接音频失败: {e}") from e
        finally:
            if output: output.close()
            for i in inputs:
                try: i.close()
                except: pass
