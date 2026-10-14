# SPDX-License-Identifier: AGPL-3.0-only
from io import BytesIO
from pathlib import Path
import os
import tempfile
from pypdf import PdfReader, PdfWriter


def load_pdf(path, password=None):
    reader = PdfReader(BytesIO(Path(path).read_bytes()))
    if reader.is_encrypted and not reader.decrypt(password or ''):
        raise ValueError('PASSWORD_REQUIRED')
    return reader


def parse_pages(text, total):
    result = []
    for part in text.split(','):
        part = part.strip()
        if not part:
            raise ValueError('페이지 번호를 입력하세요. 예: 1-3, 5, 8')
        ends = part.split('-')
        if len(ends) == 1:
            values = [int(ends[0])]
        elif len(ends) == 2:
            start, end = map(int, ends)
            if start > end:
                raise ValueError('범위는 작은 번호부터 입력하세요.')
            values = range(start, end + 1)
        else:
            raise ValueError('페이지 범위를 확인하세요.')
        for value in values:
            if not 1 <= value <= total:
                raise ValueError(f'페이지 번호는 1부터 {total}까지입니다.')
            if value - 1 not in result:
                result.append(value - 1)
    return result


def save_pdf(entries, destination):
    if not entries:
        raise ValueError('저장할 페이지가 없습니다.')
    dest = Path(destination).resolve()
    if any(dest == Path(e['path']).resolve() for e in entries):
        raise ValueError('원본 보호를 위해 다른 파일 이름으로 저장하세요.')
    writer = PdfWriter()
    for entry in entries:
        writer.append(entry['reader'], pages=[entry['page']], import_outline=False)
        if entry.get('rotation'):
            writer.pages[-1].rotate(entry['rotation'])
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
