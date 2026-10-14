# SPDX-License-Identifier: AGPL-3.0-only
from io import BytesIO
import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from fonts import checked_font_bytes
import hashlib

def text_lines(page, box):
    result=[]
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines',[]):
            chars=[c for span in line['spans'] for c in span['chars']
                   if not (fitz.Rect(c['bbox']) & box).is_empty]
            if chars and ''.join(c['c'] for c in chars).strip():
                result.append((chars[0]['origin'],line['dir']))
    return result

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

def selected_fonts(data, rect):
    with fitz.open(stream=data,filetype='pdf') as doc:
        box=fitz.Rect(rect)
        spans=[s for b in doc[0].get_text('dict')['blocks'] for line in b.get('lines',[]) for s in line['spans']
               if s['text'].strip() and not (fitz.Rect(s['bbox']) & box).is_empty]
        return sorted({s['font'] for s in spans}), (spans[0]['size'] if spans else 12)

def edit_page(data, rect, mode, text='', size=12, color=(0,0,0), image=None, font_face=None):
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
                anchors=text_lines(page,box)
                if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in page.annots() or []):
                    raise ValueError('기존 삭제 표시가 있는 페이지입니다. 원본에서 삭제 표시를 처리한 뒤 다시 여세요.')
                if not page.get_textbox(box).strip():
                    raise ValueError('선택 영역에 글자가 없습니다. 스캔 이미지 속 글자 교체는 지원하지 않습니다.')
                page.add_redact_annot(box, fill=False, cross_out=False)
                page.apply_redactions(images=0, graphics=0, text=0)
            fontname='korea'
            if font_face is not None:
                fontbuffer=checked_font_bytes(font_face,text)
                fontname='UserFont'+hashlib.sha256(fontbuffer).hexdigest()[:16]
                page.insert_font(fontname=fontname,fontbuffer=fontbuffer)
            if mode == 'replace':
                font=fitz.Font(fontbuffer=fontbuffer) if font_face is not None else fitz.Font('korea')
                lines=text.splitlines()
                if len(lines)>len(anchors):
                    raise ValueError('원래 줄 수보다 많습니다. 줄 수를 줄이거나 글자 추가 기능을 사용하세요.')
                for value,(origin,direction) in zip(lines,anchors):
                    dx,dy=direction
                    rotations={(1,0):0,(0,-1):90,(-1,0):180,(0,1):270}
                    key=(round(dx),round(dy))
                    if key not in rotations or abs(dx-key[0])+abs(dy-key[1])>0.01:
                        raise ValueError('비스듬한 글자는 위치를 정확히 유지할 수 없어 교체하지 않습니다.')
                    x,y=origin
                    available={0:box.x1-x,90:y-box.y0,180:x-box.x0,270:box.y1-y}[rotations[key]]
                    if font.text_length(value,fontsize=size)>available+0.5:
                        raise ValueError('원래 시작 위치에서 글자가 영역을 벗어납니다. 영역을 넓히거나 글자 크기를 줄여주세요.')
                    page.insert_text(origin,value,fontname=fontname,fontsize=size,color=color,rotate=rotations[key],overlay=True)
            else:
                remaining = page.insert_textbox(box, text, fontsize=size,
                                                fontname=fontname, color=color, overlay=True)
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
