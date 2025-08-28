import os
import rawpy
import cv2
import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading
import subprocess
import tempfile
from typing import List, Dict, Tuple, Optional
import exifread

#start
class ConverterThread(QThread):
    log_signal = pyqtSignal(list)
    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(object, str)
    pause_signal = pyqtSignal()
    resume_signal = pyqtSignal()
    
    def __init__(self, folders: List[Tuple[Path, bool, bool, object]], scale_factor: int, video_format: str, 
                 num_threads: int, font_size: float, video_resolution: str, video_codec: str):
        super().__init__()
        self.folders = folders
        self.scale_factor = scale_factor
        self.video_format = video_format
        self.num_threads = num_threads
        self.font_size = font_size
        self.video_resolution = video_resolution
        self.video_codec = video_codec
        self._is_running = True
        self._is_paused = False
        self.log_mutex = threading.Lock()
        self.pause_condition = threading.Condition()

    def run(self):
        with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            futures = {}
            for folder_data in self.folders:
                folder_path, convert_jpg, create_video, tree_item = folder_data
                if convert_jpg or create_video:
                    futures[executor.submit(self.process_folder, folder_path, convert_jpg, create_video, tree_item)] = folder_path
            
            for i, future in enumerate(as_completed(futures)):
                if not self._is_running:
                    break
                
                # Проверяем паузу
                with self.pause_condition:
                    while self._is_paused and self._is_running:
                        self.pause_condition.wait()
                
                try:
                    future.result()
                    self.progress_signal.emit(int((i + 1) / len(futures) * 100))
                except Exception as e:
                    self.log_messages([(f"Ошибка обработки папки: {e}", "red")])

    def stop(self):
        self._is_running = False
        with self.pause_condition:
            self.pause_condition.notify_all()

    def pause(self):
        self._is_paused = True
        self.pause_signal.emit()

    def resume(self):
        self._is_paused = False
        with self.pause_condition:
            self.pause_condition.notify_all()
        self.resume_signal.emit()

    def log_messages(self, messages):
        """Потокобезопасная отправка нескольких сообщений"""
        with self.log_mutex:
            self.log_signal.emit(messages)

    def process_folder(self, raw_folder: Path, convert_jpg: bool, create_video: bool, tree_item):
        try:
            self.log_messages([(f"Начинаем обработку папки: {raw_folder}", "blue")])
            jpg_folder = raw_folder.parent / "JPG"
            
            if convert_jpg:
                jpg_folder.mkdir(exist_ok=True)
                raw_files = list(raw_folder.glob("*.[aA][rR][wW]")) + \
                           list(raw_folder.glob("*.[cC][rR]2")) + \
                           list(raw_folder.glob("*.[dD][nN][gG]"))
                
                total = len(raw_files)
                if total == 0:
                    self.log_messages([("RAW файлы не найдены", "red")])
                    self.status_signal.emit(tree_item, "RAW файлы не найдены")
                    return
                    
                processed_count = 0
                self.status_signal.emit(tree_item, f"Конвертация JPG: 0/{total}")
                
                file_threads = min(total, max(1, os.cpu_count() // 2))
                
                with ThreadPoolExecutor(max_workers=file_threads) as executor:
                    futures = []
                    for raw_path in raw_files:
                        if not self._is_running:
                            return
                        
                        # Проверяем паузу
                        with self.pause_condition:
                            while self._is_paused and self._is_running:
                                self.pause_condition.wait()
                        
                        jpg_path = jpg_folder / (raw_path.stem + ".jpg")
                        future = executor.submit(self.convert_raw_to_jpg, raw_path, jpg_path)
                        futures.append(future)
                    
                    for future in as_completed(futures):
                        if not self._is_running:
                            return
                        
                        # Проверяем паузу
                        with self.pause_condition:
                            while self._is_paused and self._is_running:
                                self.pause_condition.wait()
                        
                        try:
                            future.result()
                            processed_count += 1
                            self.status_signal.emit(tree_item, f"Конвертация JPG: {processed_count}/{total}")
                        except Exception as e:
                            self.log_messages([(f"Ошибка конвертации файла: {e}", "red")])
            else:
                self.status_signal.emit(tree_item, "Пропуск JPG")

            if create_video and self._is_running:
                # Проверяем паузу
                with self.pause_condition:
                    while self._is_paused and self._is_running:
                        self.pause_condition.wait()
                
                self.status_signal.emit(tree_item, "Создание видео...")
                self.create_video(jpg_folder, raw_folder.parent)
                if self._is_running:
                    self.status_signal.emit(tree_item, "Видео готово")
            else:
                self.status_signal.emit(tree_item, "Пропуск видео")
                
        except Exception as e:
            self.log_messages([(f"Ошибка обработки папки {raw_folder}: {str(e)}", "red")])
            self.status_signal.emit(tree_item, f"Ошибка: {str(e)}")
            raise
        finally:
            import gc
            gc.collect()

    def convert_raw_to_jpg(self, raw_path: Path, jpg_path: Path):
        logs = []
        try:
            if jpg_path.exists():
                logs.append((f"Перезаписываем существующий JPG: {jpg_path}", "blue"))
            else:
                logs.append((f"Конвертируем {raw_path} в {jpg_path}", "blue"))
            
            with rawpy.imread(str(raw_path)) as raw:
                rgb = raw.postprocess(
                    output_bps=8,
                    no_auto_bright=True,
                    use_camera_wb=True,
                    half_size=True,
                )
                
                h, w = rgb.shape[:2]
                logs.append((f"Исходное разрешение: {w}x{h}", "blue"))

                new_h, new_w = h // self.scale_factor, w // self.scale_factor
                logs.append((f"Конечное разрешение: {new_w}x{new_h} (уменьшено в {self.scale_factor} раз)", "blue"))

                resized = cv2.resize(rgb, (new_w, new_h))
                
                success = cv2.imwrite(str(jpg_path), cv2.cvtColor(resized, cv2.COLOR_RGB2BGR))
                
                if success:
                    file_size_mb = jpg_path.stat().st_size / (1024 * 1024)
                    logs.append((
                        f"Успешно конвертирован: {raw_path} -> {jpg_path} "
                        f"(размер файла: {file_size_mb:.1f} МБ)", "green"
                    ))
                else:
                    logs.append((f"Ошибка сохранения JPG: {jpg_path}", "red"))
                
                self.log_messages(logs)
                    
        except Exception as e:
            error_msg = f"Ошибка конвертации {raw_path}: {e}"
            logs.append((error_msg, "red"))
            self.log_messages(logs)
            raise
        finally:
            import gc
            gc.collect()

    def create_video(self, jpg_folder: Path, output_dir: Path):
        images = sorted(jpg_folder.glob("*.jpg"))
        if not images:
            self.log_messages([(f"Не найдено JPG файлов в папке {jpg_folder}", "red")])
            return

        self.log_messages([(f"Начинаем создание видео из {len(images)} кадров", "blue")])
        
        if self.video_resolution == "HD (1280x720)":
            target_width, target_height = 1280, 720
        elif self.video_resolution == "Full HD (1920x1080)":
            target_width, target_height = 1920, 1080
        elif self.video_resolution == "4K (3840x2160)":
            target_width, target_height = 3840, 2160
        else:
            max_width, max_height = 0, 0
            for img_path in images:
                frame = cv2.imread(str(img_path))
                if frame is not None:
                    h, w = frame.shape[:2]
                    max_width = max(max_width, w)
                    max_height = max(max_height, h)
            target_width, target_height = max_width, max_height
        
        self.log_messages([(f"Целевое разрешение видео: {target_width}x{target_height}", "blue")])
        
        video_name = output_dir.name
        video_path = output_dir / f"{video_name}.{self.video_format}"
        
        if video_path.exists():
            self.log_messages([(f"Видео уже существует: {video_path}", "blue")])
            self.log_messages([(f"Перезаписываем существующее видео", "blue")])
        
        temp_video_path = output_dir / f"tmp_{video_name}.{self.video_format}"
        self.log_messages([(f"Создаем временный файл: {temp_video_path}", "blue")])
        
        if self.video_codec == "h264":
            fourcc = cv2.VideoWriter_fourcc(*'avc1')
        else:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        
        self.log_messages([(f"Используем кодек: {self.video_codec} ({fourcc})", "blue")])
        
        out = cv2.VideoWriter(str(temp_video_path), fourcc, 30.0, (target_width, target_height))
        
        if not out.isOpened():
            self.log_messages([(f"Ошибка: не удалось создать видеофайл {temp_video_path}", "red")])
            if self.video_codec == "h264":
                fallback_codec = "mp4v"
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            else:
                fallback_codec = "h264"
                fourcc = cv2.VideoWriter_fourcc(*'avc1')
                
            self.log_messages([(f"Пробуем альтернативный кодек: {fallback_codec}", "blue")])
            out = cv2.VideoWriter(str(temp_video_path), fourcc, 30.0, (target_width, target_height))
            if not out.isOpened():
                self.log_messages([(f"Ошибка: не удалось создать видеофайл даже с кодеком {fallback_codec}", "red")])
                return

        success_count = 0
        for i, img_path in enumerate(images):
            if not self._is_running:
                out.release()
                if temp_video_path.exists():
                    self.log_messages([(f"Удаляем временный файл после остановки: {temp_video_path}", "blue")])
                    temp_video_path.unlink()
                return
                
            # Проверяем паузу
            with self.pause_condition:
                while self._is_paused and self._is_running:
                    self.pause_condition.wait()
            
            frame = cv2.imread(str(img_path))
            if frame is None:
                self.log_messages([(f"Не удалось прочитать кадр: {img_path}", "red")])
                continue
                
            h, w = frame.shape[:2]
            
            scale = min(target_width / w, target_height / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            
            resized_frame = cv2.resize(frame, (new_w, new_h))
            
            background = np.zeros((target_height, target_width, 3), dtype=np.uint8)
            
            x_offset = (target_width - new_w) // 2
            y_offset = (target_height - new_h) // 2
            background[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized_frame
            
            text = str(img_path)
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = self.font_size
            thickness = 2
            (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
            
            padding = 10
            overlay = background.copy()
            cv2.rectangle(
                overlay, 
                (5, target_height - text_height - 2*padding), 
                (text_width + 2*padding, target_height), 
                (0, 0, 0), 
                -1
            )
            
            alpha = 0.6
            background = cv2.addWeighted(overlay, alpha, background, 1 - alpha, 0)
            
            cv2.putText(
                background, 
                text, 
                (padding, target_height-padding), 
                font, 
                font_scale, 
                (255, 255, 255), 
                thickness, 
                cv2.LINE_AA
            )
            
            try:
                out.write(background)
                success_count += 1
                if (i + 1) % 10 == 0:
                    self.log_messages([(f"Обработан кадр {i+1}/{len(images)}: {img_path}", "blue")])
            except Exception as e:
                self.log_messages([(f"Ошибка записи кадра {i+1}/{len(images)}: {e}", "red")])
        
        out.release()
        
        if temp_video_path.exists() and temp_video_path.stat().st_size > 0:
            self.log_messages([(f"Временный файл создан успешно, размер: {temp_video_path.stat().st_size} байт", "green")])
            
            if video_path.exists():
                self.log_messages([(f"Удаляем существующий файл: {video_path}", "blue")])
                video_path.unlink()
                
            self.log_messages([(f"Переименовываем временный файл в: {video_path}", "blue")])
            temp_video_path.rename(video_path)
            self.log_messages([(f"Видео успешно создано: {video_path} ({success_count}/{len(images)} кадров)", "green")])
        else:
            self.log_messages([(f"Ошибка: временный файл не создан или имеет нулевой размер", "red")])
            if temp_video_path.exists():
                self.log_messages([(f"Временный файл сохранен для диагностики: {temp_video_path}", "blue")])

class TreeWidgetItem(QtWidgets.QTreeWidgetItem):
    def __init__(self, path, parent=None, display_path=None, is_root=False):
        super().__init__(parent)
        self.path = path
        self.is_root = is_root
        display_text = display_path if display_path else str(path)
        self.setText(0, display_text)
        
        if is_root:
            self.setCheckState(1, Qt.Unchecked)
            self.setCheckState(2, Qt.Unchecked)
        else:
            self.setCheckState(1, Qt.Unchecked)
            self.setCheckState(2, Qt.Unchecked)

    def setData(self, column, role, value):
        old_state = self.checkState(column) if role == Qt.CheckStateRole else None
        
        super().setData(column, role, value)
        
        if self.is_root and role == Qt.CheckStateRole and column in [1, 2]:
            new_state = self.checkState(column)
            self.apply_to_children(column, new_state)
    
    def apply_to_children(self, column, state):
        for i in range(self.childCount()):
            child = self.child(i)
            child.setCheckState(column, state)

class CustomFileDialog(QtWidgets.QFileDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        self.setFileMode(QtWidgets.QFileDialog.Directory)
        self.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        self.tree = self.findChild(QtWidgets.QTreeView)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        
    def selectedFiles(self):
        files = super().selectedFiles()
        return files

class MainWindow(QtWidgets.QMainWindow):
    log_message_signal = QtCore.pyqtSignal(list)
    update_progress_signal = QtCore.pyqtSignal(int)
    status_signal = QtCore.pyqtSignal(object, str)
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RAW to Video Converter")
        self.setGeometry(100, 100, 1200, 800)
        
        self.log_mutex = QtCore.QMutex()
        
        self.scale_factor = 2
        self.video_format = 'mp4'
        self.num_threads = os.cpu_count()
        self.font_size = 0.8
        self.video_resolution = "Full HD (1920x1080)"
        self.video_codec = "mp4v"
        self.added_folders = set()
        
        self.setup_ui()
        
        self.log_message_signal.connect(
            self._log_messages,
            QtCore.Qt.QueuedConnection
        )
        self.update_progress_signal.connect(
            self.progress.setValue,
            QtCore.Qt.QueuedConnection
        )
        self.status_signal.connect(
            self.update_status,
            QtCore.Qt.QueuedConnection
        )

    def setup_ui(self):
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout(central_widget)

        control_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(control_layout)

        self.add_folder_btn = QtWidgets.QPushButton("Добавить папки")
        self.add_folder_btn.clicked.connect(self.add_folders)
        control_layout.addWidget(self.add_folder_btn)

        self.remove_folder_btn = QtWidgets.QPushButton("Удалить выбранные")
        self.remove_folder_btn.clicked.connect(self.remove_folders)
        control_layout.addWidget(self.remove_folder_btn)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Папки для обработки", "Конвертировать JPG", "Создать видео", "Статус"])
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        
        self.tree.setColumnWidth(0, 500)
        self.tree.setColumnWidth(1, 120)
        self.tree.setColumnWidth(2, 120)
        self.tree.setColumnWidth(3, 150)
        
        layout.addWidget(self.tree)

        selection_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(selection_layout)

        self.select_all_btn = QtWidgets.QPushButton("Выделить всё")
        self.select_all_btn.clicked.connect(self.select_all)
        selection_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QtWidgets.QPushButton("Снять все выделения")
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        selection_layout.addWidget(self.deselect_all_btn)

        first_row_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(first_row_layout)

        first_row_layout.addWidget(QtWidgets.QLabel("Коэффициент уменьшения:"))
        self.scale_combo = QtWidgets.QComboBox()
        self.scale_combo.addItems(["2", "4", "8", "16"])
        first_row_layout.addWidget(self.scale_combo)

        first_row_layout.addWidget(QtWidgets.QLabel("Размер шрифта:"))
        self.font_spin = QtWidgets.QDoubleSpinBox()
        self.font_spin.setRange(0.5, 2.0)
        self.font_spin.setSingleStep(0.1)
        self.font_spin.setValue(self.font_size)
        first_row_layout.addWidget(self.font_spin)

        first_row_layout.addWidget(QtWidgets.QLabel("Количество потоков:"))
        self.threads_spin = QtWidgets.QSpinBox()
        self.threads_spin.setRange(1, 32)
        self.threads_spin.setValue(4)
        first_row_layout.addWidget(self.threads_spin)

        second_row_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(second_row_layout)

        second_row_layout.addWidget(QtWidgets.QLabel("Формат видео:"))
        self.format_combo = QtWidgets.QComboBox()
        self.format_combo.addItems(["mp4", "mov"])
        second_row_layout.addWidget(self.format_combo)

        second_row_layout.addWidget(QtWidgets.QLabel("Кодек видео:"))
        self.codec_combo = QtWidgets.QComboBox()
        self.codec_combo.addItems(["mp4v", "h264"])
        self.codec_combo.setCurrentText("mp4v")
        second_row_layout.addWidget(self.codec_combo)

        second_row_layout.addWidget(QtWidgets.QLabel("Разрешение видео:"))
        self.resolution_combo = QtWidgets.QComboBox()
        self.resolution_combo.addItems(["Original", "HD (1280x720)", "Full HD (1920x1080)", "4K (3840x2160)"])
        self.resolution_combo.setCurrentText("Full HD (1920x1080)")
        second_row_layout.addWidget(self.resolution_combo)

        # Кнопки управления обработкой в одну строку
        button_layout = QtWidgets.QHBoxLayout()
        layout.addLayout(button_layout)

        self.start_btn = QtWidgets.QPushButton("Запуск")
        self.start_btn.clicked.connect(self.start_processing)
        button_layout.addWidget(self.start_btn)

        self.pause_btn = QtWidgets.QPushButton("Пауза")
        self.pause_btn.clicked.connect(self.pause_processing)
        self.pause_btn.setEnabled(False)
        button_layout.addWidget(self.pause_btn)

        self.stop_btn = QtWidgets.QPushButton("Остановить")
        self.stop_btn.clicked.connect(self.stop_processing)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.stop_btn)

        # Лог
        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        # Прогресс бар в самом низу - растягиваем на всю ширину
        self.progress = QtWidgets.QProgressBar()
        
        # Устанавливаем политику размера для растягивания по горизонтали
        size_policy = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Expanding,  # Горизонтальная политика
            QtWidgets.QSizePolicy.Fixed       # Вертикальная политика
        )
        self.progress.setSizePolicy(size_policy)
        
        # Устанавливаем минимальную ширину, чтобы прогресс-бар не был слишком узким
        self.progress.setMinimumWidth(200)

        layout.addWidget(self.progress)

    def select_all(self):
        for i in range(self.tree.topLevelItemCount()):
            root_item = self.tree.topLevelItem(i)
            root_item.setCheckState(1, Qt.Checked)
            root_item.setCheckState(2, Qt.Checked)

    def deselect_all(self):
        for i in range(self.tree.topLevelItemCount()):
            root_item = self.tree.topLevelItem(i)
            root_item.setCheckState(1, Qt.Unchecked)
            root_item.setCheckState(2, Qt.Unchecked)

    def add_folders(self):
        dialog = CustomFileDialog(self, "Выберите папки с RAW")
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            folders = dialog.selectedFiles()
            for folder in folders:
                folder = os.path.abspath(folder)
                if folder not in self.added_folders:
                    self.scan_raw_folders(Path(folder))
                    self.added_folders.add(folder)

    def scan_raw_folders(self, folder: Path):
        root_item = TreeWidgetItem(folder, display_path=folder.name, is_root=True)
        self.tree.addTopLevelItem(root_item)
        
        raw_folders_found = 0
        for root, dirs, files in os.walk(folder):
            if "RAW" in dirs or "raw" in dirs:
                raw_dir = "RAW" if "RAW" in dirs else "raw"
                raw_folder = Path(root) / raw_dir
                
                try:
                    relative_path = raw_folder.relative_to(folder)
                except ValueError:
                    relative_path = raw_folder
                
                raw_item = TreeWidgetItem(raw_folder, root_item, str(relative_path))
                root_item.addChild(raw_item)
                
                jpg_folder = Path(root) / "JPG"
                jpg_exists = jpg_folder.exists()
                
                video_name = Path(root).name
                video_path_mp4 = Path(root) / f"{video_name}.mp4"
                video_path_mov = Path(root) / f"{video_name}.mov"
                video_exists = video_path_mp4.exists() or video_path_mov.exists()
                
                if jpg_exists:
                    raw_files = list(raw_folder.glob("*.[aA][rR][wW]")) + \
                               list(raw_folder.glob("*.[cC][rR]2")) + \
                               list(raw_folder.glob("*.[dD][nN][gG]"))
                    jpg_files = list(jpg_folder.glob("*.jpg"))
                    
                    if len(raw_files) == len(jpg_files):
                        raw_item.setCheckState(1, Qt.Unchecked)
                        raw_item.setText(3, "JPG готовы")
                    else:
                        raw_item.setCheckState(1, Qt.Checked)
                        raw_item.setText(3, "JPG неполные")
                else:
                    raw_item.setCheckState(1, Qt.Checked)
                    raw_item.setText(3, "Нет JPG")
                
                if video_exists:
                    raw_item.setCheckState(2, Qt.Unchecked)
                    if raw_item.text(3):
                        raw_item.setText(3, raw_item.text(3) + ", видео есть")
                    else:
                        raw_item.setText(3, "Видео есть")
                else:
                    raw_item.setCheckState(2, Qt.Checked)
                    if raw_item.text(3):
                        raw_item.setText(3, raw_item.text(3) + ", нет видео")
                    else:
                        raw_item.setText(3, "Нет видео")
                
                raw_folders_found += 1
        
        root_item.setExpanded(True)
        
        if raw_folders_found == 0:
            root_item.setText(3, "Папки RAW не найдены")

    def remove_folders(self):
        selected_items = self.tree.selectedItems()
        for item in selected_items:
            if item.parent() is None:
                index = self.tree.indexOfTopLevelItem(item)
                self.tree.takeTopLevelItem(index)
                if hasattr(item, 'path'):
                    self.added_folders.discard(str(item.path))
            else:
                parent = item.parent()
                parent.removeChild(item)
                if parent.childCount() == 0:
                    index = self.tree.indexOfTopLevelItem(parent)
                    self.tree.takeTopLevelItem(index)
                    if hasattr(parent, 'path'):
                        self.added_folders.discard(str(parent.path))

    def start_processing(self):
        # Очищаем логи
        self.log.clear()
        
        selected_folders = []
        for i in range(self.tree.topLevelItemCount()):
            root_item = self.tree.topLevelItem(i)
            for j in range(root_item.childCount()):
                raw_item = root_item.child(j)
                convert_jpg = raw_item.checkState(1) == Qt.Checked
                create_video = raw_item.checkState(2) == Qt.Checked
                
                if convert_jpg or create_video:
                    selected_folders.append((raw_item.path, convert_jpg, create_video, raw_item))

        if not selected_folders:
            self.log_message([("Не выбрано ни одной папки для обработки", "red")])
            return

        self.scale_factor = int(self.scale_combo.currentText())
        self.video_format = self.format_combo.currentText()
        self.num_threads = self.threads_spin.value()
        self.font_size = self.font_spin.value()
        self.video_resolution = self.resolution_combo.currentText()
        self.video_codec = self.codec_combo.currentText()

        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)

        self.thread = ConverterThread(selected_folders, self.scale_factor, self.video_format, 
                                     self.num_threads, self.font_size, self.video_resolution, self.video_codec)
        self.thread.log_signal.connect(self.log_message)
        self.thread.progress_signal.connect(self.progress.setValue)
        self.thread.status_signal.connect(self.update_status)
        self.thread.finished.connect(self.on_processing_finished)
        self.thread.start()

    def pause_processing(self):
        if hasattr(self, 'thread') and self.thread.isRunning():
            if self.pause_btn.text() == "Пауза":
                self.thread.pause()
                self.pause_btn.setText("Продолжить")
                self.log_message([("Обработка приостановлена", "blue")])
            else:
                self.thread.resume()
                self.pause_btn.setText("Пауза")
                self.log_message([("Обработка продолжена", "blue")])

    def stop_processing(self):
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait()
            self.log_message([("Обработка остановлена пользователем", "blue")])

    def on_processing_finished(self):
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setText("Пауза")
        self.log_message([("Обработка завершена", "blue")])

    def _log_messages(self, messages: list):
        """Слот для обработки списка сообщений лога"""
        self.log_mutex.lock()
        try:
            for message, color in messages:
                self.log.setTextColor(QtGui.QColor(color))
                self.log.append(message)
            self.log.verticalScrollBar().setValue(
                self.log.verticalScrollBar().maximum()
            )
        finally:
            self.log_mutex.unlock()

    def log_message(self, messages: list):
        """Отправка списка сообщений через сигнал"""
        self.log_message_signal.emit(messages)
    
    def update_status(self, tree_item, status_text):
        tree_item.setText(3, status_text)

def resize_keeping_aspect(image, scale_factor):
    original_height, original_width = image.shape[:2]
    new_width = int(original_width / scale_factor)
    new_height = int(original_height / scale_factor)
    resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
    return resized

if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    app.exec_()