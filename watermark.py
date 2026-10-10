"""Local, opt-in watermark candidates and non-destructive removal.

Coordinates are normalized to the displayed (rotated, EXIF-oriented) page/frame.
Heuristics offer candidates, never a claim that ordinary content is a watermark.
"""
from __future__ import annotations

import hashlib
import io
import math
import re
import subprocess
import tempfile
import threading
import zipfile
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence
from converter import (ConversionError, IMAGE_INPUTS, VIDEO_INPUTS, Options,
                       _duration, _video, check_cancel, ffmpeg_path, publish)


@dataclass
class Candidate:
    id: str
    kind: str
    label: str
    reason: str
    confidence: str = '低'
    page: int = 0
    box: tuple = ()
    locator: dict = field(default_factory=dict)


@dataclass
class Analysis:
    source: Path
    fingerprint: str
    kind: str
    width: int = 0
    height: int = 0
    pages: int = 1
    candidates: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    frames: list = field(default_factory=list)
    times: list = field(default_factory=list)
    duration: float = 0
    word_bytes: bytes = b''

    def add(self, **kwargs):
        item = Candidate(id=str(len(self.candidates) + 1), **kwargs)
        self.candidates.append(item)
        return item


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _frame(source, time=0):
    command = [ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-ss', str(time),
               '-i', str(source), '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-']
    result = subprocess.run(command, capture_output=True, timeout=60,
                            creationflags=0x08000000)
    if result.returncode or not result.stdout:
        raise ConversionError('无法读取视频预览：' + result.stderr.decode('utf-8', 'replace')[-500:])
    return Image.open(io.BytesIO(result.stdout)).convert('RGB')


def _edges(image):
    import cv2
    import numpy as np
    small = ImageOps.contain(image.convert('RGB'), (960, 960))
    array = np.asarray(small)
    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    return small, cv2.Canny(gray, 65, 150)


def _regions(image, edge_mask=None):
    """Text-like compact groups near edges; keep conservative size limits."""
    import cv2
    small, edges = _edges(image)
    if edge_mask is not None:
        edges = edge_mask
    width, height = small.size
    grouped = cv2.morphologyEx(edges, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (11, 3)))
    contours, _ = cv2.findContours(grouped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h / (width * height)
        near_edge = y < height * .22 or y + h > height * .78 or x < width * .15 or x + w > width * .85
        density = cv2.countNonZero(edges[y:y+h, x:x+w]) / max(1, w*h)
        if near_edge and .0008 < area < .09 and 1.5 < w / max(h, 1) < 25 and h >= 5 and density > .08:
            boxes.append((max(0, x-4)/width, max(0, y-4)/height,
                          (min(width, x+w+4)-max(0,x-4))/width,
                          (min(height,y+h+4)-max(0,y-4))/height))
    return sorted(boxes, key=lambda b: b[2]*b[3], reverse=True)[:10]


def _image_open(source):
    if Path(source).suffix.lower() in {'.heic', '.heif'}:
        import pillow_heif
        pillow_heif.register_heif_opener()
    return Image.open(source)


def detect(source, cancel=None, progress=None):
    cancel = cancel or threading.Event()
    progress = progress or (lambda *args: None)
    source = Path(source).resolve()
    if not source.is_file():
        raise ConversionError('找不到待检测文件。')
    check_cancel(cancel)
    digest = fingerprint(source)
    suffix = source.suffix.lower().lstrip('.')
    if suffix in IMAGE_INPUTS:
        analysis = Analysis(source, digest, 'image')
        with _image_open(source) as original:
            image = ImageOps.exif_transpose(original).convert('RGBA')
            analysis.width, analysis.height = image.size
            analysis.frames = [image]
            if getattr(original, 'n_frames', 1) > 1:
                analysis.notes.append('动画仅检测首帧，选定区域会应用到所有帧。')
        for box in _regions(image):
            analysis.add(kind='region', label='疑似角落文字 / 标记',
                         reason='边缘区域的文字形状，可能是正常画面内容。', box=box)
    elif suffix in VIDEO_INPUTS:
        import numpy as np
        analysis = Analysis(source, digest, 'video')
        analysis.duration = _duration(ffmpeg_path(), source)
        analysis.times = [analysis.duration * fraction for fraction in (.2, .5, .8)] if analysis.duration > .1 else [0]
        edges = []
        for index, time in enumerate(analysis.times):
            check_cancel(cancel)
            frame = _frame(source, time)
            analysis.width, analysis.height = frame.size
            analysis.frames.append(frame)
            edges.append(_edges(frame)[1] > 0)
            progress((index+1)/len(analysis.times), '采样视频帧')
        stable = (np.mean(np.stack(edges), axis=0) >= .75).astype('uint8') * 255
        for box in _regions(analysis.frames[0], stable):
            analysis.add(kind='region', label='疑似固定位置标记',
                         reason='多个采样帧中重复出现的边缘；可能是字幕或静止背景。', box=box)
        analysis.notes.append('固定位置候选检测，不跟踪移动水印。视频区域修补使用邻近像素插值。')
    elif suffix == 'pdf':
        analysis = Analysis(source, digest, 'pdf')
        _detect_pdf(analysis, cancel, progress)
    elif suffix in {'docx', 'doc'}:
        analysis = Analysis(source, digest, 'word')
        analysis.word_bytes = source.read_bytes() if suffix == 'docx' else _doc_to_docx(source)
        _detect_word(analysis)
    else:
        raise ConversionError('水印工具支持图片、视频、PDF、DOC、DOCX。')
    check_cancel(cancel)
    if fingerprint(source) != digest:
        raise ConversionError('检测期间源文件发生变化，请重新检测。')
    analysis.notes.insert(0, '候选检测不识别文字内容，可能漏检或误检；请选择确认的对象，或在预览中手动框选。')
    return analysis


def _normalized(rect, page):
    rect = rect * page.rotation_matrix
    rect &= page.rect
    if rect.is_empty:
        return ()
    return (rect.x0/page.rect.width, rect.y0/page.rect.height,
            rect.width/page.rect.width, rect.height/page.rect.height)


def _detect_pdf(analysis, cancel, progress):
    import pikepdf
    import pymupdf
    with pikepdf.Pdf.open(analysis.source) as pdf, pymupdf.open(analysis.source) as display:
        if display.needs_pass:
            raise ConversionError('请先解密 PDF 再检测水印。')
        analysis.pages = len(pdf.pages)
        counts = Counter()
        for page in pdf.pages:
            for obj in page.get('/Resources', {}).get('/XObject', {}).values():
                if obj.is_indirect:
                    counts[obj.objgen] += 1
        for index, page in enumerate(pdf.pages):
            check_cancel(cancel)
            fitz_page = display[index]
            analysis.width, analysis.height = int(fitz_page.rect.width), int(fitz_page.rect.height)
            for annotation in page.get('/Annots', []):
                subtype = str(annotation.get('/Subtype', ''))
                if subtype in {'/Watermark', '/Stamp'}:
                    rect = pymupdf.Rect([float(v) for v in annotation.get('/Rect', [0,0,0,0])]) * fitz_page.transformation_matrix
                    analysis.add(kind='pdf_annotation', label=f'第 {index+1} 页 · {subtype[1:]} 注释',
                                 reason='PDF 原生水印 / 印章注释对象。', confidence='高', page=index,
                                 box=_normalized(rect, fitz_page), locator={'objgen': list(annotation.objgen)})
            resources = page.get('/Resources', {})
            xobjects = resources.get('/XObject', {})
            opacity, matrix, stack, used, bounds = 1., pymupdf.Matrix(1,1), [], {}, {}
            for instruction in pikepdf.parse_content_stream(page):
                operands, operator = instruction
                op = str(operator)
                if op == 'q':
                    stack.append((opacity,matrix))
                elif op == 'Q':
                    opacity,matrix = stack.pop() if stack else (1.,pymupdf.Matrix(1,1))
                elif op == 'cm' and len(operands)==6:
                    matrix = pymupdf.Matrix([float(v) for v in operands]) * matrix
                elif op == 'gs' and operands:
                    state = resources.get('/ExtGState', {}).get(str(operands[0]), {})
                    opacity = min(float(state.get('/ca', 1)), float(state.get('/CA', 1)))
                elif op == 'Do' and operands:
                    name = str(operands[0])
                    used[name] = min(opacity, used.get(name, 1.))
                    obj = xobjects.get(name)
                    if obj is not None:
                        if str(obj.get('/Subtype',''))=='/Image':
                            rect = pymupdf.Rect(0,0,1,1) * matrix * fitz_page.transformation_matrix
                        else:
                            rect = pymupdf.Rect([float(v) for v in obj.get('/BBox',[0,0,0,0])])
                            form_matrix = pymupdf.Matrix([float(v) for v in obj.get('/Matrix',[1,0,0,1,0,0])])
                            rect = rect * form_matrix * matrix * fitz_page.transformation_matrix
                        if not rect.is_empty:
                            bounds[name] = (bounds[name] | rect) if name in bounds else rect
            for name, alpha in used.items():
                obj = xobjects.get(name)
                if obj is None:
                    continue
                subtype = str(obj.get('/Subtype', ''))
                explicit = bool(re.search(r'watermark|stamp|logo|^/?wm\d*$', name, re.I))
                box = _normalized(bounds[name], fitz_page) if name in bounds else ()
                area = box[2]*box[3] if box else 1
                repeated = obj.is_indirect and counts[obj.objgen] >= 2
                if explicit or (box and area < .35 and (alpha < .95 or repeated)):
                    analysis.add(kind='pdf_object', label=f'第 {index+1} 页 · 对象 {name}', page=index, box=box,
                                 confidence='高' if explicit else '低', locator={'name': name},
                                 reason='对象名称包含水印标记。' if explicit else '重复或半透明图形对象；也可能是页眉、标识或插图。')
            text_count=0
            for block in fitz_page.get_text('dict')['blocks']:
                for line in block.get('lines',[]):
                    direction=line.get('dir',(1,0))
                    angle=abs(math.degrees(math.atan2(direction[1],direction[0])))%180
                    spans=line.get('spans',[])
                    large=any(span.get('size',0)>=20 for span in spans)
                    pale=any(min((span.get('color',0)>>16)&255,(span.get('color',0)>>8)&255,span.get('color',0)&255)>175 for span in spans)
                    if not large or not (10<angle<80 or pale) or text_count>=8:
                        continue
                    box=_normalized(pymupdf.Rect(line['bbox']),fitz_page)
                    if not box:
                        continue
                    native_boxes=[c.box for c in analysis.candidates if c.page==index and c.kind=='pdf_object' and c.box]
                    rect=pymupdf.Rect(box[0],box[1],box[0]+box[2],box[1]+box[3])
                    if any((rect & pymupdf.Rect(b[0],b[1],b[0]+b[2],b[1]+b[3])).get_area()>rect.get_area()*.6 for b in native_boxes):
                        continue
                    analysis.add(kind='region',label=f'第 {index+1} 页 · 疑似斜向 / 淡色文字',page=index,box=box,
                                 reason='较大的斜向或淡色文字，也可能是正常内容。区域修补会将本页转成图片。')
                    text_count+=1
            progress((index+1)/max(1,analysis.pages), '检测 PDF 原生对象')
        if not analysis.pages:
            raise ConversionError('PDF 没有可预览的页面。')
    analysis.notes.append('原生对象可单独移除。手动框选修补会把涉及的页面转成图片，该页文字将不能选择或搜索；其他页保持原状。')


def _doc_to_docx(source):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    app = document = None
    try:
        with tempfile.TemporaryDirectory(prefix='word-watermark-') as folder:
            import shutil
            copied = Path(folder)/source.name
            shutil.copy2(source, copied)
            target = Path(folder)/'converted.docx'
            app = win32com.client.DispatchEx('Word.Application')
            app.Visible = False
            app.DisplayAlerts = 0
            app.AutomationSecurity = 3
            document = app.Documents.Open(str(copied), ReadOnly=True, AddToRecentFiles=False)
            document.SaveAs2(str(target), FileFormat=16, AddToRecentFiles=False)
            document.Close(False)
            document = None
            return target.read_bytes()
    finally:
        if document is not None:
            try:
                document.Close(False)
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit(False)
            except Exception:
                pass
        document=app=None
        pythoncom.CoUninitialize()


def _detect_word(analysis):
    from lxml import etree
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    with zipfile.ZipFile(io.BytesIO(analysis.word_bytes)) as archive:
        for part in archive.namelist():
            if not re.fullmatch(r'word/(header\d+|footer\d+|document)\.xml', part):
                continue
            root = etree.fromstring(archive.read(part), parser)
            for node in root.xpath('//*[local-name()="shape" or local-name()="drawing"]'):
                xml = etree.tostring(node).decode('utf-8')
                marked = bool(re.search(r'watermark|PowerPlusWaterMark|水印', xml, re.I))
                textpaths = node.xpath('.//*[local-name()="textpath"]/@string')
                behind = bool(node.xpath('.//*[local-name()="anchor"][@behindDoc="1" or @behindDoc="true"]'))
                header = 'header' in part or 'footer' in part
                if marked or (header and (textpaths or behind)):
                    label = ' / '.join(textpaths) or ('图形水印' if marked else '页眉 / 页脚背景图形')
                    indices=[]
                    cursor=node
                    while cursor.getparent() is not None:
                        parent=cursor.getparent()
                        indices.append(parent.index(cursor))
                        cursor=parent
                    analysis.add(kind='word_shape', label=label[:100], confidence='高' if marked else '低',
                                 reason=f'{part} 中的独立图形对象；请确认是否为水印。',
                                 page=len(analysis.candidates), locator={'part': part, 'xpath': root.getroottree().getpath(node),
                                                                         'indices':list(reversed(indices)), 'text': label})
    analysis.pages = max(1,len(analysis.candidates))
    analysis.notes.append('Word 预览只展示候选对象说明，不代表完整页面排版。保留正文、页眉文字和未选中的图形；DOC 结果另存为 DOCX。')


def preview(analysis, page=0, result=None):
    """Return PIL pixels, without retaining open file handles."""
    page = max(0,min(page,analysis.pages-1)) if analysis.kind != 'video' else max(0,min(page,len(analysis.frames)-1))
    source = Path(result) if result else analysis.source
    if analysis.kind == 'image':
        if result:
            with _image_open(source) as image:
                return ImageOps.exif_transpose(image).convert('RGBA')
        return analysis.frames[0].copy()
    if analysis.kind == 'video':
        return _frame(source, analysis.times[page]) if result else analysis.frames[page].copy()
    if analysis.kind == 'pdf':
        import pymupdf
        with pymupdf.open(source) as pdf:
            pix = pdf[page].get_pixmap(matrix=pymupdf.Matrix(1.5,1.5), alpha=False)
            return Image.frombytes('RGB', (pix.width,pix.height), pix.samples)
    image = Image.new('RGB', (800,600), '#f5f7fc')
    draw = ImageDraw.Draw(image)
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    font = ImageFont.truetype(str(font_path), 24) if font_path.is_file() else ImageFont.load_default()
    candidates = [c for c in analysis.candidates if c.page == page]
    lines = ['Word 候选对象预览', '仅显示对象说明，不代表页面排版', '']
    if candidates:
        candidate = candidates[0]
        removed = False
        if result:
            copy = Analysis(source, '', 'word', word_bytes=source.read_bytes())
            _detect_word(copy)
            removed = not any(c.locator['part']==candidate.locator['part'] and c.label==candidate.label for c in copy.candidates)
        lines += ['已移除该对象' if removed else candidate.label, candidate.reason]
    else:
        lines.append('没有发现可识别的独立水印图形对象')
    y = 70
    for line in lines:
        for offset in range(0,max(1,len(line)),27):
            draw.text((40,y), line[offset:offset+27], fill='#39445a', font=font)
            y += 42
    return image


def add_region(analysis, page, box):
    if analysis.kind not in {'image','video','pdf'}:
        raise ConversionError('Word 只支持选择文档中检测到的独立对象。')
    if len(box) != 4 or any(not 0 <= float(v) <= 1 for v in box) or box[2] <= 0 or box[3] <= 0 or box[0]+box[2] > 1.00001 or box[1]+box[3] > 1.00001:
        raise ConversionError('框选区域必须位于预览范围内。')
    return analysis.add(kind='region', label='手动框选区域', reason='用户框选，修补选中区域。',
                        confidence='手动', page=page if analysis.kind=='pdf' else 0, box=tuple(box))


def pixel_boxes(candidates, width, height, video=False):
    boxes = []
    for item in candidates:
        x,y,w,h = item.box
        left, top = max(0,int(x*width)),max(0,int(y*height))
        right,bottom = min(width,int((x+w)*width+.999)),min(height,int((y+h)*height+.999))
        if video:
            # delogo requires a one-pixel border inside the frame.
            left,top = max(1,left),max(1,top)
            right,bottom = min(width-1,right),min(height-1,bottom)
        if right-left < 2 or bottom-top < 2:
            raise ConversionError('区域过小，请扩大选择范围。')
        boxes.append((left,top,right-left,bottom-top))
    return boxes


def _repair(image, boxes):
    import cv2
    import numpy as np
    rgba = image.convert('RGBA')
    rgb = np.array(rgba.convert('RGB'))
    mask = np.zeros(rgb.shape[:2], dtype=np.uint8)
    for x,y,w,h in boxes:
        mask[y:y+h,x:x+w] = 255
    rgb = cv2.inpaint(rgb, mask, 3, cv2.INPAINT_TELEA)
    result = Image.fromarray(rgb).convert('RGBA')
    result.putalpha(rgba.getchannel('A'))
    return result


def _crop_bounds(width,height,boxes):
    remaining = [(0,0,width,height)]
    for x,y,w,h in boxes:
        next_rects = []
        for l,t,r,b in remaining:
            if x >= r or x+w <= l or y >= b or y+h <= t:
                next_rects.append((l,t,r,b))
            else:
                next_rects += [(l,t,min(r,x),b),(max(l,x+w),t,r,b),
                               (l,t,r,min(b,y)),(l,max(t,y+h),r,b)]
        remaining = sorted((v for v in next_rects if v[2]-v[0]>=2 and v[3]-v[1]>=2),
                           key=lambda v:(v[2]-v[0])*(v[3]-v[1]), reverse=True)[:64]
        if not remaining:
            raise ConversionError('没有可保留的裁剪区域，请缩小水印框选范围。')
    return max(remaining, key=lambda v:(v[2]-v[0])*(v[3]-v[1]))


def _remove_image(analysis,selected,target,method,cancel,options):
    frames, durations = [], []
    with _image_open(analysis.source) as original:
        loop = original.info.get('loop',0)
        for frame in ImageSequence.Iterator(original):
            check_cancel(cancel)
            image = ImageOps.exif_transpose(frame).convert('RGBA')
            boxes = pixel_boxes(selected,*image.size)
            result = image.crop(_crop_bounds(*image.size,boxes)) if method=='crop' else _repair(image,boxes)
            from media import adjust_image
            result = adjust_image(result,options)
            frames.append(result)
            durations.append(frame.info.get('duration',100))
    ext = target.suffix.lower()
    if ext in {'.jpg','.jpeg','.bmp'}:
        colors = []
        for image in frames:
            canvas = Image.new('RGB',image.size,'white')
            canvas.paste(image,mask=image.getchannel('A'))
            colors.append(canvas)
        frames = colors
    params = {'quality':options.quality} if ext in {'.jpg','.jpeg','.webp','.avif'} else {}
    if len(frames)>1 and ext in {'.gif','.webp','.png','.tif','.tiff','.avif'}:
        params.update(save_all=True,append_images=frames[1:],duration=durations,loop=loop)
        if ext == '.gif':
            params['disposal']=2
    frames[0].save(target,**params)


def _remove_word(analysis,selected,target):
    from lxml import etree
    by_part = {}
    for item in selected:
        by_part.setdefault(item.locator['part'],[]).append(item.locator['indices'])
    parser = etree.XMLParser(resolve_entities=False,no_network=True)
    with zipfile.ZipFile(io.BytesIO(analysis.word_bytes)) as source, zipfile.ZipFile(target,'w') as destination:
        destination.comment = source.comment
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename in by_part:
                root = etree.fromstring(data,parser)
                # Resolve all locators before mutation; sibling indices must not shift.
                nodes = []
                for indices in by_part[info.filename]:
                    cursor=root
                    for index in indices:
                        cursor=cursor[index]
                    nodes.append(cursor)
                for node in nodes:
                    parent = node.getparent()
                    if parent is not None:
                        parent.remove(node)
                data = etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
            destination.writestr(info,data)


def _remove_pdf(analysis,selected,target,cancel,notes):
    import pikepdf
    import pymupdf
    native = [c for c in selected if c.kind!='region']
    regions = [c for c in selected if c.kind=='region']
    with pikepdf.Pdf.open(analysis.source) as pdf:
        for page_index in sorted({c.page for c in native}):
            check_cancel(cancel)
            page = pdf.pages[page_index]
            items = [c for c in native if c.page==page_index]
            names = {c.locator['name'] for c in items if c.kind=='pdf_object'}
            if names:
                # Clone page resources: shared dictionaries must not affect other pages.
                resources = pikepdf.Dictionary(page.get('/Resources',{}))
                objects = pikepdf.Dictionary(resources.get('/XObject',{}))
                for name in names:
                    blank = pdf.make_stream(b'')
                    blank['/Type'] = pikepdf.Name('/XObject')
                    blank['/Subtype'] = pikepdf.Name('/Form')
                    blank['/BBox'] = pikepdf.Array([0,0,1,1])
                    blank['/Resources'] = pikepdf.Dictionary()
                    objects[name] = blank
                resources['/XObject'] = objects
                page['/Resources'] = resources
            annotation_ids = {tuple(c.locator['objgen']) for c in items if c.kind=='pdf_annotation'}
            if annotation_ids:
                page['/Annots'] = pikepdf.Array([a for a in page.get('/Annots',[]) if a.objgen not in annotation_ids])
        pdf.save(target)
    if regions:
        with pymupdf.open(target) as pdf:
            for index in sorted({c.page for c in regions}):
                check_cancel(cancel)
                page = pdf[index]
                pix = page.get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False,annots=False)
                image = Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                image = _repair(image,pixel_boxes([c for c in regions if c.page==index],*image.size))
                if page.rotation:
                    image = image.rotate(page.rotation,expand=True)
                buffer = io.BytesIO()
                image.convert('RGB').save(buffer,format='PNG')
                rect = page.rect * page.derotation_matrix
                xref = pdf.get_new_xref()
                pdf.update_object(xref,'<<>>')
                pdf.update_stream(xref,b'')
                page.set_contents(xref)
                pdf.xref_set_key(page.xref,'Resources','<<>>')
                page.insert_image(rect,stream=buffer.getvalue())
            raster_target = target.with_name('repaired.pdf')
            pdf.save(raster_target,garbage=4,deflate=True)
        raster_target.replace(target)
        notes.append('框选修补的 PDF 页面已转成图片，该页文字不再可选择或搜索。')


def remove(analysis,ids,directory,method='inpaint',start=0.,end=0.,cancel=None,progress=None,options=None):
    cancel = cancel or threading.Event()
    progress = progress or (lambda *args:None)
    options = options or Options()
    from media import validate_media,media_notes
    validate_media(options)
    if not 1<=options.quality<=100 or options.video_quality not in {'small','balanced','high'}:
        raise ConversionError('请检查图片质量与视频质量设置。')
    check_cancel(cancel)
    if fingerprint(analysis.source)!=analysis.fingerprint:
        raise ConversionError('源文件在检测后发生变化，请重新检测，避免移除错误对象。')
    requested = set(map(str,ids))
    selected = [c for c in analysis.candidates if c.id in requested]
    if not selected or len(selected)!=len(requested):
        raise ConversionError('请选择至少一个有效候选或框选区域。')
    if method not in {'inpaint','crop'} or (method=='crop' and analysis.kind not in {'image','video'}):
        raise ConversionError('裁剪仅适用于图片和视频。')
    if not math.isfinite(start) or not math.isfinite(end) or start<0 or end<0 or (end and end<=start) or (analysis.duration and start>=analysis.duration):
        raise ConversionError('时间范围应满足：开始 ≥ 0，结束 > 开始；结束填 0 表示直到末尾。')
    if method=='crop' and (start or end):
        raise ConversionError('裁剪会应用到整段视频；局部时间段请使用区域修补。')
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    extension = analysis.source.suffix.lower().lstrip('.')
    extension = 'docx' if analysis.kind=='word' else ('mp4' if analysis.kind=='video' else extension)
    if extension in {'heic','heif','ico'}:
        extension='png'
    notes = ['仅处理选中的候选 / 区域。修补属于邻近像素填充，复杂背景可能留下痕迹。']
    if analysis.kind=='image':
        notes+=media_notes(options)
    with tempfile.TemporaryDirectory(prefix='.watermark-',dir=directory) as folder:
        staged = Path(folder)/('result.'+extension)
        progress(.05,'开始处理')
        if analysis.kind=='image':
            _remove_image(analysis,selected,staged,method,cancel,options)
        elif analysis.kind=='word':
            _remove_word(analysis,selected,staged)
        elif analysis.kind=='pdf':
            _remove_pdf(analysis,selected,staged,cancel,notes)
        else:
            boxes = pixel_boxes(selected,analysis.width,analysis.height,video=method!='crop')
            if method=='crop':
                l,t,r,b = _crop_bounds(analysis.width,analysis.height,boxes)
                updated = replace(options,crop_box=(l,t,r-l,b-t),watermark_boxes=())
            else:
                updated = replace(options,watermark_boxes=tuple(boxes),watermark_start=start,watermark_end=end)
            _video(analysis.source,staged,updated,cancel,progress,notes)
        check_cancel(cancel)
        if fingerprint(analysis.source)!=analysis.fingerprint:
            raise ConversionError('处理期间源文件发生变化，请重新检测。')
        destination = publish(staged,directory,analysis.source.stem+'_去水印',extension)
    progress(1,'处理完成')
    return destination,notes
