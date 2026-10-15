# SPDX-License-Identifier: AGPL-3.0-only
import gc
from io import BytesIO
from pathlib import Path
import tkinter as tk
import unittest
from unittest.mock import patch
import pymupdf as fitz
from PIL import Image
from ocr import recognize, background_color
from editing import edit_page
from editor import TextDialog, OCRProgress

RECT = (40, 40, 370, 130)

def scan(bg=(1,1,1), words='ORIGINAL TEXT'):
    with fitz.open() as doc:
        p=doc.new_page(width=420,height=200)
        p.draw_rect(p.rect,color=bg,fill=bg)
        p.insert_text((70,90),words,fontsize=20,color=(0,0,0) if sum(bg)>1.5 else (1,1,1))
        image=p.get_pixmap(dpi=220).tobytes('png')
    with fitz.open() as doc:
        p=doc.new_page(width=420,height=200)
        p.insert_image(p.rect,stream=image)
        return doc.tobytes()

class OCRTest(unittest.TestCase):
    def test_white_black_and_colored_scan(self):
        for bg in [(1,1,1),(0,0,0),(.2,.35,.5)]:
            with self.subTest(bg=bg):
                source=scan(bg)
                info=recognize(source,RECT)
                self.assertIn('ORIGINAL',info['text'])
                self.assertGreater(info['confidence'],.95)
                for a,b in zip(bg,info['background']):self.assertAlmostEqual(a,b,delta=.02)
                self.assertAlmostEqual(info['lines'][0]['origin'][0],70,delta=2)
                self.assertAlmostEqual(info['lines'][0]['origin'][1],90,delta=3)
                result=edit_page(source,RECT,'ocr',text='NEW',size=18,color=info['color'],background=info['background'],ocr_lines=info['lines'])
                with fitz.open(stream=result,filetype='pdf') as doc:
                    self.assertIn('NEW',doc[0].get_text())
                    if bg==(0,0,0):
                        edge=doc[0].get_pixmap(matrix=fitz.Matrix(1.5,1.5),clip=fitz.Rect(37,50,43,110))
                        self.assertEqual(max(edge.samples),0)
                    # Original ink to the right of the short replacement is erased.
                    pix=doc[0].get_pixmap(clip=fitz.Rect(180,65,240,95),colorspace=fitz.csRGB)
                    im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                    for lo,hi in im.getextrema():self.assertLessEqual(hi-lo,1)
                    # Unselected pixels survive unchanged.
                    after=doc[0].get_pixmap(clip=fitz.Rect(0,150,420,200)).samples
                with fitz.open(stream=source,filetype='pdf') as doc:
                    self.assertEqual(after,doc[0].get_pixmap(clip=fitz.Rect(0,150,420,200)).samples)

    def test_korean_and_hidden_text(self):
        with fitz.open() as doc:
            p=doc.new_page(width=420,height=200)
            p.insert_text((65,90),'한글 문서 수정',fontname='korea',fontsize=24)
            image=p.get_pixmap(dpi=300).tobytes('png')
        with fitz.open() as doc:
            p=doc.new_page(width=420,height=200);p.insert_image(p.rect,stream=image)
            p.insert_text((70,90),'SECRET OLD OCR',render_mode=3)
            source=doc.tobytes()
        info=recognize(source,RECT)
        self.assertIn('한글',info['text'])
        result=edit_page(source,RECT,'ocr',text='수정 완료',size=20,background=(1,1,1),ocr_lines=info['lines'])
        with fitz.open(stream=result,filetype='pdf') as doc:
            self.assertIn('수정 완료',doc[0].get_text())
            self.assertNotIn('SECRET',doc[0].get_text())

    def test_empty_and_overflow_are_atomic(self):
        with fitz.open() as doc:
            doc.new_page();blank=doc.tobytes()
        with self.assertRaisesRegex(ValueError,'인식하지'):recognize(blank,RECT)
        source=scan();info=recognize(source,RECT)
        with self.assertRaises(ValueError):
            edit_page(source,RECT,'ocr',text='W'*100,size=40,ocr_lines=info['lines'])
        with self.assertRaises(ValueError):
            edit_page(source,RECT,'ocr',text='ONE\nTWO',ocr_lines=info['lines'])
        self.assertIn('ORIGINAL',recognize(source,RECT)['text'])

    def test_mixed_background_confidence(self):
        im=Image.new('RGB',(100,100),'white')
        im.paste('black',(50,0,100,100))
        self.assertLess(background_color(im)[1],.85)

class OCRDialogTest(unittest.TestCase):
    def test_background_and_text_live_preview(self):
        root=tk.Tk();root.withdraw();errors=[]
        source=scan();info=recognize(source,RECT)
        def change():
            try:
                d=next(c for c in root.winfo_children() if isinstance(c,TextDialog))
                d.text.delete('1.0','end');d.text.insert('1.0','LIVE')
                with patch('editor.colorchooser.askcolor',return_value=((0,0,0),'#000000')):d.choose_background()
                d.color=(1,1,1);d.schedule_preview()
                root.after(600,lambda:check(d))
            except Exception as e:errors.append(e);root.destroy()
        def check(d):
            try:
                self.assertIsNotNone(d.preview_result)
                self.assertEqual(d.background,(0,0,0))
                self.assertTrue(d.live_canvas.find_all())
                with fitz.open(stream=d.preview_result,filetype='pdf') as doc:
                    self.assertIn('LIVE',doc[0].get_text())
                    self.assertEqual(doc[0].get_pixmap().pixel(45,45),(0,0,0))
                d.reset_background();self.assertEqual(d.background,(1,1,1))
                d.update_preview();self.assertIsNotNone(d.preview_result)
                self.assertEqual(d.preview_source,source)
            except Exception as e:errors.append(e)
            d.cancel()
        try:
            root.after(500,change)
            d=TextDialog(root,info['text'],[],18,source,RECT,'ocr',ocr_info=info)
            self.assertIsNone(d.result)
            if errors:raise errors[0]
        finally:root.destroy();gc.collect()

    def test_worker_and_cancel(self):
        root=tk.Tk();root.withdraw()
        try:
            progress=OCRProgress(root,scan(),RECT)
            self.assertIn('ORIGINAL',progress.result['text'])
            def cancel():
                for c in root.winfo_children():
                    if isinstance(c,OCRProgress):c.cancel()
            root.after(100,cancel)
            progress=OCRProgress(root,scan(),RECT)
            self.assertIsNone(progress.result)
            self.assertIsNone(progress.process)
        finally:root.destroy();gc.collect()

if __name__=='__main__':unittest.main()
