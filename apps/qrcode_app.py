import sys
import os
import qrcode
from PIL import ImageQt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QTextEdit, QMessageBox, QFileDialog,
                             QSplitter, QFrame, QColorDialog)
from PyQt6.QtGui import QPixmap, QFont, QImage, QPainter, QColor
from PyQt6.QtCore import Qt


class QRCodeApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("极速二维码工坊 (Vivo运营专用)")
        self.resize(900, 600)

        self.current_qr_image = None  # 保存当前的 PIL Image 对象
        self.qr_color = "black"  # 默认二维码颜色
        self.bg_color = "white"  # 默认背景颜色

        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        # === 左侧：操作区 ===
        left_widget = QWidget()
        left_layout = QVBoxLayout()

        # 1. 标题
        title = QLabel("🔗 链接转二维码")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        left_layout.addWidget(title)

        desc = QLabel("输入链接或文字，右侧自动生成二维码。\n支持手机直接扫码测试。")
        desc.setStyleSheet("color: #666; margin-bottom: 10px;")
        left_layout.addWidget(desc)

        # 2. 输入框
        self.text_input = QTextEdit()
        self.text_input.setPlaceholderText("请在此粘贴 http://... 链接或输入任意文本")
        self.text_input.setFont(QFont("Microsoft YaHei", 11))
        # 只要内容改变，就触发生成
        self.text_input.textChanged.connect(self.generate_qr)
        left_layout.addWidget(self.text_input)

        # 3. 颜色设置 (可选功能，增加一点趣味性)
        color_layout = QHBoxLayout()
        self.btn_color = QPushButton("🎨 更换颜色")
        self.btn_color.clicked.connect(self.choose_color)
        color_layout.addWidget(self.btn_color)
        color_layout.addStretch()
        left_layout.addLayout(color_layout)

        # 4. 保存按钮
        self.btn_save = QPushButton("💾 保存二维码图片")
        self.btn_save.setFixedHeight(50)
        self.btn_save.setStyleSheet(
            "background-color: #0078d7; color: white; font-weight: bold; font-size: 15px; border-radius: 5px;")
        self.btn_save.clicked.connect(self.save_qr_image)
        left_layout.addWidget(self.btn_save)

        left_widget.setLayout(left_layout)

        # === 右侧：展示区 ===
        right_widget = QWidget()
        right_widget.setStyleSheet("background-color: #f5f5f5; border-radius: 10px; border: 1px solid #ddd;")
        right_layout = QVBoxLayout()

        self.lbl_qr = QLabel("等待输入...")
        self.lbl_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_qr.setFont(QFont("Microsoft YaHei", 12))

        right_layout.addWidget(self.lbl_qr)
        right_widget.setLayout(right_layout)

        # 加入主布局 (左 4 : 右 6)
        layout.addWidget(left_widget, 4)
        layout.addWidget(right_widget, 6)

        self.setLayout(layout)

        # 初始化一个空的二维码
        self.text_input.setText("https://www.vivo.com.cn")

    def generate_qr(self):
        content = self.text_input.toPlainText().strip()
        if not content:
            self.lbl_qr.setText("请输入内容...")
            self.lbl_qr.setPixmap(QPixmap())  # 清空图片
            self.current_qr_image = None
            return

        try:
            # 1. 生成二维码对象
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,  # 高容错率，允许中间贴logo
                box_size=10,
                border=4,
            )
            qr.add_data(content)
            qr.make(fit=True)

            # 2. 转成图片 (使用 PIL)
            img = qr.make_image(fill_color=self.qr_color, back_color=self.bg_color)
            self.current_qr_image = img

            # 3. PIL 图片转 QPixmap 显示
            # 必须先转成 RGB 模式，因为 PyQt 处理不了 1位深度的图
            img_rgb = img.convert("RGBA")
            data = img_rgb.tobytes("raw", "RGBA")
            qimage = QImage(data, img_rgb.size[0], img_rgb.size[1], QImage.Format.Format_RGBA8888)
            pixmap = QPixmap.fromImage(qimage)

            # 4. 缩放以适应右侧窗口 (保持比例)
            w = self.lbl_qr.width() - 40  # 留点边距
            h = self.lbl_qr.height() - 40
            if w > 0 and h > 0:
                scaled_pixmap = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation)
                self.lbl_qr.setPixmap(scaled_pixmap)
                self.lbl_qr.setText("")  # 清除文字

        except Exception as e:
            self.lbl_qr.setText(f"生成出错: {str(e)}")

    def choose_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.qr_color = color.name()  # 获取十六进制颜色
            self.generate_qr()  # 重新生成

    def save_qr_image(self):
        if self.current_qr_image is None:
            QMessageBox.warning(self, "提示", "还没有生成二维码哦！")
            return

        file_path, _ = QFileDialog.getSaveFileName(self, "保存二维码", "qrcode.png",
                                                   "PNG Image (*.png);;JPEG Image (*.jpg)")
        if file_path:
            try:
                self.current_qr_image.save(file_path)
                QMessageBox.information(self, "成功", f"二维码已保存到:\n{file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")

    # 窗口大小改变时，重新调整二维码大小
    def resizeEvent(self, event):
        self.generate_qr()
        super().resizeEvent(event)


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    win = QRCodeApp()
    win.show()
    sys.exit(app.exec())