"""Searchable, untruncated model selection with explicit manual IDs."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QListWidget, QVBoxLayout, QPushButton, QHBoxLayout


class ModelPicker(QDialog):
    def __init__(self, models, current='', parent=None, *, enabled=None):
        super().__init__(parent)
        self.setWindowTitle('选择翻译模型')
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,True)
        self.resize(580,520)
        self.checked=set(enabled if enabled is not None else ([current] if current else []))
        self.models=list(dict.fromkeys(list(models)+list(self.checked)+([current] if current else [])))
        self.types=getattr(models,"types",{})
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('勾选要保留在右键菜单的模型；双击行或用按钮设为当前模型。'))
        self.search=QLineEdit()
        self.search.setPlaceholderText('搜索，例如 deepseek、claude、qwen…')
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.count=QLabel()
        layout.addWidget(self.count)
        tools=QHBoxLayout()
        clear=QPushButton('仅保留当前模型')
        clear.clicked.connect(self.only_current)
        add=QPushButton('勾选手填 ID')
        add.clicked.connect(self.add_manual)
        use=QPushButton('设为当前模型')
        use.clicked.connect(self.use_selected)
        tools.addWidget(use)
        tools.addWidget(clear)
        tools.addWidget(add)
        tools.addStretch()
        layout.addLayout(tools)
        self.list=QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self.list,1)
        layout.addWidget(QLabel('当前选择 / 手动填写模型 ID'))
        self.selected=QLineEdit(current)
        self.selected.setPlaceholderText('原样填写平台提供的模型 ID，不必在列表中')
        layout.addWidget(self.selected)
        note=QLabel('当前使用模型会自动保留在菜单中；仅勾选不会改变当前模型。')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('保存勾选与当前模型')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        layout.addWidget(buttons)
        self.search.textChanged.connect(self.filter)
        self.list.itemDoubleClicked.connect(lambda item:self.use_selected())
        self.list.itemChanged.connect(self.check_changed)
        buttons.accepted.connect(lambda:self.accept() if self.selected.text().strip() else self.selected.setFocus())
        buttons.rejected.connect(self.reject)
        self.filter('')
        self.selected.setText(current)

    def filter(self,text):
        selected=self.selected.text()
        self.list.blockSignals(True)
        self.list.clear()
        matches=[m for m in self.models if text.casefold() in m.casefold()]
        self.list.addItems(matches)
        for index,model in enumerate(matches):
            item=self.list.item(index)
            item.setData(Qt.ItemDataRole.UserRole,model)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if model in self.checked else Qt.CheckState.Unchecked)
            types=self.types.get(model,[])
            if types:
                text='图像生成 · 不用于文字翻译' if set(types)<= {'image-generation','images','image-edit'} else ' / '.join(types)
                item.setText(model+'    ['+text+']')
            item.setToolTip(model+('\n支持端点：'+', '.join(types) if types else ''))
            if model==selected:
                self.list.setCurrentRow(index)
        self.list.blockSignals(False)
        self.count.setText(f'候选 {len(self.models)} 个 · 已勾选 {len(self.checked)} 个 · 当前显示 {len(matches)} 个')

    def model_id(self):
        return self.selected.text().strip()

    def check_changed(self,item):
        model=item.data(Qt.ItemDataRole.UserRole)
        if item.checkState()==Qt.CheckState.Checked:
            self.checked.add(model)
        else:
            self.checked.discard(model)
        self.count.setText(f'候选 {len(self.models)} 个 · 已勾选 {len(self.checked)} 个 · 当前显示 {self.list.count()} 个')

    def only_current(self):
        self.checked={self.model_id()} if self.model_id() else set()
        self.filter(self.search.text())

    def add_manual(self):
        model=self.model_id()
        if model:
            self.checked.add(model)
            if model not in self.models:
                self.models.append(model)
            self.filter(self.search.text())

    def enabled_ids(self):
        # Current model is always kept so it remains accessible after saving.
        return list(dict.fromkeys([m for m in self.models if m in self.checked]+([self.model_id()] if self.model_id() else [])))

    def use_selected(self):
        item=self.list.currentItem()
        if item:
            model=item.data(Qt.ItemDataRole.UserRole)
            self.selected.setText(model)
            self.checked.add(model)
            self.filter(self.search.text())
