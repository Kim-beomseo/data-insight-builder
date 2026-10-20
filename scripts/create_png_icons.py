import zlib
import struct
import math
import os

def create_png(width, height, draw_func, out_path):
    # Generates a RGBA PNG image
    raw_data = bytearray()
    for y in range(height):
        raw_data.append(0)  # filter type 0: None
        for x in range(width):
            r, g, b, a = draw_func(x, y, width, height)
            raw_data.extend((r, g, b, a))

    # Compress
    compressed = zlib.compress(bytes(raw_data), level=9)

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

    header = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
    idat = chunk(b'IDAT', compressed)
    iend = chunk(b'IEND', b'')

    with open(out_path, 'wb') as f:
        f.write(header + ihdr + idat + iend)

def app_icon_pixel(x, y, w, h):
    # Normalized coords [0, 1]
    nx = x / float(w)
    ny = y / float(h)

    # Rounded rectangle mask with radius 0.22
    corner_r = 0.22
    dx = max(0.0, max(corner_r - nx, nx - (1.0 - corner_r)))
    dy = max(0.0, max(corner_r - ny, ny - (1.0 - corner_r)))
    dist = math.sqrt(dx * dx + dy * dy)
    
    if dist > corner_r:
        # Outside corner
        return 0, 0, 0, 0
    
    # Smooth edge antialiasing
    alpha = 255
    if dist > corner_r - (1.5 / w):
        aa = (corner_r - dist) / (1.5 / w)
        alpha = int(max(0, min(255, aa * 255)))

    # Background gradient: from (15, 23, 42) to (37, 99, 235) to (139, 92, 246)
    t = (nx + ny) * 0.5
    br = int(15 * (1 - t) + 37 * t)
    bg = int(23 * (1 - t) + 99 * t)
    bb = int(42 * (1 - t) + 235 * t)

    # 4 Bar charts
    # Bar baseline at ny = 0.76
    baseline = 0.76
    bars = [
        (0.22, 0.32, 0.54, (59, 130, 246)),   # Bar 1: blue
        (0.38, 0.48, 0.42, (16, 185, 129)),   # Bar 2: emerald
        (0.54, 0.64, 0.30, (245, 158, 11)),   # Bar 3: amber
        (0.70, 0.80, 0.18, (139, 92, 246)),   # Bar 4: purple (highlight)
    ]

    r, g, b = br, bg, bb

    # Baseline axis line
    if abs(ny - baseline) < 0.008 and 0.16 <= nx <= 0.84:
        r, g, b = 203, 213, 225

    # Draw bars
    for x1, x2, top_y, (cr, cg, cb) in bars:
        if x1 <= nx <= x2 and top_y <= ny <= baseline:
            # Subtle gradient within bar
            bar_t = (ny - top_y) / (baseline - top_y)
            r = int(cr * (1 - bar_t * 0.2))
            g = int(cg * (1 - bar_t * 0.2))
            b = int(cb * (1 - bar_t * 0.2))

    # Upward trend line
    # Quadratic curve from (0.27, 0.50) through (0.59, 0.26) to (0.75, 0.14)
    if 0.27 <= nx <= 0.76:
        u = (nx - 0.27) / (0.75 - 0.27)
        line_y = 0.50 * (1 - u)**2 + 2 * (1 - u) * u * 0.28 + u**2 * 0.14
        if abs(ny - line_y) < 0.016:
            r, g, b = 244, 63, 94  # Rose pink accent line

    # Sparkle star at top right (0.82, 0.22)
    s_dx = abs(nx - 0.82)
    s_dy = abs(ny - 0.22)
    if (s_dx < 0.035 and s_dy < 0.008) or (s_dy < 0.035 and s_dx < 0.008):
        r, g, b = 251, 191, 36

    return r, g, b, alpha

if __name__ == '__main__':
    os.makedirs('static/icons', exist_ok=True)
    create_png(192, 192, app_icon_pixel, 'static/icons/icon-192.png')
    create_png(512, 512, app_icon_pixel, 'static/icons/icon-512.png')
    print('Generated icon-192.png and icon-512.png successfully')
