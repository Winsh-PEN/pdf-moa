# SPDX-License-Identifier: AGPL-3.0-only
from datetime import datetime
from io import BytesIO
from pathlib import Path
import os
import re
import tempfile
from pypdf import PdfReader, PdfWriter

RANGE_EXAMPLE = '예: 1-3, 5, 8'


def load_pdf(path, password=None):
    reader = PdfReader(BytesIO(Path(path).read_bytes()))
    if reader.is_encrypted and not reader.decrypt(password or ''):
        raise ValueError('PASSWORD_REQUIRED')
    return reader


def blank_reader(width=595.28, height=841.89):
    """A one-page PDF with an empty page of the given size (A4 by default)."""
    with PdfWriter() as writer:
        writer.add_blank_page(width=width, height=height)
        stream = BytesIO()
        writer.write(stream)
    return PdfReader(BytesIO(stream.getvalue()))


def natural_key(path):
    """Sort key so that 'scan2.pdf' comes before 'scan10.pdf'."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', Path(path).name)]


def _number(text):
    try:
        return int(text)
    except ValueError:
        raise ValueError('숫자와 - , 만 입력하세요. ' + RANGE_EXAMPLE) from None


def parse_groups(text, total):
    """Comma separated numbers or ranges, each as a list of 0-based indices.

    '1-3, 5' -> [[0, 1, 2], [4]]. A tilde also works as the range sign (1~3).
    """
    if total < 1:
        raise ValueError('먼저 PDF를 추가하세요.')
    parts = [part.strip() for part in text.replace('~', '-').split(',')]
    parts = [part for part in parts if part]
    if not parts:
        raise ValueError('페이지 번호를 입력하세요. ' + RANGE_EXAMPLE)
    groups = []
    for part in parts:
        ends = [end.strip() for end in part.split('-')]
        if len(ends) == 1:
            values = [_number(ends[0])]
        elif len(ends) == 2:
            start, end = _number(ends[0]), _number(ends[1])
            if start > end:
                raise ValueError(f'범위는 작은 번호부터 입력하세요. 예: {end}-{start}')
            values = range(start, end + 1)
        else:
            raise ValueError('페이지 범위를 확인하세요. ' + RANGE_EXAMPLE)
        for value in values:
            if not 1 <= value <= total:
                raise ValueError(f'페이지 번호는 1부터 {total}까지입니다.')
        groups.append([value - 1 for value in values])
    return groups


def parse_pages(text, total):
    result, seen = [], set()
    for group in parse_groups(text, total):
        for index in group:
            if index not in seen:
                seen.add(index)
                result.append(index)
    return result


def split_groups(indices, mode, value=None, total=None):
    """Pages per output file for 'each', 'every' (value pages) or 'ranges' (value text)."""
    if mode == 'each':
        return [[i] for i in indices]
    if mode == 'every':
        if not value or value < 1:
            raise ValueError('한 파일에 넣을 쪽수를 1 이상으로 입력하세요.')
        return [indices[i:i + value] for i in range(0, len(indices), value)]
    if mode == 'ranges':
        return parse_groups(value or '', total)
    raise ValueError('지원하지 않는 분리 방식입니다.')


def safe_name(text, limit=50):
    """A file name part without characters Windows forbids."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', text).strip().rstrip('. ')
    return name[:limit].rstrip('. ') or '문서'


def group_name(number, entries):
    """Output file name for one split group: 001_계약서_p3.pdf, 002_계약서_p4-6.pdf ..."""
    sources = [Path(e['path']).stem if e.get('path') else '빈페이지' for e in entries]
    pages = [e.get('source_page', e['page']) + 1 for e in entries]
    if len(set(sources)) == 1:
        label = f'p{pages[0]}' if len(pages) == 1 else f'p{pages[0]}-{pages[-1]}'
        return f'{number:03d}_{safe_name(sources[0])}_{label}.pdf'
    return f'{number:03d}_{safe_name(sources[0])}_외_{len(entries)}쪽.pdf'


def new_folder(parent, prefix='PDF_분리'):
    """A new folder named prefix_YYYYMMDD_HHMMSS (with _2, _3 ... when taken)."""
    base = Path(parent) / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}"
    folder, number = base, 1
    while True:
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            number += 1
            folder = base.with_name(f'{base.name}_{number}')


def file_bookmarks(entries):
    """(page index, title) at the first page of each run of pages from one file.

    Blank pages do not start or break a run.
    """
    marks, previous = [], None
    for index, entry in enumerate(entries):
        path = entry.get('path')
        if path and path != previous:
            marks.append((index, Path(path).stem))
        previous = path or previous
    return marks


def _same_file(a, b):
    return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))


def save_pdf(entries, destination, protected=(), bookmarks=False):
    """Write entries as one PDF. Refuses to overwrite a source file.

    protected: further paths that must not be overwritten (every file in the
    page list and in the undo history, not just the pages being saved).
    bookmarks: add a bookmark with the file name where each source file starts.
    """
    if not entries:
        raise ValueError('저장할 페이지가 없습니다.')
    dest = Path(destination).resolve()
    sources = {e['path'] for e in entries if e.get('path')} | {p for p in protected if p}
    if any(_same_file(dest, source) for source in sources):
        raise ValueError('원본 보호를 위해 다른 파일 이름으로 저장하세요.')
    writer = PdfWriter()
    for entry in entries:
        writer.append(entry['reader'], pages=[entry['page']], import_outline=False)
        if entry.get('rotation'):
            writer.pages[-1].rotate(entry['rotation'])
    if bookmarks:
        for index, title in file_bookmarks(entries):
            writer.add_outline_item(title, index)
        writer.page_mode = '/UseOutlines'  # open with the bookmark panel visible
    fd, temporary = tempfile.mkstemp(suffix='.pdf', dir=dest.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            writer.write(stream)
        PdfReader(temporary)
        os.replace(temporary, dest)
    finally:
        writer.close()
        if os.path.exists(temporary):
            os.unlink(temporary)
