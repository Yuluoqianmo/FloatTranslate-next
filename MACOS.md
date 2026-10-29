# macOS 测试版

0.3.9 修复 macOS 27.0.1 的 Vision 图像请求初始化异常，并在高精度识别失败时自动切换到兼容识别。该路径的识别精度和语言覆盖可能与高精度引擎不同；可在“翻译耗时与诊断”查看实际使用的识别引擎。API Key 无需因此更换。

Apple M1 / M2 / M3 / M4 等 Apple 芯片选择 arm64；Intel Mac 选择 x64。两种架构分别在 GitHub 的原生 macOS 构建机编译。

打开 DMG，将 FloatTranslateNext.app 拖入 Applications（应用程序）。也可以解压 .app.zip 后拖入应用程序。先放入固定位置再授权，避免移动或更新包后权限失效。

本包使用本地临时签名，尚未使用 Apple Developer ID 签名及公证。首次运行若系统拦截，请在“系统设置 → 隐私与安全性”确认该测试包并使用“仍要打开”。只运行来自你信任的仓库的包。

开始翻译前，在“系统设置 → 隐私与安全性 → 屏幕与系统音频录制”（旧系统称“屏幕录制”）允许 FloatTranslate Next，按系统要求退出后重开。全局快捷键还需要“辅助功能”权限；未授权时可点击书签、右键立即翻译。默认 Alt+T 对应 Mac 的 Option+T，Ctrl+Alt+Enter 在 Qt 的 Mac 键位规则下对应 Command+Option+Return，可在设置更改。

OCR 使用 Apple Vision，无需额外下载识别模型。API 设置沿用兼容的服务和模型；Key 保存在 macOS 钥匙串。

构建后自动验证：Qt 启动、PyObjC / AppKit / Quartz 导入、Apple Vision 对合成英文图片的真实识别、架构和 ad-hoc 签名。CI 不采集屏幕、不请求翻译 API、不授予系统隐私权限。因此屏幕捕获、真实桌面覆盖、多屏 Retina、鼠标穿透、全局快捷键仍须在你的 Mac 实机验证。当前 macOS 不支持 Windows 的独立底层窗口捕获，自动翻译监测走受限的截图降级路径；以手动立即翻译为主进行测试。

本次构建环境为 macOS 15，Qt 6.12 依赖要求 macOS 14 或更新系统；14 尚未实机验收。macOS 自动安装更新尚未实现，可从“关于”打开仓库安装新版。

## 选区外观与刷新行为

选区使用单层细描边，不叠加系统窗口阴影。识别和翻译时，边框以 3.2 秒周期缓慢呼吸，尺寸和线宽固定，只改变蓝色透明度，并保留紧贴边缘的轻微光晕；书签顶部同时显示旋转进度。完成后停止所有持续动效。开启“减少动态效果”时边框及进度标记保持静止。

macOS 当前仍使用隐藏译文窗口后截图的兼容路径。自动翻译可以完成首次识别，但已有译文时不再定时重截，以免整个译文窗口周期性闪烁。页面滚动或内容变化后，请按回车、翻译快捷键或“立即翻译”刷新；拖动或清除译文后可重新自动识别。支持独立捕获的 Windows 源窗口路径继续自动监测。

外观参考：QuickRecorder 的无阴影选区与细描边（`QuickRecorder/ViewModel/AreaSelector.swift`），以及 Easydict 的细边框卡片（`Easydict/Swift/Utility/Views/View+BorderedCard.swift`）；本次使用 Qt 重新实现，未复制 Swift 代码。
