# SPDX-License-Identifier: AGPL-3.0-only
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, filedialog, colorchooser
from pathlib import Path
import pymupdf as fitz
from editing import page_bytes, selected_text, edit_page

class TextDialog(simpledialog.Dialog):
    def __init__(self, parent, initial=''):
        self.initial = initial
        self.color = (0,0,0)
        super().__init__(parent, '글자 입력 · 새 글꼴로 교체됩니다')

    def body(self, master):
        ttk.Label(master, text='입력할 글자 (여러 줄 가능)').pack(anchor='w')
        self.text = tk.Text(master, width=55, height=7, font=('맑은 고딕',11))
        self.text.pack(fill='both',expand=True)
        self.text.insert('1.0', self.initial)
        line = ttk.Frame(master)
        line.pack(fill='x',pady=8)
        ttk.Label(line,text='크기(pt)').pack(side='left')
        self.size = ttk.Spinbox(line,from_=4,to=144,width=6)
        self.size.set('12')
        self.size.pack(side='left',padx=8)
        ttk.Button(line,text='글자 색상',command=self.choose_color).pack(side='left')
        return self.text

    def choose_color(self):
        rgb, _ = colorchooser.askcolor(parent=self, title='글자 색상')
        if rgb:
            self.color = tuple(v/255 for v in rgb)

    def validate(self):
        try:
            self.value_size = float(self.size.get())
            if not 4 <= self.value_size <= 144 or not self.text.get('1.0','end-1c').strip():
                raise ValueError()
            return True
        except ValueError:
            messagebox.showerror('입력 확인','글자와 4~144pt 크기를 입력하세요.',parent=self)
            return False

    def apply(self):
        self.result = (self.text.get('1.0','end-1c'),self.value_size,self.color)

class PageEditor(tk.Toplevel):
    def __init__(self, parent, entry, on_apply):
        data = page_bytes(entry)
        super().__init__(parent)
        self.title('페이지 편집 · 영역을 드래그해서 선택')
        self.geometry('1050x850')
        self.minsize(800,600)
        self.transient(parent)
        self.on_apply = on_apply
        self.data = self.original = data
        self.history = []
        self.mode = tk.StringVar(value='replace')
        self.pending = self.start = self.box_id = self.photo = None
        bar = ttk.Frame(self,padding=12)
        bar.pack(fill='x')
        for label, mode in [('기존 글자 교체','replace'),('글자 추가','text'),('사진 추가','image')]:
            ttk.Radiobutton(bar,text=label,variable=self.mode,value=mode).pack(side='left',padx=8)
        ttk.Button(bar,text='편집 취소(한 단계)',command=self.undo).pack(side='right')
        ttk.Label(self,text='추가/교체할 영역을 드래그하세요. 교체는 글자 전체를 포함해야 하며 기본 한글 글꼴을 사용합니다.',padding=(12,0,12,8)).pack(fill='x')
        self.canvas = tk.Canvas(self,bg='#414a57',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True,padx=12)
        footer = ttk.Frame(self,padding=12)
        footer.pack(fill='x')
        ttk.Label(footer,text='변경 적용 후 메인 창에서 최종 PDF를 저장하세요.').pack(side='left')
        ttk.Button(footer,text='취소',command=self.close).pack(side='right')
        ttk.Button(footer,text='변경 적용',command=self.apply).pack(side='right',padx=8)
        self.canvas.bind('<Configure>',self.schedule)
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',self.release)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.grab_set()

    def schedule(self,event=None):
        if self.pending:
            self.after_cancel(self.pending)
        self.pending = self.after(100,self.render)

    def render(self):
        self.pending = None
        with fitz.open(stream=self.data,filetype='pdf') as doc:
            page = doc[0]
            self.page_rect = page.rect
            w,h = max(1,self.canvas.winfo_width()), max(1,self.canvas.winfo_height())
            self.scale = max(0.01,min((w-24)/page.rect.width,(h-24)/page.rect.height,3))
            pix = page.get_pixmap(matrix=fitz.Matrix(self.scale,self.scale),alpha=False)
            self.photo = tk.PhotoImage(data=pix.tobytes('png'))
            self.offset = ((w-pix.width)/2,(h-pix.height)/2)
            self.canvas.delete('all')
            self.box_id = self.start = None
            self.canvas.create_image(*self.offset,anchor='nw',image=self.photo)

    def point(self,event):
        x = (event.x-self.offset[0])/self.scale
        y = (event.y-self.offset[1])/self.scale
        return (max(0,min(self.page_rect.width,x)),max(0,min(self.page_rect.height,y)))

    def press(self,event):
        if not self.photo:
            return
        if self.box_id:
            self.canvas.delete(self.box_id)
        self.start = self.point(event)
        self.box_id = self.canvas.create_rectangle(event.x,event.y,event.x,event.y,outline='#168aff',width=2)

    def motion(self,event):
        if self.start:
            x,y = self.start
            self.canvas.coords(self.box_id,x*self.scale+self.offset[0],y*self.scale+self.offset[1],event.x,event.y)

    def release(self,event):
        if not self.start:
            return
        x,y = self.point(event)
        sx,sy = self.start
        self.start = None
        rect = (min(x,sx),min(y,sy),max(x,sx),max(y,sy))
        if rect[2]-rect[0]<3 or rect[3]-rect[1]<3:
            return
        try:
            mode = self.mode.get()
            if mode == 'image':
                path = filedialog.askopenfilename(parent=self,filetypes=[('사진','*.png *.jpg *.jpeg *.bmp *.webp')])
                if not path:
                    return
                result = edit_page(self.data,rect,mode,image=Path(path).read_bytes())
            else:
                old = selected_text(self.data,rect) if mode=='replace' else ''
                if mode=='replace' and not old.strip():
                    raise ValueError('선택 영역에 글자가 없습니다. 스캔 이미지 속 글자는 교체할 수 없습니다.')
                dialog = TextDialog(self,old)
                if not dialog.result:
                    return
                text,size,color = dialog.result
                result = edit_page(self.data,rect,mode,text=text,size=size,color=color)
            self.history.append(self.data)
            self.history = self.history[-20:]
            self.data = result
            self.render()
        except Exception as error:
            messagebox.showerror('편집 확인',str(error),parent=self)

    def undo(self):
        if self.history:
            self.data = self.history.pop()
            self.render()

    def apply(self):
        if self.data != self.original:
            self.on_apply(self.data)
        self.finish()

    def close(self):
        if self.data != self.original and not messagebox.askyesno('편집 취소','이 창에서 편집한 내용을 버릴까요?',parent=self):
            return
        self.finish()

    def finish(self):
        if self.pending:
            self.after_cancel(self.pending)
        self.grab_release()
        self.destroy()
