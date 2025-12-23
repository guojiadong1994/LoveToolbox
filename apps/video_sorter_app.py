import sys
import os
import shutil
import cv2
import time

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFileDialog, QProgressBar, QTextEdit, 
                             QGroupBox, QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# --- 工作线程：负责后台处理视频 ---
class SorterWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str)

    def __init__(self, source_dir, target_dir):
        super().__init__()
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.is_running = True

    def run(self):
        self.log_signal.emit(f"📂 正在扫描目录: {self.source_dir}")
        
        # 1. 扫描所有MP4文件
        video_files = []
        try:
            for root, dirs, files in os.walk(self.source_dir):
                for file in files:
                    if file.lower().endswith('.mp4'):
                        video_files.append(os.path.join(root, file))
        except Exception as e:
            self.log_signal.emit(f"❌ 扫描失败: {str(e)}")
            self.finished_signal.emit("扫描出错")
            return

        total_files = len(video_files)
        if total_files == 0:
            self.log_signal.emit("⚠️ 未找到任何 MP4 视频文件。")
            self.finished_signal.emit("无文件")
            return

        self.log_signal.emit(f"✅ 发现 {total_files} 个视频文件，开始分析分辨率...")

        # 2. 遍历处理
        success_count = 0
        fail_count = 0

        for index, file_path in enumerate(video_files):
            if not self.is_running:
                self.log_signal.emit("🛑 任务已停止。")
                break

            file_name = os.path.basename(file_path)
            
            try:
                # 使用 OpenCV 读取视频信息
                cap = cv2.VideoCapture(file_path)
                if not cap.isOpened():
                    raise Exception("无法读取视频流")

                # 获取宽高 (float 转 int)
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release() # 记得释放资源

                if width == 0 or height == 0:
                    raise Exception("分辨率读取为0")

                resolution_str = f"{width}x{height}" # 例如 1920x1080

                # 3. 创建目标文件夹
                dest_folder = os.path.join(self.target_dir, resolution_str)
                if not os.path.exists(dest_folder):
                    os.makedirs(dest_folder)

                # 4. 复制文件
                dest_path = os.path.join(dest_folder, file_name)
                
                # 防止重名覆盖逻辑
                if os.path.exists(dest_path):
                    name_part, ext_part = os.path.splitext(file_name)
                    dest_path = os.path.join(dest_folder, f"{name_part}_copy{ext_part}")

                shutil.copy2(file_path, dest_path)
                
                self.log_signal.emit(f"✅ [{resolution_str}] 已复制: {file_name}")
                success_count += 1

            except Exception as e:
                self.log_signal.emit(f"❌ 处理失败 {file_name}: {str(e)}")
                fail_count += 1

            # 更新进度
            progress = int(((index + 1) / total_files) * 100)
            self.progress_signal.emit(progress)

        self.finished_signal.emit(f"处理完成！成功: {success_count}, 失败: {fail_count}")

    def stop(self):
        self.is_running = False


# --- 主界面 ---
class VideoSorterApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("视频分辨率自动分类工具")
        self.resize(800, 600)
        
        self.source_path = ""
        self.target_path = ""
        self.worker = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 1. 顶部说明
        title = QLabel("🎥 视频分辨率分类整理")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title)
        
        desc = QLabel("此工具将自动识别源文件夹中 MP4 视频的分辨率(如1920x1080)，\n并在目标位置自动创建对应文件夹进行归档。")
        desc.setStyleSheet("color: #666; margin-bottom: 20px;")
        layout.addWidget(desc)

        # 2. 路径选择区
        path_group = QGroupBox("路径设置")
        path_layout = QVBoxLayout()

        # 源文件夹
        src_layout = QHBoxLayout()
        self.btn_src = QPushButton("📂 选择杂乱的视频文件夹 (源)")
        self.btn_src.clicked.connect(self.select_source)
        self.lbl_src = QLabel("未选择...")
        self.lbl_src.setStyleSheet("color: #d93025;")
        src_layout.addWidget(self.btn_src)
        src_layout.addWidget(self.lbl_src)
        path_layout.addLayout(src_layout)

        # 目标文件夹
        dst_layout = QHBoxLayout()
        self.btn_dst = QPushButton("📂 选择整理后存放位置 (目标)")
        self.btn_dst.clicked.connect(self.select_target)
        self.lbl_dst = QLabel("未选择...")
        self.lbl_dst.setStyleSheet("color: #d93025;")
        dst_layout.addWidget(self.btn_dst)
        dst_layout.addWidget(self.lbl_dst)
        path_layout.addLayout(dst_layout)

        path_group.setLayout(path_layout)
        layout.addWidget(path_group)

        # 3. 操作区
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("🚀 开始自动整理")
        self.btn_start.setFixedHeight(45)
        self.btn_start.setStyleSheet("background-color: #0078d7; color: white; font-weight: bold; font-size: 14px;")
        self.btn_start.clicked.connect(self.start_process)
        
        self.btn_stop = QPushButton("🛑 停止")
        self.btn_stop.setFixedHeight(45)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_process)

        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        layout.addLayout(btn_layout)

        # 4. 进度与日志
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        layout.addWidget(QLabel("执行日志:"))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        layout.addWidget(self.log_text)

        self.setLayout(layout)

    # --- 逻辑 ---
    def select_source(self):
        d = QFileDialog.getExistingDirectory(self, "选择源文件夹")
        if d:
            self.source_path = d
            self.lbl_src.setText(d)
            self.lbl_src.setStyleSheet("color: #188038;") # Green

    def select_target(self):
        d = QFileDialog.getExistingDirectory(self, "选择目标文件夹")
        if d:
            self.target_path = d
            self.lbl_dst.setText(d)
            self.lbl_dst.setStyleSheet("color: #188038;") # Green

    def start_process(self):
        if not self.source_path or not self.target_path:
            QMessageBox.warning(self, "提示", "请先选择【源文件夹】和【目标文件夹】！")
            return
        
        if self.source_path == self.target_path:
            QMessageBox.warning(self, "提示", "源文件夹和目标文件夹不能相同，否则会造成混乱。")
            return

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.log_text.clear()
        self.progress_bar.setValue(0)

        self.worker = SorterWorker(self.source_path, self.target_path)
        self.worker.log_signal.connect(self.log)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def stop_process(self):
        if self.worker:
            self.worker.stop()
            self.log("正在停止...")
            self.btn_stop.setEnabled(False)

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
    win = VideoSorterApp()
    win.show()
    sys.exit(app.exec())