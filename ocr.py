# SPDX-License-Identifier: AGPL-3.0-only
"""Local region OCR using MuPDF's bundled Tesseract and pinned language data."""
from collections import Counter
from io import BytesIO
from pathlib import Path
import sys
import pymupdf as fitz
from PIL import Image, ImageOps


def data_directory():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    folder = root / 'tessdata'
    if not all((folder / (lang + '.traineddata')).is_file() for lang in ('kor', 'eng')):
        raise ValueError('한글·영문 OCR 데이터가 없습니다. 배포 ZIP을 다시 압축 해제해 주세요. 소스 실행은 tessdata 폴더를 확인하세요.')
    return str(folder)


def background_color(image):
    """Dominant border colour; confidence measures similarity of the full border."""
    image = image.convert('RGB')
    image.thumbnail((400, 400))
    w, h = image.size
    edge = max(1, min(w, h) // 20)
    pixels = [image.getpixel((x, y)) for y in range(h) for x in range(w)
              if x < edge or y < edge or x >= w-edge or y >= h-edge]
    buckets = Counter(tuple(v // 16 for v in p) for p in pixels)
    dominant = buckets.most_common(1)[0][0]
    cluster = [p for p in pixels if tuple(v // 16 for v in p) == dominant]
    rgb = tuple(round(sum(p[i] for p in cluster) / len(cluster)) for i in range(3))
    confidence = sum(max(abs(p[i]-rgb[i]) for i in range(3)) <= 24 for p in pixels) / len(pixels)
    return tuple(v / 255 for v in rgb), confidence


def recognize(data, rect):
    with fitz.open(stream=data, filetype='pdf') as doc:
        page = doc[0]
        box = fitz.Rect(rect) & page.rect
        if box.is_empty or min(box.width, box.height) < 3:
            raise ValueError('읽을 글자 주변을 조금 넓게 선택하세요.')
        dpi = min(300, int(72 * (12_000_000 / (box.width * box.height)) ** .5))
        if dpi < 72:
            raise ValueError('선택 영역이 너무 큽니다. 한두 줄씩 선택하세요.')
        scale = dpi / 72
        pix = page.get_pixmap(dpi=dpi, clip=box, colorspace=fitz.csRGB, alpha=False)
    image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    background, confidence = background_color(image)
    dark = sum(background) / 3 < .5
    gray = ImageOps.grayscale(image)
    if dark:
        gray = ImageOps.invert(gray)
    gray = ImageOps.autocontrast(gray)
    # Margin helps Tesseract recognize tightly selected single lines.
    margin = 24
    prepared = ImageOps.expand(gray, border=margin, fill=255).convert('RGB')
    stream = BytesIO()
    prepared.save(stream, format='PNG')
    ocr_pix = fitz.Pixmap(stream.getvalue())
    ocr_pix.set_dpi(dpi, dpi)
    recognized = ocr_pix.pdfocr_tobytes(language='kor+eng', tessdata=data_directory())
    lines = []
    with fitz.open(stream=recognized, filetype='pdf') as doc:
        for block in doc[0].get_text('dict', sort=True)['blocks']:
            for line in block.get('lines', []):
                text = ''.join(s['text'] for s in line['spans']).strip()
                if not text:
                    continue
                r = fitz.Rect(line['bbox']) + ((pix.x-margin)/scale, (pix.y-margin)/scale,
                                              (pix.x-margin)/scale, (pix.y-margin)/scale)
                r &= box
                if r.is_empty:
                    continue
                lines.append(dict(text=text, origin=(r.x0, r.y1-r.height*.08), height=r.height))
    if not lines:
        raise ValueError('글자를 인식하지 못했습니다. 가로로 된 인쇄 글자를 여백과 함께 선택하세요.')
    return dict(text='\n'.join(line['text'] for line in lines), lines=lines,
                background=background, confidence=confidence, color=(1, 1, 1) if dark else (0, 0, 0),
                size=max(4, min(144, lines[0]['height'] / .85)))


def recognize_worker(connection, data, rect):
    """Own process: MuPDF is not thread safe, and OCR can be cancelled safely."""
    try:
        connection.send(('ok', recognize(data, rect)))
    except Exception as error:
        connection.send(('error', str(error)))
    finally:
        connection.close()
