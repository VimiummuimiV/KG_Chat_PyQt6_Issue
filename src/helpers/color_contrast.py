"""Color contrast optimization for usernames on dark backgrounds."""

def hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join([c*2 for c in hex_color])
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(rgb: tuple) -> str:
    """Convert RGB tuple to hex color string."""
    return '#{:02x}{:02x}{:02x}'.format(int(rgb[0]), int(rgb[1]), int(rgb[2]))

def relative_luminance(rgb: tuple) -> float:
    """Calculate relative luminance (WCAG formula)."""
    def adjust(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * adjust(rgb[0]) + 0.7152 * adjust(rgb[1]) + 0.0722 * adjust(rgb[2])

def contrast_ratio(c1: tuple, c2: tuple) -> float:
    """Calculate contrast ratio between two colors."""
    l1, l2 = relative_luminance(c1), relative_luminance(c2)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)

def rgb_to_hsl(rgb: tuple) -> tuple:
    """Convert RGB to HSL."""
    r, g, b = [x / 255.0 for x in rgb]
    max_val, min_val = max(r, g, b), min(r, g, b)
    diff = max_val - min_val
    l = (max_val + min_val) / 2.0
    
    if diff == 0:
        return (0, 0, l)
    
    s = diff / (2.0 - max_val - min_val) if l > 0.5 else diff / (max_val + min_val)
    
    if max_val == r:
        h = ((g - b) / diff + (6 if g < b else 0)) / 6.0
    elif max_val == g:
        h = ((b - r) / diff + 2) / 6.0
    else:
        h = ((r - g) / diff + 4) / 6.0
    
    return (h * 360, s, l)

def hsl_to_rgb(hsl: tuple) -> tuple:
    """Convert HSL to RGB."""
    h, s, l = hsl
    h = h / 360.0
    
    if s == 0:
        v = int(l * 255)
        return (v, v, v)
    
    def hue_to_rgb(p, q, t):
        t = t + 1 if t < 0 else t - 1 if t > 1 else t
        if t < 1/6: return p + (q - p) * 6 * t
        if t < 1/2: return q
        if t < 2/3: return p + (q - p) * (2/3 - t) * 6
        return p
    
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    return (round(hue_to_rgb(p, q, h + 1/3) * 255),
            round(hue_to_rgb(p, q, h) * 255),
            round(hue_to_rgb(p, q, h - 1/3) * 255))

def optimize_color_contrast(fg_hex: str, bg_hex: str = '#1E1E1E', 
                           target_ratio: float = 4.5) -> str:
    """Optimize foreground color to meet contrast ratio on background.
    
    Args:
        fg_hex: Foreground hex color (username color from server)
        bg_hex: Background hex color (default dark gray)
        target_ratio: Target contrast ratio (4.5 for WCAG AA)
    
    Returns:
        Optimized hex color string
    """
    if not fg_hex:
        return '#FFFFFF'
    
    fg_rgb = hex_to_rgb(fg_hex)
    bg_rgb = hex_to_rgb(bg_hex)
    
    if contrast_ratio(fg_rgb, bg_rgb) >= target_ratio:
        return fg_hex
    
    h, s, l = rgb_to_hsl(fg_rgb)
    bg_lum = relative_luminance(bg_rgb)
    
    # Dark background - lighten text; light background - darken text
    min_l, max_l = (l, 1.0) if bg_lum < 0.5 else (0.0, l)
    best_l = max_l if bg_lum < 0.5 else min_l
    
    for _ in range(20):
        test_l = (min_l + max_l) / 2
        test_rgb = hsl_to_rgb((h, s, test_l))
        test_ratio = contrast_ratio(test_rgb, bg_rgb)
        
        if test_ratio >= target_ratio:
            best_l = test_l
            if bg_lum < 0.5:
                max_l = test_l
            else:
                min_l = test_l
        else:
            if bg_lum < 0.5:
                min_l = test_l
            else:
                max_l = test_l
    
    return rgb_to_hex(hsl_to_rgb((h, s, best_l)))