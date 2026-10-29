from __future__ import annotations

from dataclasses import replace
import sys

from PySide6.QtCore import Qt, Signal, Slot, QPointF
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QCompleter, QScrollArea, QWidget, QFrame,
)

from .providers import PRESETS, BY_ID, identify, resolve, ModelClient
from .settings import Settings, SecretStore
from .tasks import Task
from .catalog import ModelList, load_catalog, save_catalog, load_enabled, save_enabled, catalog_identity
from .model_picker import ModelPicker


class SelectBox(QComboBox):
    """Always show an explicit chevron, including with the custom Qt stylesheet."""
    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#73819a'))
        x,y=self.width()-16,self.height()/2
        painter.drawPolygon(QPolygonF([QPointF(x-4,y-2),QPointF(x+4,y-2),QPointF(x,y+3)]))
        painter.end()


def label(text, role=None):
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(True)
    return widget


def fetch_models(connection):
    client = ModelClient(connection)
    try:
        return client.models()
    finally:
        client.close()


class Preferences(QDialog):
    saved = Signal(object)

    def __init__(self, page: str, settings: Settings, secrets: SecretStore, pool, ocr, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.settings = settings
        self.secrets = secrets
        self.pool = pool
        self.ocr = ocr
        self.page = page
        self._jobs = {}
        self._revision = 0
        self._loaded = False
        self._identity = ""
        self.enabled_models = []
        self._enabled_drafts = {}
        self.models_list = []
        self._model_connection = None
        self.setMinimumWidth(540)
        self.setWindowTitle("FloatTranslate · 设置")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 28, 30, 24)
        outer.setSpacing(15)
        headings = {
            "api": ("连接你的模型", "支持官方服务商与第三方兼容接口。"),
            "ocr": ("识别与语言", "识别在本地完成，仅将文字发送到你选择的接口。"),
            "appearance": ("边框与动效", "流光边框，轻量覆盖。拖动四边或四角即可改变范围。"),
        }
        title, subtitle = headings[page]
        outer.addWidget(label(title, "title"))
        outer.addWidget(label(subtitle, "muted"))
        self.form = QFormLayout()
        self.form.setHorizontalSpacing(22)
        self.form.setVerticalSpacing(13)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        if page=='api':
            host=QWidget()
            host.setObjectName("api-form-host")
            host.setStyleSheet("QWidget#api-form-host {background:white;}")
            host_layout=QVBoxLayout(host)
            host_layout.setContentsMargins(0,0,8,0)
            host_layout.addLayout(self.form)
            self.scroll=QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.scroll.setWidget(host)
            self.scroll.setMinimumHeight(260)
            outer.addWidget(self.scroll,1)
            available=self.screen().availableGeometry().height()
            self.resize(680,min(850,available-70))
            self.setMaximumHeight(available-40)
        else:
            outer.addLayout(self.form)
        self.message = label("", "muted")
        outer.addWidget(self.message)
        if page == "api":
            self._api()
        elif page == "ocr":
            self._ocr()
        else:
            self._appearance()
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("保存")
        self.save_button.setProperty("primary", True)
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_button)
        outer.addLayout(buttons)

    def _api(self):
        self.provider = SelectBox()
        for preset in PRESETS:
            self.provider.addItem(preset.label, preset.id)
        self.provider.setCurrentIndex(max(0, self.provider.findData(self.settings.provider)))
        self.url = QLineEdit(self.settings.base_url)
        self.url.setPlaceholderText("https://api.example.com/v1")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("输入此接口的 API Key；本机模型可留空")
        self.reveal = QCheckBox("显示 Key")
        self.reveal.toggled.connect(lambda value: self.key.setEchoMode(QLineEdit.EchoMode.Normal if value else QLineEdit.EchoMode.Password))
        self.hint = label("", "muted")
        self.validate = QPushButton("验证并获取模型")
        self.validate.setProperty("primary", True)
        self.validate.clicked.connect(self._validate)
        self.model = SelectBox()
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.model.setMaxVisibleItems(12)
        self.model.setMinimumContentsLength(20)
        self.model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model.setEditText(self.settings.model)
        self.protocol = SelectBox()
        for text,value in [('自动（按服务商）','auto'),('OpenAI · Chat Completions','openai'),('OpenAI · Responses','responses'),('Anthropic · Messages','anthropic'),('Google · Gemini','google')]:
            self.protocol.addItem(text,value)
        self.protocol.setCurrentIndex(max(0,self.protocol.findData(self.settings.api_protocol)))
        self.auth = SelectBox()
        for text,value in [('自动（按协议）','auto'),('Bearer Token','bearer'),('x-api-key','x-api-key'),('x-goog-api-key','x-goog-api-key')]:
            self.auth.addItem(text,value)
        self.auth.setCurrentIndex(max(0,self.auth.findData(self.settings.auth_mode)))
        self.choose_model = QPushButton('勾选 / 管理模型…')
        self.choose_model.clicked.connect(self._choose_model)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model,1)
        model_row.addWidget(self.choose_model)
        self.model_count = label('尚未获取模型；可直接填写完整模型 ID。','muted')
        self.test_model = QPushButton('测试所选模型（少量额度）')
        self.test_model.clicked.connect(self._test_model)
        self.model.lineEdit().setPlaceholderText("先获取模型，也可手动填写模型 ID")
        self.form.addRow("服务商", self.provider)
        self.form.addRow("API 地址", self.url)
        self.form.addRow("API 协议", self.protocol)
        self.form.addRow("鉴权方式", self.auth)
        self.form.addRow("API Key", self.key)
        self.form.addRow("", self.reveal)
        self.form.addRow("", self.hint)
        self.form.addRow("", self.validate)
        self.form.addRow("模型", model_row)
        self.form.addRow("", self.model_count)
        self.form.addRow("", self.test_model)
        self.fast_mode = QCheckBox("优先速度（DeepSeek 官方接口关闭思考模式）")
        self.fast_mode.setChecked(self.settings.fast_mode)
        self.form.addRow("翻译策略",self.fast_mode)
        self.form.addRow("", label("Key 存入系统凭据管理器 / macOS 钥匙串。\n自动识别依据地址和格式，不会向多个平台试探发送 Key。", "muted"))
        if not self.url.text() and self.provider.currentData() != "auto":
            self.url.setText(BY_ID[self.provider.currentData()].url)
        self._load_key()
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.url.textChanged.connect(self._connection_changed)
        self.key.textEdited.connect(self._key_edited)
        self.protocol.currentIndexChanged.connect(self._connection_changed)
        self.auth.currentIndexChanged.connect(self._connection_changed)
        self._update_hint()
        self._load_catalog()

    def _current_identity(self):
        pid = self.provider.currentData()
        preset = identify(self.url.text(), self.key.text()) if pid == "auto" else BY_ID[pid]
        return SecretStore.identity(preset.id, self.url.text().strip() or preset.url)

    def _load_key(self):
        self._identity = self._current_identity()
        stored = self.secrets.get(self._identity)
        self.key.setText(stored)
        self._loaded = bool(stored)

    @Slot()
    def _provider_changed(self):
        self._revision += 1
        self.key.clear()
        self._loaded = False
        self.url.setText(BY_ID[self.provider.currentData()].url)
        self.model.clear()
        self._load_key()
        self._update_hint()
        self._load_catalog()

    @Slot()
    def _connection_changed(self):
        self._revision += 1
        if self._loaded and self._identity != self._current_identity():
            self.key.clear()
            self._loaded = False
        self._update_hint()
        self._load_catalog()

    @Slot()
    def _key_edited(self):
        self._loaded = False
        self._revision += 1
        self._update_hint()
        self._load_catalog()

    def _update_hint(self):
        pid = self.provider.currentData()
        preset = identify(self.url.text(), self.key.text()) if pid == "auto" else BY_ID[pid]
        wire=self.protocol.currentData()
        if wire=='auto':
            wire=preset.protocol
        self.hint.setText(f'服务商：{preset.label} · 协议：{wire} · 鉴权：{self.auth.currentText()}。未知网关不会仅凭 Key 猜测供应商。')

    @Slot()
    def _validate(self):
        try:
            connection = self._resolve()
        except ValueError as error:
            self.message.setText(str(error))
            return
        self._model_connection = connection
        self.validate.setEnabled(False)
        self.message.setText("正在验证连接并获取模型…")
        identity = ("models", self._revision)
        task = Task(identity, lambda: fetch_models(connection))
        self._jobs[identity] = task
        task.signals.finished.connect(self._done)
        self.pool.start(task)

    def _resolve(self):
        return resolve(self.provider.currentData(),self.url.text(),self.key.text(),
                       fast_mode=self.fast_mode.isChecked(),protocol=self.protocol.currentData(),auth_mode=self.auth.currentData())

    def _set_models(self,models,*,cached=False):
        current=self.model.currentText()
        self.models_list=ModelList(dict.fromkeys(models),types=getattr(models,"types",{}))
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(self.models_list)
        self.model.setCurrentIndex(-1)
        self.model.setEditText(current)
        self.model.blockSignals(False)
        completer=self.model.completer()
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.model_count.setText(('已缓存' if cached else '接口返回')+f' {len(self.models_list)} 个模型；可搜索全部或手动填写，重新获取不会替换当前输入。')

    def _load_catalog(self):
        try:
            connection=self._resolve()
            models=load_catalog(connection)
        except ValueError:
            models=[]
        self._set_models(models,cached=True)
        try:
            identity=catalog_identity(connection)
            self.enabled_models=self._enabled_drafts.get(identity,load_enabled(connection,self.model.currentText()))
        except (ValueError,UnboundLocalError):
            self.enabled_models=[self.model.currentText()] if self.model.currentText() else []
        if not models:
            self.model_count.setText('当前连接尚无模型缓存；获取列表或直接填写模型 ID。')

    def _choose_model(self):
        picker=ModelPicker(self.models_list,self.model.currentText(),self,enabled=self.enabled_models)
        if picker.exec()==QDialog.DialogCode.Accepted:
            self.model.setEditText(picker.model_id())
            self.enabled_models=picker.enabled_ids()
            try:
                self._enabled_drafts[catalog_identity(self._resolve())]=self.enabled_models
            except ValueError:
                pass
            self.model_count.setText(f'候选 {len(self.models_list)} 个 · 已勾选 {len(self.enabled_models)} 个；保存设置后仅勾选项进入右键菜单。')

    def _test_model(self):
        try:
            connection=self._resolve()
            model=self.model.currentText().strip()
            if not model:
                raise ValueError('请先选择或填写要测试的模型 ID')
        except ValueError as error:
            self.message.setText(str(error))
            return
        self.test_model.setEnabled(False)
        self.message.setText('正在测试当前选择的模型…')
        identity=('test',self._revision)
        def probe():
            client=ModelClient(connection)
            try:
                client.generate(model,'Reply only OK.','Connection test.',max_output_tokens=64)
                return model
            finally:
                client.close()
        task=Task(identity,probe)
        self._jobs[identity]=task
        task.signals.finished.connect(self._done)
        self.pool.start(task)

    def _ocr(self):
        self.target = SelectBox()
        self.target.setEditable(True)
        self.target.addItems(["简体中文", "繁體中文", "English", "日本語", "한국어", "Deutsch", "Français"])
        self.target.setCurrentText(self.settings.target)
        self.language = SelectBox()
        self.language.addItem("跟随系统 / 自动", "")
        self.language.setEnabled(False)
        self.interval = QSpinBox()
        self.interval.setRange(700, 10000)
        self.interval.setSingleStep(100)
        self.interval.setSuffix(" 毫秒")
        self.interval.setValue(self.settings.interval_ms)
        self.form.addRow("目标语言", self.target)
        self.form.addRow("OCR 源语言", self.language)
        self.form.addRow("自动扫描间隔", self.interval)
        self.form.addRow("", label("画面不变时跳过 OCR；文字不变时复用翻译缓存。\nWindows 需安装对应语言的 OCR 组件。macOS 使用 Apple Vision。", "muted"))
        self.message.setText("正在读取本机 OCR 支持的语言…")
        task = Task(("languages", 0), self.ocr.languages)
        self._jobs[task.identity] = task
        task.signals.finished.connect(self._done)
        self.pool.start(task)

    def _appearance(self):
        self.motion = QCheckBox("减少动效（即时展开 / 静态光晕）")
        self.motion.setChecked(self.settings.reduce_motion)
        self.on_top = QCheckBox("识别框始终置顶")
        self.on_top.setChecked(self.settings.always_on_top)
        self.border = QSpinBox()
        self.border.setRange(1, 5)
        self.border.setSuffix(" px")
        self.border.setValue(self.settings.border_width)
        self.opacity = QSpinBox()
        self.opacity.setRange(80, 100)
        self.opacity.setSuffix(" %")
        self.opacity.setValue(self.settings.mask_opacity)
        if sys.platform == "win32":
            self.opacity.setValue(100)
            self.opacity.setEnabled(False)
            self.opacity.setToolTip("当前无闪烁覆盖模式使用不透明底色")
        self.font_size = QSpinBox()
        self.font_size.setRange(10, 28)
        self.font_size.setSuffix(" px")
        self.font_size.setValue(self.settings.font_size)
        self.form.addRow("动效", self.motion)
        self.form.addRow("窗口", self.on_top)
        self.form.addRow("边框粗细", self.border)
        self.form.addRow("译文底色不透明度", self.opacity)
        self.form.addRow("译文字号上限", self.font_size)
        self.form.addRow("", label("拖动书签移动；拖动蓝色角部触点缩放；触底时触点移到上方。\n译文在原文位置覆盖，超长内容会自动缩小字号。", "muted"))

    @Slot(object)
    def _done(self, payload):
        identity, value, error = payload
        self._jobs.pop(identity, None)
        kind, revision = identity
        if kind == "models":
            self.validate.setEnabled(True)
            if revision != self._revision:
                self.message.setText("连接参数已改变，请重新验证。")
                return
            if error:
                self.message.setText(error)
                return
            self._set_models(value)
            warning=getattr(value,'warning','')
            cache_warning=''
            try:
                if not warning:
                    save_catalog(self._model_connection,value)
            except OSError:
                cache_warning=' 模型缓存未能写入，当前仍可选择。'
            self.message.setText((warning or (f'模型列表读取成功，共 {len(value)} 个。列表由当前 Key 和网关提供；未列出时可手动填 ID，并点击测试。' if value else '接口返回空列表；可手动填写完整模型 ID，再测试所选模型。'))+cache_warning)
        elif kind=='test':
            self.test_model.setEnabled(True)
            if revision != self._revision:
                self.message.setText('连接参数已改变，请重新测试。')
            elif error:
                self.message.setText('模型测试未通过：'+error)
            elif self.model.currentText().strip()!=value:
                self.message.setText('测试期间模型选择已改变，请测试当前模型。')
            else:
                self.message.setText('所选模型调用成功，可保存用于翻译。')
        else:
            self.language.setEnabled(True)
            if error:
                self.message.setText(error)
                if self.settings.ocr_language:
                    self.language.addItem(self.settings.ocr_language, self.settings.ocr_language)
            else:
                for language in value:
                    self.language.addItem(language, language)
                self.message.setText(f"本机支持 {len(value)} 种 OCR 语言。")
            index = self.language.findData(self.settings.ocr_language)
            self.language.setCurrentIndex(max(0, index))

    @Slot()
    def _save(self):
        settings = self.settings
        try:
            if self.page == "api":
                connection = self._resolve()
                model = self.model.currentText().strip()
                if not model:
                    raise ValueError("请选择或填写模型 ID")
                durable = self.secrets.set(SecretStore.identity(connection.provider, connection.base_url), self.key.text().strip())
                save_enabled(connection,self.enabled_models,model)
                settings = replace(settings, provider=self.provider.currentData(), base_url=connection.base_url, model=model, fast_mode=self.fast_mode.isChecked(), api_protocol=self.protocol.currentData(),auth_mode=self.auth.currentData())
                if not durable:
                    self.parent().notify("系统钥匙串不可用：Key 仅保留到本次退出，下次启动需重新填写。")
            elif self.page == "ocr":
                target = self.target.currentText().strip()
                if not target:
                    raise ValueError("请填写目标语言")
                settings = replace(settings, target=target, ocr_language=self.language.currentData() or "", interval_ms=self.interval.value())
            else:
                settings = replace(settings, reduce_motion=self.motion.isChecked(), always_on_top=self.on_top.isChecked(),
                                   border_width=self.border.value(), mask_opacity=self.opacity.value(), font_size=self.font_size.value())
            settings.save()
        except (ValueError, OSError) as error:
            self.message.setText(str(error))
            return
        self.saved.emit((settings, self.models_list))
        self.accept()
