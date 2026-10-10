"""Review-first watermark workflow; workers never access Tk widgets."""
import queue
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageTk
from converter import Cancelled, Options
import watermark


class WatermarkWindow:
    def __init__(self, parent, directory='', source=None, options=None):
        import tkinter as tk
        from tkinter import ttk
        from ui import ModernButton, BG, INK, MUTED
        self.tk, self.ttk = tk, ttk
        self.window = tk.Toplevel(parent)
        self.window.title('水印工具 · 检测、预览、另存')
        self.window.geometry('1180x860')
        self.window.minsize(1000,760)
        self.window.configure(bg=BG)
        self.window.transient(parent)
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.options = options or Options()
        self.analysis = None
        self.selected = set()
        self.busy = self.closing = False
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.scratch = tempfile.TemporaryDirectory(prefix='watermark-preview-')
        self.result = None
        self.result_pictures = {}
        self.source = tk.StringVar(value=str(source or ''))
        self.directory = tk.StringVar(value=directory)
        self.status = tk.StringVar(value='选择文件并检测；候选默认不选中，支持在预览上拖动框选。')
        self.page = tk.StringVar(value='1')
        self.view = tk.StringVar(value='原图 / 原文件')
        self.method = tk.StringVar(value='区域修补')
        self.start, self.end = tk.StringVar(value='0'), tk.StringVar(value='0')
        self.controls, self.buttons = [], []
        header = tk.Frame(self.window,bg=BG,padx=24,pady=18)
        header.pack(fill='x')
        tk.Label(header,text='水印检测与处理',bg=BG,fg=INK,font=('Microsoft YaHei UI',19,'bold')).pack(anchor='w')
        tk.Label(header,text='选择候选 → 预览效果 → 另存结果',bg=BG,fg=MUTED,font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(4,12))
        row = tk.Frame(header,bg=BG)
        row.pack(fill='x')
        entry = ttk.Entry(row,textvariable=self.source)
        entry.pack(side='left',fill='x',expand=True)
        self.controls.append((entry,'normal'))
        self.button(row,'选择文件',self.choose,width=92).pack(side='left',padx=8)
        self.button(row,'检测候选',self.detect,variant='primary',width=100).pack(side='left')
        content = tk.Frame(self.window,bg=BG,padx=24)
        content.pack(fill='both',expand=True)
        content.columnconfigure(0,weight=1)
        content.columnconfigure(1,weight=0,minsize=350)
        content.rowconfigure(0,weight=1)
        left = tk.Frame(content,bg='white',padx=12,pady=12)
        left.grid(row=0,column=0,sticky='nsew',padx=(0,14))
        toolbar = tk.Frame(left,bg='white')
        toolbar.pack(fill='x',pady=(0,10))
        tk.Label(toolbar,text='页面 / 帧 / 对象',bg='white',fg=MUTED).pack(side='left')
        self.page_box = ttk.Combobox(toolbar,textvariable=self.page,values=('1',),state='readonly',width=6)
        self.page_box.pack(side='left',padx=8)
        self.page_box.bind('<<ComboboxSelected>>',lambda e:self.draw())
        self.controls.append((self.page_box,'readonly'))
        self.view_box = ttk.Combobox(toolbar,textvariable=self.view,values=('原图 / 原文件','处理效果'),state='readonly',width=13)
        self.view_box.pack(side='right')
        self.view_box.bind('<<ComboboxSelected>>',lambda e:self.draw())
        self.controls.append((self.view_box,'readonly'))
        self.canvas = tk.Canvas(left,bg='#eef1f7',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<ButtonPress-1>',self.drag_begin)
        self.canvas.bind('<B1-Motion>',self.drag_move)
        self.canvas.bind('<ButtonRelease-1>',self.drag_end)
        tk.Label(left,text='拖动框选新增区域。蓝框为已选，灰框为未选候选。',bg='white',fg=MUTED,
                 font=('Microsoft YaHei UI',8)).pack(anchor='w',pady=(10,0))
        right = tk.Frame(content,bg='white',padx=14,pady=14)
        right.grid(row=0,column=1,sticky='nsew')
        tk.Label(right,text='候选列表 · 点击切换选择',bg='white',fg=INK,
                 font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',pady=(0,10))
        table_frame = tk.Frame(right,bg='white')
        table_frame.pack(fill='both',expand=True)
        self.tree = ttk.Treeview(table_frame,columns=('level','label'),show='tree headings',height=5,selectmode='none')
        self.tree.heading('#0',text='选中')
        self.tree.column('#0',width=42,minwidth=42,stretch=False)
        self.tree.heading('level',text='可信度')
        self.tree.column('level',width=55,minwidth=50,stretch=False)
        self.tree.heading('label',text='对象 / 区域')
        self.tree.column('label',width=210,minwidth=160)
        self.tree.pack(side='left',fill='both',expand=True)
        scroll = ttk.Scrollbar(table_frame,orient='vertical',command=self.tree.yview)
        scroll.pack(side='right',fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<ButtonRelease-1>',self.toggle)
        self.reason = tk.StringVar(value='没有自动检测结果时，可在左侧手动框选。')
        tk.Label(right,textvariable=self.reason,wraplength=310,justify='left',bg='white',fg=MUTED,
                 font=('Microsoft YaHei UI',8)).pack(fill='x',pady=10)
        self.button(right,'清除选择',self.clear_selection,variant='text',height=28).pack(anchor='w')
        settings = tk.Frame(right,bg='white')
        settings.pack(fill='x',pady=(12,0))
        tk.Label(settings,text='图片 / 视频处理方式',bg='white',fg=MUTED).pack(anchor='w')
        method_box = ttk.Combobox(settings,textvariable=self.method,values=('区域修补','裁剪避开'),state='readonly')
        method_box.pack(fill='x',pady=(6,10))
        self.controls.append((method_box,'readonly'))
        method_box.bind('<<ComboboxSelected>>',lambda e:self.invalidate())
        tk.Label(settings,text='视频时间段（秒，结束 0 表示到末尾）',bg='white',fg=MUTED,
                 font=('Microsoft YaHei UI',8)).pack(anchor='w')
        times = tk.Frame(settings,bg='white')
        times.pack(fill='x',pady=(6,0))
        for label,variable in [('开始',self.start),('结束',self.end)]:
            tk.Label(times,text=label,bg='white',fg=MUTED).pack(side='left',padx=(0,4))
            widget = ttk.Entry(times,textvariable=variable,width=7)
            widget.pack(side='left',padx=(0,10))
            self.controls.append((widget,'normal'))
            variable.trace_add('write',lambda *args:self.invalidate())
        footer = tk.Frame(self.window,bg=BG,padx=24,pady=16)
        footer.pack(fill='x')
        self.notes = tk.StringVar(value='所有操作在本地完成，保留原文件。')
        tk.Label(footer,textvariable=self.notes,bg=BG,fg=MUTED,wraplength=1100,justify='left',
                 font=('Microsoft YaHei UI',8)).pack(fill='x',pady=(0,10))
        output = tk.Frame(footer,bg=BG)
        output.pack(fill='x')
        tk.Label(output,text='输出位置',bg=BG,fg=MUTED).pack(side='left',padx=(0,10))
        directory_entry = ttk.Entry(output,textvariable=self.directory)
        directory_entry.pack(side='left',fill='x',expand=True)
        self.controls.append((directory_entry,'normal'))
        self.button(output,'选择目录',self.choose_directory,width=92).pack(side='left',padx=(8,0))
        actions = tk.Frame(footer,bg=BG)
        actions.pack(fill='x',pady=(12,0))
        tk.Label(actions,textvariable=self.status,bg=BG,fg=MUTED,wraplength=590,justify='left',
                 font=('Microsoft YaHei UI',8)).pack(side='left',fill='x',expand=True)
        self.cancel_button = ModernButton(actions,'取消',self.cancel.set,width=70,state='disabled')
        self.cancel_button.pack(side='right',padx=(8,0))
        self.button(actions,'另存去水印结果',lambda:self.process(False),variant='primary',width=148).pack(side='right',padx=(8,0))
        self.button(actions,'预览效果',lambda:self.process(True),variant='soft',width=100).pack(side='right')
        self.window.after(100,self.poll)
        if source:
            self.window.after(150,self.detect)

    def button(self,parent,text,command,**kwargs):
        from ui import ModernButton
        button = ModernButton(parent,text,command,**kwargs)
        self.buttons.append(button)
        return button

    def choose(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.window,title='选择图片、视频、PDF 或 Word',
                    filetypes=[('支持的文件','*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.gif *.avif *.heic *.heif *.ico *.mp4 *.mov *.mkv *.avi *.webm *.wmv *.flv *.mpeg *.mpg *.m4v *.ts *.mts *.m2ts *.3gp *.vob *.ogv *.pdf *.docx *.doc'),('所有文件','*.*')])
        if path:
            self.source.set(path)
            self.detect()

    def choose_directory(self):
        from tkinter import filedialog
        if path:=filedialog.askdirectory(parent=self.window,title='选择输出文件夹'):
            self.directory.set(path)

    def run(self,operation):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        for widget,normal in self.controls:
            widget.configure(state='disabled')
        for button in self.buttons:
            button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        def worker():
            try:
                self.events.put(('done',operation()))
            except Cancelled:
                self.events.put(('cancelled',None))
            except Exception as exc:
                self.events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def detect(self):
        source = self.source.get().strip()
        if not source or self.busy:
            return
        self.analysis = None
        self.selected.clear()
        self.result = None
        self.result_pictures = {}
        self.picture = None
        self.tree.delete(*self.tree.get_children())
        self.canvas.delete('all')
        self.status.set('正在检测候选…')
        self.run(lambda:('analysis',watermark.detect(source,self.cancel,lambda f,m:self.events.put(('status',m)))))

    def invalidate(self):
        self.result = None
        if hasattr(self,'view'):
            self.view.set('原图 / 原文件')
        if hasattr(self,'canvas'):
            self.draw()

    def fill_table(self):
        self.tree.delete(*self.tree.get_children())
        for candidate in self.analysis.candidates:
            self.tree.insert('', 'end',iid=candidate.id,text='☑' if candidate.id in self.selected else '☐',
                             values=(candidate.confidence,candidate.label))

    def toggle(self,event):
        if self.busy or not self.analysis:
            return
        key = self.tree.identify_row(event.y)
        if not key:
            return
        if key in self.selected:
            self.selected.remove(key)
        else:
            self.selected.add(key)
        candidate = next(c for c in self.analysis.candidates if c.id==key)
        self.reason.set(candidate.reason)
        if self.analysis.kind in {'pdf','word'}:
            self.page.set(str(candidate.page+1))
        self.tree.item(key,text='☑' if key in self.selected else '☐')
        self.invalidate()

    def clear_selection(self):
        self.selected.clear()
        if self.analysis:
            self.fill_table()
        self.invalidate()

    def draw(self):
        if not self.analysis or not self.window.winfo_exists():
            return
        page = int(self.page.get())-1
        result = self.result if self.view.get()=='处理效果' else None
        if self.view.get()=='处理效果' and not result:
            self.view.set('原图 / 原文件')
            self.status.set('选择区域后点击「预览效果」。修改选择或方式后需重新预览。')
        # Cache rendered frames; resizing and selection do not re-run FFmpeg.
        key = (page,str(result or ''))
        if getattr(self,'picture_key',None)!=key:
            try:
                self.picture = self.result_pictures[page] if result and page in self.result_pictures else watermark.preview(self.analysis,page,result)
                self.picture_key = key
            except Exception as exc:
                self.status.set('预览失败：'+str(exc))
                return
        self.canvas.delete('all')
        width,height = max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())
        image = self.picture.copy()
        image.thumbnail((max(1,width-20),max(1,height-20)),Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image,master=self.window)
        x,y = (width-image.width)/2,(height-image.height)/2
        self.display_rect = (x,y,image.width,image.height)
        self.canvas.create_image(x,y,anchor='nw',image=self.photo)
        if result:
            return
        for candidate in self.analysis.candidates:
            if candidate.box and (self.analysis.kind!='pdf' or candidate.page==page):
                bx,by,bw,bh = candidate.box
                color = '#4c6fff' if candidate.id in self.selected else '#98a2b8'
                self.canvas.create_rectangle(x+bx*image.width,y+by*image.height,x+(bx+bw)*image.width,y+(by+bh)*image.height,
                                             outline=color,width=2,dash=() if candidate.id in self.selected else (4,3))
                self.canvas.create_text(x+bx*image.width+3,y+by*image.height+3,text=candidate.id,anchor='nw',fill=color)

    def drag_begin(self,event):
        if self.busy or not self.analysis or self.analysis.kind=='word' or self.view.get()=='处理效果':
            return
        x,y,w,h = self.display_rect
        if x<=event.x<=x+w and y<=event.y<=y+h:
            self.drag_origin = (event.x,event.y)
            self.drag_item = self.canvas.create_rectangle(event.x,event.y,event.x,event.y,outline='#4c6fff',width=2)

    def drag_move(self,event):
        if self.busy or not getattr(self,'drag_origin',None):
            return
        x,y,w,h = self.display_rect
        self.canvas.coords(self.drag_item,*self.drag_origin,min(x+w,max(x,event.x)),min(y+h,max(y,event.y)))

    def drag_end(self,event):
        if not getattr(self,'drag_origin',None):
            return
        x,y,w,h = self.display_rect
        a,b = self.drag_origin
        c,d = min(x+w,max(x,event.x)),min(y+h,max(y,event.y))
        self.drag_origin = None
        if abs(c-a)<4 or abs(d-b)<4:
            self.draw()
            return
        box = ((min(a,c)-x)/w,(min(b,d)-y)/h,abs(c-a)/w,abs(d-b)/h)
        candidate = watermark.add_region(self.analysis,int(self.page.get())-1,box)
        self.selected.add(candidate.id)
        self.fill_table()
        self.invalidate()

    def process(self,is_preview):
        from tkinter import messagebox
        if self.busy:
            return
        if not self.analysis or not self.selected:
            messagebox.showinfo('选择对象', '请先检测，然后选择候选或手动框选区域。',parent=self.window)
            return
        if Path(self.source.get().strip()).resolve()!=self.analysis.source:
            messagebox.showinfo('重新检测','文件路径已改变，请先检测新文件。',parent=self.window)
            return
        try:
            start,end = float(self.start.get()),float(self.end.get())
        except ValueError:
            messagebox.showerror('时间格式','时间应为秒数，例如 2.5。',parent=self.window)
            return
        method = 'crop' if self.method.get()=='裁剪避开' else 'inpaint'
        if self.analysis.kind!='video':
            start=end=0
        selected = tuple(self.selected)
        directory = Path(self.scratch.name) if is_preview else Path(self.directory.get().strip() or self.analysis.source.parent/'转换结果')
        analysis = self.analysis
        page = int(self.page.get())-1
        self.status.set('正在生成预览…' if is_preview else '正在处理并另存结果…')
        def operation():
            destination,notes = watermark.remove(analysis,selected,directory,method,start,end,self.cancel,
                                       lambda f,m:self.events.put(('status',m)),self.options)
            # Rendering occurs on the worker, including video frame decoding.
            pages = range(len(analysis.frames)) if analysis.kind=='video' else [page]
            pictures = {p:watermark.preview(analysis,p,destination) for p in pages}
            return ('result',destination,notes,is_preview,page,pictures)
        self.run(operation)

    def poll(self):
        from tkinter import messagebox
        if not self.window.winfo_exists():
            return
        try:
            while True:
                kind,payload = self.events.get_nowait()
                if kind=='status':
                    self.status.set(payload)
                    continue
                self.busy=False
                for widget,normal in self.controls:
                    widget.configure(state=normal)
                for button in self.buttons:
                    button.configure(state='normal')
                self.cancel_button.configure(state='disabled')
                if kind=='done' and payload[0]=='analysis':
                    self.analysis=payload[1]
                    self.picture_key=None
                    self.page.set('1')
                    count = len(self.analysis.frames) if self.analysis.kind=='video' else self.analysis.pages
                    self.page_box.configure(values=tuple(str(i+1) for i in range(count)))
                    self.view.set('原图 / 原文件')
                    self.fill_table()
                    self.notes.set('\n'.join(self.analysis.notes))
                    self.status.set(f'检测到 {len(self.analysis.candidates)} 个候选。点击选择，或在预览中手动框选。')
                    self.draw()
                elif kind=='done':
                    _,destination,notes,is_preview,page,pictures=payload
                    self.result=destination
                    self.result_pictures=pictures
                    self.picture=pictures[page]
                    self.picture_key=(page,str(destination))
                    self.view.set('处理效果')
                    self.draw()
                    self.status.set('预览已生成；修改选择后需重新预览。' if is_preview else '已另存：'+str(destination))
                    if not is_preview and not self.closing:
                        messagebox.showinfo('处理完成',str(destination)+'\n\n'+'\n'.join(notes),parent=self.window)
                elif kind=='error':
                    self.status.set('处理失败：'+payload)
                    if not self.closing:
                        messagebox.showerror('处理失败',payload,parent=self.window)
                else:
                    self.status.set('任务已取消。')
                if self.closing:
                    self.close()
                    return
        except queue.Empty:
            pass
        self.window.after(100,self.poll)

    def close(self):
        if self.busy:
            self.closing=True
            self.cancel.set()
            self.status.set('正在停止任务，完成当前检测步骤后关闭…')
        else:
            self.scratch.cleanup()
            self.window.destroy()
