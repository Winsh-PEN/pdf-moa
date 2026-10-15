# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for drop position, file bookmarks, thumbnail size and moving added items."""
import gc
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader
from tkinterdnd2 import TkinterDnD
from core import file_bookmarks, save_pdf, load_pdf
from editor import PageEditor
from settings import Settings
from thumbs import entry_key
import app as appmod
import editor as editormod

HERE = Path(__file__).parent


def make_pdf(path, pages=1, text='PAGE'):
    with fitz.open() as doc:
        for i in range(pages):
            doc.new_page(width=300, height=400).insert_text((40, 60), f'{text} {i + 1}')
        doc.save(path)
    return str(path)


def png_bytes(size=(40, 40), color='red'):
    stream = BytesIO()
    Image.new('RGB', size, color).save(stream, 'PNG')
    return stream.getvalue()


class BookmarkTest(unittest.TestCase):
    def test_runs_of_pages(self):
        pages = [dict(path='C:/a/첫째.pdf'), dict(path='C:/a/첫째.pdf'), dict(path=''), dict(path='C:/a/첫째.pdf'),
                 dict(path='C:/b/둘째.pdf'), dict(path='C:/a/첫째.pdf')]
        self.assertEqual(file_bookmarks(pages), [(0, '첫째'), (4, '둘째'), (5, '첫째')])

    def test_saved_outline(self):
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            a, b = make_pdf(Path(folder) / '견적.pdf', 2), make_pdf(Path(folder) / '도면.pdf', 3)
            ra, rb = load_pdf(a), load_pdf(b)
            entries = [dict(path=a, reader=ra, page=i, rotation=0) for i in range(2)] + \
                      [dict(path=b, reader=rb, page=i, rotation=0) for i in range(3)]
            target = Path(folder) / 'out.pdf'
            save_pdf(entries, target, bookmarks=True)
            reader = PdfReader(target)
            self.assertEqual([(item.title, reader.get_destination_page_number(item)) for item in reader.outline],
                             [('견적', 0), ('도면', 2)])
            save_pdf(entries, target)
            self.assertEqual(PdfReader(target).outline, [])


class MainWindowFeatureTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=HERE)
        self.root = TkinterDnD.Tk()
        self.root.geometry('1200x800+0+0')
        self.app = appmod.App(self.root, Settings(Path(self.folder.name) / 'settings.json'))
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        gc.collect()  # free Tk objects here, not later on the render thread
        self.folder.cleanup()

    def pdf(self, name, pages=1):
        return make_pdf(Path(self.folder.name) / name, pages)

    def names(self):
        return [Path(e['path']).name for e in self.app.entries]

    def drop_event(self, row, data=''):
        """A tkinterdnd2-like event at the lower part of a list row (insert after it)."""
        tree = self.app.tree
        x, y, w, h = tree.bbox(str(row))
        return SimpleNamespace(x_root=tree.winfo_rootx() + x + 30, y_root=tree.winfo_rooty() + y + h - 3, data=data)

    def test_drop_inserts_at_the_line(self):
        app = self.app
        app.add_paths([self.pdf('a.pdf', 3)])
        self.root.update()
        event = self.drop_event(0, f'{{{self.pdf("b.pdf")}}}')
        self.assertEqual(app.drop_position(event), appmod.COPY)
        self.assertTrue(app.drop_line.winfo_ismapped() or app.drop_line.place_info())
        self.assertIn('2번째', app.status.get())
        app.drop_files(event)
        self.root.update()
        self.assertEqual(self.names(), ['a.pdf', 'b.pdf', 'a.pdf', 'a.pdf'])
        self.assertFalse(app.drop_line.place_info())

    def test_drop_outside_the_list_appends(self):
        app = self.app
        app.add_paths([self.pdf('a.pdf', 2)])
        self.root.update()
        outside = SimpleNamespace(x_root=app.preview.canvas.winfo_rootx() + 50, y_root=app.preview.canvas.winfo_rooty() + 50,
                                  data=f'{{{self.pdf("b.pdf")}}}')
        app.drop_position(outside)
        self.assertIn('끝에', app.status.get())
        app.drop_files(outside)
        self.root.update()
        self.assertEqual(self.names(), ['a.pdf', 'a.pdf', 'b.pdf'])

    def test_bookmark_option_is_used_and_remembered(self):
        app = self.app
        app.add_paths([self.pdf('a.pdf'), self.pdf('b.pdf')])
        app.bookmarks.set(True)
        target = str(Path(self.folder.name) / 'out.pdf')
        with mock.patch.object(appmod.filedialog, 'asksaveasfilename', return_value=target), \
             mock.patch.object(appmod.ui, 'ChoiceDialog') as done:
            done.return_value.result = 'close'
            app.export(False)
        self.assertEqual([item.title for item in PdfReader(target).outline], ['a', 'b'])

    def test_thumbnail_size(self):
        app = self.app
        app.add_paths([self.pdf('a.pdf', 2)])
        app.thumb_size.set('large')
        app.change_thumb_size()
        self.assertEqual(app.settings.get('thumb_size'), 'large')
        self.assertEqual(app.thumbnails.box, tuple(appmod.px(self.root, v) for v in appmod.THUMB_SIZES['large']))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and any(entry_key(e) not in app.thumbnails.images for e in app.entries):
            self.root.update()
            time.sleep(0.02)
        image = app.thumbnails.images[entry_key(app.entries[0])]
        self.assertEqual((image.width(), image.height()), app.thumbnails.box)


class EditorMoveTest(unittest.TestCase):
    def setUp(self):
        self.root = TkinterDnD.Tk()
        with fitz.open() as doc:
            doc.new_page(width=400, height=400).insert_text((50, 60), 'KEEP', fontsize=12)
            self.original = doc.tobytes()
        entry = dict(path='', reader=PdfReader(BytesIO(self.original)), page=0, rotation=0)
        self.editor = PageEditor(self.root, entry, lambda data: None)
        self.editor.geometry('1080x880+0+0')
        self.root.update()
        self.editor.render()

    def tearDown(self):
        self.editor.finish()
        self.root.destroy()
        gc.collect()

    def image_rect(self):
        with fitz.open(stream=self.editor.data, filetype='pdf') as doc:
            return tuple(round(v) for v in doc[0].get_image_rects(doc[0].get_images()[0][0])[0])

    def text(self):
        with fitz.open(stream=self.editor.data, filetype='pdf') as doc:
            return doc[0].get_text()

    def test_move_resize_and_undo(self):
        ed = self.editor
        ed.push('image', (50, 100, 150, 200), dict(image=png_bytes()))
        ed.push('text', (200, 100, 380, 160), dict(text='메모 MEMO', size=12, color=(0, 0, 0), font_face=None))
        self.assertTrue(ed.change_op(0, rect=(150, 250, 250, 350)))
        self.assertEqual(self.image_rect(), (150, 250, 250, 350))
        self.assertIn('메모 MEMO', self.text())  # the later edit was applied again
        self.assertTrue(ed.change_op(0, rect=(150, 250, 210, 290)))  # smaller box, square picture
        self.assertEqual(self.image_rect(), (160, 250, 200, 290))
        ed.undo()
        self.assertEqual(self.image_rect(), (150, 250, 250, 350))
        ed.undo()
        self.assertEqual(self.image_rect(), (50, 100, 150, 200))
        ed.undo()
        ed.undo()
        self.assertEqual(ed.data, ed.original)  # the page as opened in the editor
        self.assertIn('disabled', ed.undo_button.state())
        self.assertIn('disabled', ed.apply_button.state())

    def test_change_that_no_longer_fits_is_refused(self):
        ed = self.editor
        ed.push('text', (50, 100, 150, 130), dict(text='ABCDEFGHIJ', size=12, color=(0, 0, 0), font_face=None))
        before = (ed.ops, ed.data)
        with mock.patch.object(editormod.messagebox, 'showerror') as error:
            self.assertFalse(ed.change_op(0, rect=(360, 100, 460, 130)))  # mostly off the page
        error.assert_called_once()
        self.assertEqual((ed.ops, ed.data), before)

    def test_remove_an_earlier_item(self):
        ed = self.editor
        ed.push('image', (50, 100, 150, 200), dict(image=png_bytes()))
        ed.push('text', (200, 100, 380, 160), dict(text='남길 글자', size=12, color=(0, 0, 0), font_face=None))
        self.assertTrue(ed.remove_op(0))  # the picture, not the last edit
        with fitz.open(stream=ed.data, filetype='pdf') as doc:
            self.assertEqual(doc[0].get_images(), [])
        self.assertIn('남길 글자', self.text())
        self.assertEqual([op['mode'] for op in ed.ops], ['text'])
        ed.undo()
        self.assertEqual([op['mode'] for op in ed.ops], ['image', 'text'])

    def test_edit_text_content(self):
        ed = self.editor
        ed.push('text', (50, 100, 300, 140), dict(text='처음', size=12, color=(0, 0, 0), font_face=None))
        self.assertTrue(ed.change_op(0, kw=dict(text='고친 글자', size=14, color=(1, 0, 0), font_face=None)))
        self.assertIn('고친 글자', self.text())
        self.assertNotIn('처음', self.text())

    def test_drag_with_the_mouse(self):
        ed = self.editor
        ed.push('image', (50, 100, 150, 200), dict(image=png_bytes()))
        ed.mode.set('move')
        ed.mode_changed()
        self.root.update()
        scale, (ox, oy) = ed.scale, ed.offset
        start = (ox + 100 * scale, oy + 150 * scale)  # centre of the picture
        end = (start[0] + 100 * scale, start[1] + 50 * scale)
        ed.canvas.event_generate('<ButtonPress-1>', x=int(start[0]), y=int(start[1]))
        ed.canvas.event_generate('<B1-Motion>', x=int(end[0]), y=int(end[1]))
        ed.canvas.event_generate('<ButtonRelease-1>', x=int(end[0]), y=int(end[1]))
        self.root.update()
        x0, y0, x1, y1 = self.image_rect()
        self.assertAlmostEqual(x0, 150, delta=2)
        self.assertAlmostEqual(y0, 150, delta=2)
        self.assertEqual((x1 - x0, y1 - y0), (100, 100))
        # dragging the bottom-right grip resizes
        grip = (ox + x1 * scale, oy + y1 * scale)
        ed.canvas.event_generate('<ButtonPress-1>', x=int(grip[0]), y=int(grip[1]))
        ed.canvas.event_generate('<B1-Motion>', x=int(grip[0] - 50 * scale), y=int(grip[1] - 50 * scale))
        ed.canvas.event_generate('<ButtonRelease-1>', x=int(grip[0] - 50 * scale), y=int(grip[1] - 50 * scale))
        self.root.update()
        x0, y0, x1, y1 = self.image_rect()
        self.assertAlmostEqual(x1 - x0, 50, delta=2)


if __name__ == '__main__':
    unittest.main()
