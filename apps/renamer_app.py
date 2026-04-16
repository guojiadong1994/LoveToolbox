import sys
import os
import shutil
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QLineEdit, QFileDialog, QProgressBar, 
                             QTextEdit, QGroupBox, QMessageBox, QTableWidget, 
                             QTableWidgetItem, QHeaderView)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt, QThread, pyqtSignal

class RenamerWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str)

    def __init__(self, source_dir, target_dir, prefix_map):
        super().__init__()
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.prefix_map = prefix_map 
        # map结构: {'1080-1920': 'PrefixA', '1280-720': ''} 
        # 注意：空字符串 '' 现在是有效值，代表无前缀
        self.is_running = True

    def run(self):
        self.log_signal.emit(f"📂 源根目录: {self.source_dir}")
        self.log_signal.emit(f"📂 目标目录: {self.target_dir}")
        self.log_signal.emit("-" * 40)

        # 1. 统计工作量
        total_files = 0
        for root, dirs, files in os.walk(self.source_dir):
            folder_name = os.path.basename(root)
            # 只要这个文件夹在 map 的 key 里（说明用户勾选了），就算任务
            if folder_name in self.prefix_map:
                 valid = [f for f in files if not f.startswith('.') and f.lower() != 'thumbs.db']
                 total_files += len(valid)
        
        if total_files == 0:
            self.finished_signal.emit("没有文件需要重命名。请检查是否勾选了要处理的文件夹。")
            return

        processed_count = 0
        
        # 2. 开始正式遍历
        for root, dirs, files in os.walk(self.source_dir):
            if not self.is_running:
                break
            
            folder_name = os.path.basename(root)
            
            valid_files = [f for f in files if not f.startswith('.') and f.lower() != 'thumbs.db']
            if not valid_files:
                continue
            
            # 构建目标路径
            rel_path = os.path.relpath(root, self.source_dir)
            target_current_dir = os.path.join(self.target_dir, rel_path)
            
            if not os.path.exists(target_current_dir):
                os.makedirs(target_current_dir)

            # --- 关键修改点 ---
            # 检查该文件夹是否在任务列表中 (即用户是否勾选)
            if folder_name not in self.prefix_map:
                # 没勾选 -> 原样复制文件
                # self.log_signal.emit(f"⚠️ [{folder_name}] 未勾选，保持原名复制...")
                for f in valid_files:
                    try:
                        shutil.copy2(os.path.join(root, f), os.path.join(target_current_dir, f))
                    except: pass
                continue

            # 获取前缀 (可能是空字符串 "")
            user_prefix = self.prefix_map[folder_name]
            if user_prefix is None:
                user_prefix = ""

            # --- 执行重命名逻辑 ---
            valid_files.sort()
            
            # 显示日志：如果前缀为空，提示“纯数字命名”
            display_prefix = user_prefix if user_prefix else "[无前缀]"
            self.log_signal.emit(f"处理: {rel_path} -> 使用前缀 {display_prefix}")

            for index, file_name in enumerate(valid_files):
                if not self.is_running:
                    break

                src_file_path = os.path.join(root, file_name)
                _, ext = os.path.splitext(file_name)
                
                # --- 命名算法 (组号1.. + 序号0-9) ---
                group_id = (index // 10) + 1
                item_id = (index % 10)
                
                # 拼接: 前缀(可能是空) + 组号 + 序号 + 后缀
                new_file_name = f"{user_prefix}{group_id}{item_id}{ext}"
                
                dest_file_path = os.path.join(target_current_dir, new_file_name)
                
                try:
                    shutil.copy2(src_file_path, dest_file_path)
                except Exception as e:
                    self.log_signal.emit(f"  ❌ 错误: {str(e)}")

                processed_count += 1
                progress = int((processed_count / total_files) * 100)
                self.progress_signal.emit(progress)

        self.finished_signal.emit(f"✅ 全部完成！共处理 {processed_count} 个文件。")

    def stop(self):
        self.is_running = False


class RenamerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("多层级文件夹批量重命名工具 (修复版)")
        self.resize(950, 750)
        
        self.source_path = ""
        self.target_path = ""
        self.worker = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 1. 说明区域
        title = QLabel("📂 结构化文件夹递归重命名")
        title.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title)
        
        info = QLabel(
            "更新说明：\n"
            "1. 扫描后，请在表格左侧【勾选】你需要处理的文件夹。\n"
            "2. 右侧【前缀】可以留空。如果留空，文件将命名为 '10.jpg', '11.jpg' 等纯数字格式。\n"
            "3. 未勾选的文件夹将原样复制，不进行重命名。"
        )
        info.setStyleSheet("color: #333; background-color: #fff2cc; padding: 10px; border-radius: 5px; border: 1px solid #d6b656;")
        layout.addWidget(info)
        layout.addSpacing(10)

        # 2. 路径选择区域
        path_box = QGroupBox("第一步：路径设置")
        path_layout = QVBoxLayout()
        
        # 源
        src_layout = QHBoxLayout()
        self.btn_src = QPushButton("📂 1. 选择源文件夹 (Source)")
        self.btn_src.clicked.connect(self.select_source)
        self.lbl_src = QLabel("未选择")
        self.lbl_src.setStyleSheet("color: #d93025;")
        src_layout.addWidget(self.btn_src)
        src_layout.addWidget(self.lbl_src, 1)
        path_layout.addLayout(src_layout)
        
        # 扫描按钮
        self.btn_scan = QPushButton("🔍 2. 扫描文件夹结构")
        self.btn_scan.setStyleSheet("background-color: #f6b26b; color: black; font-weight: bold;")
        self.btn_scan.setFixedHeight(35)
        self.btn_scan.clicked.connect(self.scan_folders)
        self.btn_scan.setEnabled(False)
        path_layout.addWidget(self.btn_scan)
        
        # 目标
        dst_layout = QHBoxLayout()
        self.btn_dst = QPushButton("📂 3. 选择目标文件夹")
        self.btn_dst.clicked.connect(self.select_target)
        self.lbl_dst = QLabel("未选择")
        self.lbl_dst.setStyleSheet("color: #d93025;")
        dst_layout.addWidget(self.btn_dst)
        dst_layout.addWidget(self.lbl_dst, 1)
        path_layout.addLayout(dst_layout)
        
        path_box.setLayout(path_layout)
        layout.addWidget(path_box)

        # 3. 表格配置区域
        layout.addWidget(QLabel("第二步：配置规则 (勾选要处理的项，前缀可留空)"))
        
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["文件夹名称 (勾选以处理)", "前缀 (留空则为纯数字)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        # 4. 执行区域
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 开始复制并重命名")
        self.btn_start.setFixedHeight(50)
        self.btn_start.setStyleSheet("background-color: #0078d7; color: white; font-weight: bold; font-size: 15px;")
        self.btn_start.clicked.connect(self.start_process)
        
        self.btn_stop = QPushButton("🛑 停止")
        self.btn_stop.setFixedHeight(50)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_process)
        
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        layout.addLayout(btn_layout)

        # 5. 进度与日志
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setStyleSheet("background-color: #2b2b2b; color: #eee; font-family: Consolas;")
        layout.addWidget(self.log_text)

        self.setLayout(layout)

    def select_source(self):
        d = QFileDialog.getExistingDirectory(self, "选择源文件夹")
        if d:
            self.source_path = d
            self.lbl_src.setText(d)
            self.lbl_src.setStyleSheet("color: #188038;")
            self.btn_scan.setEnabled(True)
            self.log_text.append(f"已选中源: {d}\n请点击【扫描文件夹结构】...")

    def select_target(self):
        d = QFileDialog.getExistingDirectory(self, "选择目标文件夹")
        if d:
            self.target_path = d
            self.lbl_dst.setText(d)
            self.lbl_dst.setStyleSheet("color: #188038;")

    def scan_folders(self):
        if not self.source_path:
            return
        
        self.log_text.append("⏳ 正在深度扫描目录结构...")
        unique_folders = set()
        
        for root, dirs, files in os.walk(self.source_path):
            valid_files = [f for f in files if not f.startswith('.') and f.lower() != 'thumbs.db']
            if valid_files:
                folder_name = os.path.basename(root)
                unique_folders.add(folder_name)
        
        if not unique_folders:
            QMessageBox.information(self, "提示", "未找到包含文件的子文件夹。")
            return

        # 填充表格
        sorted_folders = sorted(list(unique_folders))
        self.table.setRowCount(len(sorted_folders))
        
        for i, name in enumerate(sorted_folders):
            # 第一列: 文件夹名 + 复选框
            item_name = QTableWidgetItem(name)
            item_name.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            item_name.setCheckState(Qt.CheckState.Checked) # 默认勾选
            self.table.setItem(i, 0, item_name)
            
            # 第二列: 前缀 (默认空)
            item_prefix = QTableWidgetItem("")
            item_prefix.setBackground(QColor("#fff2cc"))
            self.table.setItem(i, 1, item_prefix)
            
        self.log_text.append(f"✅ 扫描完成！发现 {len(unique_folders)} 种底层文件夹。")
        self.log_text.append("请勾选需要处理的文件夹，并在右侧填写前缀（可留空）。")

    def start_process(self):
        if not self.source_path or not self.target_path:
            QMessageBox.warning(self, "提示", "请先选择源路径和目标路径！")
            return
        
        if self.table.rowCount() == 0:
            QMessageBox.warning(self, "提示", "请先点击【扫描文件夹结构】！")
            return
        
        if self.source_path == self.target_path:
            QMessageBox.warning(self, "提示", "源路径和目标路径不能相同！")
            return

        # 收集表格数据
        prefix_map = {}
        checked_count = 0
        
        for i in range(self.table.rowCount()):
            item_check = self.table.item(i, 0)
            
            # 只有勾选了的，才加入处理列表
            if item_check.checkState() == Qt.CheckState.Checked:
                folder_name = item_check.text()
                prefix = self.table.item(i, 1).text().strip()
                # 这里不再判断 if prefix，而是直接存入 map，哪怕是空字符串
                prefix_map[folder_name] = prefix 
                checked_count += 1
        
        if checked_count == 0:
            QMessageBox.warning(self, "提示", "请至少勾选一个需要处理的文件夹！")
            return

        # 启动处理
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.log_text.clear()
        self.progress_bar.setValue(0)
        
        self.worker = RenamerWorker(self.source_path, self.target_path, prefix_map)
        self.worker.log_signal.connect(self.log)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def stop_process(self):
        if self.worker:
            self.worker.stop()
            self.log("⏳ 正在停止...")

    def log(self, msg):
        self.log_text.append(msg)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def on_finished(self, msg):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        QMessageBox.information(self, "完成", msg)

if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    win = RenamerApp()
    win.show()
    sys.exit(app.exec())