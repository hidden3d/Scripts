import os
import sys
import shutil
import hashlib
import exifread
import pickle
import time
import threading
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QLineEdit, QTextEdit, QCheckBox, QFileDialog,
                             QProgressBar, QGroupBox, QMessageBox, QSpinBox, QGridLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QTextCursor, QColor

class PhotoOrganizerThread(QThread):
    """Поток для организации фотографий без блокировки GUI"""
    log_signal = pyqtSignal(str, str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)
    metadata_progress_signal = pyqtSignal(int)
    
    def __init__(self, source_root, exported_root, output_root, 
                 use_suffix, suffix_text, check_without_suffix, 
                 compare_metadata, max_workers, buffer_size_kb,
                 max_retries, retry_delay, source_extensions):
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
        self.canceled = False
        
        # Кэш для ускорения работы
        source_root_hash = hashlib.md5(source_root.encode()).hexdigest()[:8]
        self.cache_dir = os.path.join(self.output_root, f".metadata_cache_{source_root_hash}")
        
        # Блокировки и кэши
        self.file_locks = {}
        self.lock = threading.Lock()
        self.exif_cache = {}  # Кэш для EXIF данных
        
    def run(self):
        try:
            self.organize_photos()
            self.finished_signal.emit(True, "Операция завершена успешно!")
        except Exception as e:
            self.finished_signal.emit(False, f"Ошибка: {str(e)}")
    
    def cancel(self):
        self.canceled = True
        self.log_signal.emit("Операция отменена пользователем", "red")
    
    def extract_main_name(self, filename):
        """Быстрое извлечение основного имени файла"""
        # Используем более простую логику для скорости
        for suffix in ['-1', '-2', '-3', '-4', '-5', '_1', '_2', '_3', '_4', '_5']:
            if filename.endswith(suffix):
                return filename[:-len(suffix)]
        return filename
    
    def get_exif_data_fast(self, image_path):
        """Быстрое чтение EXIF данных с оптимизацией"""
        # Проверяем кэш
        if image_path in self.exif_cache:
            return self.exif_cache[image_path]
            
        retries = 0
        delay = self.retry_delay
        
        while retries < self.max_retries:
            try:
                with open(image_path, 'rb') as f:
                    # Читаем только начало файла где находятся EXIF данные
                    if any(image_path.lower().endswith(ext) for ext in ['.cr2', '.nef', '.arw', '.dng']):
                        data = f.read(262144)  # 256KB для RAW
                    else:
                        data = f.read(65536)   # 64KB для JPEG
                    
                    # Ищем EXIF маркер
                    exif_start = data.find(b'\xFF\xE1')
                    if exif_start != -1:
                        f.seek(exif_start + 4)
                        tags = exifread.process_file(f, details=False)
                    else:
                        # Если не нашли EXIF маркер, читаем с начала
                        f.seek(0)
                        tags = exifread.process_file(f, details=False, stop_tag='DateTimeOriginal')
                    
                    # Фильтруем только нужные теги
                    required_tags = ['EXIF DateTimeOriginal', 'Image DateTime', 'DateTime']
                    result = {}
                    for tag in required_tags:
                        if tag in tags:
                            result[tag] = str(tags[tag])  # Сразу конвертируем в строку для сравнения
                    
                    # Кэшируем результат
                    self.exif_cache[image_path] = result
                    return result
                    
            except Exception as e:
                retries += 1
                if retries < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                else:
                    # Логируем только при реальных ошибках
                    if "No EXIF header" not in str(e):
                        self.log_signal.emit(f"Ошибка чтения EXIF из {os.path.basename(image_path)}: {str(e)}", "red")
                    return {}
        
        return {}
    
    def read_metadata_parallel(self, file_list):
        """Оптимизированное многопоточное чтение метаданных"""
        metadata_cache = {}
        
        def read_single_metadata(file_info):
            path, name, rel_path = file_info
            return path, self.get_exif_data_fast(path)
        
        # Ограничиваем потоки для метаданных
        metadata_workers = min(self.max_workers, 2)  # Уменьшаем до 2 потоков
        
        processed = 0
        total_files = len(file_list)
        
        # Используем chunks для уменьшения накладных расходов
        chunk_size = 50
        chunks = [file_list[i:i + chunk_size] for i in range(0, len(file_list), chunk_size)]
        
        for chunk in chunks:
            if self.canceled:
                return {}
                
            with ThreadPoolExecutor(max_workers=metadata_workers) as executor:
                futures = {executor.submit(read_single_metadata, file_info): file_info for file_info in chunk}
                
                for future in as_completed(futures):
                    path, metadata = future.result()
                    if metadata:
                        metadata_cache[path] = metadata
                    
                    processed += 1
                    if processed % 100 == 0:  # Реже обновляем прогресс
                        progress = int(processed / total_files * 100)
                        self.metadata_progress_signal.emit(progress)
                        self.log_signal.emit(f"Обработано {processed} из {total_files} файлов метаданных", "blue")
        
        return metadata_cache
    
    def create_metadata_index(self, source_files):
        """Оптимизированное создание индекса метаданных"""
        os.makedirs(self.cache_dir, exist_ok=True)
        
        source_root_hash = hashlib.md5(self.source_root.encode()).hexdigest()[:16]
        index_path = os.path.join(self.cache_dir, f"metadata_index_{source_root_hash}.pkl")
        
        # Проверяем кэш
        if os.path.exists(index_path):
            try:
                source_mtime = 0
                for src_path, _, _ in source_files:
                    if os.path.exists(src_path):
                        file_mtime = os.path.getmtime(src_path)
                        if file_mtime > source_mtime:
                            source_mtime = file_mtime
                
                index_mtime = os.path.getmtime(index_path)
                
                if index_mtime > source_mtime:
                    self.log_signal.emit("Используется кэш метаданных...", "blue")
                    with open(index_path, 'rb') as f:
                        return pickle.load(f)
            except Exception:
                pass  # Игнорируем ошибки кэша, создаем заново
        
        # Создаем новый индекс
        self.log_signal.emit("Создание индекса метаданных...", "blue")
        metadata_index = self.read_metadata_parallel(source_files)
        
        # Сохраняем индекс
        try:
            with open(index_path, 'wb') as f:
                pickle.dump(metadata_index, f)
        except Exception:
            pass  # Если не удалось сохранить, продолжаем
        
        return metadata_index
    
    def compare_metadata_values(self, exp_exif, src_exif, exp_name, src_name):
        """Упрощенное сравнение метаданных"""
        # Сравниваем только DateTimeOriginal
        tag = 'EXIF DateTimeOriginal'
        
        if tag in exp_exif and tag in src_exif:
            return exp_exif[tag] == src_exif[tag]
        
        return False
    
    def create_source_index(self, source_files):
        """Быстрое создание индекса исходных файлов"""
        source_index = {}
        for src_path, src_name, rel_path in source_files:
            src_base = os.path.splitext(src_name)[0]
            if src_base not in source_index:
                source_index[src_base] = []
            source_index[src_base].append((src_path, src_name, rel_path))
        return source_index
    
    def find_matching_source_files(self, exp_base_name, source_index):
        """Оптимизированный поиск исходных файлов"""
        matching_sources = []
        
        # 1. Точное совпадение (самый быстрый)
        if exp_base_name in source_index:
            matching_sources.extend(source_index[exp_base_name])
        
        # 2. Без суффикса (если включено)
        if self.check_without_suffix and self.use_suffix and self.suffix_text:
            base_name_without_suffix = exp_base_name
            if exp_base_name.endswith(self.suffix_text):
                base_name_without_suffix = exp_base_name[:-len(self.suffix_text)]
                if base_name_without_suffix in source_index:
                    matching_sources.extend(source_index[base_name_without_suffix])
        
        # 3. Основное имя (только если нужно)
        if not matching_sources and self.compare_metadata_flag:
            main_name = self.extract_main_name(exp_base_name)
            if main_name in source_index and main_name != exp_base_name:
                matching_sources.extend(source_index[main_name])
        
        return matching_sources
    
    def process_single_file(self, exp_file, source_index, source_metadata_cache):
        """Оптимизированная обработка одного файла"""
        exp_path, exp_name = exp_file
        
        if self.canceled:
            return None, None, None, []
            
        exp_base_name = os.path.splitext(exp_name)[0]
        
        # Быстрый поиск
        matching_sources = self.find_matching_source_files(exp_base_name, source_index)
        
        matched_source = None
        matched_source_name = None
        log_messages = []
        
        for src_path, src_name, rel_path in matching_sources:
            match_found = True
            
            # Проверка метаданных (если включено)
            if self.compare_metadata_flag and match_found:
                exp_exif = self.get_exif_data_fast(exp_path)
                src_exif = source_metadata_cache.get(src_path, {})
                
                if exp_exif and src_exif:
                    if not self.compare_metadata_values(exp_exif, src_exif, exp_name, src_name):
                        match_found = False
                else:
                    match_found = False
            
            # Нашли соответствие
            if match_found:
                matched_source = src_path
                matched_source_name = src_name
                log_messages.append((f"Сопоставлено: {exp_name} -> {src_name}", "green"))
                break
        
        if not matched_source and matching_sources:
            log_messages.append((f"Не найдено точное соответствие для: {exp_name}", "yellow"))
        
        return exp_path, matched_source, exp_name, log_messages
    
    def organize_photos(self):
        """Оптимизированная основная функция"""
        os.makedirs(self.output_root, exist_ok=True)
        
        # Быстрый поиск исходных файлов
        source_files = []
        for root, dirs, files in os.walk(self.source_root):
            for file in files:
                file_ext = os.path.splitext(file.lower())[1]
                if file_ext in self.source_extensions:
                    src_path = os.path.join(root, file)
                    rel_path = os.path.relpath(src_path, self.source_root)
                    source_files.append((src_path, file, rel_path))
            if self.canceled:
                return
        
        # Быстрый поиск экспортированных файлов
        exported_files = []
        for root, dirs, files in os.walk(self.exported_root):
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.tiff', '.dng')):
                    exported_files.append((os.path.join(root, file), file))
            if self.canceled:
                return
        
        self.log_signal.emit(f"Найдено {len(source_files)} исходных и {len(exported_files)} экспортированных файлов", "black")
        
        # Создаем индексы
        source_index = self.create_source_index(source_files)
        
        # Читаем метаданные только если включена проверка
        source_metadata_cache = {}
        if self.compare_metadata_flag:
            source_metadata_cache = self.create_metadata_index(source_files)
        
        # Сопоставление файлов
        matches = {}
        
        # Используем chunks для лучшего контроля прогресса
        chunk_size = 100
        chunks = [exported_files[i:i + chunk_size] for i in range(0, len(exported_files), chunk_size)]
        
        total_processed = 0
        for chunk in chunks:
            if self.canceled:
                return
                
            chunk_matches = {}
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(
                        self.process_single_file, 
                        exp_file, 
                        source_index, 
                        source_metadata_cache
                    ): exp_file for exp_file in chunk
                }
                
                for future in as_completed(futures):
                    try:
                        exp_path, matched_source, exp_name, log_messages = future.result()
                        
                        if matched_source:
                            chunk_matches[exp_path] = (matched_source, exp_name)
                        
                        # Логируем только важные сообщения
                        for message, color in log_messages:
                            if "Сопоставлено" in message or "Не найдено" in message:
                                self.log_signal.emit(message, color)
                                
                    except Exception as e:
                        self.log_signal.emit(f"Ошибка обработки файла: {str(e)}", "red")
            
            matches.update(chunk_matches)
            total_processed += len(chunk)
            progress = int(total_processed / len(exported_files) * 100)
            self.progress_signal.emit(progress)
            self.log_signal.emit(f"Обработано {total_processed}/{len(exported_files)} файлов ({progress}%)", "blue")
        
        # Перемещение файлов
        moved_count = 0
        for exp_path, (src_path, exp_name) in matches.items():
            if self.canceled:
                return
                
            relative_path = os.path.relpath(src_path, self.source_root)
            relative_dir = os.path.dirname(relative_path)
            target_path = os.path.join(self.output_root, relative_dir, exp_name)
            
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            
            try:
                shutil.move(exp_path, target_path)
                moved_count += 1
            except Exception as e:
                self.log_signal.emit(f"Ошибка перемещения {exp_name}: {str(e)}", "red")
        
        self.log_signal.emit(f"Готово! Перемещено {moved_count} файлов в {self.output_root}", "green")

class PhotoOrganizerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.organizer_thread = None
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Организатор фотографий")
        self.setGeometry(100, 100, 800, 700)
        
        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Основной layout
        layout = QVBoxLayout(central_widget)
        
        # Группа путей
        path_group = QGroupBox("Пути к папкам")
        path_layout = QVBoxLayout()
        
        # Исходная папка
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("Исходные фото:"))
        self.source_input = QLineEdit()
        source_layout.addWidget(self.source_input)
        self.source_btn = QPushButton("Обзор...")
        self.source_btn.clicked.connect(self.browse_source)
        source_layout.addWidget(self.source_btn)
        path_layout.addLayout(source_layout)
        
        # Экспортированная папка
        export_layout = QHBoxLayout()
        export_layout.addWidget(QLabel("Экспортированные фото:"))
        self.export_input = QLineEdit()
        export_layout.addWidget(self.export_input)
        self.export_btn = QPushButton("Обзор...")
        self.export_btn.clicked.connect(self.browse_export)
        export_layout.addWidget(self.export_btn)
        path_layout.addLayout(export_layout)
        
        # Выходная папка
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Выходная папка:"))
        self.output_input = QLineEdit()
        output_layout.addWidget(self.output_input)
        self.output_btn = QPushButton("Обзор...")
        self.output_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(self.output_btn)
        path_layout.addLayout(output_layout)
        
        path_group.setLayout(path_layout)
        layout.addWidget(path_group)
        
        # Группа настроек
        settings_group = QGroupBox("Настройки")
        settings_layout = QVBoxLayout()
        
        # Суффикс
        suffix_layout = QHBoxLayout()
        self.suffix_check = QCheckBox("Учитывать суффикс:")
        self.suffix_check.setChecked(False)
        self.suffix_check.stateChanged.connect(self.on_suffix_check_changed)
        suffix_layout.addWidget(self.suffix_check)
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("Например: _export или -small")
        self.suffix_input.setText(".jpg.texture")
        suffix_layout.addWidget(self.suffix_input)
        settings_layout.addLayout(suffix_layout)
        
        # Дополнительная опция для проверки без суффикса
        self.check_without_suffix_check = QCheckBox("Также проверять фото без суффикса")
        self.check_without_suffix_check.setChecked(True)
        settings_layout.addWidget(self.check_without_suffix_check)
        
        # Дополнительные проверки
        self.metadata_check = QCheckBox("Сравнивать метаданные EXIF (DateTimeOriginal)")
        self.metadata_check.setChecked(True)
        settings_layout.addWidget(self.metadata_check)
        
        # Убрана опция сравнения хеш-сумм
        
        # Новая группа: Расширения исходных файлов
        extensions_group = QGroupBox("Расширения исходных файлов")
        extensions_layout = QHBoxLayout()
        
        # Создаем чекбоксы для расширений в нужном порядке
        extensions_order = ['.arw', '.cr2', '.dng', '.nef', '.jpg', '.jpeg', '.png', '.tiff']
        self.extension_checks = {}
        
        for ext in extensions_order:
            check = QCheckBox(ext)
            if ext in ['.arw', '.cr2']:
                check.setChecked(True)
            else:
                check.setChecked(False)
            self.extension_checks[ext] = check
            extensions_layout.addWidget(check)
        
        extensions_group.setLayout(extensions_layout)
        settings_layout.addWidget(extensions_group)
        
        # Настройки производительности
        performance_group = QGroupBox("Настройки производительности")
        performance_layout = QVBoxLayout()
        
        # Количество потоков
        threads_layout = QHBoxLayout()
        threads_layout.addWidget(QLabel("Количество потоков:"))
        self.threads_spinbox = QSpinBox()
        self.threads_spinbox.setRange(1, 16)
        self.threads_spinbox.setValue(16)
        threads_layout.addWidget(self.threads_spinbox)
        threads_layout.addStretch()
        performance_layout.addLayout(threads_layout)
        
        # Размер буфера (теперь не используется для хешей, но оставим для возможного будущего использования)
        buffer_layout = QHBoxLayout()
        buffer_layout.addWidget(QLabel("Размер буфера (KB):"))
        self.buffer_size_spinbox = QSpinBox()
        self.buffer_size_spinbox.setRange(4, 1024)
        self.buffer_size_spinbox.setValue(256)
        buffer_layout.addWidget(self.buffer_size_spinbox)
        buffer_layout.addStretch()
        performance_layout.addLayout(buffer_layout)
        
        # Настройки повторных попыток
        retry_layout = QHBoxLayout()
        retry_layout.addWidget(QLabel("Попыток чтения:"))
        self.retry_spinbox = QSpinBox()
        self.retry_spinbox.setRange(1, 10)
        self.retry_spinbox.setValue(3)
        retry_layout.addWidget(self.retry_spinbox)
        
        retry_layout.addWidget(QLabel("Задержка (мс):"))
        self.retry_delay_spinbox = QSpinBox()
        self.retry_delay_spinbox.setRange(100, 5000)
        self.retry_delay_spinbox.setValue(1000)
        self.retry_delay_spinbox.setSuffix(" мс")
        retry_layout.addWidget(self.retry_delay_spinbox)
        retry_layout.addStretch()
        performance_layout.addLayout(retry_layout)
        
        performance_group.setLayout(performance_layout)
        settings_layout.addWidget(performance_group)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # Кнопки управления
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("Начать сортировку")
        self.start_btn.clicked.connect(self.start_organization)
        button_layout.addWidget(self.start_btn)
        
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.cancel_organization)
        self.cancel_btn.setEnabled(False)
        button_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(button_layout)
        
        # Прогресс бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # Логи
        log_group = QGroupBox("Логирование")
        log_layout = QVBoxLayout()
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # Статус бар
        self.statusBar().showMessage("Готово к работе")
        
        # Активируем поля суффикса по умолчанию
        self.on_suffix_check_changed(Qt.Unchecked)
        
    def on_suffix_check_changed(self, state):
        """Активация/деактивация поля суффикса и дополнительной опции"""
        enabled = state == Qt.Checked
        self.suffix_input.setEnabled(enabled)
        self.check_without_suffix_check.setEnabled(enabled)
        
    def browse_source(self):
        directory = QFileDialog.getExistingDirectory(self, "Выберите папку с исходными фотографиями")
        if directory:
            self.source_input.setText(directory)
    
    def browse_export(self):
        directory = QFileDialog.getExistingDirectory(self, "Выберите папку с экспортированными фотографиями")
        if directory:
            self.export_input.setText(directory)
            
            # Предлагаем выходную папку по умолчанию
            if not self.output_input.text():
                self.output_input.setText(directory + "_organized")
    
    def browse_output(self):
        directory = QFileDialog.getExistingDirectory(self, "Выберите выходную папку")
        if directory:
            self.output_input.setText(directory)
    
    def append_log_message(self, message, color):
        """Добавление сообщения в лог с указанным цветом"""
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        format = cursor.charFormat()
        format.setForeground(QColor(color))
        cursor.setCharFormat(format)
        
        cursor.insertText(message + "\n")
        self.log_output.setTextCursor(cursor)
        self.log_output.ensureCursorVisible()
    
    def start_organization(self):
        # Проверка входных данных
        source_dir = self.source_input.text()
        export_dir = self.export_input.text()
        output_dir = self.output_input.text()
        
        if not source_dir or not os.path.exists(source_dir):
            QMessageBox.warning(self, "Ошибка", "Укажите действительную папку с исходными фотографиями")
            return
        
        if not export_dir or not os.path.exists(export_dir):
            QMessageBox.warning(self, "Ошибка", "Укажите действительную папку с экспортированными фотографиями")
            return
        
        if not output_dir:
            QMessageBox.warning(self, "Ошибка", "Укажите выходную папку")
            return
        
        # Получение настроек
        use_suffix = self.suffix_check.isChecked()
        suffix_text = self.suffix_input.text()
        check_without_suffix = self.check_without_suffix_check.isChecked()
        compare_metadata = self.metadata_check.isChecked()
        max_workers = self.threads_spinbox.value()
        buffer_size_kb = self.buffer_size_spinbox.value()
        max_retries = self.retry_spinbox.value()
        retry_delay = self.retry_delay_spinbox.value() / 1000
        
        # Получаем выбранные расширения исходных файлов
        source_extensions = []
        for ext, checkbox in self.extension_checks.items():
            if checkbox.isChecked():
                source_extensions.append(ext)
        
        if not source_extensions:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы одно расширение для исходных файлов")
            return
        
        if use_suffix and not suffix_text:
            QMessageBox.warning(self, "Ошибка", "Укажите суффикс или снимите галочку")
            return
        
        # Очистка логов
        self.log_output.clear()
        self.append_log_message("Начало обработки...", "black")
        
        # Блокировка UI
        self.set_ui_enabled(False)
        
        # Запуск потока обработки
        self.organizer_thread = PhotoOrganizerThread(
            source_dir, export_dir, output_dir,
            use_suffix, suffix_text, check_without_suffix, 
            compare_metadata, max_workers, buffer_size_kb,
            max_retries, retry_delay, source_extensions
        )
        
        self.organizer_thread.log_signal.connect(self.append_log_message)
        self.organizer_thread.progress_signal.connect(self.progress_bar.setValue)
        self.organizer_thread.finished_signal.connect(self.organization_finished)
        
        self.organizer_thread.start()
    
    def cancel_organization(self):
        if self.organizer_thread and self.organizer_thread.isRunning():
            self.organizer_thread.cancel()
            self.organizer_thread.wait()
    
    def organization_finished(self, success, message):
        self.set_ui_enabled(True)
        self.progress_bar.setValue(100 if success else 0)
        color = "green" if success else "red"
        self.append_log_message(message, color)
        self.statusBar().showMessage(message)
        
        if success:
            QMessageBox.information(self, "Успех", message)
        else:
            QMessageBox.warning(self, "Ошибка", message)
    
    def set_ui_enabled(self, enabled):
        self.source_input.setEnabled(enabled)
        self.source_btn.setEnabled(enabled)
        self.export_input.setEnabled(enabled)
        self.export_btn.setEnabled(enabled)
        self.output_input.setEnabled(enabled)
        self.output_btn.setEnabled(enabled)
        self.suffix_check.setEnabled(enabled)
        self.suffix_input.setEnabled(enabled)
        self.check_without_suffix_check.setEnabled(enabled)
        self.metadata_check.setEnabled(enabled)
        
        # Убрана настройка hash_check
        
        for checkbox in self.extension_checks.values():
            checkbox.setEnabled(enabled)
            
        self.threads_spinbox.setEnabled(enabled)
        self.buffer_size_spinbox.setEnabled(enabled)
        self.retry_spinbox.setEnabled(enabled)
        self.retry_delay_spinbox.setEnabled(enabled)
        self.start_btn.setEnabled(enabled)
        self.cancel_btn.setEnabled(not enabled)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PhotoOrganizerApp()
    window.show()
    sys.exit(app.exec_())