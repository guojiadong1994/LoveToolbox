import sys
import os
import time
import hashlib
import requests
import pandas as pd
import mimetypes
import shutil
import cv2
import re
import json
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QLineEdit, QFileDialog, QComboBox,
                             QProgressBar, QTextEdit, QGroupBox, QMessageBox,
                             QListWidget, QListWidgetItem, QAbstractItemView,
                             QTreeWidget, QTreeWidgetItem, QSplitter, QCheckBox,
                             QSpinBox, QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QApplication)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer, QSettings
from PyQt6.QtGui import QFont, QColor, QAction, QIcon, QDragEnterEvent, QDropEvent

# 防止 OpenCV 多线程与 ThreadPool 冲突
cv2.setNumThreads(0)


# === 0. 错误报告详情弹窗 ===
class ErrorReportDialog(QDialog):
    def __init__(self, failed_tasks, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚠️ 下载失败任务详情")
        self.resize(1100, 600)
        self.failed_tasks = failed_tasks

        layout = QVBoxLayout()
        lbl = QLabel(f"共 {len(failed_tasks)} 个文件失败。请导出清单，根据【行号】回溯检查。")
        lbl.setStyleSheet("color: red; font-weight: bold; font-size: 14px;")
        layout.addWidget(lbl)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Excel行号", "Sheet名称", "Hook ID", "文件名", "下载链接", "错误原因"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 80);
        self.table.setColumnWidth(1, 100);
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 200);
        self.table.setColumnWidth(4, 300);
        self.table.setColumnWidth(5, 200)
        layout.addWidget(self.table)

        self.table.setRowCount(len(failed_tasks))
        for i, task in enumerate(failed_tasks):
            self.table.setItem(i, 0, QTableWidgetItem(str(task.get('row_num', '-'))))
            self.table.setItem(i, 1, QTableWidgetItem(str(task.get('sheet', ''))))
            self.table.setItem(i, 2, QTableWidgetItem(str(task.get('hook', ''))))
            self.table.setItem(i, 3, QTableWidgetItem(str(task.get('name', ''))))
            self.table.setItem(i, 4, QTableWidgetItem(str(task.get('url', ''))))
            err_item = QTableWidgetItem(str(task.get('error', '未知')))
            err_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(i, 5, err_item)

        hbox = QHBoxLayout()
        btn_export = QPushButton("📉 导出失败清单 (含行号)")
        btn_export.setStyleSheet("background-color: #2196f3; color: white; font-weight: bold;")
        btn_export.clicked.connect(self.export_excel)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        hbox.addWidget(btn_export);
        hbox.addStretch();
        hbox.addWidget(btn_close)
        layout.addLayout(hbox)
        self.setLayout(layout)

    def export_excel(self):
        if not self.failed_tasks: return
        default_name = f"下载失败清单_{int(time.time())}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "保存失败清单", default_name, "Excel Files (*.xlsx)")
        if path:
            try:
                df = pd.DataFrame(self.failed_tasks)
                cols_map = {'row_num': '原始行号', 'sheet': 'Sheet名', 'hook': 'Hook ID', 'name': '文件名',
                            'url': '下载链接', 'error': '错误原因'}
                available_cols = [c for c in cols_map.keys() if c in df.columns]
                df = df[available_cols]
                df.rename(columns=cols_map, inplace=True)
                df.to_excel(path, index=False)
                QMessageBox.information(self, "成功", f"清单已保存：\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")


# === 1. 核心下载线程 ===
class DownloadWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    file_progress_signal = pyqtSignal(str, int, int)
    finished_signal = pyqtSignal(dict)

    def __init__(self, tasks, save_root, max_workers, only_missing=False):
        super().__init__()
        self.tasks = tasks
        self.save_root = save_root
        self.max_workers = max_workers
        self.only_missing = only_missing
        self.is_running = True

    def stop(self):
        self.is_running = False

    def get_url_hash(self, url):
        if not isinstance(url, str): return "no_hash"
        return hashlib.md5(url.encode('utf-8')).hexdigest()[:8]

    def clean_filename(self, filename):
        s = str(filename)
        if s.lower() == 'nan' or not s.strip(): return "未命名"
        cleaned = re.sub(r'[\\/:*?"<>|]', '_', s)
        cleaned = cleaned.replace('\n', '').replace('\r', '').strip()

        # 强制截断文件名，防止 Windows 路径溢出
        if len(cleaned) > 80:
            cleaned = cleaned[:80] + "..."

        return cleaned if cleaned else "未命名"

    def get_resolution_folder(self, file_path, file_type):
        try:
            w, h = 0, 0
            if file_type == 'IMAGE':
                with Image.open(file_path) as img:
                    w, h = img.size
            elif file_type == 'VIDEO':
                cap = cv2.VideoCapture(file_path)
                if cap.isOpened():
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap.release()
            if w > 0 and h > 0: return f"{w}x{h}"
            return "未知尺寸"
        except:
            return "未知尺寸"

    def check_if_exists(self, sheet, hook, url_hash):
        target_base = os.path.join(self.save_root, sheet, hook)
        if not os.path.exists(target_base): return False
        for root, dirs, files in os.walk(target_base):
            for f in files:
                if f.startswith(url_hash + "_"): return True
        return False

    def download_single(self, task):
        if not self.is_running: return False, "用户停止"
        url = task['url'];
        sheet = task['sheet'];
        hook = str(task['hook']).strip()
        raw_name = task['name']

        if pd.isna(url) or not str(url).startswith('http'): return False, "无效链接"
        url_hash = self.get_url_hash(url)
        clean_name = self.clean_filename(raw_name)

        if self.only_missing:
            if self.check_if_exists(sheet, hook, url_hash): return True, "已存在(跳过)"

        temp_dir = os.path.join(self.save_root, "_temp_downloading")
        if not os.path.exists(temp_dir): os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, f"temp_{url_hash}_{int(time.time() * 1000)}")

        success = False;
        ext = ".bin";
        file_type = "OTHER"

        for _ in range(3):
            if not self.is_running: return False, "用户停止"
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                with requests.get(url, headers=headers, stream=True, timeout=40) as r:
                    r.raise_for_status()
                    total_length = int(r.headers.get('content-length', 0))
                    ct = r.headers.get('content-type', '')
                    ge = mimetypes.guess_extension(ct)
                    if ge: ext = ge
                    if ext == ".bin" and '.' in url:
                        ue = '.' + url.split('.')[-1].split('?')[0]
                        if len(ue) < 10: ext = ue
                    if 'image' in ct or ext.lower() in ['.jpg', '.png', '.jpeg', '.webp']:
                        file_type = "IMAGE"
                    elif 'video' in ct or ext.lower() in ['.mp4', '.mov', '.avi', '.mkv']:
                        file_type = "VIDEO"

                    downloaded = 0
                    with open(temp_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if not self.is_running:
                                f.close();
                                if os.path.exists(temp_path): os.remove(temp_path)
                                return False, "用户停止"
                            f.write(chunk)
                            downloaded += len(chunk)
                            self.file_progress_signal.emit(clean_name, downloaded, total_length)
                    success = True;
                    break
            except:
                time.sleep(1.5)

        if not success:
            if os.path.exists(temp_path): os.remove(temp_path)
            return False, "下载失败(3次重试)"

        # 0KB / 伪装网页检测
        if os.path.exists(temp_path):
            size = os.path.getsize(temp_path)
            if size == 0:
                os.remove(temp_path)
                return False, "文件为空(0KB)"
            if size < 10 * 1024:
                try:
                    with open(temp_path, 'rb') as f:
                        header = f.read(50).lower()
                        if b'<html' in header or b'<!doctype' in header or b'<body' in header or b'{' in header:
                            f.close();
                            os.remove(temp_path)
                            return False, "链接失效(下载内容为网页或JSON)"
                except:
                    pass

        try:
            res_folder = self.get_resolution_folder(temp_path, file_type)
            final_dir = os.path.join(self.save_root, sheet, hook, file_type, res_folder)
            if not os.path.exists(final_dir): os.makedirs(final_dir)
            final_name = f"{url_hash}_{clean_name}{ext}"
            final_path = os.path.join(final_dir, final_name)
            if os.path.exists(final_path): os.remove(final_path)
            shutil.move(temp_path, final_path)
            self.file_progress_signal.emit(clean_name, 100, 100)
            return True, "成功"
        except Exception as e:
            if os.path.exists(temp_path): os.remove(temp_path)
            return False, f"归档错误:{e}"

    def run(self):
        total = len(self.tasks)
        completed = 0;
        failed_list = [];
        skipped_count = 0
        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_task = {executor.submit(self.download_single, t): t for t in self.tasks}
                for future in as_completed(future_to_task):
                    if not self.is_running: break
                    task = future_to_task[future]
                    try:
                        is_ok, msg = future.result()
                        if is_ok:
                            if "已存在" in msg:
                                skipped_count += 1
                            else:
                                self.log_signal.emit(f"✅ {task['name']}")
                        else:
                            self.log_signal.emit(f"❌ {task['name']}: {msg}")
                            task['error'] = msg
                            failed_list.append(task)
                    except Exception as e:
                        self.log_signal.emit(f"❌ 系统异常: {str(e)}")
                        task['error'] = str(e)
                        failed_list.append(task)
                    completed += 1
                    self.progress_signal.emit(int(completed / total * 100))
        except Exception as e:
            self.log_signal.emit(f"⚠️ 线程池异常: {e}")
        finally:
            if skipped_count > 0: self.log_signal.emit(f"⏭️ 智能跳过了 {skipped_count} 个已存在的文件")
            self.finished_signal.emit({"failed": failed_list, "skipped": skipped_count})


# === 主窗口 ===
class DownloaderApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("全能素材归档下载器")
        self.resize(1300, 950)
        self.setAcceptDrops(True)

        self.df_dict = {}
        self.worker = None
        self.is_loading_hooks = False
        self.active_downloads = {}

        self.settings = QSettings("LoveToolbox", "Downloader")

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        main = QVBoxLayout()
        main.setContentsMargins(10, 10, 10, 10);
        main.setSpacing(5)

        font = QFont();
        font.setPointSize(12)
        if sys.platform == 'win32': font.setFamily("Microsoft YaHei")

        header = QLabel("📖 流程：1.拖拽入表格 ➔ 2.选Sheet ➔ 3.设置列 ➔ 4.双栏选Hook ➔ 5.下载 (每次需手动选路径)")
        header.setStyleSheet(
            "background-color: #f5f5f5; color: #333; padding: 4px; border: 1px solid #ddd; border-radius: 4px; font-size: 12px;")
        header.setFixedHeight(30);
        header.setAlignment(Qt.AlignmentFlag.AlignCenter);
        main.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget();
        ll = QVBoxLayout(left);
        ll.setContentsMargins(0, 0, 0, 0)
        self.g1 = QGroupBox("Step 1: 导入表格 (支持拖拽)");
        self.g1.setMaximumHeight(80);
        l1 = QVBoxLayout(self.g1);
        l1.setContentsMargins(5, 5, 5, 5);
        h1 = QHBoxLayout()
        self.btn_load = QPushButton("📂 选择文件");
        self.btn_load.setStyleSheet("background-color: #ff9800; color: white; font-weight: bold;")
        self.btn_load.clicked.connect(self.select_file_dialog);
        self.lbl_file = QLabel("未选择 (或直接拖入文件)");
        h1.addWidget(self.btn_load);
        h1.addWidget(self.lbl_file);
        l1.addLayout(h1);
        ll.addWidget(self.g1)

        self.g2 = QGroupBox("Step 2: 选择 Sheet");
        l2 = QVBoxLayout(self.g2);
        l2.setContentsMargins(5, 5, 5, 5)
        h_sheet_tools = QHBoxLayout()
        self.search_sheet = QLineEdit();
        self.search_sheet.setPlaceholderText("🔍 搜索...");
        self.search_sheet.setClearButtonEnabled(True);
        self.search_sheet.textChanged.connect(self.filter_sheets)
        btn_sheet_all = QPushButton("全选");
        btn_sheet_all.clicked.connect(lambda: self.batch_check_sheets(True))
        btn_sheet_none = QPushButton("全不选");
        btn_sheet_none.clicked.connect(lambda: self.batch_check_sheets(False))
        h_sheet_tools.addWidget(self.search_sheet);
        h_sheet_tools.addWidget(btn_sheet_all);
        h_sheet_tools.addWidget(btn_sheet_none)
        self.list_sheets = QListWidget();
        self.list_sheets.itemChanged.connect(self.on_sheet_changed)
        l2.addLayout(h_sheet_tools);
        l2.addWidget(self.list_sheets);
        ll.addWidget(self.g2, 1)

        self.g3 = QGroupBox("Step 3: 设置列");
        self.g3.setMaximumHeight(120);
        l3 = QVBoxLayout(self.g3);
        l3.setContentsMargins(5, 5, 5, 5)
        h_hook = QHBoxLayout();
        h_hook.addWidget(QLabel("🪝 Hook:"));
        self.combo_hook = QComboBox();
        self.combo_hook.currentIndexChanged.connect(self.refresh_hooks_and_stats);
        h_hook.addWidget(self.combo_hook);
        l3.addLayout(h_hook)
        h_url = QHBoxLayout();
        h_url.addWidget(QLabel("🔗 链接:"));
        self.combo_url = QComboBox();
        h_url.addWidget(self.combo_url);
        l3.addLayout(h_url)
        h_name = QHBoxLayout();
        h_name.addWidget(QLabel("📝 名字:"));
        self.combo_name = QComboBox();
        h_name.addWidget(self.combo_name);
        l3.addLayout(h_name)
        ll.addWidget(self.g3);
        splitter.addWidget(left)

        right = QWidget();
        rl = QVBoxLayout(right);
        rl.setContentsMargins(0, 0, 0, 0)
        self.g4 = QGroupBox("Step 4: 筛选 Hook");
        l4 = QHBoxLayout(self.g4);
        l4.setContentsMargins(5, 5, 5, 5)
        v_source = QVBoxLayout();
        self.search_hook = QLineEdit();
        self.search_hook.setPlaceholderText("🔍 待选...");
        self.search_hook.setClearButtonEnabled(True);
        self.search_hook.textChanged.connect(self.filter_hooks);
        v_source.addWidget(self.search_hook)
        h_tools = QHBoxLayout();
        self.btn_all = QPushButton("全选");
        self.btn_all.clicked.connect(lambda: self.batch_check_hooks(True));
        self.btn_none = QPushButton("全不选");
        self.btn_none.clicked.connect(lambda: self.batch_check_hooks(False))
        h_tools.addWidget(self.btn_all);
        h_tools.addWidget(self.btn_none);
        v_source.addLayout(h_tools)
        self.list_source = QListWidget();
        self.list_source.itemChanged.connect(self.on_source_item_changed);
        v_source.addWidget(self.list_source)
        v_target = QVBoxLayout();
        self.lbl_selected_count = QLabel("✅ 已选: 0");
        self.lbl_selected_count.setStyleSheet("font-weight: bold; color: green;");
        v_target.addWidget(self.lbl_selected_count)
        self.list_target = QListWidget();
        self.list_target.itemDoubleClicked.connect(self.on_target_double_click);
        v_target.addWidget(self.list_target)
        l4.addLayout(v_source, 1);
        l4.addWidget(QLabel("👉"));
        l4.addLayout(v_target, 1);
        rl.addWidget(self.g4, 2)

        self.g5 = QGroupBox("Step 5: 智能下载");
        self.g5.setMaximumHeight(150);
        l5 = QVBoxLayout(self.g5);
        l5.setContentsMargins(5, 5, 5, 5)
        hp = QHBoxLayout();
        self.input_path = QLineEdit();
        self.input_path.setPlaceholderText("请手动选择保存路径...");
        self.input_path.setReadOnly(True);
        self.btn_path = QPushButton("📂 浏览");
        self.btn_path.clicked.connect(self.choose_path);
        hp.addWidget(self.input_path);
        hp.addWidget(self.btn_path);
        l5.addLayout(hp)
        ht = QHBoxLayout();
        ht.addWidget(QLabel("线程数:"));
        self.spin_thread = QSpinBox();
        self.spin_thread.setRange(1, 16);
        self.spin_thread.setValue(4);
        ht.addWidget(self.spin_thread)
        ht.addSpacing(20);
        self.chk_overwrite = QCheckBox("强制覆盖已存在文件");
        ht.addWidget(self.chk_overwrite);
        ht.addStretch();
        self.lbl_stats = QLabel("📊 实时统计: 0 个任务");
        self.lbl_stats.setStyleSheet("font-weight: bold; color: #2e7d32; font-size: 13px;");
        ht.addWidget(self.lbl_stats);
        l5.addLayout(ht)
        hb = QHBoxLayout();
        self.btn_start = QPushButton("🚀 开始 / 继续");
        self.btn_start.setFixedHeight(40);
        self.btn_start.setStyleSheet("background-color: #2196f3; color: white; font-weight: bold;");
        self.btn_start.clicked.connect(self.start_download_smart)
        self.btn_retry = QPushButton("🔄 检查重试");
        self.btn_retry.setFixedHeight(40);
        self.btn_retry.setStyleSheet("background-color: #ff9800; color: white; font-weight: bold;");
        self.btn_retry.clicked.connect(lambda: self.run_download(only_missing=True))
        self.btn_stop = QPushButton("🛑 停止");
        self.btn_stop.setFixedHeight(40);
        self.btn_stop.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;");
        self.btn_stop.clicked.connect(self.stop_download);
        self.btn_stop.setEnabled(False);
        hb.addWidget(self.btn_start);
        hb.addWidget(self.btn_retry);
        hb.addWidget(self.btn_stop);
        l5.addLayout(hb);
        rl.addWidget(self.g5)
        splitter.addWidget(right);
        main.addWidget(splitter)

        self.pbar = QProgressBar();
        self.pbar.setValue(0);
        main.addWidget(self.pbar)
        lbl_monitor = QLabel("📡 实时传输监控台");
        lbl_monitor.setStyleSheet("font-weight: bold; margin-top: 5px;");
        main.addWidget(lbl_monitor)
        self.table_active = QTableWidget();
        self.table_active.setColumnCount(4);
        self.table_active.setHorizontalHeaderLabels(["文件名", "进度", "已下载", "总大小"])
        self.table_active.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_active.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed);
        self.table_active.setColumnWidth(1, 150)
        self.table_active.setMaximumHeight(150);
        main.addWidget(self.table_active)
        lbl_log = QLabel("📜 运行日志");
        lbl_log.setStyleSheet("font-weight: bold; margin-top: 5px;");
        main.addWidget(lbl_log)
        self.log_area = QTextEdit();
        self.log_area.setMinimumHeight(120);
        self.log_area.setReadOnly(True);
        main.addWidget(self.log_area)
        self.setLayout(main)

    def toggle_ui_state(self, enabled):
        self.g1.setEnabled(enabled);
        self.g2.setEnabled(enabled);
        self.g3.setEnabled(enabled);
        self.g4.setEnabled(enabled)
        self.btn_path.setEnabled(enabled);
        self.spin_thread.setEnabled(enabled);
        self.chk_overwrite.setEnabled(enabled)
        self.btn_start.setEnabled(enabled);
        self.btn_retry.setEnabled(enabled);
        self.btn_stop.setEnabled(not enabled)

    def format_size(self, size_bytes):
        limit_5mb = 5 * 1024 * 1024
        if size_bytes < limit_5mb:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

    def update_active_progress(self, filename, downloaded, total):
        if downloaded == 100 and total == 100:
            if filename in self.active_downloads:
                row = self.active_downloads[filename]
                self.table_active.removeRow(row)
                del self.active_downloads[filename]
                self.active_downloads = {}
                for r in range(self.table_active.rowCount()):
                    fname_item = self.table_active.item(r, 0)
                    if fname_item: self.active_downloads[fname_item.text()] = r
            return

        if filename not in self.active_downloads:
            row = self.table_active.rowCount();
            self.table_active.insertRow(row);
            self.active_downloads[filename] = row
            self.table_active.setItem(row, 0, QTableWidgetItem(filename))
            pbar = QProgressBar();
            pbar.setTextVisible(True);
            self.table_active.setCellWidget(row, 1, pbar)
            self.table_active.setItem(row, 2, QTableWidgetItem("0 KB"));
            self.table_active.setItem(row, 3, QTableWidgetItem("计算中..."))

        row = self.active_downloads[filename]
        if total > 0:
            pct = int((downloaded / total) * 100);
            pbar = self.table_active.cellWidget(row, 1)
            if pbar: pbar.setValue(pct)
            self.table_active.item(row, 2).setText(self.format_size(downloaded))
            self.table_active.item(row, 3).setText(self.format_size(total))

    def load_settings(self):
        self.spin_thread.setValue(self.settings.value("threads", 4, type=int))
        self.chk_overwrite.setChecked(False)  # 默认不覆盖

    def save_settings(self):
        self.settings.setValue("threads", self.spin_thread.value())

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for f in files:
            if f.lower().endswith(('.xlsx', '.xls', '.csv')): self.process_file(f); break

    def select_file_dialog(self):
        fname, _ = QFileDialog.getOpenFileName(self, "选择表格", "", "Excel/CSV (*.xlsx *.xls *.csv)")
        if fname: self.process_file(fname)

    def process_file(self, fname):
        self.lbl_file.setText(os.path.basename(fname));
        self.df_dict = {}
        try:
            if fname.endswith('.csv'):
                self.df_dict['CSV'] = pd.read_csv(fname)
            else:
                xls = pd.ExcelFile(fname)
                for s in xls.sheet_names: self.df_dict[s] = pd.read_excel(fname, sheet_name=s)
            self.list_sheets.clear()
            for s in self.df_dict:
                item = QListWidgetItem(s);
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable);
                item.setCheckState(Qt.CheckState.Checked);
                self.list_sheets.addItem(item)
            df0 = list(self.df_dict.values())[0];
            cols = [str(c) for c in df0.columns]
            self.combo_hook.clear();
            self.combo_hook.addItems(cols);
            self.combo_url.clear();
            self.combo_url.addItems(cols);
            self.combo_name.clear();
            self.combo_name.addItems(cols)
            for i, c in enumerate(cols):
                cl = c.lower()
                if 'hook' in cl: self.combo_hook.setCurrentIndex(i)
                if 'link' in cl or 'url' in cl: self.combo_url.setCurrentIndex(i)
                if 'name' in cl: self.combo_name.setCurrentIndex(i)
            self.refresh_hooks_and_stats()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取失败: {e}")

    def sort_list_widget(self, list_widget):
        list_widget.blockSignals(True)
        items = []
        for i in range(list_widget.count()): items.append(list_widget.takeItem(0))
        items.sort(key=lambda x: (x.checkState() != Qt.CheckState.Checked, x.text()))
        for it in items: list_widget.addItem(it)
        list_widget.blockSignals(False)

    def on_sheet_changed(self, item):
        # Sheet 列表不再自动排序
        filter_txt = self.search_sheet.text().lower()
        if filter_txt: self.filter_sheets(filter_txt)
        self.refresh_hooks_and_stats()

    def batch_check_sheets(self, check):
        self.list_sheets.blockSignals(True)
        for i in range(self.list_sheets.count()):
            it = self.list_sheets.item(i)
            if check:
                if not it.isHidden(): it.setCheckState(Qt.CheckState.Checked)
            else:
                it.setCheckState(Qt.CheckState.Unchecked)
        self.list_sheets.blockSignals(False)
        self.on_sheet_changed(None)

    def on_source_item_changed(self, item):
        self.sort_list_widget(self.list_source)  # Hook 列表依然自动置顶
        filter_txt = self.search_hook.text().lower()
        if filter_txt: self.filter_hooks(filter_txt)
        self.update_task_stats()

    def batch_check_hooks(self, check):
        self.list_source.blockSignals(True)
        for i in range(self.list_source.count()):
            it = self.list_source.item(i)
            if check:
                if not it.isHidden(): it.setCheckState(Qt.CheckState.Checked)
            else:
                it.setCheckState(Qt.CheckState.Unchecked)
        self.list_source.blockSignals(False)
        self.on_source_item_changed(None)

    def refresh_hooks_and_stats(self):
        if not self.df_dict: return
        self.is_loading_hooks = True
        col = self.combo_hook.currentText()
        if not col: return
        all_hooks = set()
        for i in range(self.list_sheets.count()):
            it = self.list_sheets.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                s = it.text()
                # 直接读取原始数据，不进行自动填充
                if s in self.df_dict and col in self.df_dict[s].columns:
                    all_hooks.update(self.df_dict[s][col].dropna().astype(str).unique())
        self.list_source.blockSignals(True);
        self.list_source.clear();
        filter_txt = self.search_hook.text().lower()
        for h in sorted(list(all_hooks)):
            it = QListWidgetItem(h);
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable);
            it.setCheckState(Qt.CheckState.Checked)
            if filter_txt and filter_txt not in h.lower(): it.setHidden(True)
            self.list_source.addItem(it)
        self.list_source.blockSignals(False);
        self.is_loading_hooks = False;
        self.update_task_stats()

    def on_target_double_click(self, item):
        hook_text = item.text();
        self.list_source.blockSignals(True)
        items = self.list_source.findItems(hook_text, Qt.MatchFlag.MatchExactly)
        if items: items[0].setCheckState(Qt.CheckState.Unchecked)
        self.list_source.blockSignals(False);
        self.on_source_item_changed(None)

    def update_task_stats(self):
        if self.is_loading_hooks or not self.df_dict: return
        sel_sheets = [self.list_sheets.item(i).text() for i in range(self.list_sheets.count()) if
                      self.list_sheets.item(i).checkState() == Qt.CheckState.Checked]
        sel_hooks = set();
        self.list_target.clear()
        for i in range(self.list_source.count()):
            it = self.list_source.item(i)
            if it.checkState() == Qt.CheckState.Checked: txt = it.text(); sel_hooks.add(txt); self.list_target.addItem(
                txt)
        self.lbl_selected_count.setText(f"✅ 已选: {len(sel_hooks)}")
        h_col = self.combo_hook.currentText();
        total = 0
        for s in sel_sheets:
            df = self.df_dict[s]
            if h_col in df.columns: total += df[h_col].astype(str).isin(sel_hooks).sum()
        self.lbl_stats.setText(f"📊 实时统计: 选中 {len(sel_sheets)} 个表, {len(sel_hooks)} 个Hook, 共 {total} 个文件")

    def filter_sheets(self, text):
        for i in range(self.list_sheets.count()): it = self.list_sheets.item(i); it.setHidden(
            text.lower() not in it.text().lower())

    def filter_hooks(self, text):
        for i in range(self.list_source.count()): it = self.list_source.item(i); it.setHidden(
            text.lower() not in it.text().lower())

    def choose_path(self):
        d = QFileDialog.getExistingDirectory(self, "保存目录");
        if d: self.input_path.setText(d)

    def start_download_smart(self):
        self.save_settings()
        is_overwrite = self.chk_overwrite.isChecked()
        self.run_download(only_missing=not is_overwrite)

    def run_download(self, only_missing):
        if not self.df_dict: return
        root = self.input_path.text()
        if not root: QMessageBox.warning(self, "提示", "请手动选择保存目录"); return
        c_hook = self.combo_hook.currentText();
        c_url = self.combo_url.currentText();
        c_name = self.combo_name.currentText()
        sel_hooks = set(self.list_source.item(i).text() for i in range(self.list_source.count()) if
                        self.list_source.item(i).checkState() == Qt.CheckState.Checked)
        tasks = []
        for i in range(self.list_sheets.count()):
            it = self.list_sheets.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                s = it.text();
                df = self.df_dict[s]
                for idx, row in df.iterrows():
                    h = str(row[c_hook]).strip()
                    if h in sel_hooks:
                        n = str(row[c_name]) if c_name and not pd.isna(row[c_name]) else "未命名"
                        tasks.append({
                            "sheet": s, "hook": h, "url": row[c_url], "name": n,
                            "row_num": idx + 2
                        })
        if not tasks: QMessageBox.warning(self, "提示", "没有任务"); return
        if self.worker is not None and self.worker.isRunning(): QMessageBox.warning(self, "提示",
                                                                                    "任务停止中..."); return

        self.toggle_ui_state(False)
        self.log_area.clear();
        self.log_area.append(f"🚀 开始任务: {len(tasks)}个")
        self.pbar.setValue(0)
        self.table_active.setRowCount(0);
        self.active_downloads = {}

        self.worker = DownloadWorker(tasks, root, self.spin_thread.value(), only_missing=only_missing)
        self.worker.log_signal.connect(self.log_area.append)
        self.worker.progress_signal.connect(self.pbar.setValue)
        self.worker.file_progress_signal.connect(self.update_active_progress)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def stop_download(self):
        if self.worker: self.worker.stop(); self.log_area.append("🛑 正在停止...")

    def on_finished(self, report):
        self.toggle_ui_state(True)
        self.pbar.setValue(100)
        self.table_active.setRowCount(0);
        self.active_downloads = {}

        failed = report['failed'];
        skipped = report.get('skipped', 0)
        msg = f"处理完成！\n跳过: {skipped}\n失败: {len(failed)}"
        QMessageBox.information(self, "下载完成", msg)

        if failed:
            ErrorReportDialog(failed, self).exec()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = DownloaderApp()
    win.show()
    sys.exit(app.exec())