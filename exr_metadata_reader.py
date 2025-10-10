import os
import sys
import json
import re
import platform
import subprocess
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
                             QHeaderView, QAbstractItemView, QMenu, QAction, QTabWidget)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QTextCursor, QColor, QTextCharFormat, QFont, QBrush


class SequenceFinder(QThread):
    sequence_found = pyqtSignal(dict)
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
        self.setGeometry(200, 200, 700, 500)
        
        layout = QVBoxLayout()
        
        # Создаем вкладки
        self.tabs = QTabWidget()
        
        # Вкладка активных полей
        self.active_tab = QWidget()
        self.setup_active_tab()
        self.tabs.addTab(self.active_tab, "Активные поля")
        
        # Вкладка корзины
        self.trash_tab = QWidget()
        self.setup_trash_tab()
        self.tabs.addTab(self.trash_tab, "Корзина")
        
        layout.addWidget(self.tabs)
        
        # Кнопки диалога
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        layout.addWidget(button_box)
        self.setLayout(layout)
        
        self.load_current_settings()

    def setup_active_tab(self):
        layout = QVBoxLayout()
        
        # Добавление нового поля
        form_layout = QFormLayout()
        
        self.field_input = QLineEdit()
        self.add_button = QPushButton("Добавить поле и выбрать цвет")
        self.add_button.clicked.connect(self.add_field_with_color)
        
        form_layout.addRow("Поле метаданных:", self.field_input)
        form_layout.addRow("", self.add_button)
        
        # Список активных полей
        layout.addWidget(QLabel("Активные поля:"))
        self.active_list = QListWidget()
        self.active_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.active_list.customContextMenuRequested.connect(self.show_active_list_context_menu)
        
        # Кнопка удаления выбранного
        self.delete_active_btn = QPushButton("Удалить выбранное")
        self.delete_active_btn.clicked.connect(self.delete_selected_active)
        
        layout.addLayout(form_layout)
        layout.addWidget(self.active_list)
        layout.addWidget(self.delete_active_btn)
        
        self.active_tab.setLayout(layout)

    def setup_trash_tab(self):
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

    def load_current_settings(self):
        """Загружает текущие настройки из родительского окна"""
        self.active_list.clear()
        self.trash_list.clear()
        
        # Загружаем активные поля
        for field_name, color_data in self.parent.color_metadata.items():
            # Проверяем корректность структуры данных
            if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                if not color_data.get('removed', False):
                    color = QColor(color_data['r'], color_data['g'], color_data['b'])
                    item = QListWidgetItem(field_name)
                    item.setBackground(color)
                    self.active_list.addItem(item)
            else:
                print(f"Пропущен некорректный элемент color_metadata: {field_name} = {color_data}")
        
        # Загружаем удаленные поля
        for field_name, color_data in self.parent.removed_metadata.items():
            if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                color = QColor(color_data['r'], color_data['g'], color_data['b'])
                item = QListWidgetItem(field_name)
                item.setBackground(color)
                self.trash_list.addItem(item)
            else:
                print(f"Пропущен некорректный элемент removed_metadata: {field_name} = {color_data}")

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
            
            # Сохраняем настройки
            self.parent.save_settings()
            
            # Обновляем интерфейс
            self.load_current_settings()
            
            # Обновляем отображение метаданных
            self.parent.update_metadata_colors()
            
            self.field_input.clear()

    def delete_selected_active(self):
        current_row = self.active_list.currentRow()
        if current_row >= 0:
            field_name = self.active_list.item(current_row).text()
            self.move_field_to_trash(field_name)

    def move_field_to_trash(self, field_name):
        """Перемещает поле в корзину"""
        if field_name in self.parent.color_metadata:
            # Сохраняем цвет в корзине
            color_data = self.parent.color_metadata[field_name]
            self.parent.removed_metadata[field_name] = color_data
            
            # Удаляем из активных
            del self.parent.color_metadata[field_name]
            
            # Сохраняем настройки
            self.parent.save_settings()
            
            # Обновляем интерфейс
            self.load_current_settings()
            
            # Обновляем отображение метаданных
            self.parent.update_metadata_colors()

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


class EXRMetadataViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.sequences = {}
        self.current_sequence_files = []
        self.current_metadata = {}
        
        # Новая структура данных для цветов
        self.color_metadata = {}  # {field_name: {'r': int, 'g': int, 'b': int, 'removed': False}}
        self.removed_metadata = {}  # {field_name: {'r': int, 'g': int, 'b': int, 'removed': True}}
        
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
        self.sequences_table.setSortingEnabled(True)
        self.sequences_table.itemSelectionChanged.connect(self.on_sequence_selected)
        self.sequences_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sequences_table.customContextMenuRequested.connect(self.show_sequences_table_context_menu)
        
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
        
        layout.addLayout(folder_layout)
        layout.addLayout(control_layout)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.sequences_table)
        layout.addWidget(self.metadata_table)
        layout.addLayout(search_layout)
        
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

    def show_sequences_table_context_menu(self, position):
        """Контекстное меню для таблицы последовательностей"""
        index = self.sequences_table.indexAt(position)
        if not index.isValid():
            return
            
        row = index.row()
        path_item = self.sequences_table.item(row, 0)
        
        if path_item:
            path = path_item.text()
            
            menu = QMenu(self)
            open_action = menu.addAction("Открыть в проводнике")
            
            action = menu.exec_(self.sequences_table.viewport().mapToGlobal(position))
            
            if action == open_action:
                self.open_in_explorer(path)

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
                if key in self.color_metadata and not self.color_metadata[key].get('removed', False):
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
            
            # Сбрасываем фильтр поиска при отображении новых данных
            self.clear_search()
            
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
            self.removed_metadata[field_name] = self.color_metadata[field_name]
            del self.color_metadata[field_name]
            
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

    def load_settings(self):
        """Загружает настройки из файла с миграцией старой структуры"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    
                    # Миграция со старой структуры на новую
                    if 'color_metadata' in settings:
                        # Если это старая структура (с цветами как ключи)
                        if isinstance(settings['color_metadata'], dict) and any(color in settings['color_metadata'] for color in ['red', 'green', 'blue', 'yellow']):
                            self.migrate_from_old_structure(settings)
                        else:
                            # Новая структура
                            self.color_metadata = settings.get('color_metadata', {})
                            self.removed_metadata = settings.get('removed_metadata', {})
                    else:
                        self.color_metadata = {}
                        self.removed_metadata = {}
                        
        except Exception as e:
            print(f"Ошибка загрузки настроек: {e}")
            self.color_metadata = {}
            self.removed_metadata = {}

    def migrate_from_old_structure(self, settings):
        """Мигрирует данные со старой структуры на новую"""
        print("Миграция настроек со старой структуры на новую...")
        
        # Старая структура: {'red': ['field1', 'field2'], 'green': ['field3'], ...}
        old_color_mapping = {
            'red': QColor(255, 200, 200),
            'green': QColor(200, 255, 200),
            'blue': QColor(200, 200, 255),
            'yellow': QColor(255, 255, 200)
        }
        
        # Переносим данные из старой структуры в новую
        for color_name, fields in settings['color_metadata'].items():
            if color_name in old_color_mapping and isinstance(fields, list):
                color = old_color_mapping[color_name]
                for field_name in fields:
                    self.color_metadata[field_name] = {
                        'r': color.red(),
                        'g': color.green(),
                        'b': color.blue(),
                        'removed': False
                    }
        
        # Сохраняем в новой структуре
        self.save_settings()
        print("Миграция завершена!")

    def save_settings(self):
        """Сохраняет настройки в файл"""
        try:
            # Убедимся, что все данные в правильном формате
            cleaned_color_metadata = {}
            for field_name, color_data in self.color_metadata.items():
                if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                    cleaned_color_metadata[field_name] = color_data
                else:
                    print(f"Удален некорректный элемент color_metadata: {field_name} = {color_data}")
            
            cleaned_removed_metadata = {}
            for field_name, color_data in self.removed_metadata.items():
                if isinstance(color_data, dict) and 'r' in color_data and 'g' in color_data and 'b' in color_data:
                    cleaned_removed_metadata[field_name] = color_data
                else:
                    print(f"Удален некорректный элемент removed_metadata: {field_name} = {color_data}")
            
            settings = {
                'color_metadata': cleaned_color_metadata,
                'removed_metadata': cleaned_removed_metadata
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