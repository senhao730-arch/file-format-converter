# 格式转换工具

Windows 本地桌面工具：文档、图片、GIF 和视频格式转换，画质与分辨率调整，以及水印候选检测和处理。

**[下载 Windows 便携版](https://github.com/senhao730-arch/file-format-converter/releases/latest)** · [详细使用说明](使用说明.md)

## 下载和运行

1. 打开上面的下载页，下载 `FormatConverter-Windows-x64.zip`。
2. **完整解压**，双击 `启动程序.bat`，或打开 `FormatConverter/FormatConverter.exe`。
3. 不用安装 Python。保留 EXE 旁的 `_internal` 文件夹。

适用 Windows 10/11 64 位。Word、PPT 导出 PDF 需要本机 Microsoft Office 或 LibreOffice；DOC 水印检测需要 Microsoft Word。

## 功能

- Word ⇄ PDF、PPT ⇄ PDF。
- PNG、JPG、WebP、BMP、TIFF、GIF、ICO、AVIF 等图片格式互转，读取 HEIC/HEIF。
- GIF → MP4，以及 MP4、MOV、MKV、AVI、WebM 等视频格式互转。
- 图片和视频的自定义分辨率、等比适应、裁剪、拉伸、锐化、降噪及压缩质量设置。
- 图片、视频、PDF、Word 的水印候选检测和选择处理，支持预览；图片、视频、PDF 可手动框选。
- 批量转换、进度与失败日志、取消任务、同名自动编号。文件在本地处理，原文件保留。

![主界面](界面预览.png)

## 结果与限制

- PDF 转 Word 的可编辑模式适用于包含文字的 PDF；扫描件可选择整页图片模式，不提供 OCR。
- PDF 转 PPT 的每页作为图片插入，页内文字不能单独编辑。
- 水印候选可能误检或漏检，不会自动选中或删除。复杂背景的区域修补可能留下痕迹，不跟踪移动水印。
- PDF 框选修补会将涉及页面转成图片，该页文字不能选择或搜索；其他页保留。
- Word 只处理可识别的独立水印图形，预览仅显示对象说明；不修补正文图片内的水印。DOC 输出 DOCX。
- 提高尺寸、锐化不能恢复源文件中不存在的细节。详见[使用说明](使用说明.md)。

## 从源码运行

推荐 Python 3.12/3.13，需包含 tkinter。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

开发测试：`python -m pytest tests -q`。已通过 49 项常规测试，另有 1 项真实 Office 集成测试；验证说明见[验证结果](验证结果.txt)。

## 分享给别人

分享仓库首页：https://github.com/senhao730-arch/file-format-converter 。需要让别人直接下载时，分享[最新发布页](https://github.com/senhao730-arch/file-format-converter/releases/latest)。使用者应下载发布页的便携版 ZIP，而不是 GitHub 自动生成的 Source code 包。

## 许可证

项目源码使用 GNU AGPL v3，见 [LICENSE.txt](LICENSE.txt)。便携版和完整源码 ZIP 附带第三方组件许可证，组件来源见[第三方组件说明](第三方组件说明.txt)。
