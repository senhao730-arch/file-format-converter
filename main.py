"""Chinese desktop UI and command-line entry point."""
from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sys
import threading
import traceback
from pathlib import Path

from converter import CATEGORIES, IMAGE_INPUTS, VIDEO_INPUTS, Options, Cancelled, convert, targets_for

HELP_TEXT = '''使用步骤
1. 选择转换类别，点击「添加文件」，支持一次选择多个文件。
2. 选中列表中的文件，选择目标格式，点击「应用格式」。
3. 设置输出文件夹，点击「开始转换」。双击已完成的项目可打开结果。

PDF 转 Word：可编辑模式适用于包含文字的 PDF，复杂版式可能需要调整。
扫描 PDF 可用「整页图片」模式；它不提供 OCR，文字不可编辑。
PDF 转 PPT：每页作为一张图片插入幻灯片，文字不可单独编辑。

图片：支持 PNG、JPG、WebP、BMP、TIFF、GIF、ICO、AVIF，读取 HEIC/HEIF。
动画转静态格式时只取第一帧。JPG/BMP 透明背景会填充白色。
视频：支持 MP4、MOV、MKV、AVI、WebM、WMV、FLV、MPG、M4V、TS、GIF。
输出第一条视频及第一条音轨；字幕和其他音轨不会保留。

画质 / 分辨率：设置目标宽高、等比留边、裁剪或拉伸，支持锐化与降噪。
宽高均为 0 保持原始，一项为 0 自动按比例计算。提升尺寸不能恢复丢失细节。

左下角「水印检测 / 去水印」：检测 → 选择候选 / 拖动框选 → 预览 → 另存。
候选可能误检或漏检，不识别文字；默认不选中，不会自动删除。
图片支持区域修补或裁剪；动画会处理所有帧。视频支持固定区域、时间段修补，
或整段裁剪；输出 MP4，修补复杂背景可能留下痕迹，不跟踪移动水印。
PDF 优先移除独立图形 / 注释对象。手动框选修补会将涉及的页面转成图片，
该页文字不能选择或搜索，其他页保持原状。
Word 检测独立水印图形对象，只预览候选对象说明，不能框选正文图片。
DOC 需要本机 Microsoft Word，结果另存 DOCX。正文中的普通文字水印可能漏检。

Word/PPT 转 PDF 需要 Microsoft Office 或 LibreOffice。
Office 和可编辑 PDF 转 Word 的取消操作，在当前文件完成后生效。
视频、图片和 PDF 整页转换支持处理中取消。
视频/LibreOffice 的超时设置不限制 Office 或可编辑 PDF 引擎。

所有转换均在本地进行。原文件保留，同名结果自动加编号。
结果默认保存在源文件旁的「转换结果」文件夹。
'''


class ConverterApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        from ui import Card, ModernButton, draw_icon, BG, INK, MUTED, BLUE, LINE
        self.tk, self.ttk, self.root = tk, ttk, root
        self.jobs = {}
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.running = False
        self.closing = False
        self.output_paths = []
        self.serial = 0
        self.category = tk.StringVar(value=CATEGORIES[0])
        self.target = tk.StringVar(value='pdf')
        self.directory = tk.StringVar()
        self.status = tk.StringVar(value='准备就绪，添加文件即可开始')
        self.quality = tk.StringVar(value='90')
        self.dpi = tk.StringVar(value='150')
        self.pdf_mode = tk.StringVar(value='可编辑文字')
        self.video_quality = tk.StringVar(value='均衡')
        self.timeout = tk.StringVar(value='3600')
        self.office_backend = tk.StringVar(value='自动')
        self.queue_count = tk.StringVar(value='0 个文件')
        self.queue_hint = tk.StringVar(value='DOC · DOCX · RTF · ODT · PDF')
        self.settings_note = tk.StringVar()
        self.controls = []
        self.advanced_window = None
        self.media_window = None
        self.watermark_window = None
        self.media_values = dict(width=0, height=0, resize_mode='contain', sharpen=0., denoise=0.)
        self.media_summary = tk.StringVar(value='原始分辨率 · 无额外画质处理')
        self.nav_buttons = {}
        root.title('格式转换工具 · 本地批量转换')
        root.geometry('1260x860')
        root.minsize(1100, 780)
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 9))
        style.configure('TFrame', background='white')
        style.configure('TLabel', background='white', foreground=INK)
        style.configure('TCombobox', padding=(8, 4), fieldbackground='#f8faff', background='#f8faff',
                        foreground=INK, arrowcolor=MUTED, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        style.map('TCombobox', fieldbackground=[('readonly', '#f8faff'), ('disabled', '#f0f3f8')],
                  foreground=[('readonly', INK), ('disabled', '#aab4c5')],
                  bordercolor=[('focus', '#b3c0fb')], selectbackground=[('readonly', '#f8faff')],
                  selectforeground=[('readonly', INK)])
        style.configure('TEntry', padding=(10, 7), fieldbackground='#f8faff', bordercolor=LINE,
                        lightcolor=LINE, darkcolor=LINE, foreground=INK)
        style.map('TEntry', bordercolor=[('focus', '#b3c0fb')])
        style.configure('Treeview', rowheight=40, font=('Microsoft YaHei UI', 9), foreground='#35425b',
                        background='white', fieldbackground='white', borderwidth=0, relief='flat')
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 9), foreground=MUTED,
                        background='#f8faff', borderwidth=0, relief='flat', padding=(10, 11))
        style.layout('Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        style.map('Treeview', background=[('selected', '#e9efff')], foreground=[('selected', '#2845ad')])
        style.map('Treeview.Heading', background=[('active', '#f1f5ff')])
        style.configure('Vertical.TScrollbar', background='#d9e1ef', troughcolor='white',
                        bordercolor='white', arrowcolor='#8795ac', width=10, arrowsize=10, borderwidth=0)
        style.configure('Conversion.Horizontal.TProgressbar', background=BLUE, troughcolor='#edf1f8',
                        bordercolor='#edf1f8', lightcolor=BLUE, darkcolor=BLUE, thickness=5)
        root.option_add('*TCombobox*Listbox.font', ('Microsoft YaHei UI', 9))
        root.option_add('*TCombobox*Listbox.background', 'white')
        root.option_add('*TCombobox*Listbox.selectBackground', '#edf1ff')
        root.option_add('*TCombobox*Listbox.selectForeground', BLUE)

        sidebar = tk.Frame(root, bg='white', width=204)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        tk.Frame(root, width=1, bg=LINE).pack(side='left', fill='y')
        brand = tk.Frame(sidebar, bg='white')
        brand.pack(fill='x', padx=20, pady=(30, 32))
        logo = tk.Canvas(brand, width=38, height=38, bg='white', highlightthickness=0)
        logo.pack(side='left', padx=(0, 10))
        from ui import rounded
        rounded(logo, 0, 0, 38, 38, radius=11, fill=BLUE, outline='')
        draw_icon(logo, 'convert', 9, 9, 'white', 20)
        tk.Label(brand, text='格式转换', bg='white', fg=INK,
                 font=('Microsoft YaHei UI', 13, 'bold')).pack(side='left')
        tk.Label(sidebar, text='转换工具', bg='white', fg='#9ba5b5', anchor='w',
                 font=('Microsoft YaHei UI', 8)).pack(fill='x', padx=25, pady=(0, 12))
        navigation = [('Word ⇄ PDF', '文档格式互转', 'word'), ('PPT ⇄ PDF', '演示文稿互转', 'ppt'),
                      ('图片转换', '常见图片与动画格式', 'image'), ('GIF ⇄ 视频', '动图与视频互转', 'gif'),
                      ('视频转换', '常见视频格式互转', 'video')]
        for category, (title, subtitle, icon) in zip(CATEGORIES, navigation):
            button = ModernButton(sidebar, title, lambda value=category: self.select_category(value),
                                  variant='nav', icon=icon, subtitle=subtitle, width=176, height=64)
            button.pack(fill='x', padx=14, pady=4)
            self.nav_buttons[category] = button
        sidebar_bottom = tk.Frame(sidebar, bg='white')
        sidebar_bottom.pack(side='bottom', fill='x', padx=20, pady=24)
        self.watermark_button = ModernButton(sidebar_bottom, '水印检测 / 去水印', self.show_watermark, variant='soft', width=160)
        self.watermark_button.pack(fill='x', pady=(0, 8))
        ModernButton(sidebar_bottom, '使用说明', self.help, variant='text', width=160).pack(fill='x')
        tk.Frame(sidebar_bottom, bg=LINE, height=1).pack(fill='x', pady=14)
        tk.Label(sidebar_bottom, text='所有文件在本地处理', bg='white', fg=MUTED,
                 font=('Microsoft YaHei UI', 8)).pack(anchor='w')
        tk.Label(sidebar_bottom, text='原文件保留 · 同名自动编号', bg='white', fg='#a0a9b8',
                 font=('Microsoft YaHei UI', 8)).pack(anchor='w', pady=(5, 0))

        shell = tk.Frame(root, bg=BG)
        shell.pack(side='left', fill='both', expand=True, padx=26, pady=24)
        shell.columnconfigure(0, weight=1)
        shell.columnconfigure(1, weight=0, minsize=282)
        shell.rowconfigure(1, weight=1)
        header = tk.Frame(shell, bg=BG)
        header.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 20))
        tk.Label(header, text='文件格式转换', font=('Microsoft YaHei UI', 22, 'bold'),
                 bg=BG, fg=INK).pack(anchor='w')
        tk.Label(header, text='添加文件，选择格式，一键完成转换。', bg=BG, fg=MUTED,
                 font=('Microsoft YaHei UI', 9)).pack(anchor='w', pady=(5, 0))
        badge = tk.Label(header, text='●  本地处理  /  隐私优先', bg='#e8f6ef', fg='#358867',
                         font=('Microsoft YaHei UI', 8), padx=12, pady=7)
        badge.place(relx=1, y=14, anchor='ne')

        queue_card = Card(shell, padding=18)
        queue_card.grid(row=1, column=0, sticky='nsew', padx=(0, 16))
        queue_body = queue_card.body
        queue_body.columnconfigure(0, weight=1)
        queue_body.rowconfigure(2, weight=1)
        queue_header = tk.Frame(queue_body, bg='white')
        queue_header.grid(row=0, column=0, sticky='ew', pady=(0, 14))
        tk.Label(queue_header, text='转换队列', bg='white', fg=INK,
                 font=('Microsoft YaHei UI', 11, 'bold')).pack(side='left')
        tk.Label(queue_header, textvariable=self.queue_count, bg='#f1f4fa', fg=MUTED,
                 font=('Microsoft YaHei UI', 8), padx=8, pady=3).pack(side='left', padx=10)
        self.clear_button = ModernButton(queue_header, '清空', self.clear, variant='text', width=48, height=30)
        self.clear_button.pack(side='right')
        self.remove_button = ModernButton(queue_header, '移除选中', self.remove_selected, variant='text', width=80, height=30)
        self.remove_button.pack(side='right', padx=(0, 3))
        toolbar = tk.Frame(queue_body, bg='white')
        toolbar.grid(row=1, column=0, sticky='ew', pady=(0, 16))
        self.add_button = ModernButton(toolbar, '＋  添加文件', self.add_files, variant='soft', width=118)
        self.add_button.pack(side='left')
        tk.Label(toolbar, textvariable=self.queue_hint, bg='white', fg='#97a2b3',
                 font=('Microsoft YaHei UI', 8)).pack(side='left', padx=14)
        self.list_frame = tk.Frame(queue_body, bg='white')
        self.list_frame.grid(row=2, column=0, sticky='nsew')
        columns = ('file', 'category', 'target', 'status')
        self.tree = ttk.Treeview(self.list_frame, columns=columns, show='headings', selectmode='extended', height=4)
        for col, label, width in zip(columns, ('文件名称', '类别', '目标', '状态'), (200, 100, 60, 120)):
            self.tree.heading(col, text=label, anchor='w')
            self.tree.column(col, width=width, minwidth=55,
                             stretch=(col == 'file'), anchor='w')
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(self.list_frame, orient='vertical', command=self.tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.tag_configure('odd', background='#fafbfe')
        self.tree.tag_configure('done', foreground='#27835d', background='#f1faf5')
        self.tree.tag_configure('error', foreground='#c1565a', background='#fff4f3')
        self.tree.tag_configure('running', foreground=BLUE, background='#f0f4ff')
        self.tree.tag_configure('cancelled', foreground='#8c96a6')
        self.tree.bind('<Double-1>', self.open_item)
        self.empty_state = tk.Frame(self.list_frame, bg='white')
        empty_icon = tk.Canvas(self.empty_state, width=70, height=70, bg='white', highlightthickness=0)
        empty_icon.pack(pady=(0, 12))
        rounded(empty_icon, 0, 0, 70, 70, radius=20, fill='#f0f4ff', outline='')
        draw_icon(empty_icon, 'folder', 20, 20, '#8ea2ef', 30)
        tk.Label(self.empty_state, text='开始你的第一次转换', bg='white', fg='#64728b',
                 font=('Microsoft YaHei UI', 11, 'bold')).pack()
        tk.Label(self.empty_state, text='选择左侧类别，再添加一个或多个文件', bg='white', fg='#9ca6b5',
                 font=('Microsoft YaHei UI', 8)).pack(pady=(7, 0))

        settings_card = Card(shell, padding=20)
        settings_card.grid(row=1, column=1, sticky='nsew')
        settings_outer = settings_card.body
        settings_header = tk.Frame(settings_outer, bg='white')
        settings_header.pack(fill='x', pady=(0, 12))
        tk.Label(settings_header, text='转换设置', bg='white', fg=INK,
                 font=('Microsoft YaHei UI', 11, 'bold')).pack(side='left')
        self.advanced_button = ModernButton(settings_header, '高级', self.show_advanced,
                                            variant='text', width=48, height=28)
        self.advanced_button.pack(side='right')
        settings_viewport = tk.Frame(settings_outer, bg='white')
        settings_viewport.pack(fill='both', expand=True)
        self.settings_canvas = tk.Canvas(settings_viewport, bg='white', bd=0, highlightthickness=0, width=1, height=1)
        self.settings_canvas.pack(side='left', fill='both', expand=True)
        settings_scrollbar = ttk.Scrollbar(settings_viewport, orient='vertical', command=self.settings_canvas.yview)
        self.settings_canvas.configure(yscrollcommand=settings_scrollbar.set)
        settings = tk.Frame(self.settings_canvas, bg='white')
        settings_window = self.settings_canvas.create_window(0, 0, anchor='nw', window=settings)
        def resize_settings(event=None):
            self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox('all'))
            if settings.winfo_reqheight() > self.settings_canvas.winfo_height() + 2:
                if not settings_scrollbar.winfo_manager():
                    settings_scrollbar.pack(side='right', fill='y', padx=(5, 0))
            else:
                settings_scrollbar.pack_forget()
        settings.bind('<Configure>', resize_settings)
        def resize_viewport(event):
            self.settings_canvas.itemconfigure(settings_window, width=event.width)
            resize_settings()
        self.settings_canvas.bind('<Configure>', resize_viewport)
        self.settings_content = settings
        def settings_wheel(event):
            widget = self.root.winfo_containing(event.x_root, event.y_root)
            if widget is not None and str(widget).startswith(str(settings_viewport)):
                self.settings_canvas.yview_scroll(-int(event.delta / 120), 'units')
                return 'break'
        self.root.bind_all('<MouseWheel>', settings_wheel, add='+')
        tk.Label(settings, text='目标格式', bg='white', fg=MUTED, font=('Microsoft YaHei UI', 8)).pack(anchor='w', pady=(0, 6))
        self.target_box = ttk.Combobox(settings, textvariable=self.target, values=('pdf', 'docx'), state='readonly', width=10)
        self.target_box.pack(fill='x')
        self.controls.append((self.target_box, 'readonly'))
        self.apply_button = ModernButton(settings, '应用格式', self.apply_target, variant='soft', width=225, height=32)
        self.apply_button.pack(fill='x', pady=(8, 12))
        tk.Frame(settings, bg=LINE, height=1).pack(fill='x', pady=(0, 10))
        self.media_button = ModernButton(settings, '画质 / 分辨率设置', self.show_media, variant='soft', width=225, height=34)
        self.media_button.pack(fill='x', pady=(0, 6))
        tk.Label(settings, textvariable=self.media_summary, wraplength=218, justify='left', bg='white', fg='#7b879b',
                 font=('Microsoft YaHei UI', 8)).pack(anchor='w', pady=(0, 10))
        paired = tk.Frame(settings, bg='white')
        paired.pack(fill='x', pady=(0, 10))
        paired.columnconfigure(0, weight=1)
        paired.columnconfigure(1, weight=1)
        left = tk.Frame(paired, bg='white')
        left.grid(row=0, column=0, sticky='ew', padx=(0, 10))
        right = tk.Frame(paired, bg='white')
        right.grid(row=0, column=1, sticky='ew')
        self._setting_field(left, '图片质量', self.quality, ('70', '80', '90', '95', '100'), gap=0)
        self._setting_field(right, 'PDF 分辨率', self.dpi, ('96', '150', '200', '300'), gap=0)
        self._setting_field(settings, 'PDF → Word 模式', self.pdf_mode, ('可编辑文字', '整页图片'))
        self._setting_field(settings, '视频质量', self.video_quality, ('小体积', '均衡', '高质量'))
        tk.Label(settings, textvariable=self.settings_note, wraplength=218, justify='left', bg='white',
                 fg='#95a0b2', font=('Microsoft YaHei UI', 8)).pack(anchor='w')

        output_card = Card(shell, padding=16, height=82)
        output_card.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(16, 0))
        output = output_card.body
        output.columnconfigure(1, weight=1)
        tk.Label(output, text='输出位置', bg='white', fg='#4b5a73', font=('Microsoft YaHei UI', 9, 'bold')).grid(row=0, column=0, padx=(0, 14))
        directory_entry = ttk.Entry(output, textvariable=self.directory)
        directory_entry.grid(row=0, column=1, sticky='ew')
        self.controls.append((directory_entry, 'normal'))
        self.browse_button = ModernButton(output, '选择文件夹', self.browse, width=108, height=34)
        self.browse_button.grid(row=0, column=2, padx=(10, 6))
        ModernButton(output, '打开结果', self.open_output, variant='text', width=88, height=34).grid(row=0, column=3)

        actions = tk.Frame(shell, bg=BG)
        actions.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(18, 0))
        actions.columnconfigure(0, weight=1)
        tk.Label(actions, textvariable=self.status, bg=BG, fg='#677690', font=('Microsoft YaHei UI', 8),
                 anchor='w', wraplength=560).grid(row=0, column=0, sticky='ew', padx=(0, 16))
        self.cancel_button = ModernButton(actions, '取消任务', self.request_cancel, width=104, height=42, state='disabled')
        self.cancel_button.grid(row=0, column=1, padx=(0, 10))
        self.start_button = ModernButton(actions, '开始转换  →', self.start, variant='primary', width=152, height=42)
        self.start_button.grid(row=0, column=2)
        self.progress = ttk.Progressbar(actions, maximum=100, style='Conversion.Horizontal.TProgressbar')
        self.progress.grid(row=1, column=0, columnspan=3, sticky='ew', pady=(12, 0))

        log_header = tk.Frame(shell, bg=BG)
        log_header.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(15, 6))
        tk.Label(log_header, text='运行记录', bg=BG, fg='#7e8aa0', font=('Microsoft YaHei UI', 8)).pack(side='left')
        ModernButton(log_header, '保存日志', self.save_log, variant='text', width=80, height=24).pack(side='right')
        self.log_widget = tk.Text(shell, height=2, wrap='word', bg=BG, fg='#8b98ad',
                                  font=('Microsoft YaHei UI', 8), relief='flat', padx=0, pady=0,
                                  highlightthickness=0, state='disabled')
        self.log_widget.grid(row=5, column=0, columnspan=2, sticky='ew')
        self.log('输出位置留空时，保存到源文件旁的「转换结果」文件夹。')
        self.category_changed()
        self.refresh_queue()
        self.root.after(100, self.poll)

    def _setting_field(self, parent, label, variable, values, gap=10):
        frame = self.tk.Frame(parent, bg='white')
        frame.pack(fill='x', pady=(0, gap))
        self.tk.Label(frame, text=label, bg='white', fg='#7b879b',
                      font=('Microsoft YaHei UI', 8)).pack(anchor='w', pady=(0, 6))
        control = self.ttk.Combobox(frame, textvariable=variable, values=values, state='readonly', width=8)
        control.pack(fill='x')
        self.controls.append((control, 'readonly'))

    def select_category(self, category):
        if not self.running:
            self.category.set(category)
            self.category_changed()

    def show_media(self):
        from tkinter import messagebox
        from media import validate_media
        from ui import ModernButton, INK, MUTED
        if self.running:
            return
        if self.media_window is not None and self.media_window.winfo_exists():
            self.media_window.lift()
            return
        window = self.tk.Toplevel(self.root)
        self.media_window = window
        window.title('图片与视频 · 画质 / 分辨率')
        window.geometry('520x640')
        window.resizable(False, False)
        window.transient(self.root)
        window.configure(bg='white')
        body = self.tk.Frame(window, bg='white', padx=28, pady=24)
        body.pack(fill='both', expand=True)
        self.tk.Label(body, text='画质与分辨率', bg='white', fg=INK,
                      font=('Microsoft YaHei UI',17,'bold')).pack(anchor='w',pady=(0,16))
        variables = {key:self.tk.StringVar(value=str(value)) for key,value in self.media_values.items()}
        mode_names = {'contain':'等比适应（留边）','crop':'等比填满（裁剪）','stretch':'拉伸到目标大小'}
        variables['resize_mode'].set(mode_names[self.media_values['resize_mode']])
        preset = self.tk.StringVar(value='自定义 / 原始')
        self.tk.Label(body,text='常用分辨率（横向）',bg='white',fg=MUTED).pack(anchor='w')
        presets = {'自定义 / 原始':(0,0),'480p':(854,480),'720p':(1280,720),'1080p':(1920,1080),'2K':(2560,1440),'4K':(3840,2160)}
        combo = self.ttk.Combobox(body,textvariable=preset,values=tuple(presets),state='readonly')
        combo.pack(fill='x',pady=(6,12))
        def choose_preset(event=None):
            width,height=presets[preset.get()]
            variables['width'].set(str(width))
            variables['height'].set(str(height))
        combo.bind('<<ComboboxSelected>>',choose_preset)
        row = self.tk.Frame(body,bg='white')
        row.pack(fill='x',pady=(0,8))
        for label,key in [('宽度','width'),('高度','height')]:
            self.tk.Label(row,text=label,bg='white',fg=MUTED).pack(side='left',padx=(0,8))
            self.ttk.Entry(row,textvariable=variables[key],width=12).pack(side='left',padx=(0,20))
        self.tk.Label(body,text='单位：像素。宽高均为 0 保持原始；一项为 0 自动按比例计算。',bg='white',fg=MUTED,
                      font=('Microsoft YaHei UI',8),wraplength=450,justify='left').pack(anchor='w',pady=(0,16))
        for label,key,values in [('缩放方式','resize_mode',tuple(mode_names.values())),('锐化强度','sharpen',('0','0.5','1','2','3')),('降噪强度','denoise',('0','0.5','1','2','3'))]:
            self.tk.Label(body,text=label,bg='white',fg=MUTED).pack(anchor='w')
            self.ttk.Combobox(body,textvariable=variables[key],values=values,state='readonly').pack(fill='x',pady=(6,12))
        self.tk.Label(body,text='用于图片与视频转换。提高分辨率和锐化不能恢复源文件中不存在的细节。视频编码会将奇数尺寸调整为偶数。',
                      bg='white',fg=MUTED,font=('Microsoft YaHei UI',8),wraplength=450,justify='left').pack(anchor='w',pady=(0,14))
        def save():
            try:
                values = dict(width=int(variables['width'].get()),height=int(variables['height'].get()),
                              resize_mode={v:k for k,v in mode_names.items()}[variables['resize_mode'].get()],
                              sharpen=float(variables['sharpen'].get()),denoise=float(variables['denoise'].get()))
                validate_media(Options(**values))
            except Exception as exc:
                messagebox.showerror('设置不正确',str(exc),parent=window)
                return
            self.media_values=values
            self.media_summary.set(f'{values["width"] or "自动"} × {values["height"] or "自动"} · 锐化 {values["sharpen"]:g} · 降噪 {values["denoise"]:g}'
                                   if any(values[k] for k in ('width','height','sharpen','denoise')) else '原始分辨率 · 无额外画质处理')
            window.destroy()
        footer=self.tk.Frame(body,bg='white')
        footer.pack(side='bottom',fill='x')
        ModernButton(footer,'应用设置',save,variant='primary',width=112).pack(side='right')
        ModernButton(footer,'取消',window.destroy,variant='text',width=70).pack(side='right',padx=8)

    def build_options(self):
        return Options(quality=int(self.quality.get()),dpi=int(self.dpi.get()),
                       pdf_word_mode='editable' if self.pdf_mode.get()=='可编辑文字' else 'image',
                       video_quality={'小体积':'small','均衡':'balanced','高质量':'high'}[self.video_quality.get()],
                       timeout=int(self.timeout.get()),
                       office_backend={'自动':'auto','Microsoft Office':'office','LibreOffice':'libreoffice'}[self.office_backend.get()],
                       **self.media_values)

    def show_watermark(self):
        from tkinter import messagebox
        from watermark_ui import WatermarkWindow
        if self.running:
            return
        if self.watermark_window and self.watermark_window.window.winfo_exists():
            self.watermark_window.window.lift()
            return
        try:
            options=self.build_options()
        except (ValueError,KeyError) as exc:
            messagebox.showerror('设置不正确',str(exc))
            return
        keys=self.tree.selection()
        source=self.jobs[keys[0]]['source'] if keys else None
        self.watermark_window=WatermarkWindow(self.root,self.directory.get().strip(),source,options)

    def refresh_queue(self):
        self.queue_count.set(f'{len(self.jobs)} 个文件')
        if self.jobs:
            self.empty_state.place_forget()
        else:
            self.empty_state.place(relx=0.5, rely=0.57, anchor='center')
        for index, key in enumerate(self.tree.get_children()):
            state = self.jobs[key]['state']
            tags = ['odd'] if index % 2 else []
            if state in {'done', 'error', 'running', 'cancelled'}:
                tags.append(state)
            self.tree.item(key, tags=tuple(tags))

    def show_advanced(self):
        if self.advanced_window is not None and self.advanced_window.winfo_exists():
            self.advanced_window.lift()
            return
        from ui import ModernButton, BG, INK
        window = self.tk.Toplevel(self.root)
        self.advanced_window = window
        window.title('高级设置')
        window.geometry('470x410')
        window.resizable(False, False)
        window.configure(bg='white')
        window.transient(self.root)
        frame = self.tk.Frame(window, bg='white', padx=28, pady=24)
        frame.pack(fill='both', expand=True)
        self.tk.Label(frame, text='高级设置', bg='white', fg=INK,
                      font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w', pady=(0, 18))
        self._setting_field(frame, '文档转换引擎', self.office_backend, ('自动', 'Microsoft Office', 'LibreOffice'))
        self.tk.Label(frame, text='视频 / LibreOffice 超时（秒）', bg='white', fg='#7b879b',
                      font=('Microsoft YaHei UI', 8)).pack(anchor='w', pady=(0, 6))
        entry = self.ttk.Entry(frame, textvariable=self.timeout)
        entry.pack(fill='x')
        self.controls.append((entry, 'normal'))
        self.tk.Label(frame, text='超时设置不限制 Office 与可编辑 PDF 引擎。', bg='white', fg='#9ba5b5',
                      font=('Microsoft YaHei UI', 8)).pack(anchor='w', pady=12)
        ModernButton(frame, '完成', window.destroy, variant='primary', width=96).pack(side='right')

    def log(self, message):
        self.log_widget.configure(state='normal')
        self.log_widget.insert('end', message + '\n')
        self.log_widget.see('end')
        self.log_widget.configure(state='disabled')

    def category_changed(self):
        from converter import IMAGE_OUTPUTS, VIDEO_OUTPUTS
        choices = {CATEGORIES[0]: ('pdf', 'docx'), CATEGORIES[1]: ('pdf', 'pptx'),
                   CATEGORIES[2]: IMAGE_OUTPUTS, CATEGORIES[3]: VIDEO_OUTPUTS, CATEGORIES[4]: VIDEO_OUTPUTS}
        values = choices[self.category.get()]
        self.target_box.configure(values=values)
        self.target.set(values[0])
        for category, button in self.nav_buttons.items():
            button.configure(selected=category == self.category.get())
        descriptions = {
            CATEGORIES[0]: ('DOC · DOCX · RTF · ODT · PDF', '可编辑模式适合文字 PDF。扫描件可选择整页图片。'),
            CATEGORIES[1]: ('PPT · PPTX · PPS · ODP · PDF', 'PDF 转 PPT 保留页面外观，页内文字不可直接编辑。'),
            CATEGORIES[2]: ('PNG · JPG · WEBP · GIF 等', '透明图像转 JPG / BMP 时填充白色；静态格式仅保存第一帧。'),
            CATEGORIES[3]: ('GIF 与常见视频格式', '动图转视频播放一遍；视频转 GIF 不保留音频。'),
            CATEGORIES[4]: ('MP4 · MOV · MKV · WEBM 等', '视频重新编码，保留第一条视频与第一条音轨。'),
        }
        hint, note = descriptions[self.category.get()]
        self.queue_hint.set(hint)
        self.settings_note.set(note)

    def add_paths(self, paths):
        category, target = self.category.get(), self.target.get()
        skipped = []
        for path in paths:
            source = Path(path).resolve()
            supported = targets_for(source, category)
            if not source.is_file() or not supported:
                skipped.append(source.name)
                continue
            chosen = target if target in supported else supported[0]
            if any(job['source'] == source and job['category'] == category and job['target'] == chosen
                   for job in self.jobs.values()):
                continue
            self.serial += 1
            key = str(self.serial)
            self.jobs[key] = dict(source=source, category=category, target=chosen, state='pending', result=None)
            self.tree.insert('', 'end', iid=key, values=(source.name, category, chosen.upper(), '等待转换'))
        self.refresh_queue()
        self.status.set(f'已添加 {len(self.jobs)} 个任务')
        if skipped:
            self.log('跳过不适用于当前类别的文件：' + '、'.join(skipped))

    def add_files(self):
        from tkinter import filedialog
        from converter import WORD_INPUTS, PPT_INPUTS
        category = self.category.get()
        extensions = {CATEGORIES[0]: WORD_INPUTS | {'pdf'}, CATEGORIES[1]: PPT_INPUTS | {'pdf'},
                      CATEGORIES[2]: IMAGE_INPUTS, CATEGORIES[3]: VIDEO_INPUTS | {'gif'}, CATEGORIES[4]: VIDEO_INPUTS}[category]
        paths = filedialog.askopenfilenames(title='添加待转换文件', filetypes=[
            ('支持的文件', ' '.join('*.' + extension for extension in sorted(extensions))), ('所有文件', '*.*')])
        self.add_paths(paths)

    def apply_target(self):
        target = self.target.get()
        selected = self.tree.selection() or self.tree.get_children()
        skipped = 0
        for key in selected:
            job = self.jobs[key]
            if target not in targets_for(job['source'], job['category']):
                skipped += 1
                continue
            job.update(target=target, state='pending', result=None)
            self.tree.item(key, values=(job['source'].name, job['category'], target.upper(), '等待转换'), tags=())
        self.refresh_queue()
        if skipped:
            self.log(f'{skipped} 个任务不支持 {target.upper()}，已保留原目标格式。')

    def remove_selected(self):
        for key in self.tree.selection():
            self.tree.delete(key)
            self.jobs.pop(key, None)
        self.refresh_queue()

    def clear(self):
        for key in self.tree.get_children():
            self.tree.delete(key)
        self.jobs.clear()
        self.refresh_queue()
        self.progress['value'] = 0
        self.status.set('列表已清空')

    def browse(self):
        from tkinter import filedialog
        if selected := filedialog.askdirectory(title='选择输出文件夹'):
            self.directory.set(selected)

    def open_path(self, path):
        from tkinter import messagebox
        try:
            os.startfile(str(path))
        except OSError as exc:
            messagebox.showerror('无法打开', str(exc))

    def open_item(self, event=None):
        if self.tree.selection():
            job = self.jobs[self.tree.selection()[0]]
            if job['result'] and job['result'].exists():
                self.open_path(job['result'])
            else:
                self.log(str(job['source']))

    def open_output(self):
        from tkinter import messagebox
        path = Path(self.directory.get().strip()) if self.directory.get().strip() else (
            self.output_paths[-1].parent if self.output_paths else None)
        if path and path.is_dir():
            self.open_path(path)
        else:
            messagebox.showinfo('打开结果', '请先完成转换或选择一个已有的输出文件夹。')

    def start(self):
        from tkinter import messagebox
        batch = [(key, job.copy()) for key, job in self.jobs.items() if job['state'] != 'done']
        if not batch:
            messagebox.showinfo('开始转换', '请添加待转换文件。已完成项目不会重复执行；应用格式可重新加入任务。')
            return
        try:
            options = self.build_options()
            if not 1 <= options.quality <= 100 or not 72 <= options.dpi <= 600 or options.timeout < 1:
                raise ValueError('图片质量 1–100，PDF DPI 72–600，超时大于 0。')
        except (ValueError, KeyError) as exc:
            messagebox.showerror('设置不正确', str(exc))
            return
        directory = self.directory.get().strip()
        if self.advanced_window is not None and self.advanced_window.winfo_exists():
            self.advanced_window.destroy()
        if self.media_window is not None and self.media_window.winfo_exists():
            self.media_window.destroy()
        self.cancel.clear()
        self.running = True
        self.set_busy(True)
        self.progress['value'] = 0
        self.log(f'开始批量转换：{len(batch)} 个文件。')
        threading.Thread(target=self.worker, args=(batch, directory, options), daemon=True).start()

    def set_busy(self, busy):
        for button in (self.add_button, self.remove_button, self.clear_button, self.apply_button, self.browse_button, self.start_button):
            button.configure(state='disabled' if busy else 'normal')
        self.advanced_button.configure(state='disabled' if busy else 'normal')
        self.media_button.configure(state='disabled' if busy else 'normal')
        self.watermark_button.configure(state='disabled' if busy else 'normal')
        for button in self.nav_buttons.values():
            button.configure(state='disabled' if busy else 'normal')
        for control, normal in self.controls:
            if control.winfo_exists():
                control.configure(state='disabled' if busy else normal)
        self.cancel_button.configure(state='normal' if busy else 'disabled')

    def worker(self, batch, directory, options):
        successful = failed = 0
        try:
            for index, (key, job) in enumerate(batch):
                if self.cancel.is_set():
                    break
                self.events.put(('state', key, 'running', '转换中…', None))
                output = Path(directory).expanduser() if directory else job['source'].parent / '转换结果'
                def update(fraction, message):
                    self.events.put(('progress', (index + fraction) / len(batch) * 100, f'{index + 1}/{len(batch)} · {job["source"].name} · {message}'))
                try:
                    destination, notes = convert(job['source'], output, job['target'], job['category'], options, self.cancel, update)
                    successful += 1
                    self.events.put(('state', key, 'done', '转换完成', destination))
                    self.events.put(('log', f'✓ {job["source"].name} → {destination}'))
                    for note in notes:
                        self.events.put(('log', '  ' + note))
                except Cancelled:
                    self.events.put(('state', key, 'cancelled', '已取消', None))
                    self.events.put(('log', '已取消：' + job['source'].name))
                    break
                except Exception as exc:
                    failed += 1
                    self.events.put(('state', key, 'error', '转换失败 · 见日志', None))
                    self.events.put(('log', f'✗ {job["source"].name}：{exc}'))
        except Exception:
            self.events.put(('log', traceback.format_exc()))
        finally:
            self.events.put(('finished', successful, failed, self.cancel.is_set()))

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == 'state':
                    _, key, state, label, destination = event
                    self.jobs[key].update(state=state, result=destination)
                    self.tree.set(key, 'status', label)
                    self.refresh_queue()
                    if destination:
                        self.output_paths.append(destination)
                elif event[0] == 'progress':
                    self.progress['value'] = event[1]
                    self.status.set(event[2])
                elif event[0] == 'log':
                    self.log(event[1])
                elif event[0] == 'finished':
                    self.running = False
                    self.set_busy(False)
                    self.progress['value'] = self.progress['value'] if event[3] else 100
                    message = f'{"任务已取消" if event[3] else "批量转换结束"} · 成功 {event[1]} 个，失败 {event[2]} 个'
                    self.status.set(message)
                    self.log(message)
                    if self.closing:
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def request_cancel(self):
        self.cancel.set()
        self.cancel_button.configure(state='disabled')
        self.status.set('正在取消；Office 和可编辑 PDF 转 Word 会先完成当前文件。')

    def close(self):
        if self.watermark_window and self.watermark_window.window.winfo_exists():
            self.watermark_window.close()
            if self.watermark_window.busy:
                self.root.after(200,self.close)
                return
        if self.running:
            self.closing = True
            self.request_cancel()
            self.log('当前任务停止后，窗口会自动关闭。')
        else:
            self.root.destroy()

    def help(self):
        from ui import ModernButton, INK
        window = self.tk.Toplevel(self.root)
        window.title('使用说明')
        window.geometry('760x650')
        window.configure(bg='white')
        window.transient(self.root)
        header = self.tk.Frame(window, bg='white', padx=26, pady=20)
        header.pack(fill='x')
        self.tk.Label(header, text='使用说明', bg='white', fg=INK,
                      font=('Microsoft YaHei UI', 17, 'bold')).pack(side='left')
        ModernButton(header, '知道了', window.destroy, variant='soft', width=86, height=34).pack(side='right')
        body = self.tk.Frame(window, bg='white', padx=26, pady=8)
        body.pack(fill='both', expand=True)
        text = self.tk.Text(body, wrap='word', font=('Microsoft YaHei UI', 9), bg='white',
                            fg='#52617a', bd=0, highlightthickness=0, spacing1=3, spacing3=5)
        text.pack(side='left', fill='both', expand=True)
        scrollbar = self.ttk.Scrollbar(body, orient='vertical', command=text.yview)
        scrollbar.pack(side='right', fill='y', padx=(12, 0))
        text.configure(yscrollcommand=scrollbar.set)
        text.insert('1.0', HELP_TEXT)
        text.configure(state='disabled')

    def save_log(self):
        from tkinter import filedialog, messagebox
        if path := filedialog.asksaveasfilename(title='保存转换日志', defaultextension='.txt', initialfile='转换日志.txt', filetypes=[('文本文件', '*.txt')]):
            try:
                Path(path).write_text(self.log_widget.get('1.0', 'end'), encoding='utf-8')
            except OSError as exc:
                messagebox.showerror('保存失败', str(exc))


def write_result(path, result):
    if path:
        Path(path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    elif sys.stdout is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description='本地文件格式转换工具；无参数启动桌面界面')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--to', dest='extension')
    parser.add_argument('--category', choices=CATEGORIES)
    parser.add_argument('--pdf-word-mode', choices=('editable', 'image'), default='editable')
    parser.add_argument('--quality', type=int, default=90)
    parser.add_argument('--dpi', type=int, default=150)
    parser.add_argument('--video-quality', choices=('small', 'balanced', 'high'), default='balanced')
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--office-backend', choices=('auto', 'office', 'libreoffice'), default='auto')
    parser.add_argument('--width',type=int,default=0)
    parser.add_argument('--height',type=int,default=0)
    parser.add_argument('--resize-mode',choices=('contain','crop','stretch'),default='contain')
    parser.add_argument('--sharpen',type=float,default=0)
    parser.add_argument('--denoise',type=float,default=0)
    watermark_action=parser.add_mutually_exclusive_group()
    watermark_action.add_argument('--watermark-detect',action='store_true',help='输出水印候选 JSON，不删除')
    watermark_action.add_argument('--watermark-ids',help='移除已确认的候选编号，例如 1,3')
    parser.add_argument('--watermark-region',action='append',default=[],help='手动区域 x,y,w,h，均为 0–1；可重复')
    parser.add_argument('--watermark-page',type=int,default=1,help='PDF 框选页码，从 1 开始')
    parser.add_argument('--watermark-method',choices=('inpaint','crop'),default='inpaint')
    parser.add_argument('--watermark-start',type=float,default=0)
    parser.add_argument('--watermark-end',type=float,default=0)
    parser.add_argument('--report', type=Path, help='把命令行结果写入 JSON 文件，适合无控制台 EXE')
    parser.add_argument('--check', action='store_true', help='检查转换依赖，不启动 Office')
    args = parser.parse_args()
    if args.check:
        import importlib
        from converter import ffmpeg_path, libreoffice_path
        result = {}
        for module in ('PIL', 'pymupdf', 'pdf2docx', 'pptx', 'pillow_heif', 'win32com.client','pikepdf','cv2'):
            try:
                importlib.import_module(module)
                result[module] = '可用'
            except Exception as exc:
                result[module] = str(exc)
        try:
            result['ffmpeg'] = ffmpeg_path()
        except Exception as exc:
            result['ffmpeg'] = str(exc)
        result['libreoffice'] = libreoffice_path()
        write_result(args.report, result)
        return 0
    if args.input:
        if args.watermark_detect or args.watermark_ids or args.watermark_region:
            try:
                from dataclasses import asdict
                import watermark
                analysis=watermark.detect(args.input)
                manual_ids=[]
                if not 1<=args.watermark_page<=analysis.pages:
                    raise ValueError('框选页码超出文件范围。')
                for region in args.watermark_region:
                    manual_ids.append(watermark.add_region(analysis,args.watermark_page-1,tuple(map(float,region.split(',')))).id)
                if args.watermark_detect:
                    result=dict(ok=True,kind=analysis.kind,source=str(analysis.source),fingerprint=analysis.fingerprint,
                                pages=analysis.pages,width=analysis.width,height=analysis.height,
                                candidates=[asdict(c) for c in analysis.candidates],notes=analysis.notes)
                else:
                    ids=[i.strip() for i in (args.watermark_ids or '').split(',') if i.strip()]+manual_ids
                    options=Options(quality=args.quality,video_quality=args.video_quality,timeout=args.timeout,
                                    width=args.width,height=args.height,resize_mode=args.resize_mode,
                                    sharpen=args.sharpen,denoise=args.denoise)
                    destination,notes=watermark.remove(analysis,ids,args.output or args.input.parent/'转换结果',
                                args.watermark_method,args.watermark_start,args.watermark_end,options=options)
                    result=dict(ok=True,output=str(destination),notes=notes)
                write_result(args.report,result)
                return 0
            except Exception as exc:
                write_result(args.report,dict(ok=False,error=str(exc)))
                return 1
        if not args.extension or not args.category:
            parser.error('--input 需要 --to 和 --category')
        try:
            options = Options(args.quality,args.dpi,args.pdf_word_mode,args.video_quality,args.timeout,args.office_backend,
                              width=args.width,height=args.height,resize_mode=args.resize_mode,sharpen=args.sharpen,denoise=args.denoise)
            result, notes = convert(args.input, args.output or args.input.parent / '转换结果', args.extension, args.category, options)
            write_result(args.report, {'ok': True, 'output': str(result), 'notes': notes})
            return 0
        except Exception as exc:
            write_result(args.report, {'ok': False, 'error': str(exc)})
            return 1
    if any((args.output,args.extension,args.category,args.report,args.watermark_detect,args.watermark_ids,args.watermark_region)):
        parser.error('命令行转换需要 --input；依赖检查使用 --check')
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    def report_callback_exception(exc_type, value, tb):
        messagebox.showerror('操作失败', ''.join(traceback.format_exception_only(exc_type, value)))
    root.report_callback_exception = report_callback_exception
    ConverterApp(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    raise SystemExit(main())
