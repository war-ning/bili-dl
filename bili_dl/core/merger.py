"""PyAV 视频/音频流合并"""

from pathlib import Path

import av

from ..exceptions import MergeError


class VideoMerger:
    """使用 PyAV 将 DASH 视频流和音频流 remux 为 MP4"""

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

            # PyAV 17+ 不支持 template= 参数，需手动复制 codec 参数
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
            # #13: 失败时清理残留的输出文件
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
