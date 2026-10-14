# SPDX-License-Identifier: AGPL-3.0-only
import unittest
from io import BytesIO
from pathlib import Path
import tempfile
import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader
from core import save_pdf
from editing import edit_page, page_bytes, updated_entry

class EditingTest(unittest.TestCase):
    def setUp(self):
        with fitz.open() as doc:
            page=doc.new_page(width=400,height=500)
            page.insert_text((40,60),'OLD_SECRET',fontsize=12)
            page.insert_text((40,150),'KEEP_ME',fontsize=12)
            self.original=doc.tobytes()
        self.entry=dict(path='original.pdf',reader=PdfReader(BytesIO(self.original)),page=0,rotation=0)

    def test_replace_and_full_save_removes_original_text(self):
        changed=edit_page(self.original,(35,40,260,85),'replace',text='새 글자 NEW',size=12)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            target=Path(folder)/'edited.pdf'
            save_pdf([updated_entry(self.entry,changed)],target)
            with fitz.open(target) as doc:
                text=doc[0].get_text()
                self.assertNotIn('OLD_SECRET',text)
                self.assertIn('새 글자 NEW',text)
                self.assertIn('KEEP_ME',text)
                for x in range(1,doc.xref_length()):
                    if doc.xref_is_stream(x):
                        self.assertNotIn(b'OLD_SECRET',doc.xref_stream(x))
        self.assertIn('OLD_SECRET',self.entry['reader'].pages[0].extract_text())

    def test_add_text_and_image(self):
        changed=edit_page(self.original,(40,200,300,250),'text',text='추가 문장',size=14)
        image=BytesIO()
        Image.new('RGB',(60,30),(255,0,0)).save(image,format='PNG')
        changed=edit_page(changed,(40,300,240,400),'image',image=image.getvalue())
        with fitz.open(stream=changed,filetype='pdf') as doc:
            self.assertIn('추가 문장',doc[0].get_text())
            self.assertIn('OLD_SECRET',doc[0].get_text())
            self.assertEqual(len(doc[0].get_images()),1)
            Path('test-output').mkdir(exist_ok=True)
            doc[0].get_pixmap().save('test-output/editor-result.png')

    def test_rotation_and_atomic_failure(self):
        self.entry['rotation']=90
        normalized=page_bytes(self.entry)
        with fitz.open(stream=normalized,filetype='pdf') as doc:
            self.assertEqual(doc[0].rotation,0)
            self.assertEqual(tuple(doc[0].rect),(0,0,500,400))
        with self.assertRaises(ValueError):
            edit_page(self.original,(35,40,260,85),'replace',text='too much text '*100,size=144)
        with fitz.open(stream=self.original,filetype='pdf') as doc:
            self.assertIn('OLD_SECRET',doc[0].get_text())
        with self.assertRaises(ValueError):
            edit_page(self.original,(20,300,250,350),'replace',text='scanned')

if __name__=='__main__':
    unittest.main()
