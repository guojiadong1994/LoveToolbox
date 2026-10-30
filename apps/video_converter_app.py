"""LoveToolbox 独立视频转换模块：界面、转换线程和 FFmpeg 核心均在此文件。

使用：放入项目 apps/ 目录，在 main.py 中导入 VideoConverterApp。
本地需要 FFmpeg 和 FFprobe；打包 exe 时须包含二者。
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QCursor, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDoubleSpinBox,
    QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTabBar,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'}
QUALITY_CRF = {'高质量': 20, '标准': 23, '高压缩': 28}


class VideoError(Exception):
    """可直接展示给使用者的错误。"""


class VideoCancelled(VideoError):
    """用户取消。"""


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    duration: float
    fps: float
    has_audio: bool
    source_bytes: int


@dataclass(frozen=True)
class VideoOptions:
    resize: bool = True
    resize_mode: str = 'proportional'  # proportional=保持比例; exact=严格按指定宽高
    width: int = 1920
    height: int = 1080
    limit_size: bool = False
    max_bytes: int = 20 * 1024 * 1024
    quality: str = '标准'
    overwrite_mp4: bool = False  # 保留原字段名，语义为覆盖原文件（格式必须一致）
    output_format: str = 'same'   # same=输出容器与输入相同; mp4=统一转为 MP4
    output_dir: Optional[str] = None


def format_bytes(n: int) -> str:
    if n < 1024:
        return f'{n} B'
    if n < 1024 ** 2:
        return f'{n / 1024:.1f} KB'
    if n < 1024 ** 3:
        return f'{n / 1024 ** 2:.2f} MB'
    return f'{n / 1024 ** 3:.2f} GB'


def format_duration(seconds: float) -> str:
    """将 ffprobe 时长格式化为 01:23 / 01:02:03。"""
    if seconds <= 0:
        return '未知时长'
    total = max(1, round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f'{hours:02d}:{minutes:02d}:{secs:02d}' if hours else f'{minutes:02d}:{secs:02d}'


def find_executable(name: str) -> Optional[str]:
    """兼容源代码运行、exe 同目录、PyInstaller onefile 解压目录和 PATH。"""
    filename = name + ('.exe' if os.name == 'nt' else '')
    roots = []
    if getattr(sys, 'frozen', False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.extend([
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
    ])
    if getattr(sys, '_MEIPASS', None):
        roots.insert(0, Path(sys._MEIPASS))
    for root in roots:
        for candidate in (root / filename, root / 'ffmpeg' / filename,
                          root / 'vendor' / 'ffmpeg' / filename):
            if candidate.is_file():
                return str(candidate)
    return shutil.which(name)


def require_tools() -> tuple[str, str]:
    ffmpeg = find_executable('ffmpeg')
    ffprobe = find_executable('ffprobe')
    if not ffmpeg or not ffprobe:
        raise VideoError('未找到 FFmpeg / FFprobe。请使用包含 FFmpeg 的打包版本，'
                         '或将两个程序安装至系统 PATH。')
    return ffmpeg, ffprobe


def _startupinfo():
    if os.name != 'nt':
        return {}
    return {'creationflags': subprocess.CREATE_NO_WINDOW}


def _parse_float(val) -> float:
    try:
        f = float(val)
        return f if math.isfinite(f) and f > 0 else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def probe_video(src: str, ffprobe: Optional[str] = None,
                cancel_event: Optional[threading.Event] = None) -> VideoInfo:
    """读取视频元数据；传入 cancel_event 时支持快速终止扫描。"""
    ffprobe = ffprobe or require_tools()[1]
    cmd = [ffprobe, '-v', 'error', '-show_format', '-show_streams',
           '-of', 'json', src]
    process = None
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8', errors='replace',
                                   **_startupinfo())
        deadline = time.monotonic() + 40
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise VideoCancelled('视频信息读取已取消')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VideoError('读取视频信息超时')
            try:
                stdout, stderr = process.communicate(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    except OSError as exc:
        raise VideoError(f'无法启动 FFprobe：{exc}') from exc
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
    if process.returncode != 0:
        detail = (stderr or '').strip()[-280:]
        raise VideoError(f'无法读取视频信息：{detail or "可能是损坏或不受支持的文件"}')
    try:
        payload = json.loads(stdout)
    except (ValueError, TypeError) as exc:
        raise VideoError('FFprobe 返回的视频信息格式不正确') from exc
    streams = payload.get('streams') or []
    video = next((s for s in streams if s.get('codec_type') == 'video'
                  and not (s.get('disposition') or {}).get('attached_pic')), None)
    if not video:
        raise VideoError('文件中没有可转换的视频流')
    w, h = int(video.get('width') or 0), int(video.get('height') or 0)
    if w <= 0 or h <= 0:
        raise VideoError('无法获取有效的视频宽高')
    duration = _parse_float((payload.get('format') or {}).get('duration'))
    if not duration:
        duration = _parse_float(video.get('duration'))
    fps = 0.0
    ratio = video.get('avg_frame_rate') or video.get('r_frame_rate') or '0/1'
    if '/' in ratio:
        a, b = ratio.split('/', 1)
        denominator = _parse_float(b)
        if denominator:
            fps = _parse_float(a) / denominator
    else:
        fps = _parse_float(ratio)
    return VideoInfo(w, h, duration, fps,
                     any(s.get('codec_type') == 'audio' for s in streams),
                     os.stat(src).st_size)


def _safe_name(src: Path, directory: Path, suffix: str) -> Path:
    """按最终容器扩展名安全命名，不覆盖源文件或既有输出。"""
    base = src.stem + '_converted'
    candidate = directory / (base + suffix)
    index = 2
    while candidate.exists() or candidate.resolve() == src.resolve():
        candidate = directory / f'{base}_{index}{suffix}'
        index += 1
    return candidate


def _format_settings(src: Path, output_format: str) -> tuple[str, str, str, str]:
    """输出后缀、FFmpeg 容器、视频编码器、音频编码器。

    保留输入格式指的是保持文件容器类型，并执行真实的转码，不是仅修改扩展名。
    WebM 必须使用 VP9/Opus；AVI 使用 MPEG-4 Part 2/MP3；其他格式采用 H.264/AAC。
    """
    if output_format not in ('same', 'mp4'):
        raise VideoError('未知的输出格式')
    suffix = src.suffix.lower() if output_format == 'same' else '.mp4'
    if suffix == '.webm':
        return suffix, 'webm', 'libvpx-vp9', 'libopus'
    if suffix == '.avi':
        return suffix, 'avi', 'mpeg4', 'libmp3lame'
    if suffix == '.mkv':
        return suffix, 'matroska', 'libx264', 'aac'
    return suffix, 'mp4' if suffix in ('.mp4', '.m4v') else suffix[1:], 'libx264', 'aac'


def _video_encoder_args(codec: str, quality: str, video_bps: Optional[int] = None) -> list[str]:
    if codec == 'libx264':
        args = ['-c:v', codec, '-preset', 'medium', '-pix_fmt', 'yuv420p']
        return args + (['-b:v', str(video_bps)] if video_bps is not None
                       else ['-crf', str(QUALITY_CRF[quality])])
    if codec == 'libvpx-vp9':
        args = ['-c:v', codec, '-deadline', 'good', '-cpu-used', '3', '-pix_fmt', 'yuv420p']
        return args + (['-b:v', str(video_bps)] if video_bps is not None
                       else ['-crf', str(QUALITY_CRF[quality]), '-b:v', '0'])
    # 原 AVI 格式采用兼容性更好的 MPEG-4 Part 2；不支持 x264 的 CRF 参数。
    args = ['-c:v', 'mpeg4', '-pix_fmt', 'yuv420p']
    return args + (['-b:v', str(video_bps)] if video_bps is not None
                   else ['-q:v', str({'高质量': 3, '标准': 5, '高压缩': 9}[quality])])


def _audio_encoder_args(info: VideoInfo, codec: str, audio_rate: int) -> list[str]:
    if not info.has_audio:
        return ['-an']
    return ['-map', '0:a:0?', '-c:a', codec, '-b:a', str(audio_rate)]


def _muxer_args(muxer: str, stage: Path) -> list[str]:
    args = ['-movflags', '+faststart'] if muxer in ('mp4', 'mov') else []
    return args + ['-f', muxer, str(stage)]


def _filter_graph(opts: VideoOptions) -> str:
    # even dimensions are necessary for H.264 yuv420p. The default preserves size
    # for even-size sources and adds one pixel for odd-size sources.
    if not opts.resize:
        return 'scale=ceil(iw/2)*2:ceil(ih/2)*2:flags=lanczos,setsar=1'
    if opts.width < 2 or opts.height < 2:
        raise VideoError('目标宽高必须至少为 2 像素')
    if opts.resize_mode == 'exact':
        # H.264 yuv420p 要求宽高为偶数；固定尺寸不偷偷修正用户输入。
        if opts.width % 2 or opts.height % 2:
            raise VideoError('固定尺寸模式要求宽度、高度均为偶数（H.264 编码限制）')
        return f'scale=w={opts.width}:h={opts.height}:flags=lanczos,setsar=1'
    if opts.resize_mode != 'proportional':
        raise VideoError('未知的分辨率调整模式')
    w, h = opts.width // 2 * 2, opts.height // 2 * 2
    return (f'scale=w={w}:h={h}:force_original_aspect_ratio=decrease:'
            'force_divisible_by=2:flags=lanczos,setsar=1')


def _parse_progress_seconds(line: str) -> Optional[float]:
    if line.startswith('out_time_us=') or line.startswith('out_time_ms='):
        val = _parse_float(line.partition('=')[2].strip())
        return val / 1_000_000.0
    if line.startswith('out_time='):
        val = line.partition('=')[2].strip()
        parts = val.split(':')
        if len(parts) == 3:
            try:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            except ValueError:
                return None
    return None


class VideoConverter:
    """FFmpeg runner. A QThread may call run() and cancel() from the GUI thread."""

    def __init__(self, ffmpeg: str, ffprobe: str):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self._cancel = threading.Event()
        self._guard = threading.Lock()
        self._process: Optional[subprocess.Popen] = None

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self):
        self._cancel.set()
        with self._guard:
            process = self._process
        if process and process.poll() is None:
            try:
                process.terminate()
            except (ProcessLookupError, OSError):
                pass

    def _execute(self, args: list[str], seconds: float,
                 cb: Callable[[int, str], None], progress_from: int,
                 progress_to: int, label: str):
        if self.cancelled:
            raise VideoCancelled('已取消')
        command = [self.ffmpeg, '-hide_banner', '-nostdin', '-y', '-v', 'error',
                   '-progress', 'pipe:1', '-nostats'] + args
        process = None
        output_tail = []
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, bufsize=1,
                                       universal_newlines=True, encoding='utf-8',
                                       errors='replace', **_startupinfo())
            with self._guard:
                self._process = process
            if self.cancelled:
                process.terminate()
            assert process.stdout is not None
            for line in process.stdout:
                if self.cancelled:
                    break
                line = line.strip()
                elapsed = _parse_progress_seconds(line)
                if elapsed is not None and seconds > 0:
                    fraction = min(max(elapsed / seconds, 0), 0.99)
                    value = progress_from + round((progress_to - progress_from) * fraction)
                    cb(value, label)
                elif line.startswith('progress=end'):
                    cb(progress_to, label)
                elif line and not re.match(r'^\w+=', line):
                    output_tail.append(line)
                    output_tail = output_tail[-8:]
            if self.cancelled:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise VideoCancelled('已取消')
            code = process.wait()
            if code:
                desc = '；'.join(output_tail)[-420:]
                raise VideoError(f'FFmpeg 转换失败（代码 {code}）：{desc or "详情不可用"}')
        except OSError as exc:
            raise VideoError(f'无法启动 FFmpeg：{exc}') from exc
        finally:
            with self._guard:
                if self._process is process:
                    self._process = None
            if process and process.stdout:
                process.stdout.close()

    def convert(self, source: str, opts: VideoOptions,
                cb: Callable[[int, str], None]) -> tuple[str, VideoInfo, int]:
        if self.cancelled:
            raise VideoCancelled('已取消')
        src = Path(source).resolve()
        if not src.is_file():
            raise VideoError('源视频不存在')
        if src.suffix.lower() not in VIDEO_EXTENSIONS:
            raise VideoError('不支持该视频格式')
        if opts.quality not in QUALITY_CRF:
            raise VideoError('未知的画质档位')
        suffix, muxer, video_codec, audio_codec = _format_settings(src, opts.output_format)
        if opts.overwrite_mp4 and suffix != src.suffix.lower():
            raise VideoError('输出格式与输入格式不一致，不能覆盖原视频；请关闭覆盖或选择保留原格式')
        cb(0, '正在读取视频信息')
        info = probe_video(str(src), self.ffprobe)
        if self.cancelled:
            raise VideoCancelled('已取消')
        if opts.limit_size and info.duration <= 0:
            raise VideoError('无法获取视频时长，不能准确限制文件体积')
        if opts.limit_size and opts.max_bytes < 100 * 1024:
            raise VideoError('视频大小上限不能小于 100 KB')
        directory = src.parent if opts.overwrite_mp4 else (
            Path(opts.output_dir).resolve() if opts.output_dir else src.parent)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise VideoError(f'无法创建保存目录：{exc}') from exc
        final_path = src if opts.overwrite_mp4 else _safe_name(src, directory, suffix)
        filter_string = _filter_graph(opts)
        audio_rate = 128_000
        if opts.limit_size:
            target_bps = opts.max_bytes * 8 / info.duration
            audio_rate = (64_000 if target_bps < 400_000 else
                          96_000 if target_bps < 800_000 else 128_000)
            if not info.has_audio:
                audio_rate = 0
        # 临时文件与最终文件同格式、同目录：校验成功后再原子替换。
        fd, stage_name = tempfile.mkstemp(prefix='.video_convert_', suffix=suffix,
                                          dir=str(directory))
        os.close(fd)
        stage = Path(stage_name)
        try:
            with tempfile.TemporaryDirectory(prefix='video_two_pass_') as passdir:
                logprefix = os.path.join(passdir, 'pass')
                tries = 3 if opts.limit_size else 1
                for attempt in range(tries):
                    if self.cancelled:
                        raise VideoCancelled('已取消')
                    common = ['-i', str(src), '-map', '0:v:0', '-vf', filter_string,
                              '-sn', '-dn']
                    mux_args = _muxer_args(muxer, stage)
                    if opts.limit_size:
                        budget_factor = [0.92, 0.83, 0.72][attempt]
                        video_bps = int(opts.max_bytes * 8 * budget_factor / info.duration - audio_rate)
                        if video_bps < 80_000:
                            raise VideoError('目标体积过小，无法在当前视频时长下可靠转换；请提高大小上限')
                        encoder = _video_encoder_args(video_codec, opts.quality, video_bps)
                        args = common + encoder + ['-passlogfile', logprefix]
                        cb(0, f'双遍压缩 {attempt+1}/{tries}：分析画面')
                        self._execute(args + ['-pass', '1', '-an', '-f', 'null', os.devnull],
                                      info.duration, cb, 0, 47, '正在分析画面（第一遍）')
                        cb(48, '正在编码（第二遍）')
                        self._execute(args + ['-pass', '2'] +
                                      _audio_encoder_args(info, audio_codec, audio_rate) + mux_args,
                                      info.duration, cb, 48, 97, '正在编码（第二遍）')
                    else:
                        args = (common + _video_encoder_args(video_codec, opts.quality) +
                                _audio_encoder_args(info, audio_codec, audio_rate) + mux_args)
                        self._execute(args, info.duration, cb, 0, 97, '正在转换')
                    if self.cancelled:
                        raise VideoCancelled('已取消')
                    if not stage.exists() or stage.stat().st_size <= 0:
                        raise VideoError('输出文件为空')
                    if not opts.limit_size or stage.stat().st_size <= opts.max_bytes:
                        break
                    if attempt == tries - 1:
                        raise VideoError('多次压缩后仍超出大小上限；请调整分辨率或增大文件大小限制')
            cb(98, '正在验证输出文件')
            result_info = probe_video(str(stage), self.ffprobe)
            if result_info.duration <= 0 or result_info.source_bytes <= 0:
                raise VideoError('输出文件验证失败：时长或大小异常')
            if info.has_audio and not result_info.has_audio:
                raise VideoError('输出文件验证失败：原有音轨未保留')
            if info.duration > 1 and result_info.duration < info.duration * 0.94:
                raise VideoError('输出文件验证失败：时长明显短于原视频')
            if opts.limit_size and result_info.source_bytes > opts.max_bytes:
                raise VideoError('输出文件大于设置的限制')
            if self.cancelled:
                raise VideoCancelled('已取消')
            if not opts.overwrite_mp4 and final_path.exists():
                final_path = _safe_name(src, directory, suffix)
            os.replace(str(stage), str(final_path))
            cb(100, '完成')
            return str(final_path), info, final_path.stat().st_size
        finally:
            try:
                stage.unlink(missing_ok=True)
            except OSError:
                pass


class VideoDropTable(QTableWidget):
    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
            u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in VIDEO_EXTENSIONS
            for u in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in VIDEO_EXTENSIONS]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class VideoProbeWorker(QThread):
    """后台读取视频尺寸和时长，避免大量视频拖入时界面卡顿。"""
    infoReady = pyqtSignal(str, str, int, int)
    infoError = pyqtSignal(str, str)

    def __init__(self, files: list[str], parent=None):
        super().__init__(parent)
        self.files = files[:]
        self._stop = threading.Event()

    def cancel(self):
        self._stop.set()

    def run(self):
        ffprobe = find_executable('ffprobe')
        if not ffprobe:
            for path in self.files:
                if self._stop.is_set():
                    break
                self.infoError.emit(path, '未找到 FFprobe，无法读取视频信息')
            return
        for path in self.files:
            if self._stop.is_set():
                break
            try:
                info = probe_video(path, ffprobe, self._stop)
                self.infoReady.emit(
                    path, f'{info.width}×{info.height} / {format_duration(info.duration)}',
                    info.width, info.height
                )
            except VideoCancelled:
                return
            except (VideoError, OSError, ValueError) as exc:
                self.infoError.emit(path, str(exc))
            except Exception as exc:
                self.infoError.emit(path, f'视频信息读取异常：{exc}')


class VideoConvertWorker(QThread):
    fileStarted = pyqtSignal(str, int, int)
    fileProgress = pyqtSignal(str, int, str, int)
    fileDone = pyqtSignal(str, str, str, str)
    fileFailed = pyqtSignal(str, str)
    completed = pyqtSignal(int, int, bool)

    def __init__(self, files: list[str], opts: VideoOptions, parent=None):
        super().__init__(parent)
        self.files = files[:]
        self.opts = opts
        self._cancel_requested = False
        self._runner: Optional[VideoConverter] = None

    def cancel(self):
        self._cancel_requested = True
        if self._runner is not None:
            self._runner.cancel()

    def run(self):
        success, failure = 0, 0
        try:
            ffmpeg, ffprobe = require_tools()
            self._runner = VideoConverter(ffmpeg, ffprobe)
        except VideoError as exc:
            for path in self.files:
                self.fileFailed.emit(path, str(exc))
            self.completed.emit(0, len(self.files), False)
            return
        if self._cancel_requested:
            self._runner.cancel()
        total = len(self.files)
        for n, path in enumerate(self.files):
            if self._cancel_requested or self._runner.cancelled:
                break
            self.fileStarted.emit(path, n + 1, total)

            def on_progress(pct: int, msg: str, current_path=path, index=n):
                overall = round((index + pct / 100) / total * 100)
                self.fileProgress.emit(current_path, pct, msg, overall)

            try:
                output, info, size = self._runner.convert(path, self.opts, on_progress)
                description = f'{info.width}×{info.height}  |  {info.duration:.1f}s'
                self.fileDone.emit(path, description, format_bytes(size), output)
                success += 1
            except VideoCancelled:
                break
            except (VideoError, OSError, ValueError) as exc:
                failure += 1
                self.fileFailed.emit(path, str(exc))
            except Exception as exc:
                failure += 1
                self.fileFailed.emit(path, f'处理异常：{exc}')
        self.completed.emit(success, failure, self._cancel_requested or self._runner.cancelled)


class VideoConverterApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('视频转换')
        self.resize(1120, 770)
        self.selected_files: list[str] = []
        self.row_by_file: dict[str, int] = {}
        self.worker: Optional[VideoConvertWorker] = None
        self._probe_worker: Optional[VideoProbeWorker] = None
        self._pending_probes: list[str] = []
        self._closing_when_probes = False
        self._closing_when_done = False
        self._centered_once = False
        # 宽高联动以首个成功识别的视频为参考；未选择视频时暂按 16:9。
        self._ratio_reference = (16, 9)
        self._ratio_reference_path: Optional[str] = None
        self._dimensions_touched = False
        self._last_edited_axis = 'width'
        self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        if self._centered_once:
            return
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen:
            frame = self.frameGeometry()
            frame.moveCenter(screen.availableGeometry().center())
            self.move(frame.topLeft())
        self._centered_once = True

    def _build_ui(self):
        self.setStyleSheet('''
            QWidget { font-size: 14px; }
            QGroupBox { font-size: 15px; font-weight: bold; border: 1px solid #d9d9d9;
                        border-radius: 10px; margin-top: 10px; padding-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
            QPushButton { min-height: 34px; padding: 4px 12px; border: 1px solid #cfcfcf;
                          border-radius: 7px; background: white; }
            QPushButton:hover { background: #f5f5f5; }
            QPushButton#primaryButton { background: #2e7d32; color: white; border: none;
                                        font-weight: bold; min-height: 42px; }
            QPushButton#primaryButton:hover { background: #256a29; }
            QTableWidget { border: 1px solid #ddd; border-radius: 8px; }
            QSpinBox, QDoubleSpinBox, QComboBox { min-height: 32px; }
            QTabBar#resizeModeTabs::tab {
                padding: 8px 12px; min-width: 96px;
                border: 1px solid #c9cdd2;
                background: #f4f5f7; color: #444;
            }
            QTabBar#resizeModeTabs::tab:first {
                border-top-left-radius: 7px; border-bottom-left-radius: 7px;
            }
            QTabBar#resizeModeTabs::tab:last {
                border-top-right-radius: 7px; border-bottom-right-radius: 7px;
                border-left: 0;
            }
            QTabBar#resizeModeTabs::tab:selected {
                background: #e3f0ff; color: #125b9a;
                border-color: #74a7df; font-weight: bold;
            }
            QTabBar#qualityModeTabs::tab {
                padding: 8px 4px; min-width: 42px;
                border: 1px solid #c9cdd2;
                background: #f4f5f7; color: #444;
            }
            QTabBar#qualityModeTabs::tab:first {
                border-top-left-radius: 7px; border-bottom-left-radius: 7px;
            }
            QTabBar#qualityModeTabs::tab:last {
                border-top-right-radius: 7px; border-bottom-right-radius: 7px;
                border-left: 0;
            }
            QTabBar#qualityModeTabs::tab:middle { border-left: 0; }
            QTabBar#qualityModeTabs::tab:selected {
                background: #e3f0ff; color: #125b9a;
                border-color: #74a7df; font-weight: bold;
            }
            QPushButton#overwriteButton:checked {
                background: #e3f0ff; color: #125b9a;
                border: 1px solid #74a7df; font-weight: bold;
            }
            QPushButton#overwriteButton:checked:hover { background: #d6eaff; }
        ''')
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)
        title = QLabel('🎞️ 视频转换')
        font = title.font()
        font.setPointSize(20)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)
        mid = QHBoxLayout()
        mid.setSpacing(14)
        mid.addWidget(self._file_group(), 3)
        # 右侧设置区独立滚动：窗口缩小或系统缩放较大时不再裁切说明文字。
        settings_scroll = QScrollArea()
        settings_scroll.setObjectName('settingsScroll')
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        settings_scroll.setMinimumWidth(310)
        settings_scroll.setWidget(self._option_group())
        mid.addWidget(settings_scroll, 2)
        root.addLayout(mid, 1)
        root.addWidget(self._output_group())
        buttons = QHBoxLayout()
        self.btn_start = QPushButton('开始转换')
        self.btn_start.setObjectName('primaryButton')
        self.btn_start.clicked.connect(self.start_convert)
        self.btn_stop = QPushButton('取消任务')
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.cancel_convert)
        self.btn_open = QPushButton('打开输出目录')
        self.btn_open.clicked.connect(self.open_output_dir)
        buttons.addStretch()
        buttons.addWidget(self.btn_start)
        buttons.addWidget(self.btn_stop)
        buttons.addWidget(self.btn_open)
        root.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)
        self.lbl_status = QLabel('请选择或拖入视频。默认覆盖原文件；正式转换前会再次确认。')
        self.lbl_status.setStyleSheet('color: #666;')
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

    def _file_group(self):
        group = QGroupBox('选择视频（支持多选和拖拽）')
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self.btn_add = QPushButton('添加视频')
        self.btn_add.clicked.connect(self.select_files)
        self.btn_clear = QPushButton('清空列表')
        self.btn_clear.clicked.connect(self.clear_files)
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_clear)
        row.addStretch()
        layout.addLayout(row)
        hint = QLabel('支持 MP4、MOV、AVI、MKV、WEBM、M4V；可将多个文件拖入下方列表。')
        hint.setStyleSheet('color: #777;')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = VideoDropTable()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['文件名', '原分辨率 / 时长', '原大小', '输出大小', '状态'])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in (1, 2, 3):
            head.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.filesDropped.connect(self.add_files)
        layout.addWidget(self.table, 1)
        return group

    @staticmethod
    def _add_section_divider(layout):
        """用一条浅灰横线分隔视频转换设置的不同功能区。"""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setStyleSheet('QFrame { color: #d7dbe0; }')
        layout.addSpacing(5)
        layout.addWidget(line)
        layout.addSpacing(5)

    def _option_group(self):
        group = QGroupBox('转换设置')
        layout = QVBoxLayout(group)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 22, 14, 14)

        # 1. 分辨率始终启用，不再提供勾选开关；默认等比例缩放。
        resize_mode_row = QHBoxLayout()
        resize_mode_row.addWidget(QLabel('调整方式'))
        self.tabs_resize_mode = QTabBar()
        self.tabs_resize_mode.setObjectName('resizeModeTabs')
        self.tabs_resize_mode.setDrawBase(False)
        self.tabs_resize_mode.setExpanding(True)
        self.tabs_resize_mode.addTab('等比例缩放')
        self.tabs_resize_mode.addTab('固定尺寸')
        self.tabs_resize_mode.setCurrentIndex(0)
        resize_mode_row.addWidget(self.tabs_resize_mode, 1)
        layout.addLayout(resize_mode_row)

        dimensions = QGridLayout()
        dimensions.setHorizontalSpacing(10)
        dimensions.setVerticalSpacing(8)
        # 输入框使用同一弹性列，右侧 px 固定宽度；缩放窗口时宽、高保持齐整。
        dimensions.setColumnStretch(0, 0)
        dimensions.setColumnStretch(1, 1)
        dimensions.setColumnStretch(2, 0)
        self.lbl_width = QLabel('目标宽度')
        dimensions.addWidget(self.lbl_width, 0, 0)
        self.spin_width = QSpinBox()
        self.spin_width.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.spin_width.setRange(2, 16384)
        self.spin_width.setSingleStep(2)
        # 完成一次输入后再联动，避免键入 1280 时逐位改写另一输入框。
        self.spin_width.setKeyboardTracking(False)
        self.spin_width.setValue(1920)
        dimensions.addWidget(self.spin_width, 0, 1)
        dimensions.addWidget(QLabel('px'), 0, 2)
        self.lbl_height = QLabel('目标高度')
        dimensions.addWidget(self.lbl_height, 1, 0)
        self.spin_height = QSpinBox()
        self.spin_height.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.spin_height.setRange(2, 16384)
        self.spin_height.setSingleStep(2)
        self.spin_height.setKeyboardTracking(False)
        self.spin_height.setValue(1080)
        dimensions.addWidget(self.spin_height, 1, 1)
        dimensions.addWidget(QLabel('px'), 1, 2)
        layout.addLayout(dimensions)
        self.resize_note = QLabel()
        self.resize_note.setWordWrap(True)
        self.resize_note.setStyleSheet('color: #777;')
        layout.addWidget(self.resize_note)

        self.tabs_resize_mode.currentChanged.connect(self._resize_mode_changed)
        self.spin_width.valueChanged.connect(self._width_changed)
        self.spin_height.valueChanged.connect(self._height_changed)
        # 手工输入时 QSpinBox 关闭键盘追踪，只靠 valueChanged 无法实时联动。
        # 额外监听文本编辑，手输过程中只更新另一轴，不改正在输入的文本/光标。
        self.spin_width.lineEdit().textEdited.connect(self._width_text_edited)
        self.spin_height.lineEdit().textEdited.connect(self._height_text_edited)
        # 输入提交时原有 valueChanged 会做偶数取整，不另行抢先处理 editingFinished。
        self._update_resize_controls()

        # 2. 输出画质：三种画质预设 + 自定义文件大小上限。
        # 对用户仅展示一个“输出画质”入口；自定义沿用已有的双遍体积限制算法。
        self._add_section_divider(layout)
        layout.addWidget(QLabel('输出画质'))
        self.tabs_quality = QTabBar()
        self.tabs_quality.setObjectName('qualityModeTabs')
        self.tabs_quality.setDrawBase(False)
        self.tabs_quality.setExpanding(True)
        for name in ('高质量', '标准', '高压缩', '自定义'):
            self.tabs_quality.addTab(name)
        self.tabs_quality.setCurrentIndex(1)  # 默认“标准”
        layout.addWidget(self.tabs_quality)

        # 只有选择“自定义”时才出现，避免默认界面中多余的控制项。
        self.custom_quality_row = QWidget()
        custom_row_layout = QHBoxLayout(self.custom_quality_row)
        custom_row_layout.setContentsMargins(0, 2, 0, 2)
        custom_row_layout.setSpacing(8)
        custom_row_layout.addWidget(QLabel('不超过'))
        # 数值和单位分开显示：右侧可切换 KB / MB，默认 KB（20480 KB = 20 MB）。
        self.spin_size = QDoubleSpinBox()
        self.spin_size.setDecimals(0)
        self.spin_size.setRange(1, 100_000_000)
        self.spin_size.setSingleStep(100)
        self.spin_size.setValue(20 * 1024)
        self.spin_size.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        custom_row_layout.addWidget(self.spin_size, 1)

        self.cmb_size_unit = QComboBox()
        self.cmb_size_unit.addItem('KB', 1024)
        self.cmb_size_unit.addItem('MB', 1024 * 1024)
        self.cmb_size_unit.setCurrentIndex(0)
        self.cmb_size_unit.setFixedWidth(82)
        self.cmb_size_unit.setToolTip('切换单位时自动换算，保持实际大小限制不变。')
        self._size_unit_bytes = 1024
        self.cmb_size_unit.currentIndexChanged.connect(self._size_unit_changed)
        custom_row_layout.addWidget(self.cmb_size_unit)
        layout.addWidget(self.custom_quality_row)
        self.quality_note = QLabel()
        self.quality_note.setWordWrap(True)
        self.quality_note.setStyleSheet('color: #777;')
        layout.addWidget(self.quality_note)
        self.tabs_quality.currentChanged.connect(self._quality_mode_changed)
        self._quality_mode_changed()

        # 3. 输出格式仍保留原格式（默认）/ MP4 两种选择。
        self._add_section_divider(layout)
        format_row = QHBoxLayout()
        format_row.setSpacing(12)
        format_row.addWidget(QLabel('输出格式'))
        self.cmb_format = QComboBox()
        self.cmb_format.addItem('原格式（默认）', 'same')
        self.cmb_format.addItem('MP4', 'mp4')
        self.cmb_format.setToolTip('原格式：各视频保留原文件格式并重新编码；MP4：统一转换为 MP4。')
        self.cmb_format.setCurrentIndex(0)
        self.cmb_format.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        format_row.addWidget(self.cmb_format, 1)
        layout.addLayout(format_row)
        format_note = QLabel('原格式会重新编码；选择 MP4 则统一转换为 MP4。')
        format_note.setWordWrap(True)
        format_note.setStyleSheet('color: #777;')
        layout.addWidget(format_note)
        layout.addStretch()
        return group

    def _quality_mode_changed(self, *_):
        """选自定义时显示大小上限；其他档位仅用恒定质量编码。"""
        custom = self.tabs_quality.currentIndex() == 3
        self.custom_quality_row.setVisible(custom)
        if custom:
            self.quality_note.setText(
                '自定义：限制输出文件不超过指定大小，采用双遍编码，耗时更长；'
                '目标太小可能无法完成转换。'
            )
        else:
            self.quality_note.setText(
                '画质档位控制压缩程度：高质量更清晰，高压缩通常体积更小；'
                '实际文件大小不固定。'
            )

    def _size_unit_changed(self, *_):
        """切换 KB / MB 时同步换算输入值，不意外改变视频目标大小。"""
        self.spin_size.interpretText()  # 先提交尚在编辑中的手输数值
        target_bytes = self.spin_size.value() * self._size_unit_bytes
        new_multiplier = int(self.cmb_size_unit.currentData())
        if new_multiplier == self._size_unit_bytes:
            return
        blocked = self.spin_size.blockSignals(True)
        try:
            if new_multiplier == 1024:
                self.spin_size.setDecimals(0)
                self.spin_size.setRange(1, 100_000_000)
                self.spin_size.setSingleStep(100)
            else:
                self.spin_size.setDecimals(3)
                self.spin_size.setRange(0.001, 100_000)
                self.spin_size.setSingleStep(1)
            self.spin_size.setValue(target_bytes / new_multiplier)
            self._size_unit_bytes = new_multiplier
        finally:
            self.spin_size.blockSignals(blocked)

    @staticmethod
    def _even_dimension(value: float) -> int:
        """H.264/yuv420p 需要偶数宽高，比例联动时取最接近的偶数。"""
        return min(16384, max(2, int(value / 2 + 0.5) * 2))

    def _set_dimensions(self, width: int, height: int):
        """阻断关联输入框的信号，防止 widthChanged 和 heightChanged 相互递归。"""
        was_width_blocked = self.spin_width.blockSignals(True)
        was_height_blocked = self.spin_height.blockSignals(True)
        try:
            self.spin_width.setValue(self._even_dimension(width))
            self.spin_height.setValue(self._even_dimension(height))
        finally:
            self.spin_width.blockSignals(was_width_blocked)
            self.spin_height.blockSignals(was_height_blocked)

    def _resize_mode(self) -> str:
        return 'exact' if self.tabs_resize_mode.currentIndex() == 1 else 'proportional'

    def _resize_mode_changed(self, *_):
        if self._resize_mode() == 'proportional':
            self._sync_dimension(self._last_edited_axis)
        self._update_resize_controls()

    def _width_changed(self, value: int):
        self._dimensions_touched = True
        self._last_edited_axis = 'width'
        if self._resize_mode() == 'proportional':
            self._sync_dimension('width')

    def _height_changed(self, value: int):
        self._dimensions_touched = True
        self._last_edited_axis = 'height'
        if self._resize_mode() == 'proportional':
            self._sync_dimension('height')

    def _width_text_edited(self, text: str):
        self._sync_from_typed_text('width', text)

    def _height_text_edited(self, text: str):
        self._sync_from_typed_text('height', text)

    def _sync_from_typed_text(self, axis: str, text: str):
        """手动输入时实时更新另一轴，不动当前文本，避免输入到一半跳光标。"""
        self._dimensions_touched = True
        self._last_edited_axis = axis
        if self._resize_mode() != 'proportional':
            return
        text = text.strip()
        if not text.isdecimal():
            return
        value = int(text)
        if value < 2 or value > 16384:
            return
        ref_width, ref_height = self._ratio_reference
        if axis == 'width':
            other = self._even_dimension(value * ref_height / ref_width)
            widget = self.spin_height
        else:
            other = self._even_dimension(value * ref_width / ref_height)
            widget = self.spin_width
        previous = widget.blockSignals(True)
        try:
            widget.setValue(other)
        finally:
            widget.blockSignals(previous)

    def _sync_dimension(self, changed_axis: str):
        """完成输入/点箭头后归一到合法偶数，并按照参考视频比例联动。"""
        if self._resize_mode() != 'proportional':
            return
        ref_width, ref_height = self._ratio_reference
        if changed_axis == 'height':
            height = self._even_dimension(self.spin_height.value())
            width = self._even_dimension(height * ref_width / ref_height)
        else:
            width = self._even_dimension(self.spin_width.value())
            height = self._even_dimension(width * ref_height / ref_width)
        self._set_dimensions(width, height)

    def _update_resize_controls(self, *_):
        exact = self._resize_mode() == 'exact'
        self.lbl_width.setText('固定宽度' if exact else '目标宽度')
        self.lbl_height.setText('固定高度' if exact else '目标高度')
        if exact:
            self.resize_note.setText(
                '固定尺寸：输出严格等于填写的宽×高，不保持原比例，画面可能拉伸；宽高须为偶数。'
            )
        else:
            reference = (f'参考：{Path(self._ratio_reference_path).name} '
                         f'（{self._ratio_reference[0]}×{self._ratio_reference[1]}）'
                         if self._ratio_reference_path else '未添加视频时先按 16:9 联动。')
            self.resize_note.setText(
                '等比例：手动输入或点击箭头，宽高自动联动；'
                '批量时各视频保留自身比例。' + reference
            )

    def _output_group(self):
        group = QGroupBox('保存位置')
        layout = QHBoxLayout(group)
        self.lbl_output = QLabel('默认：保存到每个原视频所在目录，新文件添加 _converted')
        self.lbl_output.setWordWrap(True)
        layout.addWidget(self.lbl_output, 1)
        # 放在选择目录左侧，默认选中；只有经过用户确认才会实际替换源文件。
        self.chk_overwrite = QPushButton('✓ 覆盖原视频')
        self.chk_overwrite.setObjectName('overwriteButton')
        self.chk_overwrite.setCheckable(True)
        self.chk_overwrite.setChecked(True)
        self.chk_overwrite.setToolTip('点击切换：成功转换并验证后覆盖原文件；不同格式不能互相覆盖。')
        self.chk_overwrite.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.chk_overwrite)
        self.btn_folder = QPushButton('选择目录')
        self.btn_folder.clicked.connect(self.choose_output_dir)
        self.btn_original_dir = QPushButton('恢复默认')
        self.btn_original_dir.clicked.connect(self.reset_output_dir)
        layout.addWidget(self.btn_folder)
        layout.addWidget(self.btn_original_dir)
        self.custom_output_dir: Optional[str] = None
        self.chk_overwrite.toggled.connect(self._toggle_overwrite)
        self._toggle_overwrite(self.chk_overwrite.isChecked())
        return group

    def _toggle_overwrite(self, enabled):
        self.chk_overwrite.setText('✓ 覆盖原视频' if enabled else '覆盖原视频')
        self.btn_folder.setEnabled(not enabled)
        self.btn_original_dir.setEnabled(not enabled)
        if enabled:
            self.lbl_output.setText('覆盖模式：成功验证后替换原视频；输出格式必须与原视频一致。')
        else:
            self._refresh_output_label()

    def _refresh_output_label(self):
        self.lbl_output.setText(self.custom_output_dir or
                                '默认：保存到每个原视频所在目录，新文件添加 _converted')

    def select_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, '选择视频', '', '视频 (*.mp4 *.mov *.avi *.mkv *.webm *.m4v);;所有文件 (*)')
        self.add_files(paths)

    def add_files(self, paths):
        if self.worker is not None and self.worker.isRunning():
            return
        count = 0
        for path in paths:
            full = os.path.normcase(os.path.abspath(path))
            if full in self.row_by_file or not Path(full).is_file():
                continue
            if Path(full).suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            self.row_by_file[full] = len(self.selected_files)
            self.selected_files.append(full)
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, value in enumerate((Path(full).name, '识别中…',
                                          format_bytes(os.stat(full).st_size), '—', '待处理')):
                item = QTableWidgetItem(value)
                item.setToolTip(full if col == 0 else '')
                self.table.setItem(row, col, item)
            self._pending_probes.append(full)
            count += 1
        if count:
            self.lbl_status.setText(f'已选择 {len(self.selected_files)} 个视频，正在读取分辨率和时长…')
            self._start_probe_worker()

    def _start_probe_worker(self):
        if self._probe_worker is not None or not self._pending_probes:
            return
        files = self._pending_probes[:]
        self._pending_probes.clear()
        self._probe_worker = VideoProbeWorker(files, self)
        self._probe_worker.infoReady.connect(self._probe_ready)
        self._probe_worker.infoError.connect(self._probe_error)
        self._probe_worker.finished.connect(self._probe_finished)
        self._probe_worker.start()

    def _probe_ready(self, path: str, description: str, width: int, height: int):
        row = self.row_by_file.get(path)
        if row is None:
            return
        self.table.item(row, 1).setText(description)
        self.table.item(row, 1).setToolTip(f'原视频信息：{description}')
        # 以第一个成功读取的视频作为宽高联动参照。
        if self._ratio_reference_path is None:
            self._ratio_reference_path = path
            self._ratio_reference = (width, height)
            if self._resize_mode() == 'proportional':
                if self._dimensions_touched:
                    self._sync_dimension(self._last_edited_axis)
                else:
                    # 第一次导入时默认沿用源视频分辨率，不凭空放大或缩小。
                    self._set_dimensions(width, height)
            self._update_resize_controls()

    def _probe_error(self, path: str, error: str):
        row = self.row_by_file.get(path)
        if row is not None:
            self.table.item(row, 1).setText('识别失败')
            self.table.item(row, 1).setToolTip(error)

    def _probe_finished(self):
        if self._probe_worker is not None:
            self._probe_worker.deleteLater()
            self._probe_worker = None
        if self._closing_when_probes:
            QTimer.singleShot(0, self.close)
        else:
            self._start_probe_worker()

    def clear_files(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self._pending_probes.clear()
        if self._probe_worker is not None:
            self._probe_worker.cancel()
        self.selected_files.clear()
        self.row_by_file.clear()
        self._ratio_reference = (16, 9)
        self._ratio_reference_path = None
        self._dimensions_touched = False
        self._last_edited_axis = 'width'
        self._set_dimensions(1920, 1080)
        self._update_resize_controls()
        self.table.setRowCount(0)
        self.progress.setValue(0)
        self.lbl_status.setText('请选择或拖入视频。')

    def choose_output_dir(self):
        folder = QFileDialog.getExistingDirectory(self, '选择输出文件夹',
                                                  self.custom_output_dir or str(Path.home()))
        if folder:
            self.custom_output_dir = folder
            self._refresh_output_label()

    def reset_output_dir(self):
        self.custom_output_dir = None
        self._refresh_output_label()

    def start_convert(self):
        if self.worker is not None:
            return
        if not self.selected_files:
            QMessageBox.information(self, '提示', '请先选择需要转换的视频。')
            return
        try:
            require_tools()
        except VideoError as exc:
            QMessageBox.warning(self, '缺少依赖', str(exc))
            return
        if (self.chk_overwrite.isChecked() and
                self.cmb_format.currentData() == 'mp4' and
                any(Path(f).suffix.lower() != '.mp4' for f in self.selected_files)):
            QMessageBox.warning(self, '无法覆盖',
                '当前包含非 MP4 视频。统一输出 MP4 时不能覆盖不同格式的原文件，'
                '请取消“覆盖原视频”或选择“与原视频格式一致”。')
            return
        # 确保编辑中的手输数字先提交，再执行参数校验。
        self.spin_width.interpretText()
        self.spin_height.interpretText()
        self.spin_size.interpretText()
        opts = VideoOptions(
            resize=True,  # 分辨率调整始终生效
            resize_mode=self._resize_mode(),
            width=self.spin_width.value(),
            height=self.spin_height.value(),
            limit_size=self.tabs_quality.currentIndex() == 3,
            max_bytes=round(self.spin_size.value() * self._size_unit_bytes),
            quality=(self.tabs_quality.tabText(self.tabs_quality.currentIndex())
                     if self.tabs_quality.currentIndex() != 3 else '标准'),
            overwrite_mp4=self.chk_overwrite.isChecked(),
            output_format=self.cmb_format.currentData(),
            output_dir=self.custom_output_dir,
        )
        if opts.resize and opts.resize_mode == 'exact' and (
            opts.width % 2 != 0 or opts.height % 2 != 0
        ):
            QMessageBox.warning(self, '固定尺寸不合法',
                '固定尺寸模式下，宽度和高度必须为偶数（例如 1280×720）。')
            return
        if opts.overwrite_mp4:
            answer = QMessageBox.question(
                self, '确认覆盖原视频',
                '当前选择了“覆盖原视频”。转换成功后原文件将被替换，不能自动撤销。是否继续？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.worker = VideoConvertWorker(self.selected_files, opts, self)
        self.worker.fileStarted.connect(self._file_started)
        self.worker.fileProgress.connect(self._file_progress)
        self.worker.fileDone.connect(self._file_done)
        self.worker.fileFailed.connect(self._file_failed)
        self.worker.completed.connect(self._finished_summary)
        self.worker.finished.connect(self._worker_finished)
        for row in range(self.table.rowCount()):
            self.table.item(row, 3).setText('—')
            self.table.item(row, 4).setText('待处理')
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_add.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.table.setAcceptDrops(False)
        self.lbl_status.setText('正在转换，请勿移动源视频。')
        self.worker.start()

    def _file_started(self, path, current, total):
        row = self.row_by_file.get(path)
        if row is not None:
            self.table.item(row, 4).setText('准备转换')
        self.lbl_status.setText(f'正在处理第 {current}/{total} 个：{Path(path).name}')

    def _file_progress(self, path, pct, desc, total_pct):
        row = self.row_by_file.get(path)
        if row is not None:
            self.table.item(row, 4).setText(f'{desc} {pct}%')
        self.progress.setValue(total_pct)

    def _file_done(self, path, detail, size, output):
        row = self.row_by_file.get(path)
        if row is not None:
            self.table.item(row, 1).setText(detail)
            self.table.item(row, 3).setText(size)
            self.table.item(row, 4).setText('成功')
            self.table.item(row, 4).setToolTip(output)

    def _file_failed(self, path, error):
        row = self.row_by_file.get(path)
        if row is not None:
            self.table.item(row, 4).setText('失败：' + error)
            self.table.item(row, 4).setToolTip(error)

    def _finished_summary(self, success, failure, cancelled):
        if cancelled:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 4)
                if item and item.text() not in ('成功',) and not item.text().startswith('失败：'):
                    item.setText('已取消')
        else:
            self.progress.setValue(100)
        status = '已取消' if cancelled else '全部处理结束'
        self.lbl_status.setText(f'{status}：成功 {success} 个，失败 {failure} 个。')

    def _worker_finished(self):
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_add.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.table.setAcceptDrops(True)
        if self._closing_when_done:
            QTimer.singleShot(0, self.close)

    def cancel_convert(self):
        if self.worker is not None:
            self.btn_stop.setEnabled(False)
            self.lbl_status.setText('正在停止转换并清理临时文件……')
            self.worker.cancel()

    def open_output_dir(self):
        if self.chk_overwrite.isChecked() and self.selected_files:
            folder = str(Path(self.selected_files[0]).parent)
        elif self.custom_output_dir:
            folder = self.custom_output_dir
        elif self.selected_files:
            folder = str(Path(self.selected_files[0]).parent)
        else:
            QMessageBox.information(self, '提示', '请先选择视频或输出目录。')
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
            QMessageBox.warning(self, '提示', f'无法打开目录：{folder}')

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            if not self._closing_when_done:
                reply = QMessageBox.question(
                    self, '转换仍在进行', '关闭窗口将取消当前转换，确定要关闭吗？',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._closing_when_done = True
                    self.cancel_convert()
            event.ignore()
            return
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._closing_when_probes = True
            self._pending_probes.clear()
            self._probe_worker.cancel()
            event.ignore()
            return
        event.accept()
