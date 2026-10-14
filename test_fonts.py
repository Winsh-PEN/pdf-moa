# SPDX-License-Identifier: AGPL-3.0-only
import unittest
import tempfile
from pathlib import Path
from io import BytesIO
import pymupdf as fitz
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, TTCollection
from fonts import inspect_file, match_font, checked_font_bytes, embedding_policy
from editing import edit_page, selected_fonts

def make_font(path, flags=0, style='Regular'):
    fb=FontBuilder(1000,isTTF=True)
    order=['.notdef','space','A','B']
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({32:'space',65:'A',66:'B'})
    glyphs={}
    for name in order:
        pen=TTGlyphPen(None)
        if name!='space':
            pen.moveTo((50,0));pen.lineTo((300,700));pen.lineTo((550,0));pen.closePath()
        glyphs[name]=pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({g:(600,0) for g in order})
    fb.setupHorizontalHeader(ascent=800,descent=-200)
    fb.setupNameTable({'familyName':'Moa Test','styleName':style,'uniqueFontIdentifier':'MoaTest'+style,
                       'fullName':'Moa Test '+style,'psName':'MoaTest-'+style})
    fb.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200,fsType=flags)
    fb.setupPost();fb.save(path)

class FontTests(unittest.TestCase):
    def test_policy(self):
        for flags in [None,2,4,0x200,6,0x10]: self.assertFalse(embedding_policy(flags)[0])
        for flags in [0,8,0x100,0x108]: self.assertTrue(embedding_policy(flags)[0])

    def test_matching_coverage_and_file_recheck(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            p=Path(folder)/'font.ttf';make_font(p)
            face=inspect_file(p)[0]
            self.assertEqual(match_font(['ABCDEF+MoaTest-Regular'],[face]),face)
            self.assertIsNone(match_font(['MoaTest-Bold'],[face]))
            self.assertIsNone(match_font(['MoaTest-Regular','Other'],[face]))
            checked_font_bytes(face,'AB')
            with self.assertRaises(ValueError): checked_font_bytes(face,'한글')
            make_font(p,flags=2)
            with self.assertRaises(ValueError): checked_font_bytes(face,'AB')

    def test_collection_full_embedding_and_edit(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            p=Path(folder)/'font.ttf';make_font(p,flags=0x100)
            coll=TTCollection();coll.fonts=[TTFont(p)];cp=Path(folder)/'font.ttc';coll.save(cp)
            for f in coll.fonts:f.close()
            face=inspect_file(cp)[0]
            raw=checked_font_bytes(face,'A')
            with TTFont(BytesIO(raw)) as font:self.assertIn('B',font.getGlyphOrder())
            with fitz.open() as doc:
                page=doc.new_page(width=300,height=300)
                page.insert_text((30,50),'OLD')
                original=doc.tobytes()
            changed=edit_page(original,(20,25,250,80),'replace',text='AB',font_face=face)
            with fitz.open(stream=changed,filetype='pdf') as doc:
                self.assertIn('AB',doc[0].get_text())
                self.assertNotIn('OLD',doc[0].get_text())
                embedded=[doc.extract_font(x[0])[3] for x in doc[0].get_fonts() if x[4].startswith('UserFont')]
                self.assertTrue(embedded)
                with TTFont(BytesIO(embedded[0])) as f:self.assertIn('B',f.getGlyphOrder())
            names,size=selected_fonts(changed,(20,25,250,80))
            self.assertEqual(match_font(names,[face]),face)

if __name__=='__main__':unittest.main()
