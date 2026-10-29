# SPDX-License-Identifier: AGPL-3.0-only
import gc
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
import tkinter as tk
from tkinterdnd2 import TkinterDnD
import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader
from document_tools import transform,save_project,load_project,search_worker
from editing import page_bytes
from test_ocr import scan


def entry(data,rotation=0):return dict(path='',reader=PdfReader(BytesIO(data)),page=0,rotation=rotation)
def text_pdf():
    with fitz.open() as d:
        p=d.new_page(width=400,height=300);p.insert_text((80,100),'SEARCH HELLO',fontsize=18)
        return d.tobytes()

class DocumentTest(unittest.TestCase):
    def test_search_ocr_preserves_appearance(self):
        original=scan()
        output=transform(original,'ocr',{})
        with fitz.open(stream=original,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
            self.assertIn('ORIGINAL',after[0].get_text())
            self.assertEqual(before[0].get_pixmap().samples,after[0].get_pixmap().samples)
        self.assertEqual(transform(output,'ocr',{}),output)
        class Pipe:
            def __init__(self):self.items=[]
            def send(self,item):self.items.append(item)
            def close(self):pass
        pipe=Pipe();search_worker(pipe,[text_pdf(),output],'original')
        self.assertEqual(pipe.items[-1][0],'ok');self.assertEqual(pipe.items[-1][1][0][0],1)

    def test_compression_retains_text_and_reduces_image(self):
        image=Image.effect_noise((1800,1800),80).convert('RGB');stream=BytesIO();image.save(stream,'PNG')
        with fitz.open() as d:
            p=d.new_page();p.insert_image(p.rect,stream=stream.getvalue());p.insert_text((20,30),'KEEP TEXT')
            original=d.tobytes()
        output=transform(original,'compress',dict(quality=60,pixels=800))
        self.assertLess(len(output),len(original)/2)
        with fitz.open(stream=output,filetype='pdf') as d:self.assertIn('KEEP TEXT',d[0].get_text())

    def test_crop_angle_and_invalid_input(self):
        opts=dict(left=10,top=5,right=10,bottom=5,angle=0)
        output=transform(text_pdf(),'crop',opts)
        with fitz.open(stream=output,filetype='pdf') as d:
            self.assertAlmostEqual(d[0].rect.width,400-20*72/25.4,places=3)
            self.assertIn('HELLO',d[0].get_text())
        opts['angle']=3
        with fitz.open(stream=transform(text_pdf(),'crop',opts),filetype='pdf') as d:
            lines=[l for b in d[0].get_text('dict')['blocks'] for l in b.get('lines',[])]
            self.assertNotAlmostEqual(lines[0]['dir'][1],0,places=3)
        opts['left']=500
        with self.assertRaises(ValueError):transform(text_pdf(),'crop',opts)

    def test_number_watermark(self):
        options=dict(text='검토용 {n} / {total}',size=16,opacity=.3,position='center')
        with fitz.open(stream=transform(text_pdf(),'mark',options,2,5),filetype='pdf') as d:
            self.assertIn('검토용 2 / 5',d[0].get_text());self.assertIn('HELLO',d[0].get_text())
        with self.assertRaises(ValueError):transform(text_pdf(),'mark',dict(options,size=999))

    def test_project_roundtrip_and_malformed(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path=Path(folder)/'work.moa';original=[entry(text_pdf(),90),entry(scan())]
            save_project(original,path,True);loaded,marks=load_project(path)
            self.assertTrue(marks);self.assertEqual(len(loaded),2)
            from core import save_pdf
            from document_tools import combined_size
            saved=Path(folder)/'merged.pdf';save_pdf(original,saved)
            self.assertEqual(combined_size(original),saved.stat().st_size)
            for a,b in zip(original,loaded):
                with fitz.open(stream=page_bytes(a),filetype='pdf') as da,fitz.open(stream=page_bytes(b),filetype='pdf') as db:
                    self.assertEqual(da[0].rect,db[0].rect);self.assertEqual(da[0].get_pixmap().samples,db[0].get_pixmap().samples)
            original[0]['path']=str(path)
            with self.assertRaises(ValueError):save_project(original,path)
            with zipfile.ZipFile(Path(folder)/'bad.moa','w') as z:z.writestr('project.json','{}')
            with self.assertRaises(ValueError):load_project(Path(folder)/'bad.moa')

    def test_stamp_copy(self):
        from stamps import add_stamp
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            source=Path(folder)/'stamp.png';Image.new('RGBA',(50,25),(255,0,0,100)).save(source)
            copied=add_stamp(Path(folder)/'favorites',source)
            self.assertTrue(source.exists());self.assertNotEqual(source,copied)
            with Image.open(copied) as im:self.assertEqual(im.mode,'RGBA');self.assertEqual(im.size,(50,25))

class ToolUITest(unittest.TestCase):
    def test_process_progress_preview_and_cancel(self):
        from tools_ui import Progress,ResultPreview
        from document_tools import batch_worker
        root=tk.Tk();root.withdraw()
        try:
            options=dict(text='{n} / {total}',size=12,opacity=1,position='bottom')
            result=Progress(root,batch_worker,([text_pdf(),text_pdf()],'mark',options),2).result
            self.assertEqual(len(result),2)
            with fitz.open(stream=result[1],filetype='pdf') as d:self.assertIn('2 / 2',d[0].get_text())
            errors=[]
            def cancel_preview():
                for child in root.winfo_children():
                    if isinstance(child,ResultPreview):
                        try:
                            child.move(1);self.assertEqual(child.index,1)
                            child.original.set(True);child.draw();self.assertTrue(child.canvas.find_all())
                        except Exception as error:errors.append(error)
                        child.cancel()
            root.after(100,cancel_preview)
            preview=ResultPreview(root,[text_pdf(),text_pdf()],result,'test')
            self.assertIsNone(preview.result)
            if errors:raise errors[0]
            def cancel_work():
                for child in root.winfo_children():
                    if isinstance(child,Progress):child.close()
            root.after(1,cancel_work)
            job=Progress(root,batch_worker,([scan()]*5,'ocr',{}),5)
            self.assertIsNone(job.result);self.assertIsNone(job.process)
        finally:root.destroy();gc.collect()

    def test_tabs_search_jump_apply_and_undo(self):
        from app import App
        from settings import Settings
        from tools_ui import ToolsWindow
        root=TkinterDnD.Tk();root.withdraw()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            app=App(root,Settings(Path(folder)/'settings.json'));app.entries=[entry(text_pdf()),entry(text_pdf())];app.refresh([1])
            w=ToolsWindow(app);root.update()
            try:
                w.hits=[(1,'HELLO')];w.results.insert('end','2쪽 HELLO');w.results.selection_set(0);w.jump()
                self.assertEqual(app.selected(),[1])
                before=page_bytes(app.entries[0]);after=transform(before,'mark',dict(text='{n}',size=12,opacity=1,position='bottom'))
                with patch('tools_ui.Progress') as progress,patch('tools_ui.ResultPreview') as preview,patch('tools_ui.messagebox.showinfo'):
                    progress.return_value.result=[after,after];preview.return_value.result=True;w.run('mark')
                self.assertEqual(len(app.history),1)
                app.undo()
                with patch('tools_ui.Progress') as progress,patch('tools_ui.ResultPreview') as preview,patch('tools_ui.combined_size',side_effect=[100,200]),patch('tools_ui.messagebox.showinfo'):
                    progress.return_value.result=[after,after];w.run('compress');preview.assert_not_called()
                self.assertEqual(len(app.history),0)
                with fitz.open(stream=page_bytes(app.entries[0]),filetype='pdf') as d:self.assertEqual(d[0].get_text().strip(),'SEARCH HELLO')
            finally:w.destroy();root.destroy();gc.collect()

if __name__=='__main__':unittest.main()
