"""Per-run diagnostics with real measurements, including failures/cancellations."""
import json
from .dialogs import SelectBox

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QComboBox, QHeaderView, QCheckBox


class TimingsDialog(QDialog):
    def __init__(self,records,parent=None,*,counts=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,True)
        self.setWindowTitle('单次翻译耗时与诊断')
        self.resize(620,640)
        self.records=list(reversed(records))
        self.counts=counts or {"total":len(records),"manual":len(records),"auto":0}
        layout=QVBoxLayout(self)
        title=QLabel(f'本次启动翻译尝试 {self.counts["total"]} 次 · 点击 / 设置触发 {self.counts["manual"]} 次 · 自动 {self.counts["auto"]} 次')
        title.setWordWrap(True)
        layout.addWidget(title)
        self.runs=SelectBox()
        for record in self.records:
            self.runs.addItem(f"翻译 #{record.get('run','—')} · {record.get('status','未知')} · {record.get('end_to_end_ms',0)/1000:.2f} 秒 · {'自动' if record.get('trigger')=='auto' else '点击/设置'}")
        layout.addWidget(self.runs)
        self.summary=QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.details=QCheckBox('查看详细阶段（毫秒）')
        self.details.toggled.connect(lambda checked:self.display(self.runs.currentIndex()))
        layout.addWidget(self.details)
        self.table=QTableWidget(0,2)
        self.table.setHorizontalHeaderLabels(['阶段','耗时 / 结果'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table,1)
        self.error=QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        note=QLabel('默认用秒显示主要耗时；详细阶段可展开。后台画面检查不计数，自动模式只在内容变化后产生新任务。保留最近 20 次；取消表示该次旧结果没有显示。')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('关闭')
        copy=buttons.addButton('复制诊断',QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(self.copy)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.runs.currentIndexChanged.connect(self.display)
        self.display(0)

    def display(self,index):
        if not self.records:
            return
        record=self.records[index]
        self.summary.setText(f"模型：{record.get('model','—')}\n目标语言：{record.get('target','—')}\n截图：{record.get('capture_backend','—')}\n结果：{record.get('status','—')} · 缓存 {record.get('cache_hits',0)} / {record.get('paragraphs',0)} 段")
        stages=[('截图','capture_ms'),('画面比对','scene_ms'),('线程排队','queue_ms'),('图像摘要','hash_ms'),('OCR 识别'+('（缓存）' if record.get('ocr_cached') else ''),'ocr_ms'),('段落缓存查询','cache_ms'),('连接准备（客户端）','client_init_ms'),('接口等待与生成（含格式解析）','api_ms'),('↳ 首个内容返回','first_content_ms'),('↳ 结果格式解析','format_ms'),('覆盖绘制（CPU 提交）','render_ms'),('端到端总耗时','end_to_end_ms')]
        if not self.details.isChecked():
            stages=[('截取原文','capture_ms'),('识别文字'+('（缓存）' if record.get('ocr_cached') else ''),'ocr_ms'),('准备连接','client_init_ms'),('等待模型翻译','api_ms'),('显示译文','render_ms'),('本次总耗时','end_to_end_ms')]
        self.table.setRowCount(len(stages))
        for row,(title,key) in enumerate(stages):
            self.table.setItem(row,0,QTableWidgetItem(title))
            value=record.get(key)
            if key=='render_ms' and record.get('status') not in ('完成','部分完成'):
                value=None
            text='未执行 / 未测得' if value is None else (f'{value} ms' if self.details.isChecked() else f'{value/1000:.2f} 秒')
            self.table.setItem(row,1,QTableWidgetItem(text))
        self.error.setText(record.get('error',''))

    def copy(self):
        record={k:v for k,v in self.records[self.runs.currentIndex()].items() if not k.startswith('_')}
        QApplication.clipboard().setText(json.dumps(record,ensure_ascii=False,indent=2))
