from __future__ import annotations

import platform
import sys
import time
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
                              QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout)

from . import __version__
from .settings import config_dir
from .tasks import Task
from . import updates


class UpdateController(QObject):
    changed = Signal()

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.status = "尚未检查更新"
        self.busy = False
        self.release = None
        self.downloaded = None
        self.progress = 0
        self.task = None
        self._generation = 0
        self._install_paths = None
        self.install_timer = QTimer(self)
        self.install_timer.setInterval(250)
        self.install_timer.timeout.connect(self._installation_ready)
        if not owner.test_mode:
            QTimer.singleShot(6000, self.automatic_check)

    def automatic_check(self):
        settings = self.owner.settings
        if settings.update_auto_check and settings.update_repo and time.time() - settings.update_last_check >= 86400:
            self.check(automatic=True)

    def reset(self):
        self._generation += 1
        self.release = self.downloaded = None
        self.status = "更新源已保存，请检查更新"
        self.changed.emit()

    def _run(self, action, function, done):
        if self.busy:
            return
        self.busy = True
        self.status = action
        task = Task(self._generation, function)
        self.task = task
        def finished(payload):
            identity, value, error = payload
            self.busy = False
            self.task = None
            if identity == self._generation and not self.owner._closing:
                if error:
                    self.status = "更新失败：" + error
                else:
                    done(value)
            self.changed.emit()
        task.signals.finished.connect(finished)
        task.signals.progress.connect(self._progress)
        self.changed.emit()
        self.owner.preferences_pool.start(task)

    def _progress(self, value):
        self.progress = value
        self.changed.emit()

    def check(self, automatic=False):
        if self.busy:
            return
        try:
            repo = updates.repository(self.owner.settings.update_repo)
        except ValueError as error:
            self.status = str(error)
            self.changed.emit()
            return
        self.release = self.downloaded = None
        try:
            self.owner.settings = replace(self.owner.settings, update_last_check=int(time.time()))
            if not self.owner.test_mode:
                self.owner.settings.save()
        except OSError as error:
            self.status = "无法保存更新检查时间：" + str(error)
            self.changed.emit()
            return
        def done(release):
            self.release = release
            self.status = f"发现新版本 {release.version}" if release else "未发现适用于本机的更高稳定版本"
            if automatic and release:
                self.owner.notify(f"发现 FloatTranslate Next {release.version}，请在‘关于’中升级")
        self._run("正在检查 GitHub Releases…", lambda: updates.check(repo, __version__), done)

    def download(self):
        if not self.release or self.busy:
            return
        release = self.release
        self.progress = 0
        def retrieve():
            return updates.download(release, config_dir() / "updates", progress=self.task.signals.progress.emit)
        def done(path):
            self.downloaded = path
            self.status = "下载与 SHA-256 校验完成，可升级并重启"
        self._run("正在下载更新…", retrieve, done)

    def install(self):
        if self.busy or not self.downloaded:
            return
        try:
            self._install_paths = updates.start_install(self.downloaded, self.release, config_dir() / "updates")
            self._install_started = time.monotonic()
            self.busy = True
            self.status = "正在验证新版本能否启动…"
            self.install_timer.start()
        except (ValueError, OSError) as error:
            self.status = str(error)
        self.changed.emit()

    def _installation_ready(self):
        ready, result = self._install_paths
        if result.exists() or time.monotonic() - self._install_started > 90:
            self.install_timer.stop()
            self.busy = False
            self.status = ("升级失败：" + result.read_text("utf-8")) if result.exists() else "新版本启动检查超时，当前程序已保留"
            self.changed.emit()
        elif ready.exists():
            self.install_timer.stop()
            self.status = "正在退出并安装新版本…"
            self.changed.emit()
            if self.owner._dialog:
                self.owner._dialog.close()
            self.owner.close()


class AboutDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner.bookmark)
        self.owner = owner
        self.controller = owner.updater
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("关于 FloatTranslate Next")
        self.resize(540, 540)
        layout = QVBoxLayout(self)
        title = QLabel(f"FloatTranslate Next  {__version__}")
        title.setStyleSheet("font-size:20px;font-weight:600;padding:8px 0")
        layout.addWidget(title)
        layout.addWidget(QLabel(f"屏幕原位翻译 · MIT License\n{platform.system()} {platform.release()} · {updates.platform_key()}"))
        upstream = QLabel('<a href="https://github.com/CH-DONG77/FloatTranslate">原项目 CH-DONG77/FloatTranslate</a>')
        upstream.setOpenExternalLinks(True)
        layout.addWidget(upstream)
        layout.addWidget(QLabel("更新仓库（公开 GitHub 仓库）"))
        self.repo = QLineEdit(owner.settings.update_repo)
        self.repo.setPlaceholderText("用户名/FloatTranslate-next 或完整仓库链接")
        layout.addWidget(self.repo)
        self.auto = QCheckBox("启动时自动检查更新（每天最多一次）")
        self.auto.setChecked(owner.settings.update_auto_check)
        layout.addWidget(self.auto)
        save = QPushButton("保存更新设置")
        save.clicked.connect(self.save)
        layout.addWidget(save)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setPlaceholderText("新版本更新说明会显示在这里。需发布本软件的更新清单和对应平台附件。")
        layout.addWidget(self.notes)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        self.check_button = QPushButton("检查更新")
        self.check_button.clicked.connect(self.check)
        self.download_button = QPushButton("下载更新")
        self.download_button.clicked.connect(self.controller.download)
        self.install_button = QPushButton("升级并重启")
        self.install_button.clicked.connect(self.controller.install)
        for button in (self.check_button, self.download_button, self.install_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        links = QHBoxLayout()
        page = QPushButton("打开发布页")
        page.clicked.connect(self.open_releases)
        folder = QPushButton("打开下载目录")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_dir() / "updates"))))
        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        for button in (page, folder, close):
            links.addWidget(button)
        layout.addLayout(links)
        self.controller.changed.connect(self.refresh)
        self.refresh()

    def save(self):
        if self.controller.busy:
            return False
        try:
            repo = updates.repository(self.repo.text()) if self.repo.text().strip() else ""
            settings = replace(self.owner.settings, update_repo=repo, update_auto_check=self.auto.isChecked(), update_last_check=0)
            if not self.owner.test_mode:
                settings.save()
            self.owner.settings = settings
            self.repo.setText(repo)
            self.controller.reset()
            return True
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            return False

    def check(self):
        if (self.repo.text().strip() != self.owner.settings.update_repo or self.auto.isChecked() != self.owner.settings.update_auto_check) and not self.save():
            return
        self.controller.check()

    def open_releases(self):
        try:
            repo = updates.repository(self.repo.text())
            QDesktopServices.openUrl(QUrl(f"https://github.com/{repo}/releases"))
        except ValueError as error:
            self.status.setText(str(error))

    def refresh(self):
        controller = self.controller
        self.status.setText(controller.status)
        self.repo.setEnabled(not controller.busy)
        self.auto.setEnabled(not controller.busy)
        self.check_button.setEnabled(not controller.busy)
        self.download_button.setEnabled(not controller.busy and controller.release is not None)
        self.install_button.setEnabled(not controller.busy and controller.downloaded is not None and sys.platform == "win32" and getattr(sys, "frozen", False))
        self.progress.setVisible(controller.busy and controller.status.startswith("正在下载"))
        self.progress.setValue(controller.progress)
        self.notes.setPlainText(controller.release.notes if controller.release else "")


def show_about(owner):
    if owner._dialog:
        owner._dialog.raise_()
        owner._dialog.activateWindow()
        return
    owner._dialog = AboutDialog(owner)
    owner._dialog.finished.connect(owner._dialog_finished)
    owner._dialog.show()
