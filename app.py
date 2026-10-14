# SPDX-License-Identifier: AGPL-3.0-only
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
from core import load_pdf, parse_pages, save_pdf
from tkinterdnd2 import TkinterDnD, DND_FILES, COPY
from preview import Preview
from editor import PageEditor
from editing import updated_entry


class App:
    def __init__(self, root):
        self.root = root
        self.entries = []
        self.history = []
        root.title('PDF 모아 1.2.1-rc1 · 합치기 / 편집 / 분리')
        root.geometry('1360x900')
        root.minsize(1050, 700)
        root.configure(bg='#eef2f7')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('맑은 고딕', 10))
        style.configure('TButton', padding=(12, 9))
        style.configure('Treeview', rowheight=32, font=('맑은 고딕', 10))
        style.configure('Treeview.Heading', font=('맑은 고딕', 10, 'bold'), padding=8)
        header = tk.Frame(root, bg='#15283f', padx=24, pady=20)
        header.pack(fill='x')
        tk.Label(header, text='PDF 모아', font=('맑은 고딕', 23, 'bold'), fg='white', bg='#15283f').pack(anchor='w')
        tk.Label(header, text='파일 추가 → 페이지 정리 → 새 PDF로 저장', fg='#c6d7ea', bg='#15283f', font=('맑은 고딕', 11)).pack(anchor='w', pady=(5, 0))
        body = ttk.Frame(root, padding=20)
        body.pack(fill='both', expand=True)
        bar = ttk.Frame(body)
        bar.pack(fill='x', pady=(0, 12))
        ttk.Button(bar, text='＋ PDF 추가', command=self.add).pack(side='left')
        ttk.Button(bar, text='전체 선택', command=lambda: self.tree.selection_set(self.tree.get_children())).pack(side='left', padx=6)
        ttk.Button(bar, text='실행 취소', command=self.undo).pack(side='left')
        ttk.Button(bar, text='순서 뒤집기', command=self.reverse_order).pack(side='left', padx=6)
        ttk.Button(bar, text='글자·사진 편집', command=self.edit_selected).pack(side='left')
        ttk.Button(bar, text='목록 비우기', command=self.clear).pack(side='right')
        ttk.Button(bar, text='정보', command=lambda: messagebox.showinfo('PDF 모아 1.2.1-rc1', 'AGPL-3.0-only 공개 소스 프로그램\n보증 없이 제공됩니다. 라이선스 조건에 따라 수정·재배포할 수 있습니다.\n\n소스: https://github.com/Winsh-PEN/pdf-moa\n라이선스: 배포 폴더의 LICENSE 및 licenses\n사용한 편집 엔진: PyMuPDF / MuPDF')).pack(side='right', padx=4)
        ttk.Label(body, text='PDF 파일을 창에 끌어 놓으세요 · 페이지를 드래그해 순서 변경 · Ctrl / Shift로 여러 페이지 선택').pack(anchor='w', pady=(0, 10))
        panes = ttk.Panedwindow(body, orient='horizontal')
        panes.pack(fill='both', expand=True)
        left = ttk.Frame(panes, width=350)
        panes.add(left, weight=0)
        area = ttk.Frame(left)
        area.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(area, columns=('order','file','page','rotation'), show='headings', selectmode='extended')
        for key, label, width in [('order','순서',45),('file','원본 파일',155),('page','페이지',55),('rotation','회전',50)]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=35, anchor='w' if key == 'file' else 'center', stretch=key == 'file')
        scrollbar = ttk.Scrollbar(area, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='left', fill='y')
        controls = ttk.Frame(left, padding=(0,8,0,0))
        controls.pack(fill='x')
        for n, (label, command) in enumerate([('▲ 위로',lambda:self.move(-1)),('▼ 아래로',lambda:self.move(1)),('↻ 90° 회전',self.rotate),('선택 삭제',self.remove),('원본 열기',self.open_source)]):
            ttk.Button(controls, text=label, command=command).grid(row=n//3, column=n%3, sticky='ew', padx=2, pady=2)
        self.preview = Preview(panes)
        panes.add(self.preview, weight=1)
        root.after_idle(lambda: panes.sashpos(0,350))
        ranges = ttk.Frame(body)
        ranges.pack(fill='x', pady=14)
        ttk.Label(ranges, text='순서 번호로 선택').pack(side='left')
        self.range_text = ttk.Entry(ranges, width=26)
        self.range_text.pack(side='left', padx=8)
        ttk.Button(ranges, text='범위 선택', command=self.select_range).pack(side='left')
        ttk.Label(ranges, text='예: 1-3, 5, 8 (현재 목록 번호)').pack(side='left', padx=12)
        footer = ttk.Frame(body)
        footer.pack(fill='x')
        ttk.Button(footer, text='전체 합쳐서 저장', command=lambda:self.export(False)).pack(side='left')
        ttk.Button(footer, text='선택 페이지만 저장', command=lambda:self.export(True)).pack(side='left', padx=8)
        ttk.Button(footer, text='페이지별로 분리 저장', command=self.split).pack(side='left')
        self.status = tk.StringVar()
        ttk.Label(body, textvariable=self.status).pack(anchor='w', pady=(14,0))
        self.tree.bind('<<TreeviewSelect>>', self.selection_changed)
        self.drag_start = None
        self.drag_indices = []
        self.drag_active = False
        self.drop_line = tk.Frame(self.tree, height=3, bg='#1677ff')
        self.tree.bind('<ButtonPress-1>', self.drag_press)
        self.tree.bind('<B1-Motion>', self.drag_motion)
        self.tree.bind('<ButtonRelease-1>', self.drag_release)
        self.tree.bind('<Escape>', self.cancel_drag)
        root.drop_target_register(DND_FILES)
        root.dnd_bind('<<Drop>>', self.drop_files)
        root.bind('<Control-o>', lambda event:self.add())
        root.bind('<Control-z>', lambda event:self.undo())
        self.refresh()

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

    def snapshot(self):
        self.history.append([dict(e) for e in self.entries])
        self.history = self.history[-20:]

    def refresh(self, selection=()):
        self.tree.delete(*self.tree.get_children())
        for i, e in enumerate(self.entries):
            self.tree.insert('', 'end', iid=str(i), values=(i+1, Path(e['path']).name, e.get('source_page',e['page'])+1, f"{e['rotation']}°"))
        self.tree.selection_set([str(i) for i in selection])
        if selection:
            self.tree.see(str(selection[0]))
            self.tree.focus(str(selection[0]))
        self.selection_changed()
        self.update_status()

    def selection_changed(self, event=None):
        self.update_status()
        selected = self.selected()
        focused = self.tree.focus()
        index = int(focused) if focused and int(focused) in selected else (selected[0] if selected else None)
        self.preview.show(self.entries[index] if index is not None else None, index or 0, len(self.entries))

    def update_status(self):
        self.status.set(f"총 {len(self.entries)}페이지 · 선택 {len(self.tree.selection())}페이지" if self.entries else 'PDF 추가 버튼을 눌러 시작하세요.')

    def add(self):
        paths = filedialog.askopenfilenames(filetypes=[('PDF 파일','*.pdf')])
        self.add_paths(paths)

    def drop_files(self, event):
        paths = self.root.tk.splitlist(event.data)
        valid = [p for p in paths if Path(p).is_file() and Path(p).suffix.lower() == '.pdf']
        if valid:
            # Finish the native drop before showing any password or error dialog.
            self.root.after_idle(lambda: self.add_paths(valid))
        else:
            self.root.after_idle(lambda: messagebox.showinfo('PDF 파일 추가', 'PDF 파일을 끌어 놓아 주세요.'))
        return COPY

    def drag_press(self, event):
        # The custom drag handler stops the default Treeview click binding,
        # so explicitly give the list keyboard focus before returning 'break'.
        self.tree.focus_set()
        self.cancel_drag()
        row = self.tree.identify_row(event.y)
        if not row or self.tree.identify_region(event.x, event.y) != 'cell' or event.state & 5:
            return
        self.drag_start = (event.x, event.y)
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
        if not self.drag_active and max(abs(event.x-self.drag_start[0]), abs(event.y-self.drag_start[1])) < 5:
            return 'break'
        self.drag_active = True
        self.tree.configure(cursor='fleur')
        if event.y < 40:
            self.tree.yview_scroll(-1, 'units')
        elif event.y > self.tree.winfo_height() - 25:
            self.tree.yview_scroll(1, 'units')
        _, line_y = self.insertion_at(event.y)
        self.drop_line.place(x=0, y=line_y-1, relwidth=1)
        self.status.set('파란 선 위치에 놓으면 선택한 페이지가 함께 이동합니다.')
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
        self.cancel_drag()
        return 'break'

    def cancel_drag(self, event=None):
        self.drag_start = None
        self.drag_indices = []
        self.drag_active = False
        self.drop_line.place_forget()
        self.tree.configure(cursor='')
        self.update_status()

    def add_paths(self, paths):
        new = []
        for path in paths:
            try:
                try:
                    reader = load_pdf(path)
                except ValueError as error:
                    if str(error) != 'PASSWORD_REQUIRED':
                        raise
                    password = simpledialog.askstring('암호 입력', f'{Path(path).name}\nPDF 암호를 입력하세요.', show='*')
                    if password is None:
                        continue
                    reader = load_pdf(path, password)
                new.extend(dict(path=path, reader=reader, page=p, rotation=0) for p in range(len(reader.pages)))
            except Exception as error:
                messagebox.showerror('파일을 열 수 없습니다', f'{Path(path).name}\n암호 또는 PDF 파일을 확인하세요.\n{error}')
        if new:
            self.snapshot()
            self.entries.extend(new)
            self.refresh([len(self.entries)-len(new)])
            self.tree.focus_set()

    def move(self, direction):
        selected = set(self.selected())
        if not selected:
            return
        self.snapshot()
        for i in sorted(selected, reverse=direction > 0):
            target = i + direction
            if 0 <= target < len(self.entries) and target not in selected:
                self.entries[i], self.entries[target] = self.entries[target], self.entries[i]
                selected.remove(i)
                selected.add(target)
        self.refresh(sorted(selected))

    def reverse_order(self):
        if len(self.entries) < 2:
            return
        selected = self.selected()
        self.snapshot()
        self.entries.reverse()
        self.refresh(sorted(len(self.entries) - 1 - i for i in selected))

    def rotate(self):
        indices = self.selected()
        if indices:
            self.snapshot()
            for i in indices:
                self.entries[i]['rotation'] = (self.entries[i]['rotation'] + 90) % 360
            self.refresh(indices)

    def remove(self):
        indices = self.selected()
        if indices:
            self.snapshot()
            self.entries = [e for i,e in enumerate(self.entries) if i not in indices]
            self.refresh()

    def clear(self):
        if self.entries and messagebox.askyesno('목록 비우기', '추가한 페이지 목록을 비울까요?'):
            self.snapshot()
            self.entries = []
            self.refresh()

    def undo(self):
        if self.history:
            self.entries = self.history.pop()
            self.refresh()

    def select_range(self):
        try:
            indices = parse_pages(self.range_text.get(), len(self.entries))
            self.tree.selection_set([str(i) for i in indices])
            self.tree.see(str(indices[0]))
        except ValueError as error:
            messagebox.showerror('페이지 범위 확인', str(error))

    def open_source(self):
        indices = self.selected()
        if indices:
            os.startfile(self.entries[indices[0]]['path'])

    def export(self, selected_only):
        entries = [self.entries[i] for i in self.selected()] if selected_only else self.entries
        if not entries:
            messagebox.showinfo('페이지 선택', '저장할 페이지를 추가하거나 선택하세요.')
            return
        dest = filedialog.asksaveasfilename(defaultextension='.pdf', initialfile='선택페이지.pdf' if selected_only else '합친문서.pdf', filetypes=[('PDF 파일','*.pdf')])
        if dest:
            try:
                save_pdf(entries, dest)
                messagebox.showinfo('저장 완료', f'{len(entries)}페이지를 저장했습니다.\n{dest}')
            except Exception as error:
                messagebox.showerror('저장 실패', str(error))

    def split(self):
        indices = self.selected() or list(range(len(self.entries)))
        if not indices:
            messagebox.showinfo('PDF 추가', '먼저 PDF를 추가하세요.')
            return
        folder = filedialog.askdirectory(title='분리한 PDF를 저장할 폴더 선택')
        if not folder:
            return
        import tempfile
        output = Path(tempfile.mkdtemp(prefix='PDF_분리_', dir=folder))
        completed = 0
        try:
            for i in indices:
                save_pdf([self.entries[i]], output / f'페이지_{i+1:04d}.pdf')
                completed += 1
            messagebox.showinfo('분리 완료', f'{completed}개의 PDF를 저장했습니다.\n{output}')
            os.startfile(output)
        except Exception as error:
            messagebox.showerror('분리 실패', f'{completed}개 저장 후 중단되었습니다.\n{output}\n{error}')


if __name__ == '__main__':
    root = TkinterDnD.Tk()
    App(root)
    root.mainloop()
