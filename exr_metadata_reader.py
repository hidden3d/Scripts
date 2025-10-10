import os
import sys
import json
import re
from pathlib import Path
from collections import defaultdict
import ast

import OpenEXR
import Imath
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QLineEdit, QPushButton, QListWidget, 
                             QTextEdit, QLabel, QFileDialog, QMessageBox,
                             QListWidgetItem, QColorDialog, QDialog, QDialogButtonBox,
                             QFormLayout, QComboBox, QTableWidget, QTableWidgetItem,
                             QHeaderView, QAbstractItemView, QMenu, QAction)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QTextCursor, QColor, QTextCharFormat, QFont, QBrush


class SequenceFinder(QThread):
    sequence_found = pyqtSignal(dict)  # Изменяем сигнал для передачи словаря с данными
    progress_update = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, directory):
        super().__init__()
        self.directory = directory
        self._is_running = True

    def stop(self):
        self._is_running = False

    def continue_search(self):
        self._is_running = True

    def find_sequences_in_directory(self, directory):
        """Находит последовательности EXR файлов в конкретной директории"""
        exr_files = {}
        
        try:
            files = os.listdir(directory)
        except PermissionError:
            return {}
            
        for file in files:
            if not self._is_running:
                break
                
            file_path = os.path.join(directory, file)
            if os.path.isfile(file_path) and file.lower().endswith('.exr'):
                self.progress_update.emit(f"Обработка: {file}")
                
                # Извлекаем базовое имя и номер кадра
                base_name, frame_num = self.extract_sequence_info(file)
                if base_name and frame_num is not None:
                    if base_name not in exr_files:
                        exr_files[base_name] = []
                    exr_files[base_name].append((frame_num, file_path))
        
        return exr_files

    def find_sequences_recursive(self, directory):
        """Рекурсивно ищет последовательности EXR файлов во всех подпапках"""
        all_sequences = {}
        
        # Сначала ищем в текущей директории
        exr_files = self.find_sequences_in_directory(directory)
        
        # Формируем последовательности для текущей папки
        sequences = self.form_sequences(exr_files, directory)
        all_sequences.update(sequences)
        
        # Эмитируем найденные последовательности сразу
        for seq_name, seq_info in sequences.items():
            if not self._is_running:
                break
            
            # Формируем данные для таблицы
            sequence_data = {
                'path': seq_info['path'],
                'name': seq_name,
                'frame_range': seq_info['frame_range'],
                'frame_count': len(seq_info['files']),
                'files': seq_info['files']
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

    def form_sequences(self, exr_files, directory):
        """Формирует последовательности из найденных EXR файлов"""
        sequences = {}
        for base_name, files in exr_files.items():
            if len(files) > 1:  # Только если есть несколько кадров
                files.sort(key=lambda x: x[0])
                frame_numbers = [f[0] for f in files]
                file_paths = [f[1] for f in files]
                
                # Проверяем, является ли это последовательностью (последовательные номера)
                if self.is_sequence(frame_numbers):
                    rel_path = os.path.relpath(directory, self.directory)
                    if rel_path == '.':
                        display_name = base_name
                    else:
                        display_name = f"{rel_path}/{base_name}"
                    
                    sequences[display_name] = {
                        'files': file_paths,
                        'frames': frame_numbers,
                        'first_file': file_paths[0],
                        'frame_range': f"{min(frame_numbers)}-{max(frame_numbers)}",
                        'path': directory
                    }
        
        return sequences

    def extract_sequence_info(self, filename):
        """Извлекает базовое имя и номер кадра из имени файла"""
        # Убираем расширение
        name_without_ext = os.path.splitext(filename)[0]
        
        # Ищем паттерны для номеров кадров
        patterns = [
            r'(.+?)\.(\d+)$',  # name.0001
            r'(.+?)_(\d+)$',   # name_0001
            r'(.+?)-(\d+)$',   # name-0001
        ]
        
        for pattern in patterns:
            match = re.match(pattern, name_without_ext)
            if match:
                base_name = match.group(1)
                try:
                    frame_num = int(match.group(2))
                    return base_name, frame_num
                except ValueError:
                    continue
        
        # Если не нашли паттерн с числами, проверяем есть ли числа в имени
        match = re.search(r'(.+?)(\d+)\.?.*$', name_without_ext)
        if match:
            base_name = match.group(1).rstrip('._-')
            try:
                frame_num = int(match.group(2))
                return base_name, frame_num
            except ValueError:
                pass
        
        return filename, None

    def is_sequence(self, frame_numbers):
        """Проверяет, являются ли номера кадров последовательными"""
        if len(frame_numbers) < 2:
            return False
        
        sorted_frames = sorted(frame_numbers)
        
        # Проверяем, что разница между кадрами постоянная
        differences = [sorted_frames[i] - sorted_frames[i-1] for i in range(1, len(sorted_frames))]
        unique_differences = set(differences)
        
        # Допускаем последовательности с постоянным шагом (1, 2, 10 и т.д.)
        return len(unique_differences) == 1

    def run(self):
        self.find_sequences_recursive(self.directory)
        self.finished_signal.emit()


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Управление цветами метаданных")
        self.setGeometry(200, 200, 600, 500)
        
        layout = QVBoxLayout()
        
        # Выбор цвета и добавление поля
        form_layout = QFormLayout()
        
        self.field_input = QLineEdit()
        self.color_combo = QComboBox()
        self.color_combo.addItems(["Красный", "Зеленый", "Синий", "Желтый"])
        
        self.add_button = QPushButton("Добавить поле")
        self.add_button.clicked.connect(self.add_field)
        
        form_layout.addRow("Поле метаданных:", self.field_input)
        form_layout.addRow("Цвет:", self.color_combo)
        form_layout.addRow("", self.add_button)
        
        # Списки полей по цветам
        lists_layout = QHBoxLayout()
        
        red_layout = QVBoxLayout()
        red_layout.addWidget(QLabel("Красный"))
        self.red_list = QListWidget()
        red_layout.addWidget(self.red_list)
        
        green_layout = QVBoxLayout()
        green_layout.addWidget(QLabel("Зеленый"))
        self.green_list = QListWidget()
        green_layout.addWidget(self.green_list)
        
        blue_layout = QVBoxLayout()
        blue_layout.addWidget(QLabel("Синий"))
        self.blue_list = QListWidget()
        blue_layout.addWidget(self.blue_list)
        
        yellow_layout = QVBoxLayout()
        yellow_layout.addWidget(QLabel("Желтый"))
        self.yellow_list = QListWidget()
        yellow_layout.addWidget(self.yellow_list)
        
        lists_layout.addLayout(red_layout)
        lists_layout.addLayout(green_layout)
        lists_layout.addLayout(blue_layout)
        lists_layout.addLayout(yellow_layout)
        
        # Кнопки удаления
        delete_layout = QHBoxLayout()
        self.delete_red_btn = QPushButton("Удалить выбранное (Красный)")
        self.delete_green_btn = QPushButton("Удалить выбранное (Зеленый)")
        self.delete_blue_btn = QPushButton("Удалить выбранное (Синий)")
        self.delete_yellow_btn = QPushButton("Удалить выбранное (Желтый)")
        
        self.delete_red_btn.clicked.connect(lambda: self.delete_selected('red', self.red_list))
        self.delete_green_btn.clicked.connect(lambda: self.delete_selected('green', self.green_list))
        self.delete_blue_btn.clicked.connect(lambda: self.delete_selected('blue', self.blue_list))
        self.delete_yellow_btn.clicked.connect(lambda: self.delete_selected('yellow', self.yellow_list))
        
        delete_layout.addWidget(self.delete_red_btn)
        delete_layout.addWidget(self.delete_green_btn)
        delete_layout.addWidget(self.delete_blue_btn)
        delete_layout.addWidget(self.delete_yellow_btn)
        
        # Кнопки диалога
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout.addLayout(form_layout)
        layout.addLayout(lists_layout)
        layout.addLayout(delete_layout)
        layout.addWidget(button_box)
        
        self.setLayout(layout)
        self.load_current_settings()

    def load_current_settings(self):
        """Загружает текущие настройки из родительского окна"""
        self.red_list.clear()
        self.green_list.clear()
        self.blue_list.clear()
        self.yellow_list.clear()
        
        for field in self.parent.color_metadata['red']:
            self.red_list.addItem(field)
        for field in self.parent.color_metadata['green']:
            self.green_list.addItem(field)
        for field in self.parent.color_metadata['blue']:
            self.blue_list.addItem(field)
        for field in self.parent.color_metadata['yellow']:
            self.yellow_list.addItem(field)

    def add_field(self):
        field_name = self.field_input.text().strip()
        if not field_name:
            QMessageBox.warning(self, "Ошибка", "Введите название поля")
            return
        
        color_map = {
            "Красный": 'red',
            "Зеленый": 'green',
            "Синий": 'blue',
            "Желтый": 'yellow'
        }
        
        selected_color = self.color_combo.currentText()
        color_key = color_map[selected_color]
        
        # Проверяем, нет ли уже такого поля
        if field_name in self.parent.color_metadata[color_key]:
            QMessageBox.warning(self, "Ошибка", "Это поле уже добавлено")
            return
        
        # Добавляем поле в список
        self.parent.color_metadata[color_key].append(field_name)
        
        # Сохраняем настройки
        self.parent.save_settings()
        
        # Обновляем интерфейс
        self.load_current_settings()
        
        # Обновляем отображение метаданных
        self.parent.update_metadata_colors()
        
        self.field_input.clear()

    def delete_selected(self, color_key, list_widget):
        current_row = list_widget.currentRow()
        if current_row >= 0:
            field_name = list_widget.item(current_row).text()
            
            # Удаляем поле из настроек
            if field_name in self.parent.color_metadata[color_key]:
                self.parent.color_metadata[color_key].remove(field_name)
                
                # Сохраняем настройки
                self.parent.save_settings()
                
                # Обновляем интерфейс
                self.load_current_settings()
                
                # Обновляем отображение метаданных
                self.parent.update_metadata_colors()

    def get_settings(self):
        """Возвращает настройки цветов"""
        return self.parent.color_metadata.copy()


class EXRMetadataViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.sequences = {}  # Теперь будем хранить по ключу - путь + имя
        self.current_sequence_files = []
        self.current_metadata = {}
        self.color_metadata = {
            'red': [],
            'green': [],
            'blue': [],
            'yellow': []
        }
        self.settings_file = "exr_viewer_settings.json"
        self.load_settings()
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("EXR Sequence Metadata Viewer")
        self.setGeometry(100, 100, 1200, 800)
        
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
        
        self.start_btn.clicked.connect(self.start_search)
        self.stop_btn.clicked.connect(self.stop_search)
        self.continue_btn.clicked.connect(self.continue_search)
        self.settings_btn.clicked.connect(self.open_settings)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.continue_btn)
        control_layout.addWidget(self.settings_btn)
        control_layout.addStretch()
        
        # Таблица последовательностей
        layout.addWidget(QLabel("Найденные последовательности:"))
        self.sequences_table = QTableWidget()
        self.sequences_table.setColumnCount(4)
        self.sequences_table.setHorizontalHeaderLabels(["Путь", "Имя последовательности", "Диапазон", "Количество кадров"])
        self.sequences_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.sequences_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.sequences_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.sequences_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.sequences_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sequences_table.setSortingEnabled(True)  # Включаем сортировку
        self.sequences_table.itemSelectionChanged.connect(self.on_sequence_selected)
        
        # Поле прогресса
        self.progress_label = QLabel("Готов к работе")
        
        # Таблица метаданных
        layout.addWidget(QLabel("Метаданные выбранной последовательности:"))
        self.metadata_table = QTableWidget()
        self.metadata_table.setColumnCount(2)
        self.metadata_table.setHorizontalHeaderLabels(["Поле", "Значение"])
        self.metadata_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.metadata_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.metadata_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.metadata_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.metadata_table.customContextMenuRequested.connect(self.show_table_context_menu)
        
        layout.addLayout(folder_layout)
        layout.addLayout(control_layout)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.sequences_table)
        layout.addWidget(self.metadata_table)
        
        central_widget.setLayout(layout)
        
        # Изначально кнопки Стоп и Продолжить неактивны
        self.stop_btn.setEnabled(False)
        self.continue_btn.setEnabled(False)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с EXR файлами")
        if folder:
            self.folder_path.setText(folder)

    def start_search(self):
        folder = self.folder_path.text()
        if not folder or not os.path.exists(folder):
            QMessageBox.warning(self, "Ошибка", "Укажите существующую папку")
            return
        
        self.sequences_table.setRowCount(0)
        self.metadata_table.setRowCount(0)
        self.sequences = {}
        self.current_sequence_files = []
        
        self.sequence_finder = SequenceFinder(folder)
        self.sequence_finder.sequence_found.connect(self.on_sequence_found)
        self.sequence_finder.progress_update.connect(self.update_progress)
        self.sequence_finder.finished_signal.connect(self.on_search_finished)
        
        self.sequence_finder.start()
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.continue_btn.setEnabled(False)

    def stop_search(self):
        if hasattr(self, 'sequence_finder'):
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
        """Добавляет найденную последовательность в таблицу"""
        row = self.sequences_table.rowCount()
        self.sequences_table.insertRow(row)
        
        # Путь
        path_item = QTableWidgetItem(sequence_data['path'])
        path_item.setFlags(path_item.flags() & ~Qt.ItemIsEditable)
        self.sequences_table.setItem(row, 0, path_item)
        
        # Имя последовательности
        name_item = QTableWidgetItem(sequence_data['name'])
        name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
        self.sequences_table.setItem(row, 1, name_item)
        
        # Диапазон
        range_item = QTableWidgetItem(sequence_data['frame_range'])
        range_item.setFlags(range_item.flags() & ~Qt.ItemIsEditable)
        self.sequences_table.setItem(row, 2, range_item)
        
        # Количество кадров
        count_item = QTableWidgetItem(str(sequence_data['frame_count']))
        count_item.setFlags(count_item.flags() & ~Qt.ItemIsEditable)
        self.sequences_table.setItem(row, 3, count_item)
        
        # Сохраняем файлы последовательности для доступа при выборе
        key = f"{sequence_data['path']}/{sequence_data['name']}"
        self.sequences[key] = sequence_data['files']

    def update_progress(self, message):
        self.progress_label.setText(message)

    def on_search_finished(self):
        self.progress_label.setText("Поиск завершен")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.continue_btn.setEnabled(False)

    def on_sequence_selected(self):
        current_row = self.sequences_table.currentRow()
        if current_row < 0:
            return
        
        # Получаем данные из выбранной строки
        path = self.sequences_table.item(current_row, 0).text()
        name = self.sequences_table.item(current_row, 1).text()
        
        key = f"{path}/{name}"
        if key in self.sequences:
            self.current_sequence_files = self.sequences[key]
            if self.current_sequence_files:
                self.display_metadata(self.current_sequence_files[0])

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

    def display_metadata(self, file_path):
        try:
            if not os.path.exists(file_path):
                self.metadata_table.setRowCount(1)
                self.metadata_table.setItem(0, 0, QTableWidgetItem("Ошибка"))
                self.metadata_table.setItem(0, 1, QTableWidgetItem(f"Файл не найден: {file_path}"))
                return
            
            exr_file = OpenEXR.InputFile(file_path)
            header = exr_file.header()
            
            # Собираем все метаданные
            self.current_metadata = {}
            for key, value in header.items():
                self.current_metadata[key] = self.format_metadata_value(value)
            
            # Разделяем метаданные на цветные и обычные
            colored_metadata = {}
            normal_metadata = {}
            
            for key, value in self.current_metadata.items():
                if (key in self.color_metadata['red'] or 
                    key in self.color_metadata['green'] or 
                    key in self.color_metadata['blue'] or 
                    key in self.color_metadata['yellow']):
                    colored_metadata[key] = value
                else:
                    normal_metadata[key] = value
            
            # Сортируем оба словаря по ключу
            sorted_colored = sorted(colored_metadata.items())
            sorted_normal = sorted(normal_metadata.items())
            
            # Объединяем: сначала цветные, потом обычные
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
            
        except Exception as e:
            self.metadata_table.setRowCount(1)
            self.metadata_table.setItem(0, 0, QTableWidgetItem("Ошибка"))
            self.metadata_table.setItem(0, 1, QTableWidgetItem(f"Ошибка чтения метаданных: {str(e)}"))

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
        if field_name in self.color_metadata['red']:
            return QColor(255, 200, 200)  # Светло-красный
        elif field_name in self.color_metadata['green']:
            return QColor(200, 255, 200)  # Светло-зеленый
        elif field_name in self.color_metadata['blue']:
            return QColor(200, 200, 255)  # Светло-синий
        elif field_name in self.color_metadata['yellow']:
            return QColor(255, 255, 200)  # Светло-желтый
        return None

    def show_table_context_menu(self, position):
        # Определяем, по какому элементу кликнули
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
            
            # Добавить подменю для добавления в цветной список
            color_menu = menu.addMenu("Добавить в цветной список")
            
            red_action = color_menu.addAction("Красный")
            red_action.triggered.connect(lambda: self.add_field_to_color_list(field_name, 'red'))
            
            green_action = color_menu.addAction("Зеленый")
            green_action.triggered.connect(lambda: self.add_field_to_color_list(field_name, 'green'))
            
            blue_action = color_menu.addAction("Синий")
            blue_action.triggered.connect(lambda: self.add_field_to_color_list(field_name, 'blue'))
            
            yellow_action = color_menu.addAction("Желтый")
            yellow_action.triggered.connect(lambda: self.add_field_to_color_list(field_name, 'yellow'))
            
            # Удалить из цветного списка
            remove_action = menu.addAction("Удалить из цветного списка")
            remove_action.triggered.connect(lambda: self.remove_field_from_color_lists(field_name))
            
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

    def add_field_to_color_list(self, field_name, color_key):
        """Добавляет поле в указанный цветной список"""
        if field_name not in self.color_metadata[color_key]:
            self.color_metadata[color_key].append(field_name)
            self.save_settings()
            
            # Обновляем отображение метаданных с новыми цветами
            self.update_metadata_colors()
            
            # Копируем поле в буфер обмена
            clipboard = QApplication.clipboard()
            clipboard.setText(field_name)
            
            color_names = {
                'red': 'красный',
                'green': 'зеленый',
                'blue': 'синий',
                'yellow': 'желтый'
            }
            
            QMessageBox.information(self, "Успех", 
                                  f"Поле '{field_name}' добавлено в {color_names[color_key]} список и скопировано в буфер обмена")

    def remove_field_from_color_lists(self, field_name):
        """Удаляет поле из всех цветных списков"""
        removed_from = []
        
        for color_key in ['red', 'green', 'blue', 'yellow']:
            if field_name in self.color_metadata[color_key]:
                self.color_metadata[color_key].remove(field_name)
                removed_from.append(color_key)
        
        if removed_from:
            self.save_settings()
            self.update_metadata_colors()
            
            color_names = {
                'red': 'красного',
                'green': 'зеленого',
                'blue': 'синего',
                'yellow': 'желтого'
            }
            
            removed_list = ", ".join([color_names[color] for color in removed_from])
            QMessageBox.information(self, "Успех", 
                                  f"Поле '{field_name}' удалено из {removed_list} списков")
        else:
            QMessageBox.information(self, "Информация", 
                                  f"Поле '{field_name}' не найдено в цветных списках")

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
            # Получаем актуальные настройки из диалога
            self.color_metadata = dialog.get_settings()
            self.save_settings()
            # Обновляем отображение метаданных с новыми цветами
            self.update_metadata_colors()

    def load_settings(self):
        """Загружает настройки из файла"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    self.color_metadata = settings.get('color_metadata', self.color_metadata)
        except Exception as e:
            print(f"Ошибка загрузки настроек: {e}")

    def save_settings(self):
        """Сохраняет настройки в файл"""
        try:
            settings = {
                'color_metadata': self.color_metadata
            }
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения настроек: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = EXRMetadataViewer()
    window.show()
    sys.exit(app.exec_())