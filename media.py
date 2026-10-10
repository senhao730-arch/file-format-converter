"""Resolution, denoise and sharpening helpers shared by media operations."""
from PIL import Image, ImageFilter, ImageOps


def validate_media(options):
    from converter import ConversionError
    if not 0 <= options.width <= 16384 or not 0 <= options.height <= 16384:
        raise ConversionError('宽度和高度应为 0–16384；0 表示自动。')
    if options.resize_mode not in {'contain', 'crop', 'stretch'}:
        raise ConversionError('无效的缩放模式。')
    if not 0 <= options.sharpen <= 3 or not 0 <= options.denoise <= 3:
        raise ConversionError('锐化与降噪强度应为 0–3。')


def adjust_image(image, options):
    validate_media(options)
    image = image.convert('RGBA')
    width, height = options.width, options.height
    if width or height:
        width = width or max(1, round(image.width * height / image.height))
        height = height or max(1, round(image.height * width / image.width))
        if options.resize_mode == 'stretch':
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        elif options.resize_mode == 'crop':
            image = ImageOps.fit(image, (width, height), Image.Resampling.LANCZOS)
        else:
            content = ImageOps.contain(image, (width, height), Image.Resampling.LANCZOS)
            canvas = Image.new('RGBA', (width, height), (255, 255, 255, 0))
            canvas.paste(content, ((width - content.width) // 2, (height - content.height) // 2))
            image = canvas
    alpha = image.getchannel('A')
    colors = image.convert('RGB')
    if options.denoise:
        colors = colors.filter(ImageFilter.MedianFilter(3 if options.denoise < 2 else 5))
    if options.sharpen:
        colors = colors.filter(ImageFilter.UnsharpMask(radius=1.5, percent=round(options.sharpen * 100), threshold=3))
    result = colors.convert('RGBA')
    result.putalpha(alpha)
    return result


def video_filters(options):
    validate_media(options)
    filters = []
    for x, y, width, height in options.watermark_boxes:
        enable = ''
        if options.watermark_start or options.watermark_end:
            end = options.watermark_end or 1e12
            enable = f":enable='between(t,{options.watermark_start},{end})'"
        filters.append(f'delogo=x={x}:y={y}:w={width}:h={height}:show=0{enable}')
    if options.crop_box:
        x, y, width, height = options.crop_box
        filters.append(f'crop={width}:{height}:{x}:{y}')
    width, height = options.width, options.height
    if width and height:
        # Encoders using yuv420p need even frame dimensions.
        width, height = (width + 1) // 2 * 2, (height + 1) // 2 * 2
        if options.resize_mode == 'stretch':
            filters.append(f'scale={width}:{height}:flags=lanczos')
        elif options.resize_mode == 'crop':
            filters += [f'scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2:flags=lanczos',
                        f'crop={width}:{height}']
        else:
            filters += [f'scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos',
                        f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black']
        filters.append('setsar=1')
    elif width:
        filters += [f'scale={(width + 1) // 2 * 2}:-2:flags=lanczos', 'setsar=1']
    elif height:
        filters += [f'scale=-2:{(height + 1) // 2 * 2}:flags=lanczos', 'setsar=1']
    if options.denoise:
        level = options.denoise
        filters.append(f'hqdn3d={level * 2}:{level * 1.5}:{level * 3}:{level * 2}')
    if options.sharpen:
        filters.append(f'unsharp=5:5:{options.sharpen}:5:5:0')
    return filters


def media_notes(options):
    notes = []
    if options.width or options.height:
        notes.append(f'目标分辨率：{options.width or "自动"} × {options.height or "自动"}；缩放模式 {options.resize_mode}。')
    if options.sharpen or options.denoise:
        notes.append(f'锐化 {options.sharpen:g}，降噪 {options.denoise:g}；这些处理不能恢复源文件中不存在的细节。')
    return notes
