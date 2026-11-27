"""界面主题常量（NFR-4：全中文界面、颜色 + 文字双提示、最小字号 ≥ 12）。"""

from __future__ import annotations

__all__ = [
    "MIN_FONT_POINT",
    "FONT_FAMILY",
    "COLOR_BG",
    "COLOR_PANEL",
    "COLOR_TEXT",
    "COLOR_MUTED",
    "ALARM_COLORS",
    "ALARM_BACKGROUNDS",
    "ALARM_LABELS",
]

#: 最小字号（NFR-4：最小字号 ≥ 12）
MIN_FONT_POINT = 12

#: 正文字体（Windows 优先，回退到系统中文字体）
FONT_FAMILY = "Microsoft YaHei UI, PingFang SC, Noto Sans CJK SC, sans-serif"

COLOR_BG = "#f5f6f8"
COLOR_PANEL = "#ffffff"
COLOR_TEXT = "#1f2329"
COLOR_MUTED = "#8a9099"

#: 告警前景色（同时配合文字提示，满足"双提示"要求）
ALARM_COLORS = {
    "info": "#2f6feb",
    "warning": "#b7791f",
    "critical": "#c0392b",
}

#: 告警背景色
ALARM_BACKGROUNDS = {
    "info": "#e8f0fe",
    "warning": "#fdf6e3",
    "critical": "#fdecea",
}

#: 告警文字标签（不依赖颜色即可读懂）
ALARM_LABELS = {
    "info": "提示",
    "warning": "警告",
    "critical": "严重",
}
