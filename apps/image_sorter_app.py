import sys
import os
import shutil
from PIL import Image
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QLineEdit, QProgressBar, QFileDialog,
                             QMessageBox, QGroupBox, QTextEdit)
from PyQt6.QtCore import Qt, QThread, pyqtSignal


# === 🏗️ 后台工作线程 (负责搬运图片) ===
class SorterWorker(QThread):
    # 信号：进度(当前, 总数)、日志信息、完成信号、错误信号
    progress_update = pyqtSignal(int, int)
    log_update = pyqtSignal(str)
    finished_signal = pyqtSignal(int)  # 返回成功处理的总数
    error_signal = pyqtSignal(str)

    def __init__(self, source_dir, target_dir):
        super().__init__()
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.is_running = True  # 控制停止的标志位

    def stop(self):
        self.is_running = False

    def run(self):
        try:
            # 1. 扫描所有图片文件
            supported_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.gif', '.tiff'}
            all_files = [f for f in os.listdir(self.source_dir) if os.path.isfile(os.path.join(self.source_dir, f))]

            image_files = []
            for f in all_files:
                ext = os.path.splitext(f)[1].lower()
                if ext in supported_exts:
                    image_files.append(f)

            total_count = len(image_files)
            if total_count == 0:
                self.error_signal.emit("源文件夹里没找到图片哦！")
                return

            processed_count = 0

            self.log_update.emit(f"🚀 开始扫描，共发现 {total_count} 张图片...")

            # 2. 开始遍历处理
            for filename in image_files:
                if not self.is_running:
                    self.log_update.emit("⚠️ 用户手动停止任务")
                    break

                src_path = os.path.join(self.source_dir, filename)

                try:
                    # 读取分辨率 (使用 PIL，不加载原图，速度快)
                    with Image.open(src_path) as img:
                        width, height = img.size
                        # 格式化文件夹名称，例如 "1920x1080"
                        res_folder_name = f"{width}x{height}"

                    # 创建目标子文件夹
                    dest_folder = os.path.join(self.target_dir, res_folder_name)
                    if not os.path.exists(dest_folder):
                        os.makedirs(dest_folder)

                    # 复制文件
                    dest_path = os.path.join(dest_folder, filename)

                    # 防止同名文件覆盖，如果存在则跳过或重命名，这里简单处理：直接覆盖(CP常用逻辑)
                    shutil.copy2(src_path, dest_path)

                    self.log_update.emit(f"✅ [复制成功] {filename} -> {res_folder_name}/")
                    processed_count += 1

                    # 发送进度
                    self.progress_update.emit(processed_count, total_count)

                except Exception as e:
                    self.log_update.emit(f"❌ [处理失败] {filename}: {str(e)}")

            self.finished_signal.emit(processed_count)

        except Exception as e:
            self.error_signal.emit(f"发生系统错误: {str(e)}")


# === 🖥️ 主界面 ===
class ImageSorterApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("图片分辨率智能分拣器")
        self.resize(800, 600)
        self.worker = None  # 线程句柄

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 1. 标题区
        title = QLabel("📂 图片按分辨率自动归类")
        title.setFont(self.get_font(16, True))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            "功能：读取源文件夹图片尺寸 -> 自动建立【宽x高】文件夹 -> 复制图片进去。\n安全承诺：只复制，不修改原文件。")
        desc.setStyleSheet("color: #666; margin-bottom: 10px;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        # 2. 路径选择区
        # --- 源文件夹 ---
        grp_src = QGroupBox("1. 图片在哪里？(源文件夹)")
        layout_src = QHBoxLayout()
        self.input_src = QLineEdit()
        self.input_src.setPlaceholderText("请选择包含杂乱图片的文件夹...")
        self.input_src.setReadOnly(True)
        btn_src = QPushButton("📂 选择文件夹")
        btn_src.clicked.connect(lambda: self.select_folder(self.input_src))
        layout_src.addWidget(self.input_src)
        layout_src.addWidget(btn_src)
        grp_src.setLayout(layout_src)
        layout.addWidget(grp_src)

        # --- 目标文件夹 ---
        grp_dst = QGroupBox("2. 整理到哪里？(目标文件夹)")
        layout_dst = QHBoxLayout()
        self.input_dst = QLineEdit()
        self.input_dst.setPlaceholderText("请选择一个空文件夹来存放整理后的结果...")
        self.input_dst.setReadOnly(True)
        btn_dst = QPushButton("📂 选择文件夹")
        btn_dst.clicked.connect(lambda: self.select_folder(self.input_dst))
        layout_dst.addWidget(self.input_dst)
        layout_dst.addWidget(btn_dst)
        grp_dst.setLayout(layout_dst)
        layout.addWidget(grp_dst)

        # 3. 进度条与日志
        layout.addWidget(QLabel("⏳ 处理进度:"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("准备就绪 (%v/%m)")
        layout.addWidget(self.progress_bar)

        self.log_area = QTextEdit()
        self.log_area.setPlaceholderText("运行日志将显示在这里...")
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

        # 4. 控制按钮
        btn_layout = QHBoxLayout()

        self.btn_start = QPushButton("🚀 开始分拣")
        self.btn_start.setFixedHeight(50)
        self.btn_start.setStyleSheet(
            "background-color: #0078d7; color: white; font-weight: bold; font-size: 16px; border-radius: 5px;")
        self.btn_start.clicked.connect(self.start_sorting)

        self.btn_stop = QPushButton("🛑 停止")
        self.btn_stop.setFixedHeight(50)
        self.btn_stop.setEnabled(False)  # 默认不可点
        self.btn_stop.setStyleSheet(
            "background-color: #d93025; color: white; font-weight: bold; font-size: 16px; border-radius: 5px;")
        self.btn_stop.clicked.connect(self.stop_sorting)

        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)

        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def get_font(self, size, bold=False):
        font = self.font()
        font.setPointSize(size)
        font.setBold(bold)
        return font

    def select_folder(self, line_edit):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            line_edit.setText(folder)

    def start_sorting(self):
        src = self.input_src.text().strip()
        dst = self.input_dst.text().strip()

        if not src or not dst:
            QMessageBox.warning(self, "提示", "请先选择【源文件夹】和【目标文件夹】！")
            return

        if src == dst:
            QMessageBox.warning(self, "警告",
                                "源文件夹和目标文件夹不能是同一个！\n为了安全，请选择一个不同的文件夹存放结果。")
            return

        # UI 状态切换
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.log_area.clear()
        self.progress_bar.setValue(0)

        # 启动线程
        self.worker = SorterWorker(src, dst)
        self.worker.progress_update.connect(self.update_progress)
        self.worker.log_update.connect(self.update_log)
        self.worker.finished_signal.connect(self.task_finished)
        self.worker.error_signal.connect(self.task_error)
        self.worker.start()

    def stop_sorting(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.btn_stop.setEnabled(False)
            self.btn_stop.setText("正在停止...")

    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"正在处理: {current}/{total} ({(current / total) * 100:.1f}%)")

    def update_log(self, text):
        self.log_area.append(text)

    def task_finished(self, count):
        self.reset_ui()
        QMessageBox.information(self, "完成", f"🎉 分拣结束！\n\n共成功处理: {count} 张图片。\n请前往目标文件夹查看结果。")

    def task_error(self, err_msg):
        self.reset_ui()
        QMessageBox.critical(self, "错误", err_msg)

    def reset_ui(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("🛑 停止")
        self.progress_bar.setFormat("准备就绪")


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    win = ImageSorterApp()
    win.show()
    sys.exit(app.exec())