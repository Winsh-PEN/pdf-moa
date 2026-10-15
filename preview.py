# SPDX-License-Identifier: AGPL-3.0-only
import queue
import tkinter as tk
from tkinter import ttk
from PIL import ImageTk
from thumbs import PREVIEW, entry_key, entry_source, worker
import ui
from ui import px, icon_button


class Preview(ttk.Frame):
    """Shows one page. Rendering runs on the background worker (see thumbs.py)."""

    def __init__(self, parent):
        super().__init__(parent, padding=(px(parent, 14), 0, 0, 0))
        self.source = None
        self.key = None
        self.photo = None
        self.pending = None
        self.poll_job = None
        self.loading_job = None
        self.zoom = None
        self.serial = 0  # number of the newest render request; older ones are skipped
        self.expect = None  # serial we are waiting for, None when idle
        self.results = queue.Queue()
        bar = ttk.Frame(self)
        bar.pack(fill='x', pady=(0, px(self, 6)))
        ttk.Label(bar, text='미리보기', style='Section.TLabel').pack(side='left')
        icon_button(bar, '화면 맞춤', 'fit', self.fit, tip='페이지 전체가 보이게 맞추기').pack(side='right')
        icon_button(bar, '', 'zoom_in', lambda: self.change_zoom(1.25), style='Icon.TButton',
                    tip='확대 (Ctrl+휠 위)').pack(side='right', padx=(px(self, 4), px(self, 8)))
        self.scale_label = ttk.Label(bar, text='', width=5, anchor='center', style='Muted.TLabel')
        self.scale_label.pack(side='right')
        icon_button(bar, '', 'zoom_out', lambda: self.change_zoom(0.8), style='Icon.TButton',
                    tip='축소 (Ctrl+휠 아래)').pack(side='right', padx=(0, px(self, 4)))
        holder = ttk.Frame(self, style='Card.TFrame', padding=1)
        holder.pack(fill='both', expand=True)
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(holder, bg=ui.CANVAS, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        sy = ttk.Scrollbar(holder, orient='vertical', command=self.canvas.yview)
        sx = ttk.Scrollbar(holder, orient='horizontal', command=self.canvas.xview)
        sy.grid(row=0, column=1, sticky='ns')
        sx.grid(row=1, column=0, sticky='ew')
        self.canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.caption = ttk.Label(self, text='목록에서 페이지를 선택하세요.', style='Muted.TLabel', wraplength=px(self, 600))
        self.caption.pack(fill='x', pady=(px(self, 6), 0))
        self.canvas.bind('<Configure>', lambda e: self.schedule())
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.canvas.bind('<Shift-MouseWheel>', lambda e: self.canvas.xview_scroll(-1 if e.delta > 0 else 1, 'units') or 'break')
        self.canvas.bind('<ButtonPress-1>', self.grab_start)
        self.canvas.bind('<B1-Motion>', lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind('<ButtonRelease-1>', lambda e: self.canvas.configure(cursor=''))
        self.bind('<Destroy>', self.cleanup)

    def grab_start(self, event):
        self.canvas.scan_mark(event.x, event.y)
        if self.zoom is not None:
            self.canvas.configure(cursor='fleur')

    def cleanup(self, event):
        if event.widget == self:
            for job in (self.pending, self.poll_job, self.loading_job):
                if job:
                    self.after_cancel(job)
            self.pending = self.poll_job = self.loading_job = None

    def show(self, entry=None, index=0, total=0):
        key = entry_key(entry) if entry else None
        if entry:
            if entry.get('path'):
                name = entry['path'].replace(chr(92), '/').split('/')[-1]
                where = f"{name} · 원본 {entry.get('source_page', entry['page'])+1}페이지"
            else:
                where = '빈 페이지'
            edited = ' · 편집됨' if 'source_page' in entry else ''
            self.caption.configure(text=f"{index+1} / {total} · {where}{edited}")
        else:
            self.caption.configure(text='목록에서 페이지를 선택하세요.')
        if key == self.key:
            return
        self.key = key
        self.source = None
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        if entry:
            try:
                self.source = entry_source(entry)
            except Exception as error:
                self.caption.configure(text=f'미리보기를 표시할 수 없습니다: {error}')
        self.schedule()

    def fit(self):
        self.zoom = None
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.schedule()

    def change_zoom(self, factor):
        self.zoom = max(0.1, min(5, getattr(self, 'actual_scale', 1) * factor))
        self.schedule()

    def wheel(self, event):
        if event.state & 4:
            self.change_zoom(1.15 if event.delta > 0 else 1/1.15)
        else:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'

    def schedule(self):
        if self.pending:
            self.after_cancel(self.pending)
        self.pending = self.after(100, self.render)

    def render(self):
        """Ask the worker for the current page; the result arrives in poll()."""
        self.pending = None
        self.serial += 1
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        if self.loading_job:
            self.after_cancel(self.loading_job)
            self.loading_job = None
        if not self.source:
            self.expect = None
            self.photo = None
            self.canvas.delete('all')
            self.scale_label.configure(text='')
            self.canvas.create_text(width/2, height/2, text='PDF를 추가하고 페이지를 선택하세요',
                                    fill='#e5e7eb', font=(ui.FONT, 13))
            self.canvas.configure(scrollregion=(0, 0, width, height))
            return
        margin = px(self, 16)
        self.expect = self.serial
        worker().submit(PREVIEW, self.source, width - 2*margin, height - 2*margin, self.zoom,
                        self.results, self.serial, wanted=lambda serial: serial == self.serial)
        # Only show "drawing" for slow pages, so quick pages do not flicker.
        self.loading_job = self.after(300, self.show_loading)
        if self.poll_job is None:
            self.poll_job = self.after(30, self.poll)

    def show_loading(self):
        self.loading_job = None
        self.canvas.delete('loading')
        x, y = self.canvas.canvasx(0) + px(self, 12), self.canvas.canvasy(0) + px(self, 10)
        self.canvas.create_text(x, y, text='그리는 중…', anchor='nw', fill='#ffffff',
                                font=(ui.FONT, 10, 'bold'), tags='loading')

    def poll(self):
        self.poll_job = None
        newest = None
        while True:
            try:
                result = self.results.get_nowait()
            except queue.Empty:
                break
            if result[0] == self.expect:
                newest = result
        if newest is None:
            if self.expect is not None:
                self.poll_job = self.after(30, self.poll)
            return
        self.expect = None
        if self.loading_job:
            self.after_cancel(self.loading_job)
            self.loading_job = None
        _, image, scale = newest
        self.draw(image, scale)

    def draw(self, image, scale):
        self.canvas.delete('all')
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        if image is None:
            self.photo = None
            self.scale_label.configure(text='')
            self.caption.configure(text='미리보기를 표시할 수 없습니다. 원본 열기로 확인하세요.')
            return
        margin = px(self, 16)
        self.actual_scale = scale
        self.photo = ImageTk.PhotoImage(image, master=self)
        iw, ih = self.photo.width(), self.photo.height()
        x, y = max(margin, (width-iw)//2), max(margin, (height-ih)//2)
        shadow = px(self, 3)
        self.canvas.create_rectangle(x+shadow, y+shadow, x+iw+shadow, y+ih+shadow, fill='#363c45', outline='')
        self.canvas.create_image(x, y, anchor='nw', image=self.photo)
        self.canvas.configure(scrollregion=(0, 0, max(width, iw+2*margin), max(height, ih+2*margin)))
        self.scale_label.configure(text=f'{scale*100:.0f}%')
