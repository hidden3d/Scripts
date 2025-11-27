
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
                             QTextEdit, QLabel, QFileDialog, QMessageBox,  # QTextEdit уже здесь
                             QListWidgetItem, QColorDialog, QDialog, QDialogButtonBox,
                             QFormLayout, QComboBox, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView, QMenu, QAction, QTabWidget,
                             QSplitter, QTextBrowser, QScrollArea, QCheckBox, QInputDialog)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QSettings, QTimer, QPropertyAnimation, QObject
from PyQt5.QtGui import QTextCursor, QColor, QTextCharFormat, QFont, QBrush, QPainter, QColor, QPen
from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QPlainTextEdit

# ==================== НАСТРОЙКИ ====================

DEBUG = False  # Включаем логирование для отладки

SETTINGS_FILE_HARD = "/studio/tools/pipeline/commandor-test/studio/Scripts/exr_viewer_settings.json"
# Путь к ARRI Reference Tool
ARRI_REFERENCE_TOOL_PATH = "/studio/tools/ART_cmd/bin/art-cmd"

# Добавляем путь к REDline для чтения R3D файлов
REDLINE_TOOL_PATH = "/studio/tools/REDline2/REDline"

CAMERA_SENSOR_DATA_FILE = "/studio/tools/pipeline/commandor-test/studio/Scripts/Camera_sensor_data.json"


DEFAULT_FONT_SIZE = 10  # Размер шрифта по умолчанию
DEFAULT_COLUMN_WIDTHS = {  # Ширины столбцов по умолчанию
    'sequences': [500, 500, 80, 100, 100],  # Путь, Имя, Расширение, Диапазон, Количество
    'metadata': [300, 500]  # Поле, Значение
}

METADATA_TOOLS = {
    'mediainfo': 'MediaInfo',
    'ffprobe': 'FFprobe',
    'exiftool': 'ExifTool'
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

# Попытка импорта PyExifTool для чтения метаданных через ExifTool
try:
    import exiftool
    EXIFTOOL_AVAILABLE = True
    print("Библиотека PyExifTool доступна. Метаданные через ExifTool будут доступны.")
except ImportError:
    EXIFTOOL_AVAILABLE = False
    print("Библиотека PyExifTool не установлена. Метаданные через ExifTool не будут доступны.")
    print("Установите ее: pip install pyexiftool")




class ToastMessage(QLabel):
    """Всплывающее сообщение (Toast) с ручной отрисовкой фона"""
    
    def __init__(self, message, parent=None, duration=2000, opacity=0.8):
        super().__init__(parent)
        self.duration = duration
        self.background_opacity = int(255 * opacity)  # Конвертируем в 0-255
        
        # Настройка текста
        self.setText(message)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setMargin(15)
        
        # Настройка стиля текста (без фона)
        self.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 26px;
                font-weight: 500;
                background: transparent;
            }
        """)
        
        # Настройка флагов окна
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        # Анимация
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(300)
        self.animation.finished.connect(self.check_animation_finished)
        
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide_toast)
    
    def paintEvent(self, event):
        """Ручная отрисовка фона с прозрачностью"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Рисуем полупрозрачный фон с закругленными углами
        background_color = QColor(50, 50, 50, self.background_opacity)
        painter.setBrush(background_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 10, 10)
        
        # Рисуем границу
        border_color = QColor(255, 255, 255, 50)
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)
        
        # Вызываем стандартную отрисовку текста
        super().paintEvent(event)
    
    def show_toast(self):
        """Показывает toast сообщение по центру родителя"""
        self.adjustSize()
        
        # Позиционируем по центру родительского окна
        if self.parent():
            parent_rect = self.parent().geometry()
            x = parent_rect.left() + (parent_rect.width() - self.width()) // 2
            y = parent_rect.top() + (parent_rect.height() - self.height()) // 2
            self.move(x, y)
        else:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            x = (screen_geometry.width() - self.width()) // 2
            y = (screen_geometry.height() - self.height()) // 2
            self.move(x, y)
        
        # Анимация появления
        self.setWindowOpacity(0.0)
        self.show()
        
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()
        
        self.timer.start(self.duration)
    
    def hide_toast(self):
        """Скрывает toast с анимацией"""
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.start()
    
    def check_animation_finished(self):
        """Проверяет завершение анимации и скрывает виджет"""
        if self.windowOpacity() == 0.0:
            self.hide()
            self.deleteLater()




class DebugLogger(QObject):
    """Класс для сбора отладочной информации с поддержкой реального времени"""
    
    # Сигнал для отправки новых сообщений лога
    new_log_message = pyqtSignal(str)
    
    def __init__(self, debug_enabled=DEBUG, parent=None):
        super().__init__(parent)
        self.debug_enabled = debug_enabled
        self.log_messages = []
        self.max_log_size = 5000000  # Уменьшим максимальный размер лога
        self._emit_timer = QTimer()
        self._emit_timer.setSingleShot(True)
        self._emit_timer.timeout.connect(self._emit_buffered_messages)
        self._message_buffer = []
        self._buffer_size = 20
        self._buffer_delay = 50  # Увеличим задержку
        
    def log(self, message, level="INFO"):
        """Добавляет сообщение в лог с буферизацией"""
        if not self.debug_enabled:
            return
            
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] [{level}] {message}"
        self.log_messages.append(log_entry)
        self._message_buffer.append(log_entry)
        
        # Ограничиваем размер лога
        if len(self.log_messages) > self.max_log_size:
            self.log_messages = self.log_messages[-self.max_log_size:]
        
        # Отправляем сигнал с задержкой и буферизацией
        if len(self._message_buffer) >= self._buffer_size:
            self._emit_buffered_messages()
        elif not self._emit_timer.isActive():
            self._emit_timer.start(self._buffer_delay)
    
    def _emit_buffered_messages(self):
        """Отправляет буферизованные сообщения одним сигналом"""
        if self._message_buffer:
            # Объединяем сообщения в одну строку
            combined_message = "\n".join(self._message_buffer)
            self.new_log_message.emit(combined_message)
            self._message_buffer.clear()
    
    def get_log_text(self):
        """Возвращает весь лог как текст"""
        return "\n".join(self.log_messages)
    
    def clear_log(self):
        """Очищает лог"""
        self.log_messages = []
        self._message_buffer.clear()
        self._emit_timer.stop()
        self.new_log_message.emit("=== Лог очищен ===")
    
    def set_debug_enabled(self, enabled):
        """Включает/выключает логирование"""
        self.debug_enabled = enabled



class LogViewerDialog(QDialog):
    """Диалог для просмотра логов в реальном времени с улучшенной производительностью"""
    
    def __init__(self, debug_logger, parent=None):
        super().__init__(parent)
        self.debug_logger = debug_logger
        self.setup_ui()
        
        # Улучшенная буферизация
        self.log_buffer = []
        self.buffer_size = 30  # Уменьшим размер буфера
        self.buffer_timer = QTimer()
        self.buffer_timer.setSingleShot(True)
        self.buffer_timer.timeout.connect(self.flush_buffer)
        self.buffer_delay = 150  # Увеличим задержку
        
        # Статистика
        self.message_count = 0
        self.last_update_time = datetime.datetime.now()
        self.update_interval = 2000  # Обновляем статистику реже
        
        # Подключаем сигнал для обновления лога в реальном времени
        self.debug_logger.new_log_message.connect(self.add_log_message_buffered)
        
        # Загружаем существующие сообщения
        self.load_existing_logs()
        
        # Таймер для периодического обновления статистики
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.update_stats)
        self.stats_timer.start(self.update_interval)
        
        # Оптимизация производительности
        self._processing = False
        
    def setup_ui(self):
        self.setWindowTitle("Лог приложения")
        self.setGeometry(300, 300, 900, 600)  # Уменьшим размер
        
        layout = QVBoxLayout()
        
        # Упрощенная панель управления
        control_layout = QHBoxLayout()
        self.clear_btn = QPushButton("Очистить")
        self.save_btn = QPushButton("Сохранить")
        self.autoscroll_checkbox = QCheckBox("Автопрокрутка")
        self.autoscroll_checkbox.setChecked(True)
        
        self.pause_checkbox = QCheckBox("Пауза")
        
        self.clear_btn.clicked.connect(self.clear_log)
        self.save_btn.clicked.connect(self.save_log)
        
        control_layout.addWidget(self.clear_btn)
        control_layout.addWidget(self.save_btn)
        control_layout.addWidget(self.autoscroll_checkbox)
        control_layout.addWidget(self.pause_checkbox)
        control_layout.addStretch()
        
        # Упрощенная статистика
        self.stats_label = QLabel("Сообщений: 0")
        
        # Используем QPlainTextEdit вместо QTextBrowser - он более эффективен
        self.log_text = QPlainTextEdit()
        self.log_text.setFont(QFont("Courier", 8))  # Уменьшим шрифт
        self.log_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(5000)  # Ограничим количество строк
        
        layout.addWidget(self.stats_label)
        layout.addLayout(control_layout)
        layout.addWidget(self.log_text)
        
        self.setLayout(layout)
        
    def load_existing_logs(self):
        """Загружает существующие сообщения лога"""
        try:
            existing_logs = self.debug_logger.get_log_text()
            if existing_logs:
                self.log_text.setPlainText(existing_logs)
                self.message_count = len(self.debug_logger.log_messages)
                self.scroll_to_bottom()
                self.update_stats()
        except Exception as e:
            print(f"Error loading existing logs: {e}")
        
    def add_log_message_buffered(self, message):
        """Добавляет сообщение в буфер для группировки"""
        if self.pause_checkbox.isChecked() or self._processing:
            return
            
        # Если сообщение содержит несколько строк, разбиваем их
        if '\n' in message:
            lines = message.split('\n')
            self.log_buffer.extend(lines)
            self.message_count += len(lines)
        else:
            self.log_buffer.append(message)
            self.message_count += 1
        
        # Если буфер достиг максимального размера, сбрасываем немедленно
        if len(self.log_buffer) >= self.buffer_size:
            self.flush_buffer()
        elif not self.buffer_timer.isActive():
            # Запускаем таймер для сброса буфера через указанное время
            self.buffer_timer.start(self.buffer_delay)
    
    def flush_buffer(self):
        """Выводит все сообщения из буфера в текстовое поле"""
        if not self.log_buffer or self.pause_checkbox.isChecked() or self._processing:
            return
            
        self._processing = True
        
        try:
            # Останавливаем таймер, если он активен
            self.buffer_timer.stop()
            
            # Используем QPlainTextEdit для лучшей производительности
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.End)
            
            # Добавляем перенос строки если это не первое сообщение
            if not self.log_text.document().isEmpty():
                cursor.insertText("\n")
            
            # Вставляем все сообщения из буфера
            cursor.insertText("\n".join(self.log_buffer))
            
            # Автопрокрутка вниз
            if self.autoscroll_checkbox.isChecked():
                self.scroll_to_bottom()
            
            # Очищаем буфер
            self.log_buffer.clear()
            
            # Обновляем статистику
            self.update_stats()
            
        except Exception as e:
            print(f"Error flushing buffer: {e}")
        finally:
            self._processing = False
    
    def scroll_to_bottom(self):
        """Прокручивает лог вниз"""
        try:
            scrollbar = self.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        except Exception as e:
            print(f"Error scrolling to bottom: {e}")
        
    def refresh_log(self):
        """Полностью обновляет содержимое лога"""
        try:
            # Сначала сбрасываем буфер
            if self.log_buffer:
                self.flush_buffer()
                
            # Затем загружаем полный лог
            self.log_text.setPlainText(self.debug_logger.get_log_text())
            if self.autoscroll_checkbox.isChecked():
                self.scroll_to_bottom()
        except Exception as e:
            print(f"Error refreshing log: {e}")
        
    def clear_log(self):
        """Очищает лог"""
        try:
            # Сбрасываем буфер
            self.log_buffer.clear()
            self.buffer_timer.stop()
            
            # Очищаем логгер и текстовое поле
            self.debug_logger.clear_log()
            self.message_count = 0
            self.update_stats()
        except Exception as e:
            print(f"Error clearing log: {e}")
        
    def save_log(self):
        """Сохраняет лог в файл"""
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Сохранить лог", f"exr_viewer_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt", 
                "Text Files (*.txt)"
            )
            if filename:
                # Сначала сбрасываем буфер, чтобы сохранить все сообщения
                if self.log_buffer:
                    self.flush_buffer()
                    
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.debug_logger.get_log_text())
                QMessageBox.information(self, "Успех", f"Лог сохранен в файл:\n{filename}")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить лог: {str(e)}")
    
    def update_stats(self):
        """Обновляет статистику"""
        try:
            self.stats_label.setText(f"Сообщений: {self.message_count} | Буфер: {len(self.log_buffer)}")
        except Exception as e:
            print(f"Error updating stats: {e}")
    
    def closeEvent(self, event):
        """Обрабатывает закрытие окна"""
        try:
            # Сбрасываем буфер перед закрытием
            if self.log_buffer:
                self.flush_buffer()
                
            # Останавливаем таймеры
            self.buffer_timer.stop()
            self.stats_timer.stop()
            
            # Отключаем сигнал при закрытии окна
            try:
                self.debug_logger.new_log_message.disconnect(self.add_log_message_buffered)
            except:
                pass
                
        except Exception as e:
            print(f"Error in close event: {e}")
            
        event.accept()


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
                               '.f4v', '.ogv', '.ts', '.mts', '.m2ts', '.mxf', '.r3d'}

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
                _, ext = os.path.splitext(file)
                ext = ext.lower()
                
                # ОТПРАВКА СООБЩЕНИЯ О ПРОГРЕССЕ - обработка файла
                self.progress_update.emit(f"Обработка: {file}")
                
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
        
        # Обработка текущей директории
        files_by_extension = self.find_sequences_in_directory(directory)
        
        # Формирование последовательностей
        sequences = self.form_sequences(files_by_extension, directory)
        all_sequences.update(sequences)
        
        # Отправка найденных последовательностей
        for seq_name, seq_info in sequences.items():
            if not self._is_running:
                break
            
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
            
        # Рекурсивный поиск в подпапках
        try:
            for item in os.listdir(directory):
                if not self._is_running:
                    break
                    
                item_path = os.path.join(directory, item)
                if os.path.isdir(item_path):
                    # ОТПРАВКА СООБЩЕНИЯ О ПРОГРЕССЕ - обработка папки
                    self.progress_update.emit(f"Поиск в папке: {item}")
                    sub_sequences = self.find_sequences_recursive(item_path)
                    all_sequences.update(sub_sequences)
        except PermissionError:
            pass
            
        return all_sequences
    
    def find_sequences_optimized(self, directory):
        """Оптимизированный гибридный подход"""
        all_sequences = {}
        
        try:
            # Используем os.walk для основного обхода
            for root, dirs, files in os.walk(directory):
                if not self._is_running:
                    break
                    
                self.progress_update.emit(f"Обработка: {os.path.basename(root)}")
                
                # Группируем файлы по расширениям
                files_by_extension = defaultdict(list)
                
                for file in files:
                    if not self._is_running:
                        break
                        
                    file_path = os.path.join(root, file)
                    _, ext = os.path.splitext(file)
                    ext = ext.lower()
                    
                    base_name, frame_num = self.extract_sequence_info(file)
                    files_by_extension[ext].append((base_name, frame_num, file_path, file))
                
                # Формируем последовательности для текущей папки
                sequences = self.form_sequences(files_by_extension, root)
                all_sequences.update(sequences)
                
                # Отправляем найденные последовательности
                for seq_name, seq_info in sequences.items():
                    if not self._is_running:
                        break
                    
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
                    
        except Exception as e:
            self.debug_logger.log(f"Ошибка в оптимизированном поиске: {e}", "ERROR")
        
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
        """
        Улучшенный алгоритм для распознавания номеров кадров в сложных именах файлов,
        включая случаи с длинными номерами как в: 001_0030_SPB_L06_V01_asec2065_01405393.exr
        """
        name_without_ext = os.path.splitext(filename)[0]
        
        matches = []
        for match in re.finditer(r'\d+', name_without_ext):
            matches.append((match.start(), match.end(), match.group()))
            
        if not matches:
            return name_without_ext, None

        best_match = None
        best_score = -10000 

        for i, (start, end, num_str) in enumerate(matches):
            try:
                num_val = int(num_str)
            except ValueError:
                continue

            score = 0
            length = len(num_str)
            
            # --- 1. Анализ Префиксов (Контекст) ---
            prefix_bonus = 0
            
            if start > 0:
                prev_char = name_without_ext[start-1]
                
                # Проверяем контекст перед числом (3 символа)
                context_start = max(0, start - 3)
                context = name_without_ext[context_start:start].lower()
                
                # Сильные индикаторы номера кадра
                strong_frame_indicators = ['.', '_r', '_c', '_v', '_f', '.r', '.c', '.v', '.f', '_', '-']
                if any(indicator in context for indicator in strong_frame_indicators):
                    prefix_bonus += 40
                    
                    # Особый бонус для точки как разделителя кадров
                    if '.' in context:
                        prefix_bonus += 30
                
                # Если перед цифрой буква
                if prev_char.isalpha():
                    # Бонус для специфических префиксов кадров
                    if prev_char.lower() in ['r', 'c', 'v', 'f']:
                        prefix_bonus += 35
                    else:
                        # Другие буквы - умеренный штраф
                        score -= 15
                
                # Большой бонус за разделители
                elif prev_char in ['.', '_', '-']:
                    prefix_bonus += 25
                    if prev_char == '.': 
                        prefix_bonus += 20  # Особый бонус для точки
                    elif prev_char == '_': 
                        prefix_bonus += 10

            score += prefix_bonus

            # --- 2. Анализ Постфиксов (что после числа) ---
            suffix_bonus = 0
            if end < len(name_without_ext):
                next_char = name_without_ext[end]
                # Если после числа идет расширение или конец строки - бонус
                if next_char == '.' or end == len(name_without_ext) - 1:
                    suffix_bonus += 30  # Увеличили бонус
                elif next_char in ['_', '-']:
                    suffix_bonus += 15
            
            score += suffix_bonus

            # Если число стоит в самом начале имени - обычно не кадр
            if start == 0:
                score -= 10

            # --- 3. Оценка длины и значения ---
            
            # Длина 6-10 (идеальная для длинных номеров кадров)
            if 6 <= length <= 10:
                score += 60  # Очень большой бонус
                
                # Особый бонус для 8-значных чисел (типичные длинные номера кадров)
                if length == 8:
                    score += 20
                    
                # Очень большой бонус за ведущие нули в длинных числах
                if num_str.startswith('0') and length > 1:
                    score += 40
                    # Дополнительный бонус если много ведущих нулей
                    zero_count = len([c for c in num_str if c == '0'])
                    if zero_count >= 3:
                        score += 20
            
            # Длина 4-5 (хорошая)
            elif 4 <= length <= 5:
                score += 40
                
                # Бонус за ведущие нули
                if num_str.startswith('0') and length > 1:
                    score += 25
            
            # Короткие (1-3) - низкий приоритет
            elif length < 4:
                score -= 20
            
            # Длинные (>10) - возможны, но с меньшим приоритетом
            elif length > 10:
                score += 10

            # --- 4. Позиция в имени файла ---
            # Очень большой бонус последнему числу в имени
            if i == len(matches) - 1:
                score += 50  # Увеличили
            
            # Также бонус предпоследнему числу
            elif i == len(matches) - 2:
                score += 20

            # --- 5. Дополнительные эвристики для сложных имен ---
            
            # Бонус если число выглядит как типичный номер кадра
            if length >= 6:
                # Если все цифры одинаковые (0000, 1111) - вероятно не кадр
                if len(set(num_str)) == 1:
                    score -= 40
                # Если число последовательное (0001, 0002 и т.д.)
                elif num_str.startswith('0') and num_val < 1000000:
                    score += 30
                    
                    # Дополнительный бонус для последовательностей с небольшим шагом
                    if num_val % 10 == 0 or num_val % 100 == 0:
                        score += 15
            
            # Проверка на даты (штрафуем)
            if length == 8:
                # Проверяем, не является ли это датой (YYYYMMDD или YYMMDDHH)
                year_indicators = ['20', '19', '21', '22']
                if (num_str[:2] in year_indicators or 
                num_str[:4] in ['2023', '2024', '2025', '2026']):
                    # Дополнительная проверка: если контекст не указывает на кадр
                    if prefix_bonus < 30:  # Если нет сильного контекста кадра
                        score -= 50  # Штраф за возможную дату
        
            # --- 6. Анализ общего паттерна имени файла ---
            # Бонус если имя файла содержит типичные паттерны для кадров
            file_patterns = ['.r', '.c', '.v', '.f', '_r', '_c', '_v', '_f']  # Добавили подчеркивания
            if any(pattern in name_without_ext.lower() for pattern in file_patterns):
                # Особый бонус если наше число следует сразу после такого паттерна
                pattern_bonus = 0
                for pattern in file_patterns:
                    pattern_pos = name_without_ext.lower().find(pattern)
                    if pattern_pos != -1 and start == pattern_pos + len(pattern):
                        pattern_bonus += 70  # Очень большой бонус
                        break
                score += pattern_bonus
                
            # --- 7. Эвристика для длинных последовательных номеров ---
            # Если число длинное и увеличивается на 1 в последовательности файлов
            if length >= 6 and num_val > 100000:
                # Проверяем, не является ли это временной меткой или уникальным ID
                # Но даем небольшой бонус, так как это может быть длинная последовательность
                score += 15

            # --- 8. Анализ окружающего контекста для сложных имен ---
            # Для файлов типа 001_0030_SPB_L06_V01_asec2065_01405393.exr
            # Ищем паттерны с подчеркиваниями и длинными числами
            
            # Проверяем, есть ли перед числом паттерн с подчеркиванием и коротким числом
            if start >= 2:
                prev_chars = name_without_ext[start-2:start]
                if prev_chars in ['_r', '_c', '_v', '_f']:
                    score += 40
            
            # Проверяем, находится ли число в конце имени (перед расширением)
            if end == len(name_without_ext):
                score += 30  # Большой бонус для чисел в самом конце

            self.debug_logger.log(f"  Кандидат '{num_str}': len={length}, pos={i}, context='{name_without_ext[max(0,start-2):start]}...', score={score}")

            if score > best_score:
                best_score = score
                best_match = (start, end, num_str)

        # Проверка на валидность победителя - требуем хороший счет
        if best_match and best_score > 30:  # Немного повысили порог
            start, end, num_str = best_match
            try:
                frame_num = int(num_str)
                base_name_template = name_without_ext[:start] + "@@@" + name_without_ext[end:]
                
                self.debug_logger.log(f"  ВЫБРАНО: '{num_str}' как номер кадра, счет={best_score}")
                self.debug_logger.log(f"  Шаблон: '{base_name_template}'")
                
                return base_name_template, frame_num
            except ValueError:
                self.debug_logger.log(f"  Ошибка преобразования '{num_str}' в число")
                pass

        self.debug_logger.log(f"  НЕТ подходящего номера кадра, лучший счет={best_score}")
        return name_without_ext, None


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
        
        # Допускаем последовательности с постоянным шагом (1, 2, 10 и т.д.)
        # Для больших чисел допускаем больший разброс в разнице (например, 10000001-10000002 = 1)
        max_difference_variation = max(1, max(valid_frames) // 1000000)  # Автоматическая адаптация
        
        self.debug_logger.log(f"is_sequence: кадры {sorted_frames}, различия {differences}, уникальные различия {unique_differences}, max_variation={max_difference_variation}")
        
        # Если все различия одинаковые или отличаются не более чем на max_difference_variation
        if len(unique_differences) == 1:
            result = True
        else:
            min_diff = min(unique_differences)
            max_diff = max(unique_differences)
            result = (max_diff - min_diff) <= max_difference_variation
        
        self.debug_logger.log(f"is_sequence: результат {result}")
        return result

    def run(self):
        try:
        #    self.find_sequences_recursive(self.directory)
            self.find_sequences_optimized(self.directory)
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
        self.active_list.clear()
        for field_name in self.parent.settings_manager.ordered_metadata_fields:
            if field_name in self.parent.settings_manager.color_metadata:
                color_data = self.parent.settings_manager.color_metadata[field_name]
                if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                    if not color_data.get('removed', False):
                        color = QColor(color_data['r'], color_data['g'], color_data['b'])
                        item = QListWidgetItem(field_name)
                        item.setBackground(color)
                        self.active_list.addItem(item)
        
        self.trash_list.clear()
        for field_name, color_data in self.parent.settings_manager.removed_metadata.items():
            if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                color = QColor(color_data['r'], color_data['g'], color_data['b'])
                item = QListWidgetItem(field_name)
                item.setBackground(color)
                self.trash_list.addItem(item)
        
        self.sequences_list.clear()
        for seq_type, color_data in self.parent.settings_manager.sequence_colors.items():
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
        for i in range(self.active_list.count()):
            if self.active_list.item(i).text() == field_name:
                QMessageBox.warning(self, "Ошибка", "Это поле уже добавлено")
                return

        for i in range(self.trash_list.count()):
            if self.trash_list.item(i).text() == field_name:
                reply = QMessageBox.question(self, "Восстановить поле", 
                                        f"Поле '{field_name}' находится в корзине. Восстановить его?",
                                        QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.restore_field_from_trash(field_name)
                return
        
        color = QColorDialog.getColor(QColor(200, 200, 255), self, "Выберите цвет для поля")
        if color.isValid():
            self.parent.settings_manager.color_metadata[field_name] = {
                'r': color.red(),
                'g': color.green(), 
                'b': color.blue(),
                'removed': False
            }
            
            if field_name not in self.parent.settings_manager.ordered_metadata_fields:
                self.parent.settings_manager.ordered_metadata_fields.append(field_name)
            
            self.parent.settings_manager.save_settings()
            
            self.load_current_settings()
            
            if hasattr(self.parent, 'metadata_manager'):
                self.parent.metadata_manager.update_metadata_colors()
            
            self.field_input.clear()

    def add_sequence_type_with_color(self):
        seq_type = self.sequence_type_input.text().strip()
        if not seq_type:
            QMessageBox.warning(self, "Ошибка", "Введите тип последовательности")
            return
        
        for i in range(self.sequences_list.count()):
            if self.sequences_list.item(i).text() == seq_type:
                QMessageBox.warning(self, "Ошибка", "Этот тип уже добавлен")
                return

        color = QColorDialog.getColor(QColor(200, 200, 255), self, "Выберите цвет для типа последовательности")
        if color.isValid():
            self.parent.settings_manager.sequence_colors[seq_type] = {
                'r': color.red(),
                'g': color.green(), 
                'b': color.blue()
            }
            
            self.parent.settings_manager.save_settings()
            
            self.load_current_settings()
            
            if hasattr(self.parent, 'tree_manager'):
                self.parent.tree_manager.update_sequences_colors()
            
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
        if field_name in self.parent.settings_manager.color_metadata:
            
            color_data = self.parent.settings_manager.color_metadata[field_name]
            self.parent.settings_manager.removed_metadata[field_name] = color_data
            
            
            del self.parent.settings_manager.color_metadata[field_name]
            
            
            if field_name in self.parent.settings_manager.ordered_metadata_fields:
                self.parent.settings_manager.ordered_metadata_fields.remove(field_name)
            
            self.parent.settings_manager.save_settings()
            
            self.load_current_settings()
            
            if hasattr(self.parent, 'metadata_manager'):
                self.parent.metadata_manager.update_metadata_colors()

    def delete_sequence_type(self, seq_type):
        """Удаляет тип последовательности"""
        if seq_type in self.parent.settings_manager.sequence_colors:
            del self.parent.settings_manager.sequence_colors[seq_type]
            
            self.parent.settings_manager.save_settings()
            
            self.load_current_settings()
            
            if hasattr(self.parent, 'tree_manager'):
                self.parent.tree_manager.update_sequences_colors()

    def restore_selected(self):
        current_row = self.trash_list.currentRow()
        if current_row >= 0:
            field_name = self.trash_list.item(current_row).text()
            self.restore_field_from_trash(field_name)

    def restore_field_from_trash(self, field_name):
        """Восстанавливает поле из корзины"""
        if field_name in self.parent.settings_manager.removed_metadata:
            color_data = self.parent.settings_manager.removed_metadata[field_name]
            self.parent.settings_manager.color_metadata[field_name] = color_data
            
            if field_name not in self.parent.settings_manager.ordered_metadata_fields:
                self.parent.settings_manager.ordered_metadata_fields.append(field_name)
            
            del self.parent.settings_manager.removed_metadata[field_name]
            
            self.parent.settings_manager.save_settings()
            self.load_current_settings()

            if hasattr(self.parent, 'metadata_manager'):
                # ИСПОЛЬЗОВАТЬ update_metadata_colors вместо перечитывания
                self.parent.metadata_manager.update_metadata_colors()

    def delete_permanently_selected(self):
        current_row = self.trash_list.currentRow()
        if current_row >= 0:
            field_name = self.trash_list.item(current_row).text()
            self.delete_field_permanently(field_name)

    def delete_field_permanently(self, field_name):
        """Окончательно удаляет поле"""
        if field_name in self.parent.settings_manager.removed_metadata:
            del self.parent.settings_manager.removed_metadata[field_name]
            
            self.parent.settings_manager.save_settings()
            
            self.load_current_settings()

    def empty_trash(self):
        """Очищает корзину"""
        reply = QMessageBox.question(self, "Очистить корзину", 
                                "Вы уверены, что хотите окончательно удалить все поля из корзины?",
                                QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            # ИСПРАВЛЕНИЕ: Используем settings_manager
            self.parent.settings_manager.removed_metadata.clear()
            
            
            self.parent.settings_manager.save_settings()
            
            
            self.load_current_settings()

    def move_field_up(self):
        """Перемещает выбранное поле вверх в списке"""
        current_row = self.active_list.currentRow()
        if current_row > 0:
            field_name = self.active_list.item(current_row).text()
            
            # ИСПРАВЛЕНИЕ: Используем settings_manager
            index = self.parent.settings_manager.ordered_metadata_fields.index(field_name)
            if index > 0:
                self.parent.settings_manager.ordered_metadata_fields[index], self.parent.settings_manager.ordered_metadata_fields[index-1] = \
                    self.parent.settings_manager.ordered_metadata_fields[index-1], self.parent.settings_manager.ordered_metadata_fields[index]
                self.parent.settings_manager.save_settings()
                self.load_current_settings()
                self.active_list.setCurrentRow(current_row - 1)

    def move_field_down(self):
        """Перемещает выбранное поле вниз в списке"""
        current_row = self.active_list.currentRow()
        if current_row >= 0 and current_row < self.active_list.count() - 1:
            field_name = self.active_list.item(current_row).text()
            
            # ИСПРАВЛЕНИЕ: Используем settings_manager
            index = self.parent.settings_manager.ordered_metadata_fields.index(field_name)
            if index < len(self.parent.settings_manager.ordered_metadata_fields) - 1:
                self.parent.settings_manager.ordered_metadata_fields[index], self.parent.settings_manager.ordered_metadata_fields[index+1] = \
                    self.parent.settings_manager.ordered_metadata_fields[index+1], self.parent.settings_manager.ordered_metadata_fields[index]
                self.parent.settings_manager.save_settings()
                self.load_current_settings()
                self.active_list.setCurrentRow(current_row + 1)

    def move_field_top(self):
        """Перемещает выбранное поле в начало списка"""
        current_row = self.active_list.currentRow()
        if current_row > 0:
            field_name = self.active_list.item(current_row).text()
            
            # ИСПРАВЛЕНИЕ: Используем settings_manager
            if field_name in self.parent.settings_manager.ordered_metadata_fields:
                self.parent.settings_manager.ordered_metadata_fields.remove(field_name)
                self.parent.settings_manager.ordered_metadata_fields.insert(0, field_name)
                self.parent.settings_manager.save_settings()
                self.load_current_settings()
                self.active_list.setCurrentRow(0)

    def move_field_bottom(self):
        """Перемещает выбранное поле в конец списка"""
        current_row = self.active_list.currentRow()
        if current_row >= 0 and current_row < self.active_list.count() - 1:
            field_name = self.active_list.item(current_row).text()
            
            # ИСПРАВЛЕНИЕ: Используем settings_manager
            if field_name in self.parent.settings_manager.ordered_metadata_fields:
                self.parent.settings_manager.ordered_metadata_fields.remove(field_name)
                self.parent.settings_manager.ordered_metadata_fields.append(field_name)
                self.parent.settings_manager.save_settings()
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
        # УБРАТЬ вызов display_metadata и использовать только update_metadata_colors
        if field_name in self.parent.settings_manager.color_metadata:
            current_color_data = self.parent.settings_manager.color_metadata[field_name]
            current_color = QColor(current_color_data['r'], current_color_data['g'], current_color_data['b'])
            
            color = QColorDialog.getColor(current_color, self, f"Выберите цвет для поля '{field_name}'")
            if color.isValid():
                self.parent.settings_manager.color_metadata[field_name] = {
                    'r': color.red(),
                    'g': color.green(),
                    'b': color.blue(),
                    'removed': False
                }
                
                self.parent.settings_manager.save_settings()
                self.load_current_settings()
                
                if hasattr(self.parent, 'metadata_manager'):
                    # ИСПОЛЬЗОВАТЬ update_metadata_colors вместо перечитывания
                    self.parent.metadata_manager.update_metadata_colors()

    def change_sequence_color(self, seq_type):
        """Изменяет цвет типа последовательности"""
        # ИСПРАВЛЕНИЕ: Используем settings_manager
        if seq_type in self.parent.settings_manager.sequence_colors:
            current_color_data = self.parent.settings_manager.sequence_colors[seq_type]
            current_color = QColor(current_color_data['r'], current_color_data['g'], current_color_data['b'])
            
            color = QColorDialog.getColor(current_color, self, f"Выберите цвет для типа '{seq_type}'")
            if color.isValid():
                self.parent.settings_manager.sequence_colors[seq_type] = {
                    'r': color.red(),
                    'g': color.green(),
                    'b': color.blue()
                }
                
                
                self.parent.settings_manager.save_settings()
                
                
                self.load_current_settings()
                
                
                if hasattr(self.parent, 'tree_manager'):
                    self.parent.tree_manager.update_sequences_colors()






class CameraEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent  # Используем parent_window вместо parent
        self.camera_data = {}
        self.setup_ui()
        self.load_camera_data()
        self.update_cameras_list()  # ДОБАВИТЬ: обновляем список после загрузки данных
        
    def setup_ui(self):
        self.setWindowTitle("Редактор камер")
        self.setGeometry(200, 200, 1000, 700)
        
        layout = QVBoxLayout()
        
        # Вкладки
        self.tabs = QTabWidget()
        
        # Вкладка списка камер
        self.cameras_tab = QWidget()
        self.setup_cameras_tab()
        self.tabs.addTab(self.cameras_tab, "Камеры")
        
        # Вкладка правил сопоставления
        self.rules_tab = QWidget()
        self.setup_rules_tab()
        self.tabs.addTab(self.rules_tab, "Правила сопоставления")
        
        layout.addWidget(self.tabs)
        
        # Кнопки диалога
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout.addWidget(button_box)
        self.setLayout(layout)
    

    def save_current_camera(self):
        """Сохраняет данные текущей камеры"""
        current = self.cameras_list.currentItem()
        if current:
            camera_name = current.text()
            
            # Обновляем метаданные
            metadata_names = [name.strip() for name in self.metadata_names_input.text().split(",") if name.strip()]
            self.camera_data['cameras'][camera_name]['metadata_names'] = metadata_names
            
            # Обновляем разрешения из таблицы
            resolutions = {}
            for row in range(self.resolutions_table.rowCount()):
                resolution_item = self.resolutions_table.item(row, 0)
                sensor_item = self.resolutions_table.item(row, 1)
                if resolution_item and sensor_item:
                    resolutions[resolution_item.text()] = sensor_item.text()
            
            self.camera_data['cameras'][camera_name]['resolutions'] = resolutions
            
            # Сохраняем в файл
            self.save_camera_data()



    def bulk_import_cameras(self):
        """Массовый импорт камер и данных из текста"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Массовый импорт камер")
        dialog.setGeometry(300, 300, 700, 500)
        
        layout = QVBoxLayout()
        
        # Текстовое поле для ввода
        layout.addWidget(QLabel("Введите данные в формате:"))
        layout.addWidget(QLabel("camera model<tab>resolution w<tab>resolution h<tab>sensor"))
        layout.addWidget(QLabel("alexa lf<tab>8000<tab>4000<tab>20 x 10"))
        layout.addWidget(QLabel("Sony Venice 1<tab>3840<tab>2160<tab>22.8x12.8"))
        
        text_edit = QPlainTextEdit()
        text_edit.setPlaceholderText("Вставьте данные здесь...")
        
        # Устанавливаем моноширинный шрифт для лучшего отображения
        font = QFont("Courier", 9)
        text_edit.setFont(font)
        
        layout.addWidget(text_edit)
        
        # Кнопки
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        dialog.setLayout(layout)
        
        if dialog.exec_() == QDialog.Accepted:
            text = text_edit.toPlainText()
            self.process_bulk_import(text)

    def process_bulk_import(self, text):
        """Массовый импорт камер и данных из текста - для данных с табуляциями"""
        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
            self.parent_window.debug_logger.log(f"=== НАЧАЛО МАССОВОГО ИМПОРТА ===")
            self.parent_window.debug_logger.log(f"Исходный текст:\n{text}")
        
        lines = text.strip().split('\n')
        imported_count = 0
        
        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
            self.parent_window.debug_logger.log(f"Найдено строк: {len(lines)}")
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            
            # Проверяем, содержит ли строка табуляции
            if '\t' in line:
                parts = line.split('\t')
                if len(parts) >= 4:
                    camera_name = parts[0].strip()
                    resolution_w = parts[1].strip()
                    resolution_h = parts[2].strip()
                    sensor_size = ' '.join(parts[3:]).strip()
                    
                    if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                        self.parent_window.debug_logger.log(f"Строка {line_num} (табуляции): '{line}'")
                        self.parent_window.debug_logger.log(f"  Разобрано: camera='{camera_name}', w='{resolution_w}', h='{resolution_h}', sensor='{sensor_size}'")
                    
                    # Создаем камеру если не существует
                    if camera_name not in self.camera_data['cameras']:
                        self.camera_data['cameras'][camera_name] = {
                            "metadata_names": [camera_name],
                            "resolutions": {}
                        }
                        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                            self.parent_window.debug_logger.log(f"  Создана новая камера: '{camera_name}'")
                    
                    # Нормализуем и добавляем данные
                    resolution_str = f"{resolution_w}x{resolution_h}"
                    normalized_resolution = self.normalize_resolution(resolution_str)
                    normalized_sensor = self.normalize_sensor(sensor_size)
                    
                    if normalized_resolution and normalized_sensor:
                        self.camera_data['cameras'][camera_name]['resolutions'][normalized_resolution] = normalized_sensor
                        imported_count += 1
                        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                            self.parent_window.debug_logger.log(f"  Добавлено разрешение: {normalized_resolution} -> {normalized_sensor}")
                else:
                    if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                        self.parent_window.debug_logger.log(f"Строка {line_num}: недостаточно частей после разделения табуляциями: {len(parts)}")
            else:
                if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                    self.parent_window.debug_logger.log(f"Строка {line_num}: нет табуляций - пропускаем")
        
        # Сохраняем данные
        self.save_camera_data()
        self.update_cameras_list()
        
        # Перезагружаем детали если есть выбранная камера
        current_item = self.cameras_list.currentItem()
        if current_item:
            self.load_camera_details(current_item.text())
        
        QMessageBox.information(self, "Успех", f"Данные успешно импортированы. Добавлено {imported_count} разрешений")
        
        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
            self.parent_window.debug_logger.log(f"Импорт завершен. Добавлено {imported_count} разрешений")
            self.parent_window.debug_logger.log("=== ЗАВЕРШЕНИЕ МАССОВОГО ИМПОРТА ===")


    def add_camera_resolution(self, camera_name, resolution_w, resolution_h, sensor_size):
        """Добавляет разрешение к камере"""
        # Создаем камеру если не существует
        if camera_name not in self.camera_data['cameras']:
            self.camera_data['cameras'][camera_name] = {
                "metadata_names": [camera_name],
                "resolutions": {}
            }
            if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                self.parent_window.debug_logger.log(f"Создана новая камера: '{camera_name}'")
        
        # Добавляем разрешение
        resolution_str = f"{resolution_w}x{resolution_h}"
        normalized_resolution = self.normalize_resolution(resolution_str)
        normalized_sensor = self.normalize_sensor(sensor_size)
        
        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
            self.parent_window.debug_logger.log(f"Разрешение: '{resolution_str}' -> '{normalized_resolution}'")
            self.parent_window.debug_logger.log(f"Сенсор: '{sensor_size}' -> '{normalized_sensor}'")
        
        if normalized_resolution:
            self.camera_data['cameras'][camera_name]['resolutions'][normalized_resolution] = normalized_sensor
            if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                self.parent_window.debug_logger.log(f"Добавлено разрешение: {normalized_resolution} -> {normalized_sensor}")
            return True
        
        return False


    def setup_cameras_tab(self):
        layout = QVBoxLayout()
        
        # Панель управления камерами
        camera_control_layout = QHBoxLayout()

        self.add_camera_btn = QPushButton("Добавить камеру")
        self.edit_camera_btn = QPushButton("Редактировать камеру") 
        self.delete_camera_btn = QPushButton("Удалить камеру")
        self.bulk_import_btn = QPushButton("Массовое добавление камер и данных")  # Новая кнопка

        self.add_camera_btn.clicked.connect(self.add_camera)
        self.edit_camera_btn.clicked.connect(self.edit_camera)
        self.delete_camera_btn.clicked.connect(self.delete_camera)
        self.bulk_import_btn.clicked.connect(self.bulk_import_cameras)  # Подключаем метод

        camera_control_layout.addWidget(self.add_camera_btn)
        camera_control_layout.addWidget(self.edit_camera_btn)
        camera_control_layout.addWidget(self.delete_camera_btn)
        camera_control_layout.addWidget(self.bulk_import_btn)  # Добавляем в layout
        camera_control_layout.addStretch()
        
        # Список камер
        self.cameras_list = QListWidget()
        self.cameras_list.currentItemChanged.connect(self.on_camera_selected)
        
        # Детали камеры
        self.camera_details_widget = QWidget()
        self.setup_camera_details()
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.cameras_list)
        splitter.addWidget(self.camera_details_widget)
        splitter.setSizes([300, 600])
        
        layout.addLayout(camera_control_layout)
        layout.addWidget(splitter)
        
        self.cameras_tab.setLayout(layout)
    
    def setup_camera_details(self):
        layout = QVBoxLayout()
        
        form_layout = QFormLayout()
        
        self.camera_name_input = QLineEdit()
        self.metadata_names_input = QLineEdit()
        self.metadata_names_input.setPlaceholderText("Через запятую: ARRI ALEXA Mini LF, ALEXA Mini LF")
        
        form_layout.addRow("Название камеры:", self.camera_name_input)
        form_layout.addRow("Имена в метаданных:", self.metadata_names_input)
        
        # Таблица разрешений
        layout.addWidget(QLabel("Разрешения и размеры сенсоров:"))
        
        self.resolutions_table = QTableWidget()
        self.resolutions_table.setColumnCount(2)
        self.resolutions_table.setHorizontalHeaderLabels(["Разрешение", "Размер сенсора"])
        
        # Настраиваем заголовок для ручного изменения ширины столбцов
        header = self.resolutions_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)  # Разрешаем пользователю менять ширину
        header.setStretchLastSection(True)  # Растягиваем последний столбец на оставшееся пространство
        
        # Устанавливаем начальную равную ширину
        table_width = self.resolutions_table.width()
        column_width = table_width // self.resolutions_table.columnCount()
        for i in range(self.resolutions_table.columnCount()):
            self.resolutions_table.setColumnWidth(i, column_width)

        # Разрешаем редактирование ячеек и подключаем сигнал изменения
        self.resolutions_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        self.resolutions_table.cellChanged.connect(self.on_cell_changed)
        
        resolutions_control_layout = QHBoxLayout()
        self.add_resolution_btn = QPushButton("Добавить разрешение")
        self.edit_resolution_btn = QPushButton("Нормализовать выбранное")
        self.delete_resolution_btn = QPushButton("Удалить разрешение")
        
        self.add_resolution_btn.clicked.connect(self.add_resolution)
        self.edit_resolution_btn.clicked.connect(self.normalize_selected_resolution)
        self.delete_resolution_btn.clicked.connect(self.delete_resolution)
        
        resolutions_control_layout.addWidget(self.add_resolution_btn)
        resolutions_control_layout.addWidget(self.edit_resolution_btn)
        resolutions_control_layout.addWidget(self.delete_resolution_btn)
        resolutions_control_layout.addStretch()
        
        layout.addLayout(form_layout)
        layout.addLayout(resolutions_control_layout)
        layout.addWidget(self.resolutions_table)
        
        self.camera_details_widget.setLayout(layout)
        self.camera_details_widget.setEnabled(False)


    def save_camera_data_delayed(self):
        """Сохраняет данные камер с задержкой чтобы избежать частых записей"""
        if not hasattr(self, '_save_timer'):
            self._save_timer = QTimer()
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self.save_camera_data)
        
        # Останавливаем предыдущий таймер и запускаем новый
        self._save_timer.stop()
        self._save_timer.start(2000)  # Сохраняем через 2 секунды после последнего изменения


    def on_cell_changed(self, row, column):
        """Автоматически нормализует значения при ручном редактировании"""
        # Временно отключаем сигнал чтобы избежать рекурсии
        self.resolutions_table.cellChanged.disconnect(self.on_cell_changed)
        
        item = self.resolutions_table.item(row, column)
        if item:
            current_value = item.text()
            normalized_value = current_value
            
            if column == 0:  # Столбец разрешения
                normalized_value = self.normalize_resolution(current_value)
            elif column == 1:  # Столбец сенсора
                normalized_value = self.normalize_sensor(current_value)
            
            # Если значение изменилось после нормализации, обновляем ячейку
            if normalized_value != current_value:
                item.setText(normalized_value)
        
        # Включаем сигнал обратно
        self.resolutions_table.cellChanged.connect(self.on_cell_changed)
        
        # Используем отложенное сохранение вместо немедленного
        self.save_camera_data_delayed()
        


    def normalize_selected_resolution(self):
        """Нормализует выбранное разрешение и размер сенсора"""
        current_row = self.resolutions_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите разрешение для нормализации")
            return
        
        # Получаем текущие значения
        resolution_item = self.resolutions_table.item(current_row, 0)
        sensor_item = self.resolutions_table.item(current_row, 1)
        
        if not resolution_item or not sensor_item:
            QMessageBox.warning(self, "Ошибка", "Неверные данные в выбранной строке")
            return
        
        current_resolution = resolution_item.text()
        current_sensor = sensor_item.text()
        
        # Нормализуем значения
        normalized_resolution = self.normalize_resolution(current_resolution)
        normalized_sensor = self.normalize_sensor(current_sensor)
        
        # Обновляем таблицу
        resolution_item.setText(normalized_resolution)
        sensor_item.setText(normalized_sensor)
        
        # Сохраняем изменения
        self.save_camera_data_delayed()
        
        QMessageBox.information(self, "Успех", "Разрешение и размер сенсора нормализованы")


    def on_camera_data_changed(self):
        """Вызывается при изменении данных камеры"""
        # Используем таймер для отложенного сохранения, чтобы избежать частых записей
        if hasattr(self, '_save_timer'):
            self._save_timer.stop()
        
        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_current_camera)
        self._save_timer.start(1000)  # Сохраняем через 1 секунду после последнего изменения


    def delete_resolution(self):
        """Удаляет выбранное разрешение из таблицы"""
        current_row = self.resolutions_table.currentRow()
        if current_row >= 0:
            self.resolutions_table.removeRow(current_row)
            # СОХРАНЯЕМ ИЗМЕНЕНИЯ
            self.save_current_camera()

    def normalize_resolution(self, resolution_str):
        """Нормализует строку разрешения в формат WxH с поддержкой запятых"""
        if not resolution_str or not resolution_str.strip():
            return None
        
        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
            self.parent_window.debug_logger.log(f"Нормализация разрешения: '{resolution_str}'")
        
        # ПРОВЕРКА: если строка уже в нормализованном формате WxH, возвращаем как есть
        if re.match(r'^\d+x\d+$', resolution_str):
            if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                self.parent_window.debug_logger.log(f"Разрешение уже нормализовано: '{resolution_str}'")
            return resolution_str
        
        # Заменяем запятые на точки для десятичных чисел
        clean_str = resolution_str.replace(',', '.')
        
        # Удаляем все пробелы и приводим к нижнему регистру
        clean_str = re.sub(r'\s+', '', clean_str.lower())
        
        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
            self.parent_window.debug_logger.log(f"Очищенная строка: '{clean_str}'")
        
        # Пробуем разные разделители
        separators = ['x', 'х', '*', '×']  # английский x, русский х, *, символ умножения
        
        for sep in separators:
            if sep in clean_str:
                parts = clean_str.split(sep)
                if len(parts) == 2:
                    try:
                        w = float(parts[0])
                        h = float(parts[1])
                        # Если числа целые, форматируем как целые, иначе оставляем как есть
                        if w.is_integer() and h.is_integer():
                            result = f"{int(w)}x{int(h)}"
                        else:
                            result = f"{w}x{h}"
                        
                        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                            self.parent_window.debug_logger.log(f"Найден разделитель '{sep}': {parts} -> {result}")
                        return result
                    except ValueError as e:
                        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                            self.parent_window.debug_logger.log(f"Ошибка преобразования чисел для разделителя '{sep}': {e}")
                        continue
        
        # Если не нашли разделитель, пробуем извлечь числа
        numbers = re.findall(r'\d+\.?\d*', resolution_str)
        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
            self.parent_window.debug_logger.log(f"Извлеченные числа: {numbers}")
        
        if len(numbers) >= 2:
            try:
                w = float(numbers[0])
                h = float(numbers[1])
                if w.is_integer() and h.is_integer():
                    result = f"{int(w)}x{int(h)}"
                else:
                    result = f"{w}x{h}"
                
                if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                    self.parent_window.debug_logger.log(f"Используем первые два числа: {result}")
                return result
            except ValueError as e:
                if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                    self.parent_window.debug_logger.log(f"Ошибка преобразования извлеченных чисел: {e}")
        
        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
            self.parent_window.debug_logger.log(f"Не удалось нормализовать разрешение: '{resolution_str}'")
        return None

    def normalize_sensor(self, sensor_str):
        """Унифицированная нормализация строки размера сенсора к формату '20.00mm x 10.00mm'"""
        if not sensor_str or not sensor_str.strip():
            return sensor_str
        
        original_str = sensor_str
        sensor_str = sensor_str.strip()
        
        # ПРОВЕРКА: если строка уже в нормализованном формате, возвращаем как есть
        if re.match(r'^\d+\.?\d*mm x \d+\.?\d*mm$', sensor_str):
            if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                self.parent_window.debug_logger.log(f"Сенсор уже нормализован: '{sensor_str}'")
            return sensor_str
        
        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
            self.parent_window.debug_logger.log(f"Универсальная нормализация сенсора: '{original_str}'")
        
        # Шаг 1: Подготовка строки
        # Приводим к нижнему регистру
        clean_str = sensor_str.lower()
        
        # Заменяем различные варианты разделителей на стандартный [SEP]
        separators = [' на ', ' x ', 'х', '*', '×', '\\', '/', '|', ';', ',']
        for sep in separators:
            clean_str = clean_str.replace(sep, '[SEP]')
        
        # Заменяем множественные пробелы на один пробел
        clean_str = re.sub(r'\s+', ' ', clean_str)
        
        # Теперь заменяем одиночные пробелы на [SEP] только если они разделяют числа
        # Но сначала сохраним текущее состояние
        temp_str = clean_str
        
        # Попробуем разбить по [SEP]
        if '[SEP]' in clean_str:
            parts = clean_str.split('[SEP]')
            if len(parts) >= 2:
                # Обрабатываем каждую часть отдельно
                numbers = []
                for part in parts:
                    part = part.strip()
                    # Извлекаем числа из каждой части
                    part_numbers = re.findall(r'[\d]+[.,]?[\d]*', part)
                    numbers.extend(part_numbers)
                
                if len(numbers) >= 2:
                    # У нас есть как минимум два числа
                    try:
                        width = float(numbers[0].replace(',', '.'))
                        height = float(numbers[1].replace(',', '.'))
                        
                        # Форматируем результат
                        width_str = f"{width:.2f}".rstrip('0').rstrip('.') if '.' in f"{width:.2f}" else f"{width:.0f}"
                        height_str = f"{height:.2f}".rstrip('0').rstrip('.') if '.' in f"{height:.2f}" else f"{height:.0f}"
                        
                        result = f"{width_str}mm x {height_str}mm"
                        
                        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                            self.parent_window.debug_logger.log(f"Универсальная нормализация (разделитель [SEP]): '{original_str}' -> '{result}'")
                        
                        return result
                    except ValueError as e:
                        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                            self.parent_window.debug_logger.log(f"Ошибка преобразования чисел: {e}")
        
        # Шаг 2: Если не сработало, ищем два числа в строке любым способом
        # Извлекаем все числа (с запятыми и точками как десятичными разделителями)
        numbers = re.findall(r'[\d]+[.,]?[\d]*', clean_str)
        
        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
            self.parent_window.debug_logger.log(f"Извлеченные числа: {numbers}")
        
        if len(numbers) >= 2:
            # Берем первые два числа
            try:
                width = float(numbers[0].replace(',', '.'))
                height = float(numbers[1].replace(',', '.'))
                
                # Форматируем с двумя знаками после запятой, но убираем лишние нули
                width_str = f"{width:.2f}".rstrip('0').rstrip('.') if '.' in f"{width:.2f}" else f"{width:.0f}"
                height_str = f"{height:.2f}".rstrip('0').rstrip('.') if '.' in f"{height:.2f}" else f"{height:.0f}"
                
                result = f"{width_str}mm x {height_str}mm"
                
                if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                    self.parent_window.debug_logger.log(f"Универсальная нормализация (два числа): '{original_str}' -> '{result}'")
                
                return result
                
            except ValueError as e:
                if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                    self.parent_window.debug_logger.log(f"Ошибка преобразования чисел: {e}")
        
        elif len(numbers) == 1:
            # Если только одно число, предполагаем квадратный сенсор
            try:
                size = float(numbers[0].replace(',', '.'))
                size_str = f"{size:.2f}".rstrip('0').rstrip('.') if '.' in f"{size:.2f}" else f"{size:.0f}"
                result = f"{size_str}mm x {size_str}mm"
                
                if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                    self.parent_window.debug_logger.log(f"Квадратный сенсор: '{original_str}' -> '{result}'")
                
                return result
            except ValueError as e:
                if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                    self.parent_window.debug_logger.log(f"Ошибка преобразования квадратного сенсора: {e}")
        
        # Если ничего не помогло, возвращаем исходную строку
        if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
            self.parent_window.debug_logger.log(f"Не удалось нормализовать, возвращаем исходную строку: '{original_str}'")
        return original_str



    
    def setup_rules_tab(self):
        layout = QVBoxLayout()
        
        # Правила для камер
        layout.addWidget(QLabel("Правила определения камеры:"))
        self.camera_rules_table = QTableWidget()
        self.camera_rules_table.setColumnCount(3)
        self.camera_rules_table.setHorizontalHeaderLabels(["Поле", "Значение", "Камера"])
        
        # Настраиваем заголовок для ручного изменения ширины столбцов
        camera_header = self.camera_rules_table.horizontalHeader()
        camera_header.setSectionResizeMode(QHeaderView.Interactive)  # Разрешаем пользователю менять ширину
        camera_header.setStretchLastSection(True)  # Растягиваем последний столбец на оставшееся пространство

        # Устанавливаем начальную равную ширину
        table_width = self.camera_rules_table.width()
        column_width = table_width // self.camera_rules_table.columnCount()
        for i in range(self.camera_rules_table.columnCount()):
            self.camera_rules_table.setColumnWidth(i, column_width)
        
        camera_rules_control = QHBoxLayout()
        self.add_camera_rule_btn = QPushButton("Добавить правило")
        self.delete_camera_rule_btn = QPushButton("Удалить правило")
        
        self.add_camera_rule_btn.clicked.connect(self.add_camera_rule)
        self.delete_camera_rule_btn.clicked.connect(self.delete_camera_rule)
        
        camera_rules_control.addWidget(self.add_camera_rule_btn)
        camera_rules_control.addWidget(self.delete_camera_rule_btn)
        camera_rules_control.addStretch()
        
        # Правила для разрешений
        layout.addWidget(QLabel("Правила определения разрешения:"))
        self.resolution_rules_table = QTableWidget()
        self.resolution_rules_table.setColumnCount(3)
        self.resolution_rules_table.setHorizontalHeaderLabels(["Поле", "Тип", "Описание"])
        
        # Настраиваем заголовок для ручного изменения ширины столбцов
        resolution_header = self.resolution_rules_table.horizontalHeader()
        resolution_header.setSectionResizeMode(QHeaderView.Interactive)  # Разрешаем пользователю менять ширину
        resolution_header.setStretchLastSection(True)  # Растягиваем последний столбец на оставшееся пространство

        # Устанавливаем начальную равную ширину
        table_width = self.resolution_rules_table.width()
        column_width = table_width // self.resolution_rules_table.columnCount()
        for i in range(self.resolution_rules_table.columnCount()):
            self.resolution_rules_table.setColumnWidth(i, column_width)
        


        resolution_rules_control = QHBoxLayout()
        self.add_resolution_rule_btn = QPushButton("Добавить правило")
        self.delete_resolution_rule_btn = QPushButton("Удалить правило")
        
        self.add_resolution_rule_btn.clicked.connect(self.add_resolution_rule)
        self.delete_resolution_rule_btn.clicked.connect(self.delete_resolution_rule)
        
        resolution_rules_control.addWidget(self.add_resolution_rule_btn)
        resolution_rules_control.addWidget(self.delete_resolution_rule_btn)
        resolution_rules_control.addStretch()
        
        # Описание типов правил
        rules_info = QLabel(
            "Типы правил разрешения:\n"
            "- range: (min_x, min_y) - (max_x, max_y) → width = max_x+1, height = max_y+1\n"
            "- single_w: только ширина\n" 
            "- single_h: только высота\n"
            "- combined: WxH или W x H"
        )
        rules_info.setWordWrap(True)
        
        layout.addLayout(camera_rules_control)
        layout.addWidget(self.camera_rules_table)
        layout.addLayout(resolution_rules_control)
        layout.addWidget(self.resolution_rules_table)
        layout.addWidget(rules_info)
        
        self.rules_tab.setLayout(layout)
    

    def load_camera_data(self):
        """Загружает данные камер из JSON файла"""
        try:
            if os.path.exists(CAMERA_SENSOR_DATA_FILE):
                with open(CAMERA_SENSOR_DATA_FILE, 'r', encoding='utf-8') as f:
                    self.camera_data = json.load(f)
                if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                    self.parent_window.debug_logger.log(f"Данные камер загружены из {CAMERA_SENSOR_DATA_FILE}")
            else:
                # Если файла нет, создаем пустую структуру
                self.camera_data = {"cameras": {}}
                self.save_camera_data()
                if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                    self.parent_window.debug_logger.log(f"Создан пустой файл данных камер: {CAMERA_SENSOR_DATA_FILE}")
            
            # ДОБАВИТЬ: загружаем правила из настроек
            self.load_rules_from_settings()
            
        except Exception as e:
            if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                self.parent_window.debug_logger.log(f"Ошибка загрузки данных камер: {e}", "ERROR")
            self.camera_data = {"cameras": {}}



    

    def save_camera_data(self):
        """Сохраняет данные камер в JSON файл"""
        try:
            with open(CAMERA_SENSOR_DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.camera_data, f, ensure_ascii=False, indent=2)
            if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                self.parent_window.debug_logger.log(f"Данные камер сохранены в {CAMERA_SENSOR_DATA_FILE}")
        except Exception as e:
            if self.parent_window and hasattr(self.parent_window, 'debug_logger'):
                self.parent_window.debug_logger.log(f"Ошибка сохранения данных камер: {e}", "ERROR")



    
    def update_cameras_list(self):
        """Обновляет список камер"""
        self.cameras_list.clear()
        if 'cameras' in self.camera_data:
            for camera_name in sorted(self.camera_data['cameras'].keys()):
                self.cameras_list.addItem(camera_name)
        
        # ДОБАВИТЬ: если есть камеры, выбираем первую
        if self.cameras_list.count() > 0:
            self.cameras_list.setCurrentRow(0)
            self.load_camera_details(self.cameras_list.item(0).text())
        else:
            self.camera_details_widget.setEnabled(False)



    
    def load_rules_from_settings(self):
        """Загружает правила из настроек приложения"""
        # Загружаем правила для камер
        camera_rules = self.parent_window.settings_manager.camera_detection_settings.get('camera_rules', [])
        self.camera_rules_table.setRowCount(len(camera_rules))
        for row, rule in enumerate(camera_rules):
            self.camera_rules_table.setItem(row, 0, QTableWidgetItem(rule.get('field', '')))
            self.camera_rules_table.setItem(row, 1, QTableWidgetItem(rule.get('value', '')))
            self.camera_rules_table.setItem(row, 2, QTableWidgetItem(rule.get('camera', '')))
        
        # Загружаем правила для разрешений
        resolution_rules = self.parent_window.settings_manager.camera_detection_settings.get('resolution_rules', [])
        self.resolution_rules_table.setRowCount(len(resolution_rules))
        for row, rule in enumerate(resolution_rules):
            self.resolution_rules_table.setItem(row, 0, QTableWidgetItem(rule.get('field', '')))
            self.resolution_rules_table.setItem(row, 1, QTableWidgetItem(rule.get('type', '')))



    def save_rules_to_settings(self):
        """Сохраняет правила в настройки приложения и СРАЗУ сохраняет настройки"""
        # Сохраняем правила для камер
        camera_rules = []
        for row in range(self.camera_rules_table.rowCount()):
            field_item = self.camera_rules_table.item(row, 0)
            value_item = self.camera_rules_table.item(row, 1)
            camera_item = self.camera_rules_table.item(row, 2)
            if field_item and value_item and camera_item:
                camera_rules.append({
                    'field': field_item.text(),
                    'value': value_item.text(),
                    'camera': camera_item.text()
                })
        
        # Сохраняем правила для разрешений
        resolution_rules = []
        for row in range(self.resolution_rules_table.rowCount()):
            field_item = self.resolution_rules_table.item(row, 0)
            type_item = self.resolution_rules_table.item(row, 1)
            if field_item and type_item:
                resolution_rules.append({
                    'field': field_item.text(),
                    'type': type_item.text()
                })
        
        # Обновляем настройки родительского окна
        if self.parent_window:
            self.parent_window.settings_manager.camera_detection_settings = {
                'camera_rules': camera_rules,
                'resolution_rules': resolution_rules
            }
            # ДОБАВИТЬ: сразу сохраняем настройки
            self.parent_window.settings_manager.save_settings()


    def load_rules_from_settings(self):
        """Загружает правила из настроек приложения"""
        if not self.parent_window:
            return
            
        # Загружаем правила для камер
        camera_rules = self.parent_window.settings_manager.camera_detection_settings.get('camera_rules', [])
        self.camera_rules_table.setRowCount(len(camera_rules))
        for row, rule in enumerate(camera_rules):
            self.camera_rules_table.setItem(row, 0, QTableWidgetItem(rule.get('field', '')))
            self.camera_rules_table.setItem(row, 1, QTableWidgetItem(rule.get('value', '')))
            self.camera_rules_table.setItem(row, 2, QTableWidgetItem(rule.get('camera', '')))
        
        # Загружаем правила для разрешений
        resolution_rules = self.parent_window.settings_manager.camera_detection_settings.get('resolution_rules', [])
        self.resolution_rules_table.setRowCount(len(resolution_rules))
        for row, rule in enumerate(resolution_rules):
            self.resolution_rules_table.setItem(row, 0, QTableWidgetItem(rule.get('field', '')))
            self.resolution_rules_table.setItem(row, 1, QTableWidgetItem(rule.get('type', '')))




    def add_camera_rule(self):
        """Добавляет новое правило для камеры"""
        # Диалог для ввода данных правила
        dialog = QDialog(self)
        dialog.setWindowTitle("Новое правило для камеры")
        layout = QFormLayout(dialog)
        
        field_input = QLineEdit()
        value_input = QLineEdit()
        camera_combo = QComboBox()
        
        # Заполняем комбобокс камерами
        cameras = list(self.camera_data['cameras'].keys())
        camera_combo.addItems(cameras)
        
        layout.addRow("Поле метаданных:", field_input)
        layout.addRow("Значение:", value_input)
        layout.addRow("Камера:", camera_combo)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addRow(button_box)
        
        if dialog.exec_() == QDialog.Accepted:
            field = field_input.text().strip()
            value = value_input.text().strip()
            camera = camera_combo.currentText()
            
            if field and value and camera:
                row = self.camera_rules_table.rowCount()
                self.camera_rules_table.insertRow(row)
                self.camera_rules_table.setItem(row, 0, QTableWidgetItem(field))
                self.camera_rules_table.setItem(row, 1, QTableWidgetItem(value))
                self.camera_rules_table.setItem(row, 2, QTableWidgetItem(camera))
                
                # ДОБАВИТЬ: сразу сохраняем настройки
                self.save_rules_to_settings()
        
    def delete_camera_rule(self):
        """Удаляет выбранное правило для камеры"""
        current_row = self.camera_rules_table.currentRow()
        if current_row >= 0:
            self.camera_rules_table.removeRow(current_row)
            # ДОБАВИТЬ: сразу сохраняем настройки
            self.save_rules_to_settings()
    

    def add_resolution_rule(self):
        """Добавляет новое правило для разрешения"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Новое правило для разрешения")
        layout = QFormLayout(dialog)
        
        field_input = QLineEdit()
        type_combo = QComboBox()
        type_combo.addItems(["range", "single_w", "single_h", "combined"])
        
        layout.addRow("Поле метаданных:", field_input)
        layout.addRow("Тип правила:", type_combo)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addRow(button_box)
        
        if dialog.exec_() == QDialog.Accepted:
            field = field_input.text().strip()
            rule_type = type_combo.currentText()
            
            if field and rule_type:
                row = self.resolution_rules_table.rowCount()
                self.resolution_rules_table.insertRow(row)
                self.resolution_rules_table.setItem(row, 0, QTableWidgetItem(field))
                self.resolution_rules_table.setItem(row, 1, QTableWidgetItem(rule_type))
                
                # Добавляем описание
                descriptions = {
                    "range": "(min_x,min_y)-(max_x,max_y) → W=min_x+1, H=min_y+1",
                    "single_w": "только ширина", 
                    "single_h": "только высота",
                    "combined": "WxH или W x H"
                }
                self.resolution_rules_table.setItem(row, 2, QTableWidgetItem(descriptions.get(rule_type, "")))
                
                # ДОБАВИТЬ: сразу сохраняем настройки
                self.save_rules_to_settings()



    
    def delete_resolution_rule(self):
        """Удаляет выбранное правило для разрешения"""
        current_row = self.resolution_rules_table.currentRow()
        if current_row >= 0:
            self.resolution_rules_table.removeRow(current_row)
            # ДОБАВИТЬ: сразу сохраняем настройки
            self.save_rules_to_settings()


    
    def accept(self):
        """Сохраняет настройки при закрытии диалога через OK"""
        # Останавливаем таймер отложенного сохранения
        if hasattr(self, '_save_timer') and self._save_timer.isActive():
            self._save_timer.stop()
        
        # Сохраняем изменения текущей камеры
        current_item = self.cameras_list.currentItem()
        if current_item:
            self.save_current_camera()
        
        # Сохраняем правила в настройки
        self.save_rules_to_settings()
        
        # Уведомляем родительское окно об изменениях
        if self.parent_window:
            self.parent_window.camera_manager.load_camera_data()
            self.parent_window.settings_manager.save_settings()
        
        super().accept()


    def reject(self):
        """Останавливаем таймер при отмене"""
        if hasattr(self, '_save_timer') and self._save_timer.isActive():
            self._save_timer.stop()
        super().reject()

    
    def on_camera_selected(self, current, previous):
        """Обрабатывает выбор камеры в списке"""
        if current:
            camera_name = current.text()
            self.load_camera_details(camera_name)
    
    def load_camera_details(self, camera_name):
        """Загружает детали выбранной камеры БЕЗ нормализации"""
        camera_info = self.camera_data['cameras'][camera_name]
        
        self.camera_name_input.setText(camera_name)
        
        # Загружаем metadata_names
        metadata_names = camera_info.get('metadata_names', [])
        self.metadata_names_input.setText(", ".join(metadata_names))
        
        # Заполняем таблицу разрешений БЕЗ нормализации
        self.resolutions_table.setRowCount(0)
        resolutions = camera_info.get('resolutions', {})
        for resolution, sensor_size in resolutions.items():
            row = self.resolutions_table.rowCount()
            self.resolutions_table.insertRow(row)
            self.resolutions_table.setItem(row, 0, QTableWidgetItem(resolution))
            self.resolutions_table.setItem(row, 1, QTableWidgetItem(sensor_size))
        
        self.camera_details_widget.setEnabled(True)
        
    def add_camera(self):
        """Добавляет новую камеру"""
        name, ok = QInputDialog.getText(self, "Новая камера", "Введите название камеры:")
        if ok and name:
            if name not in self.camera_data['cameras']:
                self.camera_data['cameras'][name] = {
                    "metadata_names": [],
                    "resolutions": {}
                }
                self.save_camera_data()
                self.update_cameras_list()
    
    def edit_camera(self):
        """Редактирует выбранную камеру"""
        current = self.cameras_list.currentItem()
        if current:
            # Сохраняем изменения текущей камеры
            camera_name = current.text()
            new_name = self.camera_name_input.text()
            
            if new_name != camera_name and new_name:
                # Переименовываем камеру
                self.camera_data['cameras'][new_name] = self.camera_data['cameras'].pop(camera_name)
                camera_name = new_name
            
            # Обновляем метаданные
            metadata_names = [name.strip() for name in self.metadata_names_input.text().split(",") if name.strip()]
            self.camera_data['cameras'][camera_name]['metadata_names'] = metadata_names
            
            # Разрешения теперь сохраняются автоматически при добавлении/удалении
            
            self.save_camera_data()
            self.update_cameras_list()
            
            # Выбираем обновленную камеру
            items = self.cameras_list.findItems(camera_name, Qt.MatchExactly)
            if items:
                self.cameras_list.setCurrentItem(items[0])
    
    def delete_camera(self):
        """Удаляет выбранную камеру"""
        current = self.cameras_list.currentItem()
        if current:
            camera_name = current.text()
            reply = QMessageBox.question(self, "Удаление камеры", 
                                       f"Удалить камеру '{camera_name}'?",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                del self.camera_data['cameras'][camera_name]
                self.save_camera_data()
                self.update_cameras_list()
                self.camera_details_widget.setEnabled(False)
    
    # def add_resolution(self):
    #     """Добавляет новое разрешение с поддержкой разных форматов ввода"""
    #     resolution, ok1 = QInputDialog.getText(self, "Новое разрешение", 
    #                                         "Введите разрешение (WxH, W x H, W H):")
    #     if not ok1 or not resolution:
    #         return
            
    #     # Нормализуем ввод разрешения
    #     normalized_resolution = self.normalize_resolution(resolution)
    #     if not normalized_resolution:
    #         QMessageBox.warning(self, "Ошибка", "Неверный формат разрешения")
    #         return


    def add_resolution(self):
        """Добавляет новое разрешение с поддержкой разных форматов ввода"""
        # Запрос разрешения
        resolution, ok1 = QInputDialog.getText(self, "Новое разрешение", 
                                            "Введите разрешение (WxH, W x H, W H):")
        if not ok1 or not resolution:
            return
            
        # Нормализуем ввод разрешения
        normalized_resolution = self.normalize_resolution(resolution)
        if not normalized_resolution:
            QMessageBox.warning(self, "Ошибка", "Неверный формат разрешения")
            return
            
        # Запрос размера сенсора  
        sensor_size, ok2 = QInputDialog.getText(self, "Размер сенсора", 
                                            "Введите размер сенсора (например: 20 10, 20x10, 20mm x 10mm):")
        if not ok2:
            return
            
        # Нормализуем ввод сенсора
        original_sensor = sensor_size
        normalized_sensor = self.normalize_sensor(sensor_size)
        
        # Показываем пользователю, как был нормализован ввод
        if original_sensor != normalized_sensor:
            QMessageBox.information(self, "Нормализация", 
                                f"Размер сенсора был нормализован:\n{original_sensor} → {normalized_sensor}")
        
        # Получаем текущую выбранную камеру
        current_item = self.cameras_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Ошибка", "Сначала выберите камеру из списка")
            return
            
        camera_name = current_item.text()
        
        # Проверяем, нет ли уже такого разрешения для этой камеры
        if normalized_resolution in self.camera_data['cameras'][camera_name]['resolutions']:
            reply = QMessageBox.question(self, "Разрешение уже существует", 
                                    f"Разрешение {normalized_resolution} уже существует для камеры {camera_name}. Перезаписать?",
                                    QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return
        
        # Добавляем разрешение в таблицу
        row = self.resolutions_table.rowCount()
        self.resolutions_table.insertRow(row)
        self.resolutions_table.setItem(row, 0, QTableWidgetItem(normalized_resolution))
        self.resolutions_table.setItem(row, 1, QTableWidgetItem(normalized_sensor))
        
        # Сохраняем в структуру данных камеры
        self.camera_data['cameras'][camera_name]['resolutions'][normalized_resolution] = normalized_sensor
        
        # Используем отложенное сохранение
        self.save_camera_data_delayed()
        
        QMessageBox.information(self, "Успех", f"Разрешение {normalized_resolution} добавлено к камере {camera_name}")




class SettingsManager:
    """Менеджер настроек приложения"""
    
    def __init__(self, main_window):
        self.main_window = main_window
        self.debug_logger = main_window.debug_logger
        
        # Настройки по умолчанию
        self.color_metadata = {}
        self.removed_metadata = {}
        self.sequence_colors = {}
        self.ordered_metadata_fields = []
        self.use_art_for_mxf = False
        self.default_metadata_tool = 'mediainfo'
        self.camera_detection_settings = {
            'camera_rules': [],
            'resolution_rules': [
                {'field': 'dataWindow', 'type': 'range'},
                {'field': 'displayWindow', 'type': 'range'},
                {'field': 'width', 'type': 'single_w'},
                {'field': 'height', 'type': 'single_h'}
            ]
        }
        
        # Путь к файлу настроек
        if SETTINGS_FILE_HARD:
            self.settings_file = SETTINGS_FILE_HARD
        else:
            self.settings_file = "exr_viewer_settings.json"
        
        self.load_settings()

    def load_settings(self):
        """Загружает настройки из файла"""
        try:
            if SETTINGS_FILE_HARD:
                settings_dir = os.path.dirname(SETTINGS_FILE_HARD)
                if settings_dir and not os.path.exists(settings_dir):
                    os.makedirs(settings_dir, exist_ok=True)
                    
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    
                    self.color_metadata = settings.get('color_metadata', {})
                    self.removed_metadata = settings.get('removed_metadata', {})
                    self.sequence_colors = settings.get('sequence_colors', {})
                    self.ordered_metadata_fields = settings.get('ordered_metadata_fields', [])
                    self.use_art_for_mxf = settings.get('use_art_for_mxf', False)
                    self.default_metadata_tool = settings.get('default_metadata_tool', 'mediainfo')
                    
                    if not self.ordered_metadata_fields and self.color_metadata:
                        self.ordered_metadata_fields = list(self.color_metadata.keys())

                    self.camera_detection_settings = settings.get('camera_detection', {
                        'camera_rules': [],
                        'resolution_rules': [
                            {'field': 'dataWindow', 'type': 'range'},
                            {'field': 'displayWindow', 'type': 'range'},
                            {'field': 'DataWindow', 'type': 'range'},  # Добавляем с большой буквы
                            {'field': 'DisplayWindow', 'type': 'range'},  # Добавляем с большой буквы
                            {'field': 'width', 'type': 'single_w'},
                            {'field': 'height', 'type': 'single_h'}
                        ]
                    })
                        
        except Exception as e:
            self.debug_logger.log(f"Ошибка загрузки настроек: {e}", "ERROR")
            # Оставляем значения по умолчанию

    def save_settings(self):
        """Сохраняет настройки в файл"""
        try:
            if SETTINGS_FILE_HARD:
                settings_dir = os.path.dirname(SETTINGS_FILE_HARD)
                if settings_dir and not os.path.exists(settings_dir):
                    os.makedirs(settings_dir, exist_ok=True)

            # Очистка данных цветов
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
                'use_art_for_mxf': self.use_art_for_mxf,
                'default_metadata_tool': self.default_metadata_tool,
                'camera_detection': self.camera_detection_settings
            }
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            self.debug_logger.log(f"Ошибка сохранения настроек: {e}", "ERROR")

    def get_field_color(self, field_name):
        """Возвращает цвет для поля метаданных"""
        if field_name in self.color_metadata:
            color_data = self.color_metadata[field_name]
            if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                if not color_data.get('removed', False):
                    return QColor(color_data['r'], color_data['g'], color_data['b'])
        return None

    def add_field_with_color(self, field_name, color):
        """Добавляет поле с выбранным цветом"""
        self.color_metadata[field_name] = {
            'r': color.red(),
            'g': color.green(),
            'b': color.blue(),
            'removed': False
        }
        
        if field_name not in self.ordered_metadata_fields:
            self.ordered_metadata_fields.append(field_name)
        
        self.save_settings()

    def change_field_color(self, field_name, color):
        """Изменяет цвет поля"""
        if field_name in self.color_metadata:
            self.color_metadata[field_name] = {
                'r': color.red(),
                'g': color.green(),
                'b': color.blue(),
                'removed': False
            }
            self.save_settings()

    def remove_field_from_colors(self, field_name):
        """Удаляет поле из цветных в корзину"""
        if field_name in self.color_metadata:
            color_data = self.color_metadata[field_name]
            self.removed_metadata[field_name] = color_data
            del self.color_metadata[field_name]
            
            if field_name in self.ordered_metadata_fields:
                self.ordered_metadata_fields.remove(field_name)
            
            self.save_settings()

    def restore_field_from_trash(self, field_name):
        """Восстанавливает поле из корзины"""
        if field_name in self.removed_metadata:
            color_data = self.removed_metadata[field_name]
            self.color_metadata[field_name] = color_data
            
            if field_name not in self.ordered_metadata_fields:
                self.ordered_metadata_fields.append(field_name)
            
            del self.removed_metadata[field_name]
            self.save_settings()

    def delete_field_permanently(self, field_name):
        """Окончательно удаляет поле"""
        if field_name in self.removed_metadata:
            del self.removed_metadata[field_name]
            self.save_settings()

    def empty_trash(self):
        """Очищает корзину"""
        self.removed_metadata.clear()
        self.save_settings()

    def add_sequence_color(self, seq_type, color):
        """Добавляет цвет для типа последовательности"""
        self.sequence_colors[seq_type] = {
            'r': color.red(),
            'g': color.green(),
            'b': color.blue()
        }
        self.save_settings()

    def change_sequence_color(self, seq_type, color):
        """Изменяет цвет типа последовательности"""
        if seq_type in self.sequence_colors:
            self.sequence_colors[seq_type] = {
                'r': color.red(),
                'g': color.green(),
                'b': color.blue()
            }
            self.save_settings()

    def delete_sequence_color(self, seq_type):
        """Удаляет цвет типа последовательности"""
        if seq_type in self.sequence_colors:
            del self.sequence_colors[seq_type]
            self.save_settings()






class CameraManager:
    """Менеджер работы с камерами и сенсорами"""
    
    def __init__(self, main_window, settings_manager):
        self.main_window = main_window
        self.settings_manager = settings_manager
        self.debug_logger = main_window.debug_logger
        self.camera_data = {}
        
        self.load_camera_data()

    def load_camera_data(self):
        """Загружает данные камер из JSON файла"""
        try:
            if os.path.exists(CAMERA_SENSOR_DATA_FILE):
                with open(CAMERA_SENSOR_DATA_FILE, 'r', encoding='utf-8') as f:
                    self.camera_data = json.load(f)
                self.debug_logger.log(f"Данные камер загружены из {CAMERA_SENSOR_DATA_FILE}")
            else:
                self.camera_data = {"cameras": {}}
                self.save_camera_data()
                self.debug_logger.log(f"Создан пустой файл данных камер: {CAMERA_SENSOR_DATA_FILE}")
        except Exception as e:
            self.debug_logger.log(f"Ошибка загрузки данных камер: {e}", "ERROR")
            self.camera_data = {"cameras": {}}

    def save_camera_data(self):
        """Сохраняет данные камер в JSON файл"""
        try:
            with open(CAMERA_SENSOR_DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.camera_data, f, ensure_ascii=False, indent=2)
            self.debug_logger.log(f"Данные камер сохранены в {CAMERA_SENSOR_DATA_FILE}")
        except Exception as e:
            self.debug_logger.log(f"Ошибка сохранения данных камер: {e}", "ERROR")

    def detect_camera_and_sensor(self, metadata):
        """Определяет камеру и разрешение из метаданных и возвращает размер сенсора и информацию об определении"""
        camera, camera_detection_info = self.detect_camera(metadata)
        resolution, resolution_detection_info = self.detect_resolution(metadata)
        
        detection_info = []
        
        if camera:
            detection_info.append(f"Камера: {camera}")
        if resolution:
            detection_info.append(f"Разрешение: {resolution}")
        
        if camera_detection_info:
            detection_info.extend(camera_detection_info)
        if resolution_detection_info:
            detection_info.extend(resolution_detection_info)
        
        if camera and resolution:
            sensor_size = self.get_sensor_size(camera, resolution)
            if sensor_size:
                return sensor_size, detection_info
        
        return None, detection_info

    def detect_camera(self, metadata):
        """Определяет камеру из метаданных на основе правил"""
        detection_info = []
        
        # Проверяем правила из настроек
        for rule in self.settings_manager.camera_detection_settings.get('camera_rules', []):
            field = rule.get('field')
            value = rule.get('value')
            camera = rule.get('camera')
            if field in metadata and str(metadata[field]) == value:
                detection_info.append(f"Правило: {field} = {value} → {camera}")
                return camera, detection_info
        
        # Автоматическое определение по именам в метаданных
        for camera_name, camera_info in self.camera_data.get('cameras', {}).items():
            for metadata_name in camera_info.get('metadata_names', []):
                if metadata_name:
                    for field, value in metadata.items():
                        if metadata_name == str(value):
                            detection_info.append(f"Авто: {field} = {value} → {camera_name}")
                            return camera_name, detection_info
        
        return None, detection_info

    def detect_resolution(self, metadata):
        """Определяет разрешение из метаданных на основе правил, выбирая наибольшее из найденных"""
        resolutions = []
        found_rules = []
        
        for rule in self.settings_manager.camera_detection_settings.get('resolution_rules', []):
            field = rule.get('field')
            rule_type = rule.get('type')
            
            # Ищем поле в метаданных (точное совпадение или частичное)
            matching_keys = []
            for metadata_key in metadata.keys():
                # Точное совпадение (без учета регистра)
                if metadata_key.lower() == field.lower():
                    matching_keys.append(metadata_key)
                # Частичное совпадение (поле содержит ключевое слово)
                elif field.lower() in metadata_key.lower():
                    matching_keys.append(metadata_key)
                    self.debug_logger.log(f"Частичное совпадение: '{metadata_key}' содержит '{field}'")
            
            for actual_field in matching_keys:
                value = metadata[actual_field]
                parsed = self.parse_resolution(value, rule_type, actual_field)
                if parsed:
                    found_rules.append(f"{actual_field} ({rule_type})")
                    
                    if rule_type == 'single_w':
                        resolutions.append((parsed, None, f"single_w: {parsed}"))
                    elif rule_type == 'single_h':
                        resolutions.append((None, parsed, f"single_h: {parsed}"))
                    else:
                        if isinstance(parsed, tuple) and len(parsed) == 2:
                            width, height = parsed
                            resolutions.append((width, height, f"{rule_type}: {width}x{height}"))
        
        best_resolution = self.select_best_resolution(resolutions)
        
        if best_resolution:
            width, height, source = best_resolution
            if width and height:
                return f"{width}x{height}", found_rules + [f"выбрано: {source}"]
            elif width:
                return f"{width}x?", found_rules + [f"выбрано: {source}"]
            elif height:
                return f"?x{height}", found_rules + [f"выбрано: {source}"]
        
        return None, found_rules

    def select_best_resolution(self, resolutions):
        """Выбирает наилучшее разрешение из списка найденных"""
        if not resolutions:
            return None
        
        # Полные разрешения (ширина и высота)
        full_resolutions = [(w, h, s) for w, h, s in resolutions if w is not None and h is not None]
        
        if full_resolutions:
            full_resolutions.sort(key=lambda x: x[0] * x[1], reverse=True)
            return full_resolutions[0]
        
        # Только ширины
        widths = [(w, s) for w, h, s in resolutions if w is not None and h is None]
        heights = [(h, s) for w, h, s in resolutions if w is None and h is not None]
        
        if widths and heights:
            max_width = max(widths, key=lambda x: x[0])
            max_height = max(heights, key=lambda x: x[0])
            return max_width[0], max_height[0], f"комбинировано: {max_width[1]} + {max_height[1]}"
        elif widths:
            max_width = max(widths, key=lambda x: x[0])
            return max_width[0], None, max_width[1]
        elif heights:
            max_height = max(heights, key=lambda x: x[0])
            return None, max_height[0], max_height[1]
        
        return None

    def parse_resolution(self, value, rule_type, field_name=""):
        """Парсит разрешение из значения в зависимости от типа правила"""
        try:
            value_str = str(value)

            self.debug_logger.log(f"Парсинг разрешения: поле='{field_name}', тип='{rule_type}', значение='{value_str}'")
            
            if rule_type == 'range':
                # Формат: (min_x, min_y) - (max_x, max_y)
                match = re.match(r'\((\d+),\s*(\d+)\)\s*-\s*\((\d+),\s*(\d+)\)', value_str)
                if match:
                    min_x, min_y, max_x, max_y = map(int, match.groups())
                    width = max_x - min_x + 1
                    height = max_y - min_y + 1
                    return width, height
                
                # Альтернативный формат: min_x min_y max_x max_y
                match = re.match(r'(\d+)\s+(\d+)\s+(\d+)\s+(\d+)', value_str)
                if match:
                    min_x, min_y, max_x, max_y = map(int, match.groups())
                    width = max_x - min_x + 1
                    height = max_y - min_y + 1
                    return width, height
                
                # НОВЫЙ ФОРМАТ: DataWindow: 0 0 5119 2699
                # Ищем паттерн с префиксом (может быть любым текстом перед числами)
                match = re.match(r'^(?:\w+\s*:\s*)?(\d+)\s+(\d+)\s+(\d+)\s+(\d+)$', value_str.strip())
                if match:
                    min_x, min_y, max_x, max_y = map(int, match.groups())
                    width = max_x - min_x + 1
                    height = max_y - min_y + 1
                    self.debug_logger.log(f"Распознан формат DataWindow: {min_x} {min_y} {max_x} {max_y} -> {width}x{height}")
                    return width, height
            
            elif rule_type == 'single_w':
                # Пытаемся извлечь число из строки
                numbers = re.findall(r'\d+', value_str)
                if numbers:
                    return int(numbers[0])
            
            elif rule_type == 'single_h':
                # Пытаемся извлечь число из строки
                numbers = re.findall(r'\d+', value_str)
                if numbers:
                    return int(numbers[0])
            
            elif rule_type == 'combined':
                # Формат: WxH или W x H
                match = re.match(r'(\d+)\s*[xX:]\s*(\d+)', value_str)
                if match:
                    width, height = map(int, match.groups())
                    return width, height
                
                # Поиск ширины и высоты отдельно
                width_match = re.search(r'[Ww]idth:\s*(\d+)', value_str)
                height_match = re.search(r'[Hh]eight:\s*(\d+)', value_str)
                if width_match and height_match:
                    width = int(width_match.group(1))
                    height = int(height_match.group(1))
                    return width, height
        
        except Exception as e:
            self.debug_logger.log(f"Ошибка парсинга разрешения для поля {field_name}: {e}", "ERROR")
        
        return None

    def get_sensor_size(self, camera, resolution):
        """Возвращает размер сенсора для заданной камеры и разрешения"""
        if camera in self.camera_data.get('cameras', {}):
            camera_info = self.camera_data['cameras'][camera]
            if resolution in camera_info.get('resolutions', {}):
                return camera_info['resolutions'][resolution]
        return None

    def add_camera_rule(self, field, value, camera):
        """Добавляет правило для камеры"""
        new_rule = {
            'field': field,
            'value': value,
            'camera': camera
        }
        self.settings_manager.camera_detection_settings.setdefault('camera_rules', []).append(new_rule)
        self.settings_manager.save_settings()

    def add_resolution_rule(self, field, rule_type):
        """Добавляет правило для разрешения"""
        new_rule = {
            'field': field,
            'type': rule_type
        }
        self.settings_manager.camera_detection_settings.setdefault('resolution_rules', []).append(new_rule)
        self.settings_manager.save_settings()




class TreeManager:
    """Менеджер для работы с древовидной структурой файлов и последовательностей"""
    
    def __init__(self, main_window, sequence_manager):
        self.main_window = main_window
        self.sequence_manager = sequence_manager
        self.debug_logger = main_window.debug_logger
        self.settings_manager = main_window.settings_manager
        
        # Структуры данных для дерева
        self.tree_structure = {}
        self.folder_items = {}
        self.root_item = None
        
        # Ссылки на UI элементы
        self.sequences_tree = None

    def setup_ui(self, sequences_tree):
        """Настраивает UI элементы дерева"""
        self.sequences_tree = sequences_tree
        
        # Настройка столбцов
        self.sequences_tree.setColumnCount(5)
        self.sequences_tree.setHeaderLabels(["Имя", "Тип", "Диапазон", "Количество", "Путь"])
        
        # Настройка размеров столбцов
        self.sequences_tree.setColumnWidth(0, 500)
        self.sequences_tree.setColumnWidth(1, 200)
        self.sequences_tree.setColumnWidth(2, 200)
        self.sequences_tree.setColumnWidth(3, 100)
        self.sequences_tree.setColumnWidth(4, 400)
        
        # Настройка поведения
        self.sequences_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sequences_tree.setSortingEnabled(True)
        self.sequences_tree.setContextMenuPolicy(Qt.CustomContextMenu)

    def clear_tree(self):
        """Очищает дерево"""
        self.sequences_tree.clear()
        self.tree_structure.clear()
        self.folder_items.clear()
        self.root_item = None

    def initialize_root(self, root_path):
        """Инициализирует корневой элемент дерева"""
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
        self.root_item.setExpanded(True)
        
        self.debug_logger.log(f"Создан и раскрыт корневой элемент: {root_path}")

    def add_sequence_to_tree(self, seq_info):
        """Добавляет последовательность в дерево в реальном времени"""
        try:
            seq_path = seq_info['path']
            display_name = seq_info.get('display_name', seq_info.get('name', 'Unknown'))
            frame_range = seq_info.get('frame_range', '')
            frame_count = seq_info.get('frame_count', 0)
            seq_type = seq_info.get('type', 'unknown')
            
            self.debug_logger.log(f"add_sequence_to_tree: Добавляем '{display_name}' в папку '{seq_path}'")
            
            # Проверяем, что путь находится в корневой папке
            root_path = self.main_window.ui_manager.folder_path.text()
            if not seq_path.startswith(root_path):
                self.debug_logger.log(f"  Пропускаем последовательность вне корневой папки: {seq_path}")
                return
            
            # Находим или создаем родительскую папку
            parent_item = self.find_or_create_folder_item(seq_path)
            
            # Создаем элемент последовательности
            seq_item = QTreeWidgetItem([
                display_name,
                seq_type,
                frame_range,
                str(frame_count),
                seq_path
            ])
            seq_item.setData(0, Qt.UserRole, {"type": "sequence", "info": seq_info})
            
            # Применяем цвет
            self.color_tree_item_by_type(seq_item, seq_type)
            
            # Добавляем к родителю
            parent_item.addChild(seq_item)
            
            # Раскрываем путь до корня
            self.expand_path_to_root(parent_item)
            
            self.debug_logger.log(f"Успешно добавлено в дерево: {display_name}")
            
        except Exception as e:
            self.debug_logger.log(f"Ошибка при добавлении в дерево: {str(e)}", "ERROR")
            import traceback
            self.debug_logger.log(f"Трассировка: {traceback.format_exc()}", "ERROR")

    def find_or_create_folder_item(self, folder_path):
        """Находит или создает элементы папок для указанного пути"""
        # Если папка уже существует, возвращаем ее
        if folder_path in self.folder_items:
            item = self.folder_items[folder_path]
            item.setExpanded(True)
            return item
        
        self.debug_logger.log(f"find_or_create_folder_item: Создаем папку '{folder_path}'")
        
        root_path = self.main_window.ui_manager.folder_path.text()
        
        # Если это корневая папка
        if folder_path == root_path:
            return self.root_item
        
        # Вычисляем относительный путь
        if folder_path.startswith(root_path):
            relative_path = folder_path[len(root_path):].lstrip(os.sep)
        else:
            relative_path = folder_path
        
        # Разбиваем путь на части и создаем папки рекурсивно
        parts = relative_path.split(os.sep)
        current_path = root_path
        parent_item = self.root_item
        
        for part in parts:
            if not part:  # Пропускаем пустые части
                continue
                
            current_path = os.path.join(current_path, part)
            
            # Создаем папку, если ее нет
            if current_path not in self.folder_items:
                folder_name = part
                folder_item = QTreeWidgetItem([
                    folder_name,
                    "Папка",
                    "",
                    "", 
                    "" 
                ])
                folder_item.setData(0, Qt.UserRole, {"type": "folder", "path": current_path})
                
                # Добавляем к родителю
                parent_item.addChild(folder_item)
                self.folder_items[current_path] = folder_item
                
                # Раскрываем папку
                folder_item.setExpanded(True)
                
                self.debug_logger.log(f"  Создана и раскрыта папка: '{folder_name}' -> '{current_path}'")
            
            # Переходим к следующему уровню
            parent_item = self.folder_items[current_path]
            
            # Убеждаемся, что папка раскрыта
            if hasattr(parent_item, 'setExpanded'):
                parent_item.setExpanded(True)
        
        return parent_item

    def expand_path_to_root(self, item):
        """Рекурсивно раскрывает все родительские элементы до корня"""
        current_item = item
        while current_item is not None:
            current_item.setExpanded(True)
            current_item = current_item.parent()

    def color_tree_item_by_type(self, item, seq_type):
        """Подкрашивает элемент дерева в зависимости от типа последовательности"""
        color_data = self.settings_manager.sequence_colors.get(seq_type)
        if color_data and isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
            color = QColor(color_data['r'], color_data['g'], color_data['b'])
        else:
            # Цвет по умолчанию
            color = QColor(240, 240, 240)
        
        # Применяем цвет ко всем столбцам
        for col in range(self.sequences_tree.columnCount()):
            item.setBackground(col, color)

    def expand_all_tree_items(self):
        """Раскрывает все элементы дерева"""
        def expand_item(item):
            item.setExpanded(True)
            for i in range(item.childCount()):
                expand_item(item.child(i))
        
        for i in range(self.sequences_tree.topLevelItemCount()):
            expand_item(self.sequences_tree.topLevelItem(i))

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

    def filter_sequences(self, search_text):
        """Фильтрует дерево последовательностей по введенному тексту с правильным подсчетом секвенций"""
        search_text = search_text.lower().strip()
        
        self.debug_logger.log(f"Поиск последовательностей: '{search_text}'")
        
        if not search_text:
            self.show_all_tree_items()
            self.debug_logger.log("Поиск очищен, показаны все элементы")
            return
        
        self.hide_all_tree_items()
        
        root = self.sequences_tree.invisibleRootItem()
        visible_sequences_count = self.filter_tree_items_sequences_only(root, search_text)
        
        # Подсчитываем общее количество секвенций в дереве
        total_sequences = self.count_all_sequences()
        self.debug_logger.log(f"Найдено последовательностей: {visible_sequences_count} из {total_sequences}")
        
        # Если ничего не найдено, показываем сообщение
        if visible_sequences_count == 0:
            self.debug_logger.log("Ни одной последовательности не найдено по запросу")

    def filter_tree_items_sequences_only(self, parent_item, search_text):
        """Рекурсивно фильтрует элементы дерева, считая только секвенции"""
        visible_sequences = 0
        
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child_data = child.data(0, Qt.UserRole)
            
            if child_data and child_data.get('type') == 'sequence':
                # Это секвенция - проверяем соответствие поиску
                matches_search = self.item_matches_search(child, search_text)
                
                if matches_search:
                    child.setHidden(False)
                    visible_sequences += 1
                    # Раскрываем родителей для показа найденных элементов
                    self.expand_parents(child)
                    self.debug_logger.log(f"Секвенция показана: {child.text(0)}")
                else:
                    child.setHidden(True)
                    self.debug_logger.log(f"Секвенция скрыта: {child.text(0)}")
                    
            elif child_data and child_data.get('type') == 'folder':
                # Это папка - рекурсивно обрабатываем детей
                child_visible_sequences = self.filter_tree_items_sequences_only(child, search_text)
                
                if child_visible_sequences > 0:
                    # В папке есть видимые секвенции - показываем папку
                    child.setHidden(False)
                    visible_sequences += child_visible_sequences
                    # Раскрываем папку
                    child.setExpanded(True)
                    self.debug_logger.log(f"Папка показана (содержит {child_visible_sequences} секвенций): {child.text(0)}")
                else:
                    # В папке нет видимых секвенций - скрываем
                    child.setHidden(True)
                    self.debug_logger.log(f"Папка скрыта (нет секвенций): {child.text(0)}")
        
        return visible_sequences

    def count_all_sequences(self, parent_item=None):
        """Рекурсивно подсчитывает общее количество секвенций в дереве"""
        if parent_item is None:
            parent_item = self.sequences_tree.invisibleRootItem()
        
        sequence_count = 0
        
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child_data = child.data(0, Qt.UserRole)
            
            if child_data and child_data.get('type') == 'sequence':
                sequence_count += 1
            elif child_data and child_data.get('type') == 'folder':
                sequence_count += self.count_all_sequences(child)
        
        return sequence_count

    def count_all_tree_items(self):
        """Подсчитывает общее количество элементов в дереве"""
        root = self.sequences_tree.invisibleRootItem()
        return self.count_tree_items(root)

    def count_tree_items(self, item):
        """Рекурсивно подсчитывает количество элементов в дереве"""
        count = 1  # Текущий элемент
        for i in range(item.childCount()):
            count += self.count_tree_items(item.child(i))
        return count

    def filter_tree_items(self, parent_item, search_text):
        """Рекурсивно фильтрует элементы дерева с улучшенным подсчетом"""
        visible_children = 0
        
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            
            matches_search = self.item_matches_search(child, search_text)
            
            child_visible_children = self.filter_tree_items(child, search_text)
            
            if matches_search or child_visible_children > 0:
                child.setHidden(False)
                visible_children += 1
                
                # Раскрываем родителей для показа найденных элементов
                self.expand_parents(child)
                
                self.debug_logger.log(f"Элемент показан: {child.text(0)} (совпадение: {matches_search}, дочерние: {child_visible_children})")
            else:
                child.setHidden(True)
                self.debug_logger.log(f"Элемент скрыт: {child.text(0)}")
        
        return visible_children

    def item_matches_search(self, item, search_text):
        """Проверяет, соответствует ли элемент дерева поисковому запросу"""
        if not search_text:
            return True
        
        # Собираем весь текст элемента
        item_text = ""
        for col in range(self.sequences_tree.columnCount()):
            item_text += " " + item.text(col).lower()
        
        item_data = item.data(0, Qt.UserRole)
        if item_data:
            if item_data.get('type') == 'sequence':
                seq_info = item_data.get('info', {})
                
                item_text += " " + seq_info.get('name', '').lower()
                item_text += " " + seq_info.get('display_name', '').lower()
                item_text += " " + seq_info.get('type', '').lower()
                item_text += " " + seq_info.get('frame_range', '').lower()
                item_text += " " + seq_info.get('extension', '').lower()
                item_text += " " + seq_info.get('path', '').lower()
                
                files = seq_info.get('files', [])
                for file_path in files:
                    item_text += " " + os.path.basename(file_path).lower()
                    item_text += " " + file_path.lower()
                    
            elif item_data.get('type') == 'folder':
                path = item_data.get('path', '')
                item_text += " " + path.lower()
        
        # Проверяем соответствие
        matches = search_text in item_text
        if matches:
            self.debug_logger.log(f"Найдено соответствие: '{search_text}' в '{item_text.strip()}'")
        
        return matches

    def expand_parents(self, item):
        """Раскрывает всех родителей элемента"""
        parent = item.parent()
        while parent:
            parent.setExpanded(True)
            parent = parent.parent()

    def show_all_tree_items(self):
        """Показывает все элементы дерева"""
        root = self.sequences_tree.invisibleRootItem()
        self.show_tree_items_recursive(root)

    def show_tree_items_recursive(self, parent_item):
        """Рекурсивно показывает все элементы дерева"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setHidden(False)
            self.show_tree_items_recursive(child)

    def hide_all_tree_items(self):
        """Скрывает все элементы дерева (кроме корневого)"""
        root = self.sequences_tree.invisibleRootItem()
        self.hide_tree_items_recursive(root)

    def hide_tree_items_recursive(self, parent_item):
        """Рекурсивно скрывает все элементы дерева"""
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setHidden(True)
            self.hide_tree_items_recursive(child)

    def count_tree_items(self, item):
        """Рекурсивно подсчитывает количество элементов в дереве"""
        count = 1  # Текущий элемент
        for i in range(item.childCount()):
            count += self.count_tree_items(item.child(i))
        return count

    def get_selected_item_data(self):
        """Возвращает данные выбранного элемента"""
        selected_items = self.sequences_tree.selectedItems()
        if not selected_items:
            return None
        return selected_items[0].data(0, Qt.UserRole)

    def update_sequences_colors(self):
        """Обновляет цвета в дереве последовательностей"""
        for i in range(self.sequences_tree.topLevelItemCount()):
            top_item = self.sequences_tree.topLevelItem(i)
            self.update_tree_item_colors(top_item)

    def update_tree_item_colors(self, item):
        """Рекурсивно обновляет цвета элементов дерева"""
        item_data = item.data(0, Qt.UserRole)
        if item_data and item_data['type'] == 'sequence':
            seq_type = item_data['info']['type']
            self.color_tree_item_by_type(item, seq_type)
        
        # Рекурсивно обновляем дочерние элементы
        for i in range(item.childCount()):
            self.update_tree_item_colors(item.child(i))



class MetadataManager:
    """Менеджер для работы с метаданными файлов"""
    
    def __init__(self, main_window, camera_manager, tool_manager):
        self.main_window = main_window
        self.camera_manager = camera_manager
        self.tool_manager = tool_manager
        self.debug_logger = main_window.debug_logger
        self.settings_manager = main_window.settings_manager
        
        # Текущие метаданные
        self.current_metadata = {}
        self.current_sensor_info = {}
        
        # Принудительные настройки чтения
        self.forced_metadata_tool = None
        self.forced_metadata_file = None
        
        # Ссылки на UI элементы
        self.metadata_table = None
        self.metadata_source_label = None
        self.search_input = None

    def setup_ui(self, metadata_table, metadata_source_label, search_input):
        """Настраивает UI элементы для метаданных"""
        self.metadata_table = metadata_table
        self.metadata_source_label = metadata_source_label
        self.search_input = search_input
        
        # Настройка таблицы метаданных
        self.metadata_table.setColumnCount(2)
        self.metadata_table.setHorizontalHeaderLabels(["Поле", "Значение"])
        
        # Настройка размеров столбцов
        for i, width in enumerate(DEFAULT_COLUMN_WIDTHS['metadata']):
            self.metadata_table.setColumnWidth(i, width)
        
        # Настройка поведения заголовков
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.metadata_table.setColumnWidth(0, DEFAULT_COLUMN_WIDTHS['metadata'][0])
        
        self.metadata_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.metadata_table.setContextMenuPolicy(Qt.CustomContextMenu)

    def display_metadata(self, file_path, extension, forced_tool=None):
        """Отображает метаданные для файла"""
        try:
            if not os.path.exists(file_path):
                self.show_error(f"Файл не найден: {file_path}")
                return
            
            # Сбрасываем принудительные настройки, если файл изменился
            # ИСПРАВЛЕНИЕ: Используем sequence_manager вместо прямого обращения к current_sequence_files
            current_files = self.main_window.sequence_manager.get_current_sequence_files()
            if forced_tool is None and self.forced_metadata_file != file_path:
                self.forced_metadata_tool = None
                self.forced_metadata_file = None
            
            # Определяем инструмент для чтения
            if forced_tool:
                metadata_tool = forced_tool
            elif self.forced_metadata_tool and self.forced_metadata_file == file_path:
                metadata_tool = self.forced_metadata_tool
            else:
                metadata_tool = None
            
            self.debug_logger.log(f"Чтение метаданных для {file_path} с помощью {metadata_tool if metadata_tool else 'автоматического выбора'}")
            
            # Читаем метаданные
            self.current_metadata = {}
            metadata_source = self.read_metadata(file_path, extension, metadata_tool)
            
            # Добавляем базовую информацию о файле
            self.add_file_info(file_path)
            
            # Определяем камеру и сенсор
            sensor_size, detection_info = self.camera_manager.detect_camera_and_sensor(self.current_metadata)
            self.current_sensor_info = {
                'size': sensor_size,
                'detection_info': detection_info
            }
            
            # Форматируем и отображаем метаданные
            self.format_and_display_metadata(metadata_source, forced_tool)
            
        except Exception as e:
            self.show_error(f"Ошибка чтения метаданных: {str(e)}")
            self.debug_logger.log(f"Общая ошибка чтения метаданных для {file_path}: {str(e)}", "ERROR")

    def update_metadata_colors(self):
        """Обновляет цвета в таблице метаданных"""
        if not self.current_metadata:
            return
        
        # Перерисовываем таблицу с текущими метаданными
        if hasattr(self, 'last_metadata_source'):
            self.format_and_display_metadata(self.last_metadata_source, None)


    def read_metadata(self, file_path, extension, metadata_tool=None):
        """Читает метаданные файла с помощью указанного инструмента"""
        extension_lower = extension.lower()
        metadata_source = "Unknown"
        
        if metadata_tool:
            # Принудительное чтение указанным инструментом
            if metadata_tool == 'ffprobe':
                self.add_ffprobe_metadata(file_path)
                metadata_source = f"FFprobe ({'принудительно' if metadata_tool else 'сохранено'})"
            elif metadata_tool == 'mediainfo':
                if PYMEDIAINFO_AVAILABLE:
                    self.add_mediainfo_metadata(file_path)
                    metadata_source = f"MediaInfo ({'принудительно' if metadata_tool else 'сохранено'})"
                else:
                    self.current_metadata["MediaInfo Error"] = "MediaInfo не доступен"
                    metadata_source = "MediaInfo Not Available"
            elif metadata_tool == 'exiftool':
                if self.tool_manager.exiftool_available:
                    self.add_exiftool_metadata(file_path)
                    metadata_source = f"ExifTool ({'принудительно' if metadata_tool else 'сохранено'})"
                else:
                    self.current_metadata["ExifTool Error"] = "ExifTool не доступен"
                    metadata_source = "ExifTool Not Available"
        else:
            # Автоматический выбор инструмента на основе типа файла
            if extension_lower == '.exr':
                metadata_source = self.read_exr_metadata(file_path)
            elif extension_lower == '.r3d':
                metadata_source = self.read_r3d_metadata(file_path)
            elif extension_lower in ['.jpg', '.jpeg', '.arw', '.cr2', '.dng', '.nef', '.tif', '.tiff'] and EXIFREAD_AVAILABLE:
                metadata_source = self.read_exif_metadata(file_path)
            elif extension_lower in ['.png', '.bmp', '.gif', '.webp'] and PILLOW_AVAILABLE:
                metadata_source = self.read_image_metadata(file_path)
            elif extension_lower in ['.mxf', '.arr', '.arx']:
                metadata_source = self.read_mxf_metadata(file_path)
            else:
                # Используем инструмент по умолчанию для других форматов
                metadata_source = self.read_with_default_tool(file_path)
        
        return metadata_source

    def read_exr_metadata(self, file_path):
        """Читает метаданные EXR файла"""
        try:
            exr_file = OpenEXR.InputFile(file_path)
            header = exr_file.header()
            
            for key, value in header.items():
                self.current_metadata[key] = self.format_metadata_value(value)
            
            self.debug_logger.log(f"Прочитано {len(header)} метаданных EXR из {file_path}")
            return "OpenEXR"
            
        except Exception as e:
            self.current_metadata["Ошибка чтения EXR"] = f"Не удалось прочитать EXR метаданные: {str(e)}"
            self.debug_logger.log(f"Ошибка чтения EXR для {file_path}: {str(e)}", "ERROR")
            return "OpenEXR Error"

    def read_r3d_metadata(self, file_path):
        """Читает метаданные R3D файла"""
        if self.settings_manager.use_art_for_mxf and os.path.exists(REDLINE_TOOL_PATH):
            return self.read_redline_metadata(file_path)
        else:
            if PYMEDIAINFO_AVAILABLE:
                self.add_mediainfo_metadata(file_path)
                return "MediaInfo"
            else:
                self.current_metadata["MediaInfo Error"] = "MediaInfo не доступен"
                return "MediaInfo Not Available"

    def read_redline_metadata(self, file_path):
        """Читает метаданные через REDline"""
        try:
            temp_output_path = None
            try:
                # Создаем временный файл для вывода
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as temp_file:
                    temp_output_path = temp_file.name
                
                # Запускаем REDline
                cmd = [
                    REDLINE_TOOL_PATH,
                    '--i', file_path,
                    '--useMeta',
                    '--printMeta', '1'
                ]
                
                self.debug_logger.log(f"Запуск REDline: {' '.join(cmd)}")
                self.debug_logger.log(f"Временный файл вывода: {temp_output_path}")
                
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
                
                # Сохраняем вывод в файл для отладки
                with open(temp_output_path, 'w') as output_file:
                    output_file.write("=== STDOUT ===\n")
                    output_file.write(result.stdout)
                    output_file.write("\n=== STDERR ===\n")
                    output_file.write(result.stderr)
                
                # Анализируем вывод - REDline часто пишет в stderr
                output = result.stderr if result.stderr.strip() else result.stdout
                
                if output.strip():
                    lines = output.strip().split('\n')
                    redline_metadata_count = 0
                    for line in lines:
                        line = line.strip()
                        if not line or ':' not in line:
                            continue
                        
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            key = parts[0].strip()
                            value = parts[1].strip()
                            
                            # Пропускаем разделители отладки
                            if key.startswith("==="):
                                continue
                                
                            self.current_metadata[f"RED {key}"] = value
                            redline_metadata_count += 1
                    
                    if redline_metadata_count > 0:
                        self.debug_logger.log(f"Прочитано {redline_metadata_count} метаданных RED из {file_path} (код возврата: {result.returncode})")
                        return "REDline"
                    else:
                        error_msg = f"REDline не вернул метаданные (код {result.returncode})"
                        self.debug_logger.log(error_msg, "WARNING")
                        self.current_metadata["REDline Error"] = error_msg
                        
                        # Fallback на MediaInfo
                        if PYMEDIAINFO_AVAILABLE:
                            self.debug_logger.log("Используем MediaInfo как fallback для R3D")
                            self.add_mediainfo_metadata(file_path)
                            return "MediaInfo (REDline fallback)"
                        else:
                            return "REDline No Data"
                else:
                    error_msg = f"REDline не вернул данных (код {result.returncode})"
                    self.debug_logger.log(error_msg, "WARNING")
                    self.current_metadata["REDline Error"] = error_msg
                    
                    # Fallback на MediaInfo
                    if PYMEDIAINFO_AVAILABLE:
                        self.debug_logger.log("Используем MediaInfo как fallback для R3D")
                        self.add_mediainfo_metadata(file_path)
                        return "MediaInfo (REDline fallback)"
                    else:
                        return "REDline No Output"
                        
            except subprocess.TimeoutExpired:
                self.debug_logger.log("REDline timeout", "WARNING")
                if PYMEDIAINFO_AVAILABLE:
                    self.add_mediainfo_metadata(file_path)
                    return "MediaInfo (REDline timeout fallback)"
                else:
                    self.current_metadata["REDline Error"] = "REDline timeout"
                    return "REDline Timeout"
            except Exception as e:
                self.debug_logger.log(f"Ошибка REDline: {str(e)}", "WARNING")
                if PYMEDIAINFO_AVAILABLE:
                    self.add_mediainfo_metadata(file_path)
                    return "MediaInfo (REDline error fallback)"
                else:
                    self.current_metadata["REDline Error"] = f"REDline error: {str(e)}"
                    return "REDline Error"
            finally:
                # Удаляем временный файл
                if temp_output_path and os.path.exists(temp_output_path):
                    try:
                        os.unlink(temp_output_path)
                        self.debug_logger.log(f"Временный файл удален: {temp_output_path}")
                    except Exception as e:
                        self.debug_logger.log(f"Ошибка удаления временного файла: {e}", "WARNING")
        except Exception as e:
            self.debug_logger.log(f"Общая ошибка в read_redline_metadata: {str(e)}", "ERROR")
            self.current_metadata["REDline Error"] = f"Общая ошибка: {str(e)}"
            return "REDline Error"


    def read_exif_metadata(self, file_path):
        """Читает EXIF метаданные изображений"""
        try:
            with open(file_path, 'rb') as f:
                tags = exifread.process_file(f, details=False)
            
            if tags:
                for tag, value in tags.items():
                    formatted_value = self.format_exif_value(tag, value)
                    self.current_metadata[f"EXIF {tag}"] = formatted_value
                self.debug_logger.log(f"Прочитано {len(tags)} EXIF тегов из {file_path}")
                return "exifread"
            else:
                self.current_metadata["EXIF"] = "EXIF данные не найдены"
                self.debug_logger.log(f"EXIF данные не найдены в {file_path}")
                return "exifread"
                
        except Exception as e:
            self.current_metadata["Ошибка чтения EXIF"] = f"Не удалось прочитать EXIF метаданные: {str(e)}"
            self.debug_logger.log(f"Ошибка чтения EXIF для {file_path}: {str(e)}", "ERROR")
            return "exifread Error"

    def read_image_metadata(self, file_path):
        """Читает метаданные изображений через Pillow"""
        try:
            with Image.open(file_path) as img:
                self.current_metadata["Формат"] = img.format
                self.current_metadata["Режим"] = img.mode
                self.current_metadata["Размер"] = f"{img.width} x {img.height}"
                
                # Читаем EXIF данные
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
                
                # Дополнительная информация
                info = img.info
                for key, value in info.items():
                    if key != 'exif':  # EXIF уже обработали
                        self.current_metadata[key] = str(value)
                        
            return "Pillow"
            
        except Exception as e:
            self.current_metadata["Ошибка чтения"] = f"Не удалось прочитать метаданные изображения: {str(e)}"
            self.debug_logger.log(f"Ошибка чтения изображения для {file_path}: {str(e)}", "ERROR")
            return "Pillow Error"

    def read_mxf_metadata(self, file_path):
        """Читает метаданные MXF файлов"""
        if self.settings_manager.use_art_for_mxf and os.path.exists(ARRI_REFERENCE_TOOL_PATH):
            return self.read_arri_metadata(file_path)
        else:
            if PYMEDIAINFO_AVAILABLE:
                self.add_mediainfo_metadata(file_path)
                return "MediaInfo"
            else:
                self.current_metadata["MediaInfo Error"] = "MediaInfo не доступен"
                return "MediaInfo Not Available"

    def read_arri_metadata(self, file_path):
        """Читает метаданные через ARRI Reference Tool"""
        try:
            temp_json_path = None
            try:
                # Создаем временный файл для JSON вывода
                with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as temp_file:
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
                    # Читаем JSON с метаданными
                    with open(temp_json_path, 'r', encoding='utf-8') as f:
                        arri_metadata = json.load(f)
                    
                    # Разбираем JSON на отдельные ключи
                    flattened_metadata = self.flatten_json(arri_metadata)
                    
                    # Добавляем метаданные
                    for key, value in flattened_metadata.items():
                        self.current_metadata[f"ARRI.{key}"] = self.format_metadata_value(value)
                    
                    self.debug_logger.log(f"Прочитано {len(flattened_metadata)} метаданных ARRI из {file_path}")
                    return "ARRI Reference Tool"
                    
                else:
                    self.debug_logger.log(f"ARRI Tool вернул ошибку: {result.stderr}", "WARNING")
                    
                    # Fallback на MediaInfo
                    if PYMEDIAINFO_AVAILABLE:
                        self.debug_logger.log("Используем MediaInfo как fallback для MXF")
                        self.add_mediainfo_metadata(file_path)
                        return "MediaInfo (ART fallback)"
                    else:
                        self.current_metadata["ARRI Tool Error"] = f"ARRI Tool failed: {result.stderr}"
                        return "ARRI Tool Failed"
                        
            except subprocess.TimeoutExpired:
                self.debug_logger.log("ARRI Tool timeout", "WARNING")
                if PYMEDIAINFO_AVAILABLE:
                    self.add_mediainfo_metadata(file_path)
                    return "MediaInfo (ART timeout fallback)"
                else:
                    self.current_metadata["ARRI Tool Error"] = "ARRI Tool timeout"
                    return "ARRI Tool Timeout"
            except Exception as e:
                self.debug_logger.log(f"Ошибка ARRI Tool: {str(e)}", "WARNING")
                if PYMEDIAINFO_AVAILABLE:
                    self.add_mediainfo_metadata(file_path)
                    return "MediaInfo (ART error fallback)"
                else:
                    self.current_metadata["ARRI Tool Error"] = f"ARRI Tool error: {str(e)}"
                    return "ARRI Tool Error"
            finally:
                # Удаляем временный файл
                if temp_json_path and os.path.exists(temp_json_path):
                    try:
                        os.unlink(temp_json_path)
                        self.debug_logger.log(f"Временный файл удален: {temp_json_path}")
                    except Exception as e:
                        self.debug_logger.log(f"Ошибка удаления временного файла: {e}", "WARNING")
        except Exception as e:
            self.debug_logger.log(f"Общая ошибка в read_arri_metadata: {str(e)}", "ERROR")
            self.current_metadata["ARRI Tool Error"] = f"Общая ошибка: {str(e)}"
            return "ARRI Tool Error"


    def read_with_default_tool(self, file_path):
        """Читает метаданные с помощью инструмента по умолчанию"""
        if self.settings_manager.default_metadata_tool == 'ffprobe':
            self.add_ffprobe_metadata(file_path)
            return "FFprobe"
        elif self.settings_manager.default_metadata_tool == 'mediainfo':
            if PYMEDIAINFO_AVAILABLE:
                self.add_mediainfo_metadata(file_path)
                return "MediaInfo"
            else:
                self.current_metadata["MediaInfo Error"] = "MediaInfo не доступен"
                return "MediaInfo Not Available"
        elif self.settings_manager.default_metadata_tool == 'exiftool':
            if self.tool_manager.exiftool_available:
                self.add_exiftool_metadata(file_path)
                return "ExifTool"
            else:
                self.current_metadata["ExifTool Error"] = "ExifTool не доступен"
                return "ExifTool Not Available"

    def add_file_info(self, file_path):
        """Добавляет базовую информацию о файле"""
        file_stats = os.stat(file_path)
        self.current_metadata["Имя файла"] = os.path.basename(file_path)
        self.current_metadata["Путь"] = file_path
        self.current_metadata["Размер файла"] = f"{file_stats.st_size} байт ({file_stats.st_size / 1024 / 1024:.2f} MB)"
        self.current_metadata["Дата создания"] = datetime.datetime.fromtimestamp(file_stats.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
        self.current_metadata["Дата изменения"] = datetime.datetime.fromtimestamp(file_stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    def format_and_display_metadata(self, metadata_source, forced_tool=None):
        """Форматирует и отображает метаданные в таблице"""

            # Сохраняем источник для возможного обновления
        self.last_metadata_source = metadata_source

        self.debug_logger.log(f"Всего собрано {len(self.current_metadata)} метаданных")

        # Добавляем принудительную пометку к источнику
        if forced_tool:
            metadata_source = f"{metadata_source} (принудительно)"

        # Сортируем метаданные с учетом цветов
        colored_metadata = {}
        normal_metadata = {}
        
        for key, value in self.current_metadata.items():
            if key in self.settings_manager.color_metadata and not self.settings_manager.color_metadata[key].get('removed', False):
                colored_metadata[key] = value
            else:
                normal_metadata[key] = value
        
        # Сортируем цветные метаданные по порядку
        sorted_colored = []
        for field_name in self.settings_manager.ordered_metadata_fields:
            if field_name in colored_metadata:
                sorted_colored.append((field_name, colored_metadata[field_name]))
        
        # Добавляем остальные цветные метаданные
        for field_name, value in colored_metadata.items():
            if field_name not in self.settings_manager.ordered_metadata_fields:
                sorted_colored.append((field_name, value))
        
        # Сортируем обычные метаданные
        sorted_normal = sorted(normal_metadata.items())
        
        # Объединяем с информацией о сенсоре в начале
        sorted_metadata = []
        
        sensor_display_value = self.current_sensor_info['size'] if self.current_sensor_info['size'] else "не определено"
        sorted_metadata.append(("Detected Sensor", sensor_display_value))

        sorted_metadata.extend(sorted_colored)
        sorted_metadata.extend(sorted_normal)
        
        # Отображаем в таблице
        self.metadata_table.setRowCount(len(sorted_metadata))
        
        for row, (key, value) in enumerate(sorted_metadata):
            key_item = QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
            
            value_item = QTableWidgetItem(str(value))
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)
            
            # Добавляем подсказку для сенсора
            if key == "Detected Sensor":
                detection_info = self.current_sensor_info.get('detection_info', [])
                if detection_info:
                    resolution_info = []
                    camera_info = []
                    actual_resolution = None
                    actual_camera = None
                    
                    for info in detection_info:
                        if "разрешение:" in info.lower():
                            actual_resolution = info.replace("Разрешение:", "").strip()
                        elif "камера:" in info.lower():
                            actual_camera = info.replace("Камера:", "").strip()
                        elif "разрешение" in info.lower() or "width" in info.lower() or "height" in info.lower():
                            resolution_info.append(info)
                        else:
                            camera_info.append(info)
                    
                    tooltip_parts = []
                    
                    if actual_camera:
                        tooltip_parts.append(f"Камера: {actual_camera}")
                    if actual_resolution:
                        tooltip_parts.append(f"Разрешение: {actual_resolution}")
                    
                    if tooltip_parts:
                        tooltip_parts.append("")  
                    
                    if any("выбрано:" in info for info in resolution_info):
                        tooltip_parts.append("Стратегия выбора: наибольшее разрешение")
                    
                    if camera_info:
                        tooltip_parts.append("Камера определена по:")
                        tooltip_parts.extend(camera_info)
                    if resolution_info:
                        if tooltip_parts:
                            tooltip_parts.append("")  
                        tooltip_parts.append("Разрешение определено по:")
                        tooltip_parts.extend(resolution_info)
                    
                    tooltip_text = "\n".join(tooltip_parts)
                else:
                    tooltip_text = "Не удалось определить камеру или разрешение"
                
                key_item.setToolTip(tooltip_text)
                value_item.setToolTip(tooltip_text)
            
            self.metadata_table.setItem(row, 0, key_item)
            self.metadata_table.setItem(row, 1, value_item)
            
            # Применяем цвет
            self.apply_field_color(row, key)

        # Обновляем метку источника
        # ИСПРАВЛЕНИЕ: Используем sequence_manager вместо прямого обращения к current_sequence_files
        current_files = self.main_window.sequence_manager.get_current_sequence_files()
        if self.forced_metadata_tool and self.forced_metadata_file == (current_files[0] if current_files else None):
            tool_name = METADATA_TOOLS.get(self.forced_metadata_tool, self.forced_metadata_tool)
            self.metadata_source_label.setText(f"Метаданные выбранного элемента ({tool_name} - принудительно):")
        else:
            self.metadata_source_label.setText(f"Метаданные выбранного элемента ({metadata_source}):")
        
        # Очищаем поиск
        self.clear_search()

    def apply_field_color(self, row, field_name):
        """Применяет цвет к полю в таблице"""
        color = self.settings_manager.get_field_color(field_name)
        if color:
            for col in range(2):
                item = self.metadata_table.item(row, col)
                if item:
                    item.setBackground(color)

    def show_error(self, message):
        """Показывает сообщение об ошибке в таблице"""
        self.metadata_table.setRowCount(1)
        self.metadata_table.setItem(0, 0, QTableWidgetItem("Ошибка"))
        self.metadata_table.setItem(0, 1, QTableWidgetItem(message))
        self.metadata_source_label.setText("Метаданные выбранного элемента: Ошибка")

    def filter_metadata(self, search_text):
        """Фильтрует таблицу метаданных по введенному тексту"""
        search_text = search_text.lower().strip()
        
        if not search_text:
            for row in range(self.metadata_table.rowCount()):
                self.metadata_table.setRowHidden(row, False)
            return
        
        for row in range(self.metadata_table.rowCount()):
            field_item = self.metadata_table.item(row, 0)
            value_item = self.metadata_table.item(row, 1)
            
            field_text = field_item.text().lower() if field_item else ""
            value_text = value_item.text().lower() if value_item else ""
            
            if search_text in field_text or search_text in value_text:
                self.metadata_table.setRowHidden(row, False)
            else:
                self.metadata_table.setRowHidden(row, True)

    def clear_search(self):
        """Очищает поле поиска и показывает все строки"""
        self.search_input.clear()
        for row in range(self.metadata_table.rowCount()):
            self.metadata_table.setRowHidden(row, False)

    def force_read_metadata(self, file_path, extension, tool):
        """Принудительно читает метаданные с помощью указанного инструмента"""
        self.debug_logger.log(f"Принудительное чтение метаданных для {file_path} с помощью {tool}")
        
        self.forced_metadata_tool = tool
        self.forced_metadata_file = file_path
        
        self.display_metadata(file_path, extension, forced_tool=tool)

    # Методы для чтения метаданных различными инструментами
    def add_ffprobe_metadata(self, file_path):
        """Добавляет метаданные через FFprobe"""
        try:
            # Проверяем доступность FFprobe
            result = subprocess.run(['ffprobe', '-version'], capture_output=True, text=True)
            if result.returncode != 0:
                self.current_metadata["Ошибка FFprobe"] = "FFprobe не доступен в системе"
                self.debug_logger.log("FFprobe не доступен в системе", "WARNING")
                return
            
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
                        if key != 'tags':  
                            self.current_metadata[f"FFprobe Format - {key}"] = self.format_ffprobe_value(value)
                    
                    # Теги формата
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
                        
                        # Теги потока
                        if 'tags' in stream:
                            for tag_key, tag_value in stream['tags'].items():
                                self.current_metadata[f"FFprobe Stream {i} ({stream_type}) Tag - {tag_key}"] = self.format_ffprobe_value(tag_value)
                        
                        # Диспозиции
                        if 'disposition' in stream:
                            for disp_key, disp_value in stream['disposition'].items():
                                if disp_value == 1:  
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

    def add_mediainfo_metadata(self, file_path):
        """Добавляет метаданные через MediaInfo"""
        try:
            media_info = MediaInfo.parse(file_path)
            self.debug_logger.log(f"Прочитано {len(media_info.tracks)} треков MediaInfo из {file_path}")
            
            for track in media_info.tracks:
                track_type = track.track_type
                
                # Разделитель для типа трека
                self.current_metadata[f"MediaInfo - {track_type} Track"] = "---"
                
                # Читаем все атрибуты трека
                for attribute_name in dir(track):
                    # Пропускаем служебные атрибуты
                    if attribute_name.startswith('_') or attribute_name in ['to_data', 'to_json']:
                        continue
                    
                    try:
                        attribute_value = getattr(track, attribute_name)
                        
                        # Добавляем только непустые значения
                        if attribute_value is not None and str(attribute_value).strip() != '':
                            # Ограничиваем длину значения
                            str_value = str(attribute_value)
                            if len(str_value) > 500:
                                str_value = str_value[:500] + "... [урезано]"
                            
                            self.current_metadata[f"MediaInfo {track_type} - {attribute_name}"] = str_value
                    except Exception as e:
                        self.debug_logger.log(f"Ошибка чтения атрибута {attribute_name} для трека {track_type}: {str(e)}", "WARNING")
                        
        except Exception as e:
            self.current_metadata["Ошибка чтения MediaInfo"] = f"Не удалось прочитать MediaInfo метаданные: {str(e)}"
            self.debug_logger.log(f"Ошибка чтения MediaInfo для {file_path}: {str(e)}", "ERROR")

    def add_exiftool_metadata(self, file_path):
        """Добавляет метаданные через ExifTool"""
        if not self.tool_manager.exiftool_available:
            self.current_metadata["ExifTool Error"] = "ExifTool не доступен"
            self.debug_logger.log("Попытка использовать недоступный ExifTool", "WARNING")
            return

        try:
            self.debug_logger.log(f"Чтение метаданных ExifTool для {file_path}")
            
            with exiftool.ExifTool() as et:
                metadata_json = et.execute("-j", file_path)
            
            if metadata_json:
                metadata_list = json.loads(metadata_json)
                if metadata_list:
                    metadata = metadata_list[0]  # Берем первый (и обычно единственный) результат
                    
                    for tag, value in metadata.items():
                        # Упрощаем имя тега
                        if ':' in tag:
                            display_tag = tag.split(':')[-1]
                        else:
                            display_tag = tag
                        
                        formatted_value = self.format_exiftool_value(value)
                        self.current_metadata[f"ExifTool {display_tag}"] = formatted_value
                    
                    self.debug_logger.log(f"Прочитано {len(metadata)} метаданных ExifTool из {file_path}")
                else:
                    self.current_metadata["ExifTool"] = "Метаданные не найдены"
                    self.debug_logger.log(f"ExifTool не нашел метаданных для {file_path}")
            else:
                self.current_metadata["ExifTool"] = "Метаданные не найдены"
                self.debug_logger.log(f"ExifTool не вернул данных для {file_path}")
                    
        except Exception as e:
            error_msg = f"Ошибка чтения ExifTool: {str(e)}"
            self.current_metadata["ExifTool Error"] = error_msg
            self.debug_logger.log(f"Ошибка чтения ExifTool для {file_path}: {str(e)}", "ERROR")

    # Методы форматирования значений
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

    def format_exiftool_value(self, value):
        """Форматирует значение ExifTool для лучшего отображения"""
        if value is None:
            return "None"
        
        if isinstance(value, list):
            if len(value) == 1:
                return self.format_exiftool_value(value[0])
            else:
                return ", ".join(str(self.format_exiftool_value(item)) for item in value)
        
        if isinstance(value, dict):
            try:
                return json.dumps(value, ensure_ascii=False, indent=2)
            except:
                return str(value)
        
        if isinstance(value, bytes):
            try:
                return value.decode('utf-8', errors='ignore')
            except:
                return str(value)
        
        if isinstance(value, (int, float)):
            return str(value)
        
        if isinstance(value, str):
            if len(value) > 1000:
                return f"[Бинарные данные, размер: {len(value)} байт]"
            
            if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
                return f"[Данные с непечатаемыми символами, размер: {len(value)} байт]"
        
        return str(value)

    def format_exif_value(self, tag, value):
        """Форматирует значение EXIF для лучшего отображения"""
        try:
            if isinstance(value, bytes):
                try:
                    return value.decode('utf-8').strip()
                except UnicodeDecodeError:
                    return str(value)
            
            # Специальное форматирование для определенных тегов
            if tag in ['EXIF ExposureTime', 'EXIF ShutterSpeedValue']:
                if hasattr(value, 'num') and hasattr(value, 'den'):
                    return f"{value.num}/{value.den} сек"
            
            if tag in ['EXIF FNumber', 'EXIF ApertureValue']:
                if hasattr(value, 'num') and hasattr(value, 'den'):
                    return f"f/{value.num/value.den:.1f}"
            
            if tag == 'EXIF FocalLength':
                if hasattr(value, 'num') and hasattr(value, 'den'):
                    return f"{value.num/value.den} мм"
            
            if tag == 'EXIF ISOSpeedRatings':
                return f"ISO {value}"
            
            return str(value)
            
        except Exception as e:
            self.debug_logger.log(f"Ошибка форматирования EXIF тега {tag}: {str(e)}", "WARNING")
            return str(value)

    def format_metadata_value(self, value):
        """Форматирует значение метаданных, убирая лишние символы"""
        if hasattr(value, '__class__'):
            class_name = value.__class__.__name__
            
            if class_name == 'TimeCode':
                try:
                    hours = value.hours
                    minutes = value.minutes
                    seconds = value.seconds
                    frame = value.frame
                    drop_frame = value.dropFrame
                    color_frame = value.colorFrame
                    field_phase = value.fieldPhase
                    
                    time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame:02d}"
                    return f"{time_str} (dropFrame: {drop_frame}, colorFrame: {color_frame}, fieldPhase: {field_phase})"
                except Exception as e:
                    str_repr = str(value)
                    
                    match = re.search(r'time:\s*([^,]+)', str_repr)
                    if match:
                        time_str = match.group(1).strip()
                        
                        drop_match = re.search(r'dropFrame:\s*(\d+)', str_repr)
                        drop_frame = drop_match.group(1) if drop_match else '?'
                        
                        color_match = re.search(r'colorFrame:\s*(\d+)', str_repr)
                        color_frame = color_match.group(1) if color_match else '?'
                        
                        field_match = re.search(r'fieldPhase:\s*(\d+)', str_repr)
                        field_phase = field_match.group(1) if field_match else '?'
                        
                        return f"{time_str} (dropFrame: {drop_frame}, colorFrame: {color_frame}, fieldPhase: {field_phase})"
                    return str_repr
            
            elif class_name in ['Box2i', 'Box2f']:
                try:
                    min_x = value.min.x
                    min_y = value.min.y
                    max_x = value.max.x
                    max_y = value.max.y
                    return f"({min_x}, {min_y}) - ({max_x}, {max_y})"
                except:
                    return str(value)
            
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
            
            elif class_name == 'Rational':
                try:
                    numerator = value.n
                    denominator = value.d
                    return f"{numerator}/{denominator}"
                except:
                    return str(value)
        
        if isinstance(value, bytes):
            try:
                decoded = value.decode('utf-8', errors='ignore').strip()
                
                if decoded.startswith("b'") and decoded.endswith("'"):
                    try:
                        return ast.literal_eval(decoded).decode('utf-8', errors='ignore')
                    except:
                        return decoded[2:-1]
                return decoded
            except:
                return str(value)
        
        elif isinstance(value, str):
            if value.startswith("b'") and value.endswith("'"):
                try:
                    return ast.literal_eval(value).decode('utf-8', errors='ignore')
                except:
                    return value[2:-1]
        
        return str(value)

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
    






class SequenceManager:
    """Менеджер для работы с последовательностями файлов"""
    
    def __init__(self, main_window, tool_manager):
        self.main_window = main_window
        self.tool_manager = tool_manager
        self.debug_logger = main_window.debug_logger
        
        # Данные последовательностей
        self.sequences = {}
        self.current_sequence_files = []
        
        # Поиск последовательностей
        self.sequence_finder = None

    def clear_sequences(self):
        """Очищает данные о последовательностях"""
        self.sequences.clear()
        self.current_sequence_files = []

    def start_search(self, folder):
        """Начинает поиск последовательностей в указанной папке"""
        if not folder or not os.path.exists(folder):
            return False
        
        self.debug_logger.log(f"=== НАЧАЛО ПОИСКА В ПАПКЕ: {folder} ===")
        
        # Останавливаем предыдущий поиск, если он активен
        self.stop_search()
        
        # Очищаем данные
        self.clear_sequences()
        
        # Создаем и запускаем поиск
        self.sequence_finder = SequenceFinder(folder, self.debug_logger)
        self.sequence_finder.sequence_found.connect(self.on_sequence_found)
        self.sequence_finder.progress_update.connect(self.update_progress)  # Это подключение должно быть
        self.sequence_finder.finished_signal.connect(self.on_search_finished)
        
        self.sequence_finder.start()
        return True

    def stop_search(self):
        """Останавливает поиск последовательностей"""
        if hasattr(self, 'sequence_finder') and self.sequence_finder and self.sequence_finder.isRunning():
            self.sequence_finder.stop()
            self.sequence_finder.wait(2000)
            try:
                self.sequence_finder.quit()
                self.sequence_finder.wait(1000)
            except:
                pass
            self.sequence_finder = None

    def continue_search(self):
        """Продолжает приостановленный поиск"""
        if hasattr(self, 'sequence_finder') and self.sequence_finder:
            self.sequence_finder.continue_search()
            self.sequence_finder.start()

    def on_sequence_found(self, sequence_data):
        """Обрабатывает найденную последовательность"""
        self.debug_logger.log(f"\n--- ПОЛУЧЕНА ПОСЛЕДОВАТЕЛЬНОСТЬ ---")
        self.debug_logger.log(f"Данные: {sequence_data}")
        
        # Обеспечиваем наличие всех необходимых ключей
        required_keys = ['path', 'name', 'frame_range', 'frame_count', 'files', 'extension', 'type']
        
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
            
        # Проверяем, что обязательные поля не пустые
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
        
        # Обновляем прогресс - показываем найденную последовательность
        display_name = sequence_data.get('display_name', sequence_data.get('name', 'Unknown'))
        self.update_progress(f"Найдена последовательность: {display_name}")
        
        # Добавляем в дерево через TreeManager
        if hasattr(self.main_window, 'tree_manager'):
            self.main_window.tree_manager.add_sequence_to_tree(sequence_data)
        
        self.debug_logger.log(f"--- КОНЕЦ ДОБАВЛЕНИЯ ПОСЛЕДОВАТЕЛЬНОСТИ ---\n")

    def on_search_finished(self):
        """Обрабатывает завершение поиска"""
        try:
            sequence_count = len(self.sequences)
            self.debug_logger.log(f"Поиск завершен. Найдено {sequence_count} последовательностей")
            
            # Уведомляем главное окно о завершении
            if hasattr(self.main_window, 'on_search_finished'):
                self.main_window.on_search_finished()
                
        except Exception as e:
            self.debug_logger.log(f"Ошибка при завершении поиска: {str(e)}", "ERROR")

    def update_progress(self, message):
        """Обновляет прогресс поиска"""
        # Передаем сообщение в UIManager для отображения
        if hasattr(self.main_window, 'ui_manager'):
            self.main_window.ui_manager.update_progress(message)

    def get_sequence_info(self, sequence_key):
        """Возвращает информацию о последовательности по ключу"""
        return self.sequences.get(sequence_key)

    def get_all_sequences(self):
        """Возвращает все последовательности"""
        return self.sequences

    def set_current_sequence_files(self, files):
        """Устанавливает текущие файлы последовательности"""
        self.current_sequence_files = files

    def get_current_sequence_files(self):
        """Возвращает текущие файлы последовательности"""
        return self.current_sequence_files

    def get_sequence_count(self):
        """Возвращает количество найденных последовательностей"""
        return len(self.sequences)
    



class ToolManager:
    """Менеджер для работы с внешними инструментами"""
    
    def __init__(self, main_window):
        self.main_window = main_window
        self.debug_logger = main_window.debug_logger
        
        # Доступность инструментов
        self.exiftool_available = False
        self.exiftool_check_completed = False
        
        # Проверяем доступность инструментов
        self.check_tools_availability()

    def check_tools_availability(self):
        """Проверяет доступность внешних инструментов"""
        self.check_exiftool_availability()
        # Здесь можно добавить проверки других инструментов

    def check_exiftool_availability(self):
        """Проверяет доступность exiftool в системе - синхронная версия"""
        try:
            if EXIFTOOL_AVAILABLE:
                with exiftool.ExifTool() as et:
                    version = et.execute("-ver")
                    if version and version.strip():
                        self.debug_logger.log(f"ExifTool доступен, версия: {version.strip()}")
                        self.exiftool_available = True
                    else:
                        self.debug_logger.log("ExifTool не вернул версию", "WARNING")
                        self.exiftool_available = False
            else:
                self.debug_logger.log("PyExifTool не установлен", "WARNING")
                self.exiftool_available = False
        except Exception as e:
            self.debug_logger.log(f"ExifTool недоступен: {str(e)}", "WARNING")
            self.exiftool_available = False
        
        self.exiftool_check_completed = True

    def is_tool_available(self, tool_name):
        """Проверяет доступность указанного инструмента"""
        if tool_name == 'exiftool':
            return self.exiftool_available
        elif tool_name == 'mediainfo':
            return PYMEDIAINFO_AVAILABLE
        elif tool_name == 'ffprobe':
            # FFprobe обычно доступен в системе
            try:
                result = subprocess.run(['ffprobe', '-version'], capture_output=True, text=True)
                return result.returncode == 0
            except:
                return False
        return False

    def get_available_tools(self):
        """Возвращает список доступных инструментов"""
        available_tools = {}
        
        for tool_key, tool_name in METADATA_TOOLS.items():
            if tool_key == 'mediainfo' and PYMEDIAINFO_AVAILABLE:
                available_tools[tool_key] = tool_name
            elif tool_key == 'ffprobe' and self.is_tool_available('ffprobe'):
                available_tools[tool_key] = tool_name
            elif tool_key == 'exiftool' and self.exiftool_available:
                available_tools[tool_key] = tool_name
        
        return available_tools

    def wait_for_exiftool_check(self, timeout=3):
        """Ожидает завершения проверки ExifTool"""
        if self.exiftool_check_completed:
            return True
            
        import time
        start_time = time.time()
        while not self.exiftool_check_completed and time.time() - start_time < timeout:
            time.sleep(0.1)
            QApplication.processEvents()
        
        return self.exiftool_check_completed
    


class UIManager:
    """Менеджер для работы с пользовательским интерфейсом"""
    
    def __init__(self, main_window):
        self.main_window = main_window
        self.debug_logger = main_window.debug_logger
        
        # Ссылки на UI элементы
        self.folder_path = None
        self.browse_btn = None
        self.start_btn = None
        self.stop_btn = None
        self.continue_btn = None
        self.settings_btn = None
        self.art_checkbox = None
        self.log_checkbox = None
        self.log_btn = None
        self.metadata_tool_combo = None
        self.camera_editor_btn = None
        self.progress_label = None
        self.sequences_search_input = None
        self.clear_sequences_search_btn = None

    def setup_ui(self, central_widget):
        """Настраивает пользовательский интерфейс"""
        layout = QVBoxLayout()
        
        # Создаем элементы управления
        self.setup_folder_controls(layout)
        self.setup_main_controls(layout)
        self.setup_splitter(layout)
        self.setup_progress_label(layout)
        
        central_widget.setLayout(layout)
        
        # Настраиваем начальное состояние кнопок
        self.stop_btn.setEnabled(False)
        self.continue_btn.setEnabled(False)

    def setup_folder_controls(self, layout):
        """Настраивает элементы управления папкой"""
        folder_layout = QHBoxLayout()
        
        self.folder_path = QLineEdit()
        self.browse_btn = QPushButton("Обзор")
        
        folder_layout.addWidget(QLabel("Папка:"))
        folder_layout.addWidget(self.folder_path)
        folder_layout.addWidget(self.browse_btn)
        
        layout.addLayout(folder_layout)

    def setup_main_controls(self, layout):
        """Настраивает основные элементы управления"""
        control_layout = QHBoxLayout()
        
        # Кнопки управления поиском
        self.start_btn = QPushButton("СТАРТ")
        self.stop_btn = QPushButton("СТОП")
        self.continue_btn = QPushButton("ПРОДОЛЖИТЬ")
        self.settings_btn = QPushButton("Настройки цветов")
        
        # Чекбоксы
        self.art_checkbox = QCheckBox("Читать Arri и RED")
        self.art_checkbox.setChecked(self.main_window.settings_manager.use_art_for_mxf)
        
        self.log_checkbox = QCheckBox("Логирование")
        self.log_checkbox.setChecked(DEBUG)
        
        # Кнопка лога
        self.log_btn = QPushButton("Лог")
        
        # Выбор инструмента метаданных
        self.metadata_tool_label = QLabel("Инструмент метаданных:")
        self.metadata_tool_combo = QComboBox()
        
        # Кнопка редактора камер
        self.camera_editor_btn = QPushButton("Редактор камер")
        
        # Добавляем элементы в layout
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.continue_btn)
        control_layout.addWidget(self.settings_btn)
        control_layout.addWidget(self.camera_editor_btn)
        control_layout.addWidget(self.art_checkbox)
        control_layout.addWidget(self.log_checkbox)
        control_layout.addWidget(self.log_btn)
        control_layout.addWidget(self.metadata_tool_label)
        control_layout.addWidget(self.metadata_tool_combo)
        control_layout.addStretch()
        
        layout.addLayout(control_layout)

    def setup_splitter(self, layout):
        """Настраивает разделитель с деревом и метаданными"""
        splitter = QSplitter(Qt.Vertical)
        
        # Создаем виджеты для разделителя
        sequences_widget = self.setup_sequences_widget()
        metadata_widget = self.setup_metadata_widget()
        
        splitter.addWidget(sequences_widget)
        splitter.addWidget(metadata_widget)
        splitter.setSizes([400, 400])
        
        layout.addWidget(splitter)

    def setup_sequences_widget(self):
        """Настраивает виджет последовательностей"""
        sequences_widget = QWidget()
        sequences_layout = QVBoxLayout()
        
        sequences_layout.addWidget(QLabel("Структура папок и последовательностей:"))
        
        # Создаем дерево последовательностей
        sequences_tree = QTreeWidget()
        sequences_tree.setColumnCount(5)
        sequences_tree.setHeaderLabels(["Имя", "Тип", "Диапазон", "Количество", "Путь"])
        
        # Настройка размеров столбцов
        sequences_tree.setColumnWidth(0, 500)
        sequences_tree.setColumnWidth(1, 200)
        sequences_tree.setColumnWidth(2, 200)
        sequences_tree.setColumnWidth(3, 100)
        sequences_tree.setColumnWidth(4, 400)
        
        sequences_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        sequences_tree.setSortingEnabled(True)
        sequences_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        
        sequences_layout.addWidget(sequences_tree)
        
        # Поиск по последовательностям
        sequences_search_layout = QHBoxLayout()
        sequences_search_layout.addWidget(QLabel("Поиск по последовательностям:"))
        
        self.sequences_search_input = QLineEdit()
        self.sequences_search_input.setPlaceholderText("Введите текст для поиска...")
        
        self.clear_sequences_search_btn = QPushButton("Очистить")
        
        sequences_search_layout.addWidget(self.sequences_search_input)
        sequences_search_layout.addWidget(self.clear_sequences_search_btn)
        
        sequences_layout.addLayout(sequences_search_layout)
        sequences_widget.setLayout(sequences_layout)
        
        # Сохраняем ссылку на дерево в главном окне
        self.main_window.sequences_tree = sequences_tree
        
        return sequences_widget

    def setup_metadata_widget(self):
        """Настраивает виджет метаданных"""
        metadata_widget = QWidget()
        metadata_layout = QVBoxLayout()
        
        # Метка источника метаданных
        metadata_source_label = QLabel("Метаданные выбранного элемента:")
        metadata_layout.addWidget(metadata_source_label)
        
        # Таблица метаданных
        metadata_table = QTableWidget()
        metadata_table.setColumnCount(2)
        metadata_table.setHorizontalHeaderLabels(["Поле", "Значение"])
        
        # Настройка размеров столбцов
        for i, width in enumerate(DEFAULT_COLUMN_WIDTHS['metadata']):
            metadata_table.setColumnWidth(i, width)
        
        # Настройка поведения заголовков
        metadata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        metadata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        metadata_table.setColumnWidth(0, DEFAULT_COLUMN_WIDTHS['metadata'][0])
        
        metadata_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        metadata_table.setContextMenuPolicy(Qt.CustomContextMenu)
        
        metadata_layout.addWidget(metadata_table)
        
        # Поиск по метаданным
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Поиск по метаданным:"))
        
        search_input = QLineEdit()
        search_input.setPlaceholderText("Введите текст для поиска...")
        
        clear_search_btn = QPushButton("Очистить")
        
        search_layout.addWidget(search_input)
        search_layout.addWidget(clear_search_btn)
        
        metadata_layout.addLayout(search_layout)
        metadata_widget.setLayout(metadata_layout)
        
        # Сохраняем ссылки на элементы в главном окне
        self.main_window.metadata_table = metadata_table
        self.main_window.metadata_source_label = metadata_source_label
        self.main_window.search_input = search_input
        self.main_window.clear_search_btn = clear_search_btn
        
        return metadata_widget

    def setup_progress_label(self, layout):
        """Настраивает метку прогресса"""
        self.progress_label = QLabel("Готов к работе")
        layout.addWidget(self.progress_label)

    def update_metadata_tool_combo(self):
        """Обновляет комбобокс выбора инструмента метаданных"""
        if not hasattr(self.main_window, 'tool_manager'):
            return
            
        try:
            current_text = self.metadata_tool_combo.currentText()
            current_data = self.metadata_tool_combo.currentData()
            
            self.metadata_tool_combo.clear()
            
            available_tools = self.main_window.tool_manager.get_available_tools()
            
            for tool_key, tool_name in available_tools.items():
                self.metadata_tool_combo.addItem(tool_name, tool_key)
            
            # Восстанавливаем предыдущий выбор
            restore_success = False
            if current_data in available_tools:
                self.metadata_tool_combo.setCurrentText(METADATA_TOOLS[current_data])
                restore_success = True
            elif self.main_window.settings_manager.default_metadata_tool in available_tools:
                self.metadata_tool_combo.setCurrentText(METADATA_TOOLS[self.main_window.settings_manager.default_metadata_tool])
                restore_success = True
            
            if not restore_success and available_tools:
                first_tool = list(available_tools.keys())[0]
                self.metadata_tool_combo.setCurrentText(available_tools[first_tool])
                self.main_window.settings_manager.default_metadata_tool = first_tool
            
            if self.metadata_tool_combo.count() == 0:
                self.metadata_tool_combo.addItem("Нет доступных инструментов", None)
                self.metadata_tool_combo.setEnabled(False)
            else:
                self.metadata_tool_combo.setEnabled(True)
                
        except Exception as e:
            self.debug_logger.log(f"Ошибка обновления UI инструментов: {str(e)}", "ERROR")

    def connect_signals(self):
        """Подключает сигналы к слотам главного окна"""
        # Простые сигналы, которые можно обработать локально
        self.browse_btn.clicked.connect(self.browse_folder)
        self.log_checkbox.stateChanged.connect(self.toggle_logging)
        self.art_checkbox.stateChanged.connect(self.toggle_art_usage)
        self.clear_sequences_search_btn.clicked.connect(self.clear_sequences_search)
        
        # Сложные сигналы, которые требуют координации менеджеров
        self.start_btn.clicked.connect(self.main_window.start_search)
        self.stop_btn.clicked.connect(self.main_window.stop_search)
        self.continue_btn.clicked.connect(self.main_window.continue_search)
        self.settings_btn.clicked.connect(self.main_window.open_settings)
        self.log_btn.clicked.connect(self.main_window.show_log)
        self.camera_editor_btn.clicked.connect(self.main_window.open_camera_editor)
        self.metadata_tool_combo.currentIndexChanged.connect(self.main_window.change_metadata_tool)
        
        # Сигналы поиска
        self.sequences_search_input.textChanged.connect(self.main_window.filter_sequences)
        self.main_window.search_input.textChanged.connect(self.main_window.filter_metadata)
        self.main_window.clear_search_btn.clicked.connect(self.main_window.clear_search)
        
        # Сигналы дерева
        self.main_window.sequences_tree.itemSelectionChanged.connect(self.main_window.on_tree_item_selected)
        self.main_window.sequences_tree.customContextMenuRequested.connect(self.main_window.show_tree_context_menu)
        
        # Сигналы таблицы метаданных
        self.main_window.metadata_table.customContextMenuRequested.connect(self.main_window.show_metadata_table_context_menu)

    def browse_folder(self):
        """Открывает диалог выбора папки"""
        folder = QFileDialog.getExistingDirectory(self.main_window, "Выберите папку с файлами")
        if folder:
            self.folder_path.setText(folder)

    def toggle_logging(self, state):
        """Включает/выключает логирование"""
        enabled = state == Qt.Checked
        self.debug_logger.set_debug_enabled(enabled)
        if enabled:
            self.debug_logger.log("Логирование включено")
        else:
            self.debug_logger.log("Логирование выключено")

    def toggle_art_usage(self, state):
        """Включает/выключает использование ART для MXF файлов"""
        self.main_window.settings_manager.use_art_for_mxf = state == Qt.Checked
        self.main_window.settings_manager.save_settings()
        if state == Qt.Checked:
            self.debug_logger.log("Включено чтение MXF через ART")
        else:
            self.debug_logger.log("Выключено чтение MXF через ART")

    def clear_sequences_search(self):
        """Очищает поле поиска последовательностей"""
        self.sequences_search_input.clear()
        if hasattr(self.main_window, 'tree_manager'):
            self.main_window.tree_manager.show_all_tree_items()

    def update_progress(self, message):
        """Обновляет метку прогресса"""
        if self.progress_label:
            self.progress_label.setText(message)

    def set_search_controls_state(self, searching):
        """Устанавливает состояние элементов управления поиском"""
        self.start_btn.setEnabled(not searching)
        self.stop_btn.setEnabled(searching)
        self.continue_btn.setEnabled(False)  # По умолчанию отключена

    def set_continue_enabled(self, enabled):
        """Включает/выключает кнопку продолжения"""
        self.continue_btn.setEnabled(enabled)






class EXRMetadataViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Инициализация отладчика
        self.debug_logger = DebugLogger(DEBUG)
        
        # Инициализация менеджеров
        self.settings_manager = SettingsManager(self)
        self.tool_manager = ToolManager(self)
        self.camera_manager = CameraManager(self, self.settings_manager)
        self.sequence_manager = SequenceManager(self, self.tool_manager)
        self.metadata_manager = MetadataManager(self, self.camera_manager, self.tool_manager)
        self.ui_manager = UIManager(self)
        
        # Инициализация UI
        self.setup_ui()
        
        # Инициализация TreeManager после создания UI
        self.tree_manager = TreeManager(self, self.sequence_manager)
        
        # Настройка менеджеров, требующих UI элементы
        self.setup_managers()
        
        # Подключение сигналов
        self.ui_manager.connect_signals()
        
        # Обновление UI инструментов
        QTimer.singleShot(100, self.ui_manager.update_metadata_tool_combo)

    def setup_ui(self):
        """Настраивает пользовательский интерфейс"""
        self.setWindowTitle("Universal File Sequence Metadata Viewer - Tree View")
        self.setGeometry(100, 100, 1200, 800)
        
        # Установка шрифта приложения
        app_font = QFont()
        app_font.setPointSize(DEFAULT_FONT_SIZE)
        app_font.setWeight(QFont.Bold)
        QApplication.setFont(app_font)
        
        # Создание центрального виджета
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Настройка UI через UIManager
        self.ui_manager.setup_ui(central_widget)

    def setup_managers(self):
        """Настраивает менеджеры, требующие UI элементы"""
        # Настройка TreeManager
        if hasattr(self, 'sequences_tree'):
            self.tree_manager.setup_ui(self.sequences_tree)
        
        # Настройка MetadataManager
        if hasattr(self, 'metadata_table') and hasattr(self, 'metadata_source_label') and hasattr(self, 'search_input'):
            self.metadata_manager.setup_ui(self.metadata_table, self.metadata_source_label, self.search_input)

    # Основные методы, перенесенные из оригинального класса
    # Эти методы теперь координируют работу менеджеров

    def start_search(self):
        """Начинает поиск последовательностей"""
        # ИСПРАВЛЕНИЕ: Получаем folder_path через ui_manager
        folder = self.ui_manager.folder_path.text()
        if not folder or not os.path.exists(folder):
            QMessageBox.warning(self, "Ошибка", "Укажите существующую папку")
            return
        
        # Очищаем дерево через TreeManager
        self.tree_manager.clear_tree()
        
        # Инициализируем корневой элемент
        self.tree_manager.initialize_root(folder)
        
        # Очищаем поиск
        self.clear_search()
        self.clear_sequences_search()
        
        # Обновляем UI
        self.ui_manager.update_progress("Начинаем поиск...")
        self.ui_manager.set_search_controls_state(True)
        
        # Запускаем поиск через SequenceManager
        if not self.sequence_manager.start_search(folder):
            QMessageBox.warning(self, "Ошибка", "Не удалось начать поиск")
            return

    def stop_search(self):
        """Останавливает поиск последовательностей"""
        self.sequence_manager.stop_search()
        self.ui_manager.set_search_controls_state(False)
        self.ui_manager.set_continue_enabled(True)
        self.ui_manager.update_progress("Поиск приостановлен")

    def continue_search(self):
        """Продолжает приостановленный поиск"""
        self.sequence_manager.continue_search()
        self.ui_manager.set_search_controls_state(True)
        self.ui_manager.set_continue_enabled(False)
        self.ui_manager.update_progress("Продолжение поиска...")

    def on_search_finished(self):
        """Обрабатывает завершение поиска"""
        try:
            sequence_count = self.sequence_manager.get_sequence_count()
            folder_count = len(self.tree_manager.folder_items)
            
            self.ui_manager.update_progress(f"Поиск завершен. Найдено {sequence_count} последовательностей в {folder_count} папках")
            self.debug_logger.log(f"Поиск завершен. Найдено {sequence_count} последовательностей в {folder_count} папках")
            
            # Раскрываем все элементы дерева
            self.tree_manager.expand_all_tree_items()
            
            # Очищаем поиск
            self.clear_sequences_search()
            
        except Exception as e:
            self.debug_logger.log(f"Ошибка при завершении поиска: {str(e)}", "ERROR")
            self.ui_manager.update_progress(f"Ошибка при завершении поиска: {str(e)}")
        
        self.ui_manager.set_search_controls_state(False)
        self.ui_manager.set_continue_enabled(False)

    def on_tree_item_selected(self):
        """Обрабатывает выбор элемента в дереве"""
        item_data = self.tree_manager.get_selected_item_data()
        
        if not item_data:
            return
            
        if item_data['type'] == 'sequence':
            # Обрабатываем выбор последовательности
            seq_info = item_data['info']
            self.sequence_manager.set_current_sequence_files(seq_info['files'])
            extension = seq_info['extension']
            
            if self.sequence_manager.current_sequence_files:
                current_file = self.sequence_manager.current_sequence_files[0]
                
                # Сбрасываем принудительные настройки, если файл изменился
                if self.metadata_manager.forced_metadata_file != current_file:
                    self.metadata_manager.forced_metadata_tool = None
                    self.metadata_manager.forced_metadata_file = None
                
                # Отображаем метаданные
                if self.metadata_manager.forced_metadata_tool and self.metadata_manager.forced_metadata_file == current_file:
                    self.metadata_manager.display_metadata(current_file, extension, forced_tool=self.metadata_manager.forced_metadata_tool)
                else:
                    self.metadata_manager.display_metadata(current_file, extension)
        else:
            # Обрабатываем выбор папки - очищаем метаданные
            self.metadata_table.setRowCount(0)
            self.sequence_manager.set_current_sequence_files([])
            self.metadata_manager.current_metadata = {}
            self.metadata_manager.forced_metadata_tool = None
            self.metadata_manager.forced_metadata_file = None
            self.metadata_source_label.setText("Метаданные выбранного элемента:")

    def show_tree_context_menu(self, position):
        """Показывает контекстное меню для дерева"""
        self.tool_manager.wait_for_exiftool_check()
        
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
            expand_all_action.triggered.connect(lambda: self.tree_manager.expand_folder_recursive(item))
            collapse_all_action.triggered.connect(lambda: self.tree_manager.collapse_folder_recursive(item))
        else:
            seq_info = item_data['info']
            open_action = menu.addAction("Открыть в проводнике")
            open_action.triggered.connect(lambda: self.open_in_explorer(seq_info['path']))
            
            menu.addSeparator()
            
            if len(seq_info['files']) > 0:
                file_path = seq_info['files'][0]
                extension = seq_info['extension'].lower()
                
                mediainfo_action = menu.addAction("Читать принудительно mediainfo")
                ffprobe_action = menu.addAction("Читать принудительно ffprobe")
                exiftool_action = menu.addAction("Читать принудительно ExifTool")
                
                if self.tool_manager.exiftool_available:
                    exiftool_action.triggered.connect(lambda: self.metadata_manager.force_read_metadata(file_path, extension, 'exiftool'))
                else:
                    exiftool_action.setEnabled(False)
                    exiftool_action.setToolTip(f"ExifTool недоступен. Проверка завершена: {self.tool_manager.exiftool_check_completed}")
                
                mediainfo_action.triggered.connect(lambda: self.metadata_manager.force_read_metadata(file_path, extension, 'mediainfo'))
                ffprobe_action.triggered.connect(lambda: self.metadata_manager.force_read_metadata(file_path, extension, 'ffprobe'))
                
                menu.addSeparator()
            
            color_action = menu.addAction(f"Изменить цвет для '{seq_info['type']}'")
            color_action.triggered.connect(lambda: self.change_sequence_color(seq_info['type']))
        
        menu.exec_(self.sequences_tree.viewport().mapToGlobal(position))

    def show_metadata_table_context_menu(self, position):
        """Показывает контекстное меню для таблицы метаданных"""
        index = self.metadata_table.indexAt(position)
        selected_rows = self.metadata_table.selectionModel().selectedRows()
        
        menu = QMenu(self)
        
        if selected_rows:
            copy_selected_values_action = menu.addAction("Копировать выделенное: значения")
            copy_selected_both_action = menu.addAction("Копировать выделенное: поля и значения")
            
            copy_selected_values_action.triggered.connect(self.copy_selected_values)
            copy_selected_both_action.triggered.connect(self.copy_selected_fields_and_values)
            
            menu.addSeparator()
        
        if index.isValid():
            row = index.row()
            column = index.column()
            
            field_name_item = self.metadata_table.item(row, 0)
            value_item = self.metadata_table.item(row, 1)
            
            if field_name_item and value_item:
                field_name = field_name_item.text()
                field_value = value_item.text()
                
                if column == 0:
                    copy_name_action = menu.addAction("Копировать имя поля")
                    copy_name_action.triggered.connect(lambda: self.copy_field_name(field_name))
                    
                    menu.addSeparator()
                    
                    if field_name in self.settings_manager.color_metadata and not self.settings_manager.color_metadata[field_name].get('removed', False):
                        color_action = menu.addAction("Изменить цвет")
                        remove_action = menu.addAction("Удалить из списка")
                        
                        color_action.triggered.connect(lambda: self.change_field_color(field_name))
                        remove_action.triggered.connect(lambda: self.remove_field_from_colors(field_name))
                    else:
                        color_action = menu.addAction("Задать цвет")
                        color_action.triggered.connect(lambda: self.add_field_with_color(field_name))
                    
                    menu.addSeparator()

                    set_camera_action = menu.addAction("Задать камеру для этого поля")
                    set_resolution_action = menu.addAction("Задать разрешение для этого поля")

                    set_camera_action.triggered.connect(lambda: self.set_camera_rule(field_name, field_value))
                    set_resolution_action.triggered.connect(lambda: self.set_resolution_rule(field_name, field_value))

                elif column == 1:
                    copy_value_action = menu.addAction("Копировать значение")
                    copy_value_action.triggered.connect(lambda: self.copy_field_value(field_value))
                    
                    copy_both_action = menu.addAction("Копировать имя и значение")
                    copy_both_action.triggered.connect(lambda: self.copy_field_name_and_value(field_name, field_value))
        
        menu.exec_(self.metadata_table.viewport().mapToGlobal(position))

    def filter_sequences(self):
        """Фильтрует дерево последовательностей"""
        search_text = self.ui_manager.sequences_search_input.text()
        self.tree_manager.filter_sequences(search_text)

    def filter_metadata(self):
        """Фильтрует таблицу метаданных"""
        search_text = self.search_input.text()
        self.metadata_manager.filter_metadata(search_text)

    def clear_search(self):
        """Очищает поиск по метаданным"""
        self.metadata_manager.clear_search()

    def clear_sequences_search(self):
        """Очищает поиск по последовательностям"""
        self.ui_manager.clear_sequences_search()

    def change_metadata_tool(self, index):
        """Изменяет инструмент для чтения метаданных"""
        tool_key = self.ui_manager.metadata_tool_combo.currentData()
        
        if tool_key is None or tool_key not in METADATA_TOOLS:
            self.debug_logger.log(f"Предупреждение: неверный ключ инструмента: {tool_key}", "WARNING")
            return
        
        self.settings_manager.default_metadata_tool = tool_key
        self.settings_manager.save_settings()
        self.debug_logger.log(f"Изменен инструмент метаданных на: {METADATA_TOOLS[tool_key]}")

    def open_settings(self):
        """Открывает диалог настроек цветов"""
        dialog = SettingsDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            # Обновляем цвета через менеджеры
            if hasattr(self, 'tree_manager'):
                self.tree_manager.update_sequences_colors()
            if hasattr(self, 'metadata_manager') and hasattr(self.metadata_manager, 'update_metadata_colors'):
                self.metadata_manager.update_metadata_colors()

    def open_camera_editor(self):
        """Открывает редактор камер"""
        if not self.camera_manager.camera_data.get('cameras'):
            reply = QMessageBox.information(self, "База камер пуста", 
                                        "База данных камер пуста. Хотите добавить первую камеру?",
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                dialog = CameraEditorDialog(self)
                if dialog.exec_() == QDialog.Accepted:
                    self.camera_manager.load_camera_data()
        else:
            dialog = CameraEditorDialog(self)
            dialog.exec_()

    def show_log(self):
        """Безопасно показывает диалог с логами"""
        try:
            # Проверяем, не открыт ли уже диалог логов
            if hasattr(self, 'log_dialog') and self.log_dialog:
                try:
                    self.log_dialog.raise_()
                    self.log_dialog.activateWindow()
                    return
                except:
                    # Если диалог был удален, создаем новый
                    pass
            
            # Создаем немодальный диалог с отложенной инициализацией
            QTimer.singleShot(100, lambda: self._create_log_dialog())
            
        except Exception as e:
            print(f"Error showing log: {e}")

    def _create_log_dialog(self):
        """Создает диалог лога с защитой от ошибок"""
        try:
            self.log_dialog = LogViewerDialog(self.debug_logger, self)
            self.log_dialog.setAttribute(Qt.WA_DeleteOnClose)
            
            # Подключаем сигнал закрытия диалога для очистки ссылки
            self.log_dialog.destroyed.connect(lambda: setattr(self, 'log_dialog', None))
            
            self.log_dialog.show()
        except Exception as e:
            print(f"Error creating log dialog: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть окно логов: {str(e)}")

    # Методы работы с буфером обмена (оставлены в главном классе для простоты)
    def copy_selected_values(self):
        """Копирует значения выделенных строк в буфер обмена"""
        selected_indexes = self.metadata_table.selectionModel().selectedIndexes()
        if not selected_indexes:
            return
        
        rows_values = {}
        for index in selected_indexes:
            if index.column() == 1:
                value_item = self.metadata_table.item(index.row(), 1)
                if value_item:
                    rows_values[index.row()] = value_item.text()
        
        if rows_values:
            values = [rows_values[row] for row in sorted(rows_values.keys())]
            clipboard = QApplication.clipboard()
            clipboard.setText("\n".join(values))
            self.show_toast(f"Скопировано {len(values)} значений")

    def copy_selected_fields_and_values(self):
        """Копирует поля и значения выделенных строк в буфер обмена"""
        selected_indexes = self.metadata_table.selectionModel().selectedIndexes()
        if not selected_indexes:
            return
        
        rows_data = {}
        for index in selected_indexes:
            row = index.row()
            if row not in rows_data:
                field_item = self.metadata_table.item(row, 0)
                value_item = self.metadata_table.item(row, 1)
                if field_item and value_item:
                    rows_data[row] = f"{field_item.text()}: {value_item.text()}"
        
        if rows_data:
            fields_and_values = [rows_data[row] for row in sorted(rows_data.keys())]
            clipboard = QApplication.clipboard()
            clipboard.setText("\n".join(fields_and_values))
            self.show_toast(f"Скопировано {len(fields_and_values)} полей и значений")

    def copy_field_name(self, field_name):
        """Копирует имя поля в буфер обмена"""
        clipboard = QApplication.clipboard()
        clipboard.setText(field_name)
        self.show_toast("Имя поля скопировано")

    def copy_field_value(self, field_value):
        """Копирует значение поля в буфер обмена"""
        clipboard = QApplication.clipboard()
        clipboard.setText(field_value)
        self.show_toast("Значение поля скопировано")

    def copy_field_name_and_value(self, field_name, field_value):
        """Копирует имя и значение поля в буфер обмена"""
        clipboard = QApplication.clipboard()
        clipboard.setText(f"{field_name}: {field_value}")
        self.show_toast("Имя и значение поля скопированы")

    def add_field_with_color(self, field_name):
        """Добавляет поле с выбранным цветом"""
        color = QColorDialog.getColor(QColor(200, 200, 255), self, f"Выберите цвет для поля '{field_name}'")
        if color.isValid():
            self.settings_manager.add_field_with_color(field_name, color)
            # ЗАМЕНИТЬ display_metadata на update_metadata_colors
            self.metadata_manager.update_metadata_colors()
            QMessageBox.information(self, "Успех", f"Поле '{field_name}' добавлено с выбранным цветом")

    def change_field_color(self, field_name):
        """Изменяет цвет поля"""
        if field_name in self.settings_manager.color_metadata:
            current_color_data = self.settings_manager.color_metadata[field_name]
            current_color = QColor(current_color_data['r'], current_color_data['g'], current_color_data['b'])
            
            color = QColorDialog.getColor(current_color, self, f"Выберите цвет для поля '{field_name}'")
            if color.isValid():
                self.settings_manager.change_field_color(field_name, color)
                # ЗАМЕНИТЬ display_metadata на update_metadata_colors
                self.metadata_manager.update_metadata_colors()

    def remove_field_from_colors(self, field_name):
        """Удаляет поле из цветных в корзину"""
        self.settings_manager.remove_field_from_colors(field_name)
        # ЗАМЕНИТЬ display_metadata на update_metadata_colors
        self.metadata_manager.update_metadata_colors()
        QMessageBox.information(self, "Успех", f"Поле '{field_name}' перемещено в корзину")

    def change_sequence_color(self, seq_type):
        """Изменяет цвет типа последовательности"""
        current_color_data = self.settings_manager.sequence_colors.get(seq_type)
        current_color = QColor(200, 200, 255)
        
        if current_color_data and isinstance(current_color_data, dict) and 'r' in current_color_data and 'g' in current_color_data and 'b' in current_color_data:
            current_color = QColor(current_color_data['r'], current_color_data['g'], current_color_data['b'])
        
        color = QColorDialog.getColor(current_color, self, f"Выберите цвет для типа '{seq_type}'")
        if color.isValid():
            self.settings_manager.change_sequence_color(seq_type, color)
            self.tree_manager.update_sequences_colors()

    def set_camera_rule(self, field, value):
        """Добавляет правило для камеры"""
        cameras = list(self.camera_manager.camera_data.get('cameras', {}).keys())
        if not cameras:
            QMessageBox.warning(self, "Ошибка", 
                            "Нет доступных камер. Сначала добавьте камеры в редакторе камер.")
            return
        
        existing_rules = self.settings_manager.camera_detection_settings.get('camera_rules', [])
        for rule in existing_rules:
            if rule.get('field') == field and rule.get('value') == value:
                QMessageBox.information(self, "Информация", "Такое правило уже существует")
                return
        
        camera, ok = QInputDialog.getItem(self, "Выбор камеры", "Выберите камеру:", cameras, 0, False)
        if ok and camera:
            self.camera_manager.add_camera_rule(field, value, camera)
            QMessageBox.information(self, "Успех", f"Правило добавлено: {field} = {value} → {camera}")
            self.metadata_manager.display_metadata(
                self.sequence_manager.current_sequence_files[0] if self.sequence_manager.current_sequence_files else "",
                ""
            )

    def set_resolution_rule(self, field, value):
        """Добавляет правило для разрешения"""
        rule_types = ["range", "single_w", "single_h", "combined"]
        rule_type, ok = QInputDialog.getItem(self, "Тип правила", "Выберите тип правила:", rule_types, 0, False)
        if ok and rule_type:
            existing_rules = self.settings_manager.camera_detection_settings.get('resolution_rules', [])
            for rule in existing_rules:
                if rule.get('field') == field and rule.get('type') == rule_type:
                    QMessageBox.information(self, "Информация", "Такое правило уже существует")
                    return
            
            self.camera_manager.add_resolution_rule(field, rule_type)
            QMessageBox.information(self, "Успех", "Правило для разрешения добавлено")
            self.metadata_manager.display_metadata(
                self.sequence_manager.current_sequence_files[0] if self.sequence_manager.current_sequence_files else "",
                ""
            )

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

    def show_toast(self, message, duration=2000, opacity=0.5):
        """Показывает toast сообщение"""
        toast = ToastMessage(message, self, duration, opacity)
        toast.show_toast()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Установка шрифта приложения
    app_font = QFont()
    app_font.setPointSize(DEFAULT_FONT_SIZE)
    app_font.setWeight(QFont.Bold)
    app.setFont(app_font)
    
    # Создание и отображение главного окна
    window = EXRMetadataViewer()
    window.show()
    sys.exit(app.exec_())


    
#f