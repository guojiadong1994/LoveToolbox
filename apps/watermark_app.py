import sys
import os  # 新增：用于获取文件后缀
import cv2
import numpy as np
from PIL import Image  # 新增：用于保存 PDF
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFileDialog, QMessageBox, QSlider, QCheckBox)
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QAction
from PyQt6.QtCore import Qt, QPoint, QRect

class WatermarkRemover(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("智能图片去水印 (多格式导出版)")
        self.resize(1000, 700)
        
        # --- 核心数据 ---
        self.original_image = None      # RGB 格式
        self.display_image = None       
        self.mask = None                
        self.history = []               
        self.original_extension = ".jpg" # 默认后缀，加载图片后会更新
        
        # --- 缩放与坐标相关 ---
        self.scale_factor = 1.0         
        self.offset_x = 0               
        self.offset_y = 0               
        
        # --- 绘图状态 ---
        self.drawing = False
        self.last_point = None          
        self.brush_size = 20            
        
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout()

        # --- 1. 顶部工具栏 ---
        toolbar = QHBoxLayout()
        
        self.btn_load = QPushButton("📂 打开图片")
        self.btn_load.clicked.connect(self.load_image)
        self.btn_save = QPushButton("💾 保存结果")
        self.btn_save.clicked.connect(self.save_image)
        self.btn_save.setEnabled(False)

        lbl_size = QLabel("🖊️ 笔刷大小:")
        self.slider_size = QSlider(Qt.Orientation.Horizontal)
        self.slider_size.setRange(5, 100)
        self.slider_size.setValue(30)
        self.slider_size.setFixedWidth(150)
        self.slider_size.valueChanged.connect(self.change_brush_size)
        
        self.btn_undo = QPushButton("↩️ 撤销")
        self.btn_undo.clicked.connect(self.undo_last_step)
        self.btn_undo.setEnabled(False)

        self.chk_auto = QCheckBox("✨ 松开即消")
        self.chk_auto.setChecked(True)

        self.btn_process = QPushButton("⚡ 执行消除")
        self.btn_process.clicked.connect(self.process_inpainting)
        self.btn_process.hide()
        self.chk_auto.toggled.connect(lambda checked: self.btn_process.setVisible(not checked))

        toolbar.addWidget(self.btn_load)
        toolbar.addWidget(self.btn_save)
        toolbar.addSpacing(20)
        toolbar.addWidget(lbl_size)
        toolbar.addWidget(self.slider_size)
        toolbar.addSpacing(20)
        toolbar.addWidget(self.chk_auto)
        toolbar.addWidget(self.btn_process)
        toolbar.addWidget(self.btn_undo)
        toolbar.addStretch()

        main_layout.addLayout(toolbar)

        # --- 2. 图片显示区域 ---
        self.image_label = QLabel("请打开图片\n支持滚轮缩放窗口，图片自适应")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background-color: #2b2b2b; color: #aaa; font-size: 16px;")
        self.image_label.setMouseTracking(True)
        self.image_label.setMinimumSize(400, 300)
        
        main_layout.addWidget(self.image_label, 1)
        self.setLayout(main_layout)

    # --- 窗口大小改变事件 ---
    def resizeEvent(self, event):
        if self.original_image is not None:
            self.update_display()
        super().resizeEvent(event)

    # --- 逻辑功能 ---

    def load_image(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.webp)")
        if file_name:
            # 1. 记录原始后缀 (例如 .png)
            _, ext = os.path.splitext(file_name)
            self.original_extension = ext.lower()

            # 2. 读取图片
            img_src = cv2.imdecode(np.fromfile(file_name, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if img_src is None:
                return

            # 3. 处理透明背景
            if len(img_src.shape) == 3 and img_src.shape[2] == 4:
                b, g, r, a = cv2.split(img_src)
                white_bg = np.ones_like(img_src, dtype=np.uint8) * 255
                alpha = a.astype(float) / 255.0
                alpha = cv2.merge([alpha, alpha, alpha, alpha])
                foreground = img_src.astype(float)
                background = white_bg.astype(float)
                final_img = foreground[:,:,:3] * alpha[:,:,:3] + background[:,:,:3] * (1 - alpha[:,:,:3])
                img_src = final_img.astype(np.uint8)
            
            if len(img_src.shape) == 3:
                self.original_image = cv2.cvtColor(img_src, cv2.COLOR_BGR2RGB)
            else:
                self.original_image = cv2.cvtColor(img_src, cv2.COLOR_GRAY2RGB)
            
            # 初始化
            h, w, _ = self.original_image.shape
            self.mask = np.zeros((h, w), dtype=np.uint8)
            self.display_image = self.original_image.copy()
            self.history = []
            self.btn_undo.setEnabled(False)
            
            self.update_display()
            self.btn_save.setEnabled(True)

    def change_brush_size(self, value):
        self.brush_size = value

    def undo_last_step(self):
        if self.history:
            self.original_image = self.history.pop()
            self.display_image = self.original_image.copy()
            self.mask[:] = 0
            self.update_display()
            if not self.history:
                self.btn_undo.setEnabled(False)

    def update_display(self):
        if self.display_image is None:
            return
        
        view_w = self.image_label.width()
        view_h = self.image_label.height()
        img_h, img_w, ch = self.display_image.shape
        
        scale_w = view_w / img_w
        scale_h = view_h / img_h
        self.scale_factor = min(scale_w, scale_h)
        
        new_w = int(img_w * self.scale_factor)
        new_h = int(img_h * self.scale_factor)
        
        self.offset_x = (view_w - new_w) // 2
        self.offset_y = (view_h - new_h) // 2
        
        bytes_per_line = ch * img_w
        q_img = QImage(self.display_image.data, img_w, img_h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)
        scaled_pixmap = pixmap.scaled(new_w, new_h, 
                                      Qt.AspectRatioMode.KeepAspectRatio, 
                                      Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled_pixmap)

    def get_real_coords(self, global_pos):
        if self.original_image is None:
            return None

        mouse_x = global_pos.x()
        mouse_y = global_pos.y()
        
        img_x_disp = mouse_x - self.offset_x
        img_y_disp = mouse_y - self.offset_y
        
        real_x = int(img_x_disp / self.scale_factor)
        real_y = int(img_y_disp / self.scale_factor)
        
        h, w, _ = self.original_image.shape
        if 0 <= real_x < w and 0 <= real_y < h:
            return QPoint(real_x, real_y)
        return None

    # --- 鼠标事件 ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.original_image is not None:
            label_pos = self.image_label.mapFrom(self, event.pos())
            real_point = self.get_real_coords(label_pos)
            
            if real_point:
                self.drawing = True
                self.last_point = real_point
                self.history.append(self.original_image.copy())
                self.btn_undo.setEnabled(True)
                self.draw_stroke(real_point)

    def mouseMoveEvent(self, event):
        if self.drawing and self.original_image is not None:
            label_pos = self.image_label.mapFrom(self, event.pos())
            real_point = self.get_real_coords(label_pos)
            if real_point:
                self.draw_stroke(real_point)
                self.last_point = real_point

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drawing:
            self.drawing = False
            if self.chk_auto.isChecked():
                self.process_inpainting()

    def draw_stroke(self, current_point):
        if not self.last_point:
            self.last_point = current_point

        cv2.line(self.mask, (self.last_point.x(), self.last_point.y()), 
                 (current_point.x(), current_point.y()), 255, self.brush_size)
        
        overlay = self.display_image.copy()
        cv2.line(overlay, (self.last_point.x(), self.last_point.y()), 
                 (current_point.x(), current_point.y()), (255, 0, 0), self.brush_size)
        
        alpha = 0.5
        cv2.addWeighted(overlay, alpha, self.display_image, 1 - alpha, 0, self.display_image)
        self.update_display()

    def process_inpainting(self):
        if self.original_image is None or np.count_nonzero(self.mask) == 0:
            return
        res = cv2.inpaint(self.original_image, self.mask, 3, cv2.INPAINT_TELEA)
        self.original_image = res
        self.display_image = res.copy()
        self.mask[:] = 0
        self.update_display()

    # --- 修改后的保存逻辑 ---
    def save_image(self):
        if self.original_image is None:
            return
        
        # 1. 构建过滤器字符串
        # 格式示例: "Original (*.jpg);;JPEG (*.jpg);;PDF (*.pdf)"
        # 默认把 原有格式 放在第一位，这样就是默认选中
        orig_filter = f"Original ({self.original_extension})"
        filters = f"{orig_filter};;JPEG Image (*.jpg *.jpeg);;PNG Image (*.png);;PDF Document (*.pdf)"
        
        # 2. 弹出对话框
        default_name = f"processed{self.original_extension}"
        file_path, selected_filter = QFileDialog.getSaveFileName(self, "保存文件", default_name, filters)
        
        if not file_path:
            return

        # 3. 检查文件后缀，处理逻辑
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()

        try:
            # === 如果是保存为 PDF ===
            if ext == '.pdf':
                # PIL Image 需要 RGB 格式 (self.original_image 已经是 RGB)
                pil_img = Image.fromarray(self.original_image)
                pil_img.save(file_path, "PDF", resolution=100.0)
                QMessageBox.information(self, "成功", f"已成功导出为 PDF:\n{file_path}")
            
            # === 如果是保存为图片 (JPG, PNG, 原格式等) ===
            else:
                # 兼容性处理：如果用户没有输入后缀，我们根据 filter 强行补全吗？
                # QFileDialog 通常会返回带后缀的路径，除非用户故意删掉
                # OpenCV 保存需要 BGR 格式
                save_img_bgr = cv2.cvtColor(self.original_image, cv2.COLOR_RGB2BGR)
                
                # imencode 支持中文路径，imwrite 不支持
                is_success, im_buf = cv2.imencode(ext, save_img_bgr)
                
                if is_success:
                    im_buf.tofile(file_path)
                    QMessageBox.information(self, "成功", f"图片已保存:\n{file_path}")
                else:
                    # 如果编码失败（比如不支持的格式），尝试强制存为 jpg
                    cv2.imencode(".jpg", save_img_bgr)[1].tofile(file_path + ".jpg")
                    QMessageBox.warning(self, "警告", "格式不支持，已默认保存为 .jpg")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WatermarkRemover()
    window.show()
    sys.exit(app.exec())