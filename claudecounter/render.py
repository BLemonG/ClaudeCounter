from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from PIL import Image

from .snapshot import UsageSnapshot, utc_now_iso

SIZE = 16
RING_BOTTOM_ROW = SIZE - 2
WEEKLY_ROW = SIZE - 1
INTERIOR_FIRST_COLUMN = 1
INTERIOR_LAST_COLUMN = SIZE - 2
INTERIOR_FIRST_ROW = 1
INTERIOR_LAST_ROW = RING_BOTTOM_ROW - 1
GLYPH_WIDTH = 5
GLYPH_HEIGHT = 9
GLYPH_SPACING = 2

SESSION_WINDOW_SECONDS = 5 * 60 * 60
WEEKLY_WINDOW_SECONDS = 7 * 24 * 60 * 60

Color = Tuple[int, int, int]
Position = Tuple[int, int]

BACKGROUND: Color = (0, 0, 0)
RING_TRACK: Color = (42, 42, 42)
LABEL: Color = (240, 240, 240)
WEEKLY_FILL: Color = (150, 80, 255)
WEEKLY_TRACK: Color = (38, 18, 68)
TIME_MARKER: Color = (0, 190, 255)
UNAVAILABLE_LABEL: Color = (120, 120, 120)
UNAVAILABLE_TEXT = "--"

SESSION_GREEN: Color = (0, 220, 80)
SESSION_YELLOW: Color = (245, 200, 0)
SESSION_ORANGE: Color = (255, 120, 0)
SESSION_RED: Color = (240, 40, 40)

SESSION_COLOR_BY_UPPER_BOUND: Tuple[Tuple[float, Color], ...] = (
    (60.0, SESSION_GREEN),
    (80.0, SESSION_YELLOW),
    (95.0, SESSION_ORANGE),
)

STALE_BRIGHTNESS = 0.34

GLYPHS_5X9: Dict[str, Tuple[str, ...]] = {
    "0": (
        ".###.",
        "##.##",
        "##.##",
        "##.##",
        "##.##",
        "##.##",
        "##.##",
        "##.##",
        ".###.",
    ),
    "1": (
        "..##.",
        ".###.",
        "####.",
        "..##.",
        "..##.",
        "..##.",
        "..##.",
        "..##.",
        "#####",
    ),
    "2": (
        ".###.",
        "##.##",
        "...##",
        "...##",
        "..##.",
        ".##..",
        "##...",
        "##...",
        "#####",
    ),
    "3": (
        ".###.",
        "##.##",
        "...##",
        "...##",
        ".###.",
        "...##",
        "...##",
        "##.##",
        ".###.",
    ),
    "4": (
        "##.##",
        "##.##",
        "##.##",
        "##.##",
        "#####",
        "...##",
        "...##",
        "...##",
        "...##",
    ),
    "5": (
        "#####",
        "##...",
        "##...",
        "####.",
        "...##",
        "...##",
        "...##",
        "##.##",
        ".###.",
    ),
    "6": (
        "..##.",
        ".##..",
        "##...",
        "##...",
        "####.",
        "##.##",
        "##.##",
        "##.##",
        ".###.",
    ),
    "7": (
        "#####",
        "...##",
        "...##",
        "..##.",
        "..##.",
        "..##.",
        ".##..",
        ".##..",
        ".##..",
    ),
    "8": (
        ".###.",
        "##.##",
        "##.##",
        "##.##",
        ".###.",
        "##.##",
        "##.##",
        "##.##",
        ".###.",
    ),
    "9": (
        ".###.",
        "##.##",
        "##.##",
        "##.##",
        ".####",
        "...##",
        "...##",
        "..##.",
        ".##..",
    ),
    "-": (
        ".....",
        ".....",
        ".....",
        "#####",
        "#####",
        ".....",
        ".....",
        ".....",
        ".....",
    ),
    "!": (
        ".###.",
        ".###.",
        ".###.",
        ".###.",
        ".###.",
        ".###.",
        ".###.",
        ".....",
        ".###.",
    ),
}

def clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def dimmed(color: Color) -> Color:
    return (
        int(round(color[0] * STALE_BRIGHTNESS)),
        int(round(color[1] * STALE_BRIGHTNESS)),
        int(round(color[2] * STALE_BRIGHTNESS)),
    )


def session_color(percent: float) -> Color:
    for upper_bound, color in SESSION_COLOR_BY_UPPER_BOUND:
        if percent < upper_bound:
            return color
    return SESSION_RED


def ring_positions() -> List[Position]:
    last_column = SIZE - 1
    positions: List[Position] = [(x, 0) for x in range(SIZE)]
    positions += [(last_column, y) for y in range(1, RING_BOTTOM_ROW + 1)]
    positions += [(x, RING_BOTTOM_ROW) for x in range(SIZE - 2, -1, -1)]
    positions += [(0, y) for y in range(RING_BOTTOM_ROW - 1, 0, -1)]
    top_centre = SIZE // 2
    return positions[top_centre:] + positions[:top_centre]


def lit_count(percent: float, total: int) -> int:
    count = int(round(total * percent / 100.0))
    if percent > 0.0 and count == 0:
        return 1
    return min(count, total)


def session_label(percent: float) -> str:
    value = int(round(percent))
    if value >= 100:
        return "!!"
    return f"{value:02d}"


def label_width(text: str) -> int:
    if not text:
        return 0
    return len(text) * (GLYPH_WIDTH + GLYPH_SPACING) - GLYPH_SPACING


def parse_timestamp(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def elapsed_fraction(
    resets_at_text: Optional[str], fetched_at_text: Optional[str], window_seconds: int
) -> Optional[float]:
    resets_at = parse_timestamp(resets_at_text)
    fetched_at = parse_timestamp(fetched_at_text)
    if resets_at is None or fetched_at is None:
        return None
    remaining_seconds = (resets_at - fetched_at).total_seconds()
    if remaining_seconds <= 0.0:
        return 1.0
    if remaining_seconds >= window_seconds:
        return 0.0
    return 1.0 - remaining_seconds / window_seconds


def session_elapsed_fraction(
    snapshot: UsageSnapshot, now: Optional[str] = None
) -> Optional[float]:
    return elapsed_fraction(
        snapshot.session_resets_at, now or utc_now_iso(), SESSION_WINDOW_SECONDS
    )


def time_marker_position(fraction: float) -> Position:
    positions = ring_positions()
    index = int(round(max(0.0, min(1.0, fraction)) * len(positions)))
    return positions[min(index, len(positions) - 1)]


def draw_session_ring(pixels, percent: float, stale: bool) -> None:
    positions = ring_positions()
    fill_color = session_color(percent)
    if stale:
        fill_color = dimmed(fill_color)
    lit = lit_count(percent, len(positions))
    for index, (x, y) in enumerate(positions):
        pixels[x, y] = fill_color if index < lit else RING_TRACK


def draw_time_marker(pixels, fraction: float, stale: bool) -> None:
    color = dimmed(TIME_MARKER) if stale else TIME_MARKER
    pixels[time_marker_position(fraction)] = color


def draw_text(pixels, text: str, color: Color) -> None:
    origin_x = (SIZE - label_width(text)) // 2
    origin_y = INTERIOR_FIRST_ROW + (
        (INTERIOR_LAST_ROW - INTERIOR_FIRST_ROW + 1 - GLYPH_HEIGHT) // 2
    )
    for character in text:
        glyph = GLYPHS_5X9[character]
        for row_offset, row in enumerate(glyph):
            for column_offset, cell in enumerate(row):
                if cell == "#":
                    pixels[origin_x + column_offset, origin_y + row_offset] = color
        origin_x += GLYPH_WIDTH + GLYPH_SPACING


def draw_session_label(pixels, percent: float, stale: bool) -> None:
    draw_text(pixels, session_label(percent), LABEL)


def weekly_elapsed_fraction(
    snapshot: UsageSnapshot, now: Optional[str] = None
) -> Optional[float]:
    return elapsed_fraction(
        snapshot.weekly_resets_at, now or utc_now_iso(), WEEKLY_WINDOW_SECONDS
    )


def weekly_marker_column(fraction: float) -> int:
    column = int(round(max(0.0, min(1.0, fraction)) * SIZE))
    return min(column, SIZE - 1)


def draw_weekly_bar(pixels, percent: float, stale: bool) -> None:
    fill_color = dimmed(WEEKLY_FILL) if stale else WEEKLY_FILL
    lit = lit_count(percent, SIZE)
    for x in range(SIZE):
        pixels[x, WEEKLY_ROW] = fill_color if x < lit else WEEKLY_TRACK


def draw_weekly_marker(pixels, fraction: float, stale: bool) -> None:
    color = dimmed(TIME_MARKER) if stale else TIME_MARKER
    pixels[weekly_marker_column(fraction), WEEKLY_ROW] = color


def render(snapshot: UsageSnapshot, now: Optional[str] = None) -> Image.Image:
    reference = now or utc_now_iso()
    session = clamp_percent(snapshot.session_pct)
    weekly = clamp_percent(snapshot.weekly_pct)
    image = Image.new("RGB", (SIZE, SIZE), BACKGROUND)
    pixels = image.load()
    draw_session_ring(pixels, session, snapshot.stale)
    elapsed = session_elapsed_fraction(snapshot, reference)
    if elapsed is not None:
        draw_time_marker(pixels, elapsed, snapshot.stale)
    draw_session_label(pixels, session, snapshot.stale)
    draw_weekly_bar(pixels, weekly, snapshot.stale)
    weekly_elapsed = weekly_elapsed_fraction(snapshot, reference)
    if weekly_elapsed is not None:
        draw_weekly_marker(pixels, weekly_elapsed, snapshot.stale)
    return image


def render_unavailable() -> Image.Image:
    image = Image.new("RGB", (SIZE, SIZE), BACKGROUND)
    pixels = image.load()
    for x, y in ring_positions():
        pixels[x, y] = RING_TRACK
    for x in range(SIZE):
        pixels[x, WEEKLY_ROW] = WEEKLY_TRACK
    draw_text(pixels, UNAVAILABLE_TEXT, UNAVAILABLE_LABEL)
    return image


def scaled_preview(image: Image.Image, scale: int) -> Image.Image:
    return image.resize((SIZE * scale, SIZE * scale), Image.Resampling.NEAREST)


def ascii_art(image: Image.Image) -> str:
    symbol_by_color = {
        BACKGROUND: ".",
        RING_TRACK: "-",
        WEEKLY_TRACK: "_",
        LABEL: "#",
        UNAVAILABLE_LABEL: "-",
        WEEKLY_FILL: "=",
        dimmed(WEEKLY_FILL): "=",
        TIME_MARKER: "*",
        dimmed(TIME_MARKER): "*",
    }
    for session_fill in (SESSION_GREEN, SESSION_YELLOW, SESSION_ORANGE, SESSION_RED):
        symbol_by_color[session_fill] = "O"
        symbol_by_color[dimmed(session_fill)] = "o"
    pixels = image.load()
    rows = []
    for y in range(SIZE):
        cells = []
        for x in range(SIZE):
            color = pixels[x, y]
            cells.append(symbol_by_color.get(color, "O"))
        rows.append("".join(cells))
    return "\n".join(rows)
