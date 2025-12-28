def logical_to_physical(logical_rect, dpr):
    """Converts (x, y, w, h) from logical UI pixels to physical screen pixels."""
    x, y, w, h = logical_rect
    return (int(x * dpr), int(y * dpr), int(w * dpr), int(h * dpr))

def physical_to_logical(physical_rect, dpr):
    """Converts (x, y, w, h) from physical screen pixels back to logical UI pixels."""
    x, y, w, h = physical_rect
    return (x / dpr, y / dpr, w / dpr, h / dpr)

def global_to_local(global_rect, screen_origin_logical):
    """
    Translates global logical coordinates (spanning all monitors)
    to screen-local logical coordinates (0,0 is top-left of specific monitor).
    """
    gx, gy, gw, gh = global_rect
    ox, oy = screen_origin_logical
    return (gx - ox, gy - oy, gw, gh)

def local_to_global(local_rect, screen_origin_logical):
    """Translates screen-local logical coordinates back to global logical coordinates."""
    lx, ly, lw, lh = local_rect
    ox, oy = screen_origin_logical
    return (lx + ox, ly + oy, lw, lh)