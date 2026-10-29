# SPDX-License-Identifier: AGPL-3.0-only
from pathlib import Path
from io import BytesIO
import uuid
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from PIL import Image,ImageOps,ImageTk
from settings import default_path
import ui


def add_stamp(folder,path):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with Image.open(path) as source:
        im=ImageOps.exif_transpose(source).convert('RGBA')
        im.thumbnail((2400,2400),Image.Resampling.LANCZOS)
        name=Path(path).stem[:60]+'_'+uuid.uuid4().hex[:8]+'.png'
        target=folder/name;im.save(target,'PNG')
        return target


class StampDialog(ui.Dialog):
    ok_text='선택한 도장 사용'
    def __init__(self,parent,folder=None):
        self.folder=Path(folder) if folder else default_path().parent/'stamps'
        self.paths=[];super().__init__(parent,'도장·서명 즐겨찾기')
    def body(self,frame):
        ttk.Label(frame,text='등록한 이미지는 이 PC에 보관합니다. 선택 후 페이지에서 넣을 영역을 드래그하세요.').pack(pady=8)
        row=ttk.Frame(frame);row.pack(fill='both',expand=True)
        self.list=tk.Listbox(row,width=36,height=10,exportselection=False);self.list.pack(side='left',fill='both',expand=True)
        self.list.bind('<<ListboxSelect>>',lambda e:self.preview())
        self.canvas=tk.Canvas(row,width=220,height=190,bg='white');self.canvas.pack(side='right',padx=10)
        bar=ttk.Frame(frame);bar.pack(fill='x',pady=8)
        ttk.Button(bar,text='이미지 등록…',command=self.add).pack(side='left')
        ttk.Button(bar,text='즐겨찾기에서 제거',command=self.remove).pack(side='left',padx=8)
        self.reload()
    def reload(self):
        self.paths=sorted(self.folder.glob('*.png')) if self.folder.exists() else []
        self.list.delete(0,'end')
        for p in self.paths:self.list.insert('end',p.stem.rsplit('_',1)[0])
        if self.paths:self.list.selection_set(0)
        self.preview()
    def preview(self):
        self.canvas.delete('all');selected=self.list.curselection()
        if not selected:return
        try:
            with Image.open(self.paths[selected[0]]) as source:
                im=source.copy();im.thumbnail((210,180));self.photo=ImageTk.PhotoImage(im,master=self)
            self.canvas.create_image(110,95,image=self.photo)
        except Exception as error:messagebox.showerror('이미지 확인',str(error),parent=self)
    def add(self):
        path=filedialog.askopenfilename(parent=self,filetypes=[('도장·서명 이미지','*.png *.jpg *.jpeg *.webp *.bmp')])
        if path:
            try:add_stamp(self.folder,path);self.reload()
            except Exception as error:messagebox.showerror('등록 실패',str(error),parent=self)
    def remove(self):
        selected=self.list.curselection()
        if selected and messagebox.askyesno('즐겨찾기 제거','등록한 복사본을 제거할까요? 원본 이미지는 유지됩니다.',parent=self):
            try:self.paths[selected[0]].unlink();self.reload()
            except OSError as error:messagebox.showerror('제거 실패',str(error),parent=self)
    def validate(self):
        if not self.list.curselection():
            messagebox.showinfo('이미지 선택','이미지를 등록하거나 선택하세요.',parent=self);return False
        try:self.chosen=self.paths[self.list.curselection()[0]].read_bytes();return True
        except OSError as error:messagebox.showerror('이미지 열기',str(error),parent=self);return False
    def apply(self):self.result=self.chosen
