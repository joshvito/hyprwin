from typing import List, Tuple

Rect = Tuple[int, int, int, int]  # x, y, width, height


def apply_layout(
    name: str,
    windows: int,
    area: Rect,
    gaps_in: int = 5,
    gaps_out: int = 10,
    master_factor: float = 0.55,
) -> List[Rect]:
    if windows == 0:
        return []
    if name == "rows":
        return _layout_rows(windows, area, gaps_in, gaps_out)
    elif name == "columns":
        return _layout_columns(windows, area, gaps_in, gaps_out)
    else:
        return _layout_master_stack(windows, area, gaps_in, gaps_out, master_factor)


def _apply_gaps(area: Rect, go: int) -> Rect:
    x, y, w, h = area
    return (x + go, y + go, w - 2 * go, h - 2 * go)


def _layout_master_stack(
    n: int, area: Rect, gi: int, go: int, mf: float = 0.55
) -> List[Rect]:
    ax, ay, aw, ah = _apply_gaps(area, go)
    if n == 1:
        return [(ax, ay, aw, ah)]
    if n == 2:
        mw = int(aw * mf)
        hw = aw - mw - gi
        return [
            (ax, ay, mw, ah),
            (ax + mw + gi, ay, hw, ah),
        ]
    mw = int(aw * mf)
    sw = aw - mw - gi
    stack_n = n - 1
    sh = (ah - (stack_n - 1) * gi) // stack_n
    rects = [(ax, ay, mw, ah)]
    for i in range(stack_n):
        sy = ay + i * (sh + gi)
        rects.append((ax + mw + gi, sy, sw, sh))
    return rects


def _layout_rows(n: int, area: Rect, gi: int, go: int) -> List[Rect]:
    ax, ay, aw, ah = _apply_gaps(area, go)
    rh = (ah - (n - 1) * gi) // n
    rects = []
    for i in range(n):
        ry = ay + i * (rh + gi)
        rects.append((ax, ry, aw, rh))
    return rects


def _layout_columns(n: int, area: Rect, gi: int, go: int) -> List[Rect]:
    ax, ay, aw, ah = _apply_gaps(area, go)
    cw = (aw - (n - 1) * gi) // n
    rects = []
    for i in range(n):
        rx = ax + i * (cw + gi)
        rects.append((rx, ay, cw, ah))
    return rects
