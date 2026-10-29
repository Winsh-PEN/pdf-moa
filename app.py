# SPDX-License-Identifier: AGPL-3.0-only
from contextlib import contextmanager
import os
import re
import subprocess
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from core import load_pdf, blank_reader, natural_key, parse_pages, split_groups, group_name, new_folder, save_pdf
from tkinterdnd2 import TkinterDnD, DND_FILES, COPY
from preview import Preview
from editor import PageEditor
from editing import updated_entry, page_png
from fonts import installed_fonts
from thumbs import Thumbnails, entry_key
from settings import Settings
from dialogs import SplitDialog
from tools_ui import ToolsWindow
import ui
from ui import px, icon_button

VERSION = '1.5.0-rc1'
LIST_WIDTH = 440  # default page-list width at 100% scaling
THUMB_SIZES = {'small': (40, 52), 'large': (72, 96)}  # thumbnail cell at 100% scaling


def display_name(entry):
    return Path(entry['path']).name if entry.get('path') else '빈 페이지'


class App:
    def __init__(self, root, settings=None):
        self.root = root
        self.entries = []
        self.history = []
        self.future = []  # pages lists for redo
        self.saved_state = ()
        self.thumb_rows = {}
        self.thumb_job = None
        self.settings = settings or Settings()
        root.title(f'PDF 모아 {VERSION} · 합치기 / 편집 / 분리')
        ui.apply_theme(root)
        ui.fit_geometry(root, 1360, 900, minimum=(980, 640))
        self.restore_window()
        self.icons = ui.icons_for(root)
        self.build_toolbar()
        body = ttk.Frame(root, padding=(px(root, 16), px(root, 12), px(root, 16), px(root, 10)))
        self.build_footer()
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='PDF 파일을 창에 끌어 놓으세요 · 페이지를 끌어서 순서 변경 · Ctrl / Shift로 여러 페이지 선택 · 오른쪽 클릭으로 더 많은 기능',
                  style='Muted.TLabel').pack(anchor='w', pady=(0, px(root, 10)))
        self.panes = panes = ttk.Panedwindow(body, orient='horizontal')
        panes.pack(fill='both', expand=True)
        left = ttk.Frame(panes, width=px(root, LIST_WIDTH))
        panes.add(left, weight=0)
        header = ttk.Frame(left)
        header.pack(fill='x', pady=(0, px(root, 6)))
        ttk.Label(header, text='페이지 목록', style='Section.TLabel').pack(side='left')
        size = self.settings.get('thumb_size')
        self.thumb_size = tk.StringVar(value=size if size in THUMB_SIZES else 'small')
        for value, label in (('large', '크게'), ('small', '작게')):
            ttk.Radiobutton(header, text=label, value=value, variable=self.thumb_size, style='Small.Toolbutton',
                            command=self.change_thumb_size).pack(side='right', padx=(px(root, 3), 0))
        ttk.Label(header, text='썸네일', style='Muted.TLabel').pack(side='right', padx=(0, px(root, 3)))
        # Pack the buttons first so they stay visible when the window is short.
        controls = ttk.Frame(left, padding=(0, px(root, 8), 0, 0))
        controls.pack(side='bottom', fill='x')
        area = ttk.Frame(left, style='Card.TFrame', padding=1)
        area.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(area, columns=('order', 'file', 'page', 'rotation'), show='tree headings',
                                 selectmode='extended', style='Pages.Treeview', height=5)
        self.tree.heading('#0', text='')
        self.tree.column('#0', stretch=False, anchor='center')
        for key, label, width in [('order', '#', 40), ('file', '원본 파일', 150), ('page', '쪽', 46), ('rotation', '회전', 50)]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=px(root, width), minwidth=px(root, 35),
                             anchor='w' if key == 'file' else 'center', stretch=key == 'file')
        self.tree.tag_configure('edited', foreground=ui.ACCENT_HOVER)
        self.tree.tag_configure('blank', foreground=ui.MUTED)
        scrollbar = ttk.Scrollbar(area, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=lambda *a: (scrollbar.set(*a), self.request_thumbnails()))
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='left', fill='y')
        self.empty = self.build_empty_state(self.tree)
        self.list_buttons = []
        for n, (label, icon, command, tip) in enumerate([
                ('위로', 'up', lambda: self.move(-1), '선택한 페이지를 위로 (Alt+↑)\n맨 위로: Alt+Home'),
                ('아래로', 'down', lambda: self.move(1), '선택한 페이지를 아래로 (Alt+↓)\n맨 아래로: Alt+End'),
                ('회전', 'rotate', self.rotate, '오른쪽으로 90° 회전 (Ctrl+R)\n왼쪽으로: Ctrl+Shift+R'),
                ('삭제', 'trash', self.remove, '선택한 페이지를 목록에서 빼기 (Delete)\n원본 파일은 그대로입니다.'),
                ('원본', 'open', self.open_source, '원본 PDF를 기본 뷰어로 열기')]):
            button = icon_button(controls, label, icon, command, style='Small.TButton', tip=tip, size=16)
            button.grid(row=0, column=n, sticky='ew', padx=(0 if n == 0 else px(root, 4), 0))
            controls.columnconfigure(n, weight=1)
            self.list_buttons.append(button)
        self.preview = Preview(panes)
        panes.add(self.preview, weight=1)
        list_width = self.settings.get('list_width')
        list_width = px(root, list_width if isinstance(list_width, int) and 320 <= list_width <= 900 else LIST_WIDTH)
        def place_sash(event):
            # Set the list width once the panes have their real size.
            if panes.winfo_width() > list_width + px(root, 300):
                panes.sashpos(0, list_width)
                panes.unbind('<Configure>', sash_binding)
        sash_binding = panes.bind('<Configure>', place_sash, add='+')
        self.thumbnails = None
        self.apply_thumb_size()
        self.tree.bind('<Destroy>', self.cancel_thumbnail_job, add='+')
        self.tree.bind('<<TreeviewSelect>>', self.selection_changed)
        self.drag_start = None
        self.drag_indices = []
        self.drag_active = False
        self.press_row = None
        self.drop_line = tk.Frame(self.tree, height=3, bg=ui.ACCENT)
        self.tree.bind('<ButtonPress-1>', self.drag_press)
        self.tree.bind('<B1-Motion>', self.drag_motion)
        self.tree.bind('<ButtonRelease-1>', self.drag_release)
        self.tree.bind('<Escape>', self.cancel_drag)
        self.tree.bind('<Delete>', lambda event: self.remove())
        self.tree.bind('<Control-a>', self.select_all)
        self.tree.bind('<Control-A>', self.select_all)
        self.tree.bind('<Alt-Up>', lambda event: self.move(-1) or 'break')
        self.tree.bind('<Alt-Down>', lambda event: self.move(1) or 'break')
        self.tree.bind('<Alt-Home>', lambda event: self.move_to('top') or 'break')
        self.tree.bind('<Alt-End>', lambda event: self.move_to('bottom') or 'break')
        self.tree.bind('<Home>', lambda event: self.select_edge(0))
        self.tree.bind('<End>', lambda event: self.select_edge(-1))
        self.tree.bind('<Double-1>', lambda event: self.edit_selected() if self.tree.identify_row(event.y) else None)
        self.tree.bind('<Button-3>', self.popup_menu)
        self.tree.bind('<Shift-F10>', self.popup_menu)
        self.tree.bind('<App>', self.popup_menu)
        root.drop_target_register(DND_FILES)
        root.dnd_bind('<<DropEnter>>', self.drop_position)
        root.dnd_bind('<<DropPosition>>', self.drop_position)
        root.dnd_bind('<<DropLeave>>', self.drop_leave)
        root.dnd_bind('<<Drop>>', self.drop_files)
        for keys, action in [(('o',), self.add), (('z',), self.undo), (('y',), self.redo),
                             (('s',), lambda: self.export(False)), (('e',), self.edit_selected),
                             (('r',), self.rotate), (('d',), self.duplicate)]:
            for key in keys:
                root.bind(f'<Control-{key}>', lambda event, action=action: action() or 'break')
                root.bind(f'<Control-{key.upper()}>', lambda event, action=action: action() or 'break')
        for key in ('R', 'r'):
            root.bind(f'<Control-Shift-{key}>', lambda event: self.rotate(-90) or 'break')
        root.bind('<Control-f>',lambda event:self.open_tools() or 'break')
        root.bind('<Control-F>',lambda event:self.open_tools() or 'break')
        root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.refresh()

    def build_toolbar(self):
        root = self.root
        bar = ttk.Frame(root, style='Bar.TFrame', padding=(px(root, 16), px(root, 10)))
        bar.pack(fill='x')
        tk.Label(bar, image=self.icons.logo(30), bg=ui.SURFACE).pack(side='left')
        ttk.Label(bar, text='PDF 모아', style='Title.TLabel').pack(side='left', padx=(px(root, 8), px(root, 4)))
        ttk.Label(bar, text=VERSION, style='BarMuted.TLabel').pack(side='left', padx=(0, px(root, 12)), pady=(px(root, 5), 0))
        sep = lambda: ttk.Separator(bar, orient='vertical').pack(side='left', fill='y', padx=px(root, 8), pady=px(root, 3))
        sep()
        self.add_button = icon_button(bar, 'PDF 추가', 'add', self.add, style='Accent.TButton', color='#ffffff',
                                      tip='PDF 파일 추가 (Ctrl+O)\n여러 파일은 이름순(1, 2, 10…)으로 들어갑니다.\n창으로 끌어 놓아도 됩니다.')
        self.add_button.pack(side='left')
        self.undo_button = icon_button(bar, '실행 취소', 'undo', self.undo, tip='마지막 목록 변경 되돌리기 (Ctrl+Z)')
        self.undo_button.pack(side='left', padx=(px(root, 6), 0))
        self.redo_button = icon_button(bar, '', 'redo', self.redo, style='Icon.TButton', tip='다시 실행 (Ctrl+Y)')
        self.redo_button.pack(side='left', padx=(px(root, 4), 0))
        sep()
        self.select_all_button = icon_button(bar, '전체 선택', 'select_all', self.select_all, tip='모든 페이지 선택 (Ctrl+A)')
        self.select_all_button.pack(side='left')
        self.reverse_button = icon_button(bar, '순서 뒤집기', 'reverse', self.reverse_order, tip='전체 목록을 마지막 페이지부터 거꾸로')
        self.reverse_button.pack(side='left', padx=(px(root, 6), 0))
        sep()
        self.edit_button = icon_button(bar, '글자·사진 편집', 'edit', self.edit_selected,
                                       tip='선택한 한 페이지의 글자 교체·추가·지우기, 사진 추가 (Ctrl+E)\n목록에서 페이지를 더블클릭해도 됩니다.')
        self.edit_button.pack(side='left')
        icon_button(bar, '', 'info', self.show_about, style='Icon.TButton', tip='프로그램 정보·라이선스').pack(side='right')
        self.clear_button = icon_button(bar, '목록 비우기', 'clear', self.clear, style='Danger.TButton', color=ui.DANGER,
                                        tip='추가한 페이지 목록을 모두 비우기')
        self.clear_button.pack(side='right', padx=(0, px(root, 6)))
        ttk.Separator(root, orient='horizontal').pack(fill='x')
        extra=ttk.Frame(root,padding=(16,4))
        extra.pack(fill='x')
        ttk.Button(extra,text='문서 도구 · 검색 / OCR / 압축 / 자르기 / 번호',command=self.open_tools).pack(side='left')
        ttk.Label(extra,text='작업 저장·이어 열기도 문서 도구에서 · Ctrl+F',style='Muted.TLabel').pack(side='left',padx=12)

    def open_tools(self):
        ToolsWindow(self)

    def build_footer(self):
        root = self.root
        self.status = tk.StringVar()
        status = ttk.Label(root, textvariable=self.status, style='Muted.TLabel', padding=(px(root, 16), px(root, 4)))
        status.pack(side='bottom', fill='x')
        footer = ttk.Frame(root, style='Bar.TFrame', padding=(px(root, 16), px(root, 10)))
        footer.pack(side='bottom', fill='x')
        ttk.Separator(root, orient='horizontal').pack(side='bottom', fill='x')
        ttk.Label(footer, text='순서 번호로 선택', style='Bar.TLabel').pack(side='left')
        self.range_text = ttk.Entry(footer, width=18)
        self.range_text.pack(side='left', padx=px(root, 8))
        self.range_text.bind('<Return>', lambda event: self.select_range())
        self.range_button = ttk.Button(footer, text='선택', command=self.select_range, style='Tool.TButton')
        self.range_button.pack(side='left')
        ttk.Label(footer, text='예: 1-3, 5, 8', style='BarMuted.TLabel').pack(side='left', padx=px(root, 10))
        self.save_button = icon_button(footer, '전체 합쳐서 저장', 'save', lambda: self.export(False),
                                       style='Accent.TButton', color='#ffffff', tip='목록 순서대로 PDF 하나로 저장 (Ctrl+S)')
        self.save_button.pack(side='right')
        self.save_selected_button = icon_button(footer, '선택 페이지만 저장', 'save_selected', lambda: self.export(True),
                                                tip='선택한 페이지만 목록 순서대로 PDF 하나로 저장')
        self.save_selected_button.pack(side='right', padx=px(root, 6))
        self.split_button = icon_button(footer, '나눠서 저장', 'split', self.split,
                                        tip='전체 또는 선택한 페이지를\n한 쪽씩, N쪽씩 또는 범위별로 나눠 저장')
        self.split_button.pack(side='right')
        self.bookmarks = tk.BooleanVar(value=self.settings.get('bookmarks') is True)
        bookmarks = ttk.Checkbutton(footer, text='파일별 책갈피', variable=self.bookmarks, style='Bar.TCheckbutton',
                                    command=lambda: self.settings.set('bookmarks', self.bookmarks.get()))
        bookmarks.pack(side='right', padx=(0, px(root, 12)))
        ui.Tooltip(bookmarks, '저장할 때 원본 파일이 시작되는 쪽마다\n파일 이름으로 책갈피(목차)를 만듭니다.')

    def build_empty_state(self, parent):
        frame = tk.Frame(parent, bg=ui.SURFACE)
        tk.Label(frame, image=self.icons.get('add', 40, '#94a3b8'), bg=ui.SURFACE).pack()
        tk.Label(frame, text='PDF 파일을 여기에 끌어 놓거나', bg=ui.SURFACE, fg=ui.MUTED,
                 font=(ui.FONT, 10)).pack(pady=(px(parent, 8), 0))
        tk.Label(frame, text='위의 [PDF 추가]를 누르세요', bg=ui.SURFACE, fg=ui.MUTED, font=(ui.FONT, 10)).pack()
        for child in [frame, *frame.winfo_children()]:
            child.bind('<Button-1>', lambda event: self.add())
            child.configure(cursor='hand2')
        return frame

    def restore_window(self):
        """Reuse the last window size and position when they still fit the screen."""
        match = re.fullmatch(r'(\d+)x(\d+)\+(-?\d+)\+(-?\d+)', str(self.settings.get('geometry', '')))
        if match:
            w, h, x, y = map(int, match.groups())
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            if 600 <= w <= sw and 400 <= h <= sh and -20 <= x <= sw - 200 and -20 <= y <= sh - 200:
                self.root.geometry(f'{w}x{h}+{x}+{y}')
        if self.settings.get('zoomed') is True:
            self.root.state('zoomed')

    def remember_window(self):
        try:
            zoomed = self.root.state() == 'zoomed'
            self.settings.set('zoomed', zoomed)
            if not zoomed:
                self.settings.set('geometry', self.root.geometry())
            self.settings.set('list_width', round(self.panes.sashpos(0) / ui.ui_scale(self.root)))
        except tk.TclError:
            pass
        self.settings.save()

    def show_about(self):
        messagebox.showinfo(f'PDF 모아 {VERSION}', 'AGPL-3.0-only 공개 소스 프로그램\n보증 없이 제공됩니다. 라이선스 조건에 따라 수정·재배포할 수 있습니다.\n\n소스: https://github.com/Winsh-PEN/pdf-moa\n라이선스: 배포 폴더의 LICENSE 및 licenses\n사용한 편집 엔진: PyMuPDF / MuPDF')

    @contextmanager
    def busy(self, message=None):
        """Watch cursor (and a status message) while a long step runs."""
        self.root.configure(cursor='watch')
        if message:
            self.status.set(message)
        self.root.update_idletasks()
        try:
            yield
        finally:
            self.root.configure(cursor='')
            self.update_status()

    def edit_selected(self):
        indices = self.selected()
        if len(indices) != 1:
            messagebox.showinfo('페이지 선택', '편집할 페이지 하나를 선택하세요.')
            return
        index = indices[0]
        original = self.entries[index]
        def apply(data):
            replacement = updated_entry(original, data)
            self.snapshot()
            self.entries[index] = replacement
            self.refresh([index])
            self.tree.focus_set()
        try:
            PageEditor(self.root, original, apply)
        except Exception as error:
            messagebox.showerror('편집 창 열기 실패',str(error))

    def selected(self):
        return sorted(int(x) for x in self.tree.selection())

    def select_all(self, event=None):
        self.tree.selection_set(self.tree.get_children())
        return 'break'

    def select_edge(self, index):
        children = self.tree.get_children()
        if children:
            item = children[index]
            self.tree.selection_set(item)
            self.tree.focus(item)
            self.tree.see(item)
        return 'break'

    def snapshot(self):
        self.history.append([dict(e) for e in self.entries])
        self.history = self.history[-20:]
        self.future.clear()

    def protected_paths(self):
        """Every source file in the list and in undo/redo, never to be overwritten."""
        return {e['path'] for pages in [self.entries, *self.history, *self.future] for e in pages if e.get('path')}

    def refresh(self, selection=()):
        self.tree.delete(*self.tree.get_children())
        self.thumb_rows = {}
        for i, e in enumerate(self.entries):
            name = display_name(e) + (' · 편집됨' if 'source_page' in e else '')
            rotation = f"{e['rotation']}°" if e['rotation'] else ''
            tags = ('edited',) if 'source_page' in e else ('blank',) if not e.get('path') else ()
            page = e.get('source_page', e['page']) + 1 if e.get('path') else ''
            self.tree.insert('', 'end', iid=str(i), image=self.thumbnails.image(e), tags=tags,
                             values=(i+1, name, page, rotation))
            self.thumb_rows.setdefault(entry_key(e), []).append(str(i))
        self.tree.selection_set([str(i) for i in selection])
        if selection:
            self.tree.see(str(selection[0]))
            self.tree.focus(str(selection[0]))
        if self.entries:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.42, anchor='center')
        self.selection_changed()
        self.update_status()
        self.request_thumbnails()

    def apply_thumb_size(self):
        width, height = (px(self.root, v) for v in THUMB_SIZES[self.thumb_size.get()])
        ttk.Style(self.root).configure('Pages.Treeview', rowheight=height + px(self.root, 8))
        self.tree.column('#0', width=width + px(self.root, 22), minwidth=width + px(self.root, 22))
        if self.thumbnails:
            self.thumbnails.close()
        self.thumbnails = Thumbnails(self.tree, (width, height), self.thumbnail_ready)

    def change_thumb_size(self):
        self.settings.set('thumb_size', self.thumb_size.get())
        self.apply_thumb_size()
        self.refresh(self.selected())

    def request_thumbnails(self):
        if self.thumb_job is None:
            self.thumb_job = self.root.after_idle(self.queue_thumbnails)

    def cancel_thumbnail_job(self, event=None):
        if self.thumb_job is not None and event.widget is self.tree:
            self.root.after_cancel(self.thumb_job)
            self.thumb_job = None

    def queue_thumbnails(self):
        self.thumb_job = None
        if not self.entries:
            self.thumbnails.request([])
            return
        first = int(self.tree.yview()[0] * len(self.entries))
        order = list(range(first, len(self.entries))) + list(range(first))
        self.thumbnails.request([self.entries[i] for i in order])

    def thumbnail_ready(self, key, image):
        for iid in self.thumb_rows.get(key, []):
            if self.tree.exists(iid):
                self.tree.item(iid, image=image)

    def selection_changed(self, event=None):
        self.update_status()
        selected = self.selected()
        focused = self.tree.focus()
        index = int(focused) if focused and int(focused) in selected else (selected[0] if selected else None)
        self.preview.show(self.entries[index] if index is not None else None, index or 0, len(self.entries))

    def update_status(self):
        files = len({e['path'] for e in self.entries if e.get('path')})
        self.status.set(f"총 {len(self.entries)}페이지 (파일 {files}개) · 선택 {len(self.tree.selection())}페이지" if self.entries else 'PDF 추가 버튼을 누르거나 PDF 파일을 창에 끌어 놓아 시작하세요.')
        self.update_actions()

    def update_actions(self):
        count, chosen = len(self.entries), len(self.tree.selection())
        rules = [(self.list_buttons, chosen > 0), ([self.save_selected_button], chosen > 0),
                 ([self.edit_button], chosen == 1), ([self.undo_button], bool(self.history)),
                 ([self.redo_button], bool(self.future)),
                 ([self.select_all_button, self.clear_button, self.save_button, self.split_button, self.range_button], count > 0),
                 ([self.reverse_button], count > 1)]
        for buttons, enabled in rules:
            for button in buttons:
                button.state(['!disabled'] if enabled else ['disabled'])

    def popup_menu(self, event):
        """Right-click (or Shift+F10 / menu key) menu for the selected pages."""
        if getattr(event, 'num', None) == 3:
            row = self.tree.identify_row(event.y)
            if row and row not in self.tree.selection():
                self.tree.selection_set(row)
                self.tree.focus(row)
            x, y = event.x_root, event.y_root
        else:
            item = self.tree.focus()
            box = self.tree.bbox(item) if item else None
            x = self.tree.winfo_rootx() + px(self.root, 40)
            y = self.tree.winfo_rooty() + (box[1] + box[3] if box else px(self.root, 40))
        self.tree.focus_set()
        # Replace the previous menu here rather than right after the popup, so a
        # chosen command is never lost by destroying the menu too early.
        if getattr(self, 'menu', None) is not None:
            self.menu.destroy()
        self.menu = menu = self.context_menu()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()
        return 'break'

    def context_menu(self):
        chosen = self.selected()
        some, one = bool(chosen), len(chosen) == 1
        source = one and bool(self.entries[chosen[0]].get('path'))
        menu = tk.Menu(self.root, tearoff=0, font=(ui.FONT, 10))
        def item(label, icon, command, enabled=True, accelerator=''):
            menu.add_command(label=label, image=self.icons.get(icon, 16), compound='left', command=command,
                             accelerator=accelerator, state='normal' if enabled else 'disabled')
        item(' 글자·사진 편집…', 'edit', self.edit_selected, one, 'Ctrl+E')
        menu.add_separator()
        item(' 맨 위로', 'top', lambda: self.move_to('top'), some, 'Alt+Home')
        item(' 위로', 'up', lambda: self.move(-1), some, 'Alt+↑')
        item(' 아래로', 'down', lambda: self.move(1), some, 'Alt+↓')
        item(' 맨 아래로', 'bottom', lambda: self.move_to('bottom'), some, 'Alt+End')
        menu.add_separator()
        item(' 오른쪽으로 90° 회전', 'rotate', lambda: self.rotate(90), some, 'Ctrl+R')
        item(' 왼쪽으로 90° 회전', 'rotate_left', lambda: self.rotate(-90), some, 'Ctrl+Shift+R')
        item(' 180° 회전', 'rotate', lambda: self.rotate(180), some)
        menu.add_separator()
        item(' 복제', 'duplicate', self.duplicate, some, 'Ctrl+D')
        item(' 뒤에 빈 페이지 넣기', 'blank', self.insert_blank, True)
        item(' 뒤에 PDF 끼워 넣기…', 'insert', self.insert_files, True)
        menu.add_separator()
        item(' 선택 페이지만 저장…', 'save_selected', lambda: self.export(True), some)
        item(' 선택 페이지 나눠서 저장…', 'split', lambda: self.split(prefer_selected=True), some)
        item(' 이미지로 저장 (PNG)…', 'image', self.export_images, some)
        item(' 원본 PDF 열기', 'open', self.open_source, source)
        menu.add_separator()
        item(' 목록에서 빼기', 'trash', self.remove, some, 'Delete')
        return menu

    def ask_open(self, title='PDF 추가'):
        paths = filedialog.askopenfilenames(parent=self.root, title=title, filetypes=[('PDF 파일', '*.pdf')],
                                            initialdir=self.settings.folder('open_dir'))
        if paths:
            self.settings.set('open_dir', str(Path(paths[0]).parent))
        return paths

    def add(self):
        self.add_paths(self.ask_open())

    def insert_files(self):
        indices = self.selected()
        position = indices[-1] + 1 if indices else len(self.entries)
        paths = self.ask_open('선택한 페이지 뒤에 끼워 넣을 PDF')
        if paths:
            self.add_paths(paths, position)

    def drop_target(self, x_root, y_root):
        """(list index, line y) for files dropped at a screen point; (None, None) appends."""
        x, y = x_root - self.tree.winfo_rootx(), y_root - self.tree.winfo_rooty()
        if not self.entries or not (0 <= x <= self.tree.winfo_width() and 0 <= y <= self.tree.winfo_height()):
            return None, None
        return self.insertion_at(y)

    def drop_position(self, event):
        """While files are dragged over the window: show where they will go.

        Runs during a native drag, so it must never raise (an error dialog
        would interrupt the drag); the drop itself still works without it.
        """
        try:
            self.show_drop_position(event)
        except Exception:
            self.drop_line.place_forget()
        return COPY

    def show_drop_position(self, event):
        y = event.y_root - self.tree.winfo_rooty()
        if self.entries and 0 <= event.x_root - self.tree.winfo_rootx() <= self.tree.winfo_width():
            if 0 <= y < px(self.root, 40):
                self.tree.yview_scroll(-1, 'units')
            elif self.tree.winfo_height() - px(self.root, 25) < y <= self.tree.winfo_height():
                self.tree.yview_scroll(1, 'units')
        target, line_y = self.drop_target(event.x_root, event.y_root)
        if target is None:
            self.drop_line.place_forget()
            self.status.set('놓으면 목록 끝에 추가합니다.' if self.entries else '놓으면 PDF를 추가합니다.')
        else:
            self.drop_line.place(x=0, y=line_y-1, relwidth=1)
            self.status.set(f'놓으면 파란 선 자리({target + 1}번째)에 끼워 넣습니다.')

    def drop_leave(self, event=None):
        self.drop_line.place_forget()
        self.update_status()

    def drop_files(self, event):
        target, _ = self.drop_target(event.x_root, event.y_root)
        self.drop_leave()
        paths = self.root.tk.splitlist(event.data)
        valid = [p for p in paths if Path(p).is_file() and Path(p).suffix.lower() == '.pdf']
        if valid:
            # Finish the native drop before showing any password or error dialog.
            self.root.after_idle(lambda: self.add_paths(valid, target))
        else:
            self.root.after_idle(lambda: messagebox.showinfo('PDF 파일 추가', 'PDF 파일을 끌어 놓아 주세요.'))
        return COPY

    def drag_press(self, event):
        # The custom drag handler stops the default Treeview click binding,
        # so explicitly give the list keyboard focus before returning 'break'.
        self.tree.focus_set()
        self.cancel_drag()
        row = self.tree.identify_row(event.y)
        if not row or self.tree.identify_region(event.x, event.y) not in ('cell', 'tree') or event.state & 5:
            return
        self.drag_start = (event.x, event.y)
        self.press_row = row
        if row not in self.tree.selection():
            self.tree.selection_set(row)
        self.tree.focus(row)
        self.selection_changed()
        self.drag_indices = self.selected()
        return 'break'

    def insertion_at(self, y):
        row = self.tree.identify_row(y)
        if row:
            box = self.tree.bbox(row)
            after = y >= box[1] + box[3] / 2
            return int(row) + int(after), box[1] + (box[3] if after else 0)
        children = self.tree.get_children()
        visible = [(int(r), self.tree.bbox(r)) for r in children if self.tree.bbox(r)]
        if visible:
            if y < visible[0][1][1]:
                return visible[0][0], visible[0][1][1]
            last, box = visible[-1]
            return last + 1, box[1] + box[3]
        return len(self.entries), 25

    def drag_motion(self, event):
        if not self.drag_start:
            return
        if not self.drag_active and max(abs(event.x-self.drag_start[0]), abs(event.y-self.drag_start[1])) < px(self.root, 5):
            return 'break'
        self.drag_active = True
        self.tree.configure(cursor='fleur')
        if event.y < px(self.root, 40):
            self.tree.yview_scroll(-1, 'units')
        elif event.y > self.tree.winfo_height() - px(self.root, 25):
            self.tree.yview_scroll(1, 'units')
        _, line_y = self.insertion_at(event.y)
        self.drop_line.place(x=0, y=line_y-1, relwidth=1)
        self.status.set('파란 선 위치에 놓으면 선택한 페이지가 함께 이동합니다. (Esc: 취소)')
        return 'break'

    def drag_release(self, event):
        if not self.drag_start:
            return
        indices = self.drag_indices[:]
        if self.drag_active and 0 <= event.x <= self.tree.winfo_width() and 0 <= event.y <= self.tree.winfo_height():
            target, _ = self.insertion_at(event.y)
            remaining = [i for i in range(len(self.entries)) if i not in indices]
            position = target - sum(i < target for i in indices)
            order = remaining[:position] + indices + remaining[position:]
            if order != list(range(len(self.entries))):
                self.snapshot()
                self.entries = [self.entries[i] for i in order]
                self.refresh(list(range(position, position + len(indices))))
        elif not self.drag_active and self.press_row and len(indices) > 1:
            # A plain click inside a multi-selection selects just that page.
            self.tree.selection_set(self.press_row)
            self.tree.focus(self.press_row)
        self.cancel_drag()
        return 'break'

    def cancel_drag(self, event=None):
        self.drag_start = None
        self.drag_indices = []
        self.drag_active = False
        self.press_row = None
        self.drop_line.place_forget()
        self.tree.configure(cursor='')
        self.update_status()

    def open_pdf(self, path):
        """Open path, asking for the password up to three times. None when skipped."""
        name = Path(path).name
        with self.busy(f'{name} 여는 중…'):
            try:
                return load_pdf(path)
            except ValueError as error:
                if str(error) != 'PASSWORD_REQUIRED':
                    raise
        message = f'{name}\nPDF 암호를 입력하세요.'
        for attempt in range(1, 4):
            password = ui.ask_password(self.root, '암호 입력', message)
            if password is None:
                return None
            with self.busy(f'{name} 여는 중…'):
                try:
                    return load_pdf(path, password)
                except ValueError as error:
                    if str(error) != 'PASSWORD_REQUIRED':
                        raise
            message = f'{name}\n암호가 맞지 않습니다. 다시 입력하세요. ({attempt + 1}/3)'
        raise ValueError('암호가 3번 맞지 않아 이 파일은 추가하지 않았습니다.')

    def add_paths(self, paths, position=None):
        new, failed = [], []
        for path in sorted(paths, key=natural_key):
            try:
                reader = self.open_pdf(path)
            except Exception as error:
                failed.append(f'· {Path(path).name}\n  {error}')
                continue
            if reader is None:
                continue
            if not reader.pages:
                failed.append(f'· {Path(path).name}\n  페이지가 없는 PDF입니다.')
                continue
            new.extend(dict(path=path, reader=reader, page=p, rotation=0) for p in range(len(reader.pages)))
        if failed:
            more = f'\n외 {len(failed) - 8}개' if len(failed) > 8 else ''
            messagebox.showerror('파일을 열 수 없습니다', '\n'.join(failed[:8]) + more + '\n\n암호나 PDF 파일을 확인하세요.')
        if new:
            position = len(self.entries) if position is None else position
            self.snapshot()
            self.entries[position:position] = new
            self.refresh([position])
            self.tree.focus_set()

    def move(self, direction):
        selected = set(self.selected())
        if not selected:
            return
        order = list(range(len(self.entries)))
        for i in sorted(selected, reverse=direction > 0):
            target = i + direction
            if 0 <= target < len(order) and target not in selected:
                order[i], order[target] = order[target], order[i]
                selected.remove(i)
                selected.add(target)
        if order == list(range(len(self.entries))):
            return  # already at the edge: nothing to undo
        self.snapshot()
        self.entries = [self.entries[i] for i in order]
        self.refresh(sorted(selected))

    def move_to(self, edge):
        indices = self.selected()
        if not indices:
            return
        chosen = set(indices)
        picked = [self.entries[i] for i in indices]
        rest = [e for i, e in enumerate(self.entries) if i not in chosen]
        entries = picked + rest if edge == 'top' else rest + picked
        if [id(e) for e in entries] == [id(e) for e in self.entries]:
            return
        self.snapshot()
        self.entries = entries
        start = 0 if edge == 'top' else len(rest)
        self.refresh(list(range(start, start + len(picked))))

    def reverse_order(self):
        if len(self.entries) < 2:
            return
        selected = self.selected()
        self.snapshot()
        self.entries.reverse()
        self.refresh(sorted(len(self.entries) - 1 - i for i in selected))

    def rotate(self, angle=90):
        indices = self.selected()
        if indices:
            self.snapshot()
            for i in indices:
                self.entries[i]['rotation'] = (self.entries[i]['rotation'] + angle) % 360
            self.refresh(indices)

    def duplicate(self):
        indices = self.selected()
        if not indices:
            return
        copies = [dict(self.entries[i]) for i in indices]
        position = indices[-1] + 1
        self.snapshot()
        self.entries[position:position] = copies
        self.refresh(list(range(position, position + len(copies))))

    def insert_blank(self):
        """An empty page after the selection, the same size as the selected page (A4 otherwise)."""
        indices = self.selected()
        position = indices[-1] + 1 if indices else len(self.entries)
        size = (595.28, 841.89)
        if indices:
            entry = self.entries[indices[-1]]
            page = entry['reader'].pages[entry['page']]
            size = (float(page.mediabox.width), float(page.mediabox.height))
            if (page.rotation + entry['rotation']) % 180:
                size = size[::-1]
        self.snapshot()
        self.entries.insert(position, dict(path='', reader=blank_reader(*size), page=0, rotation=0))
        self.refresh([position])

    def remove(self):
        indices = self.selected()
        if indices:
            self.snapshot()
            self.entries = [e for i,e in enumerate(self.entries) if i not in indices]
            self.refresh([min(indices[0], len(self.entries) - 1)] if self.entries else ())

    def clear(self):
        if self.entries and messagebox.askyesno('목록 비우기', '추가한 페이지 목록을 비울까요?\n실행 취소로 되돌릴 수 있습니다.'):
            self.snapshot()
            self.entries = []
            self.refresh()

    def undo(self):
        if self.history:
            self.future.append([dict(e) for e in self.entries])
            self.entries = self.history.pop()
            self.refresh()

    def redo(self):
        if self.future:
            self.history.append([dict(e) for e in self.entries])
            self.entries = self.future.pop()
            self.refresh()

    def select_range(self):
        try:
            indices = parse_pages(self.range_text.get(), len(self.entries))
            self.tree.selection_set([str(i) for i in indices])
            self.tree.see(str(indices[0]))
            self.tree.focus_set()
        except ValueError as error:
            messagebox.showerror('페이지 범위 확인', str(error))

    def open_source(self):
        indices = self.selected()
        if not indices:
            return
        path = self.entries[indices[0]].get('path')
        if not path:
            messagebox.showinfo('원본 열기', '빈 페이지는 원본 파일이 없습니다.')
        elif not Path(path).exists():
            messagebox.showerror('원본 열기', f'원본 파일을 찾을 수 없습니다. 옮겨졌거나 지워졌을 수 있습니다.\n{path}')
        else:
            os.startfile(path)

    def state_signature(self):
        return tuple(entry_key(e) for e in self.entries)

    def first_source(self, entries):
        return next((e['path'] for e in entries if e.get('path')), None)

    def default_folder(self, entries):
        source = self.first_source(entries)
        return self.settings.folder('save_dir') or (str(Path(source).parent) if source else None)

    def saved(self, location, message):
        self.saved_state = self.state_signature()
        self.done(location, message)

    def done(self, location, message):
        folder = Path(location).is_dir()
        choices = ([] if folder else [('file', '파일 열기', False)]) + [('folder', '폴더 열기', False), ('close', '닫기', True)]
        choice = ui.ChoiceDialog(self.root, '저장 완료', message, choices, default='close').result
        if choice == 'file':
            os.startfile(location)
        elif choice == 'folder':
            if folder:
                os.startfile(location)
            else:
                subprocess.Popen(['explorer', '/select,', str(Path(location))])

    def export(self, selected_only):
        entries = [self.entries[i] for i in self.selected()] if selected_only else self.entries
        if not entries:
            messagebox.showinfo('페이지 선택', '저장할 페이지를 추가하거나 선택하세요.')
            return
        source = self.first_source(entries)
        stem = Path(source).stem if source else '빈페이지'
        several = len({e['path'] for e in entries if e.get('path')}) > 1
        name = f'{stem}_선택.pdf' if selected_only else f'{stem}_합침.pdf' if several else f'{stem}_정리.pdf'
        dest = filedialog.asksaveasfilename(parent=self.root, title='선택 페이지만 저장' if selected_only else '전체 합쳐서 저장',
                                            defaultextension='.pdf', initialfile=name, initialdir=self.default_folder(entries),
                                            filetypes=[('PDF 파일','*.pdf')])
        if not dest:
            return
        self.settings.set('save_dir', str(Path(dest).parent))
        try:
            with self.busy('저장하는 중…'):
                save_pdf(entries, dest, protected=self.protected_paths(), bookmarks=self.bookmarks.get())
        except Exception as error:
            messagebox.showerror('저장 실패', str(error))
            return
        self.saved(dest, f'{len(entries)}페이지를 저장했습니다.\n{dest}')

    def split(self, prefer_selected=False):
        if not self.entries:
            messagebox.showinfo('PDF 추가', '먼저 PDF를 추가하세요.')
            return
        chosen = self.selected()
        choice = SplitDialog(self.root, len(self.entries), len(chosen), prefer_selected).result
        if not choice:
            return
        scope, mode, value = choice
        indices = chosen if scope == 'selected' and chosen else list(range(len(self.entries)))
        groups = split_groups(indices, mode, value, len(self.entries))
        folder = filedialog.askdirectory(parent=self.root, title='나눈 PDF를 저장할 폴더 선택',
                                         initialdir=self.default_folder([self.entries[i] for i in indices]))
        if not folder:
            return
        self.settings.set('save_dir', folder)
        output = new_folder(folder)
        protected = self.protected_paths()
        completed = 0
        try:
            with self.busy():
                for number, group in enumerate(groups, 1):
                    self.status.set(f'나눠서 저장하는 중… {number}/{len(groups)}')
                    self.root.update_idletasks()
                    pages = [self.entries[i] for i in group]
                    save_pdf(pages, output / group_name(number, pages), protected, bookmarks=self.bookmarks.get())
                    completed += 1
        except Exception as error:
            messagebox.showerror('나눠서 저장 실패', f'{completed}개 저장 후 중단되었습니다.\n{output}\n{error}')
            return
        self.saved(output, f'{completed}개의 PDF를 저장했습니다.\n{output}')

    def export_images(self):
        """Selected pages as PNG files, e.g. to paste a drawing page into a report or a chat."""
        pages = [self.entries[i] for i in self.selected()]
        if not pages:
            messagebox.showinfo('페이지 선택', '이미지로 저장할 페이지를 선택하세요.')
            return
        dpi = ui.ChoiceDialog(self.root, '이미지로 저장', f'선택한 {len(pages)}쪽을 PNG 이미지로 저장합니다.\n해상도를 고르세요. 아주 큰 도면은 자동으로 낮춥니다.',
                              [(150, '보통 (150 dpi)', False), (300, '선명하게 (300 dpi)', True)], default=300).result
        if not dpi:
            return
        names = [group_name(n, [entry])[:-4] + '.png' for n, entry in enumerate(pages, 1)]
        if len(pages) == 1:
            dest = filedialog.asksaveasfilename(parent=self.root, title='이미지로 저장', defaultextension='.png',
                                                initialfile=names[0][4:], initialdir=self.default_folder(pages),
                                                filetypes=[('PNG 이미지', '*.png')])
            if not dest:
                return
            location, targets = dest, [Path(dest)]
        else:
            folder = filedialog.askdirectory(parent=self.root, title='이미지를 저장할 폴더 선택', initialdir=self.default_folder(pages))
            if not folder:
                return
            location = new_folder(folder, 'PDF_이미지')
            targets = [location / name for name in names]
        # The file's folder for one page, the chosen folder (parent of the new one) otherwise.
        self.settings.set('save_dir', str(Path(location).parent))
        completed = 0
        try:
            with self.busy():
                for entry, target in zip(pages, targets):
                    self.status.set(f'이미지로 저장하는 중… {completed + 1}/{len(pages)}')
                    self.root.update_idletasks()
                    target.write_bytes(page_png(entry, dpi))
                    completed += 1
        except Exception as error:
            messagebox.showerror('이미지 저장 실패', f'{completed}개 저장 후 중단되었습니다.\n{location}\n{error}')
            return
        self.done(location, f'{completed}개의 PNG 이미지를 저장했습니다.\n{location}')

    def on_close(self):
        if self.entries and self.state_signature() != self.saved_state:
            if not messagebox.askyesno('종료', '저장하지 않은 페이지 목록이 있습니다.\n편집·정리한 내용은 종료하면 사라집니다.\n\n저장하지 않고 종료할까요?', icon='warning'):
                return
        self.remember_window()
        self.root.destroy()


def report_error(exc, value, tb):
    # In the windowed exe there is no console, so show unexpected errors.
    traceback.print_exception(exc, value, tb)
    messagebox.showerror('오류', f'예상하지 못한 오류가 발생했습니다.\n{value}')


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    ui.enable_dpi_awareness()
    root = TkinterDnD.Tk()
    root.report_callback_exception = report_error
    App(root)
    # Read the installed font list early so the first text dialog opens quickly.
    root.after(1500, lambda: threading.Thread(target=installed_fonts, daemon=True).start())
    root.mainloop()
