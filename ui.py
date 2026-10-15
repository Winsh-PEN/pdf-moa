# SPDX-License-Identifier: AGPL-3.0-only
"""Shared look and small widgets: theme, DPI scaling, icons, tooltips, dialogs."""
import tkinter as tk
from tkinter import ttk, simpledialog
from icons import icon_png, logo_png, checkbox_png

FONT = '맑은 고딕'
BG = '#f3f5f9'
SURFACE = '#ffffff'
BORDER = '#d5dbe5'
TEXT = '#1f2937'
MUTED = '#64748b'
ACCENT = '#2563eb'
ACCENT_HOVER = '#1d4ed8'
ACCENT_PRESSED = '#1e40af'
SELECT = '#d6e4ff'
CANVAS = '#4b5563'
ICON = '#334155'
ICON_DISABLED = '#b4bcc8'
DANGER = '#b42318'


def enable_dpi_awareness():
    """Call before creating Tk so text stays sharp at 125%/150% display scaling."""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def ui_scale(widget):
    """Pixel factor relative to 96 DPI (1.0 at 100%, 1.5 at 150%)."""
    try:
        return max(1.0, widget.winfo_fpixels('1i') / 96)
    except tk.TclError:
        return 1.0


def px(widget, value):
    return int(round(value * ui_scale(widget)))


def fit_geometry(window, width, height, minimum=(760, 520)):
    """Scale a window size by DPI, keep it on screen and center it."""
    sw, sh = window.winfo_screenwidth(), window.winfo_screenheight()
    w = min(px(window, width), sw - px(window, 40))
    h = min(px(window, height), sh - px(window, 90))
    window.minsize(min(px(window, minimum[0]), w), min(px(window, minimum[1]), h))
    window.geometry(f'{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}')


class Icons:
    """PhotoImage cache; keeps references alive for Tk."""
    def __init__(self, master):
        self.master = master
        self.cache = {}

    def get(self, name, size=18, color=ICON):
        size = px(self.master, size)
        key = (name, size, color)
        if key not in self.cache:
            self.cache[key] = tk.PhotoImage(master=self.master, data=icon_png(name, size, color))
        return self.cache[key]

    def states(self, name, size=18, color=ICON):
        """Image spec for ttk widgets with a lighter icon when disabled."""
        return (self.get(name, size, color), 'disabled', self.get(name, size, ICON_DISABLED))

    def logo(self, size):
        size = px(self.master, size)
        key = ('logo', size)
        if key not in self.cache:
            self.cache[key] = tk.PhotoImage(master=self.master, data=logo_png(size))
        return self.cache[key]

    def checkbox(self, checked, size=16):
        size = px(self.master, size)
        key = ('checkbox', checked, size)
        if key not in self.cache:
            self.cache[key] = tk.PhotoImage(master=self.master, data=checkbox_png(checked, size))
        return self.cache[key]


def icons_for(widget):
    root = widget._root()
    if not hasattr(root, '_moa_icons'):
        root._moa_icons = Icons(root)
    return root._moa_icons


def apply_theme(root):
    style = ttk.Style(root)
    style.theme_use('clam')
    pad = lambda x, y: (px(root, x), px(root, y))
    root.configure(bg=BG)
    root.option_add('*TCombobox*Listbox.font', (FONT, 10))
    style.configure('.', font=(FONT, 10), background=BG, foreground=TEXT, bordercolor=BORDER,
                    lightcolor=BG, darkcolor=BG, troughcolor='#e6eaf0', focuscolor=ACCENT,
                    selectbackground=SELECT, selectforeground=TEXT)
    style.configure('TFrame', background=BG)
    style.configure('Card.TFrame', background=SURFACE, bordercolor=BORDER, relief='solid', borderwidth=1)
    style.configure('Bar.TFrame', background=SURFACE)
    style.configure('TLabel', background=BG, foreground=TEXT)
    style.configure('Muted.TLabel', background=BG, foreground=MUTED)
    style.configure('Bar.TLabel', background=SURFACE, foreground=TEXT)
    style.configure('BarMuted.TLabel', background=SURFACE, foreground=MUTED)
    style.configure('Title.TLabel', background=SURFACE, foreground=TEXT, font=(FONT, 14, 'bold'))
    style.configure('Section.TLabel', background=BG, foreground=TEXT, font=(FONT, 11, 'bold'))
    style.configure('Status.TLabel', background=SURFACE, foreground=MUTED, padding=pad(14, 6))
    style.configure('TSeparator', background=BORDER)
    common = dict(background=SURFACE, bordercolor=BORDER, lightcolor=SURFACE, darkcolor=SURFACE,
                  foreground=TEXT, focusthickness=1, focuscolor=ACCENT)
    style.configure('TButton', padding=pad(12, 6), **common)
    style.map('TButton',
              background=[('disabled', BG), ('pressed', '#dbe3ee'), ('active', '#eef3fa')],
              bordercolor=[('disabled', '#e1e6ee'), ('focus', ACCENT), ('active', '#b8c4d6')],
              lightcolor=[('pressed', '#dbe3ee'), ('active', '#eef3fa')],
              darkcolor=[('pressed', '#dbe3ee'), ('active', '#eef3fa')],
              foreground=[('disabled', '#a3acb9')])
    style.configure('Tool.TButton', padding=pad(9, 5))
    style.configure('Small.TButton', padding=pad(5, 4), width=0)
    style.configure('Icon.TButton', padding=pad(5, 5))
    style.configure('Danger.TButton', foreground=DANGER)
    style.configure('Accent.TButton', padding=pad(16, 7), background=ACCENT, foreground='white',
                    bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT, font=(FONT, 10, 'bold'))
    style.map('Accent.TButton',
              background=[('disabled', '#a9bff0'), ('pressed', ACCENT_PRESSED), ('active', ACCENT_HOVER)],
              bordercolor=[('disabled', '#a9bff0'), ('pressed', ACCENT_PRESSED), ('active', ACCENT_HOVER)],
              lightcolor=[('pressed', ACCENT_PRESSED), ('active', ACCENT_HOVER)],
              darkcolor=[('pressed', ACCENT_PRESSED), ('active', ACCENT_HOVER)],
              foreground=[('disabled', '#eef2ff')])
    style.configure('Toolbutton', padding=pad(10, 5), background=SURFACE, bordercolor=BORDER,
                    lightcolor=SURFACE, darkcolor=SURFACE)
    style.map('Toolbutton',
              background=[('selected', SELECT), ('active', '#eef3fa')],
              bordercolor=[('selected', ACCENT), ('active', '#b8c4d6')],
              lightcolor=[('selected', SELECT)], darkcolor=[('selected', SELECT)])
    style.configure('Small.Toolbutton', padding=pad(8, 2), font=(FONT, 9))
    # clam draws an X for "checked", which reads like "off"; use a box with a tick instead.
    icons = icons_for(root)
    if 'Moa.Checkbutton.indicator' not in style.element_names():
        style.element_create('Moa.Checkbutton.indicator', 'image', icons.checkbox(False),
                             ('selected', icons.checkbox(True)), padding=(0, 0, px(root, 6), 0), sticky='w')
    style.layout('TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
        ('Moa.Checkbutton.indicator', {'side': 'left', 'sticky': ''}),
        ('Checkbutton.focus', {'side': 'left', 'sticky': 'w', 'children': [('Checkbutton.label', {'sticky': 'nswe'})]})]})])
    style.configure('TCheckbutton', background=BG, padding=pad(2, 2))
    style.configure('Bar.TCheckbutton', background=SURFACE)
    style.map('TCheckbutton', background=[('active', BG)])
    style.map('Bar.TCheckbutton', background=[('active', SURFACE)])
    style.configure('TEntry', fieldbackground=SURFACE, bordercolor=BORDER, lightcolor=SURFACE, padding=pad(6, 4))
    style.map('TEntry', bordercolor=[('focus', ACCENT)], lightcolor=[('focus', ACCENT)])
    style.configure('TSpinbox', fieldbackground=SURFACE, bordercolor=BORDER, lightcolor=SURFACE,
                    arrowsize=px(root, 12), padding=pad(4, 3))
    style.map('TSpinbox', bordercolor=[('focus', ACCENT)])
    style.configure('TCombobox', fieldbackground=SURFACE, background=SURFACE, bordercolor=BORDER,
                    lightcolor=SURFACE, arrowsize=px(root, 14), padding=pad(6, 4))
    style.map('TCombobox', fieldbackground=[('readonly', SURFACE)], bordercolor=[('focus', ACCENT)],
              selectbackground=[('readonly', SURFACE)], selectforeground=[('readonly', TEXT)])
    style.configure('Treeview', background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
                    bordercolor=BORDER, lightcolor=SURFACE, darkcolor=SURFACE,
                    rowheight=px(root, 32), font=(FONT, 10))
    style.map('Treeview', background=[('selected', SELECT)], foreground=[('selected', TEXT)])
    style.configure('Treeview.Heading', background='#eef2f7', foreground=MUTED, bordercolor=BORDER,
                    lightcolor='#eef2f7', darkcolor='#eef2f7', font=(FONT, 9, 'bold'), padding=pad(6, 6))
    style.map('Treeview.Heading', background=[('active', '#e4e9f1')])
    style.configure('TRadiobutton', background=BG)
    style.configure('TLabelframe', background=BG, bordercolor=BORDER, lightcolor=BG, darkcolor=BG)
    style.configure('TLabelframe.Label', background=BG, foreground=MUTED, font=(FONT, 9, 'bold'))
    style.configure('Vertical.TScrollbar', background='#e6eaf0', bordercolor=BG, arrowcolor=MUTED,
                    lightcolor='#e6eaf0', darkcolor='#e6eaf0', troughcolor=BG, arrowsize=px(root, 14))
    style.configure('Horizontal.TScrollbar', background='#e6eaf0', bordercolor=BG, arrowcolor=MUTED,
                    lightcolor='#e6eaf0', darkcolor='#e6eaf0', troughcolor=BG, arrowsize=px(root, 14))
    style.configure('Sash', sashthickness=px(root, 6), gripcount=0, background=BG)
    try:
        icons = icons_for(root)
        root.iconphoto(True, icons.logo(64), icons.logo(32), icons.logo(16))
    except Exception:
        pass
    return style


def icon_button(parent, text, icon, command, style='Tool.TButton', tip=None, size=18, color=ICON):
    icons = icons_for(parent)
    button = ttk.Button(parent, text=text, command=command, style=style, compound='left' if text else 'image',
                        image=icons.states(icon, size, color))
    if tip:
        Tooltip(button, tip)
    return button


class Tooltip:
    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self.job = self.window = None
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')

    def schedule(self, event=None):
        self.hide()
        self.job = self.widget.after(self.delay, self.show)

    def show(self):
        self.job = None
        if not self.widget.winfo_exists():
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.attributes('-topmost', True)
        tk.Label(self.window, text=self.text, justify='left', bg='#1f2937', fg='white', font=(FONT, 9),
                 padx=px(self.widget, 8), pady=px(self.widget, 4)).pack()
        self.window.update_idletasks()
        gap = px(self.widget, 4)
        w, h = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        x = self.widget.winfo_rootx() + gap
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + gap
        # Keep the tip on screen: flip above buttons near the bottom edge
        # (the save buttons) and shift left near the right edge.
        if y + h > self.widget.winfo_screenheight() - px(self.widget, 48):
            y = self.widget.winfo_rooty() - h - gap
        x = max(0, min(x, self.widget.winfo_screenwidth() - w - gap))
        self.window.geometry(f'+{x}+{y}')

    def hide(self, event=None):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.window:
            self.window.destroy()
            self.window = None


class Dialog(simpledialog.Dialog):
    """simpledialog.Dialog with Korean buttons and an accent primary button.

    Enter submits only when submit_on_return is true, so multi-line text
    boxes can use Enter for new lines (Ctrl+Enter always submits).
    """
    ok_text = '확인'
    submit_on_return = True

    def buttonbox(self):
        self.configure(bg=BG)
        box = ttk.Frame(self, padding=(px(self, 12), px(self, 4), px(self, 12), px(self, 12)))
        ttk.Button(box, text='취소', command=self.cancel).pack(side='right')
        ttk.Button(box, text=self.ok_text, style='Accent.TButton', command=self.ok).pack(side='right', padx=px(self, 8))
        if self.submit_on_return:
            self.bind('<Return>', self.ok)
        self.bind('<Control-Return>', self.ok)
        self.bind('<Escape>', self.cancel)
        box.pack(side='bottom', fill='x')
        # Re-pack the body after the buttons so it grows with the window
        # and the buttons stay visible when the window is made smaller.
        for child in self.winfo_children():
            if type(child) is tk.Frame:
                child.configure(bg=BG)
                child.pack_forget()
                child.pack(fill='both', expand=True, padx=px(self, 12), pady=(px(self, 12), px(self, 4)))


class ChoiceDialog(simpledialog.Dialog):
    """A message with several buttons. result is the chosen key, None when closed."""

    def __init__(self, parent, title, message, choices, default=None):
        self.message = message
        self.choices = choices  # [(key, label, primary), ...] in display order
        self.default = default
        super().__init__(parent, title)

    def body(self, master):
        self.configure(bg=BG)
        master.configure(bg=BG)
        ttk.Label(master, text=self.message, justify='left', wraplength=px(self, 440)).pack(
            anchor='w', padx=px(self, 8), pady=(px(self, 8), 0))

    def buttonbox(self):
        box = ttk.Frame(self, padding=(px(self, 12), px(self, 12), px(self, 12), px(self, 12)))
        for key, label, primary in reversed(self.choices):
            ttk.Button(box, text=label, style='Accent.TButton' if primary else 'TButton',
                       command=lambda key=key: self.choose(key)).pack(side='right', padx=(px(self, 6), 0))
        box.pack(side='bottom', fill='x')
        self.bind('<Escape>', lambda event: self.choose(None))
        if self.default is not None:
            self.bind('<Return>', lambda event: self.choose(self.default))

    def choose(self, key):
        self.result = key
        self.cancel()


class PasswordDialog(Dialog):
    def __init__(self, parent, title, message):
        self.message = message
        super().__init__(parent, title)

    def body(self, master):
        self.configure(bg=BG)
        master.configure(bg=BG, padx=px(self, 12), pady=px(self, 10))
        ttk.Label(master, text=self.message, wraplength=px(self, 340)).pack(anchor='w', pady=(0, px(self, 8)))
        self.entry = ttk.Entry(master, show='●', width=32)
        self.entry.pack(fill='x')
        return self.entry

    def apply(self):
        self.result = self.entry.get()


def ask_password(parent, title, message):
    return PasswordDialog(parent, title, message).result
