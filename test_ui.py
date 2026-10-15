# SPDX-License-Identifier: AGPL-3.0-only
import gc
import time
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
import pymupdf as fitz
from tkinterdnd2 import TkinterDnD
import icons
from app import App
from editor import TextDialog
from thumbs import entry_key


def make_pdf(path, pages):
    with fitz.open() as doc:
        for i in range(pages):
            doc.new_page(width=300, height=400).insert_text((40, 60), f'PAGE {i+1}')
        doc.save(path)


class IconTest(unittest.TestCase):
    def test_all_icons_render(self):
        for name in icons.PATHS:
            self.assertTrue(icons.icon_png(name, 18).startswith(b'\x89PNG'), name)
        self.assertTrue(icons.logo_png(32).startswith(b'\x89PNG'))


class EntryKeyTest(unittest.TestCase):
    def test_reader_keys_are_unique_and_stable(self):
        from io import BytesIO
        from pypdf import PdfReader
        with fitz.open() as doc:
            doc.new_page()
            data = doc.tobytes()
        first, second = PdfReader(BytesIO(data)), PdfReader(BytesIO(data))
        entry = dict(reader=first, page=0, rotation=0)
        self.assertEqual(entry_key(entry), entry_key(dict(entry)))
        self.assertNotEqual(entry_key(entry), entry_key(dict(entry, reader=second)))
        self.assertNotEqual(entry_key(entry), entry_key(dict(entry, rotation=90)))


class MainWindowTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = TkinterDnD.Tk()
        self.app = App(self.root)
        self.root.update()
        fixture = Path(self.folder.name)/'pages.pdf'
        make_pdf(fixture, 4)
        self.app.add_paths([str(fixture)])
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        gc.collect()  # free Tk objects here, not later on the render thread
        self.folder.cleanup()

    def click(self, iid):
        x, y, w, h = self.app.tree.bbox(iid)
        self.app.tree.event_generate('<ButtonPress-1>', x=x+80, y=y+h//2)
        self.app.tree.event_generate('<ButtonRelease-1>', x=x+80, y=y+h//2)
        self.root.update()

    def test_buttons_follow_selection(self):
        app = self.app
        app.tree.selection_set(['0'])
        self.root.update()
        self.assertNotIn('disabled', app.edit_button.state())
        app.tree.selection_set(['0', '1'])
        self.root.update()
        self.assertIn('disabled', app.edit_button.state())
        app.tree.selection_set([])
        self.root.update()
        self.assertTrue(all('disabled' in b.state() for b in app.list_buttons))

    def test_click_inside_multi_selection_selects_one(self):
        app = self.app
        app.tree.selection_set(['0', '1', '2'])
        self.root.update()
        self.click('1')
        self.assertEqual(app.selected(), [1])

    def test_delete_key_and_alt_arrows(self):
        app = self.app
        self.click('1')
        app.tree.focus_force()
        self.root.update()
        app.tree.event_generate('<Delete>')
        self.root.update()
        self.assertEqual(len(app.entries), 3)
        self.assertEqual(app.selected(), [1])
        app.tree.event_generate('<Alt-Up>')
        self.root.update()
        self.assertEqual(app.selected(), [0])
        self.assertEqual([e['page'] for e in app.entries], [2, 0, 3])

    def test_preview_renders_in_background(self):
        app = self.app
        app.tree.selection_set(['2'])
        app.tree.focus('2')
        self.root.update()
        deadline = time.monotonic() + 10
        # Wait for the debounce (pending) and the worker result (expect).
        while time.monotonic() < deadline and (app.preview.pending is not None or app.preview.expect is not None):
            self.root.update()
            time.sleep(0.02)
        self.assertEqual(app.preview.key, entry_key(app.entries[2]))
        self.assertIsNotNone(app.preview.photo)
        self.assertTrue(app.preview.scale_label.cget('text').endswith('%'))

    def test_thumbnails_are_rendered(self):
        app = self.app
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and any(entry_key(e) not in app.thumbnails.images for e in app.entries):
            self.root.update()
            time.sleep(0.02)
        self.assertTrue(all(entry_key(e) in app.thumbnails.images for e in app.entries))


class TextDialogKeysTest(unittest.TestCase):
    def test_enter_adds_line_and_ctrl_enter_applies(self):
        with fitz.open() as doc:
            page = doc.new_page(width=400, height=400)
            page.insert_text((100, 150), 'FIRST')
            page.insert_text((100, 180), 'SECOND')
            source = doc.tobytes()
        root = tk.Tk()
        root.withdraw()
        seen = {}
        def interact():
            dialog = next(c for c in root.winfo_children() if isinstance(c, TextDialog))
            dialog.text.focus_force()
            dialog.text.delete('1.0', 'end')
            dialog.text.insert('1.0', 'ONE')
            dialog.text.event_generate('<Return>')
            dialog.update()
            seen['open after Enter'] = dialog.winfo_exists()
            dialog.text.insert('end', 'TWO')
            dialog.text.event_generate('<Control-Return>')
        try:
            root.after(600, interact)
            dialog = TextDialog(root, 'FIRST\nSECOND', [], 12, source, (60, 130, 350, 190), 'replace')
            self.assertTrue(seen['open after Enter'])
            self.assertEqual(dialog.result[0], 'ONE\nTWO')
        finally:
            root.destroy()
            gc.collect()


if __name__ == '__main__':
    unittest.main()
