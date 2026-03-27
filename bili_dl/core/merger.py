"""PyAV 视频/音频流合并与拼接"""

from pathlib import Path

import av

from ..exceptions import MergeError


class VideoMerger:
    """使用 PyAV 合并/拼接媒体流"""

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

            out_v_stream = output.add_stream(in_v_stream.codec_context.name)
            out_v_stream.width = in_v_stream.codec_context.width
            out_v_stream.height = in_v_stream.codec_context.height
            if in_v_stream.codec_context.extradata:
                out_v_stream.codec_context.extradata = in_v_stream.codec_context.extradata

            out_a_stream = output.add_stream(
                in_a_stream.codec_context.name,
                rate=in_a_stream.codec_context.rate,
            )
            if in_a_stream.codec_context.extradata:
                out_a_stream.codec_context.extradata = in_a_stream.codec_context.extradata

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
            # 用第一个文件初始化输出流参数
            first = av.open(str(input_paths[0]))
            inputs.append(first)

            output = av.open(str(output_path), "w", format="mp4")

            has_video = len(first.streams.video) > 0
            has_audio = len(first.streams.audio) > 0

            out_vs = None
            out_as = None

            if has_video:
                in_vs = first.streams.video[0]
                out_vs = output.add_stream(in_vs.codec_context.name)
                out_vs.width = in_vs.codec_context.width
                out_vs.height = in_vs.codec_context.height
                if in_vs.codec_context.extradata:
                    out_vs.codec_context.extradata = in_vs.codec_context.extradata

            if has_audio:
                in_as = first.streams.audio[0]
                out_as = output.add_stream(
                    in_as.codec_context.name,
                    rate=in_as.codec_context.rate,
                )
                if in_as.codec_context.extradata:
                    out_as.codec_context.extradata = in_as.codec_context.extradata

            first.close()
            inputs.clear()

            # 逐文件拼接，调整 PTS/DTS 偏移
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
            out_as = output.add_stream(
                in_as.codec_context.name,
                rate=in_as.codec_context.rate,
            )
            if in_as.codec_context.extradata:
                out_as.codec_context.extradata = in_as.codec_context.extradata

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
