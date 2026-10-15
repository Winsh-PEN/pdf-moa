# SPDX-License-Identifier: AGPL-3.0-only
"""Regression tests for review items B1-B11 (2026-10-15) and the page-list features."""
import ast
import gc
import re
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock
import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader
from tkinterdnd2 import TkinterDnD
from core import parse_pages, split_groups, group_name, new_folder, natural_key, save_pdf, load_pdf
from editing import edit_page, selected_text, selected_fonts, page_bytes, updated_entry, normalized_image
from fonts import inspect_file, checked_font_bytes
from settings import Settings
from test_fonts import make_font
import app as appmod
import ui

HERE = Path(__file__).parent


def spans(data):
    with fitz.open(stream=data, filetype='pdf') as doc:
        return [(s['text'], tuple(round(v) for v in s['origin']), s['bbox'][2] - s['bbox'][0])
                for b in doc[0].get_text('dict')['blocks'] for l in b.get('lines', []) for s in l['spans']]


def two_lines(first_font='helv', first_size=12):
    with fitz.open() as doc:
        page = doc.new_page(width=400, height=300)
        page.insert_text((100, 150), 'FIRST LINE', fontname=first_font, fontsize=first_size)
        page.insert_text((100, 180), 'SECOND LINE', fontsize=12)
        return doc.tobytes()


def make_pdf(path, pages=1, text='PAGE', **save):
    with fitz.open() as doc:
        for i in range(pages):
            doc.new_page(width=300, height=400).insert_text((40, 60), f'{text} {i + 1}')
        doc.save(path, **save)


class SelectionRuleTest(unittest.TestCase):
    """B9: a box that only touches a neighbouring line must not pick it up."""

    def test_box_touching_line_above(self):
        data = two_lines()
        box = (90, 152, 300, 190)  # 1.6pt into FIRST LINE's character boxes
        self.assertEqual(selected_text(data, box), 'SECOND LINE')
        result = spans(edit_page(data, box, 'replace', text='NEW SECOND', size=12))
        self.assertEqual([(t, o) for t, o, _ in result], [('FIRST LINE', (100, 150)), ('NEW SECOND', (100, 180))])

    def test_box_touching_line_below(self):
        data = two_lines()
        box = (90, 130, 300, 168)
        self.assertEqual(selected_text(data, box), 'FIRST LINE')
        result = spans(edit_page(data, box, 'replace', text='NEW FIRST', size=12))
        self.assertEqual(sorted((t, o) for t, o, _ in result), [('NEW FIRST', (100, 150)), ('SECOND LINE', (100, 180))])

    def test_original_font_comes_from_selected_line(self):
        data = two_lines(first_font='tiro', first_size=20)
        names, size = selected_fonts(data, (90, 156, 300, 190))
        self.assertEqual((names, size), (['Helvetica'], 12))

    def test_delete_mode_removes_only_the_selection(self):
        data = two_lines()
        result = edit_page(data, (90, 152, 300, 190), 'delete')
        with fitz.open(stream=result, filetype='pdf') as doc:
            self.assertEqual(doc[0].get_text().split(), ['FIRST', 'LINE'])
            for xref in range(1, doc.xref_length()):
                if doc.xref_is_stream(xref):
                    self.assertNotIn(b'SECOND', doc.xref_stream(xref))

    def test_part_of_a_line(self):
        with fitz.open() as doc:
            doc.new_page(width=400, height=200).insert_text((50, 100), 'KEEP CHANGE KEEP', fontsize=12)
            data = doc.tobytes()
        start = fitz.get_text_length('KEEP ', fontsize=12) + 50
        end = start + fitz.get_text_length('CHANGE', fontsize=12)
        box = (start - 1, 85, end + 1, 105)
        self.assertEqual(selected_text(data, box), 'CHANGE')
        with fitz.open(stream=edit_page(data, box, 'delete'), filetype='pdf') as doc:
            self.assertEqual(doc[0].get_text().split(), ['KEEP', 'KEEP'])


class DefaultFontTest(unittest.TestCase):
    """B1: the built-in Korean font is measured and drawn with the same widths."""

    def setUp(self):
        with fitz.open() as doc:
            page = doc.new_page(width=400, height=200)
            page.insert_text((50, 100), 'OLD VALUE 1', fontsize=12)
            page.insert_text((260, 100), 'NEIGHBOR', fontsize=12)
            self.data = doc.tobytes()

    def test_drawn_width_matches_measurement(self):
        text = 'Total 1,234,567 합계'
        expected = fitz.Font('korea').text_length(text, fontsize=12)
        drawn = [w for t, _, w in spans(edit_page(self.data, (40, 85, 250, 105), 'replace', text=text, size=12)) if t == text]
        self.assertEqual(len(drawn), 1)
        self.assertAlmostEqual(drawn[0], expected, delta=expected * 0.02)

    def test_too_wide_text_is_refused(self):
        with self.assertRaises(ValueError):
            edit_page(self.data, (40, 85, 250, 105), 'replace', text='Total 1,234,567,890 합계 금액입니다 그리고 더 긴 설명', size=12)

    def test_added_text_has_normal_spacing(self):
        text = '추가 Text 12,345'
        drawn = [w for t, _, w in spans(edit_page(self.data, (40, 120, 390, 190), 'text', text=text, size=12)) if t == text]
        self.assertAlmostEqual(drawn[0], fitz.Font('korea').text_length(text, fontsize=12), delta=2)


class FontSubsetTest(unittest.TestCase):
    """B2: only the glyphs that are used get embedded, unless the font forbids it."""

    def test_subset_unless_forbidden(self):
        from fontTools.ttLib import TTFont
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            for flags, keeps_b in ((0, False), (0x100, True)):
                path = Path(folder) / f'font{flags}.ttf'
                make_font(path, flags=flags)
                with TTFont(BytesIO(checked_font_bytes(inspect_file(path)[0], 'A'))) as font:
                    self.assertEqual('B' in font.getGlyphOrder(), keeps_b)

    def test_edited_pages_stay_small(self):
        with fitz.open() as doc:
            for i in range(3):
                doc.new_page().insert_text((72, 100), f'ORIGINAL {i}', fontsize=12)
            reader = PdfReader(BytesIO(doc.tobytes()))
        entries = []
        for i in range(3):
            entry = dict(path='src.pdf', reader=reader, page=i, rotation=0)
            entries.append(updated_entry(entry, edit_page(page_bytes(entry), (60, 80, 400, 110), 'replace', text=f'새 글자 {i}', size=12)))
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            target = Path(folder) / 'small.pdf'
            save_pdf(entries, target)
            self.assertLess(target.stat().st_size, 200_000)


class ImageTest(unittest.TestCase):
    """B10: phone photos are placed upright; WebP works; unreadable files get a clear message."""

    def setUp(self):
        with fitz.open() as doc:
            doc.new_page(width=400, height=400)
            self.blank = doc.tobytes()

    def placed(self, image_bytes):
        result = edit_page(self.blank, (50, 50, 350, 350), 'image', image=image_bytes)
        with fitz.open(stream=result, filetype='pdf') as doc:
            return doc[0].get_image_rects(doc[0].get_images()[0][0])[0]

    def test_exif_rotation(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # stored landscape, shown portrait
        stream = BytesIO()
        Image.new('RGB', (80, 40), 'blue').save(stream, 'JPEG', exif=exif)
        rect = self.placed(stream.getvalue())
        self.assertLess(rect.width, rect.height)

    def test_plain_jpeg_is_not_recompressed(self):
        stream = BytesIO()
        Image.new('RGB', (80, 40), 'blue').save(stream, 'JPEG')
        self.assertEqual(normalized_image(stream.getvalue()), stream.getvalue())

    def test_webp_and_transparent_png(self):
        for mode, fmt in (('RGB', 'WEBP'), ('RGBA', 'PNG')):
            stream = BytesIO()
            Image.new(mode, (80, 40), 'red').save(stream, fmt)
            self.assertGreater(self.placed(stream.getvalue()).width, 0)

    def test_square_picture_is_not_stretched(self):
        # PyMuPDF 1.26.7's keep_proportion stretches square pictures; editing.fitted_rect avoids it.
        stream = BytesIO()
        Image.new('RGB', (40, 40), 'red').save(stream, 'PNG')
        result = edit_page(self.blank, (100, 100, 300, 150), 'image', image=stream.getvalue())
        with fitz.open(stream=result, filetype='pdf') as doc:
            rect = doc[0].get_image_rects(doc[0].get_images()[0][0])[0]
        self.assertEqual(tuple(round(v) for v in rect), (175, 100, 225, 150))

    def test_unreadable_file(self):
        with self.assertRaisesRegex(ValueError, '지원하지 않는 사진 형식'):
            edit_page(self.blank, (50, 50, 250, 250), 'image', image=b'not an image')


class RangeTest(unittest.TestCase):
    """B7: range input errors are in Korean."""

    def test_messages(self):
        for text, total, message in [('1-', 5, '숫자와'), ('a', 5, '숫자와'), ('3-1', 5, '작은 번호부터'),
                                     ('9', 5, '1부터 5까지'), ('1', 0, '먼저 PDF')]:
            with self.assertRaisesRegex(ValueError, message):
                parse_pages(text, total)

    def test_tilde_and_spaces(self):
        self.assertEqual(parse_pages(' 1 ~ 3 , 5, ', 5), [0, 1, 2, 4])


class SplitHelpersTest(unittest.TestCase):
    """B6: readable split folders and file names, plus the split modes."""

    def test_groups(self):
        self.assertEqual(split_groups([0, 1, 2, 3, 4], 'each'), [[0], [1], [2], [3], [4]])
        self.assertEqual(split_groups([0, 1, 2, 3, 4], 'every', 2), [[0, 1], [2, 3], [4]])
        self.assertEqual(split_groups([], 'ranges', '1-2, 4', 5), [[0, 1], [3]])

    def test_names(self):
        page = lambda path, n: dict(path=path, page=n)
        self.assertEqual(group_name(1, [page('C:/a/계약 서:1.pdf', 2)]), '001_계약 서_1_p3.pdf')
        self.assertEqual(group_name(12, [page('C:/a/x.pdf', 0), page('C:/a/x.pdf', 3)]), '012_x_p1-4.pdf')
        self.assertEqual(group_name(3, [page('C:/a/x.pdf', 0), page('C:/b/y.pdf', 0)]), '003_x_외_2쪽.pdf')
        self.assertEqual(group_name(4, [dict(path='', page=0)]), '004_빈페이지_p1.pdf')

    def test_new_folder_is_unique(self):
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            first, second = new_folder(folder), new_folder(folder)
            self.assertNotEqual(first, second)
            self.assertTrue(re.fullmatch(r'PDF_분리_\d{8}_\d{6}', first.name))

    def test_natural_order(self):
        names = ['scan10.pdf', 'scan2.pdf', 'Scan1.pdf']
        self.assertEqual(sorted(names, key=natural_key), ['Scan1.pdf', 'scan2.pdf', 'scan10.pdf'])


class ProtectSourcesTest(unittest.TestCase):
    """B11: saving never overwrites any loaded source file."""

    def test_other_source_is_protected(self):
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            a, b = Path(folder) / 'A.pdf', Path(folder) / 'B.pdf'
            make_pdf(a, text='AAA')
            make_pdf(b, text='BBB')
            entry = dict(path=str(a), reader=load_pdf(a), page=0, rotation=0)
            with self.assertRaisesRegex(ValueError, '원본 보호'):
                save_pdf([entry], str(b).upper(), protected={str(a), str(b)})
            self.assertIn('BBB', PdfReader(b).pages[0].extract_text())


class RequirementsTest(unittest.TestCase):
    """B4: AES encrypted PDFs need cryptography, which must be a listed dependency."""

    def test_cryptography_listed_and_aes_opens(self):
        self.assertRegex((HERE / 'requirements.txt').read_text(), r'(?m)^cryptography==')
        with tempfile.TemporaryDirectory(dir=HERE) as folder:
            path = Path(folder) / 'aes.pdf'
            make_pdf(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='1234', owner_pw='owner')
            self.assertEqual(len(load_pdf(path, '1234').pages), 1)


class VersionTest(unittest.TestCase):
    """B8: one version string, read by the release script from app.py."""

    def test_single_version(self):
        self.assertRegex(appmod.VERSION, r'^\d+\.\d+\.\d+(-rc\d+)?$')
        script = (HERE / 'prepare_editor_release.py').read_text(encoding='utf-8')
        versions = {node.value for node in ast.walk(ast.parse(script))
                    if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r'\d+\.\d+\.\d+-rc', node.value)}
        self.assertLessEqual(versions, {'PDF-Moa-1.0.0-rc1-Windows-x64', '1.0.0-rc1'})
        self.assertNotIn('1.2.0-rc1', (HERE / 'README.md').read_text(encoding='utf-8'))


class AppTest(unittest.TestCase):
    """B3, B5 and the page-list actions, driven through the main window."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=HERE)
        self.root = TkinterDnD.Tk()
        self.app = appmod.App(self.root, Settings(Path(self.folder.name) / 'settings.json'))
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        gc.collect()  # free Tk objects here, not later on the render thread
        self.folder.cleanup()

    def pdf(self, name, pages=1, **save):
        path = Path(self.folder.name) / name
        make_pdf(path, pages, **save)
        return str(path)

    def pages(self):
        return [(Path(e['path']).name if e['path'] else '', e['page'], e['rotation']) for e in self.app.entries]

    def test_password_retry(self):
        path = self.pdf('locked.pdf', encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='1234', owner_pw='owner')
        with mock.patch.object(ui, 'ask_password', side_effect=['wrong', '1234']) as ask, \
             mock.patch.object(appmod.messagebox, 'showerror') as error:
            self.app.add_paths([path])
        self.assertEqual(ask.call_count, 2)
        self.assertIn('맞지 않습니다', ask.call_args_list[1].args[2])
        error.assert_not_called()
        self.assertEqual(len(self.app.entries), 1)
        with mock.patch.object(ui, 'ask_password', side_effect=['a', 'b', 'c']), \
             mock.patch.object(appmod.messagebox, 'showerror') as error:
            self.app.add_paths([path])
        self.assertIn('3번', error.call_args.args[1])
        self.assertNotIn('PASSWORD_REQUIRED', error.call_args.args[1])
        with mock.patch.object(ui, 'ask_password', return_value=None), \
             mock.patch.object(appmod.messagebox, 'showerror') as error:
            self.app.add_paths([path])
        error.assert_not_called()
        self.assertEqual(len(self.app.entries), 1)

    def test_files_are_added_in_natural_order(self):
        paths = [self.pdf(n) for n in ('p10.pdf', 'p2.pdf', 'p1.pdf')]
        self.app.add_paths(paths)
        self.assertEqual([p[0] for p in self.pages()], ['p1.pdf', 'p2.pdf', 'p10.pdf'])

    def test_move_at_edge_keeps_undo_history(self):
        self.app.add_paths([self.pdf('a.pdf', 3)])
        history = len(self.app.history)
        self.app.tree.selection_set(['0'])
        self.app.move(-1)
        self.assertEqual(len(self.app.history), history)
        self.app.move(1)
        self.assertEqual(len(self.app.history), history + 1)

    def test_list_actions_and_redo(self):
        app = self.app
        app.add_paths([self.pdf('a.pdf', 3)])
        app.tree.selection_set(['2'])
        app.move_to('top')
        self.assertEqual([p[1] for p in self.pages()], [2, 0, 1])
        app.tree.selection_set(['0'])
        app.rotate(-90)
        self.assertEqual(self.pages()[0][2], 270)
        app.duplicate()
        self.assertEqual([p[1] for p in self.pages()], [2, 2, 0, 1])
        app.tree.selection_set(['3'])
        app.insert_blank()
        self.assertEqual(self.pages()[4], ('', 0, 0))
        blank = app.entries[4]['reader'].pages[0]
        self.assertEqual((round(float(blank.mediabox.width)), round(float(blank.mediabox.height))), (300, 400))
        before = self.pages()
        app.undo()
        app.undo()
        self.assertEqual(len(app.entries), 3)
        app.redo()
        app.redo()
        self.assertEqual(self.pages(), before)
        app.undo()
        app.tree.selection_set(['0'])
        app.rotate(180)
        self.assertEqual(app.future, [])  # a new change drops the redo steps

    def test_insert_files_after_selection(self):
        app = self.app
        app.add_paths([self.pdf('a.pdf', 2)])
        app.tree.selection_set(['0'])
        with mock.patch.object(appmod.filedialog, 'askopenfilenames', return_value=(self.pdf('b.pdf'),)):
            app.insert_files()
        self.assertEqual([p[0] for p in self.pages()], ['a.pdf', 'b.pdf', 'a.pdf'])
        self.assertEqual(app.settings.get('open_dir'), str(Path(self.folder.name)))

    def test_export_protects_every_loaded_source(self):
        app = self.app
        a, b = self.pdf('a.pdf'), self.pdf('b.pdf')
        app.add_paths([a, b])
        app.tree.selection_set(['0'])
        with mock.patch.object(appmod.filedialog, 'asksaveasfilename', return_value=b), \
             mock.patch.object(appmod.messagebox, 'showerror') as error:
            app.export(True)
        self.assertIn('원본 보호', error.call_args.args[1])

    def test_export_default_name_and_save(self):
        app = self.app
        app.add_paths([self.pdf('견적서.pdf', 2)])
        target = str(Path(self.folder.name) / 'out.pdf')
        with mock.patch.object(appmod.filedialog, 'asksaveasfilename', return_value=target) as ask, \
             mock.patch.object(appmod.ui, 'ChoiceDialog') as done:
            done.return_value.result = 'close'
            app.export(False)
        self.assertEqual(ask.call_args.kwargs['initialfile'], '견적서_정리.pdf')
        self.assertEqual(len(PdfReader(target).pages), 2)
        self.assertEqual(app.state_signature(), app.saved_state)

    def test_split_names(self):
        app = self.app
        app.add_paths([self.pdf('도면.pdf', 3)])
        with mock.patch.object(appmod, 'SplitDialog') as dialog, \
             mock.patch.object(appmod.filedialog, 'askdirectory', return_value=self.folder.name), \
             mock.patch.object(appmod.ui, 'ChoiceDialog') as done:
            dialog.return_value.result = ('all', 'every', 2)
            done.return_value.result = 'close'
            app.split()
        # After adding, page 1 is selected; with one page selected the whole list is the default.
        self.assertEqual(dialog.call_args.args[1:], (3, 1, False))
        output = next(Path(self.folder.name).glob('PDF_분리_*'))
        self.assertEqual(sorted(p.name for p in output.iterdir()), ['001_도면_p1-2.pdf', '002_도면_p3.pdf'])

    def test_split_dialog(self):
        from dialogs import SplitDialog, default_scope
        self.assertEqual([default_scope(3, c, p) for c, p in [(1, False), (2, False), (1, True), (0, True), (3, False)]],
                         ['all', 'selected', 'selected', 'all', 'all'])
        seen = {}
        def interact():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, SplitDialog))
            seen['default'] = dialog.each_button.cget('text')
            dialog.scope.set('all')
            dialog.update_labels()
            seen['all'] = dialog.each_button.cget('text')
            dialog.mode.set('every')
            dialog.every.set('2')
            dialog.ok()
        self.root.after(300, interact)
        result = SplitDialog(self.root, 3, 2).result
        self.assertIn('파일 2개', seen['default'])
        self.assertIn('파일 3개', seen['all'])
        self.assertEqual(result, ('all', 'every', 2))

    def test_export_images(self):
        app = self.app
        app.add_paths([self.pdf('도면.pdf', 2)])
        app.tree.selection_set(['0', '1'])
        with mock.patch.object(appmod.ui, 'ChoiceDialog') as choice, \
             mock.patch.object(appmod.filedialog, 'askdirectory', return_value=self.folder.name):
            choice.return_value.result = 150
            app.export_images()
        output = next(Path(self.folder.name).glob('PDF_이미지_*'))
        files = sorted(output.iterdir())
        self.assertEqual([p.name for p in files], ['001_도면_p1.png', '002_도면_p2.png'])
        with Image.open(files[0]) as image:  # 300 x 400 pt at 150 dpi, MuPDF rounds up
            self.assertAlmostEqual(image.width, 625, delta=1)
            self.assertAlmostEqual(image.height, 833, delta=1)
        self.assertNotEqual(app.state_signature(), app.saved_state)  # images do not count as saving the list

    def test_huge_page_image_is_limited(self):
        from editing import page_png
        from core import blank_reader
        entry = dict(path='', reader=blank_reader(3370, 2384), page=0, rotation=0)  # A0 landscape
        with Image.open(BytesIO(page_png(entry, 300))) as image:
            self.assertLessEqual(image.width * image.height, 40_000_000)

    def test_context_menu_states(self):
        app = self.app
        app.add_paths([self.pdf('a.pdf', 2)])
        app.insert_blank()  # page 1 is selected after adding, so the blank page becomes row 1
        self.assertEqual(self.pages()[1], ('', 0, 0))
        def states():
            menu = app.context_menu()
            return {menu.entrycget(i, 'label').strip(): menu.entrycget(i, 'state')
                    for i in range(menu.index('end') + 1) if menu.type(i) == 'command'}
        app.tree.selection_set(['0'])
        self.assertEqual(states()['글자·사진 편집…'], 'normal')
        self.assertEqual(states()['원본 PDF 열기'], 'normal')
        app.tree.selection_set(['1'])  # the blank page has no source file
        self.assertEqual(states()['원본 PDF 열기'], 'disabled')
        app.tree.selection_set(['0', '1'])
        self.assertEqual(states()['글자·사진 편집…'], 'disabled')
        self.assertEqual(states()['복제'], 'normal')
        app.tree.selection_set([])
        current = states()
        self.assertEqual(current['맨 위로'], 'disabled')
        self.assertEqual(current['뒤에 빈 페이지 넣기'], 'normal')

    def test_settings_round_trip(self):
        self.app.settings.set('open_dir', self.folder.name)
        self.app.remember_window()
        again = Settings(self.app.settings.path)
        self.assertEqual(again.folder('open_dir'), self.folder.name)
        self.assertTrue(isinstance(again.get('list_width'), int))


if __name__ == '__main__':
    unittest.main()
