# macOS 测试版

Apple M1 / M2 / M3 / M4 等 Apple 芯片选择 arm64；Intel Mac 选择 x64。两种架构分别在 GitHub 的原生 macOS 构建机编译。

打开 DMG，将 FloatTranslateNext.app 拖入 Applications（应用程序）。也可以解压 .app.zip 后拖入应用程序。先放入固定位置再授权，避免移动或更新包后权限失效。

本包使用本地临时签名，尚未使用 Apple Developer ID 签名及公证。首次运行若系统拦截，请在“系统设置 → 隐私与安全性”确认该测试包并使用“仍要打开”。只运行来自你信任的仓库的包。

开始翻译前，在“系统设置 → 隐私与安全性 → 屏幕与系统音频录制”（旧系统称“屏幕录制”）允许 FloatTranslate Next，按系统要求退出后重开。全局快捷键还需要“辅助功能”权限；未授权时可点击书签、右键立即翻译。默认 Alt+T 对应 Mac 的 Option+T，Ctrl+Alt+Enter 在 Qt 的 Mac 键位规则下对应 Command+Option+Return，可在设置更改。

OCR 使用 Apple Vision，无需额外下载识别模型。API 设置沿用兼容的服务和模型；Key 保存在 macOS 钥匙串。

构建后自动验证：Qt 启动、PyObjC / AppKit / Quartz 导入、Apple Vision 对合成英文图片的真实识别、架构和 ad-hoc 签名。CI 不采集屏幕、不请求翻译 API、不授予系统隐私权限。因此屏幕捕获、真实桌面覆盖、多屏 Retina、鼠标穿透、全局快捷键仍须在你的 Mac 实机验证。当前 macOS 不支持 Windows 的独立底层窗口捕获，自动翻译监测走受限的截图降级路径；以手动立即翻译为主进行测试。

本次构建环境为 macOS 15，Qt 6.12 依赖要求 macOS 14 或更新系统；14 尚未实机验收。macOS 自动安装更新尚未实现，可从“关于”打开仓库安装新版。
