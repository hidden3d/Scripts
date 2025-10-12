import os
import sys
import json
import re
import platform
import subprocess
from pathlib import Path
from collections import defaultdict
import ast
import datetime
import logging

import OpenEXR
import Imath
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QLineEdit, QPushButton, QListWidget, 
                             QTextEdit, QLabel, QFileDialog, QMessageBox,
                             QListWidgetItem, QColorDialog, QDialog, QDialogButtonBox,
                             QFormLayout, QComboBox, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView, QMenu, QAction, QTabWidget,
                             QSplitter, QTextBrowser, QScrollArea, QCheckBox)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QSettings
from PyQt5.QtGui import QTextCursor, QColor, QTextCharFormat, QFont, QBrush

# ==================== НАСТРОЙКИ ====================
DEBUG = True  # Включаем логирование для отладки
DEFAULT_FONT_SIZE = 10  # Размер шрифта по умолчанию
DEFAULT_COLUMN_WIDTHS = {  # Ширины столбцов по умолчанию
    'sequences': [200, 300, 80, 100, 100],  # Путь, Имя, Расширение, Диапазон, Количество
    'metadata': [300, 500]  # Поле, Значение
}
# ===================================================

# Попытка импорта exifread для чтения метаданных изображений
try:
    import exifread
    EXIFREAD_AVAILABLE = True
except ImportError:
    EXIFREAD_AVAILABLE = False
    print("Библиотека exifread не установлена. Метаданные для JPEG/RAW файлов не будут доступны.")
    print("Установите ее: pip install exifread")

# Попытка импорта Pillow для чтения метаданных PNG, TIFF и других форматов
try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("Библиотека Pillow не установлена. Метаданные для PNG/TIFF файлов не будут доступны.")
    print("Установите ее: pip install Pillow")

# Попытка импорта pymediainfo для чтения метаданных медиафайлов
try:
    from pymediainfo import MediaInfo
    PYMEDIAINFO_AVAILABLE = True
except ImportError:
    PYMEDIAINFO_AVAILABLE = False
    print("Библиотека pymediainfo не установлена. Расширенные метаданные для медиафайлов не будут доступны.")
    print("Установите ее: pip install pymediainfo")


class DebugLogger:
    """Класс для сбора отладочной информации"""
    
    def __init__(self, debug_enabled=DEBUG):
        self.debug_enabled = debug_enabled
        self.log_messages = []
        self.max_log_size = 10000  # Максимальное количество сообщений в логе
        
    def log(self, message, level="INFO"):
        """Добавляет сообщение в лог"""
        if not self.debug_enabled:
            return
            
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] [{level}] {message}"
        self.log_messages.append(log_entry)
        
        # Ограничиваем размер лога
        if len(self.log_messages) > self.max_log_size:
            self.log_messages = self.log_messages[-self.max_log_size:]
        
    def get_log_text(self):
        """Возвращает весь лог как текст"""
        return "\n".join(self.log_messages)
    
    def clear_log(self):
        """Очищает лог"""
        self.log_messages = []
    
    def set_debug_enabled(self, enabled):
        """Включает/выключает логирование"""
        self.debug_enabled = enabled


class LogViewerDialog(QDialog):
    """Диалог для просмотра логов"""
    
    def __init__(self, debug_logger, parent=None):
        super().__init__(parent)
        self.debug_logger = debug_logger
        self.setup_ui()
        
    def setup_ui(self):
        self.setWindowTitle("Лог приложения")
        self.setGeometry(300, 300, 800, 600)
        
        layout = QVBoxLayout()
        
        # Панель управления
        control_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Обновить")
        self.clear_btn = QPushButton("Очистить лог")
        self.save_btn = QPushButton("Сохранить в файл")
        
        self.refresh_btn.clicked.connect(self.refresh_log)
        self.clear_btn.clicked.connect(self.clear_log)
        self.save_btn.clicked.connect(self.save_log)
        
        control_layout.addWidget(self.refresh_btn)
        control_layout.addWidget(self.clear_btn)
        control_layout.addWidget(self.save_btn)
        control_layout.addStretch()
        
        # Текстовое поле для лога
        self.log_text = QTextBrowser()
        self.log_text.setFont(QFont("Courier", 9))
        self.log_text.setLineWrapMode(QTextEdit.NoWrap)
        
        layout.addLayout(control_layout)
        layout.addWidget(self.log_text)
        
        self.setLayout(layout)
        self.refresh_log()
        
    def refresh_log(self):
        """Обновляет содержимое лога"""
        self.log_text.setPlainText(self.debug_logger.get_log_text())
        # Прокручиваем вниз
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)
        
    def clear_log(self):
        """Очищает лог"""
        self.debug_logger.clear_log()
        self.refresh_log()
        
    def save_log(self):
        """Сохраняет лог в файл"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Сохранить лог", "exr_viewer_log.txt", "Text Files (*.txt)"
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.debug_logger.get_log_text())
                QMessageBox.information(self, "Успех", "Лог сохранен в файл")
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить лог: {str(e)}")


class SequenceFinder(QThread):
    sequence_found = pyqtSignal(dict)
    progress_update = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, directory, debug_logger):
        super().__init__()
        self.directory = directory
        self.debug_logger = debug_logger
        self._is_running = True
        # Ищем все файлы, независимо от расширения
        self.supported_extensions = set()  # Пустое множество означает все файлы
        # Видео расширения, которые всегда считаем одиночными
        self.video_extensions = {'.mov', '.mp4', '.avi', '.mkv', '.wmv', '.flv', '.webm', 
                               '.m4v', '.mpg', '.mpeg', '.m2v', '.m4v', '.3gp', '.3g2', 
                               '.f4v', '.ogv', '.ts', '.mts', '.m2ts', '.mxf'}

    def stop(self):
        self._is_running = False

    def continue_search(self):
        self._is_running = True

    def find_sequences_in_directory(self, directory):
        """Находит последовательности файлов в конкретной директории"""
        files_by_extension = defaultdict(list)
        
        try:
            files = os.listdir(directory)
            self.debug_logger.log(f"find_sequences_in_directory: В папке {directory} найдено {len(files)} файлов/папок")
        except PermissionError:
            self.debug_logger.log(f"find_sequences_in_directory: Нет доступа к папке {directory}", "WARNING")
            return {}
            
        for file in files:
            if not self._is_running:
                break
                
            file_path = os.path.join(directory, file)
            if os.path.isfile(file_path):
                # Получаем расширение файла
                _, ext = os.path.splitext(file)
                ext = ext.lower()
                
                # Обрабатываем все файлы, независимо от расширения
                self.progress_update.emit(f"Обработка: {file}")
                
                # Для ВСЕХ файлов извлекаем базовое имя и номер кадра
                base_name, frame_num = self.extract_sequence_info(file)
                self.debug_logger.log(f"  Файл: {file} -> base_name: {base_name}, frame_num: {frame_num}")
                
                files_by_extension[ext].append((base_name, frame_num, file_path, file))
        
        self.debug_logger.log(f"find_sequences_in_directory: Для папки {directory} найдено:")
        for ext, files in files_by_extension.items():
            self.debug_logger.log(f"    {ext}: {len(files)} файлов")
        
        return files_by_extension

    def find_sequences_recursive(self, directory):
        """Рекурсивно ищет последовательности файлов во всех подпапках"""
        all_sequences = {}
        
        # Сначала ищем в текущей директории
        files_by_extension = self.find_sequences_in_directory(directory)
        
        # Формируем последовательности для текущей папки
        sequences = self.form_sequences(files_by_extension, directory)
        all_sequences.update(sequences)
        
        # Эмитируем найденные последовательности сразу
        for seq_name, seq_info in sequences.items():
            if not self._is_running:
                break
            
            # Формируем данные для таблицы
            sequence_data = {
                'path': seq_info['path'],
                'name': seq_info['display_name'],
                'frame_range': seq_info['frame_range'],
                'frame_count': len(seq_info['files']),
                'files': seq_info['files'],
                'extension': seq_info['extension'],
                'type': seq_info['type']
            }
            
            self.sequence_found.emit(sequence_data)
            
        if not self._is_running:
            return all_sequences
            
        # Затем рекурсивно в подпапках
        try:
            for item in os.listdir(directory):
                if not self._is_running:
                    break
                    
                item_path = os.path.join(directory, item)
                if os.path.isdir(item_path):
                    self.progress_update.emit(f"Поиск в папке: {item}")
                    sub_sequences = self.find_sequences_recursive(item_path)
                    all_sequences.update(sub_sequences)
        except PermissionError:
            pass
            
        return all_sequences

    def form_sequences(self, files_by_extension, directory):
        """Формирует последовательности из найденных файлов"""
        sequences = {}
        self.debug_logger.log(f"form_sequences: Начало формирования последовательностей для {directory}")
        
        # Обрабатываем каждый тип расширений отдельно
        for ext, files_list in files_by_extension.items():
            self.debug_logger.log(f"  Обрабатываем расширение {ext}: {len(files_list)} файлов")
            
            # Для видеофайлов каждый файл - отдельная последовательность
            if ext in self.video_extensions:
                self.debug_logger.log(f"    Расширение {ext} является видео, обрабатываем каждый файл отдельно")
                for base_name, frame_num, file_path, file_name in files_list:
                    # Создаем отдельную последовательность для каждого видеофайла
                    unique_key = f"{directory}/{file_name}"
                    
                    sequences[unique_key] = {
                        'files': [file_path],
                        'frames': [],  # Для видео нет номеров кадров
                        'first_file': file_path,
                        'frame_range': "одиночный файл",
                        'path': directory,
                        'display_name': file_name,
                        'extension': ext,
                        'type': f'video_single_{ext[1:]}',
                        'frame_count': 1
                    }
                    
                    self.debug_logger.log(f"      Создана видео-последовательность: {unique_key}")
                continue  # Переходим к следующему расширению
            
            # Для НЕ-видео файлов используем логику группировки по базовому имени
            files_by_base_name = defaultdict(list)
            for base_name, frame_num, file_path, file_name in files_list:
                # Для группировки используем base_name только если есть frame_num
                # Если frame_num None, то это одиночный файл
                if frame_num is not None:
                    group_key = base_name
                else:
                    # Для файлов без номера кадра используем полное имя как ключ группы
                    group_key = file_name
                files_by_base_name[group_key].append((frame_num, file_path, file_name))
                self.debug_logger.log(f"    Файл {file_name} -> базовая группа: '{group_key}', номер кадра: {frame_num}")
            
            # Формируем последовательности для каждой группы
            for group_key, files in files_by_base_name.items():
                self.debug_logger.log(f"    Формируем последовательность для группы: '{group_key}'")
                self.debug_logger.log(f"      Файлов в группе: {len(files)}")
                
                if len(files) == 1:
                    # Одиночный файл
                    frame_num, file_path, file_name = files[0]
                    unique_key = f"{directory}/{file_name}"
                    
                    sequences[unique_key] = {
                        'files': [file_path],
                        'frames': [frame_num] if frame_num is not None else [],
                        'first_file': file_path,
                        'frame_range': "одиночный файл",
                        'path': directory,
                        'display_name': file_name,
                        'extension': ext,
                        'type': f'single_{ext[1:]}',
                        'frame_count': 1
                    }
                    self.debug_logger.log(f"      Создан одиночный файл: {unique_key}")
                    
                else:
                    # Группа файлов - потенциальная последовательность
                    # Сортируем файлы по номеру кадра
                    files.sort(key=lambda x: x[0] if x[0] is not None else -1)
                    frame_numbers = [f[0] for f in files if f[0] is not None]  # Только валидные номера кадров
                    file_paths = [f[1] for f in files]
                    file_names = [f[2] for f in files]
                    
                    self.debug_logger.log(f"      Файлы: {file_names}")
                    self.debug_logger.log(f"      Номера кадров: {frame_numbers}")
                    
                    # Проверяем, является ли это последовательностью
                    if self.is_sequence(frame_numbers):
                        # Это последовательность
                        seq_type = f'sequence_{ext[1:]}'
                        
                        # Формируем диапазон кадров
                        if frame_numbers:
                            min_frame = min(frame_numbers)
                            max_frame = max(frame_numbers)
                            
                            # Определяем количество цифр для форматирования
                            max_digits = max(len(str(f)) for f in frame_numbers)
                            
                            # Если все номера кадров имеют одинаковую длину или есть ведущие нули
                            if all(len(str(f)) == max_digits for f in frame_numbers) or any(len(str(f)) < max_digits for f in frame_numbers):
                                frame_range = f"{min_frame:0{max_digits}d}-{max_frame:0{max_digits}d}"
                            else:
                                frame_range = f"{min_frame}-{max_frame}"
                        else:
                            frame_range = "одиночный файл"
                    else:
                        # Это не последовательность, а группа одиночных файлов
                        seq_type = f'group_{ext[1:]}'
                        frame_range = "группа файлов"
                    
                    # Имя последовательности - имя первого файла
                    display_name = file_names[0]
                    
                    # Используем путь + имя группы как ключ для уникальности
                    unique_key = f"{directory}/{group_key}"
                    
                    sequences[unique_key] = {
                        'files': file_paths,
                        'frames': frame_numbers,
                        'first_file': file_paths[0],
                        'frame_range': frame_range,
                        'path': directory,
                        'display_name': display_name,
                        'extension': ext,
                        'type': seq_type,
                        'frame_count': len(files)
                    }
                    
                    self.debug_logger.log(f"      Сформирована последовательность/группа:")
                    self.debug_logger.log(f"        Ключ: {unique_key}")
                    self.debug_logger.log(f"        Имя: {display_name}")
                    self.debug_logger.log(f"        Расширение: {ext}")
                    self.debug_logger.log(f"        Диапазон: {frame_range}")
                    self.debug_logger.log(f"        Количество файлов: {len(files)}")
                    self.debug_logger.log(f"        Тип: {seq_type}")
        
        self.debug_logger.log(f"form_sequences: Сформировано {len(sequences)} последовательностей")
        return sequences


    def extract_sequence_info(self, filename):
        """Извлекает базовое имя и номер кадра из имени файла"""
        # Убираем расширение
        name_without_ext = os.path.splitext(filename)[0]
        
        self.debug_logger.log(f"extract_sequence_info: Обрабатываем файл '{filename}' -> '{name_without_ext}'")
        
        # УЛУЧШЕННЫЙ список паттернов для лучшего распознавания DNG и других форматов
        patterns = [
            # 1. ПАТТЕРНЫ ДЛЯ ФОРМАТА ТИПА D003C0015_250121_8H3408 (DNG файлы)
            
            # 1.1. Паттерн для формата с префиксом и 4+ цифрами перед датой
            r'^(.+?[A-Z])(\d{4,})_\d+_.+$',
            
            # 1.2. Паттерн для чисел после определенных префиксов (C, A, R, S, F и т.д.)
            r'^(.+?[ACFRS])(\d{3,5})_.*$',
            
            # 2. ПАТТЕРНЫ ДЛЯ СТАНДАРТНЫХ НОМЕРОВ КАДРОВ (ВЫСОКИЙ ПРИОРИТЕТ)
            
            # 2.1. Числа в самом конце имени (перед расширением) - самый распространенный случай
            r'^(.+?)(\d{1,8})$',
            
            # 2.2. Числа перед точкой или разделителем в конце имени (name.0001, name_0001)
            r'^(.+?)[._ -](\d{1,8})$',
            
            # 2.3. Числа с фиксированной длиной в конце (типичные номера кадров)
            r'^(.+?)(\d{4,8})([^0-9]*)$',
            
            # 3. ПАТТЕРНЫ ДЛЯ СЛОЖНЫХ ФОРМАТОВ
            
            # 3.1. Паттерн для чисел, окруженных нецифровыми символами
            r'^(.+?[^0-9])(\d{3,5})([^0-9].*)$',
        ]
        
        # Сначала пробуем все паттерны по порядку
        for i, pattern in enumerate(patterns):
            match = re.match(pattern, name_without_ext)
            if match:
                base_name = match.group(1)
                frame_num_str = match.group(2)
                
                try:
                    frame_num = int(frame_num_str)
                    self.debug_logger.log(f"extract_sequence_info: '{filename}' -> pattern {i+1} '{pattern}': base_name='{base_name}', frame_num={frame_num}")
                    return base_name, frame_num
                except ValueError:
                    continue
        
        # РЕЗЕРВНЫЕ ПАТТЕРНЫ
        all_numbers = re.findall(r'\d+', name_without_ext)
        if all_numbers:
            # Ищем числа с 3-6 цифрами (типичные номера кадров)
            frame_candidates = []
            for number in all_numbers:
                if 3 <= len(number) <= 6:
                    frame_candidates.append(number)
            
            # Берем ПЕРВОЕ подходящее число (самое левое)
            if frame_candidates:
                frame_num_str = frame_candidates[0]
                frame_pos = name_without_ext.find(frame_num_str)
                if frame_pos > 0:
                    base_name = name_without_ext[:frame_pos]
                    try:
                        frame_num = int(frame_num_str)
                        self.debug_logger.log(f"extract_sequence_info: '{filename}' -> fallback filtered numbers: base_name='{base_name}', frame_num={frame_num}")
                        return base_name, frame_num
                    except ValueError:
                        pass
            
            # Если не нашли подходящих по длине, берем первое число
            first_number = all_numbers[0]
            first_number_pos = name_without_ext.find(first_number)
            if first_number_pos > 0:
                base_name = name_without_ext[:first_number_pos]
                try:
                    frame_num = int(first_number)
                    self.debug_logger.log(f"extract_sequence_info: '{filename}' -> fallback first number: base_name='{base_name}', frame_num={frame_num}")
                    return base_name, frame_num
                except ValueError:
                    pass
        
        # Если не нашли номер кадра, возвращаем полное имя как базовое
        result = (name_without_ext, None)
        self.debug_logger.log(f"extract_sequence_info: '{filename}' -> fallback: base_name='{name_without_ext}', frame_num=None")
        return result


    def is_sequence(self, frame_numbers):
        """Проверяет, являются ли номера кадров последовательными"""
        if len(frame_numbers) < 2:
            return False
        
        # Фильтруем None значения (одиночные файлы)
        valid_frames = [f for f in frame_numbers if f is not None]
        if len(valid_frames) < 2:
            return False
        
        sorted_frames = sorted(valid_frames)
        
        # Проверяем, что разница между кадрами постоянная
        differences = [sorted_frames[i] - sorted_frames[i-1] for i in range(1, len(sorted_frames))]
        unique_differences = set(differences)
        
        # Допускаем последовательности с постоянным шагом (1, 2, 10 и т.д.)
        return len(unique_differences) == 1

    def run(self):
        try:
            self.find_sequences_recursive(self.directory)
        except Exception as e:
            self.debug_logger.log(f"Ошибка в потоке поиска: {e}", "ERROR")
        finally:
            self.finished_signal.emit()



class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Управление цветами")
        self.setGeometry(200, 200, 800, 600)
        
        layout = QVBoxLayout()
        
        # Создаем вкладки
        self.tabs = QTabWidget()
        
        # Вкладка цветов метаданных
        self.metadata_tab = QWidget()
        self.setup_metadata_tab()
        self.tabs.addTab(self.metadata_tab, "Цвета метаданных")
        
        # Вкладка цветов последовательностей
        self.sequences_tab = QWidget()
        self.setup_sequences_tab()
        self.tabs.addTab(self.sequences_tab, "Цвета последовательностей")
        
        layout.addWidget(self.tabs)
        
        # Кнопки диалога
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout.addWidget(button_box)
        self.setLayout(layout)
        
        self.load_current_settings()

    def setup_metadata_tab(self):
        # Создаем табы для активных и удаленных полей метаданных
        layout = QVBoxLayout()
        metadata_tabs = QTabWidget()
        
        # Вкладка активных полей
        self.active_tab = QWidget()
        self.setup_active_metadata_tab()
        metadata_tabs.addTab(self.active_tab, "Активные поля")
        
        # Вкладка корзины
        self.trash_tab = QWidget()
        self.setup_trash_metadata_tab()
        metadata_tabs.addTab(self.trash_tab, "Корзина")
        
        layout.addWidget(metadata_tabs)
        self.metadata_tab.setLayout(layout)

    def setup_active_metadata_tab(self):
        layout = QVBoxLayout()
        
        # Добавление нового поля
        form_layout = QFormLayout()
        
        self.field_input = QLineEdit()
        self.add_button = QPushButton("Добавить поле и выбрать цвет")
        self.add_button.clicked.connect(self.add_field_with_color)
        
        form_layout.addRow("Поле метаданных:", self.field_input)
        form_layout.addRow("", self.add_button)
        
        # Список активных полей с кнопками управления порядком
        layout.addWidget(QLabel("Активные поля (порядок отображения):"))
        
        # Панель кнопок управления порядком
        order_buttons_layout = QHBoxLayout()
        self.move_up_btn = QPushButton("Вверх")
        self.move_down_btn = QPushButton("Вниз")
        self.move_top_btn = QPushButton("В начало")
        self.move_bottom_btn = QPushButton("В конец")
        
        self.move_up_btn.clicked.connect(self.move_field_up)
        self.move_down_btn.clicked.connect(self.move_field_down)
        self.move_top_btn.clicked.connect(self.move_field_top)
        self.move_bottom_btn.clicked.connect(self.move_field_bottom)
        
        order_buttons_layout.addWidget(self.move_up_btn)
        order_buttons_layout.addWidget(self.move_down_btn)
        order_buttons_layout.addWidget(self.move_top_btn)
        order_buttons_layout.addWidget(self.move_bottom_btn)
        order_buttons_layout.addStretch()
        
        self.active_list = QListWidget()
        self.active_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.active_list.customContextMenuRequested.connect(self.show_active_list_context_menu)
        
        # Кнопка удаления выбранного
        self.delete_active_btn = QPushButton("Удалить выбранное")
        self.delete_active_btn.clicked.connect(self.delete_selected_active)
        
        layout.addLayout(form_layout)
        layout.addLayout(order_buttons_layout)
        layout.addWidget(self.active_list)
        layout.addWidget(self.delete_active_btn)
        
        self.active_tab.setLayout(layout)

    def setup_trash_metadata_tab(self):
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel("Удаленные поля:"))
        self.trash_list = QListWidget()
        self.trash_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.trash_list.customContextMenuRequested.connect(self.show_trash_list_context_menu)
        
        # Кнопки управления корзиной
        buttons_layout = QHBoxLayout()
        self.restore_btn = QPushButton("Восстановить выбранное")
        self.delete_permanently_btn = QPushButton("Удалить окончательно")
        self.empty_trash_btn = QPushButton("Очистить корзину")
        
        self.restore_btn.clicked.connect(self.restore_selected)
        self.delete_permanently_btn.clicked.connect(self.delete_permanently_selected)
        self.empty_trash_btn.clicked.connect(self.empty_trash)
        
        buttons_layout.addWidget(self.restore_btn)
        buttons_layout.addWidget(self.delete_permanently_btn)
        buttons_layout.addWidget(self.empty_trash_btn)
        
        layout.addWidget(self.trash_list)
        layout.addLayout(buttons_layout)
        
        self.trash_tab.setLayout(layout)

    def setup_sequences_tab(self):
        layout = QVBoxLayout()
        
        # Добавление нового типа последовательности
        form_layout = QFormLayout()
        
        self.sequence_type_input = QLineEdit()
        self.sequence_type_input.setPlaceholderText("Например: exr_sequence, video_single_mov")
        self.add_sequence_color_btn = QPushButton("Добавить тип и выбрать цвет")
        self.add_sequence_color_btn.clicked.connect(self.add_sequence_type_with_color)
        
        form_layout.addRow("Тип последовательности:", self.sequence_type_input)
        form_layout.addRow("", self.add_sequence_color_btn)
        
        # Список активных цветов последовательностей
        layout.addWidget(QLabel("Цвета последовательностей:"))
        self.sequences_list = QListWidget()
        self.sequences_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sequences_list.customContextMenuRequested.connect(self.show_sequences_list_context_menu)
        
        # Кнопка удаления выбранного
        self.delete_sequence_btn = QPushButton("Удалить выбранное")
        self.delete_sequence_btn.clicked.connect(self.delete_selected_sequence)
        
        layout.addLayout(form_layout)
        layout.addWidget(self.sequences_list)
        layout.addWidget(self.delete_sequence_btn)
        
        self.sequences_tab.setLayout(layout)

    def load_current_settings(self):
        """Загружает текущие настройки из родительского окна"""
        # Загружаем активные поля метаданных в правильном порядке
        self.active_list.clear()
        for field_name in self.parent.ordered_metadata_fields:
            if field_name in self.parent.color_metadata:
                color_data = self.parent.color_metadata[field_name]
                if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                    if not color_data.get('removed', False):
                        color = QColor(color_data['r'], color_data['g'], color_data['b'])
                        item = QListWidgetItem(field_name)
                        item.setBackground(color)
                        self.active_list.addItem(item)
        
        # Загружаем корзину метаданных
        self.trash_list.clear()
        for field_name, color_data in self.parent.removed_metadata.items():
            if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                color = QColor(color_data['r'], color_data['g'], color_data['b'])
                item = QListWidgetItem(field_name)
                item.setBackground(color)
                self.trash_list.addItem(item)
        
        # Загружаем цвета последовательностей
        self.sequences_list.clear()
        for seq_type, color_data in self.parent.sequence_colors.items():
            if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                color = QColor(color_data['r'], color_data['g'], color_data['b'])
                item = QListWidgetItem(seq_type)
                item.setBackground(color)
                self.sequences_list.addItem(item)

    def add_field_with_color(self):
        field_name = self.field_input.text().strip()
        if not field_name:
            QMessageBox.warning(self, "Ошибка", "Введите название поля")
            return
        
        # Проверяем, нет ли уже такого поля в активных
        for i in range(self.active_list.count()):
            if self.active_list.item(i).text() == field_name:
                QMessageBox.warning(self, "Ошибка", "Это поле уже добавлено")
                return
        
        # Проверяем, нет ли в корзине
        for i in range(self.trash_list.count()):
            if self.trash_list.item(i).text() == field_name:
                reply = QMessageBox.question(self, "Восстановить поле", 
                                           f"Поле '{field_name}' находится в корзине. Восстановить его?",
                                           QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.restore_field_from_trash(field_name)
                return
        
        # Выбираем цвет
        color = QColorDialog.getColor(QColor(200, 200, 255), self, "Выберите цвет для поля")
        if color.isValid():
            # Добавляем поле в активные
            self.parent.color_metadata[field_name] = {
                'r': color.red(),
                'g': color.green(), 
                'b': color.blue(),
                'removed': False
            }
            
            # Добавляем поле в конец списка порядка
            if field_name not in self.parent.ordered_metadata_fields:
                self.parent.ordered_metadata_fields.append(field_name)
            
            # Сохраняем настройки
            self.parent.save_settings()
            
            # Обновляем интерфейс
            self.load_current_settings()
            
            # Обновляем отображение метаданных
            self.parent.update_metadata_colors()
            
            self.field_input.clear()

    def add_sequence_type_with_color(self):
        seq_type = self.sequence_type_input.text().strip()
        if not seq_type:
            QMessageBox.warning(self, "Ошибка", "Введите тип последовательности")
            return
        
        # Проверяем, нет ли уже такого типа
        for i in range(self.sequences_list.count()):
            if self.sequences_list.item(i).text() == seq_type:
                QMessageBox.warning(self, "Ошибка", "Этот тип уже добавлен")
                return
        
        # Выбираем цвет
        color = QColorDialog.getColor(QColor(200, 200, 255), self, "Выберите цвет для типа последовательности")
        if color.isValid():
            # Добавляем тип в активные
            self.parent.sequence_colors[seq_type] = {
                'r': color.red(),
                'g': color.green(), 
                'b': color.blue()
            }
            
            # Сохраняем настройки
            self.parent.save_settings()
            
            # Обновляем интерфейс
            self.load_current_settings()
            
            # Обновляем отображение последовательностей
            self.parent.update_sequences_colors()
            
            self.sequence_type_input.clear()

    def delete_selected_active(self):
        current_row = self.active_list.currentRow()
        if current_row >= 0:
            field_name = self.active_list.item(current_row).text()
            self.move_field_to_trash(field_name)

    def delete_selected_sequence(self):
        current_row = self.sequences_list.currentRow()
        if current_row >= 0:
            seq_type = self.sequences_list.item(current_row).text()
            self.delete_sequence_type(seq_type)

    def move_field_to_trash(self, field_name):
        """Перемещает поле в корзину"""
        if field_name in self.parent.color_metadata:
            # Сохраняем цвет в корзине
            color_data = self.parent.color_metadata[field_name]
            self.parent.removed_metadata[field_name] = color_data
            
            # Удаляем из активных
            del self.parent.color_metadata[field_name]
            
            # Удаляем из списка порядка
            if field_name in self.parent.ordered_metadata_fields:
                self.parent.ordered_metadata_fields.remove(field_name)
            
            # Сохраняем настройки
            self.parent.save_settings()
            
            # Обновляем интерфейс
            self.load_current_settings()
            
            # Обновляем отображение метаданных
            self.parent.update_metadata_colors()

    def delete_sequence_type(self, seq_type):
        """Удаляет тип последовательности"""
        if seq_type in self.parent.sequence_colors:
            del self.parent.sequence_colors[seq_type]
            
            # Сохраняем настройки
            self.parent.save_settings()
            
            # Обновляем интерфейс
            self.load_current_settings()
            
            # Обновляем отображение последовательностей
            self.parent.update_sequences_colors()

    def restore_selected(self):
        current_row = self.trash_list.currentRow()
        if current_row >= 0:
            field_name = self.trash_list.item(current_row).text()
            self.restore_field_from_trash(field_name)

    def restore_field_from_trash(self, field_name):
        """Восстанавливает поле из корзины"""
        if field_name in self.parent.removed_metadata:
            # Возвращаем в активные
            color_data = self.parent.removed_metadata[field_name]
            self.parent.color_metadata[field_name] = color_data
            
            # Добавляем в конец списка порядка, если его там нет
            if field_name not in self.parent.ordered_metadata_fields:
                self.parent.ordered_metadata_fields.append(field_name)
            
            # Удаляем из корзины
            del self.parent.removed_metadata[field_name]
            
            # Сохраняем настройки
            self.parent.save_settings()
            
            # Обновляем интерфейс
            self.load_current_settings()
            
            # Обновляем отображение метаданных
            self.parent.update_metadata_colors()

    def delete_permanently_selected(self):
        current_row = self.trash_list.currentRow()
        if current_row >= 0:
            field_name = self.trash_list.item(current_row).text()
            self.delete_field_permanently(field_name)

    def delete_field_permanently(self, field_name):
        """Окончательно удаляет поле"""
        if field_name in self.parent.removed_metadata:
            del self.parent.removed_metadata[field_name]
            
            # Сохраняем настройки
            self.parent.save_settings()
            
            # Обновляем интерфейс
            self.load_current_settings()

    def empty_trash(self):
        """Очищает корзину"""
        reply = QMessageBox.question(self, "Очистить корзину", 
                                   "Вы уверены, что хотите окончательно удалить все поля из корзины?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.parent.removed_metadata.clear()
            
            # Сохраняем настройки
            self.parent.save_settings()
            
            # Обновляем интерфейс
            self.load_current_settings()

    def move_field_up(self):
        """Перемещает выбранное поле вверх в списке"""
        current_row = self.active_list.currentRow()
        if current_row > 0:
            field_name = self.active_list.item(current_row).text()
            # Обновляем порядок в родительском классе
            index = self.parent.ordered_metadata_fields.index(field_name)
            if index > 0:
                self.parent.ordered_metadata_fields[index], self.parent.ordered_metadata_fields[index-1] = \
                    self.parent.ordered_metadata_fields[index-1], self.parent.ordered_metadata_fields[index]
                self.parent.save_settings()
                self.load_current_settings()
                self.active_list.setCurrentRow(current_row - 1)

    def move_field_down(self):
        """Перемещает выбранное поле вниз в списке"""
        current_row = self.active_list.currentRow()
        if current_row >= 0 and current_row < self.active_list.count() - 1:
            field_name = self.active_list.item(current_row).text()
            # Обновляем порядок в родительском классе
            index = self.parent.ordered_metadata_fields.index(field_name)
            if index < len(self.parent.ordered_metadata_fields) - 1:
                self.parent.ordered_metadata_fields[index], self.parent.ordered_metadata_fields[index+1] = \
                    self.parent.ordered_metadata_fields[index+1], self.parent.ordered_metadata_fields[index]
                self.parent.save_settings()
                self.load_current_settings()
                self.active_list.setCurrentRow(current_row + 1)

    def move_field_top(self):
        """Перемещает выбранное поле в начало списка"""
        current_row = self.active_list.currentRow()
        if current_row > 0:
            field_name = self.active_list.item(current_row).text()
            # Обновляем порядок в родительском классе
            if field_name in self.parent.ordered_metadata_fields:
                self.parent.ordered_metadata_fields.remove(field_name)
                self.parent.ordered_metadata_fields.insert(0, field_name)
                self.parent.save_settings()
                self.load_current_settings()
                self.active_list.setCurrentRow(0)

    def move_field_bottom(self):
        """Перемещает выбранное поле в конец списка"""
        current_row = self.active_list.currentRow()
        if current_row >= 0 and current_row < self.active_list.count() - 1:
            field_name = self.active_list.item(current_row).text()
            # Обновляем порядок в родительском классе
            if field_name in self.parent.ordered_metadata_fields:
                self.parent.ordered_metadata_fields.remove(field_name)
                self.parent.ordered_metadata_fields.append(field_name)
                self.parent.save_settings()
                self.load_current_settings()
                self.active_list.setCurrentRow(self.active_list.count() - 1)

    def show_active_list_context_menu(self, position):
        current_row = self.active_list.currentRow()
        if current_row >= 0:
            field_name = self.active_list.item(current_row).text()
            
            menu = QMenu(self)
            
            change_color_action = menu.addAction("Изменить цвет")
            remove_action = menu.addAction("Удалить в корзину")
            
            action = menu.exec_(self.active_list.mapToGlobal(position))
            
            if action == change_color_action:
                self.change_field_color(field_name)
            elif action == remove_action:
                self.move_field_to_trash(field_name)

    def show_trash_list_context_menu(self, position):
        current_row = self.trash_list.currentRow()
        if current_row >= 0:
            field_name = self.trash_list.item(current_row).text()
            
            menu = QMenu(self)
            
            restore_action = menu.addAction("Восстановить")
            delete_action = menu.addAction("Удалить окончательно")
            
            action = menu.exec_(self.trash_list.mapToGlobal(position))
            
            if action == restore_action:
                self.restore_field_from_trash(field_name)
            elif action == delete_action:
                self.delete_field_permanently(field_name)

    def show_sequences_list_context_menu(self, position):
        current_row = self.sequences_list.currentRow()
        if current_row >= 0:
            seq_type = self.sequences_list.item(current_row).text()
            
            menu = QMenu(self)
            
            change_color_action = menu.addAction("Изменить цвет")
            remove_action = menu.addAction("Удалить")
            
            action = menu.exec_(self.sequences_list.mapToGlobal(position))
            
            if action == change_color_action:
                self.change_sequence_color(seq_type)
            elif action == remove_action:
                self.delete_sequence_type(seq_type)

    def change_field_color(self, field_name):
        """Изменяет цвет поля"""
        if field_name in self.parent.color_metadata:
            current_color_data = self.parent.color_metadata[field_name]
            current_color = QColor(current_color_data['r'], current_color_data['g'], current_color_data['b'])
            
            color = QColorDialog.getColor(current_color, self, f"Выберите цвет для поля '{field_name}'")
            if color.isValid():
                self.parent.color_metadata[field_name] = {
                    'r': color.red(),
                    'g': color.green(),
                    'b': color.blue(),
                    'removed': False
                }
                
                # Сохраняем настройки
                self.parent.save_settings()
                
                # Обновляем интерфейс
                self.load_current_settings()
                
                # Обновляем отображение метаданных
                self.parent.update_metadata_colors()

    def change_sequence_color(self, seq_type):
        """Изменяет цвет типа последовательности"""
        if seq_type in self.parent.sequence_colors:
            current_color_data = self.parent.sequence_colors[seq_type]
            current_color = QColor(current_color_data['r'], current_color_data['g'], current_color_data['b'])
            
            color = QColorDialog.getColor(current_color, self, f"Выберите цвет для типа '{seq_type}'")
            if color.isValid():
                self.parent.sequence_colors[seq_type] = {
                    'r': color.red(),
                    'g': color.green(),
                    'b': color.blue()
                }
                
                # Сохраняем настройки
                self.parent.save_settings()
                
                # Обновляем интерфейс
                self.load_current_settings()
                
                # Обновляем отображение последовательностей
                self.parent.update_sequences_colors()


class EXRMetadataViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.sequences = {}
        self.current_sequence_files = []
        self.current_metadata = {}
        
        # Инициализация логгера
        self.debug_logger = DebugLogger(DEBUG)
        
        # Структуры данных для цветов
        self.color_metadata = {}  # {field_name: {'r': int, 'g': int, 'b': int, 'removed': False}}
        self.removed_metadata = {}  # {field_name: {'r': int, 'g': int, 'b': int, 'removed': True}}
        self.sequence_colors = {}  # {seq_type: {'r': int, 'g': int, 'b': int}}
        self.ordered_metadata_fields = []  # Порядок отображения полей метаданных
        
        self.settings_file = "exr_viewer_settings.json"
        self.load_settings()
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Universal File Sequence Metadata Viewer")
        self.setGeometry(100, 100, 1200, 800)
        
        # Устанавливаем шрифт приложения
        app_font = QFont()
        app_font.setPointSize(DEFAULT_FONT_SIZE)
        QApplication.setFont(app_font)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        
        # Панель выбора папки
        folder_layout = QHBoxLayout()
        self.folder_path = QLineEdit()
        self.browse_btn = QPushButton("Обзор")
        self.browse_btn.clicked.connect(self.browse_folder)
        
        folder_layout.addWidget(QLabel("Папка:"))
        folder_layout.addWidget(self.folder_path)
        folder_layout.addWidget(self.browse_btn)
        
        # Панель управления
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("СТАРТ")
        self.stop_btn = QPushButton("СТОП")
        self.continue_btn = QPushButton("ПРОДОЛЖИТЬ")
        self.settings_btn = QPushButton("Настройки цветов")
        
        # Добавляем галочку для включения/выключения логирования
        self.log_checkbox = QCheckBox("Логирование")
        self.log_checkbox.setChecked(DEBUG)  # По умолчанию выключено
        self.log_checkbox.stateChanged.connect(self.toggle_logging)
        
        self.log_btn = QPushButton("Лог")  # Новая кнопка для лога
        
        self.start_btn.clicked.connect(self.start_search)
        self.stop_btn.clicked.connect(self.stop_search)
        self.continue_btn.clicked.connect(self.continue_search)
        self.settings_btn.clicked.connect(self.open_settings)
        self.log_btn.clicked.connect(self.show_log)  # Подключаем показ лога
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.continue_btn)
        control_layout.addWidget(self.settings_btn)
        control_layout.addWidget(self.log_checkbox)  # Добавляем галочку
        control_layout.addWidget(self.log_btn)  # Добавляем кнопку лога
        control_layout.addStretch()
        
        # Создаем разделитель для таблиц
        splitter = QSplitter(Qt.Vertical)
        
        # Верхняя часть - таблица последовательностей
        sequences_widget = QWidget()
        sequences_layout = QVBoxLayout()
        sequences_layout.addWidget(QLabel("Найденные последовательности:"))
        
        self.sequences_table = QTableWidget()
        self.sequences_table.setColumnCount(5)
        self.sequences_table.setHorizontalHeaderLabels(["Путь", "Имя последовательности", "Расширение", "Диапазон", "Количество кадров"])
        
        # Устанавливаем ширины столбцов по умолчанию
        for i, width in enumerate(DEFAULT_COLUMN_WIDTHS['sequences']):
            self.sequences_table.setColumnWidth(i, width)
        
        # Настраиваем режимы изменения размеров столбцов
        # Только столбец "Путь" будет растягиваться, остальные - фиксированные
        self.sequences_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)  # Путь растягивается
        self.sequences_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)    # Имя - фиксированная
        self.sequences_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)    # Расширение - фиксированная
        self.sequences_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)    # Диапазон - фиксированная
        self.sequences_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)    # Количество - фиксированная
        
        # Устанавливаем фиксированные ширины для столбцов 1-4
        self.sequences_table.setColumnWidth(1, DEFAULT_COLUMN_WIDTHS['sequences'][1])
        self.sequences_table.setColumnWidth(2, DEFAULT_COLUMN_WIDTHS['sequences'][2])
        self.sequences_table.setColumnWidth(3, DEFAULT_COLUMN_WIDTHS['sequences'][3])
        self.sequences_table.setColumnWidth(4, DEFAULT_COLUMN_WIDTHS['sequences'][4])
        
        self.sequences_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sequences_table.setSortingEnabled(True)
        self.sequences_table.itemSelectionChanged.connect(self.on_sequence_selected)
        self.sequences_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sequences_table.customContextMenuRequested.connect(self.show_sequences_table_context_menu)
        
        sequences_layout.addWidget(self.sequences_table)
        sequences_widget.setLayout(sequences_layout)
        
        # Нижняя часть - таблица метаданных
        metadata_widget = QWidget()
        metadata_layout = QVBoxLayout()
        metadata_layout.addWidget(QLabel("Метаданные выбранной последовательности:"))
        
        self.metadata_table = QTableWidget()
        self.metadata_table.setColumnCount(2)
        self.metadata_table.setHorizontalHeaderLabels(["Поле", "Значение"])
        
        # Устанавливаем ширины столбцов по умолчанию
        for i, width in enumerate(DEFAULT_COLUMN_WIDTHS['metadata']):
            self.metadata_table.setColumnWidth(i, width)
        
        # Настраиваем режимы изменения размеров столбцов
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)    # Поле - фиксированная
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)  # Значение растягивается до конца
        
        # Устанавливаем фиксированную ширину для столбца "Поле"
        self.metadata_table.setColumnWidth(0, DEFAULT_COLUMN_WIDTHS['metadata'][0])
        
        self.metadata_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.metadata_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.metadata_table.customContextMenuRequested.connect(self.show_metadata_table_context_menu)
        
        # Поле поиска по метаданным
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Поиск по метаданным:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите текст для поиска...")
        self.search_input.textChanged.connect(self.filter_metadata)
        search_layout.addWidget(self.search_input)
        
        # Кнопка сброса поиска
        self.clear_search_btn = QPushButton("Очистить")
        self.clear_search_btn.clicked.connect(self.clear_search)
        search_layout.addWidget(self.clear_search_btn)
        
        metadata_layout.addWidget(self.metadata_table)
        metadata_layout.addLayout(search_layout)
        metadata_widget.setLayout(metadata_layout)
        
        # Добавляем виджеты в разделитель
        splitter.addWidget(sequences_widget)
        splitter.addWidget(metadata_widget)
        
        # Устанавливаем начальные размеры (верхняя часть - 40%, нижняя - 60%)
        splitter.setSizes([400, 600])
        
        # Поле прогресса
        self.progress_label = QLabel("Готов к работе")
        
        layout.addLayout(folder_layout)
        layout.addLayout(control_layout)
        layout.addWidget(self.progress_label)
        layout.addWidget(splitter)  # Добавляем разделитель вместо отдельных таблиц
        
        central_widget.setLayout(layout)
        
        # Изначально кнопки Стоп и Продолжить неактивны
        self.stop_btn.setEnabled(False)
        self.continue_btn.setEnabled(False)
        
        # Применяем выравнивание для таблицы последовательностей
        self.apply_sequences_table_alignment()

    def apply_sequences_table_alignment(self):
        """Применяет выравнивание для столбцов таблицы последовательностей"""
        # Устанавливаем выравнивание по правому краю для всех столбцов кроме первого
        for col in range(1, self.sequences_table.columnCount()):
            for row in range(self.sequences_table.rowCount()):
                item = self.sequences_table.item(row, col)
                if item:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        # Устанавливаем выравнивание для заголовков
        header = self.sequences_table.horizontalHeader()
        for col in range(1, self.sequences_table.columnCount()):
            header_item = self.sequences_table.horizontalHeaderItem(col)
            if header_item:
                header_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def toggle_logging(self, state):
        """Включает/выключает логирование"""
        enabled = state == Qt.Checked
        self.debug_logger.set_debug_enabled(enabled)
        if enabled:
            self.debug_logger.log("Логирование включено")
        else:
            self.debug_logger.log("Логирование выключено")

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с файлами")
        if folder:
            self.folder_path.setText(folder)

    def start_search(self):
        folder = self.folder_path.text()
        if not folder or not os.path.exists(folder):
            QMessageBox.warning(self, "Ошибка", "Укажите существующую папку")
            return
        
        self.debug_logger.log(f"=== НАЧАЛО ПОИСКА В ПАПКЕ: {folder} ===")
        
        # Полностью останавливаем и удаляем предыдущий поиск
        if hasattr(self, 'sequence_finder'):
            self.debug_logger.log("Останавливаем предыдущий поиск...")
            self.sequence_finder.stop()
            self.sequence_finder.wait(2000)
            try:
                self.sequence_finder.quit()
                self.sequence_finder.wait(1000)
            except:
                pass
            del self.sequence_finder
        
        # СБРАСЫВАЕМ СОРТИРОВКУ ТАБЛИЦЫ
        self.debug_logger.log("Сбрасываем сортировку таблицы...")
        self.sequences_table.setSortingEnabled(False)  # Временно отключаем сортировку
        
        # АБСОЛЮТНАЯ очистка всех данных
        self.debug_logger.log("Очищаем данные...")
        self.sequences_table.setRowCount(0)
        self.metadata_table.setRowCount(0)
        self.sequences.clear()
        self.current_sequence_files = []
        self.current_metadata = {}
        
        self.debug_logger.log(f"Таблица последовательностей очищена: {self.sequences_table.rowCount()} строк")
        self.debug_logger.log(f"Словарь sequences очищен: {len(self.sequences)} элементов")
        
        # ВКЛЮЧАЕМ СОРТИРОВКУ ОБРАТНО
        self.sequences_table.setSortingEnabled(True)
        
        # Принудительно обновляем интерфейс
        QApplication.processEvents()
        
        # Сбрасываем поиск
        self.clear_search()
        
        # Обновляем прогресс
        self.progress_label.setText("Начинаем поиск...")
        QApplication.processEvents()
        
        # Создаем новый поиск с новыми соединениями
        self.debug_logger.log("Создаем новый поиск...")
        self.sequence_finder = SequenceFinder(folder, self.debug_logger)
        self.sequence_finder.sequence_found.connect(self.on_sequence_found)
        self.sequence_finder.progress_update.connect(self.update_progress)
        self.sequence_finder.finished_signal.connect(self.on_search_finished)
        
        self.sequence_finder.start()
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.continue_btn.setEnabled(False)

    def stop_search(self):
        if hasattr(self, 'sequence_finder') and self.sequence_finder.isRunning():
            # Временно отключаем сортировку
            self.sequences_table.setSortingEnabled(False)
            self.sequence_finder.stop()
            self.stop_btn.setEnabled(False)
            self.continue_btn.setEnabled(True)
            self.progress_label.setText("Поиск приостановлен")
            # Включаем сортировку обратно
            self.sequences_table.setSortingEnabled(True)

    def continue_search(self):
        if hasattr(self, 'sequence_finder'):
            # Временно отключаем сортировку
            self.sequences_table.setSortingEnabled(False)
            self.sequence_finder.continue_search()
            self.sequence_finder.start()
            self.stop_btn.setEnabled(True)
            self.continue_btn.setEnabled(False)
            # Включаем сортировку обратно
            self.sequences_table.setSortingEnabled(True)

    def on_sequence_found(self, sequence_data):
        """Добавляет найденную последовательность в таблицу"""
        # ВРЕМЕННО ОТКЛЮЧАЕМ СОРТИРОВКУ ПРИ ДОБАВЛЕНИИ НОВЫХ ДАННЫХ
        was_sorting_enabled = self.sequences_table.isSortingEnabled()
        if was_sorting_enabled:
            self.sequences_table.setSortingEnabled(False)
        
        try:
            self.debug_logger.log(f"\n--- ПОЛУЧЕНА ПОСЛЕДОВАТЕЛЬНОСТЬ ---")
            self.debug_logger.log(f"Данные: {sequence_data}")
            
            # Проверяем, что данные корректны
            required_keys = ['path', 'name', 'frame_range', 'frame_count', 'files', 'extension', 'type']
            missing_keys = [key for key in required_keys if key not in sequence_data]
            if missing_keys:
                self.debug_logger.log(f"ОШИБКА: Отсутствуют ключи: {missing_keys}", "ERROR")
                return
                
            # Проверяем, что ключевые поля не пустые
            empty_fields = []
            for key in ['path', 'name', 'extension', 'frame_range']:
                if not sequence_data.get(key):
                    empty_fields.append(key)
            
            if empty_fields:
                self.debug_logger.log(f"ОШИБКА: Пустые поля: {empty_fields}", "ERROR")
                return
                    
            row = self.sequences_table.rowCount()
            self.debug_logger.log(f"Добавляем строку #{row} в таблицу")
            self.sequences_table.insertRow(row)
            
            # Путь
            path_item = QTableWidgetItem(sequence_data['path'])
            path_item.setFlags(path_item.flags() & ~Qt.ItemIsEditable)
            path_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)  # Выравнивание по левому краю
            self.sequences_table.setItem(row, 0, path_item)
            self.debug_logger.log(f"  Столбец 0 (Путь): '{sequence_data['path']}'")
            
            # Имя последовательности
            name_item = QTableWidgetItem(sequence_data['name'])
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            name_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)  # Выравнивание по правому краю
            self.sequences_table.setItem(row, 1, name_item)
            self.debug_logger.log(f"  Столбец 1 (Имя): '{sequence_data['name']}'")
            
            # Расширение
            ext_item = QTableWidgetItem(sequence_data['extension'])
            ext_item.setFlags(ext_item.flags() & ~Qt.ItemIsEditable)
            ext_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)  # Выравнивание по правому краю
            self.sequences_table.setItem(row, 2, ext_item)
            self.debug_logger.log(f"  Столбец 2 (Расширение): '{sequence_data['extension']}'")
            
            # Диапазон
            range_item = QTableWidgetItem(sequence_data['frame_range'])
            range_item.setFlags(range_item.flags() & ~Qt.ItemIsEditable)
            range_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)  # Выравнивание по правому краю
            self.sequences_table.setItem(row, 3, range_item)
            self.debug_logger.log(f"  Столбец 3 (Диапазон): '{sequence_data['frame_range']}'")
            
            # Количество кадров
            count_item = QTableWidgetItem()
            count_item.setData(Qt.DisplayRole, sequence_data['frame_count'])
            count_item.setFlags(count_item.flags() & ~Qt.ItemIsEditable)
            count_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)  # Выравнивание по правому краю
            self.sequences_table.setItem(row, 4, count_item)
            self.debug_logger.log(f"  Столбец 4 (Количество): '{sequence_data['frame_count']}'")
            
            # Сохраняем тип и файлы последовательности
            key = f"{sequence_data['path']}/{sequence_data['name']}"
            self.sequences[key] = {
                'files': sequence_data['files'],
                'type': sequence_data['type'],
                'extension': sequence_data['extension']
            }
            self.debug_logger.log(f"  Сохранено в словарь sequences с ключом: '{key}'")
            
            # Подкрашиваем строку в зависимости от типа
            self.color_row_by_type(row, sequence_data['type'])
            self.debug_logger.log(f"  Строка окрашена по типу: '{sequence_data['type']}'")
            
            # Проверяем, что все ячейки заполнены
            for col in range(5):
                item = self.sequences_table.item(row, col)
                if item is None:
                    self.debug_logger.log(f"  ВНИМАНИЕ: Ячейка ({row}, {col}) пустая!", "WARNING")
                else:
                    self.debug_logger.log(f"  Ячейка ({row}, {col}): '{item.text()}'")
            
            self.debug_logger.log(f"--- КОНЕЦ ДОБАВЛЕНИЯ ПОСЛЕДОВАТЕЛЬНОСТИ ---\n")
        
        finally:
            # ВОССТАНАВЛИВАЕМ СОРТИРОВКУ
            if was_sorting_enabled:
                self.sequences_table.setSortingEnabled(True)

    def color_row_by_type(self, row, seq_type):
        """Подкрашивает строку таблицы в зависимости от типа последовательности"""
        # Получаем цвет из настроек
        color_data = self.sequence_colors.get(seq_type)
        if color_data and isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
            color = QColor(color_data['r'], color_data['g'], color_data['b'])
        else:
            # Цвет по умолчанию - серый
            color = QColor(240, 240, 240)
        
        # Применяем цвет ко всей строке
        for col in range(self.sequences_table.columnCount()):
            item = self.sequences_table.item(row, col)
            if item:
                item.setBackground(color)

    def update_progress(self, message):
        self.progress_label.setText(message)

    def on_search_finished(self):
        self.progress_label.setText("Поиск завершен")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.continue_btn.setEnabled(False)
        
        # ПРИНУДИТЕЛЬНО ОБНОВЛЯЕМ ОТОБРАЖЕНИЕ ТАБЛИЦЫ
        self.sequences_table.viewport().update()
        
        # Применяем выравнивание после завершения поиска
        self.apply_sequences_table_alignment()
        
        self.debug_logger.log(f"=== ПОИСК ЗАВЕРШЕН ===")
        self.debug_logger.log(f"Всего последовательностей в таблице: {self.sequences_table.rowCount()}")
        self.debug_logger.log(f"Всего последовательностей в словаре: {len(self.sequences)}")
        
        # Принудительно обновляем интерфейс
        QApplication.processEvents()

    def on_sequence_selected(self):
        current_row = self.sequences_table.currentRow()
        if current_row < 0:
            return
        
        # Получаем данные из выбранной строки
        path_item = self.sequences_table.item(current_row, 0)
        name_item = self.sequences_table.item(current_row, 1)
        ext_item = self.sequences_table.item(current_row, 2)
        
        if not path_item or not name_item or not ext_item:
            return
            
        path = path_item.text()
        name = name_item.text()
        extension = ext_item.text()
        
        key = f"{path}/{name}"
        if key in self.sequences and self.sequences[key]['files']:
            self.current_sequence_files = self.sequences[key]['files']
            seq_type = self.sequences[key]['type']
            
            # Для всех файлов отображаем метаданные, если они доступны
            if self.current_sequence_files:
                self.display_metadata(self.current_sequence_files[0], extension)
            else:
                # Очищаем таблицу метаданных
                self.metadata_table.setRowCount(0)

    def display_metadata(self, file_path, extension):
        """Отображает метаданные для файла"""
        try:
            if not os.path.exists(file_path):
                self.metadata_table.setRowCount(1)
                self.metadata_table.setItem(0, 0, QTableWidgetItem("Ошибка"))
                self.metadata_table.setItem(0, 1, QTableWidgetItem(f"Файл не найден: {file_path}"))
                return
            
            # Собираем все метаданные
            self.current_metadata = {}
            
            # Для EXR файлов используем OpenEXR для чтения метаданных
            if extension.lower() == '.exr':
                try:
                    exr_file = OpenEXR.InputFile(file_path)
                    header = exr_file.header()
                    
                    for key, value in header.items():
                        self.current_metadata[key] = self.format_metadata_value(value)
                    self.debug_logger.log(f"Прочитано {len(header)} метаданных EXR из {file_path}")
                except Exception as e:
                    self.current_metadata["Ошибка чтения EXR"] = f"Не удалось прочитать EXR метаданные: {str(e)}"
                    self.debug_logger.log(f"Ошибка чтения EXR для {file_path}: {str(e)}", "ERROR")
            
            # Для JPEG и RAW файлов используем exifread
            elif extension.lower() in ['.jpg', '.jpeg', '.arw', '.cr2', '.dng', '.nef', '.tif', '.tiff'] and EXIFREAD_AVAILABLE:
                try:
                    with open(file_path, 'rb') as f:
                        tags = exifread.process_file(f, details=False)
                    
                    if tags:
                        for tag, value in tags.items():
                            # Форматируем значение для лучшего отображения
                            formatted_value = self.format_exif_value(tag, value)
                            self.current_metadata[f"EXIF {tag}"] = formatted_value
                        self.debug_logger.log(f"Прочитано {len(tags)} EXIF тегов из {file_path}")
                    else:
                        self.current_metadata["EXIF"] = "EXIF данные не найдены"
                        self.debug_logger.log(f"EXIF данные не найдены в {file_path}")
                except Exception as e:
                    self.current_metadata["Ошибка чтения EXIF"] = f"Не удалось прочитать EXIF метаданные: {str(e)}"
                    self.debug_logger.log(f"Ошибка чтения EXIF для {file_path}: {str(e)}", "ERROR")
            
            # Для PNG, TIFF и других изображений используем Pillow
            elif extension.lower() in ['.png', '.bmp', '.gif', '.webp'] and PILLOW_AVAILABLE:
                try:
                    with Image.open(file_path) as img:
                        # Получаем базовую информацию об изображении
                        self.current_metadata["Формат"] = img.format
                        self.current_metadata["Режим"] = img.mode
                        self.current_metadata["Размер"] = f"{img.width} x {img.height}"
                        
                        # Получаем EXIF данные, если они есть
                        exif_data = img._getexif()
                        if exif_data:
                            for tag_id, value in exif_data.items():
                                tag_name = TAGS.get(tag_id, tag_id)
                                formatted_value = self.format_exif_value(tag_name, value)
                                self.current_metadata[f"EXIF {tag_name}"] = formatted_value
                            self.debug_logger.log(f"Прочитано {len(exif_data)} EXIF тегов из {file_path}")
                        else:
                            self.current_metadata["EXIF"] = "EXIF данные не найдены"
                            self.debug_logger.log(f"EXIF данные не найдены в {file_path}")
                        
                        # Получаем другую информацию
                        info = img.info
                        for key, value in info.items():
                            if key != 'exif':  # EXIF уже обработали отдельно
                                self.current_metadata[key] = str(value)
                except Exception as e:
                    self.current_metadata["Ошибка чтения"] = f"Не удалось прочитать метаданные изображения: {str(e)}"
                    self.debug_logger.log(f"Ошибка чтения изображения для {file_path}: {str(e)}", "ERROR")
            
            # ==================== ДОБАВЛЯЕМ PYMEDIAINFO ДЛЯ МЕДИАФАЙЛОВ ====================
            
            # Используем pymediainfo для видео, аудио и других медиафайлов
            if PYMEDIAINFO_AVAILABLE:
                # Определяем, является ли файл медиафайлом (видео, аудио, изображения)
                media_extensions = [
                    # Видео форматы
                    '.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg',
                    '.m2v', '.m4v', '.3gp', '.3g2', '.f4v', '.ogv', '.ts', '.mts', '.m2ts',
                    # Аудио форматы
                    '.mp3', '.wav', '.aac', '.flac', '.ogg', '.wma', '.m4a', '.aiff', '.aif',
                    '.amr', '.ape', '.opus', '.ra', '.rm', '.voc', '.8svx',
                    # Другие медиаформаты
                    '.swf', '.dv', '.mxf', '.nut', '.yuv'
                ]
                
                if extension.lower() in media_extensions:
                    try:
                        media_info = MediaInfo.parse(file_path)
                        self.debug_logger.log(f"Прочитано {len(media_info.tracks)} треков MediaInfo из {file_path}")
                        
                        for track in media_info.tracks:
                            track_type = track.track_type
                            
                            # Добавляем заголовок для типа трека
                            self.current_metadata[f"MediaInfo - {track_type} Track"] = "---"
                            
                            # Получаем все атрибуты трека
                            for attribute_name in dir(track):
                                # Пропускаем служебные атрибуты
                                if attribute_name.startswith('_') or attribute_name in ['to_data', 'to_json']:
                                    continue
                                
                                try:
                                    attribute_value = getattr(track, attribute_name)
                                    
                                    # Пропускаем None, пустые строки и слишком длинные значения
                                    if attribute_value is not None and str(attribute_value).strip() != '':
                                        # Форматируем длинные значения
                                        str_value = str(attribute_value)
                                        if len(str_value) > 500:
                                            str_value = str_value[:500] + "... [урезано]"
                                        
                                        self.current_metadata[f"MediaInfo {track_type} - {attribute_name}"] = str_value
                                except Exception as e:
                                    self.debug_logger.log(f"Ошибка чтения атрибута {attribute_name} для трека {track_type}: {str(e)}", "WARNING")
                        
                    except Exception as e:
                        self.current_metadata["Ошибка чтения MediaInfo"] = f"Не удалось прочитать MediaInfo метаданные: {str(e)}"
                        self.debug_logger.log(f"Ошибка чтения MediaInfo для {file_path}: {str(e)}", "ERROR")
            
            # Для всех файлов добавляем базовую информацию
            file_stats = os.stat(file_path)
            self.current_metadata["Имя файла"] = os.path.basename(file_path)
            self.current_metadata["Путь"] = file_path
            self.current_metadata["Размер файла"] = f"{file_stats.st_size} байт ({file_stats.st_size / 1024 / 1024:.2f} MB)"
            self.current_metadata["Дата создания"] = datetime.datetime.fromtimestamp(file_stats.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
            self.current_metadata["Дата изменения"] = datetime.datetime.fromtimestamp(file_stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            
            self.debug_logger.log(f"Всего собрано {len(self.current_metadata)} метаданных для {file_path}")
            
            # Разделяем метаданные на цветные и обычные
            colored_metadata = {}
            normal_metadata = {}
            
            for key, value in self.current_metadata.items():
                if key in self.color_metadata and not self.color_metadata[key].get('removed', False):
                    colored_metadata[key] = value
                else:
                    normal_metadata[key] = value
            
            # Сортируем цветные метаданные в соответствии с порядком из ordered_metadata_fields
            sorted_colored = []
            for field_name in self.ordered_metadata_fields:
                if field_name in colored_metadata:
                    sorted_colored.append((field_name, colored_metadata[field_name]))
            
            # Добавляем оставшиеся цветные поля, которых нет в ordered_metadata_fields (на всякий случай)
            for field_name, value in colored_metadata.items():
                if field_name not in self.ordered_metadata_fields:
                    sorted_colored.append((field_name, value))
            
            # Сортируем обычные метаданные по ключу
            sorted_normal = sorted(normal_metadata.items())
            
            # Объединяем: сначала цветные в указанном порядке, потом обычные
            sorted_metadata = sorted_colored + sorted_normal
            
            # Заполняем таблицу
            self.metadata_table.setRowCount(len(sorted_metadata))
            
            for row, (key, value) in enumerate(sorted_metadata):
                # Поле
                key_item = QTableWidgetItem(key)
                key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
                
                # Значение
                value_item = QTableWidgetItem(str(value))
                value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)
                
                self.metadata_table.setItem(row, 0, key_item)
                self.metadata_table.setItem(row, 1, value_item)
                
                # Применяем цвет, если поле есть в цветном списке
                self.apply_field_color(row, key)
            
            # Сбрасываем фильтр поиска при отображении новых данных
            self.clear_search()
            
        except Exception as e:
            self.metadata_table.setRowCount(1)
            self.metadata_table.setItem(0, 0, QTableWidgetItem("Ошибка"))
            self.metadata_table.setItem(0, 1, QTableWidgetItem(f"Ошибка чтения метаданных: {str(e)}"))
            self.debug_logger.log(f"Общая ошибка чтения метаданных для {file_path}: {str(e)}", "ERROR")

    def format_exif_value(self, tag, value):
        """Форматирует значение EXIF для лучшего отображения"""
        try:
            # Если значение - bytes, декодируем его
            if isinstance(value, bytes):
                try:
                    # Пробуем декодировать как UTF-8
                    return value.decode('utf-8').strip()
                except UnicodeDecodeError:
                    # Если не получается, возвращаем строковое представление
                    return str(value)
            
            # Для некоторых специфических тегов можно добавить специальную обработку
            if tag in ['EXIF ExposureTime', 'EXIF ShutterSpeedValue']:
                # Обработка времени экспозиции
                if hasattr(value, 'num') and hasattr(value, 'den'):
                    return f"{value.num}/{value.den} сек"
            
            if tag in ['EXIF FNumber', 'EXIF ApertureValue']:
                # Обработка диафрагмы
                if hasattr(value, 'num') and hasattr(value, 'den'):
                    return f"f/{value.num/value.den:.1f}"
            
            if tag == 'EXIF FocalLength':
                # Фокусное расстояние
                if hasattr(value, 'num') and hasattr(value, 'den'):
                    return f"{value.num/value.den} мм"
            
            if tag == 'EXIF ISOSpeedRatings':
                # ISO
                return f"ISO {value}"
            
            # Для всех остальных случаев возвращаем строковое представление
            return str(value)
            
        except Exception as e:
            self.debug_logger.log(f"Ошибка форматирования EXIF тега {tag}: {str(e)}", "WARNING")
            return str(value)


    def show_sequences_table_context_menu(self, position):
        """Контекстное меню для таблицы последовательностей"""
        index = self.sequences_table.indexAt(position)
        if not index.isValid():
            return
            
        row = index.row()
        path_item = self.sequences_table.item(row, 0)
        name_item = self.sequences_table.item(row, 1)
        
        if path_item and name_item:
            path = path_item.text()
            name = name_item.text()
            
            key = f"{path}/{name}"
            if key in self.sequences:
                seq_type = self.sequences[key]['type']
                
                menu = QMenu(self)
                open_action = menu.addAction("Открыть в проводнике")
                menu.addSeparator()
                color_action = menu.addAction(f"Изменить цвет для '{seq_type}'")
                
                action = menu.exec_(self.sequences_table.viewport().mapToGlobal(position))
                
                if action == open_action:
                    self.open_in_explorer(path)
                elif action == color_action:
                    self.change_sequence_color(seq_type)

    def change_sequence_color(self, seq_type):
        """Изменяет цвет типа последовательности через контекстное меню"""
        current_color_data = self.sequence_colors.get(seq_type)
        current_color = QColor(200, 200, 255)  # Цвет по умолчанию
        
        if current_color_data and isinstance(current_color_data, dict) and 'r' in current_color_data and 'g' in current_color_data and 'b' in current_color_data:
            current_color = QColor(current_color_data['r'], current_color_data['g'], current_color_data['b'])
        
        color = QColorDialog.getColor(current_color, self, f"Выберите цвет для типа '{seq_type}'")
        if color.isValid():
            self.sequence_colors[seq_type] = {
                'r': color.red(),
                'g': color.green(),
                'b': color.blue()
            }
            
            self.save_settings()
            self.update_sequences_colors()

    def update_sequences_colors(self):
        """Обновляет цвета в таблице последовательностей"""
        for row in range(self.sequences_table.rowCount()):
            path_item = self.sequences_table.item(row, 0)
            name_item = self.sequences_table.item(row, 1)
            
            if path_item and name_item:
                path = path_item.text()
                name = name_item.text()
                
                key = f"{path}/{name}"
                if key in self.sequences:
                    seq_type = self.sequences[key]['type']
                    self.color_row_by_type(row, seq_type)

    def open_in_explorer(self, path):
        """Открывает папку в проводнике"""
        if os.path.exists(path):
            try:
                if platform.system() == "Windows":
                    os.startfile(path)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось открыть папку: {str(e)}")
        else:
            QMessageBox.warning(self, "Ошибка", f"Папка не существует: {path}")

    def filter_metadata(self):
        """Фильтрует таблицу метаданных по введенному тексту"""
        search_text = self.search_input.text().lower().strip()
        
        # Если поле поиска пустое, показываем все строки
        if not search_text:
            for row in range(self.metadata_table.rowCount()):
                self.metadata_table.setRowHidden(row, False)
            return
        
        # Иначе скрываем строки, которые не содержат искомый текст
        for row in range(self.metadata_table.rowCount()):
            field_item = self.metadata_table.item(row, 0)
            value_item = self.metadata_table.item(row, 1)
            
            field_text = field_item.text().lower() if field_item else ""
            value_text = value_item.text().lower() if value_item else ""
            
            # Показываем строку, если текст найден в поле или значении
            if search_text in field_text or search_text in value_text:
                self.metadata_table.setRowHidden(row, False)
            else:
                self.metadata_table.setRowHidden(row, True)

    def clear_search(self):
        """Очищает поле поиска и показывает все строки"""
        self.search_input.clear()
        for row in range(self.metadata_table.rowCount()):
            self.metadata_table.setRowHidden(row, False)

    def format_metadata_value(self, value):
        """Форматирует значение метаданных, убирая лишние символы"""
        # Обработка специальных типов Imath
        if hasattr(value, '__class__'):
            class_name = value.__class__.__name__
            
            # Обработка TimeCode
            if class_name == 'TimeCode':
                try:
                    # Получаем атрибуты TimeCode напрямую
                    hours = value.hours
                    minutes = value.minutes
                    seconds = value.seconds
                    frame = value.frame
                    drop_frame = value.dropFrame
                    color_frame = value.colorFrame
                    field_phase = value.fieldPhase
                    
                    # Форматируем в читаемый вид
                    time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame:02d}"
                    return f"{time_str} (dropFrame: {drop_frame}, colorFrame: {color_frame}, fieldPhase: {field_phase})"
                except Exception as e:
                    # Если не удалось получить атрибуты, парсим строковое представление
                    str_repr = str(value)
                    # Пример: '<Imath.TimeCode instance { time: 14:33:4:15, dropFrame: 0, ... }'
                    match = re.search(r'time:\s*([^,]+)', str_repr)
                    if match:
                        time_str = match.group(1).strip()
                        # Извлекаем остальные параметры
                        drop_match = re.search(r'dropFrame:\s*(\d+)', str_repr)
                        drop_frame = drop_match.group(1) if drop_match else '?'
                        
                        color_match = re.search(r'colorFrame:\s*(\d+)', str_repr)
                        color_frame = color_match.group(1) if color_match else '?'
                        
                        field_match = re.search(r'fieldPhase:\s*(\d+)', str_repr)
                        field_phase = field_match.group(1) if field_match else '?'
                        
                        return f"{time_str} (dropFrame: {drop_frame}, colorFrame: {color_frame}, fieldPhase: {field_phase})"
                    return str_repr
            
            # Обработка Box2i и Box2f
            elif class_name in ['Box2i', 'Box2f']:
                try:
                    min_x = value.min.x
                    min_y = value.min.y
                    max_x = value.max.x
                    max_y = value.max.y
                    return f"({min_x}, {min_y}) - ({max_x}, {max_y})"
                except:
                    return str(value)
            
            # Обработка V2i, V2f, V3i, V3f
            elif class_name in ['V2i', 'V2f']:
                try:
                    x = value.x
                    y = value.y
                    return f"({x}, {y})"
                except:
                    return str(value)
            
            elif class_name in ['V3i', 'V3f']:
                try:
                    x = value.x
                    y = value.y
                    z = value.z
                    return f"({x}, {y}, {z})"
                except:
                    return str(value)
            
            # Обработка Rational
            elif class_name == 'Rational':
                try:
                    numerator = value.n
                    denominator = value.d
                    return f"{numerator}/{denominator}"
                except:
                    return str(value)
        
        # Обработка байтовых строк
        if isinstance(value, bytes):
            try:
                decoded = value.decode('utf-8', errors='ignore').strip()
                # Если после декодирования получилась строка с префиксом b'', пробуем обработать дальше
                if decoded.startswith("b'") and decoded.endswith("'"):
                    try:
                        return ast.literal_eval(decoded).decode('utf-8', errors='ignore')
                    except:
                        return decoded[2:-1]
                return decoded
            except:
                return str(value)
        
        # Обработка строк с префиксом b''
        elif isinstance(value, str):
            if value.startswith("b'") and value.endswith("'"):
                try:
                    return ast.literal_eval(value).decode('utf-8', errors='ignore')
                except:
                    return value[2:-1]
        
        # Для всех остальных типов используем строковое представление
        return str(value)

    def apply_field_color(self, row, field_name):
        """Применяет цвет к полю в таблице"""
        color = self.get_field_color(field_name)
        if color:
            for col in range(2):
                item = self.metadata_table.item(row, col)
                if item:
                    item.setBackground(color)

    def get_field_color(self, field_name):
        """Возвращает цвет для поля метаданных"""
        if field_name in self.color_metadata:
            color_data = self.color_metadata[field_name]
            # Проверяем корректность структуры
            if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                if not color_data.get('removed', False):
                    return QColor(color_data['r'], color_data['g'], color_data['b'])
        return None

    def show_metadata_table_context_menu(self, position):
        """Контекстное меню для таблицы метаданных"""
        index = self.metadata_table.indexAt(position)
        if not index.isValid():
            return
            
        row = index.row()
        column = index.column()
        
        field_name_item = self.metadata_table.item(row, 0)
        value_item = self.metadata_table.item(row, 1)
        
        if not field_name_item or not value_item:
            return
            
        field_name = field_name_item.text()
        field_value = value_item.text()
        
        menu = QMenu(self)
        
        if column == 0:  # Клик по столбцу "Поле"
            # Копировать имя поля
            copy_name_action = menu.addAction("Копировать имя поля")
            copy_name_action.triggered.connect(lambda: self.copy_field_name(field_name))
            
            menu.addSeparator()
            
            # Проверяем, есть ли поле в цветных
            if field_name in self.color_metadata and not self.color_metadata[field_name].get('removed', False):
                color_action = menu.addAction("Изменить цвет")
                remove_action = menu.addAction("Удалить из списка")
                
                color_action.triggered.connect(lambda: self.change_field_color(field_name))
                remove_action.triggered.connect(lambda: self.remove_field_from_colors(field_name))
            else:
                color_action = menu.addAction("Задать цвет")
                color_action.triggered.connect(lambda: self.add_field_with_color(field_name))
            
        elif column == 1:  # Клик по столбцу "Значение"
            # Копировать значение поля
            copy_value_action = menu.addAction("Копировать значение")
            copy_value_action.triggered.connect(lambda: self.copy_field_value(field_value))
            
            # Копировать имя и значение
            copy_both_action = menu.addAction("Копировать имя и значение")
            copy_both_action.triggered.connect(lambda: self.copy_field_name_and_value(field_name, field_value))
        
        menu.exec_(self.metadata_table.viewport().mapToGlobal(position))

    def copy_field_name(self, field_name):
        """Копирует имя поля в буфер обмена"""
        clipboard = QApplication.clipboard()
        clipboard.setText(field_name)
        QMessageBox.information(self, "Успех", f"Поле '{field_name}' скопировано в буфер обмена")

    def copy_field_value(self, field_value):
        """Копирует значение поля в буфер обмена"""
        clipboard = QApplication.clipboard()
        clipboard.setText(field_value)
        QMessageBox.information(self, "Успех", "Значение поля скопировано в буфер обмена")

    def copy_field_name_and_value(self, field_name, field_value):
        """Копирует имя и значение поля в буфер обмена"""
        clipboard = QApplication.clipboard()
        clipboard.setText(f"{field_name}: {field_value}")
        QMessageBox.information(self, "Успех", "Имя и значение поля скопированы в буфер обмена")

    def add_field_with_color(self, field_name):
        """Добавляет поле с выбранным цветом"""
        color = QColorDialog.getColor(QColor(200, 200, 255), self, f"Выберите цвет для поля '{field_name}'")
        if color.isValid():
            self.color_metadata[field_name] = {
                'r': color.red(),
                'g': color.green(),
                'b': color.blue(),
                'removed': False
            }
            
            # Добавляем поле в конец списка порядка, если его там нет
            if field_name not in self.ordered_metadata_fields:
                self.ordered_metadata_fields.append(field_name)
            
            self.save_settings()
            self.update_metadata_colors()
            
            QMessageBox.information(self, "Успех", f"Поле '{field_name}' добавлено с выбранным цветом")

    def change_field_color(self, field_name):
        """Изменяет цвет поля"""
        if field_name in self.color_metadata:
            current_color_data = self.color_metadata[field_name]
            current_color = QColor(current_color_data['r'], current_color_data['g'], current_color_data['b'])
            
            color = QColorDialog.getColor(current_color, self, f"Выберите цвет для поля '{field_name}'")
            if color.isValid():
                self.color_metadata[field_name] = {
                    'r': color.red(),
                    'g': color.green(),
                    'b': color.blue(),
                    'removed': False
                }
                
                self.save_settings()
                self.update_metadata_colors()

    def remove_field_from_colors(self, field_name):
        """Удаляет поле из цветных в корзину"""
        if field_name in self.color_metadata:
            # Перемещаем в корзину
            color_data = self.color_metadata[field_name]
            self.removed_metadata[field_name] = color_data
            
            # Удаляем из активных
            del self.color_metadata[field_name]
            
            # Удаляем из списка порядка
            if field_name in self.ordered_metadata_fields:
                self.ordered_metadata_fields.remove(field_name)
            
            self.save_settings()
            self.update_metadata_colors()
            
            QMessageBox.information(self, "Успех", f"Поле '{field_name}' перемещено в корзину")

    def update_metadata_colors(self):
        """Обновляет цвета в таблице метаданных"""
        if not self.current_metadata:
            return
        
        # Полностью перерисовываем таблицу с новыми цветами
        if self.sequences_table.currentRow() >= 0:
            self.on_sequence_selected()

    def open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            # Настройки сохраняются автоматически в диалоге
            # Обновляем отображение метаданных с новыми цветами
            self.update_metadata_colors()
            self.update_sequences_colors()

    def show_log(self):
        """Показывает диалог с логами"""
        dialog = LogViewerDialog(self.debug_logger, self)
        dialog.exec_()

    def load_settings(self):
        """Загружает настройки из файла"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    
                    # Загружаем цвета метаданных
                    self.color_metadata = settings.get('color_metadata', {})
                    self.removed_metadata = settings.get('removed_metadata', {})
                    
                    # Загружаем цвета последовательностей
                    self.sequence_colors = settings.get('sequence_colors', {})
                    
                    # Загружаем порядок полей метаданных
                    self.ordered_metadata_fields = settings.get('ordered_metadata_fields', [])
                    
                    # Если ordered_metadata_fields пуст, инициализируем его из color_metadata
                    if not self.ordered_metadata_fields and self.color_metadata:
                        self.ordered_metadata_fields = list(self.color_metadata.keys())
                        
        except Exception as e:
            self.debug_logger.log(f"Ошибка загрузки настроек: {e}", "ERROR")
            self.color_metadata = {}
            self.removed_metadata = {}
            self.sequence_colors = {}
            self.ordered_metadata_fields = []

    def save_settings(self):
        """Сохраняет настройки в файл"""
        try:
            # Убедимся, что все данные в правильном формате
            cleaned_color_metadata = {}
            for field_name, color_data in self.color_metadata.items():
                if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                    cleaned_color_metadata[field_name] = color_data
            
            cleaned_removed_metadata = {}
            for field_name, color_data in self.removed_metadata.items():
                if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                    cleaned_removed_metadata[field_name] = color_data
            
            cleaned_sequence_colors = {}
            for seq_type, color_data in self.sequence_colors.items():
                if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                    cleaned_sequence_colors[seq_type] = color_data
            
            settings = {
                'color_metadata': cleaned_color_metadata,
                'removed_metadata': cleaned_removed_metadata,
                'sequence_colors': cleaned_sequence_colors,
                'ordered_metadata_fields': self.ordered_metadata_fields
            }
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            self.debug_logger.log(f"Ошибка сохранения настроек: {e}", "ERROR")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Устанавливаем шрифт приложения
    app_font = QFont()
    app_font.setPointSize(DEFAULT_FONT_SIZE)
    app.setFont(app_font)
    
    window = EXRMetadataViewer()
    window.show()
    sys.exit(app.exec_())