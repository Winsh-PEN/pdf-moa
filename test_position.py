# SPDX-License-Identifier: AGPL-3.0-only
import unittest
import pymupdf as fitz
from editing import edit_page

class PositionTest(unittest.TestCase):
    def test_loose_selection_preserves_baseline(self):
        with fitz.open() as doc:
            p=doc.new_page(width=400,height=400)
            p.insert_text((100,150),'ORIGINAL',fontsize=12)
            p.insert_text((100,180),'SECOND',fontsize=12)
            data=doc.tobytes()
        out=edit_page(data,(60,110,350,210),'replace',text='NEW\nLINE',size=12)
        with fitz.open(stream=out,filetype='pdf') as doc:
            spans=[s for b in doc[0].get_text('dict')['blocks'] for l in b.get('lines',[]) for s in l['spans']]
            self.assertEqual([tuple(s['origin']) for s in spans],[(100,150),(100,180)])
            self.assertNotIn('ORIGINAL',doc[0].get_text())

    def test_vertical_baseline(self):
        with fitz.open() as doc:
            p=doc.new_page(width=400,height=400)
            p.insert_text((150,250),'OLD',fontsize=12,rotate=90)
            data=doc.tobytes()
        out=edit_page(data,(110,100,180,280),'replace',text='NEW',size=12)
        with fitz.open(stream=out,filetype='pdf') as doc:
            line=doc[0].get_text('dict')['blocks'][0]['lines'][0]
            self.assertEqual(tuple(line['spans'][0]['origin']),(150,250))
            self.assertEqual(tuple(line['dir']),(0,-1))

if __name__=='__main__':unittest.main()
