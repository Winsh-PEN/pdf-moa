# SPDX-License-Identifier: AGPL-3.0-only
"""Line icons drawn for PDF 모아 (24x24 SVG paths), rendered with PyMuPDF.

The icons are original drawings kept as text so the source stays editable and
no image files are needed in the PyInstaller bundle.
"""
from functools import lru_cache
import pymupdf as fitz

PATHS = {
    'add': '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M12 11v6M9 14h6"/>',
    'undo': '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    'select_all': '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="m8 12 3 3 5-6"/>',
    'reverse': '<path d="M7 20V4M3 8l4-4 4 4"/><path d="M17 4v16M13 16l4 4 4-4"/>',
    'up': '<path d="M12 19V5M5 12l7-7 7 7"/>',
    'down': '<path d="M12 5v14M19 12l-7 7-7-7"/>',
    'rotate': '<path d="M20 12a8 8 0 1 1-2.34-5.66L20 9"/><path d="M20 4v5h-5"/>',
    'trash': '<path d="M4 7h16M10 11v6M14 11v6"/><path d="m6 7 1 12.1A2 2 0 0 0 9 21h6a2 2 0 0 0 2-1.9L18 7"/><path d="M9 7V4h6v3"/>',
    'open': '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    'edit': '<path d="M4 20h4L19 9a2.83 2.83 0 0 0-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    'info': '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    'clear': '<path d="M4 6h10M4 12h10M4 18h6"/><path d="m15 15 5 5M20 15l-5 5"/>',
    'save': '<path d="M5 4h11l4 4v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    'save_selected': '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="m9 14 2 2 4-4"/>',
    'split': '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M8.5 7.8 20 17M8.5 16.2 20 7"/>',
    'zoom_in': '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4M11 8v6M8 11h6"/>',
    'zoom_out': '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4M8 11h6"/>',
    'fit': '<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>',
    'replace': '<path d="m3 17 3.5-9 3.5 9M4.3 14h4.4"/><path d="M13 12h7M17 9l3 3-3 3"/>',
    'text': '<path d="M4 6V4h12v2M10 4v16M7 20h6"/><path d="M18 14v6M15 17h6"/>',
    'image': '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/><path d="m21 16-5-5L5 20"/>',
    'check': '<path d="M5 12l5 5L20 7"/>',
    'font': '<path d="M4 20 9.5 5h1L16 20M6.2 14h7.6"/><path d="M18 9v6M15 12h6"/>',
    'redo': '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    'rotate_left': '<path d="M4 12a8 8 0 1 0 2.34-5.66L4 9"/><path d="M4 4v5h5"/>',
    'duplicate': '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    'blank': '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    'insert': '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M8 14h7M12 11l3 3-3 3"/>',
    'top': '<path d="M5 4h14M12 20V9M7 13l5-5 5 5"/>',
    'bottom': '<path d="M5 20h14M12 4v11M7 11l5 5 5-5"/>',
    'erase': '<path d="M4 7V5h11v2M9.5 5v14M7 19h5"/><path d="m15 13 6 6M21 13l-6 6"/>',
    'move': '<path d="M12 3v18M3 12h18"/><path d="m9 6 3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3"/>',
    'shield': '<path d="M12 3 5 6v5c0 4.5 3 8.3 7 10 4-1.7 7-5.5 7-10V6z"/><path d="M12 8v4M12 15h.01"/>',
}

LOGO = '''<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
<rect x="2" y="2" width="60" height="60" rx="14" fill="#2563eb"/>
<path d="M17 10h15l10 10v24a4 4 0 0 1-4 4H17a4 4 0 0 1-4-4V14a4 4 0 0 1 4-4z" fill="#8fb4ff"/>
<path d="M26 17h15l10 10v23a4 4 0 0 1-4 4H26a4 4 0 0 1-4-4V21a4 4 0 0 1 4-4z" fill="#ffffff"/>
<path d="M41 17v8a2 2 0 0 0 2 2h8z" fill="#c7d9ff"/>
<path d="M28 35h16M28 41h16M28 47h10" stroke="#2563eb" stroke-width="3" stroke-linecap="round" fill="none"/>
</svg>'''


CHECKBOX = {
    False: '<rect x="3" y="3" width="18" height="18" rx="4" fill="#ffffff" stroke="#94a3b8" stroke-width="1.6"/>',
    True: '<rect x="3" y="3" width="18" height="18" rx="4" fill="#2563eb"/>'
          '<path d="m7.2 12.2 3.1 3.1 6.5-6.6" fill="none" stroke="#ffffff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
}


def checkbox_png(checked, size):
    return png('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
               f'{CHECKBOX[checked]}</svg>', size)


def svg(name, color, width=2.0):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
            f'<g fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">'
            f'{PATHS[name]}</g></svg>')


@lru_cache(maxsize=None)
def png(source, size):
    with fitz.open(stream=source.encode('utf-8'), filetype='svg') as doc:
        page = doc[0]
        zoom = size / max(page.rect.width, page.rect.height)
        return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=True).tobytes('png')


def icon_png(name, size, color='#334155'):
    return png(svg(name, color, 2.0 if size >= 18 else 2.2), size)


def logo_png(size):
    return png(LOGO, size)


def write_ico(path, sizes=(16, 20, 24, 32, 40, 48, 64, 128, 256)):
    """Write the app icon for the Windows executable (build time only)."""
    from io import BytesIO
    from PIL import Image
    images = [Image.open(BytesIO(logo_png(s))).convert('RGBA') for s in sizes]
    images[-1].save(path, format='ICO', sizes=[(s, s) for s in sizes], append_images=images[:-1])
