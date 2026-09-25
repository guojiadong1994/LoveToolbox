import os
import json
import shutil
import pandas as pd
from copy import copy

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QComboBox, QListWidget,
    QListWidgetItem, QProgressBar, QGroupBox, QListWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal


DEFAULT_FIELDS = [
    "账号id",
    "总消耗(元)",
    "现金消耗(元)",
    "媒体返货消耗(元)",
    "媒体赔付消耗(元)",
    "代理赔付消耗(元)",
    "结算消耗(元)",
]

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".lovetoolbox")
CONFIG_FILE = os.path.join(CONFIG_DIR, "data_converter_config.json")


class DataConvertWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, file_path, save_dir, date_value, tasks, fields):
        super().__init__()
        self.file_path = file_path
        self.save_dir = save_dir
        self.date_value = date_value
        self.tasks = tasks
        self.fields = fields

    def find_header(self):
        preview = pd.read_excel(self.file_path, header=None, nrows=20, keep_default_na=False)
        for i, row in preview.iterrows():
            values = [str(x).strip() for x in row.tolist()]
            if "日期" in values and "任务" in values and "账号id" in values:
                return i
        return None

    def format_excel(self, path):
        wb = load_workbook(path)
        ws = wb.active

        for col in ws.columns:
            max_len = 0
            letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.value is not None:
                    max_len = max(max_len, len(str(cell.value)))
                    if cell.row > 1:
                        cell.number_format = "@"
            ws.column_dimensions[letter].width = max(max_len + 5, 18)

        wb.save(path)

    def run(self):
        try:
            self.progress.emit(5, "正在识别表头")
            header = self.find_header()
            if header is None:
                raise Exception("无法识别表头")

            df = pd.read_excel(self.file_path, header=header, keep_default_na=False)
            df.columns = [str(c).strip() for c in df.columns]

            df = df.dropna(how="all")

            df["日期"] = df["日期"].astype(str)
            df["任务"] = df["任务"].astype(str)

            if self.date_value:
                df = df[df["日期"] == self.date_value]

            if df.empty:
                raise Exception("当前日期没有数据")

            # 输出目录直接使用日期
            output = os.path.join(self.save_dir, self.date_value)
            os.makedirs(output, exist_ok=True)

            tasks = self.tasks or sorted(df["任务"].unique())

            for index, task in enumerate(tasks):
                self.progress.emit(
                    20 + int(index / max(len(tasks), 1) * 70),
                    f"正在生成 {task}"
                )

                part = df[df["任务"] == task]
                if part.empty:
                    continue

                cols = [c for c in self.fields if c in part.columns]
                if not cols:
                    continue

                result = part[cols]
                path = os.path.join(output, f"{task}消耗上传模版.xlsx")

                result.to_excel(path, index=False)
                self.format_excel(path)

            self.progress.emit(100, "生成完成")
            self.finished_signal.emit(output)

        except Exception as e:
            self.error_signal.emit(str(e))


class DataConverterApp(QWidget):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("转换数据")
        self.resize(1200, 700)

        self.file_path = ""
        self.last_output = ""
        self.worker = None
        self.config = self.load_config()

        self.init_ui()
        self.setStyleSheet("""
            QWidget { font-size: 15px; }
            QPushButton { font-size: 15px; padding: 6px 10px; }
            QLabel { font-size: 15px; }
            QListWidget { font-size: 15px; }
            QComboBox { font-size: 15px; padding: 4px; }
        """)

    def load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_config(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def init_ui(self):
        main = QVBoxLayout()

        body = QHBoxLayout()

        # 左侧
        left = QVBoxLayout()

        self.file_label = QLabel("未选择底表")
        self.file_label.setMinimumHeight(50)
        self.file_label.setAcceptDrops(True)

        btn_file = QPushButton("选择底表 Excel（支持拖入）")
        btn_file.clicked.connect(self.select_file)

        self.save_label = QLabel(
            "保存目录: " + self.config.get("save_dir", "未设置")
        )
        btn_save = QPushButton("选择保存目录")
        btn_save.clicked.connect(self.select_save_dir)

        self.date_box = QComboBox()
        self.date_box.currentTextChanged.connect(self.change_date)
        self.task_list = QListWidget()

        left.addWidget(btn_file)
        left.addWidget(self.file_label)
        left.addWidget(btn_save)
        left.addWidget(self.save_label)
        left.addWidget(QLabel("选择日期"))
        left.addWidget(self.date_box)
        left.addWidget(QLabel("任务"))
        left.addWidget(self.task_list)

        left_group = QGroupBox("数据筛选")
        left_group.setLayout(left)

        # 右侧字段
        right = QVBoxLayout()
        self.selected_fields = QListWidget()
        self.unselected_fields = QListWidget()

        self.selected_fields.itemClicked.connect(
            lambda i: self.move_field(i, self.selected_fields, self.unselected_fields)
        )
        self.unselected_fields.itemClicked.connect(
            lambda i: self.move_field(i, self.unselected_fields, self.selected_fields)
        )

        right.addWidget(QLabel("已选择字段（点击移除）"))
        right.addWidget(self.selected_fields)
        right.addWidget(QLabel("未选择字段（点击添加）"))
        right.addWidget(self.unselected_fields)

        right_group = QGroupBox("输出字段")
        right_group.setLayout(right)

        body.addWidget(left_group, 1)
        body.addWidget(right_group, 1)
        main.addLayout(body)

        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.status = QLabel("等待操作")
        btn_start = QPushButton("开始生成")
        btn_start.clicked.connect(self.start_convert)
        btn_open = QPushButton("打开生成目录")
        btn_open.clicked.connect(self.open_output)

        bottom.addWidget(self.progress)
        bottom.addWidget(self.status)
        bottom.addWidget(btn_start)
        bottom.addWidget(btn_open)

        main.addLayout(bottom)
        self.setLayout(main)

    def move_field(self, item, source, target):
        source.takeItem(source.row(item))
        target.addItem(item.text())

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择Excel", filter="Excel (*.xlsx *.xls)")
        if not path:
            return
        try:
            header = self.find_header(path)
            df = pd.read_excel(path, header=header, keep_default_na=False)
            df.columns = [str(c).strip() for c in df.columns]
            self.file_path = path
            self.file_label.setText(path)

            dates = sorted(df["日期"].astype(str).unique(), reverse=True)
            self.date_box.clear()
            self.date_box.addItems(dates)
            self.date_value = dates[0] if dates else ""

            self.task_list.clear()
            # 保留所有任务，包括 #N/A 等特殊值，并增加单独复制按钮
            for t in sorted(df["任务"].astype(str).unique()):
                self.add_task_item(t)

            self.init_fields(list(df.columns))

        except Exception as e:
            QMessageBox.warning(self, "错误", str(e))

    def add_task_item(self, task_name):
        item = QListWidgetItem()
        item.setSizeHint(self.task_row_size())
        item.setCheckState(Qt.CheckState.Checked)
        item.setData(Qt.ItemDataRole.UserRole, task_name)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(5, 2, 5, 2)

        label = QLabel(task_name)
        copy_btn = QPushButton("📋")
        copy_btn.setFixedWidth(40)
        copy_btn.setToolTip("复制任务名称")
        copy_btn.clicked.connect(lambda: self.copy_task_name(task_name))

        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(copy_btn)

        self.task_list.addItem(item)
        self.task_list.setItemWidget(item, row)

    def task_row_size(self):
        from PyQt6.QtCore import QSize
        return QSize(200, 35)

    def copy_task_name(self, text):
        QApplication.clipboard().setText(text)
        self.status.setText(f"已复制：{text}")

    def change_date(self, value):
        self.date_value = value

    def init_fields(self, columns):
        self.selected_fields.clear()
        self.unselected_fields.clear()
        for f in columns:
            if f in DEFAULT_FIELDS:
                self.selected_fields.addItem(f)
            else:
                self.unselected_fields.addItem(f)

    def find_header(self, path):
        preview = pd.read_excel(path, header=None, nrows=20, keep_default_na=False)
        for i, row in preview.iterrows():
            values = [str(x).strip() for x in row.tolist()]
            if "日期" in values and "任务" in values and "账号id" in values:
                return i
        raise Exception("无法识别表头")

    def select_save_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if path:
            self.config["save_dir"] = path
            self.save_config()
            self.save_label.setText("保存目录: " + path)

    def start_convert(self):
        if not self.file_path:
            QMessageBox.warning(self, "提示", "请先选择底表")
            return
        save = self.config.get("save_dir")
        if not save:
            QMessageBox.warning(self, "提示", "请选择保存目录")
            return

        tasks = [
            self.task_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.task_list.count())
            if self.task_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        fields = [self.selected_fields.item(i).text() for i in range(self.selected_fields.count())]

        self.worker = DataConvertWorker(self.file_path, save, getattr(self, "date_value", ""), tasks, fields)
        self.worker.progress.connect(lambda p,t: (self.progress.setValue(p), self.status.setText(t)))
        self.worker.finished_signal.connect(self.done)
        self.worker.error_signal.connect(lambda x: QMessageBox.warning(self,"错误",x))
        self.worker.start()

    def done(self, path):
        self.last_output = path
        QMessageBox.information(self,"完成",f"生成完成:\n{path}")

    def open_output(self):
        if self.last_output and os.path.exists(self.last_output):
            os.startfile(self.last_output) if os.name == "nt" else os.system(f'open "{self.last_output}"')
        else:
            QMessageBox.information(self,"提示","暂无生成目录")
