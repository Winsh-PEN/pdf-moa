# SPDX-License-Identifier: AGPL-3.0-only
from collections import defaultdict
from io import BytesIO
import hashlib
import pymupdf as fitz
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter
from fonts import checked_font_bytes, builtin_font_bytes, needed_chars

MODES = ('replace', 'text', 'image', 'delete')
ROTATIONS = {(1,0):0,(0,-1):90,(-1,0):180,(0,1):270}
# Formats MuPDF places directly; anything else is converted with Pillow.
NATIVE_IMAGE_FORMATS = {'JPEG', 'PNG', 'BMP', 'GIF', 'TIFF'}


def _center(bbox):
    return (bbox[0]+bbox[2])/2, (bbox[1]+bbox[3])/2


def selected_lines(page, box):
    """The text a dragged box selects, line by line.

    A character is selected when the centre of its box lies inside the box.
    The text shown for editing, the start positions, the original font and
    the characters that get deleted all come from this one rule, so a box
    that only touches a neighbouring line does not pick that line up.
    Spaces before the first and after the last selected letter are left alone.
    """
    box = fitz.Rect(box)
    lines = []
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines',[]):
            chars = [(c, span) for span in line['spans'] for c in span['chars']
                     if fitz.Point(_center(c['bbox'])) in box]
            marks = [i for i,(c,_) in enumerate(chars) if not c['c'].isspace()]
            if marks:
                chars = chars[marks[0]:marks[-1]+1]
                lines.append(dict(chars=chars, dir=line['dir'], origin=chars[0][0]['origin'],
                                  text=''.join(c['c'] for c,_ in chars)))
    return lines


def text_lines(page, box):
    return [(line['origin'], line['dir']) for line in selected_lines(page, box)]


def page_bytes(entry):
    with PdfWriter() as writer:
        writer.add_page(entry['reader'].pages[entry['page']])
        writer.pages[0].rotate(entry.get('rotation', 0))
        stream = BytesIO()
        writer.write(stream)
    with fitz.open(stream=stream.getvalue(), filetype='pdf') as doc:
        doc[0].remove_rotation()
        return doc.tobytes(garbage=4, deflate=True)


def page_png(entry, dpi, max_pixels=40_000_000):
    """The page as PNG data at dpi, lowered for huge pages (A0 drawings) to stay under max_pixels."""
    with fitz.open(stream=page_bytes(entry), filetype='pdf') as doc:
        page = doc[0]
        inches = page.rect.width / 72 * page.rect.height / 72
        dpi = min(dpi, int((max_pixels / inches) ** 0.5))
        return page.get_pixmap(dpi=dpi, alpha=False).tobytes('png')


def selected_text(data, rect):
    with fitz.open(stream=data, filetype='pdf') as doc:
        return '\n'.join(line['text'] for line in selected_lines(doc[0], rect))


def selected_fonts(data, rect):
    with fitz.open(stream=data,filetype='pdf') as doc:
        spans=[span for line in selected_lines(doc[0], rect) for c,span in line['chars'] if not c['c'].isspace()]
        return sorted({s['font'] for s in spans}), (spans[0]['size'] if spans else 12)


def _letters(page):
    """Non-space characters on the page as char -> list of box centres."""
    found = defaultdict(list)
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines',[]):
            for span in line['spans']:
                for c in span['chars']:
                    if not c['c'].isspace():
                        found[c['c']].append(_center(c['bbox']))
    return found


def delete_selection(page, lines):
    """Remove exactly the selected characters from the page content.

    MuPDF removes a glyph when a redaction area touches the glyph box shrunk
    by 10% on each side, so a tiny area at each selected glyph's centre hits
    that glyph and never its neighbours. The result is checked afterwards.
    """
    chosen = [c for line in lines for c,_ in line['chars']]
    before = _letters(page)
    for c in chosen:
        x, y = _center(c['bbox'])
        page.add_redact_annot(fitz.Rect(x-0.05, y-0.05, x+0.05, y+0.05), fill=False, cross_out=False)
    page.apply_redactions(images=0, graphics=0, text=0)
    after = _letters(page)
    removed = [c for c in chosen if not c['c'].isspace()]

    def remains(c):
        cx, cy = _center(c['bbox'])
        return any(abs(x-cx) < 0.5 and abs(y-cy) < 0.5 for x, y in after.get(c['c'], ()))

    # Every selected letter gone and nothing else: the count drops by exactly that many.
    if any(map(remains, removed)) or sum(map(len, after.values())) != sum(map(len, before.values())) - len(removed):
        raise ValueError('선택한 글자만 정확히 지울 수 없는 문서입니다. 영역을 조금 다르게 선택해 보세요.')


def embedded_font(font_face, text):
    """(resource name, font data) for text: the chosen PC font or the built-in Korean font."""
    if font_face is None:
        data, prefix = builtin_font_bytes(needed_chars(text)), 'MoaKorea'
    else:
        data, prefix = checked_font_bytes(font_face, text), 'UserFont'
    return prefix + hashlib.sha256(data).hexdigest()[:16], data


def normalized_image(data):
    """Image data MuPDF can place upright.

    Applies the EXIF rotation of phone photos and converts formats MuPDF
    cannot read (WebP and others). Other images are passed through unchanged.
    """
    if not data:
        raise ValueError('추가할 사진을 선택하세요.')
    try:
        image = Image.open(BytesIO(data))
        image.load()
    except Exception:
        raise ValueError('지원하지 않는 사진 형식입니다. PNG 또는 JPG 파일을 사용하세요.')
    with image:
        orientation = image.getexif().get(0x0112, 1)
        if image.format in NATIVE_IMAGE_FORMATS and orientation == 1:
            return data
        upright = ImageOps.exif_transpose(image)
        out = BytesIO()
        if image.format == 'JPEG' and upright.mode in ('RGB', 'L', 'CMYK'):
            upright.save(out, 'JPEG', quality=95)
        else:
            alpha = upright.mode in ('RGBA', 'LA', 'PA') or 'transparency' in upright.info
            upright.convert('RGBA' if alpha else 'RGB').save(out, 'PNG')
        return out.getvalue()


def fitted_rect(box, width, height):
    """The largest rectangle with the picture's proportions, centred in box.

    Computed here because PyMuPDF 1.26.7's keep_proportion stretches square
    pictures to fill the box (non-square ones are kept correctly).
    """
    scale = min(box.width / width, box.height / height)
    w, h = width * scale, height * scale
    x, y = box.x0 + (box.width - w) / 2, box.y0 + (box.height - h) / 2
    return fitz.Rect(x, y, x + w, y + h)


def edit_page(data, rect, mode, text='', size=12, color=(0,0,0), image=None, font_face=None):
    with fitz.open(stream=data, filetype='pdf') as doc:
        page = doc[0]
        box = fitz.Rect(rect) & page.rect
        if box.is_empty or box.width < 2 or box.height < 2:
            raise ValueError('페이지 안에 조금 더 큰 영역을 선택하세요.')
        if mode not in MODES:
            raise ValueError('지원하지 않는 편집 방식입니다.')
        if mode in ('replace', 'delete'):
            if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in page.annots() or []):
                raise ValueError('기존 삭제 표시가 있는 페이지입니다. 원본에서 삭제 표시를 처리한 뒤 다시 여세요.')
            lines = selected_lines(page, box)
            if not lines:
                raise ValueError('선택 영역에 글자가 없습니다. 스캔 이미지 속 글자는 바꾸거나 지울 수 없습니다.')
        if mode in ('replace', 'text'):
            if not 4 <= size <= 144 or not text.strip():
                raise ValueError('새 글자와 4~144pt 크기를 입력하세요.')
            # Measure with the same font that is embedded, so the width checks hold.
            fontname, fontbuffer = embedded_font(font_face, text)
            font = fitz.Font(fontbuffer=fontbuffer)
        if mode == 'replace':
            values = text.splitlines()
            if len(values) > len(lines):
                raise ValueError('원래 줄 수보다 많습니다. 줄 수를 줄이거나 글자 추가 기능을 사용하세요.')
            placements = []
            for value, line in zip(values, lines):
                dx, dy = line['dir']
                key = (round(dx), round(dy))
                if key not in ROTATIONS or abs(dx-key[0])+abs(dy-key[1]) > 0.01:
                    raise ValueError('비스듬한 글자는 위치를 정확히 유지할 수 없어 교체하지 않습니다.')
                x, y = line['origin']
                available = {0:box.x1-x, 90:y-box.y0, 180:x-box.x0, 270:box.y1-y}[ROTATIONS[key]]
                if font.text_length(value, fontsize=size) > available+0.5:
                    raise ValueError('원래 시작 위치에서 글자가 영역을 벗어납니다. 영역을 넓히거나 글자 크기를 줄여주세요.')
                placements.append((line['origin'], value, ROTATIONS[key]))
            delete_selection(page, lines)
            page.insert_font(fontname=fontname, fontbuffer=fontbuffer)
            for origin, value, rotation in placements:
                if value:
                    page.insert_text(origin, value, fontname=fontname, fontsize=size, color=color, rotate=rotation, overlay=True)
        elif mode == 'delete':
            delete_selection(page, lines)
        elif mode == 'text':
            page.insert_font(fontname=fontname, fontbuffer=fontbuffer)
            remaining = page.insert_textbox(box, text, fontsize=size, fontname=fontname, color=color, overlay=True)
            if remaining < 0:
                raise ValueError('글자가 영역에 들어가지 않습니다. 영역을 넓히거나 글자 크기를 줄여주세요. 변경은 적용되지 않았습니다.')
        else:
            picture = normalized_image(image)
            with Image.open(BytesIO(picture)) as opened:
                place = fitted_rect(box, *opened.size)
            page.insert_image(place, stream=picture, keep_proportion=False, overlay=True)
        return doc.tobytes(garbage=4, deflate=True, clean=True)


def updated_entry(entry, data):
    result = dict(entry)
    result['source_page'] = entry.get('source_page',entry['page'])
    result.update(reader=PdfReader(BytesIO(data)), page=0, rotation=0)
    return result
