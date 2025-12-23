import sys
import os
import time
import random
import string
import mimetypes
import requests
import pandas as pd
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QLineEdit, QFileDialog, QComboBox, 
                             QSlider, QProgressBar, QTextEdit, QGroupBox, 
                             QRadioButton, QMessageBox, QCheckBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# --- 核心下载逻辑线程 ---
class DownloadWorker(QThread):
    log_signal = pyqtSignal(str)        
    progress_signal = pyqtSignal(int)   
    finished_signal = pyqtSignal(dict)  

    def __init__(self, tasks, base_save_dir, max_workers, retry_count=3, prevent_dupe=True, 
                 folder_rule=None):
        """
        folder_rule: dict or None
          {
            "use_folder": True,
            "col_value": "1920x1080_tab3...",
            "delimiter": "_" (如果设为 None 则使用全部内容)
          }
        """
        super().__init__()
        self.tasks = tasks 
        self.base_save_dir = base_save_dir
        self.max_workers = max_workers
        self.retry_count = retry_count
        self.prevent_dupe = prevent_dupe
        self.folder_rule = folder_rule
        
        self.is_running = True # 控制停止的标志位
        self.total_tasks = len(tasks)
        self.completed_count = 0
        self.failed_tasks = []

    def stop(self):
        """外部调用此方法来停止下载"""
        self.is_running = False
        self.log_signal.emit("🛑 正在尝试停止所有任务...")

    def run(self):
        self.log_signal.emit(f"🚀 开始任务，共 {self.total_tasks} 个文件，线程数: {self.max_workers}")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {executor.submit(self.download_single, task): task for task in self.tasks}
            
            for future in as_completed(future_to_task):
                # 1. 级检查：如果用户点了停止，就不再处理结果，直接退出循环
                if not self.is_running:
                    self.log_signal.emit("🚫 任务队列已终止。")
                    break 
                
                task = future_to_task[future]
                try:
                    success, msg = future.result()
                    if success:
                        self.log_signal.emit(f"✅ 成功: {msg}")
                    else:
                        if "已停止" in msg: # 如果是手动停止的反馈
                            self.log_signal.emit(f"⏹️ {msg}")
                        else:
                            self.log_signal.emit(f"❌ 失败: {msg}")
                            self.failed_tasks.append(f"{task.get('name', '未知')}: {msg}")
                except Exception as e:
                    self.log_signal.emit(f"💥 异常: {str(e)}")
                    self.failed_tasks.append(f"{task.get('url')}: {str(e)}")
                
                self.completed_count += 1
                progress = int((self.completed_count / self.total_tasks) * 100)
                self.progress_signal.emit(progress)

        self.finished_signal.emit({
            "total": self.total_tasks,
            "failed": self.failed_tasks,
            "stopped": not self.is_running
        })

    def get_target_directory(self, task):
        """计算文件应该存放在哪个文件夹"""
        # 默认放在根目录
        target_dir = self.base_save_dir
        
        # 如果启用了自动归档
        if self.folder_rule and self.folder_rule.get('use_folder'):
            raw_folder_str = str(task.get('folder_key', '')).strip()
            
            if raw_folder_str and raw_folder_str.lower() != 'nan':
                folder_name = raw_folder_str
                delimiter = self.folder_rule.get('delimiter')
                
                # 智能分割逻辑：比如 1920x1080_tab3，分隔符是 _，取第一部分
                if delimiter and delimiter in folder_name:
                    folder_name = folder_name.split(delimiter)[0]
                
                # 清理文件夹名中的非法字符
                valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
                folder_name = ''.join(c for c in folder_name if c in valid_chars).strip()
                
                if folder_name:
                    target_dir = os.path.join(self.base_save_dir, folder_name)
                    # 自动创建文件夹
                    try:
                        os.makedirs(target_dir, exist_ok=True)
                    except:
                        pass # 创建失败回退到根目录

        return target_dir

    def download_single(self, task):
        # 2. 线程级检查：在开始每个任务前检查是否停止
        if not self.is_running:
            return False, "用户已停止任务"

        url = task['url']
        custom_name = task.get('name')
        
        # 获取应该保存的目录（可能是子文件夹）
        save_dir = self.get_target_directory(task)

        if not url or not isinstance(url, str) or not url.startswith('http'):
            return False, f"无效链接: {url}"

        headers = { 'User-Agent': 'Mozilla/5.0' }

        last_error = ""
        for attempt in range(1, self.retry_count + 1):
            if not self.is_running: return False, "用户已停止任务"
            
            try:
                with requests.get(url, headers=headers, stream=True, timeout=15) as response:
                    response.raise_for_status()
                    
                    # 探测后缀
                    content_type = response.headers.get('content-type', '')
                    ext = mimetypes.guess_extension(content_type)
                    if not ext:
                        path = urlparse(url).path
                        ext = os.path.splitext(path)[1]
                    if not ext: ext = ".bin"

                    # 确定文件名
                    if custom_name:
                        valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
                        clean_name = ''.join(c for c in str(custom_name) if c in valid_chars)
                        filename = clean_name
                    else:
                        filename = os.path.basename(urlparse(url).path)
                        if not filename: filename = f"file_{int(time.time())}"

                    if not filename.endswith(ext): filename += ext

                    # 防重名
                    final_path = os.path.join(save_dir, filename)
                    if os.path.exists(final_path) and self.prevent_dupe:
                        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
                        name_part, ext_part = os.path.splitext(filename)
                        final_path = os.path.join(save_dir, f"{name_part}_{random_str}{ext_part}")

                    # 写入文件
                    with open(final_path, 'wb') as f:
                        # chunk_size=8192
                        for chunk in response.iter_content(chunk_size=8192):
                            # 3. 流级检查：每写入8KB检查一次，确保能秒停大文件
                            if not self.is_running:
                                f.close()
                                os.remove(final_path) # 删除下载了一半的残废文件
                                return False, "下载中途被用户停止"
                            
                            f.write(chunk)
                    
                    # 返回相对路径方便查看
                    rel_path = os.path.relpath(final_path, self.base_save_dir)
                    return True, f"{rel_path}"

            except Exception as e:
                last_error = str(e)
                if attempt < self.retry_count and self.is_running:
                    time.sleep(1)
                    continue
        
        return False, f"失败: {last_error}"


# --- 主界面 ---
class DownloaderApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("全能批量下载器 (Pro版)")
        self.resize(950, 800)
        
        self.excel_df = None
        self.save_path = os.getcwd()
        self.worker = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 1. 模式选择
        mode_group = QGroupBox("1. 基础配置")
        mode_layout = QHBoxLayout()
        self.rb_single = QRadioButton("单链接下载")
        self.rb_batch = QRadioButton("Excel 批量下载")
        self.rb_single.setChecked(True)
        self.rb_single.toggled.connect(self.switch_mode)
        self.rb_batch.toggled.connect(self.switch_mode)
        mode_layout.addWidget(self.rb_single)
        mode_layout.addWidget(self.rb_batch)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)

        # 2. 单链接区
        self.single_input_widget = QWidget()
        single_layout = QHBoxLayout()
        self.line_url = QLineEdit()
        self.line_url.setPlaceholderText("在此输入链接...")
        single_layout.addWidget(QLabel("下载链接:"))
        single_layout.addWidget(self.line_url)
        self.single_input_widget.setLayout(single_layout)
        layout.addWidget(self.single_input_widget)

        # 3. Excel 批量区
        self.batch_input_widget = QWidget()
        self.batch_input_widget.hide()
        batch_layout = QVBoxLayout()
        
        # 文件加载
        file_row = QHBoxLayout()
        self.btn_load_excel = QPushButton("📂 加载 Excel")
        self.btn_load_excel.clicked.connect(self.load_excel)
        self.lbl_excel_path = QLabel("未选择")
        file_row.addWidget(self.btn_load_excel)
        file_row.addWidget(self.lbl_excel_path)
        batch_layout.addLayout(file_row)
        
        # 列映射
        col_row = QHBoxLayout()
        col_row.addWidget(QLabel("🔗 链接列:"))
        self.combo_url_col = QComboBox()
        col_row.addWidget(self.combo_url_col)
        col_row.addSpacing(10)
        col_row.addWidget(QLabel("📝 文件名列(可选):"))
        self.combo_name_col = QComboBox()
        col_row.addWidget(self.combo_name_col)
        batch_layout.addLayout(col_row)

        # === 新增：自动分类设置 ===
        folder_group = QGroupBox("📂 自动归档/分类规则 (可选)")
        folder_group.setStyleSheet("QGroupBox { border: 1px solid #aaa; margin-top: 10px; }")
        folder_layout = QHBoxLayout()
        
        self.chk_auto_folder = QCheckBox("启用自动分类")
        self.chk_auto_folder.setToolTip("开启后，将根据Excel某一列的内容自动创建子文件夹")
        self.chk_auto_folder.toggled.connect(self.toggle_folder_ui)
        
        self.lbl_folder_col = QLabel("分类依据列:")
        self.combo_folder_col = QComboBox()
        self.combo_folder_col.setEnabled(False)
        
        self.lbl_delimiter = QLabel("分割规则:")
        self.combo_delimiter = QComboBox()
        self.combo_delimiter.addItems(["无 (使用整列内容)", "_ (下划线)", "- (横杠)", "空格", "| (竖线)"])
        self.combo_delimiter.setEnabled(False)
        self.combo_delimiter.setToolTip("例如：原内容为 '1920x1080_描述'，选择下划线规则后，文件夹名为 '1920x1080'")

        folder_layout.addWidget(self.chk_auto_folder)
        folder_layout.addSpacing(20)
        folder_layout.addWidget(self.lbl_folder_col)
        folder_layout.addWidget(self.combo_folder_col)
        folder_layout.addSpacing(20)
        folder_layout.addWidget(self.lbl_delimiter)
        folder_layout.addWidget(self.combo_delimiter)
        folder_group.setLayout(folder_layout)
        
        batch_layout.addWidget(folder_group)
        
        self.batch_input_widget.setLayout(batch_layout)
        layout.addWidget(self.batch_input_widget)

        # 4. 设置区
        settings_group = QGroupBox("2. 下载参数")
        set_layout = QHBoxLayout()
        
        self.btn_save_dir = QPushButton("📂 保存位置")
        self.btn_save_dir.clicked.connect(self.choose_save_dir)
        self.lbl_save_dir = QLabel(self.save_path)
        
        set_layout.addWidget(self.btn_save_dir)
        set_layout.addWidget(self.lbl_save_dir)
        set_layout.addStretch()
        
        set_layout.addWidget(QLabel("线程:"))
        self.slider_thread = QSlider(Qt.Orientation.Horizontal)
        self.slider_thread.setRange(1, 16)
        self.slider_thread.setValue(4)
        self.slider_thread.setFixedWidth(100)
        self.lbl_thread_val = QLabel("4")
        self.slider_thread.valueChanged.connect(lambda v: self.lbl_thread_val.setText(str(v)))
        set_layout.addWidget(self.slider_thread)
        set_layout.addWidget(self.lbl_thread_val)
        
        set_layout.addSpacing(20)
        self.chk_random = QCheckBox("防重名")
        self.chk_random.setChecked(True)
        set_layout.addWidget(self.chk_random)
        
        settings_group.setLayout(set_layout)
        layout.addWidget(settings_group)

        # 5. 按钮区 (开始 & 停止)
        btn_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("🚀 开始下载")
        self.btn_start.setFixedHeight(45)
        self.btn_start.setStyleSheet("background-color: #0078d7; color: white; font-weight: bold; font-size: 14px;")
        self.btn_start.clicked.connect(self.start_download)
        
        self.btn_stop = QPushButton("🛑 立即停止")
        self.btn_stop.setFixedHeight(45)
        self.btn_stop.setStyleSheet("background-color: #d93025; color: white; font-weight: bold; font-size: 14px;")
        self.btn_stop.clicked.connect(self.stop_download)
        self.btn_stop.setEnabled(False) # 初始不可用

        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        layout.addLayout(btn_layout)

        # 6. 进度与日志
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #222; color: #0f0; font-family: Consolas;")
        layout.addWidget(self.log_text)

        self.setLayout(layout)

    # --- UI 交互逻辑 ---

    def switch_mode(self):
        if self.rb_single.isChecked():
            self.single_input_widget.show()
            self.batch_input_widget.hide()
        else:
            self.single_input_widget.hide()
            self.batch_input_widget.show()

    def toggle_folder_ui(self, checked):
        self.combo_folder_col.setEnabled(checked)
        self.combo_delimiter.setEnabled(checked)

    def choose_save_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存根目录")
        if d:
            self.save_path = d
            self.lbl_save_dir.setText(d)

    def load_excel(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "选择 Excel", "", "Excel Files (*.xlsx *.xls)")
        if file_name:
            try:
                self.lbl_excel_path.setText(os.path.basename(file_name))
                self.excel_df = pd.read_excel(file_name)
                columns = self.excel_df.columns.tolist()
                
                # 填充所有下拉框
                for combo in [self.combo_url_col, self.combo_name_col, self.combo_folder_col]:
                    combo.clear()
                    if combo == self.combo_name_col:
                        combo.addItem("如果不选则自动命名")
                    combo.addItems(columns)
                
                self.log(f"已加载 Excel，共 {len(self.excel_df)} 行数据")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"读取失败: {str(e)}")

    def start_download(self):
        tasks = []
        
        # 1. 收集任务
        if self.rb_single.isChecked():
            url = self.line_url.text().strip()
            if not url: return
            tasks.append({"url": url, "name": None, "folder_key": None})
        else:
            if self.excel_df is None:
                QMessageBox.warning(self, "提示", "请先加载 Excel")
                return
            
            url_col = self.combo_url_col.currentText()
            name_col = self.combo_name_col.currentText()
            
            # 获取分类列
            use_folder = self.chk_auto_folder.isChecked()
            folder_col = self.combo_folder_col.currentText() if use_folder else None
            
            for index, row in self.excel_df.iterrows():
                u = str(row[url_col]).strip()
                if u and u.lower() != 'nan':
                    n = str(row[name_col]).strip() if name_col != "如果不选则自动命名" else None
                    # 获取分类的原始文本 (比如 "1920x1080_tab3")
                    f_key = str(row[folder_col]).strip() if use_folder else None
                    
                    tasks.append({
                        "url": u, 
                        "name": n,
                        "folder_key": f_key
                    })

        if not tasks: return

        # 2. 获取分类规则
        folder_rule = None
        if self.chk_auto_folder.isChecked():
            delimiter_map = {
                "无 (使用整列内容)": None,
                "_ (下划线)": "_",
                "- (横杠)": "-",
                "空格": " ",
                "| (竖线)": "|"
            }
            sel_del = self.combo_delimiter.currentText()
            folder_rule = {
                "use_folder": True,
                "delimiter": delimiter_map.get(sel_del)
            }

        # 3. UI 状态切换
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True) # 启用停止按钮
        self.progress_bar.setValue(0)
        self.log_text.clear()
        
        # 4. 启动线程
        self.worker = DownloadWorker(
            tasks, self.save_path, self.slider_thread.value(), 
            prevent_dupe=self.chk_random.isChecked(),
            folder_rule=folder_rule
        )
        self.worker.log_signal.connect(self.log)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def stop_download(self):
        if self.worker and self.worker.isRunning():
            self.btn_stop.setEnabled(False)
            self.btn_stop.setText("正在停止...")
            self.worker.stop() # 发送停止信号

    def log(self, msg):
        self.log_text.append(msg)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def update_progress(self, val):
        self.progress_bar.setValue(val)

    def on_finished(self, report):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("🛑 立即停止")
        
        if report.get('stopped'):
            self.log("⚠️ 任务已被用户强制停止。")
            QMessageBox.information(self, "已停止", "下载任务已停止。部分文件可能已下载完成。")
        else:
            failed = report.get('failed', [])
            if failed:
                QMessageBox.warning(self, "完成但有错误", f"失败 {len(failed)} 个，详见日志")
            else:
                QMessageBox.information(self, "成功", "全部下载完成！")

if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    win = DownloaderApp()
    win.show()
    sys.exit(app.exec())