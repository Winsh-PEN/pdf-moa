# SPDX-License-Identifier: AGPL-3.0-only
from io import BytesIO
import math
import tkinter as tk
from tkinter import ttk
from PIL import ImageTk
from pypdf import PdfWriter
import pypdfium2 as pdfium


class Preview(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=(12, 0, 0, 0))
        self.document = None
        self.key = None
        self.photo = None
        self.pending = None
        self.zoom = None
        bar = ttk.Frame(self)
        bar.pack(fill='x', pady=(0, 8))
        ttk.Label(bar, text='PDF 미리보기', font=('맑은 고딕', 12, 'bold')).pack(side='left')
        ttk.Button(bar, text='화면 맞춤', command=self.fit).pack(side='right')
        ttk.Button(bar, text='＋', width=3, command=lambda:self.change_zoom(1.25)).pack(side='right', padx=4)
        ttk.Button(bar, text='－', width=3, command=lambda:self.change_zoom(0.8)).pack(side='right')
        self.scale_label = ttk.Label(bar, text='')
        self.scale_label.pack(side='right', padx=8)
        holder = ttk.Frame(self)
        holder.pack(fill='both', expand=True)
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(holder, bg='#414a57', highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        sy = ttk.Scrollbar(holder, orient='vertical', command=self.canvas.yview)
        sx = ttk.Scrollbar(holder, orient='horizontal', command=self.canvas.xview)
        sy.grid(row=0, column=1, sticky='ns')
        sx.grid(row=1, column=0, sticky='ew')
        self.canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.caption = ttk.Label(self, text='목록에서 페이지를 선택하세요.', wraplength=600)
        self.caption.pack(fill='x', pady=(8,0))
        self.canvas.bind('<Configure>', lambda e:self.schedule())
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.canvas.bind('<ButtonPress-1>', lambda e:self.canvas.scan_mark(e.x,e.y))
        self.canvas.bind('<B1-Motion>', lambda e:self.canvas.scan_dragto(e.x,e.y,gain=1))
        self.bind('<Destroy>', self.cleanup)

    def cleanup(self, event):
        if event.widget == self:
            if self.pending:
                self.after_cancel(self.pending)
            if self.document:
                self.document.close()
                self.document = None

    def show(self, entry=None, index=0, total=0):
        key = (id(entry['reader']),entry['page'],entry['rotation']) if entry else None
        if entry:
            self.caption.configure(text=f"{index+1} / {total} · {entry['path'].replace(chr(92), '/').split('/')[-1]} · 원본 {entry.get('source_page',entry['page'])+1}페이지")
        else:
            self.caption.configure(text='목록에서 페이지를 선택하세요.')
        if key == self.key:
            return
        self.key = key
        if self.document:
            self.document.close()
            self.document = None
        self.canvas.delete('all')
        self.photo = None
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        if entry:
            try:
                with PdfWriter() as writer:
                    writer.add_page(entry['reader'].pages[entry['page']])
                    writer.pages[0].rotate(entry['rotation'])
                    stream = BytesIO()
                    writer.write(stream)
                self.document = pdfium.PdfDocument(stream.getvalue())
            except Exception as error:
                self.caption.configure(text=f'미리보기를 표시할 수 없습니다: {error}')
        self.schedule()

    def fit(self):
        self.zoom = None
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.schedule()

    def change_zoom(self, factor):
        self.zoom = max(0.1, min(5, getattr(self,'actual_scale',1) * factor))
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
        self.pending = None
        self.canvas.delete('all')
        width, height = max(1,self.canvas.winfo_width()), max(1,self.canvas.winfo_height())
        if not self.document:
            self.scale_label.configure(text='')
            self.canvas.create_text(width/2,height/2,text='PDF를 추가하고 페이지를 선택하세요',fill='white',font=('맑은 고딕',14))
            self.canvas.configure(scrollregion=(0,0,width,height))
            return
        page = self.document[0]
        bitmap = None
        try:
            pw, ph = page.get_size()
            scale = self.zoom if self.zoom is not None else max(0.01,min((width-32)/pw,(height-32)/ph))
            scale = min(scale, math.sqrt(16000000/(pw*ph)),8000/max(pw,ph))
            self.actual_scale = scale
            bitmap = page.render(scale=scale)
            self.photo = ImageTk.PhotoImage(bitmap.to_pil())
            iw, ih = self.photo.width(), self.photo.height()
            x, y = max(16,(width-iw)//2), max(16,(height-ih)//2)
            self.canvas.create_image(x,y,anchor='nw',image=self.photo)
            self.canvas.configure(scrollregion=(0,0,max(width,iw+32),max(height,ih+32)))
            self.scale_label.configure(text=f'{scale*100:.0f}%')
        except Exception as error:
            self.caption.configure(text=f'미리보기 오류: {error}')
        finally:
            if bitmap:
                bitmap.close()
            page.close()
