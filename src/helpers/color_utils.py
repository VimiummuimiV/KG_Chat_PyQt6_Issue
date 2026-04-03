"""Color utilities for HSL manipulation"""
import colorsys


def hsl_to_hex(h: float, s: float, l: float) -> str:
    """Convert HSL to hex color
    
    Args:
        h: Hue (0-360)
        s: Saturation (0-100)
        l: Lightness (0-100)
    
    Returns:
        Hex color string like '#FF0000'
    """
    # Normalize to 0-1 range
    h_norm = h / 360.0
    s_norm = s / 100.0
    l_norm = l / 100.0
    
    # Convert to RGB
    r, g, b = colorsys.hls_to_rgb(h_norm, l_norm, s_norm)
    
    # Convert to 0-255 range and format as hex
    return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


def get_private_message_colors(config, is_dark_theme: bool) -> dict:
    # Read only hue and saturation from config
    hue = config.get("ui", "private_message_color", "hue") or 0
    saturation = config.get("ui", "private_message_color", "saturation") or 75
    
    # Derive lightness values based on theme
    if is_dark_theme:
        # Dark theme: light text on dark backgrounds
        lightness_values = {
            "text": 75,          # Light & readable text
            "input_bg": 15,      # Dark background
            "input_border": 35   # Medium contrast border
        }
    else:
        # Light theme: dark text on light backgrounds
        lightness_values = {
            "text": 35,          # Dark & readable text
            "input_bg": 85,      # Light background
            "input_border": 55   # Medium contrast border
        }
    
    # Generate all colors
    return {
        key: hsl_to_hex(hue, saturation, lightness)
        for key, lightness in lightness_values.items()
    }


def get_ban_message_colors(config, is_dark_theme: bool) -> dict:
    # Read only hue and saturation from config
    hue = config.get("ui", "ban_message_color", "hue") or 170 
    saturation = config.get("ui", "ban_message_color", "saturation") or 75
    
    # Derive lightness values based on theme
    if is_dark_theme:
        # Dark theme: light text on dark backgrounds
        lightness_values = {
            "text": 75,          # Light & readable text
        }
    else:
        # Light theme: dark text on light backgrounds
        lightness_values = {
            "text": 35,          # Dark & readable text
        }
    
    # Generate all colors
    return {
        key: hsl_to_hex(hue, saturation, lightness)
        for key, lightness in lightness_values.items()
    }


def get_system_message_colors(config, is_dark_theme: bool) -> dict:
    # Read only hue and saturation from config
    hue = config.get("ui", "system_message_color", "hue") or 240
    saturation = config.get("ui", "system_message_color", "saturation") or 0
    
    # Derive lightness values based on theme
    if is_dark_theme:
        # Dark theme: light gray text
        lightness_values = {
            "text": 60,          # Medium-light gray
        }
    else:
        # Light theme: dark gray text
        lightness_values = {
            "text": 50,          # Medium gray
        }
    
    # Generate all colors
    return {
        key: hsl_to_hex(hue, saturation, lightness)
        for key, lightness in lightness_values.items()
    }


def get_mention_color(is_dark_theme: bool) -> str:
    """Get mention highlight color based on theme"""
    return "#00FF00" if is_dark_theme else "#008000"