import os
import sys
import shutil
import hashlib
import exifread
import pickle
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QLineEdit, QTextEdit, QCheckBox, QFileDialog,
                             QProgressBar, QGroupBox, QMessageBox, QSpinBox, QComboBox, 
                             QFrame, QGridLayout) 
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QTextCursor, QColor

# ============================================================================
#   ГЛОБАЛЬНЫЕ НАСТРОЙКИ ИНТЕРФЕЙСА (UI CONFIG)
#   Меняйте размеры и отступы здесь
# ============================================================================
UI_CONFIG = {
    # --- Размеры окна ---
    "WINDOW_WIDTH": 600,
    "WINDOW_HEIGHT": 850,
    
    # --- Шрифты (в px) ---
    "FONT_MAIN": 10,           # Основной текст
    "FONT_HEADER": 10,         # Заголовки групп
    "FONT_BTN": 10,            # Текст на больших кнопках
    "FONT_CONSOLE": 10,        # Текст в логах
    
    # --- Отступы и интервалы ---
    "MARGIN_MAIN": 5,         # Отступ от края окна
    "SPACING_GLOBAL": 5,      # Расстояние между группами настроек
    "SPACING_INSIDE": 5,      # Расстояние между элементами внутри групп
    
    # --- Размеры элементов ---
    "BTN_HEIGHT_LARGE": 20,    # Высота кнопок "Запустить" и "Стоп"
    "BTN_HEIGHT_SMALL": 20,    # Высота кнопок "Обзор"
    "BTN_WIDTH_SMALL": 90,     # Ширина кнопок "Обзор"
    "INPUT_HEIGHT": 12,        # Высота полей ввода
    "PROGRESS_HEIGHT": 5,     # Толщина прогресс-бара
    
    # --- Скругления (Border Radius) ---
    "RADIUS_CARD": 2,         # Скругление групп-карточек
    "RADIUS_BTN": 2,           # Скругление кнопок
    "RADIUS_INPUT": 2,         # Скругление полей ввода
    
    # --- Цвета (можно менять тему здесь) ---
    "COLOR_BG": "#EEEEEE",           # Фон окна
    "COLOR_CARD_BG": "#FFFFFFFF",      # Фон карточек
    "COLOR_ACCENT": "#1877F2",       # Основной синий цвет
    "COLOR_ACCENT_HOVER": "#166FE5", # Синий при наведении
    "COLOR_DANGER": "#D32F2F",       # Красный цвет ошибок/отмены
    "COLOR_TEXT": "#1C1E21",         # Основной цвет текста
    "COLOR_BORDER": "#C4C4C4"        # Цвет рамок
}

# Константы логов
LOG_DEBUG = 0
LOG_INFO = 1
LOG_WARNING = 2
LOG_ERROR = 3

class PhotoOrganizerThread(QThread):
    """Поток для организации фотографий без блокировки GUI"""
    log_signal = pyqtSignal(str, str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)
    metadata_progress_signal = pyqtSignal(int)
    
    def __init__(self, source_root, exported_root, output_root, 
                 use_suffix, suffix_text, check_without_suffix, 
                 compare_metadata, max_workers, buffer_size_kb,
                 max_retries, retry_delay, source_extensions,
                 log_level):
        super().__init__()
        self.source_root = source_root
        self.exported_root = exported_root
        self.output_root = output_root
        self.use_suffix = use_suffix
        self.suffix_text = suffix_text
        self.check_without_suffix = check_without_suffix
        self.compare_metadata_flag = compare_metadata
        self.max_workers = max_workers
        self.buffer_size = buffer_size_kb * 1024
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.source_extensions = source_extensions
        self.log_level = log_level
        self.canceled = False
        
        source_root_hash = hashlib.md5(source_root.encode()).hexdigest()[:8]
        self.cache_dir = os.path.join(self.output_root, f".metadata_cache_{source_root_hash}")
        self.exif_cache = {}
        
    def emit_log(self, message, color, level):
        if level >= self.log_level:
            self.log_signal.emit(message, color)

    def run(self):
        try:
            self.organize_photos()
            self.finished_signal.emit(True, "Операция завершена успешно!")
        except Exception as e:
            self.finished_signal.emit(False, f"Ошибка: {str(e)}")
    
    def cancel(self):
        self.canceled = True
        self.emit_log("Операция отменена пользователем", UI_CONFIG["COLOR_DANGER"], LOG_WARNING)
    
    def extract_main_name(self, filename):
        for suffix in ['-1', '-2', '-3', '-4', '-5', '_1', '_2', '_3', '_4', '_5']:
            if filename.endswith(suffix):
                return filename[:-len(suffix)]
        return filename
    
    def get_exif_data_fast(self, image_path):
        if image_path in self.exif_cache:
            return self.exif_cache[image_path]
            
        retries = 0
        delay = self.retry_delay
        
        while retries < self.max_retries:
            try:
                with open(image_path, 'rb') as f:
                    if any(image_path.lower().endswith(ext) for ext in ['.cr2', '.nef', '.arw', '.dng']):
                        data = f.read(262144)
                    else:
                        data = f.read(65536)
                    
                    exif_start = data.find(b'\xFF\xE1')
                    if exif_start != -1:
                        f.seek(exif_start + 4)
                        tags = exifread.process_file(f, details=False)
                    else:
                        f.seek(0)
                        tags = exifread.process_file(f, details=False, stop_tag='DateTimeOriginal')
                    
                    required_tags = ['EXIF DateTimeOriginal', 'Image DateTime', 'DateTime']
                    result = {}
                    for tag in required_tags:
                        if tag in tags:
                            result[tag] = str(tags[tag])
                    
                    self.exif_cache[image_path] = result
                    return result
            except Exception as e:
                retries += 1
                if retries < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                else:
                    if "No EXIF header" not in str(e):
                        self.emit_log(f"Ошибка чтения EXIF из {os.path.basename(image_path)}: {str(e)}", UI_CONFIG["COLOR_DANGER"], LOG_ERROR)
                    return {}
        return {}
    
    def read_metadata_parallel(self, file_list):
        metadata_cache = {}
        def read_single_metadata(file_info):
            path, name, rel_path = file_info
            return path, self.get_exif_data_fast(path)
        
        metadata_workers = min(self.max_workers, 2)
        processed = 0
        total_files = len(file_list)
        chunk_size = 50
        chunks = [file_list[i:i + chunk_size] for i in range(0, len(file_list), chunk_size)]
        
        for chunk in chunks:
            if self.canceled: return {}
            with ThreadPoolExecutor(max_workers=metadata_workers) as executor:
                futures = {executor.submit(read_single_metadata, file_info): file_info for file_info in chunk}
                for future in as_completed(futures):
                    path, metadata = future.result()
                    if metadata: metadata_cache[path] = metadata
                    processed += 1
                    if processed % 100 == 0:
                        progress = int(processed / total_files * 100)
                        self.metadata_progress_signal.emit(progress)
                        self.emit_log(f"Обработано {processed} из {total_files} файлов метаданных", UI_CONFIG["COLOR_ACCENT"], LOG_DEBUG)
        return metadata_cache
    
    def create_metadata_index(self, source_files):
        os.makedirs(self.cache_dir, exist_ok=True)
        source_root_hash = hashlib.md5(self.source_root.encode()).hexdigest()[:16]
        index_path = os.path.join(self.cache_dir, f"metadata_index_{source_root_hash}.pkl")
        
        if os.path.exists(index_path):
            try:
                source_mtime = 0
                for src_path, _, _ in source_files:
                    if os.path.exists(src_path):
                        file_mtime = os.path.getmtime(src_path)
                        if file_mtime > source_mtime: source_mtime = file_mtime
                if os.path.getmtime(index_path) > source_mtime:
                    self.emit_log("Используется кэш метаданных...", UI_CONFIG["COLOR_ACCENT"], LOG_INFO)
                    with open(index_path, 'rb') as f: return pickle.load(f)
            except Exception: pass
        
        self.emit_log("Создание индекса метаданных...", UI_CONFIG["COLOR_ACCENT"], LOG_INFO)
        metadata_index = self.read_metadata_parallel(source_files)
        try:
            with open(index_path, 'wb') as f: pickle.dump(metadata_index, f)
        except Exception: pass
        return metadata_index
    
    def compare_metadata_values(self, exp_exif, src_exif, exp_name, src_name):
        tag = 'EXIF DateTimeOriginal'
        if tag in exp_exif and tag in src_exif:
            return exp_exif[tag] == src_exif[tag]
        return False
    
    def create_source_index(self, source_files):
        source_index = {}
        for src_path, src_name, rel_path in source_files:
            src_base = os.path.splitext(src_name)[0]
            if src_base not in source_index: source_index[src_base] = []
            source_index[src_base].append((src_path, src_name, rel_path))
        return source_index
    
    def find_matching_source_files(self, exp_base_name, source_index):
        matching_sources = []
        if exp_base_name in source_index:
            matching_sources.extend(source_index[exp_base_name])
        
        if self.check_without_suffix and self.use_suffix and self.suffix_text:
            base_name_without_suffix = exp_base_name
            if exp_base_name.endswith(self.suffix_text):
                base_name_without_suffix = exp_base_name[:-len(self.suffix_text)]
                if base_name_without_suffix in source_index:
                    matching_sources.extend(source_index[base_name_without_suffix])
        
        if not matching_sources and self.compare_metadata_flag:
            main_name = self.extract_main_name(exp_base_name)
            if main_name in source_index and main_name != exp_base_name:
                matching_sources.extend(source_index[main_name])
        return matching_sources
    
    def process_single_file(self, exp_file, source_index, source_metadata_cache):
        exp_path, exp_name = exp_file
        if self.canceled: return None, None, None, []
        
        exp_base_name = os.path.splitext(exp_name)[0]
        matching_sources = self.find_matching_source_files(exp_base_name, source_index)
        
        matched_source = None
        log_messages = []
        
        for src_path, src_name, rel_path in matching_sources:
            match_found = True
            if self.compare_metadata_flag:
                exp_exif = self.get_exif_data_fast(exp_path)
                src_exif = source_metadata_cache.get(src_path, {})
                if exp_exif and src_exif:
                    if not self.compare_metadata_values(exp_exif, src_exif, exp_name, src_name):
                        match_found = False
                else: match_found = False
            
            if match_found:
                matched_source = src_path
                log_messages.append((f"Сопоставлено: {exp_name} -> {src_name}", "green", LOG_INFO))
                break
        
        if not matched_source and matching_sources:
            log_messages.append((f"Не найдено точное соответствие: {exp_name}", "orange", LOG_WARNING))
        
        return exp_path, matched_source, exp_name, log_messages
    
    def organize_photos(self):
        os.makedirs(self.output_root, exist_ok=True)
        
        source_files = []
        for root, dirs, files in os.walk(self.source_root):
            for file in files:
                if os.path.splitext(file.lower())[1] in self.source_extensions:
                    source_files.append((os.path.join(root, file), file, os.path.relpath(os.path.join(root, file), self.source_root)))
            if self.canceled: return
        
        exported_files = []
        for root, dirs, files in os.walk(self.exported_root):
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.tiff', '.dng')):
                    exported_files.append((os.path.join(root, file), file))
            if self.canceled: return
        
        self.emit_log(f"Исходных: {len(source_files)} | Экспортированных: {len(exported_files)}", "#000000", LOG_INFO)
        
        source_index = self.create_source_index(source_files)
        source_metadata_cache = {}
        if self.compare_metadata_flag:
            source_metadata_cache = self.create_metadata_index(source_files)
        
        matches = {}
        chunk_size = 100
        chunks = [exported_files[i:i + chunk_size] for i in range(0, len(exported_files), chunk_size)]
        total_processed = 0
        
        for chunk in chunks:
            if self.canceled: return
            chunk_matches = {}
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(self.process_single_file, f, source_index, source_metadata_cache): f for f in chunk}
                for future in as_completed(futures):
                    try:
                        exp_path, matched_source, exp_name, log_messages = future.result()
                        if matched_source: chunk_matches[exp_path] = (matched_source, exp_name)
                        for msg, col, lvl in log_messages: self.emit_log(msg, col, lvl)
                    except Exception as e: self.emit_log(f"Ошибка: {str(e)}", UI_CONFIG["COLOR_DANGER"], LOG_ERROR)
            
            matches.update(chunk_matches)
            total_processed += len(chunk)
            progress = int(total_processed / len(exported_files) * 100)
            self.progress_signal.emit(progress)
            self.emit_log(f"Обработано {total_processed}/{len(exported_files)} ({progress}%)", UI_CONFIG["COLOR_ACCENT"], LOG_DEBUG)
        
        moved_count = 0
        for exp_path, (src_path, exp_name) in matches.items():
            if self.canceled: return
            target_path = os.path.join(self.output_root, os.path.dirname(os.path.relpath(src_path, self.source_root)), exp_name)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            try:
                shutil.move(exp_path, target_path)
                moved_count += 1
            except Exception as e: self.emit_log(f"Ошибка перемещения {exp_name}: {str(e)}", UI_CONFIG["COLOR_DANGER"], LOG_ERROR)
        
        self.emit_log(f"Готово! Перемещено {moved_count} файлов.", "green", LOG_INFO)

class PhotoOrganizerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.organizer_thread = None
        self.init_ui()
        self.apply_material_theme()
        
    def apply_material_theme(self):
        """Применение стилей Material Design через UI_CONFIG"""
        
        if sys.platform == "win32":
            base_font = "Segoe UI"
        elif sys.platform == "darwin":
            base_font = "San Francisco"
        else:
            base_font = "Roboto"
            
        # Используем f-строки для вставки значений из UI_CONFIG
        # Обратите внимание: фигурные скобки CSS {{ }} экранированы
        style_sheet = f"""
            QMainWindow {{
                background-color: {UI_CONFIG['COLOR_BG']};
                font-family: "{base_font}", sans-serif;
                font-size: {UI_CONFIG['FONT_MAIN']}px;
            }}
            
            QGroupBox {{
                background-color: {UI_CONFIG['COLOR_CARD_BG']};
                border: 1px solid {UI_CONFIG['COLOR_BORDER']};
                border-radius: {UI_CONFIG['RADIUS_CARD']}px;
                margin-top: 22px;
                padding-top: 15px;
                font-weight: bold;
                color: #444;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 0 5px;
                background-color: transparent;
                color: {UI_CONFIG['COLOR_ACCENT']};
                font-size: {UI_CONFIG['FONT_HEADER']}px;
                font-weight: bold;
                text-transform: uppercase;
            }}
            
            QLineEdit {{
                background-color: {UI_CONFIG['COLOR_BG']};
                border: 1px solid transparent;
                border-radius: {UI_CONFIG['RADIUS_INPUT']}px;
                padding: 4px 10px;
                color: {UI_CONFIG['COLOR_TEXT']};
                selection-background-color: {UI_CONFIG['COLOR_ACCENT']};
                height: {UI_CONFIG['INPUT_HEIGHT']}px;
            }}
            QLineEdit:focus {{
                background-color: {UI_CONFIG['COLOR_CARD_BG']};
                border: 1px solid {UI_CONFIG['COLOR_ACCENT']};
            }}
            QLineEdit:disabled {{
                background-color: {UI_CONFIG['COLOR_BORDER']};
                color: #B0B3B8;
            }}
            
            QComboBox, QSpinBox {{
                background-color: {UI_CONFIG['COLOR_BG']};
                border: 1px solid transparent;
                border-radius: {UI_CONFIG['RADIUS_INPUT']}px;
                padding: 4px;
                color: {UI_CONFIG['COLOR_TEXT']};
                height: {UI_CONFIG['INPUT_HEIGHT']}px;
            }}
            
            QPushButton {{
                background-color: {UI_CONFIG['COLOR_BORDER']};
                border: none;
                border-radius: {UI_CONFIG['RADIUS_BTN']}px;
                color: #050505;
                padding: 0px 16px;
                font-weight: 600;
                height: {UI_CONFIG['BTN_HEIGHT_SMALL']}px;
            }}
            QPushButton:hover {{
                background-color: #D8DADF;
            }}
            QPushButton:pressed {{
                background-color: #BCC0C4;
            }}
            QPushButton:disabled {{
                background-color: {UI_CONFIG['COLOR_BG']};
                color: #BCC0C4;
            }}
            
            QPushButton#PrimaryButton {{
                background-color: {UI_CONFIG['COLOR_ACCENT']};
                color: #FFFFFF;
                font-size: {UI_CONFIG['FONT_BTN']}px;
                border-radius: {UI_CONFIG['RADIUS_BTN']}px;
                height: {UI_CONFIG['BTN_HEIGHT_LARGE']}px;
            }}
            QPushButton#PrimaryButton:hover {{
                background-color: {UI_CONFIG['COLOR_ACCENT_HOVER']};
            }}
            
            QPushButton#DangerButton {{
                background-color: #FFF;
                border: 1px solid #FFCDD2;
                color: {UI_CONFIG['COLOR_DANGER']};
                height: {UI_CONFIG['BTN_HEIGHT_LARGE']}px;
            }}
            QPushButton#DangerButton:hover {{
                background-color: #FFEBEE;
            }}
            
            QCheckBox {{
                spacing: 8px;
                color: {UI_CONFIG['COLOR_TEXT']};
            }}
            
            QProgressBar {{
                border: none;
                background-color: {UI_CONFIG['COLOR_BORDER']};
                border-radius: {int(UI_CONFIG['PROGRESS_HEIGHT']/2)}px;
                height: {UI_CONFIG['PROGRESS_HEIGHT']}px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {UI_CONFIG['COLOR_ACCENT']};
                border-radius: {int(UI_CONFIG['PROGRESS_HEIGHT']/2)}px;
            }}
            
            QTextEdit {{
                background-color: {UI_CONFIG['COLOR_CARD_BG']};
                border: 1px solid {UI_CONFIG['COLOR_BORDER']};
                border-radius: {UI_CONFIG['RADIUS_CARD']}px;
                color: #333;
                font-family: "Consolas", "Monaco", monospace;
                font-size: {UI_CONFIG['FONT_CONSOLE']}px;
                padding: 5px;
            }}
        """
        self.setStyleSheet(style_sheet)

    def init_ui(self):
        self.setWindowTitle("Photo Organizer Pro")
        self.setGeometry(100, 100, UI_CONFIG['WINDOW_WIDTH'], UI_CONFIG['WINDOW_HEIGHT'])
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(UI_CONFIG['SPACING_GLOBAL'])
        main_layout.setContentsMargins(
            UI_CONFIG['MARGIN_MAIN'], UI_CONFIG['MARGIN_MAIN'], 
            UI_CONFIG['MARGIN_MAIN'], UI_CONFIG['MARGIN_MAIN']
        )
        
        path_group = QGroupBox("Рабочие папки")
        path_layout = QGridLayout()
        path_layout.setVerticalSpacing(UI_CONFIG['SPACING_INSIDE'])
        path_layout.setHorizontalSpacing(10)
        
        def add_path_row(row, label_text, btn_callback):
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #65676B; font-weight: 600;")
            inp = QLineEdit()
            inp.setPlaceholderText("Выберите папку...")
            btn = QPushButton("Обзор")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(btn_callback)
            btn.setFixedWidth(UI_CONFIG['BTN_WIDTH_SMALL'])
            
            path_layout.addWidget(lbl, row, 0)
            path_layout.addWidget(inp, row, 1)
            path_layout.addWidget(btn, row, 2)
            return inp

        self.source_input = add_path_row(0, "Исходные (RAW):", self.browse_source)
        self.export_input = add_path_row(1, "Экспорт (JPG):", self.browse_export)
        self.output_input = add_path_row(2, "Куда сложить:", self.browse_output)
        
        path_group.setLayout(path_layout)
        main_layout.addWidget(path_group)
        
        settings_group = QGroupBox("Параметры сортировки")
        settings_layout = QVBoxLayout()
        settings_layout.setSpacing(UI_CONFIG['SPACING_INSIDE'])
        
        suffix_container = QHBoxLayout()
        self.suffix_check = QCheckBox("Искать по суффиксу")
        self.suffix_check.setCursor(Qt.PointingHandCursor)
        self.suffix_check.stateChanged.connect(self.on_suffix_check_changed)
        
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("Например: _edit")
        self.suffix_input.setText(".jpg.texture")
        self.suffix_input.setFixedWidth(200)
        
        suffix_container.addWidget(self.suffix_check)
        suffix_container.addWidget(self.suffix_input)
        suffix_container.addStretch()
        settings_layout.addLayout(suffix_container)
        
        opts_layout = QHBoxLayout()
        self.check_without_suffix_check = QCheckBox("Искать также без суффикса")
        self.check_without_suffix_check.setChecked(True)
        self.check_without_suffix_check.setCursor(Qt.PointingHandCursor)
        
        self.metadata_check = QCheckBox("Сверка EXIF (дата съемки)")
        self.metadata_check.setChecked(True)
        self.metadata_check.setCursor(Qt.PointingHandCursor)
        
        opts_layout.addWidget(self.check_without_suffix_check)
        opts_layout.addSpacing(20)
        opts_layout.addWidget(self.metadata_check)
        opts_layout.addStretch()
        settings_layout.addLayout(opts_layout)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {UI_CONFIG['COLOR_BORDER']};")
        settings_layout.addWidget(line)
        
        ext_layout = QHBoxLayout()
        lbl_ext = QLabel("Типы исходников:")
        lbl_ext.setStyleSheet("color: #65676B; font-weight: 600;")
        ext_layout.addWidget(lbl_ext)
        
        self.extension_checks = {}
        for ext in ['.arw', '.cr2', '.dng', '.nef', '.jpg', '.png']:
            check = QCheckBox(ext.upper())
            check.setCursor(Qt.PointingHandCursor)
            check.setChecked(True if ext in ['.arw', '.cr2'] else False)
            self.extension_checks[ext] = check
            ext_layout.addWidget(check)
        ext_layout.addStretch()
        settings_layout.addLayout(ext_layout)
        
        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)
        
        perf_group = QGroupBox("Движок")
        perf_layout = QHBoxLayout()
        
        perf_layout.addWidget(QLabel("Потоки:"))
        self.threads_spinbox = QSpinBox()
        self.threads_spinbox.setRange(1, 32)
        self.threads_spinbox.setValue(16)
        self.threads_spinbox.setFixedWidth(60)
        perf_layout.addWidget(self.threads_spinbox)
        
        perf_layout.addSpacing(15)
        perf_layout.addWidget(QLabel("Буфер (KB):"))
        self.buffer_size_spinbox = QSpinBox()
        self.buffer_size_spinbox.setRange(4, 4096)
        self.buffer_size_spinbox.setValue(256)
        self.buffer_size_spinbox.setFixedWidth(70)
        perf_layout.addWidget(self.buffer_size_spinbox)
        
        perf_layout.addSpacing(15)
        perf_layout.addWidget(QLabel("Повторы:"))
        self.retry_spinbox = QSpinBox()
        self.retry_spinbox.setValue(3)
        perf_layout.addWidget(self.retry_spinbox)
        
        perf_layout.addSpacing(15)
        perf_layout.addWidget(QLabel("Таймаут (мс):"))
        self.retry_delay_spinbox = QSpinBox()
        self.retry_delay_spinbox.setRange(100, 5000)
        self.retry_delay_spinbox.setValue(1000)
        self.retry_delay_spinbox.setSuffix(" ms")
        perf_layout.addWidget(self.retry_delay_spinbox)
        
        perf_layout.addStretch()
        perf_group.setLayout(perf_layout)
        main_layout.addWidget(perf_group)
        
        action_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("ЗАПУСТИТЬ СОРТИРОВКУ")
        self.start_btn.setObjectName("PrimaryButton")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self.start_organization)
        
        self.cancel_btn = QPushButton("Остановить")
        self.cancel_btn.setObjectName("DangerButton")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.cancel_organization)
        self.cancel_btn.setEnabled(False)
        
        action_layout.addWidget(self.start_btn, 70)
        action_layout.addWidget(self.cancel_btn, 30)
        main_layout.addLayout(action_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        main_layout.addWidget(self.progress_bar)
        
        log_group = QGroupBox("Журнал событий")
        log_layout = QVBoxLayout()
        
        log_tools = QHBoxLayout()
        self.log_enable_check = QCheckBox("Запись лога")
        self.log_enable_check.setChecked(True)
        
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItem("Всё подряд", LOG_DEBUG)
        self.log_level_combo.addItem("Стандартно", LOG_INFO)
        self.log_level_combo.addItem("Только ошибки", LOG_WARNING)
        self.log_level_combo.setCurrentIndex(1)
        
        self.save_log_btn = QPushButton("Сохранить...")
        self.save_log_btn.setFixedWidth(110)
        self.save_log_btn.clicked.connect(self.save_log_to_file)
        
        log_tools.addWidget(self.log_enable_check)
        log_tools.addSpacing(10)
        log_tools.addWidget(self.log_level_combo)
        log_tools.addStretch()
        log_tools.addWidget(self.save_log_btn)
        log_layout.addLayout(log_tools)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)
        
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)
        
        self.on_suffix_check_changed(Qt.Unchecked)

    def on_suffix_check_changed(self, state):
        enabled = state == Qt.Checked
        self.suffix_input.setEnabled(enabled)
        self.check_without_suffix_check.setEnabled(enabled)
        
    def browse_source(self):
        d = QFileDialog.getExistingDirectory(self, "Исходные RAW")
        if d: self.source_input.setText(d)
    
    def browse_export(self):
        d = QFileDialog.getExistingDirectory(self, "Папка с JPG")
        if d: 
            self.export_input.setText(d)
            if not self.output_input.text(): self.output_input.setText(d + "_Sorted")
    
    def browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "Куда сохранять")
        if d: self.output_input.setText(d)
    
    def append_log_message(self, message, color):
        if not self.log_enable_check.isChecked(): return
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(message + "\n")
        self.log_output.setTextCursor(cursor)
        self.log_output.ensureCursorVisible()
        
    def save_log_to_file(self):
        content = self.log_output.toPlainText()
        if not content: return
        fn, _ = QFileDialog.getSaveFileName(self, "Save Log", "", "Text (*.txt)")
        if fn:
            with open(fn, 'w', encoding='utf-8') as f: f.write(content)

    def start_organization(self):
        s_dir, e_dir, o_dir = self.source_input.text(), self.export_input.text(), self.output_input.text()
        if not all([s_dir, e_dir, o_dir]):
            QMessageBox.warning(self, "Ошибка", "Заполните все пути к папкам!")
            return
        
        src_exts = [k for k, v in self.extension_checks.items() if v.isChecked()]
        if not src_exts:
            QMessageBox.warning(self, "Ошибка", "Выберите типы файлов!")
            return

        self.log_output.clear()
        self.set_ui_enabled(False)
        
        self.organizer_thread = PhotoOrganizerThread(
            s_dir, e_dir, o_dir,
            self.suffix_check.isChecked(), self.suffix_input.text(),
            self.check_without_suffix_check.isChecked(), self.metadata_check.isChecked(),
            self.threads_spinbox.value(), self.buffer_size_spinbox.value(),
            self.retry_spinbox.value(), self.retry_delay_spinbox.value() / 1000,
            src_exts, self.log_level_combo.currentData()
        )
        
        self.organizer_thread.log_signal.connect(self.append_log_message)
        self.organizer_thread.progress_signal.connect(self.progress_bar.setValue)
        self.organizer_thread.finished_signal.connect(self.organization_finished)
        self.organizer_thread.start()
    
    def cancel_organization(self):
        if self.organizer_thread: self.organizer_thread.cancel()
    
    def organization_finished(self, success, msg):
        self.set_ui_enabled(True)
        self.progress_bar.setValue(100 if success else 0)
        self.append_log_message(msg, "green" if success else UI_CONFIG["COLOR_DANGER"])
        if success: QMessageBox.information(self, "Готово", msg)
        else: QMessageBox.warning(self, "Стоп", msg)
    
    def set_ui_enabled(self, enabled):
        for w in [self.source_input, self.export_input, self.output_input, 
                  self.suffix_check, self.suffix_input, self.check_without_suffix_check,
                  self.metadata_check, self.start_btn, self.threads_spinbox]:
            w.setEnabled(enabled)
        self.cancel_btn.setEnabled(not enabled)

if __name__ == "__main__":
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    
    app = QApplication(sys.argv)
    
    window = PhotoOrganizerApp()
    window.show()
    sys.exit(app.exec_())