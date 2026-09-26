import os
import shutil
import sys
import tempfile
from collections import Counter
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSlider,
    QSpinBox,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QAbstractItemView,
)


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MAX_IMAGE_PIXELS_FOR_TOOL = 60_000_000  # 保护内存：单张最多约 6000 万像素


def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


def safe_display_path(path: str) -> str:
    return os.path.normpath(path) if path else ""


def read_oriented_size(path: str):
    """只读取尺寸和 EXIF 方向，不解码整张图片。"""
    with Image.open(path) as im:
        width, height = im.size
        try:
            orientation = im.getexif().get(274)
        except Exception:
            orientation = None
        if orientation in (5, 6, 7, 8):
            width, height = height, width
        return width, height


class ImageDropTable(QTableWidget):
    """图片列表，同时支持把多张图片直接拖入。"""

    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            valid = any(
                url.isLocalFile()
                and Path(url.toLocalFile()).suffix.lower() in SUPPORTED_EXTENSIONS
                for url in event.mimeData().urls()
            )
            if valid:
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        files = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if files:
            self.filesDropped.emit(files)
            event.acceptProposedAction()
        else:
            event.ignore()


class ImageConvertWorker(QThread):
    progress = pyqtSignal(int, int, str)
    rowResult = pyqtSignal(str, str, str, str)  # path, new_size_text, new_bytes_text, status
    summary = pyqtSignal(int, int, str)
    fatalError = pyqtSignal(str)

    def __init__(
        self,
        files,
        save_dir,
        resize_enabled,
        target_width,
        target_height,
        limit_enabled,
        max_bytes,
        target_size_mode=False,
        parent=None,
    ):
        super().__init__(parent)
        self.files = list(files)
        self.save_dir = save_dir
        self.resize_enabled = resize_enabled
        self.target_width = target_width
        self.target_height = target_height
        self.limit_enabled = limit_enabled
        self.max_bytes = max_bytes
        self.target_size_mode = target_size_mode

    def run(self):
        success = 0
        failed = 0
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            total = len(self.files)
            for index, path in enumerate(self.files, start=1):
                if self.isInterruptionRequested():
                    break

                name = os.path.basename(path)
                self.progress.emit(index - 1, total, f"正在处理：{name}")
                try:
                    new_dim, new_bytes, status = self._process_one(path)
                    success += 1
                    self.rowResult.emit(
                        path,
                        new_dim,
                        format_file_size(new_bytes),
                        status,
                    )
                except Exception as exc:
                    failed += 1
                    self.rowResult.emit(path, "-", "-", f"失败：{exc}")

                self.progress.emit(index, total, f"已处理 {index} / {total}")

            self.summary.emit(success, failed, self.save_dir)
        except Exception as exc:
            self.fatalError.emit(str(exc))

    def _process_one(self, source_path: str):
        source_path = os.path.abspath(source_path)
        output_path = os.path.abspath(
            os.path.join(self.save_dir, os.path.basename(source_path))
        )
        same_path = os.path.normcase(source_path) == os.path.normcase(output_path)
        original_bytes = os.path.getsize(source_path)

        try:
            with Image.open(source_path) as opened:
                if opened.width * opened.height > MAX_IMAGE_PIXELS_FOR_TOOL:
                    raise ValueError("图片像素过大，为避免占用过多内存已停止处理")
                original_format = (opened.format or "").upper()
                source_info = dict(opened.info)
                image = ImageOps.exif_transpose(opened).copy()
                try:
                    exif_obj = opened.getexif()
                    # exif_transpose 已经应用方向，移除 Orientation 避免再次旋转
                    if 274 in exif_obj:
                        del exif_obj[274]
                    exif_bytes = exif_obj.tobytes() if exif_obj else None
                except Exception:
                    exif_bytes = None
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("无法读取图片或图片已损坏") from exc

        resized = False
        if self.resize_enabled:
            if self.target_width <= 0 or self.target_height <= 0:
                raise ValueError("目标尺寸必须大于 0")
            if self.target_width * self.target_height > MAX_IMAGE_PIXELS_FOR_TOOL:
                raise ValueError("目标尺寸过大，为避免占用过多内存已停止处理")
            if image.size != (self.target_width, self.target_height):
                image = image.resize(
                    (self.target_width, self.target_height),
                    Image.Resampling.LANCZOS,
                )
                resized = True

        # 默认模式：文件大小只是“上限”。
        # 没有尺寸变化且原图已经不超限时，完全保留原文件，不做任何重新编码。
        # “尽量调整到目标大小”模式开启后，才会对所有图片重新编码并尝试接近目标值。
        if (
            not resized
            and not self.target_size_mode
            and (not self.limit_enabled or original_bytes <= self.max_bytes)
        ):
            if same_path:
                return (
                    f"{image.width}×{image.height}",
                    original_bytes,
                    "无需处理（原图保留）",
                )
            self._safe_copy(source_path, output_path)
            return (
                f"{image.width}×{image.height}",
                os.path.getsize(output_path),
                "已复制（无需压缩）",
            )

        fmt = self._normalize_format(original_format, source_path)

        # 先按正常高质量方式编码一次。
        # 默认“上限模式”下，只有这个结果仍然超过上限时，才继续降低质量。
        normal_encoded = self._encode_image(
            image=image,
            fmt=fmt,
            limit_bytes=None,
            source_info=source_info,
            exif_bytes=exif_bytes,
        )

        compressed_for_limit = False
        if self.limit_enabled:
            if self.target_size_mode:
                encoded = self._encode_near_target(
                    image=image,
                    fmt=fmt,
                    target_bytes=self.max_bytes,
                    source_info=source_info,
                    exif_bytes=exif_bytes,
                )
            elif len(normal_encoded) > self.max_bytes:
                encoded = self._encode_image(
                    image=image,
                    fmt=fmt,
                    limit_bytes=self.max_bytes,
                    source_info=source_info,
                    exif_bytes=exif_bytes,
                )
                compressed_for_limit = True
            else:
                encoded = normal_encoded
        else:
            encoded = normal_encoded

        if (
            self.limit_enabled
            and not self.target_size_mode
            and len(encoded) > self.max_bytes
        ):
            raise ValueError(
                f"在保持当前尺寸和格式下无法压缩到 {format_file_size(self.max_bytes)}"
            )

        self._atomic_write(output_path, encoded)

        if self.target_size_mode and self.limit_enabled:
            action = "已尽量调整到目标大小"
            status = f"已调整尺寸并尽量接近目标大小" if resized else action
        elif resized and compressed_for_limit:
            status = "已调整尺寸并压缩至上限内"
        elif resized:
            status = "已调整尺寸（未触发大小压缩）"
        elif compressed_for_limit:
            status = "已压缩至上限内"
        else:
            status = "已重新编码"

        return f"{image.width}×{image.height}", len(encoded), status

    @staticmethod
    def _normalize_format(fmt: str, path: str) -> str:
        if fmt in {"JPEG", "JPG", "PNG", "WEBP", "BMP"}:
            return "JPEG" if fmt == "JPG" else fmt
        ext = Path(path).suffix.lower()
        return {
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".png": "PNG",
            ".webp": "WEBP",
            ".bmp": "BMP",
        }.get(ext, "PNG")

    @staticmethod
    def _safe_copy(source: str, output: str):
        os.makedirs(os.path.dirname(output), exist_ok=True)
        if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(output)):
            return
        fd, temp_path = tempfile.mkstemp(
            prefix=".lovetoolbox_", suffix=Path(output).suffix, dir=os.path.dirname(output)
        )
        os.close(fd)
        try:
            shutil.copy2(source, temp_path)
            os.replace(temp_path, output)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @staticmethod
    def _atomic_write(output: str, data: bytes):
        os.makedirs(os.path.dirname(output), exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=".lovetoolbox_", suffix=Path(output).suffix, dir=os.path.dirname(output)
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            # os.replace 在 Windows/macOS/Linux 均可覆盖已有同名文件
            os.replace(temp_path, output)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _encode_image(self, image, fmt, limit_bytes, source_info, exif_bytes):
        if fmt == "JPEG":
            prepared = self._prepare_jpeg(image)
            common = self._metadata_kwargs(fmt, source_info, exif_bytes)
            if limit_bytes is None:
                return self._save_to_bytes(
                    prepared, fmt, quality=95, optimize=True, progressive=True, **common
                )
            return self._quality_search(
                prepared,
                fmt,
                limit_bytes,
                low=1,
                high=100,
                extra={"optimize": True, "progressive": True, "subsampling": 0, **common},
            )

        if fmt == "WEBP":
            prepared = image
            common = self._metadata_kwargs(fmt, source_info, exif_bytes)
            if limit_bytes is None:
                return self._save_to_bytes(prepared, fmt, quality=95, method=6, **common)
            return self._quality_search(
                prepared,
                fmt,
                limit_bytes,
                low=1,
                high=100,
                extra={"method": 6, **common},
            )

        if fmt == "PNG":
            common = self._metadata_kwargs(fmt, source_info, exif_bytes)
            initial = self._save_to_bytes(
                image, fmt, optimize=True, compress_level=9, **common
            )
            if limit_bytes is None or len(initial) <= limit_bytes:
                return initial

            best = initial
            # PNG 无损压缩不一定能达到很小的体积，超限时逐步颜色量化。
            for colors in (256, 192, 128, 96, 64, 48, 32, 24, 16):
                if image.mode in ("RGBA", "LA"):
                    work = image.convert("RGBA").quantize(
                        colors=colors, method=Image.Quantize.FASTOCTREE
                    )
                else:
                    work = image.convert("RGB").quantize(
                        colors=colors, method=Image.Quantize.MEDIANCUT
                    )
                candidate = self._save_to_bytes(
                    work, fmt, optimize=True, compress_level=9, **common
                )
                if len(candidate) < len(best):
                    best = candidate
                if len(candidate) <= limit_bytes:
                    return candidate
            return best

        if fmt == "BMP":
            initial = self._save_to_bytes(image.convert("RGB"), fmt)
            if limit_bytes is None or len(initial) <= limit_bytes:
                return initial
            best = initial
            for colors in (256, 128, 64, 32, 16):
                work = image.convert("RGB").quantize(
                    colors=colors, method=Image.Quantize.MEDIANCUT
                )
                candidate = self._save_to_bytes(work, fmt)
                if len(candidate) < len(best):
                    best = candidate
                if len(candidate) <= limit_bytes:
                    return candidate
            return best

        return self._save_to_bytes(image, fmt)

    def _encode_near_target(self, image, fmt, target_bytes, source_info, exif_bytes):
        """尽量接近目标文件大小。

        JPEG/WEBP 在质量 1~100 中寻找最接近目标的结果；PNG/BMP 在可用的
        无损/量化方案中选择最接近目标的候选。不会通过填充无意义数据强行凑大小。
        """
        if fmt == "JPEG":
            prepared = self._prepare_jpeg(image)
            common = self._metadata_kwargs(fmt, source_info, exif_bytes)
            return self._quality_target_search(
                prepared,
                fmt,
                target_bytes,
                low=1,
                high=100,
                extra={"optimize": True, "progressive": True, "subsampling": 0, **common},
            )

        if fmt == "WEBP":
            common = self._metadata_kwargs(fmt, source_info, exif_bytes)
            return self._quality_target_search(
                image,
                fmt,
                target_bytes,
                low=1,
                high=100,
                extra={"method": 6, **common},
            )

        candidates = []
        if fmt == "PNG":
            common = self._metadata_kwargs(fmt, source_info, exif_bytes)
            candidates.append(
                self._save_to_bytes(image, fmt, optimize=True, compress_level=9, **common)
            )
            for colors in (256, 192, 128, 96, 64, 48, 32, 24, 16):
                if image.mode in ("RGBA", "LA"):
                    work = image.convert("RGBA").quantize(
                        colors=colors, method=Image.Quantize.FASTOCTREE
                    )
                else:
                    work = image.convert("RGB").quantize(
                        colors=colors, method=Image.Quantize.MEDIANCUT
                    )
                candidates.append(
                    self._save_to_bytes(work, fmt, optimize=True, compress_level=9, **common)
                )
        elif fmt == "BMP":
            candidates.append(self._save_to_bytes(image.convert("RGB"), fmt))
            for colors in (256, 128, 64, 32, 16):
                work = image.convert("RGB").quantize(
                    colors=colors, method=Image.Quantize.MEDIANCUT
                )
                candidates.append(self._save_to_bytes(work, fmt))
        else:
            return self._save_to_bytes(image, fmt)

        return min(candidates, key=lambda data: (abs(len(data) - target_bytes), len(data)))

    def _quality_target_search(self, image, fmt, target_bytes, low, high, extra):
        best = None
        best_diff = None
        left, right = low, high
        while left <= right:
            quality = (left + right) // 2
            candidate = self._save_to_bytes(image, fmt, quality=quality, **extra)
            size = len(candidate)
            diff = abs(size - target_bytes)
            if best is None or diff < best_diff or (diff == best_diff and size < len(best)):
                best = candidate
                best_diff = diff
            if size < target_bytes:
                left = quality + 1
            elif size > target_bytes:
                right = quality - 1
            else:
                return candidate

        # 把边界质量也纳入比较，处理目标大于 quality=100 或小于 quality=1 的情况。
        for quality in {low, high, max(low, min(high, left)), max(low, min(high, right))}:
            candidate = self._save_to_bytes(image, fmt, quality=quality, **extra)
            size = len(candidate)
            diff = abs(size - target_bytes)
            if best is None or diff < best_diff or (diff == best_diff and size < len(best)):
                best = candidate
                best_diff = diff
        return best

    @staticmethod
    def _prepare_jpeg(image):
        if image.mode in ("RGBA", "LA"):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        return image.convert("RGB")

    @staticmethod
    def _metadata_kwargs(fmt, source_info, exif_bytes):
        kwargs = {}
        icc = source_info.get("icc_profile")
        dpi = source_info.get("dpi")
        if icc:
            kwargs["icc_profile"] = icc
        if dpi and fmt in {"JPEG", "PNG"}:
            kwargs["dpi"] = dpi
        if exif_bytes and fmt in {"JPEG", "WEBP", "PNG"}:
            kwargs["exif"] = exif_bytes
        return kwargs

    @staticmethod
    def _save_to_bytes(image, fmt, **kwargs):
        buffer = BytesIO()
        image.save(buffer, format=fmt, **kwargs)
        return buffer.getvalue()

    def _quality_search(self, image, fmt, limit_bytes, low, high, extra):
        best = None
        best_size = -1
        left, right = low, high
        while left <= right:
            quality = (left + right) // 2
            candidate = self._save_to_bytes(image, fmt, quality=quality, **extra)
            size = len(candidate)
            if size <= limit_bytes:
                if size > best_size:
                    best = candidate
                    best_size = size
                left = quality + 1
            else:
                right = quality - 1

        if best is not None:
            return best
        # 即使最低质量仍超限，也返回最小结果，由上层给出明确失败提示。
        return self._save_to_bytes(image, fmt, quality=low, **extra)


class ImageConverterApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("图片转换")
        self.resize(1080, 760)
        self.selected_files = []
        self.save_dir = ""
        self.worker = None
        self._syncing_size_controls = False
        self.target_size_kb = 500.0
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(
            """
            QWidget { font-size: 14px; }
            QGroupBox {
                font-size: 15px;
                font-weight: bold;
                border: 1px solid #d9d9d9;
                border-radius: 10px;
                margin-top: 10px;
                padding-top: 12px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
            QPushButton {
                min-height: 34px;
                padding: 4px 12px;
                border: 1px solid #cfcfcf;
                border-radius: 7px;
                background: #ffffff;
            }
            QPushButton:hover { background: #f5f5f5; }
            QPushButton#primaryButton {
                background: #2e7d32;
                color: white;
                border: none;
                font-weight: bold;
                min-height: 42px;
            }
            QPushButton#primaryButton:hover { background: #256a29; }
            QTableWidget { border: 1px solid #ddd; border-radius: 8px; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                min-height: 32px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title = QLabel("🖼️ 图片转换")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(self._build_files_group(), 3)
        top.addWidget(self._build_settings_group(), 2)
        root.addLayout(top, 1)

        root.addWidget(self._build_output_group())

        action_row = QHBoxLayout()
        self.btn_start = QPushButton("开始处理")
        self.btn_start.setObjectName("primaryButton")
        self.btn_start.clicked.connect(self.start_convert)
        self.btn_open = QPushButton("打开输出目录")
        self.btn_open.clicked.connect(self.open_output_dir)
        action_row.addStretch()
        action_row.addWidget(self.btn_start)
        action_row.addWidget(self.btn_open)
        root.addLayout(action_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.lbl_status = QLabel("请选择或拖入图片。")
        self.lbl_status.setStyleSheet("color: #666;")
        root.addWidget(self.lbl_status)

    def _build_files_group(self):
        group = QGroupBox("选择图片（支持多选和拖拽）")
        layout = QVBoxLayout(group)

        buttons = QHBoxLayout()
        btn_select = QPushButton("选择多张图片")
        btn_select.clicked.connect(self.select_images)
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self.clear_images)
        buttons.addWidget(btn_select)
        buttons.addWidget(btn_clear)
        buttons.addStretch()
        layout.addLayout(buttons)

        hint = QLabel("也可以把 JPG / PNG / WEBP / BMP 图片直接拖到下方列表。")
        hint.setStyleSheet("color: #777;")
        layout.addWidget(hint)

        self.table = ImageDropTable()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["文件名", "原尺寸", "原大小", "处理后", "状态"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.filesDropped.connect(self.add_images)
        layout.addWidget(self.table, 1)
        return group

    def _build_settings_group(self):
        group = QGroupBox("转换设置")
        layout = QVBoxLayout(group)

        self.chk_resize = QCheckBox("修改图片尺寸")
        self.chk_resize.setChecked(True)
        layout.addWidget(self.chk_resize)

        size_grid = QGridLayout()
        size_grid.setHorizontalSpacing(12)

        size_grid.addWidget(QLabel("宽度"), 0, 0)
        self.spin_width = QSpinBox()
        self.spin_width.setRange(0, 20000)
        self.spin_width.setSpecialValueText("自动")
        self.spin_width.setValue(0)
        size_grid.addWidget(self.spin_width, 0, 1)
        width_unit = QLabel("px")
        width_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        width_unit.setFixedWidth(42)
        width_unit.setToolTip("像素单位，不可编辑")
        width_unit.setStyleSheet(
            "QLabel { color: #777; background: #f2f2f2; "
            "border: 1px solid #d9d9d9; border-radius: 5px; "
            "padding: 3px 7px; }"
        )
        size_grid.addWidget(width_unit, 0, 2)

        size_grid.addWidget(QLabel("高度"), 1, 0)
        self.spin_height = QSpinBox()
        self.spin_height.setRange(0, 20000)
        self.spin_height.setSpecialValueText("自动")
        self.spin_height.setValue(0)
        size_grid.addWidget(self.spin_height, 1, 1)
        height_unit = QLabel("px")
        height_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        height_unit.setFixedWidth(42)
        height_unit.setToolTip("像素单位，不可编辑")
        height_unit.setStyleSheet(
            "QLabel { color: #777; background: #f2f2f2; "
            "border: 1px solid #d9d9d9; border-radius: 5px; "
            "padding: 3px 7px; }"
        )
        size_grid.addWidget(height_unit, 1, 2)

        layout.addLayout(size_grid)
        size_hint = QLabel("选择图片后，会自动使用当前批次中出现次数最多的尺寸。")
        size_hint.setWordWrap(True)
        size_hint.setStyleSheet("color: #666;")
        layout.addWidget(size_hint)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        self.chk_limit = QCheckBox("限制文件大小")
        self.chk_limit.setChecked(True)
        layout.addWidget(self.chk_limit)

        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(10, 20480)  # KB，滑块覆盖 10KB~20MB
        self.size_slider.setValue(500)
        self.size_slider.valueChanged.connect(self.on_slider_changed)
        layout.addWidget(self.size_slider)

        input_row = QHBoxLayout()
        self.size_input = QDoubleSpinBox()
        self.size_input.setRange(1, 102400)
        self.size_input.setDecimals(0)
        self.size_input.setValue(500)
        self.size_input.setSingleStep(50)
        self.size_input.valueChanged.connect(self.on_size_input_changed)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["KB", "MB"])
        self.unit_combo.currentTextChanged.connect(self.on_unit_changed)
        input_row.addWidget(QLabel("最大"))
        input_row.addWidget(self.size_input, 1)
        input_row.addWidget(self.unit_combo)
        layout.addLayout(input_row)

        self.chk_target_size = QCheckBox("所有图片都尽量调整到这个目标大小")
        self.chk_target_size.setChecked(False)
        self.chk_target_size.setToolTip(
            "默认关闭：填写的是文件大小上限，只有超限图片才压缩。\n"
            "开启后：所有图片都会重新编码，并尽量接近填写的目标大小。"
        )
        self.chk_limit.toggled.connect(self.chk_target_size.setEnabled)
        layout.addWidget(self.chk_target_size)

        note = QLabel(
            "默认规则：这里填写的是文件大小上限。例如 500 KB 表示不超过 500 KB；原本 100 KB 的图片不会为了接近 500 KB 而重新压缩。只有勾选上面的“所有图片都尽量调整到这个目标大小”后，才会对全部图片尽量靠近目标值。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")
        layout.addWidget(note)
        layout.addStretch()
        return group

    def _build_output_group(self):
        group = QGroupBox("保存目录")
        layout = QHBoxLayout(group)
        self.lbl_save_dir = QLabel("选择图片后会自动设为图片所在目录（默认覆盖原图）")
        self.lbl_save_dir.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_save_dir.setStyleSheet("color: #555;")
        btn_choose = QPushButton("选择其他目录")
        btn_choose.clicked.connect(self.choose_save_dir)
        layout.addWidget(self.lbl_save_dir, 1)
        layout.addWidget(btn_choose)
        return group

    def select_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图片",
            "",
            "图片 (*.jpg *.jpeg *.png *.webp *.bmp)",
        )
        if files:
            self.add_images(files)

    def add_images(self, files):
        normalized = []
        seen = set(self.selected_files)
        ignored = 0
        for path in files:
            abs_path = os.path.abspath(path)
            if Path(abs_path).suffix.lower() not in SUPPORTED_EXTENSIONS or not os.path.isfile(abs_path):
                ignored += 1
                continue
            if abs_path not in seen:
                normalized.append(abs_path)
                seen.add(abs_path)

        if not normalized:
            if ignored:
                self.lbl_status.setText("没有可添加的受支持图片。")
            return

        self.selected_files.extend(normalized)
        self._refresh_table()
        self._update_default_target_size()

        # 按用户要求：每次新选择/拖入图片，都自动把保存目录定位到当前图片目录。
        # 多目录选择时以第一张新增图片所在目录为默认目录，用户仍可手动改。
        self.save_dir = os.path.dirname(normalized[0])
        self.lbl_save_dir.setText(safe_display_path(self.save_dir))

        dirs = {os.path.dirname(p) for p in self.selected_files}
        if len(dirs) > 1:
            self.lbl_status.setText(
                f"已选择 {len(self.selected_files)} 张图片；图片来自多个目录，默认保存到第一张图片所在目录。"
            )
        else:
            self.lbl_status.setText(
                f"已选择 {len(self.selected_files)} 张图片；默认原目录覆盖，文件名保持不变。"
            )

    def _refresh_table(self):
        self.table.setRowCount(0)
        for path in self.selected_files:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(os.path.basename(path))
            name_item.setData(Qt.ItemDataRole.UserRole, path)
            self.table.setItem(row, 0, name_item)

            try:
                width, height = read_oriented_size(path)
                dim = f"{width}×{height}"
                size_text = format_file_size(os.path.getsize(path))
            except Exception:
                dim = "无法读取"
                size_text = "-"
            self.table.setItem(row, 1, QTableWidgetItem(dim))
            self.table.setItem(row, 2, QTableWidgetItem(size_text))
            self.table.setItem(row, 3, QTableWidgetItem("-"))
            self.table.setItem(row, 4, QTableWidgetItem("待处理"))

    def _update_default_target_size(self):
        """按当前批次中出现次数最多的有效尺寸更新默认宽高。

        边界规则：
        - 损坏/无法读取的图片不参与统计；
        - 尺寸并列时，取当前选择顺序中最先出现的并列尺寸；
        - 没有任何可读尺寸时，不修改当前输入值。
        """
        sizes = []
        for path in self.selected_files:
            try:
                sizes.append(read_oriented_size(path))
            except Exception:
                continue
        if not sizes:
            return
        counts = Counter(sizes)
        max_count = max(counts.values())
        chosen = next(size for size in sizes if counts[size] == max_count)
        self.spin_width.setValue(chosen[0])
        self.spin_height.setValue(chosen[1])

    def clear_images(self):
        self.selected_files.clear()
        self.table.setRowCount(0)
        self.save_dir = ""
        self.spin_width.setValue(0)
        self.spin_height.setValue(0)
        self.lbl_save_dir.setText("选择图片后会自动设为图片所在目录（默认覆盖原图）")
        self.progress.setValue(0)
        self.lbl_status.setText("已清空，请重新选择图片。")

    def choose_save_dir(self):
        start = self.save_dir or os.path.expanduser("~")
        directory = QFileDialog.getExistingDirectory(self, "选择保存目录", start)
        if directory:
            self.save_dir = directory
            self.lbl_save_dir.setText(safe_display_path(directory))
            self.lbl_status.setText("已使用自定义保存目录；同名文件会直接覆盖。")

    def on_slider_changed(self, kb_value):
        if self._syncing_size_controls:
            return
        self.target_size_kb = float(kb_value)
        self._syncing_size_controls = True
        try:
            if self.unit_combo.currentText() == "KB":
                self.size_input.setValue(self.target_size_kb)
            else:
                self.size_input.setValue(self.target_size_kb / 1024)
        finally:
            self._syncing_size_controls = False

    def on_size_input_changed(self, value):
        if self._syncing_size_controls:
            return
        self.target_size_kb = (
            float(value) if self.unit_combo.currentText() == "KB" else float(value) * 1024
        )
        self._syncing_size_controls = True
        try:
            slider_value = int(round(self.target_size_kb))
            slider_value = max(
                self.size_slider.minimum(), min(self.size_slider.maximum(), slider_value)
            )
            self.size_slider.setValue(slider_value)
        finally:
            self._syncing_size_controls = False

    def on_unit_changed(self, unit):
        self._syncing_size_controls = True
        try:
            # 切换 KB/MB 只改变显示单位，不改变用户已经设定的实际大小。
            if unit == "KB":
                self.size_input.setRange(1, 102400)
                self.size_input.setDecimals(0)
                self.size_input.setSingleStep(50)
                self.size_input.setValue(self.target_size_kb)
            else:
                self.size_input.setRange(0.01, 100)
                self.size_input.setDecimals(2)
                self.size_input.setSingleStep(0.1)
                self.size_input.setValue(self.target_size_kb / 1024)
        finally:
            self._syncing_size_controls = False

    def get_max_bytes(self):
        """按界面当前输入值精确计算限制大小，避免滑块/输入框同步造成数值偏差。

        例如：1367 KB -> 1367 * 1024 bytes；1.5 MB -> 1.5 * 1024 * 1024 bytes。
        """
        value = float(self.size_input.value())
        if self.unit_combo.currentText() == "MB":
            return int(round(value * 1024 * 1024))
        return int(round(value * 1024))

    def start_convert(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.selected_files:
            QMessageBox.warning(self, "提示", "请先选择至少一张图片。")
            return
        if not self.save_dir:
            QMessageBox.warning(self, "提示", "请选择保存目录。")
            return
        if not self.chk_resize.isChecked() and not self.chk_limit.isChecked():
            QMessageBox.information(self, "提示", "请至少启用“修改图片尺寸”或“限制文件大小”中的一项。")
            return

        width = self.spin_width.value()
        height = self.spin_height.value()
        if self.chk_resize.isChecked() and (width <= 0 or height <= 0):
            QMessageBox.warning(
                self,
                "无法确定尺寸",
                "当前没有可用的默认图片尺寸，请先选择可读取的图片，或手动输入目标宽高。",
            )
            return
        if self.chk_resize.isChecked() and width * height > MAX_IMAGE_PIXELS_FOR_TOOL:
            QMessageBox.warning(self, "尺寸过大", "目标图片像素过大，为避免占用过多内存，请降低宽高。")
            return

        max_bytes = self.get_max_bytes()
        if self.chk_limit.isChecked() and max_bytes <= 0:
            QMessageBox.warning(self, "提示", "文件大小限制必须大于 0。")
            return

        # 多目录选择时若存在相同文件名，汇总到一个保存目录会互相覆盖。
        # 正常“同一文件夹批量处理”不会遇到此情况，这里仅做数据安全保护。
        basenames = [os.path.normcase(os.path.basename(p)) for p in self.selected_files]
        if len(basenames) != len(set(basenames)):
            QMessageBox.warning(
                self,
                "存在同名图片",
                "所选图片中存在来自不同位置但文件名相同的图片。\n"
                "为了避免它们在同一保存目录中互相覆盖，请分批处理。",
            )
            return

        # 第二次处理前重新读取当前文件信息；原地覆盖后，尺寸/大小以磁盘最新状态为准。
        self._refresh_table()

        # 明确提示原图覆盖，但不额外弹确认框打断批处理；页面本身已说明默认覆盖。
        self.btn_start.setEnabled(False)
        self.progress.setValue(0)
        for row in range(self.table.rowCount()):
            self.table.setItem(row, 3, QTableWidgetItem("-"))
            self.table.setItem(row, 4, QTableWidgetItem("等待处理"))

        self.worker = ImageConvertWorker(
            files=self.selected_files,
            save_dir=self.save_dir,
            resize_enabled=self.chk_resize.isChecked(),
            target_width=width,
            target_height=height,
            limit_enabled=self.chk_limit.isChecked(),
            max_bytes=max_bytes,
            target_size_mode=(
                self.chk_limit.isChecked() and self.chk_target_size.isChecked()
            ),
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.rowResult.connect(self.on_row_result)
        self.worker.summary.connect(self.on_summary)
        self.worker.fatalError.connect(self.on_fatal_error)
        self.worker.finished.connect(lambda: self.btn_start.setEnabled(True))
        self.worker.start()

    def on_progress(self, done, total, message):
        percent = int(done * 100 / total) if total else 0
        self.progress.setValue(percent)
        self.lbl_status.setText(message)

    def on_row_result(self, path, new_dim, new_bytes, status):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == path:
                self.table.setItem(row, 3, QTableWidgetItem(f"{new_dim} / {new_bytes}"))
                self.table.setItem(row, 4, QTableWidgetItem(status))
                break

    def on_summary(self, success, failed, output_dir):
        self.progress.setValue(100)
        self.lbl_status.setText(
            f"处理完成：成功 {success} 张，失败 {failed} 张。输出目录：{safe_display_path(output_dir)}"
        )
        if failed:
            QMessageBox.warning(
                self,
                "处理完成",
                f"成功 {success} 张，失败 {failed} 张。\n失败原因可在图片列表“状态”列查看。",
            )
        else:
            QMessageBox.information(self, "处理完成", f"全部 {success} 张图片处理完成。")


    def on_fatal_error(self, message):
        self.btn_start.setEnabled(True)
        self.lbl_status.setText(f"处理失败：{message}")
        QMessageBox.critical(self, "处理失败", message)

    def open_output_dir(self):
        if not self.save_dir or not os.path.isdir(self.save_dir):
            QMessageBox.warning(self, "提示", "当前没有可打开的输出目录。")
            return
        path = os.path.abspath(self.save_dir)
        try:
            if sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", path])
            elif os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            QMessageBox.warning(self, "打开失败", f"无法打开目录：{exc}")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(3000)
        super().closeEvent(event)
