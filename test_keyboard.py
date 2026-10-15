import gc
import unittest
import tempfile
from pathlib import Path
from pypdf import PdfWriter
from tkinterdnd2 import TkinterDnD
from app import App


class KeyboardNavigationTest(unittest.TestCase):
    def test_click_then_arrow_updates_selection_and_preview(self):
        root = TkinterDnD.Tk()
        folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        try:
            app = App(root)
            root.update()
            fixture = Path(folder.name)/'pages.pdf'
            with PdfWriter() as writer:
                for i in range(3):
                    writer.add_blank_page(width=400,height=500)
                writer.write(fixture)
            app.add_paths([str(fixture)])
            root.update()
            original = [e['page'] for e in app.entries]
            history_length = len(app.history)
            # Reproduce clicking the list while an input field owns focus.
            app.range_text.focus_force()
            root.update()
            x, y, w, h = app.tree.bbox('0')
            app.tree.event_generate('<ButtonPress-1>', x=x+20, y=y+h//2)
            app.tree.event_generate('<ButtonRelease-1>', x=x+20, y=y+h//2)
            root.update()
            self.assertEqual(root.focus_get(), app.tree)
            for key, expected in [('Down',1),('Down',2),('Down',2),('Up',1),('Up',0),('Up',0)]:
                app.tree.event_generate(f'<KeyPress-{key}>')
                root.update()
                self.assertEqual(app.selected(), [expected])
                self.assertEqual(app.preview.key[1], expected)
            self.assertEqual([e['page'] for e in app.entries], original)
            self.assertEqual(len(app.history), history_length)
        finally:
            root.destroy()
            gc.collect()
            folder.cleanup()


if __name__ == '__main__':
    unittest.main()
