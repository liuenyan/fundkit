"""
CJK font setup for matplotlib — extracted for reuse.
"""

import matplotlib as mpl
import matplotlib.pyplot as plt


def setup_cjk_font() -> None:
    s = ""
    for _label, _names in (
        (
            "sans-serif",
            [
                "Noto Sans CJK SC",
                "Noto Sans CJK JP",
                "WenQuanYi Micro Hei",
                "WenQuanYi Zen Hei",
                "AR PL UMing CN",
                "AR PL UKai CN",
                "Source Han Sans CN",
                "Source Han Sans SC",
                "Microsoft YaHei",
                "SimHei",
            ],
        ),
        (
            "serif",
            [
                "Noto Serif CJK SC",
                "Source Han Serif CN",
                "AR PL New Sung",
                "SimSun",
            ],
        ),
    ):
        for _name in _names:
            try:
                mpl.font_manager.findfont(_name, fallback_to_default=False)
                s += f"{_name}, "
                break
            except Exception:
                continue
    if s:
        plt.rcParams["font.family"] = s.rstrip(", ")
    else:
        plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["axes.unicode_minus"] = False
