# GitHub 更新发布

右键书签 → **关于 / 检查更新**。填写完整的 `用户名/FloatTranslate-next`，保存后检查更新。自动检查只在启动后执行，每天最多一次；发现版本后提示，用户点击下载和升级。公开仓库无需 GitHub Token；翻译 API Key 不参与更新请求。

默认更新源为 `Yuluoqianmo/FloatTranslate-next`。未发布有效附件时不会把其他软件或原项目版本当作本软件更新。

## 发布 Windows x64 更新

1. 在 `floattranslate/__init__.py`、`pyproject.toml`、`build.py` 更新版本，格式 `0.3.9` 等三段数字。只接受更高稳定版本；不安装草稿或预发布。
2. 在 Windows x64 环境执行 `python build.py`。
3. 执行 `python release_manifest.py dist/FloatTranslateNext.exe release`。
4. 在配置的仓库创建 **Release**，标签为 `v0.3.9`（与程序版本相同），将 `release/` 内的 **EXE 和 floattranslate-next-update.json 两个附件一起上传**。只上传源代码、只推送标签或只上传 EXE 不会触发升级。

程序读取最近 100 个 GitHub Releases，从高到低选择适用于本机的更高稳定版本。清单必须有 `product: floattranslate-next`、`schema: 1`、匹配版本、平台、文件名、大小和 SHA-256；清单和下载附件必须属于所配置的仓库。不要将翻译 Key、settings.json、用户配置或临时工作目录上传到仓库。

## 安装行为

Windows EXE：下载完成后先校验 SHA-256；点击“升级并重启”后，在独立进程启动新版本的 Qt 健康检查，成功才退出旧程序。后台助手等待 EXE 解锁，再在原目录原子替换，保留 `.previous` 备份并重新启动。原目录不可写或验证失败时保留旧程序；可通过“打开下载目录”手动安装。配置和 Key 保持在原来的系统配置 / 凭据存储中。

安装结果保存在配置目录 `updates/install-*.result`。升级中不要手动移动或删除当前 EXE。SHA-256 校验验证下载完整性；更新仓库维护者仍须是你信任的人。

源码运行和 macOS：支持版本检查；仅当发布清单含有对应平台附件时提供下载，安装通过发布页手动完成。macOS 自动替换与签名公证尚未实现、未实机验收。
