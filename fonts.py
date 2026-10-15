# SPDX-License-Identifier: AGPL-3.0-only
"""Local font discovery and conservative embedding checks. No font downloads."""
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import logging
import os
import re
from fontTools.ttLib import TTFont, TTCollection
from fontTools import subset

# fontTools reports dropped tables (meta, MERG, ...) while subsetting; not useful to users.
logging.getLogger('fontTools').setLevel(logging.ERROR)

BUILTIN_LABEL = '기본 한글 글꼴 (프로그램 내장)'


def embedding_policy(flags):
    if flags is None:
        return False, '포함 제한 정보 없음: 사용 불가'
    if flags & ~0x030E or (flags & 0xE) not in (0,2,4,8):
        return False, '알 수 없거나 충돌하는 제한: 사용 불가'
    if flags & 2:
        return False, 'PDF 포함 금지: 사용 불가'
    if flags & 0x200:
        return False, '비트맵만 포함 허용: 이 편집기에서 사용 불가'
    if flags & 4:
        return False, '보기·인쇄 전용: 편집 PDF에는 사용 불가'
    label = '편집 가능한 포함 허용' if flags & 8 else '설치 가능한 포함 허용'
    if flags & 0x100:
        label += ' · 전체 글꼴 포함(부분 포함 금지)'
    return True, label


def normalized(name):
    name = re.sub(r'^[A-Z]{6}\+', '', name)
    return ''.join(c for c in name.casefold() if c.isalnum())


@dataclass(frozen=True)
class FontFace:
    path: str
    index: int
    name: str
    aliases: tuple
    flags: object
    license_text: str
    variable: bool

    @property
    def policy(self):
        return (False,'가변 글꼴은 지원하지 않습니다.') if self.variable else embedding_policy(self.flags)

    @property
    def label(self):
        return self.name + ('' if self.policy[0] else ' [사용 제한]')


def open_face(path, index):
    return TTFont(path, fontNumber=index, lazy=False)


def inspect_file(path):
    path = str(Path(path).resolve())
    stat = os.stat(path)
    # Keyed by modification time and size, so a replaced file is checked again.
    return list(_inspect(path, stat.st_mtime_ns, stat.st_size))


@lru_cache(maxsize=1024)
def _inspect(path, mtime, size):
    with open(path,'rb') as stream:
        collection = stream.read(4) == b'ttcf'
    count = 1
    if collection:
        with TTCollection(path,lazy=True) as fonts:
            count = len(fonts.fonts)
    faces = []
    for index in range(count):
        with open_face(path,index) as font:
            names = font['name']
            def values(ids):
                result=[]
                for n in names.names:
                    if n.nameID in ids:
                        try:
                            s=n.toUnicode().strip()
                            if s and s not in result: result.append(s)
                        except (UnicodeError,AttributeError): pass
                return result
            aliases=values([4,6])
            # Full and PostScript names describe a face. Family names alone
            # can also identify Black/Narrow variants and must not auto-match.
            name=names.getDebugName(4) or (aliases[0] if aliases else Path(path).name)
            flags=font['OS/2'].fsType if 'OS/2' in font else None
            faces.append(FontFace(path,index,name,tuple(set(aliases)),flags,
                                  '\n'.join(values([13,14])) or '글꼴 파일에 라이선스 설명이 없습니다. 제공처 이용조건을 확인하세요.',
                                  'fvar' in font))
    return tuple(faces)


@lru_cache(maxsize=1)
def installed_fonts():
    roots=[Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts',
           Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'Microsoft/Windows/Fonts']
    paths={p for root in roots if root.exists() for p in root.iterdir() if p.suffix.lower() in ('.ttf','.otf','.ttc','.otc')}
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts') as key:
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        _,value,_=winreg.EnumValue(key,i)
                        if isinstance(value,str):
                            p=Path(os.path.expandvars(value))
                            if p.is_absolute(): paths.add(p)
            except OSError: pass
    except ImportError: pass
    result=[]
    for p in sorted(paths):
        try: result.extend(inspect_file(p))
        except Exception: continue
    return sorted(result,key=lambda f:(f.name.casefold(),f.path,f.index))


def match_font(names, faces):
    targets={normalized(n) for n in names}
    if len(targets)!=1:
        return None
    matches=[f for f in faces if targets.intersection(normalized(a) for a in f.aliases)]
    if not matches: return None
    # Duplicate installations are okay; ambiguous different faces are not.
    if len({normalized(f.name) for f in matches})>1: return None
    return next((f for f in matches if f.policy[0]),matches[0])


def needed_chars(text):
    """The distinct characters of text in a stable order (a cache key)."""
    return ''.join(sorted(set(text)))


def embed_bytes(data, index, chars, allow_subset, font_name='이 글꼴'):
    """Font data to embed for chars: only the glyphs they need when the font allows it.

    Raises ValueError when the font lacks one of the characters.
    """
    font = TTFont(BytesIO(data), fontNumber=index, lazy=True)
    try:
        cmap = font.getBestCmap() or {}
        missing = sorted({c for c in chars if not c.isspace() and ord(c) not in cmap})
        if missing:
            raise ValueError(f'{font_name}에서 지원하지 않는 글자: '+''.join(missing[:24])+'\n다른 글꼴을 선택하세요.')
        if allow_subset:
            options = subset.Options()
            options.name_IDs = ['*']
            options.name_languages = ['*']
            options.name_legacy = True
            options.notdef_outline = True
            options.layout_features = ['*']
            options.legacy_kern = True
            subsetter = subset.Subsetter(options)
            subsetter.populate(text=chars)
            subsetter.subset(font)
        buffer = BytesIO()
        font.save(buffer)
        return buffer.getvalue()
    finally:
        font.close()


@lru_cache(maxsize=32)
def _file_embed_bytes(path, index, mtime, size, chars, allow_subset):
    with open(path,'rb') as stream:
        data = stream.read()
    return embed_bytes(data, index, chars, allow_subset)


def checked_font_bytes(face, text):
    """Embeddable font data for text after checking the file's current restrictions.

    The font is reduced to the glyphs text needs, except when fsType 0x100
    forbids subsetting; then the complete face is embedded.
    """
    # Re-check the actual file on every use, including after file replacement.
    stat = os.stat(face.path)
    fresh=inspect_file(face.path)[face.index]
    allowed,message=fresh.policy
    if not allowed: raise ValueError(message+'\n다른 글꼴을 선택하세요.')
    return _file_embed_bytes(str(Path(face.path).resolve()), face.index, stat.st_mtime_ns, stat.st_size,
                             needed_chars(text), not (fresh.flags & 0x100))


@lru_cache(maxsize=32)
def builtin_font_bytes(chars):
    """The program's built-in Korean font (MuPDF's Droid Sans Fallback), subset to chars."""
    import pymupdf as fitz
    return embed_bytes(fitz.Font('korea').buffer, 0, chars, True, '기본 한글 글꼴')
