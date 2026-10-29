# SPDX-License-Identifier: AGPL-3.0-only
"""Document tools. All transforms return new bytes and never modify inputs."""
from io import BytesIO
from pathlib import Path
import json
import os
import tempfile
import zipfile
import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader, PdfWriter
from editing import embedded_font, page_bytes
from ocr import data_directory


def transform(data, mode, options, number=1, total=1):
    with fitz.open(stream=data, filetype='pdf') as doc:
        page=doc[0]
        if mode=='ocr':
            # Keep existing searchable pages intact instead of duplicating text.
            if page.get_text().strip():return data
            dpi=min(200,int(72*(16_000_000/(page.rect.width*page.rect.height))**.5))
            if dpi<72:raise ValueError('OCR 대상 페이지가 너무 큽니다. 페이지를 먼저 잘라 주세요.')
            tp=page.get_textpage_ocr(language='kor+eng',dpi=dpi,full=True,tessdata=data_directory())
            lines=[line for b in page.get_text('dict',textpage=tp)['blocks'] for line in b.get('lines',[])]
            text=''.join(s['text'] for line in lines for s in line['spans'])
            if not text.strip():return data
            name,buffer=embedded_font(None,text)
            page.insert_font(fontname=name,fontbuffer=buffer)
            for line in lines:
                for span in line['spans']:
                    page.insert_text(span['origin'],span['text'],fontsize=span['size'],fontname=name,render_mode=3)
        elif mode=='compress':
            quality=int(options['quality']);limit=int(options['pixels'])
            if not 20<=quality<=95 or not 600<=limit<=5000:raise ValueError('압축 품질과 크기를 확인하세요.')
            for xref in {im[0] for im in page.get_images(full=True) if not im[1]}:
                original=doc.extract_image(xref)
                if not original:continue
                with Image.open(BytesIO(original['image'])) as im:
                    if im.mode not in ('RGB','L'):continue
                    im.thumbnail((limit,limit),Image.Resampling.LANCZOS)
                    out=BytesIO();im.save(out,'JPEG',quality=quality,optimize=True)
                if len(out.getvalue())<len(original['image']):page.replace_image(xref,stream=out.getvalue())
        elif mode=='crop':
            left,top,right,bottom=[float(options[k])*72/25.4 for k in ('left','top','right','bottom')]
            if min(left,top,right,bottom)<0:raise ValueError('여백은 0 이상이어야 합니다.')
            box=page.rect+ (left,top,-right,-bottom)
            if min(box.width,box.height)<20:raise ValueError('남는 페이지가 너무 작습니다.')
            angle=float(options['angle'])
            if not -15<=angle<=15:raise ValueError('기울기는 -15~15도 범위로 입력하세요.')
            # New page normalizes cropped coordinates without rasterizing text.
            with fitz.open() as result:
                target=result.new_page(width=box.width,height=box.height)
                target.show_pdf_page(target.rect,doc,0,clip=box,rotate=angle)
                return result.tobytes(garbage=4,deflate=True)
        elif mode=='mark':
            text=options['text'].replace('{n}',str(number)).replace('{total}',str(total))
            size=float(options['size']);opacity=float(options['opacity'])
            if not text.strip() or not 4<=size<=144 or not 0.05<=opacity<=1:raise ValueError('글자·크기(4~144)·불투명도(0.05~1)를 확인하세요.')
            name,buffer=embedded_font(None,text);font=fitz.Font(fontbuffer=buffer)
            width=font.text_length(text,fontsize=size)
            if width>page.rect.width-24:raise ValueError('문구가 페이지 너비를 넘습니다. 크기를 줄이세요.')
            y=page.rect.height-18 if options['position']=='bottom' else page.rect.height/2
            if y-size*font.ascender<0 or y-size*font.descender>page.rect.height:raise ValueError('페이지에 글자가 들어가지 않습니다.')
            page.insert_font(fontname=name,fontbuffer=buffer)
            page.insert_text(((page.rect.width-width)/2,y),text,fontname=name,fontsize=size,color=(.3,.3,.3),fill_opacity=opacity)
        else:raise ValueError('지원하지 않는 도구입니다.')
        result=doc.tobytes(garbage=4,deflate=True)
        return data if mode=='compress' and len(result)>=len(data) else result


def batch_worker(pipe, pages, mode, options):
    try:
        results=[]
        for i,data in enumerate(pages):
            results.append(transform(data,mode,options,i+1,len(pages)))
            pipe.send(('progress',i+1))
        pipe.send(('ok',results))
    except Exception as error:pipe.send(('error',str(error)))
    finally:pipe.close()


def search_worker(pipe,pages,query):
    try:
        hits=[]
        for i,data in enumerate(pages):
            with fitz.open(stream=data,filetype='pdf') as doc:
                text=doc[0].get_text()
                for line in text.splitlines():
                    if query.casefold() in line.casefold():hits.append((i,line[:200]))
            pipe.send(('progress',i+1))
        pipe.send(('ok',hits))
    except Exception as error:pipe.send(('error',str(error)))
    finally:pipe.close()


def save_project(entries,destination,bookmarks=False):
    dest=Path(destination).resolve()
    if any(e.get('path') and os.path.normcase(str(Path(e['path']).resolve()))==os.path.normcase(str(dest)) for e in entries):
        raise ValueError('원본 파일과 다른 이름으로 저장하세요.')
    if len(entries)>10000:raise ValueError('작업 파일은 최대 10,000페이지까지 지원합니다.')
    total_bytes=0
    manifest={'format':'pdf-moa-project','version':1,'bookmarks':bool(bookmarks),'pages':[]}
    fd,temp=tempfile.mkstemp(dir=dest.parent,suffix='.tmp');os.close(fd)
    try:
        with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for i,e in enumerate(entries):
                name=f'pages/{i}.pdf';data=page_bytes(e);total_bytes+=len(data)
                if total_bytes>990_000_000:raise ValueError('작업 파일은 압축 해제 기준 1GB 이하만 지원합니다. 문서를 나눠 보관하세요.')
                z.writestr(name,data)
                manifest['pages'].append({'file':name,'path':e.get('path'),'source_page':e.get('source_page',e['page'])})
            z.writestr('project.json',json.dumps(manifest,ensure_ascii=False))
        os.replace(temp,dest)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def load_project(path):
    with zipfile.ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist())>1_000_000_000:raise ValueError('작업 파일은 압축 해제 기준 1GB 이하만 지원합니다.')
        m=json.loads(z.read('project.json'))
        if m.get('format')!='pdf-moa-project' or m.get('version')!=1:raise ValueError('지원하지 않는 작업 파일입니다.')
        pages=m.get('pages',[])
        if not isinstance(pages,list) or len(pages)>10000:raise ValueError('작업 페이지 정보가 잘못되었습니다.')
        entries=[]
        for item in pages:
            reader=PdfReader(BytesIO(z.read(item['file'])))
            if len(reader.pages)!=1:raise ValueError('작업 페이지가 손상되었습니다.')
            source=item.get('path')
            if source is not None and not isinstance(source,str):raise ValueError('원본 경로가 잘못되었습니다.')
            entries.append(dict(reader=reader,page=0,rotation=0,path=source,source_page=int(item.get('source_page',0))))
        return entries,bool(m.get('bookmarks',False))


def combined_size(entries, bookmarks=False):
    """Size of the same merged document the export path writes (including shared objects)."""
    from core import file_bookmarks
    with PdfWriter() as writer:
        for entry in entries:
            writer.append(entry['reader'],pages=[entry['page']],import_outline=False)
            if entry.get('rotation'):writer.pages[-1].rotate(entry['rotation'])
        if bookmarks:
            for index,title in file_bookmarks(entries):writer.add_outline_item(title,index)
            writer.page_mode='/UseOutlines'
        out=BytesIO();writer.write(out);return len(out.getvalue())
