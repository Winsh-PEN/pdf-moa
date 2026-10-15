# SPDX-License-Identifier: AGPL-3.0-only
"""Dialogs of the main window."""
import tkinter as tk
from tkinter import ttk, messagebox
from core import split_groups, RANGE_EXAMPLE
import ui
from ui import px


def default_scope(total, chosen, prefer_selected=False):
    """'selected' when the selection looks intended, else 'all'.

    One selected page is usually just the page that was clicked (adding a
    PDF selects its first page), so the whole list is the better default.
    """
    partial = 0 < chosen < total
    return 'selected' if partial and (chosen > 1 or prefer_selected) else 'all'


class SplitDialog(ui.Dialog):
    """Which pages and how: one page per file, every N pages, or by list-number ranges.

    result: (scope, mode, value) with scope 'all' or 'selected'.
    """
    ok_text = '폴더 선택 후 저장'

    def __init__(self, parent, total, chosen, prefer_selected=False):
        self.total, self.chosen = total, chosen
        self.default_scope = default_scope(total, chosen, prefer_selected)
        super().__init__(parent, '나눠서 저장')

    def body(self, master):
        self.configure(bg=ui.BG)
        master.configure(bg=ui.BG)
        gap = px(self, 8)
        self.scope = tk.StringVar(value=self.default_scope)
        self.mode = tk.StringVar(value='each')
        row = 0
        if 0 < self.chosen < self.total:
            ttk.Label(master, text='나눌 페이지', style='Section.TLabel').grid(row=row, column=0, columnspan=4, sticky='w', pady=(0, gap))
            row += 1
            scope = ttk.Frame(master)
            scope.grid(row=row, column=0, columnspan=4, sticky='w', pady=(0, px(self, 14)))
            ttk.Radiobutton(scope, text=f'전체 {self.total}쪽', variable=self.scope, value='all',
                            command=self.update_labels).pack(side='left', padx=(0, px(self, 16)))
            ttk.Radiobutton(scope, text=f'선택한 {self.chosen}쪽', variable=self.scope, value='selected',
                            command=self.update_labels).pack(side='left')
            row += 1
        ttk.Label(master, text='나누는 방법', style='Section.TLabel').grid(row=row, column=0, columnspan=4, sticky='w', pady=(0, gap))
        row += 1
        self.each_button = ttk.Radiobutton(master, variable=self.mode, value='each')
        self.each_button.grid(row=row, column=0, columnspan=4, sticky='w', pady=(0, gap))
        row += 1
        ttk.Radiobutton(master, text='', variable=self.mode, value='every').grid(row=row, column=0, sticky='w')
        self.every = ttk.Spinbox(master, from_=2, to=9999, width=5)
        self.every.set('2')
        self.every.grid(row=row, column=1, sticky='w')
        ttk.Label(master, text='쪽씩 묶어서 저장 (앞에서부터)').grid(row=row, column=2, columnspan=2, sticky='w', padx=(px(self, 6), 0))
        row += 1
        ttk.Radiobutton(master, text='범위마다 한 파일', variable=self.mode, value='ranges').grid(
            row=row, column=0, columnspan=2, sticky='w', pady=(gap, 0))
        self.ranges = ttk.Entry(master, width=24)
        self.ranges.grid(row=row, column=2, sticky='w', padx=(px(self, 6), 0), pady=(gap, 0))
        row += 1
        ttk.Label(master, text=f'전체 목록 번호 기준 · {RANGE_EXAMPLE} → 파일 3개', style='Muted.TLabel').grid(
            row=row, column=2, columnspan=2, sticky='w', padx=(px(self, 6), 0))
        row += 1
        ttk.Label(master, text='고른 폴더 안에 PDF_분리_날짜_시간 폴더를 새로 만들어 저장합니다.', style='Muted.TLabel').grid(
            row=row, column=0, columnspan=4, sticky='w', pady=(px(self, 14), 0))
        # Typing in a field chooses its option, so the fields stay enabled.
        self.every.bind('<FocusIn>', lambda event: self.mode.set('every'))
        self.ranges.bind('<FocusIn>', lambda event: self.mode.set('ranges'))
        self.update_labels()
        return self.each_button

    def count(self):
        return self.chosen if self.scope.get() == 'selected' else self.total

    def update_labels(self):
        self.each_button.configure(text=f'한 쪽씩 각각 저장  (파일 {self.count()}개)')

    def validate(self):
        mode = self.mode.get()
        try:
            if mode == 'every':
                try:
                    value = int(self.every.get())
                except ValueError:
                    raise ValueError('한 파일에 넣을 쪽수를 숫자로 입력하세요.') from None
                split_groups(list(range(self.count())), 'every', value)
            elif mode == 'ranges':
                value = self.ranges.get()
                split_groups([], 'ranges', value, self.total)
            else:
                value = None
        except ValueError as error:
            messagebox.showerror('나누는 방법 확인', str(error), parent=self)
            return False
        self.choice = (self.scope.get(), mode, value)
        return True

    def apply(self):
        self.result = self.choice
