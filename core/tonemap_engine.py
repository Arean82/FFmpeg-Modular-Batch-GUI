"""HDR10 to SDR BT.709 color space tone-mapping generator.

Builds color conversion filter chains to prevent washed-out colors when
converting 4K 10-bit HDR content (BT.2020 / PQ / HLG) to standard 8-bit SDR (BT.709).
"""

TONEMAP_PRESETS = {
    "HDR10 to SDR BT.709 (High Quality Mobius)": {
        "filter": "-vf zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=mobius:desat=0.5,zscale=t=bt709:m=bt709:r=tv,format=yuv420p",
        "desc": "High quality tone-mapping using zscale and mobius algorithm with saturation preservation."
    },
    "HDR10 to SDR BT.709 (Hable Algorithm)": {
        "filter": "-vf zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0.6,zscale=t=bt709:m=bt709:r=tv,format=yuv420p",
        "desc": "Hable (film-like) tone reproduction curve popular for cinematic content."
    },
    "Fast CPU Tone-map (Linear Fallback)": {
        "filter": "-vf tonemap=hable,format=yuv420p",
        "desc": "Lightweight tone-mapping filter suitable for fast processing without zscale."
    }
}


def build_tonemap_filter(algorithm: str = "mobius", desat: float = 0.5) -> str:
    """Builds customized tone-mapping filter string."""
    algo = algorithm.lower().strip()
    if algo not in ["mobius", "hable", "reinhard"]:
        algo = "mobius"
    return (
        f"-vf zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
        f"tonemap=tonemap={algo}:desat={desat:.1f},"
        f"zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
    )
