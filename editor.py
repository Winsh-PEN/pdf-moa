# SPDX-License-Identifier: AGPL-3.0-only
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, filedialog, colorchooser
from pathlib import Path
import pymupdf as fitz
from editing import page_bytes, selected_text, selected_fonts, edit_page
from fonts import installed_fonts, inspect_file, match_font, checked_font_bytes

class TextDialog(simpledialog.Dialog):
    def __init__(self, parent, initial='', original_fonts=(), original_size=12, data=None, rect=None, mode='replace'):
        self.preview_source=data
        self.preview_rect=rect
        self.edit_mode=mode
        self.preview_job=None
        self.preview_result=None
        self.initial = initial
        self.color = (0,0,0)
        self.original_fonts=original_fonts
        self.original_size=original_size
        self.faces=list(installed_fonts())
        self.auto_face=match_font(original_fonts,self.faces)
        self.font_face=self.auto_face
        super().__init__(parent, '글자 입력 · 글꼴 선택')

    def body(self, master):
        outer=master
        master=ttk.Frame(outer)
        master.pack(side='left',fill='both',expand=True,padx=(0,12))
        pane=ttk.Frame(outer)
        pane.pack(side='right',fill='both',expand=True)
        ttk.Label(pane,text='선택 부분 실시간 미리보기').pack(anchor='w')
        self.live_canvas=tk.Canvas(pane,width=420,height=430,bg='#414a57',highlightthickness=0)
        self.live_canvas.pack(fill='both',expand=True)
        self.live_status=ttk.Label(pane,text='입력하면 미리보기가 갱신됩니다.',wraplength=420)
        self.live_status.pack(fill='x',pady=6)
        ttk.Label(master,text='PDF 글꼴: '+(', '.join(self.original_fonts) or '새 글자'),wraplength=580).pack(anchor='w')
        auto='PC의 일치 글꼴을 자동 선택했습니다.' if self.auto_face else '일치 글꼴 없음 또는 여러 글꼴 혼합: 사용할 글꼴을 선택하세요.'
        ttk.Label(master,text=auto,wraplength=580).pack(anchor='w',pady=(0,5))
        searchbar=ttk.Frame(master)
        searchbar.pack(fill='x')
        ttk.Label(searchbar,text='글꼴 검색').pack(side='left')
        self.search=tk.StringVar()
        ttk.Entry(searchbar,textvariable=self.search).pack(side='left',fill='x',expand=True,padx=6)
        ttk.Button(searchbar,text='글꼴 파일 추가',command=self.add_font).pack(side='left')
        self.combo=ttk.Combobox(master,state='readonly',width=72)
        self.combo.pack(fill='x',pady=5)
        self.combo.bind('<<ComboboxSelected>>',self.pick_font)
        self.policy_label=ttk.Label(master,wraplength=580)
        self.policy_label.pack(anchor='w')
        ttk.Button(master,text='글꼴 라이선스 정보',command=self.show_license).pack(anchor='w',pady=4)
        ttk.Label(master,text='파일의 포함 제한을 검사합니다. 상업적 이용 등 별도 이용조건은 글꼴 제공처에서 확인하세요.',wraplength=580).pack(anchor='w',pady=(0,8))
        self.search.trace_add('write',lambda *args:self.filter_fonts())
        self.filter_fonts()
        ttk.Label(master, text='입력할 글자 (여러 줄 가능)').pack(anchor='w')
        self.text = tk.Text(master, width=55, height=7, font=('맑은 고딕',11))
        self.text.pack(fill='both',expand=True)
        self.text.insert('1.0', self.initial)
        self.text.bind('<<Modified>>',self.text_modified)
        self.text.edit_modified(False)
        line = ttk.Frame(master)
        line.pack(fill='x',pady=8)
        ttk.Label(line,text='크기(pt)').pack(side='left')
        self.size_var=tk.StringVar()
        self.size = ttk.Spinbox(line,from_=4,to=144,width=6,textvariable=self.size_var)
        self.size.set(f'{max(4,min(144,self.original_size)):.1f}')
        self.size.pack(side='left',padx=8)
        ttk.Button(line,text='글자 색상',command=self.choose_color).pack(side='left')
        self.size_var.trace_add('write',lambda *args:self.schedule_preview())
        self.schedule_preview()
        return self.text

    def text_modified(self,event=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.schedule_preview()

    def schedule_preview(self):
        if not hasattr(self,'text') or self.preview_source is None:return
        if self.preview_job:self.after_cancel(self.preview_job)
        self.preview_result=None
        self.preview_job=self.after(220,self.update_preview)

    def update_preview(self):
        self.preview_job=None
        try:
            if self.combo.current()<0:raise ValueError('글꼴을 선택하세요.')
            data=edit_page(self.preview_source,self.preview_rect,self.edit_mode,
                          text=self.text.get('1.0','end-1c'),size=float(self.size.get()),color=self.color,font_face=self.font_face)
            with fitz.open(stream=data,filetype='pdf') as doc:
                box=fitz.Rect(self.preview_rect)
                clip=(box+(-40,-40,40,40)) & doc[0].rect
                scale=min(3, max(1,self.live_canvas.winfo_width()-16)/clip.width,
                          max(1,self.live_canvas.winfo_height()-16)/clip.height)
                pix=doc[0].get_pixmap(matrix=fitz.Matrix(scale,scale),clip=clip,alpha=False)
                self.live_photo=tk.PhotoImage(data=pix.tobytes('png'))
                self.live_canvas.delete('all')
                self.live_canvas.create_image(self.live_canvas.winfo_width()/2,self.live_canvas.winfo_height()/2,image=self.live_photo)
            self.preview_result=data
            self.live_status.configure(text='저장에 적용될 모습입니다. 확인을 누르면 반영됩니다.')
        except Exception as error:
            self.preview_result=None
            self.live_canvas.delete('all')
            self.live_status.configure(text=str(error))

    def destroy(self):
        if self.preview_job:
            self.after_cancel(self.preview_job)
            self.preview_job=None
        super().destroy()

    def filter_fonts(self):
        query=self.search.get().casefold()
        self.shown=[None]+[f for f in self.faces if query in f.name.casefold()]
        self.combo['values']=['기본 한글 글꼴 (MuPDF)']+[f.label for f in self.shown[1:]]
        if self.font_face in self.shown:
            self.combo.current(self.shown.index(self.font_face))
        else:
            self.combo.set('글꼴을 선택하세요')
        self.show_policy()

    def pick_font(self,event=None):
        index=self.combo.current()
        if index>=0: self.font_face=self.shown[index]
        self.show_policy()

    def show_policy(self):
        self.policy_label.configure(text=self.font_face.policy[1] if self.font_face else '프로그램에 포함된 기본 한글 글꼴')
        self.schedule_preview()

    def add_font(self):
        path=filedialog.askopenfilename(parent=self,filetypes=[('글꼴 파일','*.ttf *.otf *.ttc *.otc')])
        if not path: return
        try:
            added=inspect_file(path)
            self.faces.extend(f for f in added if f not in self.faces)
            self.font_face=added[0]
            self.search.set('')
            self.filter_fonts()
        except Exception as error:
            messagebox.showerror('글꼴 열기 실패',str(error),parent=self)

    def show_license(self):
        text=(self.font_face.license_text if self.font_face else 'MuPDF 기본 글꼴: 배포 폴더의 licenses/MuPDF 글꼴 고지를 확인하세요.')
        if self.font_face:
            text=self.font_face.name+'\n'+self.font_face.policy[1]+'\n\n'+text
        messagebox.showinfo('글꼴 파일의 라이선스 정보',text,parent=self)

    def choose_color(self):
        rgb, _ = colorchooser.askcolor(parent=self, title='글자 색상')
        if rgb:
            self.color = tuple(v/255 for v in rgb)
            self.schedule_preview()

    def validate(self):
        try:
            self.value_size = float(self.size.get())
            if not 4 <= self.value_size <= 144 or not self.text.get('1.0','end-1c').strip():
                raise ValueError('글자와 4~144pt 크기를 입력하세요.')
            if self.combo.current()<0:
                raise ValueError('목록에서 사용할 글꼴을 선택하세요.')
            if self.font_face is not None:
                checked_font_bytes(self.font_face,self.text.get('1.0','end-1c'))
            if self.preview_source is not None:
                if self.preview_job:self.after_cancel(self.preview_job)
                self.update_preview()
                if self.preview_result is None:raise ValueError(self.live_status.cget('text'))
            return True
        except Exception as error:
            messagebox.showerror('입력 확인',str(error),parent=self)
            return False

    def apply(self):
        self.result = (self.text.get('1.0','end-1c'),self.value_size,self.color,self.font_face)

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
        ttk.Label(self,text='추가/교체할 영역을 드래그하세요. 원래 글꼴을 PC에서 찾아 선택하며 다른 글꼴이나 파일도 사용할 수 있습니다.',padding=(12,0,12,8)).pack(fill='x')
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
                names,size=selected_fonts(self.data,rect) if mode=='replace' else ([],12)
                dialog = TextDialog(self,old,names,size,self.data,rect,mode)
                if not dialog.result:
                    return
                text,size,color,font_face = dialog.result
                result = dialog.preview_result
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
