"""Token substitution engine compatible with FFmpeg Batch variables."""
import os
import re
from typing import Dict, Any

def substitute_tokens(template: str, input_file: str, output_file: str, metadata: Dict[str, Any] = None) -> str:
    """
    Substitutes FFmpeg Batch and DOS-style tokens:
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
    
    replacements = {
        r"%~n": name,
        r"%~x": ext,
        r"%~p": dirname,
        r"<source_dir>": dirname,
        r"<filename>": name,
        r"<ext>": ext.lstrip("."),
        r"<res>": metadata.get("resolution", ""),
        r"<vcodec>": metadata.get("video_codec", ""),
        r"<acodec>": metadata.get("audio_codec", ""),
    }
    
    result = template
    for pattern, val in replacements.items():
        result = re.sub(re.escape(pattern), str(val), result, flags=re.IGNORECASE)
        
    return result
