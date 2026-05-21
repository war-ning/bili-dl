"""PyAV 视频/音频流合并与拼接

PyAV 17+ 关键约束：设 width/height/rate 等属性会触发 codec 开启，
extradata（H.264 之 SPS/PPS）须先于此等属性设置，否则无效，
导致输出有音无画。
"""

from pathlib import Path

import av

from ..exceptions import MergeError


class VideoMerger:
    """使用 PyAV 合并/拼接媒体流"""

    def remux_to_mp4(self, input_path: Path, output_path: Path) -> None:
        """将任意格式视频转封装为 MP4（不重编码）"""
        inp = None
        out = None
        try:
            inp = av.open(str(input_path))
            out = av.open(str(output_path), "w", format="mp4")

            stream_map = {}
            for in_stream in inp.streams:
                if in_stream.type not in ("video", "audio"):
                    continue
                ctx = in_stream.codec_context
                out_stream = out.add_stream(ctx.name)

                # extradata 必须先设！width/height/rate 会触发 codec open
                if ctx.extradata:
                    out_stream.codec_context.extradata = ctx.extradata

                if in_stream.type == "video":
                    out_stream.width = ctx.width
                    out_stream.height = ctx.height
                    if getattr(ctx, "pix_fmt", None) is not None:
                        out_stream.pix_fmt = ctx.pix_fmt
                elif in_stream.type == "audio":
                    if getattr(ctx, "rate", None) is not None:
                        out_stream.rate = ctx.rate
                    if getattr(ctx, "channels", None) is not None:
                        out_stream.channels = ctx.channels
                    if hasattr(ctx, "layout") and ctx.layout is not None:
                        out_stream.layout = ctx.layout

                stream_map[in_stream.index] = out_stream

            for packet in inp.demux():
                if packet.dts is None:
                    continue
                out_stream = stream_map.get(packet.stream.index)
                if out_stream is None:
                    continue
                packet.stream = out_stream
                out.mux(packet)

        except Exception as e:
            if out:
                out.close()
                out = None
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            raise MergeError(f"转封装失败: {e}") from e
        finally:
            if out:
                out.close()
            if inp:
                inp.close()

    def merge(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
    ) -> None:
        """将分离的视频和音频流合并为单个 MP4（不重编码）"""
        input_video = None
        input_audio = None
        output = None

        try:
            input_video = av.open(str(video_path))
            input_audio = av.open(str(audio_path))
            output = av.open(str(output_path), "w", format="mp4")

            in_v_stream = input_video.streams.video[0]
            in_a_stream = input_audio.streams.audio[0]
            v_ctx = in_v_stream.codec_context
            a_ctx = in_a_stream.codec_context

            # --- video stream ---
            out_v_stream = output.add_stream(v_ctx.name)
            # extradata 必须先设！
            if v_ctx.extradata:
                out_v_stream.codec_context.extradata = v_ctx.extradata
            out_v_stream.width = v_ctx.width
            out_v_stream.height = v_ctx.height

            # --- audio stream ---
            out_a_stream = output.add_stream(a_ctx.name)
            # extradata 必须先设！
            if a_ctx.extradata:
                out_a_stream.codec_context.extradata = a_ctx.extradata
            out_a_stream.rate = a_ctx.rate

            for packet in input_video.demux(in_v_stream):
                if packet.dts is None:
                    continue
                packet.stream = out_v_stream
                output.mux(packet)

            for packet in input_audio.demux(in_a_stream):
                if packet.dts is None:
                    continue
                packet.stream = out_a_stream
                output.mux(packet)

        except Exception as e:
            if output:
                output.close()
                output = None
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            raise MergeError(f"合并视频音频流失败: {e}") from e
        finally:
            if output:
                output.close()
            if input_video:
                input_video.close()
            if input_audio:
                input_audio.close()

    def concat_videos(
        self,
        input_paths: list[Path],
        output_path: Path,
    ) -> None:
        """将多个 MP4 文件拼接为一个（不重编码）"""
        if not input_paths:
            raise MergeError("没有文件可拼接")

        if len(input_paths) == 1:
            import shutil
            shutil.copy2(str(input_paths[0]), str(output_path))
            return

        output = None
        inputs = []

        try:
            first = av.open(str(input_paths[0]))
            inputs.append(first)

            output = av.open(str(output_path), "w", format="mp4")

            has_video = len(first.streams.video) > 0
            has_audio = len(first.streams.audio) > 0

            out_vs = None
            out_as = None

            if has_video:
                in_vs = first.streams.video[0]
                v_ctx = in_vs.codec_context
                out_vs = output.add_stream(v_ctx.name)
                if v_ctx.extradata:
                    out_vs.codec_context.extradata = v_ctx.extradata
                out_vs.width = v_ctx.width
                out_vs.height = v_ctx.height

            if has_audio:
                in_as = first.streams.audio[0]
                a_ctx = in_as.codec_context
                out_as = output.add_stream(a_ctx.name)
                if a_ctx.extradata:
                    out_as.codec_context.extradata = a_ctx.extradata
                out_as.rate = a_ctx.rate

            first.close()
            inputs.clear()

            v_offset = 0
            a_offset = 0

            for path in input_paths:
                inp = av.open(str(path))
                inputs.append(inp)

                if has_video and out_vs:
                    v_max_pts = v_offset
                    for pkt in inp.demux(inp.streams.video[0]):
                        if pkt.dts is None:
                            continue
                        pkt.pts += v_offset
                        pkt.dts += v_offset
                        if pkt.pts > v_max_pts:
                            v_max_pts = pkt.pts
                        pkt.stream = out_vs
                        output.mux(pkt)
                    v_offset = v_max_pts + 1

                    inp.seek(0)

                if has_audio and out_as:
                    a_max_pts = a_offset
                    for pkt in inp.demux(inp.streams.audio[0]):
                        if pkt.dts is None:
                            continue
                        pkt.pts += a_offset
                        pkt.dts += a_offset
                        if pkt.pts > a_max_pts:
                            a_max_pts = pkt.pts
                        pkt.stream = out_as
                        output.mux(pkt)
                    a_offset = a_max_pts + 1

                inp.close()
                inputs.pop()

        except Exception as e:
            if output:
                output.close()
                output = None
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            raise MergeError(f"拼接视频失败: {e}") from e
        finally:
            if output:
                output.close()
            for inp in inputs:
                try:
                    inp.close()
                except Exception:
                    pass

    def concat_audios(
        self,
        input_paths: list[Path],
        output_path: Path,
        output_format: str = "ipod",
    ) -> None:
        """将多个音频文件拼接为一个（不重编码）"""
        if not input_paths:
            raise MergeError("没有文件可拼接")

        if len(input_paths) == 1:
            import shutil
            shutil.copy2(str(input_paths[0]), str(output_path))
            return

        output = None
        inputs = []

        try:
            first = av.open(str(input_paths[0]))
            inputs.append(first)

            output = av.open(str(output_path), "w", format=output_format)

            in_as = first.streams.audio[0]
            a_ctx = in_as.codec_context
            out_as = output.add_stream(a_ctx.name)
            if a_ctx.extradata:
                out_as.codec_context.extradata = a_ctx.extradata
            out_as.rate = a_ctx.rate

            first.close()
            inputs.clear()

            a_offset = 0
            for path in input_paths:
                inp = av.open(str(path))
                inputs.append(inp)

                a_max_pts = a_offset
                for pkt in inp.demux(inp.streams.audio[0]):
                    if pkt.dts is None:
                        continue
                    pkt.pts += a_offset
                    pkt.dts += a_offset
                    if pkt.pts > a_max_pts:
                        a_max_pts = pkt.pts
                    pkt.stream = out_as
                    output.mux(pkt)
                a_offset = a_max_pts + 1

                inp.close()
                inputs.pop()

        except Exception as e:
            if output:
                output.close()
                output = None
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            raise MergeError(f"拼接音频失败: {e}") from e
        finally:
            if output:
                output.close()
            for inp in inputs:
                try:
                    inp.close()
                except Exception:
                    pass
