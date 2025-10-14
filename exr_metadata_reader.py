
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
import tempfile
import shutil

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
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem

# ==================== НАСТРОЙКИ ====================

DEBUG = False  # Включаем логирование для отладки

SETTINGS_FILE_HARD = "/home/hidden/Documents/DEV/exr_viewer_settings.json"
# Путь к ARRI Reference Tool
ARRI_REFERENCE_TOOL_PATH = "/home/hidden/Downloads/arri/art-cmd_0.4.1_rhel8_gcc85_x64/bin/art-cmd"

DEFAULT_FONT_SIZE = 10  # Размер шрифта по умолчанию
DEFAULT_COLUMN_WIDTHS = {  # Ширины столбцов по умолчанию
    'sequences': [500, 500, 80, 100, 100],  # Путь, Имя, Расширение, Диапазон, Количество
    'metadata': [300, 500]  # Поле, Значение
}

METADATA_TOOLS = {
    'mediainfo': 'MediaInfo',
    'ffprobe': 'FFprobe'
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
                            
                            self.debug_logger.log(f"      Минимальный кадр: {min_frame}, максимальный: {max_frame}, макс. цифр: {max_digits}")
                            
                            # Проверяем, есть ли ведущие нули
                            has_leading_zeros = any(len(str(f)) < max_digits for f in frame_numbers)
                            
                            if has_leading_zeros or all(len(str(f)) == max_digits for f in frame_numbers):
                                frame_range = f"{min_frame:0{max_digits}d}-{max_frame:0{max_digits}d}"
                            else:
                                frame_range = f"{min_frame}-{max_frame}"
                                
                            self.debug_logger.log(f"      Диапазон кадров: {min_frame}..{max_frame} -> '{frame_range}'")
                        else:
                            frame_range = "одиночный файл"
                    else:
                        # Это не последовательность, а группа одиночных файлов
                        seq_type = f'group_{ext[1:]}'
                        frame_range = "группа файлов"
                    
                    # Имя последовательности - имя первого файла
                    display_name = file_names[0]
                    
                    # Используем путь + имени группы как ключ для уникальности
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
        
        # УЛУЧШЕННЫЙ список паттернов для лучшего распознавания сложных форматов
        patterns = [
            # 1. ПАТТЕРНЫ ДЛЯ СЛОЖНЫХ EXR С НОМЕРАМИ В КОНЦЕ
            # A_0160C003_240903_041957_a1CGM.mxf00380118.exr -> 00380118
            r'^(.+?\.\w+?)(\d{6,8})$',
            
            # 2. ПАТТЕРНЫ ДЛЯ СТАНДАРТНЫХ EXR С НОМЕРАМИ КАДРОВ В КОНЦЕ
            # A_0104C003_240510_141409_a1DPL.00000001.exr -> 00000001
            r'^(.+?\.)(\d{6,8})$',
            
            # 3. ПАТТЕРНЫ ДЛЯ ФОРМАТА С ПРЕФИКСОМ И НОМЕРОМ КАДРА
            # A_0051C010_240406_182948_a1DPL01693065.exr -> 01693065
            r'^(.+?[A-Z])(\d{6,8})$',
            
            # 4. ПАТТЕРНЫ ДЛЯ ФОРМАТА С ПОДЧЕРКИВАНИЕМ И НОМЕРОМ КАДРА
            # V006C0030_240318_8J4U_000247.DNG -> 000247
            r'^(.+?_)(\d{3,6})$',
            
            # 5. ПАТТЕРНЫ ДЛЯ ФОРМАТА DNG С ПРЕФИКСОМ
            # D003C0015_250121_8H3408.DNG -> 0015
            r'^(.+?[A-Z])(\d{3,5})_.*$',
            
            # 6. СТАНДАРТНЫЕ ПАТТЕРНЫ ДЛЯ ЧИСЕЛ В КОНЦЕ
            r'^(.+?)(\d{1,8})$',
            r'^(.+?)[._ -](\d{1,8})$',
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
        
        # РЕЗЕРВНЫЕ ПАТТЕРНЫ - ищем последнюю группу цифр подходящей длины
        all_numbers = re.findall(r'\d+', name_without_ext)
        if all_numbers:
            # Сначала ищем числа с 6-8 цифрами (типичные для EXR)
            frame_candidates = []
            for number in all_numbers:
                if 6 <= len(number) <= 8:
                    frame_candidates.append(number)
            
            # Берем ПОСЛЕДНЕЕ подходящее число (самое правое)
            if frame_candidates:
                frame_num_str = frame_candidates[-1]
                frame_pos = name_without_ext.rfind(frame_num_str)
                if frame_pos > 0:
                    base_name = name_without_ext[:frame_pos]
                    try:
                        frame_num = int(frame_num_str)
                        self.debug_logger.log(f"extract_sequence_info: '{filename}' -> fallback EXR numbers (last): base_name='{base_name}', frame_num={frame_num}")
                        return base_name, frame_num
                    except ValueError:
                        pass
            
            # Если не нашли EXR номера, ищем любые числа с 4-6 цифрами
            frame_candidates = []
            for number in all_numbers:
                if 4 <= len(number) <= 6:
                    frame_candidates.append(number)
            
            if frame_candidates:
                # Берем ПОСЛЕДНЕЕ число (самое правое)
                frame_num_str = frame_candidates[-1]
                frame_pos = name_without_ext.rfind(frame_num_str)
                if frame_pos > 0:
                    base_name = name_without_ext[:frame_pos]
                    try:
                        frame_num = int(frame_num_str)
                        self.debug_logger.log(f"extract_sequence_info: '{filename}' -> fallback filtered numbers (last): base_name='{base_name}', frame_num={frame_num}")
                        return base_name, frame_num
                    except ValueError:
                        pass
            
            # Если не нашли подходящих по длине, берем последнее число
            last_number = all_numbers[-1]
            last_number_pos = name_without_ext.rfind(last_number)
            if last_number_pos > 0:
                base_name = name_without_ext[:last_number_pos]
                try:
                    frame_num = int(last_number)
                    self.debug_logger.log(f"extract_sequence_info: '{filename}' -> fallback last number: base_name='{base_name}', frame_num={frame_num}")
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
            self.debug_logger.log(f"is_sequence: недостаточно кадров ({len(frame_numbers)})")
            return False
        
        # Фильтруем None значения (одиночные файлы)
        valid_frames = [f for f in frame_numbers if f is not None]
        if len(valid_frames) < 2:
            self.debug_logger.log(f"is_sequence: недостаточно валидных кадров ({len(valid_frames)})")
            return False
        
        sorted_frames = sorted(valid_frames)
        
        # Проверяем, что разница между кадрами постоянная
        differences = [sorted_frames[i] - sorted_frames[i-1] for i in range(1, len(sorted_frames))]
        unique_differences = set(differences)
        
        self.debug_logger.log(f"is_sequence: кадры {sorted_frames}, различия {differences}, уникальные различия {unique_differences}")
        
        # Допускаем последовательности с постоянным шагом (1, 2, 10 и т.д.)
        result = len(unique_differences) == 1
        self.debug_logger.log(f"is_sequence: результат {result}")
        return result

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
        
        # Настройки
        self.use_art_for_mxf = False  # По умолчанию используем MediaInfo для MXF
        self.default_metadata_tool = 'mediainfo'  # Инструмент по умолчанию для чтения метаданных
        
        # Для древовидной структуры
        self.tree_structure = {}  # {path: {subfolders: {}, sequences: []}}
        self.folder_items = {}  # {folder_path: QTreeWidgetItem}
        self.root_item = None

        self.forced_metadata_tool = None  # Текущий форсированный инструмент
        self.forced_metadata_file = None  # Файл, для которого применено форсированное чтение
        


        # Используем жесткий путь если задан, иначе локальный файл
        if SETTINGS_FILE_HARD:
            self.settings_file = SETTINGS_FILE_HARD
        else:
            self.settings_file = "exr_viewer_settings.json"

        self.load_settings()
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Universal File Sequence Metadata Viewer - Tree View")
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

        # Добавляем галочку для чтения MXF через ART
        self.art_checkbox = QCheckBox("Читать Arri")
        self.art_checkbox.setChecked(self.use_art_for_mxf)
        self.art_checkbox.stateChanged.connect(self.toggle_art_usage)
        
        # Добавляем галочку для включения/выключения логирования
        self.log_checkbox = QCheckBox("Логирование")
        self.log_checkbox.setChecked(DEBUG)
        self.log_checkbox.stateChanged.connect(self.toggle_logging)
        
        self.log_btn = QPushButton("Лог")
        
        # Добавляем выбор инструмента для чтения метаданных
        self.metadata_tool_label = QLabel("Инструмент метаданных:")
        self.metadata_tool_combo = QComboBox()
        for tool_key, tool_name in METADATA_TOOLS.items():
            self.metadata_tool_combo.addItem(tool_name, tool_key)
        self.metadata_tool_combo.setCurrentText(METADATA_TOOLS.get(self.default_metadata_tool, 'MediaInfo'))
        self.metadata_tool_combo.currentIndexChanged.connect(self.change_metadata_tool)
        
        
        
        self.start_btn.clicked.connect(self.start_search)
        self.stop_btn.clicked.connect(self.stop_search)
        self.continue_btn.clicked.connect(self.continue_search)
        self.settings_btn.clicked.connect(self.open_settings)
        self.log_btn.clicked.connect(self.show_log)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.continue_btn)
        control_layout.addWidget(self.settings_btn)
        control_layout.addWidget(self.art_checkbox)
        control_layout.addWidget(self.log_checkbox)
        control_layout.addWidget(self.log_btn)
        
        control_layout.addWidget(self.metadata_tool_label)
        control_layout.addWidget(self.metadata_tool_combo)
        
        control_layout.addStretch()
        
        # Создаем разделитель для таблиц
        splitter = QSplitter(Qt.Vertical)
        
        # Верхняя часть - дерево последовательностей
        sequences_widget = QWidget()
        sequences_layout = QVBoxLayout()
        sequences_layout.addWidget(QLabel("Структура папок и последовательностей:"))
        
        # Дерево последовательностей
        self.sequences_tree = QTreeWidget()
        self.sequences_tree.setColumnCount(5)
        self.sequences_tree.setHeaderLabels(["Имя", "Тип", "Диапазон", "Количество", "Путь"])
        
        # Настраиваем ширины столбцов
        self.sequences_tree.setColumnWidth(0, 500)  # Имя
        self.sequences_tree.setColumnWidth(1, 200)  # Тип
        self.sequences_tree.setColumnWidth(2, 200)  # Диапазон
        self.sequences_tree.setColumnWidth(3, 100)   # Количество
        self.sequences_tree.setColumnWidth(4, 400)  # Путь
        
        self.sequences_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
# ОТКЛЮЧАЕМ СОРТИРОВКУ для сохранения порядка добавления
        self.sequences_tree.setSortingEnabled(True)
        self.sequences_tree.itemSelectionChanged.connect(self.on_tree_item_selected)
        self.sequences_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sequences_tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        
        sequences_layout.addWidget(self.sequences_tree)
        sequences_widget.setLayout(sequences_layout)
        
        # Нижняя часть - таблица метаданных
        metadata_widget = QWidget()
        metadata_layout = QVBoxLayout()
        
        # Метка для отображения источника метаданных
        self.metadata_source_label = QLabel("Метаданные выбранного элемента:")
        metadata_layout.addWidget(self.metadata_source_label)
        
        self.metadata_table = QTableWidget()
        self.metadata_table.setColumnCount(2)
        self.metadata_table.setHorizontalHeaderLabels(["Поле", "Значение"])
        
        # Устанавливаем ширины столбцов по умолчанию
        for i, width in enumerate(DEFAULT_COLUMN_WIDTHS['metadata']):
            self.metadata_table.setColumnWidth(i, width)
        
        # Настраиваем режимы изменения размеров столбцов
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        
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
        
        # Устанавливаем начальные размеры (верхняя часть - 50%, нижняя - 50%)
        splitter.setSizes([400, 400])
        
        # Поле прогресса
        self.progress_label = QLabel("Готов к работе")
        
        layout.addLayout(folder_layout)
        layout.addLayout(control_layout)
        layout.addWidget(self.progress_label)
        layout.addWidget(splitter)
        
        central_widget.setLayout(layout)
        
        # Изначально кнопки Стоп и Продолжить неактивны
        self.stop_btn.setEnabled(False)
        self.continue_btn.setEnabled(False)



    def change_metadata_tool(self, index):
        """Изменяет инструмент для чтения метаданных"""
        tool_key = self.metadata_tool_combo.currentData()
        self.default_metadata_tool = tool_key
        self.save_settings()
        self.debug_logger.log(f"Изменен инструмент метаданных на: {METADATA_TOOLS[tool_key]}")


    def show_tree_context_menu(self, position):
        """Контекстное меню для дерева"""
        index = self.sequences_tree.indexAt(position)
        if not index.isValid():
            return
            
        item = self.sequences_tree.itemFromIndex(index)
        item_data = item.data(0, Qt.UserRole)
        
        if not item_data:
            return
            
        menu = QMenu(self)
        
        if item_data['type'] == 'folder':
            open_action = menu.addAction("Открыть в проводнике")
            expand_all_action = menu.addAction("Раскрыть все вложенные")
            collapse_all_action = menu.addAction("Свернуть все вложенные")
            
            open_action.triggered.connect(lambda: self.open_in_explorer(item_data['path']))
            expand_all_action.triggered.connect(lambda: self.expand_folder_recursive(item))
            collapse_all_action.triggered.connect(lambda: self.collapse_folder_recursive(item))
        else:
            # Для последовательности или одиночного файла
            seq_info = item_data['info']
            open_action = menu.addAction("Открыть в проводнике")
            open_action.triggered.connect(lambda: self.open_in_explorer(seq_info['path']))
            
            menu.addSeparator()
            
            # ВСЕГДА добавляем пункты для принудительного чтения метаданных для ЛЮБОГО файла
            if len(seq_info['files']) > 0:
                file_path = seq_info['files'][0]
                extension = seq_info['extension'].lower()
                
                # Показываем эти пункты для ВСЕХ файлов, независимо от расширения
                mediainfo_action = menu.addAction("Читать принудительно mediainfo")
                ffprobe_action = menu.addAction("Читать принудительно ffprobe")
                
                mediainfo_action.triggered.connect(lambda: self.force_read_metadata(file_path, extension, 'mediainfo'))
                ffprobe_action.triggered.connect(lambda: self.force_read_metadata(file_path, extension, 'ffprobe'))
                
                menu.addSeparator()
            
            color_action = menu.addAction(f"Изменить цвет для '{seq_info['type']}'")
            color_action.triggered.connect(lambda: self.change_sequence_color(seq_info['type']))
        
        menu.exec_(self.sequences_tree.viewport().mapToGlobal(position))


    def force_read_metadata(self, file_path, extension, tool):
        """Принудительно читает метаданные с помощью указанного инструмента"""
        self.debug_logger.log(f"Принудительное чтение метаданных для {file_path} с помощью {tool}")
        
        # Устанавливаем состояние форсированного чтения
        self.forced_metadata_tool = tool
        self.forced_metadata_file = file_path
        
        # Читаем метаданные с выбранным инструментом
        self.display_metadata(file_path, extension, forced_tool=tool)






    def toggle_art_usage(self, state):
        """Включает/выключает использование ART для MXF файлов"""
        self.use_art_for_mxf = state == Qt.Checked
        self.save_settings()
        if state == Qt.Checked:
            self.debug_logger.log("Включено чтение MXF через ART")
        else:
            self.debug_logger.log("Выключено чтение MXF через ART")

    def build_tree_structure(self):
        """Строит полную древовидную структуру папок и последовательностей"""
        self.tree_structure = {}
        root_path = self.folder_path.text()
        
        # Создаем корневой узел
        self.tree_structure[root_path] = {
            'name': os.path.basename(root_path) if root_path else "Корневая папка",
            'full_path': root_path,
            'subfolders': {},
            'sequences': [],
            'files': []
        }
        
        # Собираем все уникальные пути из последовательностей, которые находятся внутри корневой папки
        all_paths = set()
        for seq_info in self.sequences.values():
            path = seq_info['path']
            
            # Добавляем только пути, которые находятся внутри корневой папки
            if path.startswith(root_path):
                all_paths.add(path)
                
                # Добавляем все родительские пути внутри корневой папки
                parent_path = path
                while (parent_path and 
                       parent_path.startswith(root_path) and 
                       parent_path != root_path and 
                       os.path.dirname(parent_path) != parent_path):
                    all_paths.add(parent_path)
                    parent_path = os.path.dirname(parent_path)
        
        # Создаем узлы для всех путей
        for path in sorted(all_paths):
            if path not in self.tree_structure:
                self.tree_structure[path] = {
                    'name': os.path.basename(path),
                    'full_path': path,
                    'subfolders': {},
                    'sequences': [],
                    'files': []
                }
        
        # Добавляем последовательности в соответствующие папки
        for seq_info in self.sequences.values():
            path = seq_info['path']
            
            # Убедимся, что у последовательности есть все необходимые поля
            self.ensure_sequence_fields(seq_info)
            
            # Добавляем последовательность в папку только если она внутри корневой папки
            if path in self.tree_structure:
                self.tree_structure[path]['sequences'].append(seq_info)
        
        # Строим иерархию подпапок
        self.build_folder_hierarchy(root_path)


    def build_folder_hierarchy(self, root_path):
        """Строит иерархию подпапок для корневой папки"""
        if root_path not in self.tree_structure:
            return
            
        # Создаем копию ключей для безопасной итерации
        all_paths = list(self.tree_structure.keys())
        
        for path in all_paths:
            if path == root_path:
                continue
                
            parent_path = os.path.dirname(path)
            
            # Если родитель существует в структуре, добавляем текущую папку как подпапку
            if parent_path in self.tree_structure:
                # Убедимся, что подпапка еще не добавлена
                if path not in self.tree_structure[parent_path]['subfolders']:
                    self.tree_structure[parent_path]['subfolders'][path] = self.tree_structure[path]


    def build_subfolder_hierarchy(self, parent_path, parent_info):
        """Рекурсивно строит иерархию для подпапки"""
        # Находим все подпапки текущей папки
        subfolders = {}
        for path, folder_info in self.tree_structure.items():
            if os.path.dirname(path) == parent_path:
                subfolders[path] = folder_info
                # Добавляем в подпапки родителя
                parent_info['subfolders'][path] = folder_info
                # Рекурсивно обрабатываем подпапки
                self.build_subfolder_hierarchy(path, folder_info)

    def ensure_sequence_fields(self, seq_info):
        """Убеждается, что у последовательности есть все необходимые поля"""
        if 'name' not in seq_info:
            seq_info['name'] = os.path.basename(seq_info.get('first_file', 'Unknown'))
        if 'display_name' not in seq_info:
            seq_info['display_name'] = seq_info['name']
        if 'frame_range' not in seq_info:
            seq_info['frame_range'] = ''
        if 'frame_count' not in seq_info:
            seq_info['frame_count'] = len(seq_info.get('files', []))
        if 'type' not in seq_info:
            seq_info['type'] = 'unknown'


    def create_parent_folders(self, path, root_path):
        """Рекурсивно создает родительские папки в структуре"""
        if path == root_path or not path.startswith(root_path):
            return
            
        parent_path = os.path.dirname(path)
        
        # Если родительской папки нет, создаем ее рекурсивно
        if parent_path not in self.tree_structure and parent_path.startswith(root_path):
            self.create_parent_folders(parent_path, root_path)
        
        # Создаем текущую папку
        if path not in self.tree_structure:
            self.tree_structure[path] = {
                'name': os.path.basename(path),
                'full_path': path,
                'subfolders': {},
                'sequences': [],
                'files': []
            }


    def populate_tree_widget(self):
        """Заполняет дерево на основе древовидной структуры"""
        self.sequences_tree.clear()
        root_path = self.folder_path.text()
        
        if root_path not in self.tree_structure:
            self.debug_logger.log(f"populate_tree_widget: корневой путь {root_path} не найден в tree_structure")
            return
            
        root_info = self.tree_structure[root_path]
        
        # Создаем корневой элемент
        root_item = QTreeWidgetItem(self.sequences_tree, [
            root_info['name'], 
            "Папка", 
            "", 
            "", #str(len(root_info['sequences'])), 
            "" #root_path
        ])
        root_item.setData(0, Qt.UserRole, {"type": "folder", "path": root_path})
        
        # Добавляем подпапки и последовательности корневой папки
        self.add_tree_children(root_item, root_info)
        
        # Раскрываем ВСЕ узлы дерева
        self.expand_all_tree_items(root_item)
        
        # Логируем результат
        total_sequences = sum(len(folder_info['sequences']) for folder_info in self.tree_structure.values())
        total_folders = len(self.tree_structure)
        self.debug_logger.log(f"populate_tree_widget: отображено {total_sequences} последовательностей в {total_folders} папках")
        
        # Дополнительная информация для отладки
        expanded_count = self.count_expanded_items(root_item)
        self.debug_logger.log(f"Раскрыто элементов дерева: {expanded_count}")

    def expand_all_tree_items(self, item):
        """Рекурсивно раскрывает все элементы дерева"""
        item.setExpanded(True)
        for i in range(item.childCount()):
            child = item.child(i)
            self.expand_all_tree_items(child)


    def count_expanded_items(self, item):
        """Рекурсивно подсчитывает количество раскрытых элементов"""
        count = 1  # Текущий элемент
        if item.isExpanded():
            for i in range(item.childCount()):
                count += self.count_expanded_items(item.child(i))
        return count


    def expand_all_tree_items_iterative(self, root_item):
        """Раскрывает все элементы дерева итеративно (без рекурсии)"""
        stack = [root_item]
        while stack:
            item = stack.pop()
            item.setExpanded(True)
            # Добавляем всех детей в стек
            for i in range(item.childCount()):
                stack.append(item.child(i))


    def expand_first_levels(self, item, levels):
        """Рекурсивно расширяет первые несколько уровней дерева"""
        if levels <= 0:
            return
            
        item.setExpanded(True)
        for i in range(item.childCount()):
            child = item.child(i)
            child_data = child.data(0, Qt.UserRole)
            if child_data and child_data.get('type') == 'folder':
                self.expand_first_levels(child, levels - 1)


    def add_tree_children(self, parent_item, folder_info):
        """Рекурсивно добавляет дочерние элементы в дерево"""
        # Сначала добавляем подпапки
        for subfolder_path, subfolder_info in sorted(folder_info['subfolders'].items(), 
                                                key=lambda x: x[1]['name'].lower()):
            subfolder_item = QTreeWidgetItem(parent_item, [
                subfolder_info['name'], 
                "Папка", 
                "", 
                "", #str(len(subfolder_info['sequences'])), 
                "" #subfolder_path
            ])
            subfolder_item.setData(0, Qt.UserRole, {"type": "folder", "path": subfolder_path})
            
            # Рекурсивно добавляем содержимое подпапки
            self.add_tree_children(subfolder_item, subfolder_info)
        
        # Затем добавляем последовательности текущей папки
        for seq_info in sorted(folder_info['sequences'], 
                            key=lambda x: x.get('display_name', x.get('name', 'Unknown')).lower()):
            display_name = seq_info.get('display_name', seq_info.get('name', 'Unknown'))
            frame_range = seq_info.get('frame_range', '')
            frame_count = seq_info.get('frame_count', 0)
            seq_type = seq_info.get('type', 'unknown')
            
            seq_item = QTreeWidgetItem(parent_item, [
                display_name,
                seq_type,
                frame_range,
                str(frame_count),
                seq_info.get('path', '')
            ])
            seq_item.setData(0, Qt.UserRole, {"type": "sequence", "info": seq_info})
            
            # Применяем цвет в зависимости от типа последовательности
            self.color_tree_item_by_type(seq_item, seq_type)



    def is_item_already_added(self, parent_item, path):
        """Проверяет, был ли элемент с таким путем уже добавлен"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child_data = child.data(0, Qt.UserRole)
            if child_data and child_data.get('path') == path:
                return True
        return False
    
        


    def color_tree_item_by_type(self, item, seq_type):
        """Подкрашивает элемент дерева в зависимости от типа последовательности"""
        color_data = self.sequence_colors.get(seq_type)
        if color_data and isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
            color = QColor(color_data['r'], color_data['g'], color_data['b'])
        else:
            # Цвет по умолчанию - серый
            color = QColor(240, 240, 240)
        
        # Применяем цвет ко всем столбцам элемента
        for col in range(self.sequences_tree.columnCount()):
            item.setBackground(col, color)

    def on_tree_item_selected(self):
        """Обрабатывает выбор элемента в дереве"""
        selected_items = self.sequences_tree.selectedItems()
        if not selected_items:
            return
            
        item = selected_items[0]
        item_data = item.data(0, Qt.UserRole)
        
        if not item_data:
            return
            
        if item_data['type'] == 'sequence':
            # Для последовательности показываем метаданные первого файла
            seq_info = item_data['info']
            self.current_sequence_files = seq_info['files']
            extension = seq_info['extension']
            
            if self.current_sequence_files:
                current_file = self.current_sequence_files[0]
                
                # Сбрасываем форсированное чтение, если выбран другой файл
                if self.forced_metadata_file != current_file:
                    self.forced_metadata_tool = None
                    self.forced_metadata_file = None
                    
                # Определяем, использовать ли форсированный инструмент
                if self.forced_metadata_tool and self.forced_metadata_file == current_file:
                    self.display_metadata(current_file, extension, forced_tool=self.forced_metadata_tool)
                else:
                    self.display_metadata(current_file, extension)
        else:
            # Для папки очищаем метаданные и состояние форсированного чтения
            self.metadata_table.setRowCount(0)
            self.current_sequence_files = []
            self.current_metadata = {}
            self.forced_metadata_tool = None
            self.forced_metadata_file = None
            self.metadata_source_label.setText("Метаданные выбранного элемента:")



    def expand_folder_recursive(self, item):
        """Рекурсивно раскрывает папку и все вложенные"""
        item.setExpanded(True)
        for i in range(item.childCount()):
            child = item.child(i)
            child_data = child.data(0, Qt.UserRole)
            if child_data and child_data.get('type') == 'folder':
                self.expand_folder_recursive(child)

    def collapse_folder_recursive(self, item):
        """Рекурсивно сворачивает папку и все вложенные"""
        item.setExpanded(False)
        for i in range(item.childCount()):
            child = item.child(i)
            child_data = child.data(0, Qt.UserRole)
            if child_data and child_data.get('type') == 'folder':
                self.collapse_folder_recursive(child)

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
        
        # Очищаем все данные
        self.debug_logger.log("Очищаем данные...")
        self.sequences_tree.clear()
        self.metadata_table.setRowCount(0)
        self.sequences.clear()
        self.current_sequence_files = []
        self.current_metadata = {}
        self.folder_items = {}  # Очищаем словарь папок
        self.metadata_source_label.setText("Метаданные выбранного элемента:")
        
        # Создаем корневой элемент
        root_path = folder
        root_name = os.path.basename(root_path) if root_path != "/" else root_path
        self.root_item = QTreeWidgetItem(self.sequences_tree, [
            root_name, 
            "Папка", 
            "", 
            "0", 
            root_path
        ])
        self.root_item.setData(0, Qt.UserRole, {"type": "folder", "path": root_path})
        self.folder_items[root_path] = self.root_item
        
        # СРАЗУ РАСКРЫВАЕМ корневой элемент
        self.root_item.setExpanded(True)
        
        self.debug_logger.log(f"Создан и раскрыт корневой элемент: {root_path}")
        self.debug_logger.log(f"Словарь sequences очищен: {len(self.sequences)} элементов")
        
        # Принудительно обновляем интерфейс
        QApplication.processEvents()
        
        # Сбрасываем поиск
        self.clear_search()
        
        # Обновляем прогресс
        self.progress_label.setText("Начинаем поиск...")
        QApplication.processEvents()
        
        # Создаем новый поиск
        self.debug_logger.log("Создаем новый поиск...")
        self.sequence_finder = SequenceFinder(folder, self.debug_logger)
        self.sequence_finder.sequence_found.connect(self.on_sequence_found)
        self.sequence_finder.progress_update.connect(self.update_progress)
        self.sequence_finder.finished_signal.connect(self.on_search_finished)
        
        self.sequence_finder.start()
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.continue_btn.setEnabled(False)


    def expand_all_tree_items(self):
        """Раскрывает все элементы дерева"""
        def expand_item(item):
            item.setExpanded(True)
            for i in range(item.childCount()):
                expand_item(item.child(i))
        
        for i in range(self.sequences_tree.topLevelItemCount()):
            expand_item(self.sequences_tree.topLevelItem(i))



    def stop_search(self):
        if hasattr(self, 'sequence_finder') and self.sequence_finder.isRunning():
            self.sequence_finder.stop()
            self.stop_btn.setEnabled(False)
            self.continue_btn.setEnabled(True)
            self.progress_label.setText("Поиск приостановлен")

    def continue_search(self):
        if hasattr(self, 'sequence_finder'):
            self.sequence_finder.continue_search()
            self.sequence_finder.start()
            self.stop_btn.setEnabled(True)
            self.continue_btn.setEnabled(False)

    def on_sequence_found(self, sequence_data):
        """Добавляет найденную последовательность в коллекцию и сразу в дерево"""
        self.debug_logger.log(f"\n--- ПОЛУЧЕНА ПОСЛЕДОВАТЕЛЬНОСТЬ ---")
        self.debug_logger.log(f"Данные: {sequence_data}")
        
        # Проверяем, что данные корректны и добавляем недостающие поля
        required_keys = ['path', 'name', 'frame_range', 'frame_count', 'files', 'extension', 'type']
        
        # Добавляем недостающие поля
        if 'name' not in sequence_data:
            sequence_data['name'] = os.path.basename(sequence_data.get('first_file', 'Unknown'))
        if 'display_name' not in sequence_data:
            sequence_data['display_name'] = sequence_data['name']
        if 'frame_range' not in sequence_data:
            sequence_data['frame_range'] = ''
        if 'frame_count' not in sequence_data:
            sequence_data['frame_count'] = len(sequence_data.get('files', []))
        if 'type' not in sequence_data:
            sequence_data['type'] = 'unknown'
        
        # Проверяем наличие обязательных ключей
        missing_keys = [key for key in required_keys if key not in sequence_data]
        if missing_keys:
            self.debug_logger.log(f"ОШИБКА: Отсутствуют ключи: {missing_keys}", "ERROR")
            return
            
        # Проверяем, что ключевые поля не пустые
        empty_fields = []
        for key in ['path', 'name', 'extension']:
            if not sequence_data.get(key):
                empty_fields.append(key)
        
        if empty_fields:
            self.debug_logger.log(f"ОШИБКА: Пустые поля: {empty_fields}", "ERROR")
            return
            
        # Сохраняем последовательность
        key = f"{sequence_data['path']}/{sequence_data['name']}"
        self.sequences[key] = sequence_data
        self.debug_logger.log(f"  Сохранено в словарь sequences с ключом: '{key}'")
        
        # НЕМЕДЛЕННО добавляем в дерево
        self.add_sequence_to_tree(sequence_data)
        
        self.debug_logger.log(f"--- КОНЕЦ ДОБАВЛЕНИЯ ПОСЛЕДОВАТЕЛЬНОСТИ ---\n")



    def add_sequence_to_tree(self, seq_info):
        """Добавляет последовательность в дерево в реальном времени с сохранением структуры папок"""
        try:
            seq_path = seq_info['path']
            display_name = seq_info.get('display_name', seq_info.get('name', 'Unknown'))
            frame_range = seq_info.get('frame_range', '')
            frame_count = seq_info.get('frame_count', 0)
            seq_type = seq_info.get('type', 'unknown')
            
            self.debug_logger.log(f"add_sequence_to_tree: Добавляем '{display_name}' в папку '{seq_path}'")
            
            # Проверяем, что путь последовательности находится внутри корневой папки
            root_path = self.folder_path.text()
            if not seq_path.startswith(root_path):
                self.debug_logger.log(f"  Пропускаем последовательность вне корневой папки: {seq_path}")
                return
            
            # Находим или создаем родительскую папку для последовательности
            parent_item = self.find_or_create_folder_item(seq_path)
            
            # Создаем элемент для последовательности
            seq_item = QTreeWidgetItem([
                display_name,
                seq_type,
                frame_range,
                str(frame_count),
                seq_path
            ])
            seq_item.setData(0, Qt.UserRole, {"type": "sequence", "info": seq_info})
            
            # Применяем цвет в зависимости от типа последовательности
            self.color_tree_item_by_type(seq_item, seq_type)
            
            # Добавляем последовательность в родительскую папку
            parent_item.addChild(seq_item)
            
            # РАСКРЫВАЕМ всю иерархию до корня для этой последовательности
            self.expand_path_to_root(parent_item)
            
            self.debug_logger.log(f"Успешно добавлено в дерево: {display_name}")
            
        except Exception as e:
            self.debug_logger.log(f"Ошибка при добавлении в дерево: {str(e)}", "ERROR")
            import traceback
            self.debug_logger.log(f"Трассировка: {traceback.format_exc()}", "ERROR")



    def expand_path_to_root(self, item):
        """Рекурсивно раскрывает все родительские элементы до корня"""
        current_item = item
        while current_item is not None:
            current_item.setExpanded(True)
            current_item = current_item.parent()



    def find_or_create_folder_item(self, folder_path):
        """Находит или создает элементы папок для указанного пути"""
        # Если папка уже существует в словаре, возвращаем ее
        if folder_path in self.folder_items:
            item = self.folder_items[folder_path]
            # РАСКРЫВАЕМ существующую папку
            item.setExpanded(True)
            return item
        
        self.debug_logger.log(f"find_or_create_folder_item: Создаем папку '{folder_path}'")
        
        # Получаем корневую папку поиска
        root_path = self.folder_path.text()
        
        # Если путь совпадает с корневым, возвращаем корневой элемент
        if folder_path == root_path:
            return self.root_item
        
        # Определяем относительный путь от корневой папки
        if folder_path.startswith(root_path):
            relative_path = folder_path[len(root_path):].lstrip(os.sep)
        else:
            relative_path = folder_path
        
        # Разбиваем относительный путь на компоненты
        parts = relative_path.split(os.sep)
        current_path = root_path
        parent_item = self.root_item
        
        # Строим путь от корня до целевой папки
        for part in parts:
            if not part:  # Пропускаем пустые части
                continue
                
            # Обновляем текущий путь
            current_path = os.path.join(current_path, part)
            
            # Если папка еще не создана, создаем ее
            if current_path not in self.folder_items:
                folder_name = part
                folder_item = QTreeWidgetItem([
                    folder_name,
                    "Папка",
                    "",
                    "", #"0",
                    "" #current_path
                ])
                folder_item.setData(0, Qt.UserRole, {"type": "folder", "path": current_path})
                
                # Добавляем в родительскую папку
                parent_item.addChild(folder_item)
                self.folder_items[current_path] = folder_item
                
                # СРАЗУ РАСКРЫВАЕМ новую папку
                folder_item.setExpanded(True)
                
                self.debug_logger.log(f"  Создана и раскрыта папка: '{folder_name}' -> '{current_path}'")
            
            # Обновляем родительский элемент для следующей итерации
            parent_item = self.folder_items[current_path]
            
            # Убедимся, что родительская папка тоже раскрыта
            if hasattr(parent_item, 'setExpanded'):
                parent_item.setExpanded(True)
        
        return parent_item
    

    def update_folder_count(self, folder_item):
        """Обновляет счетчик файлов в папке"""
        try:
            folder_data = folder_item.data(0, Qt.UserRole)
            if folder_data and folder_data.get('type') == 'folder':
                folder_path = folder_data.get('path')
                
                # Подсчитываем последовательности в этой папке
                count = 0
                for seq_info in self.sequences.values():
                    if seq_info['path'] == folder_path:
                        count += 1
                
                # Обновляем отображение счетчика
                folder_item.setText(3, str(count))
                
                # Рекурсивно обновляем родительские папки
                parent = folder_item.parent()
                if parent:
                    self.update_folder_count(parent)
                else:
                    # Если это корневой элемент, обновляем его
                    root_count = sum(1 for seq_info in self.sequences.values())
                    folder_item.setText(3, str(root_count))
                    
        except Exception as e:
            self.debug_logger.log(f"Ошибка при обновлении счетчика папки: {str(e)}", "ERROR")


    def update_progress(self, message):
        self.progress_label.setText(message)

    def expand_all_tree_items(self):
        """Раскрывает все элементы дерева"""
        def expand_item(item):
            item.setExpanded(True)
            for i in range(item.childCount()):
                expand_item(item.child(i))
        
        for i in range(self.sequences_tree.topLevelItemCount()):
            expand_item(self.sequences_tree.topLevelItem(i))

# Можно вызвать этот метод в on_search_finished для полного раскрытия после завершения поиска
    def on_search_finished(self):
        """Обрабатывает завершение поиска"""
        try:
            # Обновляем статистику
            sequence_count = len(self.sequences)
            folder_count = len(self.folder_items)
            
            self.progress_label.setText(f"Поиск завершен. Найдено {sequence_count} последовательностей в {folder_count} папках")
            self.debug_logger.log(f"Поиск завершен. Найдено {sequence_count} последовательностей в {folder_count} папках")
            
            # Дополнительная отладочная информация
            total_tree_items = self.count_tree_items(self.root_item)
            self.debug_logger.log(f"Всего элементов в дереве: {total_tree_items}")
            
            # РАСКРЫВАЕМ ВСЕ ДЕРЕВО после завершения поиска
            self.expand_all_tree_items()
            
        except Exception as e:
            self.debug_logger.log(f"Ошибка при завершении поиска: {str(e)}", "ERROR")
            self.progress_label.setText(f"Ошибка при завершении поиска: {str(e)}")
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.continue_btn.setEnabled(False)
        
        # Принудительно обновляем интерфейс
        QApplication.processEvents()


    def count_tree_items(self, item):
        """Рекурсивно подсчитывает количество элементов в дереве"""
        count = 1  # Текущий элемент
        for i in range(item.childCount()):
            count += self.count_tree_items(item.child(i))
        return count

    def flatten_json(self, json_data, parent_key='', separator='.'):
        """
        Рекурсивно разбирает JSON на отдельные ключи и значения
        """
        items = {}
        if isinstance(json_data, dict):
            for key, value in json_data.items():
                new_key = f"{parent_key}{separator}{key}" if parent_key else key
                if isinstance(value, (dict, list)):
                    items.update(self.flatten_json(value, new_key, separator))
                else:
                    items[new_key] = value
        elif isinstance(json_data, list):
            for i, value in enumerate(json_data):
                new_key = f"{parent_key}{separator}{i}" if parent_key else str(i)
                if isinstance(value, (dict, list)):
                    items.update(self.flatten_json(value, new_key, separator))
                else:
                    items[new_key] = value
        else:
            items[parent_key] = json_data
        return items











    def display_metadata(self, file_path, extension, forced_tool=None):
        """Отображает метаданные для файла"""
        try:
            if not os.path.exists(file_path):
                self.metadata_table.setRowCount(1)
                self.metadata_table.setItem(0, 0, QTableWidgetItem("Ошибка"))
                self.metadata_table.setItem(0, 1, QTableWidgetItem(f"Файл не найден: {file_path}"))
                self.metadata_source_label.setText("Метаданные выбранного элемента: Ошибка")
                return
            
            # Сбрасываем состояние форсированного чтения, если выбран другой файл
            if forced_tool is None and self.forced_metadata_file != file_path:
                self.forced_metadata_tool = None
                self.forced_metadata_file = None
            
            # Определяем инструмент для чтения метаданных
            # ПРИОРИТЕТ: принудительный инструмент > сохраненный форсированный > инструмент по умолчанию
            if forced_tool:
                metadata_tool = forced_tool
            elif self.forced_metadata_tool and self.forced_metadata_file == file_path:
                metadata_tool = self.forced_metadata_tool
            else:
                metadata_tool = self.default_metadata_tool
                
            self.debug_logger.log(f"Чтение метаданных для {file_path} с помощью {metadata_tool}")
            
            # Собираем все метаданные
            self.current_metadata = {}
            metadata_source = "System"
            
            # ЕСЛИ УКАЗАН ПРИНУДИТЕЛЬНЫЙ ИНСТРУМЕНТ - ИСПОЛЬЗУЕМ ЕГО ДЛЯ ЛЮБОГО ФАЙЛА
            if forced_tool:
                if forced_tool == 'ffprobe':
                    self.add_ffprobe_metadata(file_path)
                    metadata_source = "FFprobe (принудительно)"
                else:  # mediainfo
                    if PYMEDIAINFO_AVAILABLE:
                        self.add_mediainfo_metadata(file_path)
                        metadata_source = "MediaInfo (принудительно)"
                    else:
                        self.current_metadata["MediaInfo Error"] = "MediaInfo не доступен"
                        metadata_source = "MediaInfo Not Available"
            
            # СТАНДАРТНАЯ ЛОГИКА (когда forced_tool = None)
            else:
                # Для MXF файлов (логика остается прежней)
                if extension.lower() == '.mxf' or '.arr' or '.arx':
                    # Если включена галочка и ART доступен, используем ART
                    if self.use_art_for_mxf and os.path.exists(ARRI_REFERENCE_TOOL_PATH):
                        try:
                            # Создаем временный файл для вывода ARRI Tool
                            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
                                temp_json_path = temp_file.name
                            
                            # Запускаем ARRI Reference Tool
                            cmd = [
                                ARRI_REFERENCE_TOOL_PATH,
                                'export',
                                '--duration', '1',
                                '--input', file_path,
                                '--output', temp_json_path
                            ]
                            
                            self.debug_logger.log(f"Запуск ARRI Reference Tool: {' '.join(cmd)}")
                            
                            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                            
                            if result.returncode == 0 and os.path.exists(temp_json_path):
                                # Успешно получили метаданные от ARRI Tool
                                with open(temp_json_path, 'r', encoding='utf-8') as f:
                                    arri_metadata = json.load(f)
                                
                                # Разбираем JSON на отдельные ключи и значения
                                flattened_metadata = self.flatten_json(arri_metadata)
                                
                                # Добавляем метаданные в общий словарь
                                for key, value in flattened_metadata.items():
                                    self.current_metadata[f"ARRI.{key}"] = self.format_metadata_value(value)
                                
                                metadata_source = "ARRI Reference Tool"
                                self.debug_logger.log(f"Прочитано {len(flattened_metadata)} метаданных ARRI из {file_path}")
                                
                                # Удаляем временный файл
                                os.unlink(temp_json_path)
                            else:
                                self.debug_logger.log(f"ARRI Tool вернул ошибку: {result.stderr}", "WARNING")
                                # Если ARRI Tool не сработал, используем MediaInfo
                                if PYMEDIAINFO_AVAILABLE:
                                    self.debug_logger.log("Используем MediaInfo как fallback для MXF")
                                    self.add_mediainfo_metadata(file_path)
                                    metadata_source = "MediaInfo (ART fallback)"
                                else:
                                    self.current_metadata["ARRI Tool Error"] = f"ARRI Tool failed: {result.stderr}"
                                    metadata_source = "ARRI Tool Failed"
                                    
                        except subprocess.TimeoutExpired:
                            self.debug_logger.log("ARRI Tool timeout", "WARNING")
                            if PYMEDIAINFO_AVAILABLE:
                                self.add_mediainfo_metadata(file_path)
                                metadata_source = "MediaInfo (ART timeout fallback)"
                            else:
                                self.current_metadata["ARRI Tool Error"] = "ARRI Tool timeout"
                                metadata_source = "ARRI Tool Timeout"
                        except Exception as e:
                            self.debug_logger.log(f"Ошибка ARRI Tool: {str(e)}", "WARNING")
                            if PYMEDIAINFO_AVAILABLE:
                                self.add_mediainfo_metadata(file_path)
                                metadata_source = "MediaInfo (ART error fallback)"
                            else:
                                self.current_metadata["ARRI Tool Error"] = f"ARRI Tool error: {str(e)}"
                                metadata_source = "ARRI Tool Error"
                    else:
                        # По умолчанию используем MediaInfo для MXF
                        if PYMEDIAINFO_AVAILABLE:
                            self.add_mediainfo_metadata(file_path)
                            metadata_source = "MediaInfo"
                        else:
                            self.current_metadata["MediaInfo Error"] = "MediaInfo не доступен"
                            metadata_source = "MediaInfo Not Available"
                
                # Для EXR файлов используем OpenEXR для чтения метаданных
                elif extension.lower() == '.exr':
                    try:
                        exr_file = OpenEXR.InputFile(file_path)
                        header = exr_file.header()
                        
                        for key, value in header.items():
                            self.current_metadata[key] = self.format_metadata_value(value)
                        metadata_source = "OpenEXR"
                        self.debug_logger.log(f"Прочитано {len(header)} метаданных EXR из {file_path}")
                    except Exception as e:
                        self.current_metadata["Ошибка чтения EXR"] = f"Не удалось прочитать EXR метаданные: {str(e)}"
                        metadata_source = "OpenEXR Error"
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
                            metadata_source = "exifread"
                            self.debug_logger.log(f"Прочитано {len(tags)} EXIF тегов из {file_path}")
                        else:
                            self.current_metadata["EXIF"] = "EXIF данные не найдены"
                            metadata_source = "exifread"
                            self.debug_logger.log(f"EXIF данные не найдены в {file_path}")
                    except Exception as e:
                        self.current_metadata["Ошибка чтения EXIF"] = f"Не удалось прочитать EXIF метаданные: {str(e)}"
                        metadata_source = "exifread Error"
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
                                metadata_source = "Pillow"
                                self.debug_logger.log(f"Прочитано {len(exif_data)} EXIF тегов из {file_path}")
                            else:
                                self.current_metadata["EXIF"] = "EXIF данные не найдены"
                                metadata_source = "Pillow"
                                self.debug_logger.log(f"EXIF данные не найдены в {file_path}")
                            
                            # Получаем другую информацию
                            info = img.info
                            for key, value in info.items():
                                if key != 'exif':  # EXIF уже обработали отдельно
                                    self.current_metadata[key] = str(value)
                    except Exception as e:
                        self.current_metadata["Ошибка чтения"] = f"Не удалось прочитать метаданные изображения: {str(e)}"
                        metadata_source = "Pillow Error"
                        self.debug_logger.log(f"Ошибка чтения изображения для {file_path}: {str(e)}", "ERROR")
                
                # Для остальных файлов используем выбранный инструмент по умолчанию
                else:
                    if metadata_tool == 'ffprobe':
                        self.add_ffprobe_metadata(file_path)
                        metadata_source = "FFprobe"
                    else:  # mediainfo
                        if PYMEDIAINFO_AVAILABLE:
                            self.add_mediainfo_metadata(file_path)
                            metadata_source = "MediaInfo"
                        else:
                            self.current_metadata["MediaInfo Error"] = "MediaInfo не доступен"
                            metadata_source = "MediaInfo Not Available"
            
            # Для всех файлов добавляем базовую информацию
            file_stats = os.stat(file_path)
            self.current_metadata["Имя файла"] = os.path.basename(file_path)
            self.current_metadata["Путь"] = file_path
            self.current_metadata["Размер файла"] = f"{file_stats.st_size} байт ({file_stats.st_size / 1024 / 1024:.2f} MB)"
            self.current_metadata["Дата создания"] = datetime.datetime.fromtimestamp(file_stats.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
            self.current_metadata["Дата изменения"] = datetime.datetime.fromtimestamp(file_stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            
            self.debug_logger.log(f"Всего собрано {len(self.current_metadata)} метаданных для {file_path}")

                        # Если использовался принудительный инструмент, добавляем отметку
            if forced_tool:
                metadata_source = f"{metadata_source} (принудительно)"
            
            


            
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
            
            # Обновляем метку с источником метаданных
            self.metadata_source_label.setText(f"Метаданные выбранного элемента ({metadata_source}):")
            
            # Сбрасываем фильтр поиска при отображении новых данных
            self.clear_search()
            
        except Exception as e:
            self.metadata_table.setRowCount(1)
            self.metadata_table.setItem(0, 0, QTableWidgetItem("Ошибка"))
            self.metadata_table.setItem(0, 1, QTableWidgetItem(f"Ошибка чтения метаданных: {str(e)}"))
            self.metadata_source_label.setText("Метаданные выбранного элемента: Ошибка")
            self.debug_logger.log(f"Общая ошибка чтения метаданных для {file_path}: {str(e)}", "ERROR")

        if self.forced_metadata_tool and self.forced_metadata_file == file_path:
            tool_name = METADATA_TOOLS.get(self.forced_metadata_tool, self.forced_metadata_tool)
            self.metadata_source_label.setText(f"Метаданные выбранного элемента ({tool_name} - принудительно):")
        else:
            self.metadata_source_label.setText(f"Метаданные выбранного элемента ({metadata_source}):")



    def add_ffprobe_metadata(self, file_path):
        """Добавляет метаданные через FFprobe"""
        try:
            # Проверяем доступность ffprobe
            result = subprocess.run(['ffprobe', '-version'], capture_output=True, text=True)
            if result.returncode != 0:
                self.current_metadata["Ошибка FFprobe"] = "FFprobe не доступен в системе"
                self.debug_logger.log("FFprobe не доступен в системе", "WARNING")
                return
            
            # Запускаем ffprobe для получения метаданных в формате JSON
            cmd = [
                'ffprobe', 
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                '-show_chapters',
                '-show_programs',
                file_path
            ]
            
            self.debug_logger.log(f"Запуск FFprobe: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                ffprobe_data = json.loads(result.stdout)
                
                # Обрабатываем формат
                if 'format' in ffprobe_data:
                    format_data = ffprobe_data['format']
                    for key, value in format_data.items():
                        if key != 'tags':  # Теги обработаем отдельно
                            self.current_metadata[f"FFprobe Format - {key}"] = self.format_ffprobe_value(value)
                    
                    # Обрабатываем теги формата
                    if 'tags' in format_data:
                        for tag_key, tag_value in format_data['tags'].items():
                            self.current_metadata[f"FFprobe Format Tag - {tag_key}"] = self.format_ffprobe_value(tag_value)
                
                # Обрабатываем потоки
                if 'streams' in ffprobe_data:
                    for i, stream in enumerate(ffprobe_data['streams']):
                        stream_type = stream.get('codec_type', 'unknown')
                        for key, value in stream.items():
                            if key != 'tags' and key != 'disposition':
                                self.current_metadata[f"FFprobe Stream {i} ({stream_type}) - {key}"] = self.format_ffprobe_value(value)
                        
                        # Обрабатываем теги потока
                        if 'tags' in stream:
                            for tag_key, tag_value in stream['tags'].items():
                                self.current_metadata[f"FFprobe Stream {i} ({stream_type}) Tag - {tag_key}"] = self.format_ffprobe_value(tag_value)
                        
                        # Обрабатываем disposition
                        if 'disposition' in stream:
                            for disp_key, disp_value in stream['disposition'].items():
                                if disp_value == 1:  # Показываем только активные disposition
                                    self.current_metadata[f"FFprobe Stream {i} ({stream_type}) Disposition - {disp_key}"] = "Да"
                
                # Обрабатываем программы
                if 'programs' in ffprobe_data:
                    for i, program in enumerate(ffprobe_data['programs']):
                        for key, value in program.items():
                            if key != 'streams' and key != 'tags':
                                self.current_metadata[f"FFprobe Program {i} - {key}"] = self.format_ffprobe_value(value)
                        
                        if 'tags' in program:
                            for tag_key, tag_value in program['tags'].items():
                                self.current_metadata[f"FFprobe Program {i} Tag - {tag_key}"] = self.format_ffprobe_value(tag_value)
                
                # Обрабатываем главы
                if 'chapters' in ffprobe_data:
                    for i, chapter in enumerate(ffprobe_data['chapters']):
                        for key, value in chapter.items():
                            if key != 'tags':
                                self.current_metadata[f"FFprobe Chapter {i} - {key}"] = self.format_ffprobe_value(value)
                        
                        if 'tags' in chapter:
                            for tag_key, tag_value in chapter['tags'].items():
                                self.current_metadata[f"FFprobe Chapter {i} Tag - {tag_key}"] = self.format_ffprobe_value(tag_value)
                
                self.debug_logger.log(f"Прочитано {len(ffprobe_data)} разделов FFprobe из {file_path}")
                
            else:
                self.current_metadata["Ошибка FFprobe"] = f"FFprobe вернул ошибку: {result.stderr}"
                self.debug_logger.log(f"Ошибка FFprobe для {file_path}: {result.stderr}", "ERROR")
                
        except subprocess.TimeoutExpired:
            self.current_metadata["Ошибка FFprobe"] = "Таймаут выполнения FFprobe"
            self.debug_logger.log(f"Таймаут FFprobe для {file_path}", "ERROR")
        except Exception as e:
            self.current_metadata["Ошибка FFprobe"] = f"Не удалось прочитать FFprobe метаданные: {str(e)}"
            self.debug_logger.log(f"Ошибка чтения FFprobe для {file_path}: {str(e)}", "ERROR")

    def format_ffprobe_value(self, value):
        """Форматирует значение FFprobe для лучшего отображения"""
        if isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            return value
        elif isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        elif isinstance(value, list):
            return ", ".join(str(item) for item in value)
        else:
            return str(value)





    def add_mediainfo_metadata(self, file_path):
        """Добавляет метаданные через MediaInfo"""
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
        """Обновляет цвета в дереве последовательностей"""
        # Проходим по всем элементам дерева и обновляем цвета
        for i in range(self.sequences_tree.topLevelItemCount()):
            top_item = self.sequences_tree.topLevelItem(i)
            self.update_tree_item_colors(top_item)

    def update_tree_item_colors(self, item):
        """Рекурсивно обновляет цвета элементов дерева"""
        item_data = item.data(0, Qt.UserRole)
        if item_data and item_data['type'] == 'sequence':
            seq_type = item_data['info']['type']
            self.color_tree_item_by_type(item, seq_type)
        
        # Рекурсивно обрабатываем дочерние элементы
        for i in range(item.childCount()):
            self.update_tree_item_colors(item.child(i))

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
        if self.sequences_tree.selectedItems():
            self.on_tree_item_selected()

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
            # Создаем директорию для настроек если ее нет (для жесткого пути)
            if SETTINGS_FILE_HARD:
                settings_dir = os.path.dirname(SETTINGS_FILE_HARD)
                if settings_dir and not os.path.exists(settings_dir):
                    os.makedirs(settings_dir, exist_ok=True)
                    
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
                    
                    # Загружаем настройку использования ART для MXF
                    self.use_art_for_mxf = settings.get('use_art_for_mxf', False)
                    
                    # Если ordered_metadata_fields пуст, инициализируем его из color_metadata
                    if not self.ordered_metadata_fields and self.color_metadata:
                        self.ordered_metadata_fields = list(self.color_metadata.keys())
                        
        except Exception as e:
            self.debug_logger.log(f"Ошибка загрузки настроек: {e}", "ERROR")
            self.color_metadata = {}
            self.removed_metadata = {}
            self.sequence_colors = {}
            self.ordered_metadata_fields = []
            self.use_art_for_mxf = False

    def save_settings(self):
        """Сохраняет настройки в файл"""
        try:
            # Создаем директорию для настроек если ее нет (для жесткого пути)
            if SETTINGS_FILE_HARD:
                settings_dir = os.path.dirname(SETTINGS_FILE_HARD)
                if settings_dir and not os.path.exists(settings_dir):
                    os.makedirs(settings_dir, exist_ok=True)

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
                'ordered_metadata_fields': self.ordered_metadata_fields,
                'use_art_for_mxf': self.use_art_for_mxf
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
