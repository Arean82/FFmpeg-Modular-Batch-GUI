"""Token substitution engine compatible with FFmpeg Batch variables."""
import os
from typing import Any


def substitute_tokens(template: str, input_file: str, output_file: str, metadata: dict[str, Any] | None = None) -> str:
    """
    Substitutes FFmpeg Batch and DOS-style tokens using exact string replacement (No Regex).
    %~n : file name without extension
    %~x : file extension (with dot)
    %~p : directory path
    <source_dir> : full path to directory of input file
    <filename> : base filename without extension
    <ext> : extension
    <res> : resolution
    <vcodec> : video codec
    <acodec> : audio codec
    """
    if metadata is None:
        metadata = {}

    dirname, fullname = os.path.split(input_file)
    name, ext = os.path.splitext(fullname)

    replacements = [
        ("%~n", name),
        ("%~x", ext),
        ("%~p", dirname),
        ("<source_dir>", dirname),
        ("<filename>", name),
        ("<ext>", ext.lstrip(".")),
        ("<res>", metadata.get("resolution", "")),
        ("<vcodec>", metadata.get("video_codec", "")),
        ("<acodec>", metadata.get("audio_codec", "")),
    ]

    result = template
    for pattern, val in replacements:
        if pattern in result:
            result = result.replace(pattern, str(val))
        # Case insensitive fallback
        pattern_lower = pattern.lower()
        if pattern_lower in result.lower() and pattern_lower != pattern:
            # Replace case-insensitively using standard split/join
            idx = result.lower().find(pattern_lower)
            while idx != -1:
                result = result[:idx] + str(val) + result[idx + len(pattern_lower):]
                idx = result.lower().find(pattern_lower)

    return result
