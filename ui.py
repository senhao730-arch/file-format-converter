"""Small native Tk widgets for the desktop application's visual theme."""
import tkinter as tk

BG = '#f4f6fb'
INK = '#17243b'
MUTED = '#7b879b'
BLUE = '#4263eb'
LINE = '#e7ebf3'


def rounded(canvas, x, y, width, height, radius=12, **kwargs):
    radius = min(radius, width / 2, height / 2)
    return canvas.create_polygon(
        x + radius, y, x + width - radius, y, x + width, y,
        x + width, y + radius, x + width, y + height - radius,
        x + width, y + height, x + width - radius, y + height,
        x + radius, y + height, x, y + height,
        x, y + height - radius, x, y + radius, x, y,
        smooth=True, splinesteps=24, **kwargs)


class ModernButton(tk.Canvas):
    def __init__(self, parent, text, command, *, width=108, height=38,
                 variant='secondary', icon=None, subtitle=None, state='normal', **kwargs):
        super().__init__(parent, width=width, height=height, highlightthickness=0,
                         bd=0, bg=parent.cget('bg'), takefocus=True, cursor='hand2', **kwargs)
        self.text, self.command = text, command
        self.variant, self.icon, self.subtitle = variant, icon, subtitle
        self.state, self.hovered, self.selected, self.focused = state, False, False, False
        self.bind('<Configure>', lambda event: self.draw())
        self.bind('<Enter>', lambda event: self._hover(True))
        self.bind('<Leave>', lambda event: self._hover(False))
        self.bind('<Button-1>', self._click)
        self.bind('<Return>', self._click)
        self.bind('<space>', self._click)
        self.bind('<FocusIn>', lambda event: self._focus(True))
        self.bind('<FocusOut>', lambda event: self._focus(False))
        self.draw()

    def configure(self, cnf=None, **kwargs):
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
            cnf = None
        for name in ('state', 'text', 'selected'):
            if name in kwargs:
                setattr(self, name, kwargs.pop(name))
        result = super().configure(cnf, **kwargs)
        self.draw()
        return result

    config = configure

    def _hover(self, value):
        self.hovered = value
        self.draw()

    def _focus(self, value):
        self.focused = value
        self.draw()

    def _click(self, event=None):
        if self.state != 'disabled':
            self.focus_set()
            self.command()
        return 'break'

    def draw(self):
        self.delete('all')
        width = max(self.winfo_width(), int(float(super().cget('width'))))
        height = max(self.winfo_height(), int(float(super().cget('height'))))
        disabled = self.state == 'disabled'
        self.configure_cursor(disabled)
        fill, color, outline = '#ffffff', '#44516a', LINE
        if self.variant == 'primary':
            fill, color, outline = ('#3452d0' if self.hovered else BLUE), 'white', ''
        elif self.variant == 'soft':
            fill, color, outline = ('#e2e9ff' if self.hovered else '#edf1ff'), BLUE, ''
        elif self.variant == 'text':
            fill, outline = self.cget('bg'), ''
            if self.hovered:
                fill, color = '#eef2fa', BLUE
        elif self.variant == 'nav':
            fill, outline = self.cget('bg'), ''
            if self.selected:
                fill, color = '#edf1ff', BLUE
            elif self.hovered:
                fill = '#f5f7fc'
        elif self.hovered:
            fill, outline = '#f7f9ff', '#ccd7f7'
        if disabled:
            fill, color, outline = '#f0f3f8', '#aab4c5', ''
        if self.focused and not disabled:
            outline = '#a6b5fb'
        rounded(self, 1, 1, width - 2, height - 2, radius=9, fill=fill, outline=outline)
        if self.variant == 'nav':
            if self.selected:
                rounded(self, 7, 17, 3, height - 34, radius=1, fill=BLUE, outline='')
            draw_icon(self, self.icon, 22, height / 2 - 10, color, 20)
            self.create_text(54, height / 2 - 8, text=self.text, anchor='w', fill=color,
                             font=('Microsoft YaHei UI', 10, 'bold' if self.selected else 'normal'))
            self.create_text(54, height / 2 + 12, text=self.subtitle or '', anchor='w', fill=MUTED,
                             font=('Microsoft YaHei UI', 8))
        else:
            self.create_text(width / 2, height / 2, text=self.text, fill=color,
                             font=('Microsoft YaHei UI', 9, 'bold' if self.variant == 'primary' else 'normal'))

    def configure_cursor(self, disabled):
        super().configure(cursor='arrow' if disabled else 'hand2', takefocus=not disabled)


class Card(tk.Canvas):
    def __init__(self, parent, padding=18, **kwargs):
        kwargs.setdefault('width', 1)
        kwargs.setdefault('height', 1)
        super().__init__(parent, bg=BG, bd=0, highlightthickness=0, **kwargs)
        self.padding = padding
        self.body = tk.Frame(self, bg='white')
        self.window = self.create_window(padding, padding, anchor='nw', window=self.body)
        self.bind('<Configure>', self.resize)

    def resize(self, event):
        self.delete('surface')
        rounded(self, 1, 2, event.width - 3, event.height - 3, radius=16,
                fill='#e9edf5', outline='', tags='surface')
        rounded(self, 1, 1, event.width - 3, event.height - 4, radius=16,
                fill='white', outline=LINE, tags='surface')
        self.tag_lower('surface', self.window)
        self.itemconfigure(self.window, width=max(1, event.width - 2 * self.padding),
                           height=max(1, event.height - 2 * self.padding))


def draw_icon(canvas, kind, x, y, color=BLUE, size=20):
    def line(points, **kwargs):
        coords = []
        for px, py in points:
            coords.extend((x + px * size / 20, y + py * size / 20))
        canvas.create_line(*coords, fill=color, width=1.7, capstyle='round', joinstyle='round', **kwargs)
    if kind in {'word', 'ppt'}:
        line([(4, 1), (12, 1), (17, 6), (17, 19), (4, 19), (4, 1)])
        line([(12, 1), (12, 6), (17, 6)])
        if kind == 'word':
            line([(7, 10), (14, 10)])
            line([(7, 14), (12, 14)])
        else:
            canvas.create_rectangle(x + 7 * size / 20, y + 9 * size / 20,
                                    x + 14 * size / 20, y + 15 * size / 20, outline=color, width=1.4)
    elif kind == 'image':
        line([(2, 2), (18, 2), (18, 18), (2, 18), (2, 2)])
        line([(3, 15), (8, 10), (12, 14), (15, 11), (18, 14)])
        canvas.create_oval(x + size * .55, y + size * .22, x + size * .72, y + size * .39,
                           fill=color, outline='')
    elif kind == 'gif':
        line([(4, 5), (17, 5), (17, 18), (4, 18), (4, 5)])
        line([(1, 14), (1, 2), (13, 2)])
        line([(9, 9), (13, 12), (9, 15), (9, 9)])
    elif kind == 'video':
        line([(2, 4), (13, 4), (13, 16), (2, 16), (2, 4)])
        line([(13, 8), (19, 5), (19, 15), (13, 12)])
    elif kind == 'convert':
        line([(2, 6), (18, 6), (14, 2)])
        line([(18, 14), (2, 14), (6, 18)])
    elif kind == 'folder':
        line([(1, 6), (1, 3), (8, 3), (10, 6), (19, 6), (17, 18), (2, 18), (1, 6), (19, 6)])
    else:
        line([(10, 2), (10, 18)])
        line([(2, 10), (18, 10)])
