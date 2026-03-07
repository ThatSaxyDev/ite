import flet as ft

CANVAS = "#181818"
SURFACE_1 = "#202020"
SURFACE_2 = "#222222"
SURFACE_3 = "#262626"
SURFACE_ELEVATED = "#1D1D1D"
BORDER = ft.Colors.with_opacity(0.07, ft.Colors.WHITE)
BORDER_STRONG = ft.Colors.with_opacity(0.14, ft.Colors.WHITE)
HAIRLINE = ft.Colors.with_opacity(0.05, ft.Colors.WHITE)
TEXT_PRIMARY = ft.Colors.with_opacity(0.90, ft.Colors.WHITE)
TEXT_SECONDARY = ft.Colors.with_opacity(0.62, ft.Colors.WHITE)
TEXT_MUTED = ft.Colors.with_opacity(0.40, ft.Colors.WHITE)
ACCENT = "#6EA7FF"
ACCENT_SOFT = ft.Colors.with_opacity(0.18, ACCENT)
SUCCESS = ft.Colors.with_opacity(0.90, ft.Colors.GREEN_300)
SUCCESS_SOFT = ft.Colors.with_opacity(0.22, ft.Colors.GREEN_300)
DANGER = ft.Colors.with_opacity(0.90, ft.Colors.RED_300)
DANGER_SOFT = ft.Colors.with_opacity(0.22, ft.Colors.RED_300)
WARNING = ft.Colors.with_opacity(0.90, ft.Colors.AMBER_300)
WARNING_SOFT = ft.Colors.with_opacity(0.22, ft.Colors.AMBER_300)

RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 10
SPACE_XS = 6
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 20

THREADS_WIDTH = 284
THREADS_WIDTH_COLLAPSED = 68
CONTENT_LANE_WIDTH = 760
CHAT_WIDTH = CONTENT_LANE_WIDTH
ASSISTANT_MESSAGE_WIDTH = 760
USER_MESSAGE_WIDTH = 600
SPECIAL_CARD_WIDTH = 760
FONT_UI = "IBM Plex Sans"
FONT_MONO = "IBM Plex Mono"

TYPE_XS = 10
TYPE_SM = 11
TYPE_MD = 12
TYPE_BODY = 13
TYPE_TITLE = 14
TYPE_H1 = 18

WEIGHT_REGULAR = ft.FontWeight.W_400
WEIGHT_MEDIUM = ft.FontWeight.W_500
WEIGHT_SEMIBOLD = ft.FontWeight.W_600
WEIGHT_BOLD = ft.FontWeight.W_700

CHAT_ITEM_GAP = 24
CHAT_BLOCK_GAP = 20
CARD_PAD_X = 10
CARD_PAD_Y = 10
COMPOSER_CONTROL_HEIGHT = 40

SHADOW_SUBTLE = [
    ft.BoxShadow(
        spread_radius=0,
        blur_radius=12,
        color=ft.Colors.with_opacity(0.18, ft.Colors.BLACK),
        offset=ft.Offset(0, 4),
    )
]

MONO_STYLE = ft.TextStyle(
    font_family=FONT_MONO,
    size=TYPE_SM,
    color=TEXT_SECONDARY,
)
