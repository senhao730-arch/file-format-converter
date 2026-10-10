# 格式转换工具 · Android 离线版

[下载 Android APK](https://github.com/senhao730-arch/file-format-converter/releases/tag/android-v1.0.0) · [完整 Android 源码包](FormatConverter-Android-Source.zip)

开发时先解压本目录的源码 ZIP，以下构建说明中的「此目录」指解压后的 AndroidConverter 项目目录。

适用 Android 8.0 及以上。安装发布页的 **FormatConverter-Android.apk**，无需电脑、Python 或服务器。使用系统文件选择器添加文件，处理后选择「保存到手机文件夹」或「分享结果」。应用无网络权限，原文件保留。

## 首版功能

- 图片输出 JPG、PNG、WebP、BMP；按比例调整尺寸、锐化、降噪和压缩质量。
- 多张图片合成 PDF，按系统选择器返回的顺序排列。
- 手机支持解码的视频转为 MP4 / H.264 + AAC；调整分辨率、码率档位、对比度，移除音轨，框选保留区域裁剪。
- GIF 转无声 MP4，15 fps，保存一次完整动画，最长 2 分钟，最长边 1280。
- PDF 全部页面导出为图片 ZIP；PDF 页面栅格化压缩。
- 图片、指定 PDF 页的水印角落候选与手动框选修补，先预览、再处理。
- 进度、取消、最近结果、系统保存与分享。

## 使用限制

- 不包含 Word/PPT 互转、OCR、任意视频输出格式、视频水印修补或移动水印跟踪；这些功能继续使用 Windows 版。
- 视频输入支持取决于手机的系统解码器，不能承诺所有 MOV/MKV/AVI 等文件都支持；视频输出目前为 MP4。码率和分辨率可能由系统编码器调整。
- 图片输入依赖 Android 解码器；GIF、动画 WebP 等在图片模式仅保存第一帧。没有 GIF/TIFF/ICO/AVIF 输出。
- 图片解码采样至最长边 4096、最多 800 万像素；输出最多 1200 万像素、单边最多 8192。尺寸提升、锐化不能恢复不存在的细节。
- PDF 支持最多 200 页，单页渲染最多 1200 万像素；超大页面需降低 DPI。PDF 压缩/修补输出的**所有页面**都变为图片，文字不可搜索或选择，链接/表单不保留。压缩体积不保证更小。
- 水印检测只检查角落纹理，不识别文字或品牌，可能误检漏检；候选默认不选中。区域修补通过边缘颜色插值，适合平滑背景，复杂纹理、文字或大面积覆盖会留下明显痕迹。框选不得覆盖整页。
- 处理期间请留在应用内。系统终止应用会中断任务，下次启动清除未完成的临时结果。原文件不被修改。
- 文件先复制到应用缓存，单文件最多 1 GB；多图 PDF 一次最多 30 张。注意手机剩余存储空间。
- 最近结果保存在应用私有目录，卸载会删除；请先保存重要结果到手机文件夹。

## 构建与验证

安装 JDK 17 和 Android SDK 35 / Build Tools 35.0.0，使用 Android Studio 打开此目录；或在配置好 SDK 后执行：

```powershell
.\gradlew.bat assembleDebug testDebugUnitTest lintRelease
.\gradlew.bat connectedDebugAndroidTest
```

签名正式 APK 需要设置 `CONVERTER_KEYSTORE_FILE` 与 `CONVERTER_KEY_PASSWORD` 环境变量，别名为 `converter`，然后执行 `assembleRelease`。发布签名私钥单独保存在本地，不打包进源码和 GitHub。

## 开源

应用采用 GNU AGPL v3，详见 LICENSE.txt。AndroidX、Media3 及相关开源运行库采用 Apache 2.0，详见 THIRD_PARTY.md 和 app/src/main/assets/licenses。公开源码与下载：https://github.com/senhao730-arch/file-format-converter 。
