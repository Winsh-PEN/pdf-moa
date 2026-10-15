# SPDX-License-Identifier: AGPL-3.0-only
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser
from pathlib import Path
import pymupdf as fitz
from editing import page_bytes, selected_text, selected_fonts, selected_lines, edit_page
from fonts import installed_fonts, inspect_file, match_font, checked_font_bytes, BUILTIN_LABEL
import ui
from ui import px, icon_button

MODE_HINTS = {
    'replace': '바꿀 글자를 드래그해서 감싸세요. 글자 가운데가 영역 안에 들어간 글자만 선택되며, 원래 시작점과 줄 위치를 유지합니다.',
    'text': '새 글자를 넣을 영역을 드래그하세요.',
    'image': '사진을 넣을 영역을 드래그하세요. 사진은 비율을 유지해 영역 안에 들어갑니다.',
    'delete': '지울 글자를 드래그해서 감싸세요. 글자 가운데가 영역 안에 들어간 글자만 지워집니다(흰 상자로 덮지 않고 실제로 지움).',
    'move': '이 창에서 넣은 글자·사진을 끌어서 옮기세요. 오른쪽 아래 모서리를 끌면 크기가 바뀌고, 두 번 클릭하면 글자를 고치거나 사진을 바꿉니다. 오른쪽 클릭으로 지울 수 있습니다.',
}
MOVE_EMPTY = '옮길 수 있는 것은 이 창에서 넣은 글자·사진입니다. 먼저 글자 추가나 사진 추가를 하세요.'
MODES = [('글자 교체','replace','replace'),('글자 추가','text','text'),('사진 추가','image','image'),
         ('글자 지우기','delete','erase'),('옮기기','move','move')]
MOVABLE = ('text', 'image')
AUTO = object()  # TextDialog font_face default: pick the font matching the PDF's original
IMAGE_TYPES = [('사진','*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp')]


class TextDialog(ui.Dialog):
    ok_text = '적용'
    submit_on_return = False  # Enter makes a new line; Ctrl+Enter applies

    def __init__(self, parent, initial='', original_fonts=(), original_size=12, data=None, rect=None, mode='replace',
                 font_face=AUTO, color=None, title=None):
        self.preview_source=data
        self.preview_rect=rect
        self.edit_mode=mode
        self.preview_job=None
        self.draw_job=None
        self.preview_result=None
        self.initial = initial
        self.color = color or (0,0,0)
        self.original_fonts=original_fonts
        self.original_size=original_size
        self.faces=list(installed_fonts())
        if font_face not in (AUTO, None) and font_face not in self.faces:
            self.faces.append(font_face)  # a font file added earlier in this editor
        self.auto_face=match_font(original_fonts,self.faces)
        # AUTO: match the PDF's original font. Otherwise keep the given font (None = built-in).
        self.font_face=self.auto_face if font_face is AUTO else font_face
        super().__init__(parent, title or ('글자 교체' if mode == 'replace' else '글자 추가'))

    def body(self, outer):
        self.configure(bg=ui.BG)
        outer.configure(bg=ui.BG)
        gap = px(self, 8)
        wrap = px(self, 520)
        master=ttk.Frame(outer)
        master.pack(side='left',fill='both',expand=True,padx=(0,px(self, 14)))
        pane=ttk.Frame(outer)
        pane.pack(side='right',fill='both',expand=True)
        ttk.Label(pane,text='실시간 미리보기',style='Section.TLabel').pack(anchor='w',pady=(0,px(self, 4)))
        holder=ttk.Frame(pane,style='Card.TFrame',padding=1)
        holder.pack(fill='both',expand=True)
        self.live_canvas=tk.Canvas(holder,width=px(self, 420),height=px(self, 400),bg=ui.CANVAS,highlightthickness=0)
        self.live_canvas.pack(fill='both',expand=True)
        self.live_canvas.bind('<Configure>',lambda e:self.schedule_draw())
        self.live_status=ttk.Label(pane,text='입력하면 미리보기가 갱신됩니다.',style='Muted.TLabel',wraplength=px(self, 420))
        self.live_status.pack(fill='x',pady=(px(self, 6),0))

        fonts=ttk.Labelframe(master,text='글꼴',padding=(px(self, 10),px(self, 6)))
        fonts.pack(fill='x')
        ttk.Label(fonts,text='PDF 원래 글꼴: '+(', '.join(self.original_fonts) or '없음 (새 글자)'),wraplength=wrap).pack(anchor='w')
        auto=('✓ PC에서 같은 글꼴을 찾아 자동 선택했습니다.' if self.auto_face else
              '같은 글꼴을 찾지 못했거나 여러 글꼴이 섞여 있습니다. 사용할 글꼴을 고르세요.')
        ttk.Label(fonts,text=auto,style='Muted.TLabel',wraplength=wrap).pack(anchor='w',pady=(px(self, 2),gap))
        searchbar=ttk.Frame(fonts)
        searchbar.pack(fill='x')
        ttk.Label(searchbar,text='검색').pack(side='left')
        self.search=tk.StringVar()
        ttk.Entry(searchbar,textvariable=self.search).pack(side='left',fill='x',expand=True,padx=(px(self, 6),px(self, 6)))
        icon_button(searchbar,'글꼴 파일 추가','font',self.add_font,size=16,
                    tip='PC에 설치하지 않은 TTF/OTF/TTC/OTC 파일을 이 창에서만 사용').pack(side='left')
        self.combo=ttk.Combobox(fonts,state='readonly',width=60)
        self.combo.pack(fill='x',pady=(px(self, 6),px(self, 4)))
        self.combo.bind('<<ComboboxSelected>>',self.pick_font)
        policy=ttk.Frame(fonts)
        policy.pack(fill='x')
        self.policy_label=ttk.Label(policy,style='Muted.TLabel',wraplength=px(self, 380))
        self.policy_label.pack(side='left',anchor='w')
        icon_button(policy,'라이선스 정보','shield',self.show_license,size=16).pack(side='right')
        ttk.Label(fonts,text='글꼴 파일의 포함 제한만 검사합니다. 상업적 이용 등 이용조건은 글꼴 제공처에서 확인하세요.',
                  style='Muted.TLabel',font=(ui.FONT, 9),wraplength=wrap).pack(anchor='w',pady=(px(self, 4),0))
        self.search.trace_add('write',lambda *args:self.filter_fonts())

        words=ttk.Labelframe(master,text='글자',padding=(px(self, 10),px(self, 6)))
        words.pack(fill='both',expand=True,pady=(gap,0))
        self.text = tk.Text(words, width=52, height=6, font=(ui.FONT,11), relief='flat', wrap='word',
                            highlightthickness=1, highlightbackground=ui.BORDER, highlightcolor=ui.ACCENT,
                            padx=px(self, 6), pady=px(self, 4))
        self.text.pack(fill='both',expand=True)
        self.text.insert('1.0', self.initial)
        self.text.bind('<<Modified>>',self.text_modified)
        # Without 'break' the Text class binding would also insert a newline.
        self.text.bind('<Control-Return>',lambda event:self.ok() or 'break')
        self.text.edit_modified(False)
        ttk.Label(words,text='Enter: 줄바꿈 · Ctrl+Enter: 적용 · Esc: 취소',style='Muted.TLabel',font=(ui.FONT, 9)).pack(anchor='w',pady=(px(self, 4),0))
        line = ttk.Frame(words)
        line.pack(fill='x',pady=(px(self, 6),0))
        ttk.Label(line,text='크기').pack(side='left')
        self.size_var=tk.StringVar()
        self.size = ttk.Spinbox(line,from_=4,to=144,increment=0.5,width=6,textvariable=self.size_var)
        self.size.set(f'{max(4,min(144,self.original_size)):.1f}')
        self.size.pack(side='left',padx=(px(self, 6),px(self, 2)))
        ttk.Label(line,text='pt').pack(side='left',padx=(0,px(self, 14)))
        self.swatch=tk.PhotoImage(master=self,width=px(self, 16),height=px(self, 16))
        self.paint_swatch()
        ttk.Button(line,text='글자 색상',image=self.swatch,compound='left',style='Tool.TButton',command=self.choose_color).pack(side='left')
        self.size_var.trace_add('write',lambda *args:self.schedule_preview())
        self.filter_fonts()
        self.schedule_preview()
        return self.text

    def paint_swatch(self):
        size = self.swatch.width()
        hex_color = '#%02x%02x%02x' % tuple(round(v*255) for v in self.color)
        self.swatch.put('#94a3b8', to=(0, 0, size, size))
        self.swatch.put(hex_color, to=(1, 1, size-1, size-1))

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
            self.preview_result=data
            self.draw_preview()
            self.live_status.configure(text='저장에 적용될 모습입니다. [적용]을 누르면 반영됩니다.',foreground=ui.MUTED)
        except Exception as error:
            self.preview_result=None
            self.live_canvas.delete('all')
            self.live_status.configure(text=str(error),foreground=ui.DANGER)

    def schedule_draw(self):
        if self.draw_job:self.after_cancel(self.draw_job)
        self.draw_job=self.after(120,self.draw_preview)

    def draw_preview(self):
        # Also called directly; drop a scheduled draw so none is left behind.
        if self.draw_job:self.after_cancel(self.draw_job)
        self.draw_job=None
        if self.preview_result is None:return
        with fitz.open(stream=self.preview_result,filetype='pdf') as doc:
            box=fitz.Rect(self.preview_rect)
            clip=(box+(-40,-40,40,40)) & doc[0].rect
            scale=min(3, max(1,self.live_canvas.winfo_width()-16)/clip.width,
                      max(1,self.live_canvas.winfo_height()-16)/clip.height)
            pix=doc[0].get_pixmap(matrix=fitz.Matrix(scale,scale),clip=clip,alpha=False)
            self.live_photo=tk.PhotoImage(master=self,data=pix.tobytes('png'))
        self.live_canvas.delete('all')
        self.live_canvas.create_image(self.live_canvas.winfo_width()/2,self.live_canvas.winfo_height()/2,image=self.live_photo)

    def destroy(self):
        for job in ('preview_job','draw_job'):
            if getattr(self,job,None):
                self.after_cancel(getattr(self,job))
                setattr(self,job,None)
        super().destroy()

    def filter_fonts(self):
        query=self.search.get().casefold()
        self.shown=[None]+[f for f in self.faces if query in f.name.casefold()]
        self.combo['values']=[BUILTIN_LABEL]+[f.label for f in self.shown[1:]]
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
        if self.font_face:
            allowed, message = self.font_face.policy
            self.policy_label.configure(text=message, foreground=ui.MUTED if allowed else ui.DANGER)
        else:
            self.policy_label.configure(text='프로그램에 포함된 기본 한글 글꼴', foreground=ui.MUTED)
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
        text=(self.font_face.license_text if self.font_face else
              '기본 한글 글꼴: Droid Sans Fallback (Apache License 2.0, MuPDF에 포함).\n'
              '쓴 글자만 PDF에 포함합니다. 고지: 배포 폴더의 licenses/MuPDF/resources/fonts/droid/NOTICE')
        if self.font_face:
            text=self.font_face.name+'\n'+self.font_face.policy[1]+'\n\n'+text
        messagebox.showinfo('글꼴 파일의 라이선스 정보',text,parent=self)

    def choose_color(self):
        rgb, _ = colorchooser.askcolor(parent=self, title='글자 색상')
        if rgb:
            self.color = tuple(v/255 for v in rgb)
            self.paint_swatch()
            self.schedule_preview()

    def validate(self):
        try:
            self.value_size = float(self.size.get())
            if not 4 <= self.value_size <= 144 or not self.text.get('1.0','end-1c').strip():
                raise ValueError('글자와 4~144pt 크기를 입력하세요.')
            if self.combo.current()<0:
                raise ValueError('목록에서 사용할 글꼴을 선택하세요.')
            if self.preview_source is None:
                if self.font_face is not None:
                    checked_font_bytes(self.font_face,self.text.get('1.0','end-1c'))
            else:
                # Any change clears preview_result, so a result here matches the inputs.
                if self.preview_job:
                    self.after_cancel(self.preview_job)
                    self.preview_job=None
                if self.preview_result is None:
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
        page = entry.get('source_page', entry['page']) + 1
        self.title(f"페이지 편집 · {Path(entry['path']).name} {page}페이지" if entry.get('path') else '페이지 편집 · 빈 페이지')
        self.configure(bg=ui.BG)
        ui.fit_geometry(self, 1080, 880, minimum=(1000, 600))
        self.transient(parent)
        self.on_apply = on_apply
        self.data = self.original = data
        # The edits in order, each dict(mode, rect, kw) for edit_page. Text and
        # images added here can be moved later: that edit and the ones after it
        # are applied again. states[k] is the page after the first k edits.
        self.ops = []
        self.states = [data]
        self.undo_stack = []  # earlier (ops, states); the lists are replaced, never changed in place
        self.drag_op = None
        self.zoom = None  # None = fit to window
        self.mode = tk.StringVar(value='replace')
        self.pending = self.start = self.box_id = self.photo = None
        bar = ttk.Frame(self,style='Bar.TFrame',padding=(px(self, 14),px(self, 10)))
        bar.pack(fill='x')
        icons = ui.icons_for(self)
        for label, mode, icon in MODES:
            ttk.Radiobutton(bar,text=label,variable=self.mode,value=mode,style='Toolbutton',image=icons.get(icon),
                            compound='left',command=self.mode_changed).pack(side='left',padx=(0,px(self, 4)))
        self.undo_button = icon_button(bar,'되돌리기','undo',self.undo,tip='이 창에서 한 단계 되돌리기 (Ctrl+Z)')
        self.undo_button.pack(side='right')
        ttk.Separator(bar,orient='vertical').pack(side='right',fill='y',padx=px(self, 10),pady=px(self, 3))
        icon_button(bar,'화면 맞춤','fit',self.fit,tip='페이지 전체가 보이게 맞추기').pack(side='right')
        icon_button(bar,'','zoom_in',lambda:self.change_zoom(1.25),style='Icon.TButton',tip='확대 (Ctrl+휠 위)').pack(side='right',padx=(px(self, 4),px(self, 8)))
        self.scale_label = ttk.Label(bar,text='',width=5,anchor='center',style='BarMuted.TLabel')
        self.scale_label.pack(side='right')
        icon_button(bar,'','zoom_out',lambda:self.change_zoom(0.8),style='Icon.TButton',tip='축소 (Ctrl+휠 아래)').pack(side='right',padx=(0,px(self, 4)))
        ttk.Separator(self,orient='horizontal').pack(fill='x')
        self.hint = ttk.Label(self,text=MODE_HINTS['replace'],style='Muted.TLabel',padding=(px(self, 14),px(self, 8)))
        self.hint.pack(fill='x')
        self.hint.bind('<Configure>',lambda e:self.hint.configure(wraplength=max(px(self, 200),e.width-px(self, 30))))
        footer = ttk.Frame(self,style='Bar.TFrame',padding=(px(self, 14),px(self, 10)))
        footer.pack(side='bottom',fill='x')
        ttk.Separator(self,orient='horizontal').pack(side='bottom',fill='x')
        ttk.Label(footer,text='변경 적용 후 메인 창에서 최종 PDF를 저장하세요.',style='BarMuted.TLabel').pack(side='left')
        ttk.Button(footer,text='취소',command=self.close).pack(side='right')
        self.apply_button = icon_button(footer,'변경 적용','check',self.apply,style='Accent.TButton',color='#ffffff')
        self.apply_button.pack(side='right',padx=px(self, 8))
        holder = ttk.Frame(self,style='Card.TFrame',padding=1)
        holder.pack(fill='both',expand=True,padx=px(self, 14),pady=(0,px(self, 12)))
        holder.rowconfigure(0,weight=1)
        holder.columnconfigure(0,weight=1)
        self.canvas = tk.Canvas(holder,bg=ui.CANVAS,highlightthickness=0,cursor='crosshair')
        self.canvas.grid(row=0,column=0,sticky='nsew')
        sy = ttk.Scrollbar(holder,orient='vertical',command=self.canvas.yview)
        sx = ttk.Scrollbar(holder,orient='horizontal',command=self.canvas.xview)
        sy.grid(row=0,column=1,sticky='ns')
        sx.grid(row=1,column=0,sticky='ew')
        self.canvas.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.canvas.bind('<Configure>',self.schedule)
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Double-Button-1>',self.edit_op_at)
        self.canvas.bind('<Button-3>',self.op_menu)
        self.canvas.bind('<Motion>',self.hover)
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Shift-MouseWheel>',lambda e:self.canvas.xview_scroll(-1 if e.delta>0 else 1,'units') or 'break')
        self.bind('<Escape>',lambda e:self.close())
        self.bind('<Control-z>',lambda e:self.undo())
        self.bind('<Control-Z>',lambda e:self.undo())
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.update_buttons()
        self.grab_set()

    def mode_changed(self):
        mode = self.mode.get()
        movable = any(op['mode'] in MOVABLE for op in self.ops)
        self.hint.configure(text=MOVE_EMPTY if mode == 'move' and not movable else MODE_HINTS[mode])
        self.canvas.configure(cursor='' if mode == 'move' else 'crosshair')
        self.canvas.delete('selection')
        if self.box_id:
            self.canvas.delete(self.box_id)
            self.box_id = None
        self.draw_ops()

    def update_buttons(self):
        self.undo_button.state(['!disabled'] if self.undo_stack else ['disabled'])
        self.apply_button.state(['!disabled'] if self.data != self.original else ['disabled'])

    def fit(self):
        self.zoom = None
        self.schedule()

    def change_zoom(self,factor):
        self.zoom = max(0.25,min(4,getattr(self,'scale',1)*factor))
        self.schedule()

    def wheel(self,event):
        if event.state & 4:
            self.change_zoom(1.15 if event.delta>0 else 1/1.15)
        else:
            self.canvas.yview_scroll(-1 if event.delta>0 else 1,'units')
        return 'break'

    def schedule(self,event=None):
        if self.pending:
            self.after_cancel(self.pending)
        self.pending = self.after(100,self.render)

    def render(self):
        # Also called directly; drop a scheduled render so none is left behind.
        if self.pending:
            self.after_cancel(self.pending)
        self.pending = None
        with fitz.open(stream=self.data,filetype='pdf') as doc:
            page = doc[0]
            self.page_rect = page.rect
            w,h = max(1,self.canvas.winfo_width()), max(1,self.canvas.winfo_height())
            margin = px(self, 12)
            fit = max(0.01,min((w-2*margin)/page.rect.width,(h-2*margin)/page.rect.height,3))
            self.scale = fit if self.zoom is None else self.zoom
            pix = page.get_pixmap(matrix=fitz.Matrix(self.scale,self.scale),alpha=False)
            self.photo = tk.PhotoImage(master=self,data=pix.tobytes('png'))
            self.offset = (max(margin,(w-pix.width)/2),max(margin,(h-pix.height)/2))
            self.canvas.delete('all')
            self.box_id = self.start = None
            self.canvas.create_image(*self.offset,anchor='nw',image=self.photo)
            self.canvas.configure(scrollregion=(0,0,max(w,pix.width+2*margin),max(h,pix.height+2*margin)))
            self.scale_label.configure(text=f'{self.scale*100:.0f}%')
        self.draw_ops()

    def canvas_xy(self,event):
        return self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)

    def point(self,event):
        cx,cy = self.canvas_xy(event)
        x = (cx-self.offset[0])/self.scale
        y = (cy-self.offset[1])/self.scale
        return (max(0,min(self.page_rect.width,x)),max(0,min(self.page_rect.height,y)))

    def press(self,event):
        if not self.photo:
            return
        if self.mode.get() == 'move':
            index, action = self.op_at(self.point(event))
            rect = self.ops[index]['rect'] if index is not None else None
            self.drag_op = dict(index=index, action=action, start=self.point(event), rect=rect, new=rect) if rect else None
            return
        if self.box_id:
            self.canvas.delete(self.box_id)
        self.start = self.point(event)
        cx,cy = self.canvas_xy(event)
        self.box_id = self.canvas.create_rectangle(cx,cy,cx,cy,outline=ui.ACCENT,width=2,dash=(6,3))

    def motion(self,event):
        if self.mode.get() == 'move':
            if self.drag_op:
                self.drag_op['new'] = self.dragged_rect(self.drag_op, self.point(event))
                self.draw_ops(self.drag_op['index'], self.drag_op['new'])
            return
        if self.start:
            x,y = self.start
            cx,cy = self.canvas_xy(event)
            self.canvas.coords(self.box_id,x*self.scale+self.offset[0],y*self.scale+self.offset[1],cx,cy)

    def release(self,event):
        if self.mode.get() == 'move':
            drag, self.drag_op = self.drag_op, None
            if drag and drag['new'] != drag['rect']:
                self.change_op(drag['index'], rect=drag['new'])
            else:
                self.draw_ops()
            return
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
                path = filedialog.askopenfilename(parent=self,filetypes=IMAGE_TYPES)
                if not path:
                    return
                kw = dict(image=Path(path).read_bytes())
                result = edit_page(self.data,rect,mode,**kw)
            elif mode == 'delete':
                old = selected_text(self.data,rect)
                if not old.strip():
                    raise ValueError('선택 영역에 글자가 없습니다. 스캔 이미지 속 글자는 지울 수 없습니다.')
                self.show_selection(rect)
                shown = old if len(old) <= 300 else old[:300]+'…'
                if not messagebox.askyesno('글자 지우기',f'다음 글자를 지웁니다.\n\n{shown}\n\n계속할까요?',parent=self):
                    self.canvas.delete('selection')
                    return
                kw = {}
                result = edit_page(self.data,rect,mode)
            else:
                old = selected_text(self.data,rect) if mode=='replace' else ''
                if mode=='replace' and not old.strip():
                    raise ValueError('선택 영역에 글자가 없습니다. 스캔 이미지 속 글자는 교체할 수 없습니다.')
                names,size=selected_fonts(self.data,rect) if mode=='replace' else ([],12)
                if mode == 'replace':
                    self.show_selection(rect)
                dialog = TextDialog(self,old,names,size,self.data,rect,mode)
                self.canvas.delete('selection')
                if not dialog.result:
                    return
                text,size,color,font_face = dialog.result
                kw = dict(text=text,size=size,color=color,font_face=font_face)
                result = dialog.preview_result
            self.push(mode, rect, kw, result)
        except Exception as error:
            messagebox.showerror('편집 확인',str(error),parent=self)

    def set_state(self, ops, states):
        self.undo_stack = self.undo_stack + [(self.ops, self.states)]
        self.ops, self.states = ops, states
        self.data = states[-1]
        self.render()
        self.update_buttons()
        if self.mode.get() == 'move':
            self.mode_changed()

    def push(self, mode, rect, kw, result=None):
        """Add one edit; result is edit_page's output when it is already known."""
        if result is None:
            result = edit_page(self.data, rect, mode, **kw)
        self.set_state(self.ops + [dict(mode=mode, rect=tuple(rect), kw=kw)], self.states + [result])

    def change_op(self, index, rect=None, kw=None):
        """Apply edit index again at a new place or with new content, then the later edits.

        Nothing changes when one of them no longer fits; returns whether it worked.
        """
        ops = [dict(op) for op in self.ops]
        if rect is not None:
            ops[index]['rect'] = tuple(rect)
        if kw is not None:
            ops[index]['kw'] = kw
        return self.replay(index, ops)

    def remove_op(self, index):
        """Take out one added item (not only the last one) and apply the later edits again."""
        return self.replay(index, self.ops[:index] + self.ops[index + 1:])

    def replay(self, index, ops):
        """Use ops, reusing the pages before edit index and applying the rest again."""
        states = self.states[:index + 1]
        self.configure(cursor='watch')
        self.update_idletasks()
        try:
            for op in ops[index:]:
                states.append(edit_page(states[-1], op['rect'], op['mode'], **op['kw']))
        except Exception as error:
            messagebox.showerror('바꿀 수 없습니다', f'{error}\n원래대로 둡니다.', parent=self)
            self.draw_ops()
            return False
        finally:
            self.configure(cursor='')
        self.set_state(ops, states)
        return True

    def op_menu(self, event):
        """Right-click on an added item in move mode: change or remove it."""
        if self.mode.get() != 'move' or not self.photo:
            return
        index, _ = self.op_at(self.point(event))
        if index is None:
            return
        menu = tk.Menu(self, tearoff=0)
        change = '사진 바꾸기…' if self.ops[index]['mode'] == 'image' else '글자 고치기…'
        menu.add_command(label=change, command=lambda: self.edit_op(index))
        menu.add_command(label='이 항목 지우기', command=lambda: self.remove_op(index))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def op_at(self, point):
        """(index, 'move' or 'resize') of the topmost movable edit at a page point."""
        x, y = point
        grip = px(self, 9) / self.scale
        for index in reversed(range(len(self.ops))):
            op = self.ops[index]
            if op['mode'] not in MOVABLE:
                continue
            x0, y0, x1, y1 = op['rect']
            if abs(x - x1) <= grip and abs(y - y1) <= grip:
                return index, 'resize'
            if x0 <= x <= x1 and y0 <= y <= y1:
                return index, 'move'
        return None, None

    def dragged_rect(self, drag, point):
        """The item's rectangle while dragging, kept on the page (at least 10pt big)."""
        x0, y0, x1, y1 = drag['rect']
        dx, dy = point[0] - drag['start'][0], point[1] - drag['start'][1]
        width, height = self.page_rect.width, self.page_rect.height
        if drag['action'] == 'resize':
            return (x0, y0, max(x0 + 10, min(width, x1 + dx)), max(y0 + 10, min(height, y1 + dy)))
        dx = max(-x0, min(width - x1, dx))
        dy = max(-y0, min(height - y1, dy))
        return (x0 + dx, y0 + dy, x1 + dx, y1 + dy)

    def draw_ops(self, moving=None, rect=None):
        """Outlines of the movable edits (move mode), with a resize grip at the bottom right."""
        self.canvas.delete('ops')
        if self.mode.get() != 'move' or not self.photo:
            return
        ox, oy, s, g = self.offset[0], self.offset[1], self.scale, px(self, 5)
        for index, op in enumerate(self.ops):
            if op['mode'] not in MOVABLE:
                continue
            x0, y0, x1, y1 = rect if index == moving and rect else op['rect']
            color = ui.ACCENT if index == moving else '#d97706'
            self.canvas.create_rectangle(ox+x0*s, oy+y0*s, ox+x1*s, oy+y1*s, outline=color, width=2, dash=(5, 3), tags='ops')
            self.canvas.create_rectangle(ox+x1*s-g, oy+y1*s-g, ox+x1*s+g, oy+y1*s+g, outline=color, fill='white', tags='ops')

    def hover(self, event):
        if self.mode.get() != 'move' or not self.photo or self.drag_op:
            return
        _, action = self.op_at(self.point(event))
        self.canvas.configure(cursor={'move': 'fleur', 'resize': 'size_nw_se'}.get(action, ''))

    def edit_op_at(self, event):
        """Double-click in move mode: change the text of added text, or the picture."""
        if self.mode.get() != 'move' or not self.photo:
            return
        index, _ = self.op_at(self.point(event))
        if index is not None:
            self.edit_op(index)

    def edit_op(self, index):
        op = self.ops[index]
        if op['mode'] == 'image':
            path = filedialog.askopenfilename(parent=self, filetypes=IMAGE_TYPES)
            if path:
                self.change_op(index, kw=dict(image=Path(path).read_bytes()))
            return
        kw = op['kw']
        dialog = TextDialog(self, kw['text'], (), kw['size'], self.states[index], op['rect'], 'text',
                            font_face=kw['font_face'], color=kw['color'], title='넣은 글자 고치기')
        if dialog.result:
            text, size, color, font_face = dialog.result
            self.change_op(index, kw=dict(text=text, size=size, color=color, font_face=font_face))

    def show_selection(self, rect):
        """Mark the characters the box selected (the same rule the edit uses)."""
        self.canvas.delete('selection')
        with fitz.open(stream=self.data,filetype='pdf') as doc:
            lines = selected_lines(doc[0], rect)
        ox, oy = self.offset
        for line in lines:
            for c,_ in line['chars']:
                x0,y0,x1,y1 = c['bbox']
                self.canvas.create_rectangle(ox+x0*self.scale, oy+y0*self.scale, ox+x1*self.scale, oy+y1*self.scale,
                                             outline='', fill=ui.ACCENT, stipple='gray25', tags='selection')
        self.update_idletasks()

    def undo(self):
        """Undo the last edit, move or change."""
        if self.undo_stack:
            self.ops, self.states = self.undo_stack[-1]
            self.undo_stack = self.undo_stack[:-1]
            self.data = self.states[-1]
            self.render()
            self.update_buttons()
            if self.mode.get() == 'move':
                self.mode_changed()

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
