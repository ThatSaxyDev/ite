import flet as ft

CANVAS = "#181818"
SURFACE_1 = "#202020"
SURFACE_2 = "#222222"
BORDER = ft.Colors.with_opacity(0.07, ft.Colors.WHITE)
TEXT_PRIMARY = ft.Colors.with_opacity(0.90, ft.Colors.WHITE)
TEXT_SECONDARY = ft.Colors.with_opacity(0.62, ft.Colors.WHITE)
TEXT_MUTED = ft.Colors.with_opacity(0.40, ft.Colors.WHITE)
ACCENT = "#6EA7FF"

RADIUS_SM = 6
RADIUS_MD = 8
SPACE_XS = 6
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 20

THREADS_WIDTH = 284
CHAT_WIDTH = 940

SHADOW_SUBTLE = [
    ft.BoxShadow(
        spread_radius=0,
        blur_radius=12,
        color=ft.Colors.with_opacity(0.18, ft.Colors.BLACK),
        offset=ft.Offset(0, 4),
    )
]

MONO_STYLE = ft.TextStyle(
    font_family="monospace",
    size=13,
    color=TEXT_SECONDARY,
)
