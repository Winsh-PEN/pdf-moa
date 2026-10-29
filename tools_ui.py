# SPDX-License-Identifier: AGPL-3.0-only
import multiprocessing
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import os
import pymupdf as fitz
from editing import page_bytes, updated_entry
from document_tools import batch_worker, search_worker, save_project, load_project, combined_size
import ui


class Progress(tk.Toplevel):
    def __init__(self,parent,target,args,total):
        super().__init__(parent)
        self.result=None;self.job=None;self.process=None;self.connection=None
        self.title('문서 처리 중');self.transient(parent)
        self.label=ttk.Label(self,text=f'준비 중… 0 / {total}',padding=20);self.label.pack()
        ttk.Button(self,text='취소',command=self.close).pack(pady=10)
        self.protocol('WM_DELETE_WINDOW',self.close);self.bind('<Escape>',lambda e:self.close())
        self.grab_set();self.total=total;self.last=time.monotonic()
        try:
            ctx=multiprocessing.get_context('spawn');self.connection,sender=ctx.Pipe(False)
            self.process=ctx.Process(target=target,args=(sender,*args),daemon=True)
            self.process.start();sender.close();self.job=self.after(100,self.poll);self.wait_window()
        except Exception:
            self.close();raise

    def poll(self):
        self.job=None
        try:
            while self.connection.poll():
                status,value=self.connection.recv()
                if status=='progress':
                    self.label.configure(text=f'처리 중… {value} / {self.total}');self.last=time.monotonic()
                else:
                    if status=='ok':self.result=value
                    else:messagebox.showerror('처리 실패',value,parent=self)
                    self.close();return
            if not self.process.is_alive():raise ValueError('처리가 중단되었습니다. 더 적은 페이지로 다시 시도하세요.')
            if time.monotonic()-self.last>180:raise ValueError('한 페이지 처리 시간이 너무 깁니다. 더 작은 문서로 시도하세요.')
            self.job=self.after(100,self.poll)
        except Exception as error:
            messagebox.showerror('처리 실패',str(error),parent=self);self.close()

    def close(self):
        if self.job:self.after_cancel(self.job);self.job=None
        if self.process is not None and self.process.pid:
            if self.process.is_alive():self.process.terminate()
            self.process.join(timeout=1);self.process.close();self.process=None
        if self.connection:self.connection.close();self.connection=None
        self.grab_release()
        if self.master.winfo_exists():self.master.grab_set()
        self.destroy()


class ResultPreview(ui.Dialog):
    ok_text='전체 결과 적용'
    def __init__(self,parent,before,after,title,sizes=None):
        self.sizes=sizes
        self.before=before;self.after_pages=after;self.index=0
        super().__init__(parent,title)
    def body(self,frame):
        old,new=self.sizes or (sum(map(len,self.before)),sum(map(len,self.after_pages)))
        label='전체 목록 PDF 저장 기준' if self.sizes else '페이지 데이터 합계 (최종 저장 크기와 다를 수 있음)'
        ttk.Label(frame,text=f'{len(self.before)}페이지 · {label}\n{old/1024/1024:.2f} → {new/1024/1024:.2f} MB').pack()
        bar=ttk.Frame(frame);bar.pack(fill='x',pady=8)
        ttk.Button(bar,text='◀ 이전',command=lambda:self.move(-1)).pack(side='left')
        self.label=ttk.Label(bar);self.label.pack(side='left',padx=12)
        ttk.Button(bar,text='다음 ▶',command=lambda:self.move(1)).pack(side='left')
        self.original=tk.BooleanVar(value=False)
        ttk.Checkbutton(bar,text='변경 전 보기',variable=self.original,command=self.draw).pack(side='right')
        self.canvas=tk.Canvas(frame,width=640,height=440,bg=ui.CANVAS,highlightthickness=0);self.canvas.pack(fill='both',expand=True)
        self.draw()
    def move(self,step):self.index=max(0,min(len(self.before)-1,self.index+step));self.draw()
    def draw(self):
        self.label.configure(text=f'{self.index+1} / {len(self.before)}')
        data=(self.before if self.original.get() else self.after_pages)[self.index]
        with fitz.open(stream=data,filetype='pdf') as doc:
            p=doc[0];scale=min(620/p.rect.width,420/p.rect.height)
            pix=p.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
            self.photo=tk.PhotoImage(master=self,data=pix.tobytes('png'))
        self.canvas.delete('all');self.canvas.create_image(320,220,image=self.photo)
    def apply(self):self.result=True


class ToolsWindow(tk.Toplevel):
    def __init__(self,app):
        super().__init__(app.root);self.app=app;self.hits=[]
        self.title('문서 도구');self.transient(app.root);self.grab_set()
        self.geometry('720x650');self.minsize(650,550)
        top=ttk.Frame(self,padding=12);top.pack(fill='x')
        ttk.Button(top,text='작업 저장…',command=self.save_work).pack(side='left')
        ttk.Button(top,text='작업 이어 열기…',command=self.open_work).pack(side='left',padx=8)
        ttk.Label(top,text='순서·편집 내용을 .moa 파일에 보관').pack(side='left')
        scope=ttk.Frame(self,padding=12);scope.pack(fill='x')
        self.scope=tk.StringVar(value='all')
        ttk.Label(scope,text='처리 대상').pack(side='left')
        ttk.Radiobutton(scope,text='전체 페이지',variable=self.scope,value='all').pack(side='left',padx=10)
        ttk.Radiobutton(scope,text='메인 목록의 선택 페이지',variable=self.scope,value='selected').pack(side='left')
        notebook=ttk.Notebook(self);notebook.pack(fill='both',expand=True,padx=12,pady=6)
        search=ttk.Frame(notebook,padding=12);notebook.add(search,text='전체 검색')
        bar=ttk.Frame(search);bar.pack(fill='x')
        self.query=ttk.Entry(bar);self.query.pack(side='left',fill='x',expand=True)
        ttk.Button(bar,text='찾기',command=self.search).pack(side='left',padx=8)
        self.query.bind('<Return>',lambda e:self.search())
        ttk.Label(search,text='검색 결과를 선택하면 메인 미리보기가 해당 페이지로 이동합니다.\n스캔 문서는 먼저 검색 가능한 OCR을 실행하세요.').pack(anchor='w',pady=8)
        self.results=tk.Listbox(search);self.results.pack(fill='both',expand=True)
        self.results.bind('<<ListboxSelect>>',self.jump)
        self.search_status=ttk.Label(search);self.search_status.pack(anchor='w')
        self.vars={}
        def tab(label,description):
            f=ttk.Frame(notebook,padding=16);notebook.add(f,text=label)
            ttk.Label(f,text=description,wraplength=620,justify='left').pack(anchor='w',pady=(0,16));return f
        def field(f,key,label,value):
            row=ttk.Frame(f);row.pack(fill='x',pady=5);ttk.Label(row,text=label,width=26).pack(side='left')
            var=tk.StringVar(value=str(value));self.vars[key]=var;ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True)
        f=tab('검색용 OCR','문서의 모습은 그대로 두고 보이지 않는 한글·영문 글자를 추가합니다.\n이미 글자가 있는 페이지는 건너뜁니다. 인식 오류가 있을 수 있으며, 복합 문서는 스캔 부분이 건너뛰어질 수 있습니다.')
        ttk.Button(f,text='OCR 실행 후 미리보기',command=lambda:self.run('ocr')).pack(anchor='w')
        f=tab('용량 줄이기','포함된 사진·스캔 이미지를 JPEG로 압축합니다. 글자와 도형은 유지합니다.\n투명 이미지는 건너뛰고, 용량이 늘어나는 페이지는 원래대로 둡니다.')
        field(f,'quality','JPEG 품질 (20~95)',75);field(f,'pixels','이미지 긴 변 최대 픽셀',1800)
        ttk.Button(f,text='압축 결과 비교',command=lambda:self.run('compress')).pack(anchor='w',pady=16)
        f=tab('자르기·기울기','각 가장자리에서 잘라낼 길이(mm)를 입력하세요.\n기울기는 직접 조절합니다(-15~15도). 양수는 반시계 방향입니다.\n기울기 보정 시 잘린 화면 안에 맞춰 내용 크기가 조금 줄어들 수 있습니다.')
        for key,label in [('left','왼쪽'),('top','위쪽'),('right','오른쪽'),('bottom','아래쪽')]:field(f,key,label+' 여백 (mm)',0)
        field(f,'angle','기울기 보정 (도)',0)
        ttk.Button(f,text='자르기·보정 미리보기',command=lambda:self.run('crop')).pack(anchor='w',pady=12)
        f=tab('번호·워터마크','{n}은 처리 대상 중 순서, {total}은 처리할 총 페이지 수입니다.\n예: {n} / {total} 또는 검토용 · {n}')
        field(f,'text','문구','{n} / {total}');field(f,'size','글자 크기 (pt)',12);field(f,'opacity','불투명도 (0.05~1)',1)
        self.position=tk.StringVar(value='bottom')
        ttk.Radiobutton(f,text='아래 가운데 (페이지 번호)',variable=self.position,value='bottom').pack(anchor='w',pady=8)
        ttk.Radiobutton(f,text='페이지 가운데 (워터마크)',variable=self.position,value='center').pack(anchor='w')
        ttk.Button(f,text='번호·워터마크 미리보기',command=lambda:self.run('mark')).pack(anchor='w',pady=16)
        ttk.Button(self,text='닫기',command=self.destroy).pack(anchor='e',padx=12,pady=10)
        self.bind('<Escape>',lambda e:self.destroy())
        self.query.focus_set()

    def indices(self):
        result=self.app.selected() if self.scope.get()=='selected' else list(range(len(self.app.entries)))
        if not result:raise ValueError('처리할 PDF 페이지를 추가하거나 선택하세요.')
        return result

    def pages(self,indices):
        self.configure(cursor='watch');self.update_idletasks()
        try:return [page_bytes(self.app.entries[i]) for i in indices]
        finally:self.configure(cursor='')

    def search(self):
        try:
            query=self.query.get().strip()
            if not query:raise ValueError('검색어를 입력하세요.')
            indices=self.indices();pages=self.pages(indices)
            hits=Progress(self,search_worker,(pages,query),len(pages)).result
            if hits is None:return
            self.hits=[(indices[i],text) for i,text in hits];self.results.delete(0,'end')
            for i,text in self.hits:self.results.insert('end',f'{i+1}쪽 · {text}')
            self.search_status.configure(text=f'{len(self.hits)}개 줄에서 찾았습니다.')
        except Exception as error:messagebox.showerror('검색 확인',str(error),parent=self)

    def jump(self,event=None):
        selected=self.results.curselection()
        if not selected:return
        i=self.hits[selected[0]][0];self.app.tree.selection_set(str(i));self.app.tree.focus(str(i));self.app.tree.see(str(i));self.app.selection_changed()

    def run(self,mode):
        try:
            indices=self.indices();pages=self.pages(indices)
            options={k:v.get() for k,v in self.vars.items()};options['position']=self.position.get()
            output=Progress(self,batch_worker,(pages,mode,options),len(pages)).result
            if output is None:return
            if all(a==b for a,b in zip(pages,output)):
                messagebox.showinfo('변경 없음','처리할 내용이 없거나 더 줄일 수 없습니다. 기존 페이지를 유지합니다.',parent=self);return
            replacements=[updated_entry(self.app.entries[i],data) if data!=old else self.app.entries[i] for i,data,old in zip(indices,output,pages)]
            sizes=None
            if mode=='compress':
                trial=list(self.app.entries)
                for i,e in zip(indices,replacements):trial[i]=e
                sizes=(combined_size(self.app.entries,self.app.bookmarks.get()),combined_size(trial,self.app.bookmarks.get()))
                if sizes[1]>=sizes[0]:
                    messagebox.showinfo('압축 효과 없음','공유 이미지·글꼴까지 고려하면 저장 용량이 줄지 않아 기존 목록을 유지합니다.',parent=self);return
            accepted=ResultPreview(self,pages,output,'결과 확인 · 적용 전 비교',sizes=sizes).result
            self.grab_set()
            if not accepted:return
            self.app.snapshot()
            for i,e in zip(indices,replacements):self.app.entries[i]=e
            self.app.refresh(indices);self.hits=[];self.results.delete(0,'end')
            messagebox.showinfo('적용 완료','목록에 반영했습니다. 메인 창에서 PDF를 저장하세요. Ctrl+Z로 되돌릴 수 있습니다.',parent=self)
        except Exception as error:messagebox.showerror('문서 도구',str(error),parent=self)

    def save_work(self):
        if not self.app.entries:return
        path=filedialog.asksaveasfilename(parent=self,title='작업 저장',defaultextension='.moa',filetypes=[('PDF 모아 작업','*.moa')])
        if not path:return
        try:
            if any(os.path.normcase(str(Path(p).resolve()))==os.path.normcase(str(Path(path).resolve())) for p in self.app.protected_paths()):raise ValueError('원본 파일과 다른 이름을 사용하세요.')
            save_project(self.app.entries,path,self.app.bookmarks.get());self.app.saved_state=self.app.state_signature()
            messagebox.showinfo('작업 저장','페이지와 편집 내용이 저장되었습니다. 원본 파일 없이도 이어 열 수 있습니다.\n실행 취소 기록과 편집 창의 개별 이동 항목은 저장되지 않습니다.',parent=self)
        except Exception as error:messagebox.showerror('작업 저장 실패',str(error),parent=self)

    def open_work(self):
        path=filedialog.askopenfilename(parent=self,title='작업 이어 열기',filetypes=[('PDF 모아 작업','*.moa')])
        if not path:return
        try:
            entries,bookmarks=load_project(path)
            if self.app.entries and not messagebox.askyesno('작업 열기','현재 목록을 작업 파일로 바꿀까요? 실행 취소로 현재 목록에 돌아올 수 있습니다.',parent=self):return
            self.app.snapshot();self.app.entries=entries;self.app.bookmarks.set(bookmarks);self.app.refresh([0] if entries else [])
            self.app.saved_state=self.app.state_signature();self.hits=[];self.results.delete(0,'end')
        except Exception as error:messagebox.showerror('작업 열기 실패',str(error),parent=self)
