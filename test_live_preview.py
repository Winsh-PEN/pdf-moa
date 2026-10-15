# SPDX-License-Identifier: AGPL-3.0-only
import gc
import tkinter as tk
import unittest
import pymupdf as fitz
from editor import TextDialog

class LivePreviewTest(unittest.TestCase):
    def test_typing_updates_preview_and_cancel_keeps_source(self):
        with fitz.open() as doc:
            p=doc.new_page(width=400,height=400)
            p.insert_text((100,150),'ORIGINAL')
            source=doc.tobytes()
        root=tk.Tk();root.withdraw()
        errors=[]
        def typed():
            try:
                d=next(c for c in root.winfo_children() if isinstance(c,TextDialog))
                d.text.delete('1.0','end');d.text.insert('1.0','CHANGED')
                root.after(700,lambda:check(d))
            except Exception as error:
                errors.append(error);root.destroy()
        def check(d):
            try:
                self.assertIsNotNone(d.preview_result)
                self.assertTrue(d.live_canvas.find_all())
                with fitz.open(stream=d.preview_result,filetype='pdf') as doc:
                    self.assertIn('CHANGED',doc[0].get_text())
                    self.assertNotIn('ORIGINAL',doc[0].get_text())
                self.assertEqual(d.preview_source,source)
                d.size_var.set('bad')
                root.after(500,lambda:invalid(d))
            except Exception as error:
                errors.append(error);d.cancel()
        def invalid(d):
            try:self.assertIsNone(d.preview_result)
            except Exception as error:errors.append(error)
            d.cancel()
        try:
            root.after(500,typed)
            dialog=TextDialog(root,'ORIGINAL',[],11,source,(60,110,350,190),'replace')
            self.assertIsNone(dialog.result)
            if errors:raise errors[0]
        finally:
            if root.winfo_exists():root.destroy()
            gc.collect()

if __name__=='__main__':unittest.main()
