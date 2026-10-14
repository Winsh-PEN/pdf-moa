# SPDX-License-Identifier: AGPL-3.0-only
from io import BytesIO
import pymupdf as fitz
from pypdf import PdfReader, PdfWriter

def page_bytes(entry):
    with PdfWriter() as writer:
        writer.add_page(entry['reader'].pages[entry['page']])
        writer.pages[0].rotate(entry.get('rotation', 0))
        stream = BytesIO()
        writer.write(stream)
    with fitz.open(stream=stream.getvalue(), filetype='pdf') as doc:
        doc[0].remove_rotation()
        return doc.tobytes(garbage=4, deflate=True)

def selected_text(data, rect):
    with fitz.open(stream=data, filetype='pdf') as doc:
        return doc[0].get_textbox(fitz.Rect(rect))

def edit_page(data, rect, mode, text='', size=12, color=(0,0,0), image=None):
    with fitz.open(stream=data, filetype='pdf') as doc:
        page = doc[0]
        box = fitz.Rect(rect) & page.rect
        if box.is_empty or box.width < 2 or box.height < 2:
            raise ValueError('페이지 안에 조금 더 큰 영역을 선택하세요.')
        if mode not in ('replace', 'text', 'image'):
            raise ValueError('지원하지 않는 편집 방식입니다.')
        if mode in ('replace','text'):
            if not 4 <= size <= 144 or not text.strip():
                raise ValueError('새 글자와 4~144pt 크기를 입력하세요.')
            if mode == 'replace':
                if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in page.annots() or []):
                    raise ValueError('기존 삭제 표시가 있는 페이지입니다. 원본에서 삭제 표시를 처리한 뒤 다시 여세요.')
                if not page.get_textbox(box).strip():
                    raise ValueError('선택 영역에 글자가 없습니다. 스캔 이미지 속 글자 교체는 지원하지 않습니다.')
                page.add_redact_annot(box, fill=False, cross_out=False)
                page.apply_redactions(images=0, graphics=0, text=0)
            remaining = page.insert_textbox(box, text, fontsize=size,
                                            fontname='korea', color=color, overlay=True)
            if remaining < 0:
                raise ValueError('글자가 영역에 들어가지 않습니다. 영역을 넓히거나 글자 크기를 줄여주세요. 변경은 적용되지 않았습니다.')
        else:
            if not image:
                raise ValueError('추가할 사진을 선택하세요.')
            page.insert_image(box, stream=image, keep_proportion=True, overlay=True)
        return doc.tobytes(garbage=4, deflate=True, clean=True)

def updated_entry(entry, data):
    result = dict(entry)
    result['source_page'] = entry.get('source_page',entry['page'])
    result.update(reader=PdfReader(BytesIO(data)), page=0, rotation=0)
    return result
