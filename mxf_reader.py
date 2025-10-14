import sys
import subprocess
import json
import os
import tempfile
from pathlib import Path
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QTextEdit, QLabel, QFileDialog, 
                             QWidget, QSplitter, QTreeWidget, QTreeWidgetItem,
                             QHeaderView, QMessageBox, QProgressBar, QTabWidget,
                             QComboBox, QCheckBox, QGroupBox, QLineEdit)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor

class MetadataLoader(QThread):
    """Поток для загрузки метаданных без блокировки UI"""
    metadata_ready = pyqtSignal(dict, str)  # metadata, source
    error_occurred = pyqtSignal(str)
    progress_update = pyqtSignal(int)
    info_message = pyqtSignal(str)

    def __init__(self, file_path, tool_type="exiftool", options=None, art_path=None):
        super().__init__()
        self.file_path = file_path
        self.tool_type = tool_type
        self.options = options or {}
        self.art_path = art_path

    def run(self):
        try:
            self.progress_update.emit(10)
            
            if not os.path.exists(self.file_path):
                self.error_occurred.emit(f"Файл не найден: {self.file_path}")
                return

            self.progress_update.emit(30)
            
            if self.tool_type == "exiftool":
                metadata = self.run_exiftool()
            elif self.tool_type == "arri_reference_tool":
                metadata = self.run_arri_reference_tool()
            else:
                self.error_occurred.emit(f"Неизвестный инструмент: {self.tool_type}")
                return

            self.progress_update.emit(90)
            
            if metadata:
                self.progress_update.emit(100)
                self.metadata_ready.emit(metadata, self.tool_type)
            else:
                self.error_occurred.emit("Не удалось извлечь метаданные")

        except subprocess.TimeoutExpired:
            self.error_occurred.emit("Таймаут выполнения")
        except Exception as e:
            self.error_occurred.emit(f"Неожиданная ошибка: {e}")

    def run_exiftool(self):
        """Запуск exiftool с расширенными опциями"""
        cmd = [
            'exiftool', '-j', '-a', '-u', '-g1', '-b',
            '-ee', '-api', 'largefilesupport=1'
        ]
        
        # Добавляем специфичные опции для ARRI
        if self.options.get('extract_binary', False):
            cmd.extend(['-b'])
        
        if self.options.get('all_tags', False):
            cmd.extend(['-all:all'])
        
        cmd.append(self.file_path)
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            raise Exception(f"Ошибка exiftool: {result.stderr}")
        
        return json.loads(result.stdout)[0]

    def run_arri_reference_tool(self):
        """Запуск ARRI Reference Tool с правильным синтаксисом"""
        # Определяем исполняемый файл
        if self.art_path and os.path.exists(self.art_path):
            art_executable = self.art_path
        else:
            art_executable = self.art_path or './art-cmd'
        
        # Создаем временный файл для вывода JSON
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            temp_json = tmp.name
        
        try:
            # Запускаем ARRI Reference Tool для экспорта метаданных в JSON
            cmd = [
                art_executable,
                'export',
                '--duration', '1',
                '--input', self.file_path,
                '--output', temp_json
            ]
            
            self.info_message.emit(f"Запуск ARRI Reference Tool: {' '.join(cmd)}")
            
            # Если используем относительный путь, запускаем из директории где находится art-cmd
            if art_executable.startswith('./'):
                art_dir = os.path.dirname(os.path.abspath(art_executable))
                if not art_dir:
                    art_dir = os.getcwd()
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=art_dir)
            else:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                # Пробуем альтернативные имена исполняемого файла
                alternative_names = ['art-cmd', 'ARRIReferenceTool_CMD', 'arrireferencetool']
                
                for alt_name in alternative_names:
                    alt_cmd = [alt_name, 'export', '--duration', '1', '--input', self.file_path, '--output', temp_json]
                    self.info_message.emit(f"Попытка с {alt_name}: {' '.join(alt_cmd)}")
                    
                    if alt_name.startswith('./'):
                        art_dir = os.path.dirname(os.path.abspath(alt_name))
                        if not art_dir:
                            art_dir = os.getcwd()
                        result = subprocess.run(alt_cmd, capture_output=True, text=True, timeout=120, cwd=art_dir)
                    else:
                        result = subprocess.run(alt_cmd, capture_output=True, text=True, timeout=120)
                    
                    if result.returncode == 0:
                        break
                else:
                    error_msg = f"Ошибка ARRI Reference Tool (код {result.returncode}):\n"
                    if result.stderr:
                        error_msg += f"Stderr: {result.stderr}\n"
                    if result.stdout:
                        error_msg += f"Stdout: {result.stdout}"
                    raise Exception(error_msg)
            
            # Читаем и парсим JSON
            if os.path.exists(temp_json) and os.path.getsize(temp_json) > 0:
                with open(temp_json, 'r', encoding='utf-8') as f:
                    json_content = f.read()
                
                if json_content.strip():
                    metadata = self.parse_arri_json(json_content)
                else:
                    raise Exception("ARRI Reference Tool создал пустой файл")
            else:
                raise Exception("ARRI Reference Tool не создал выходной файл")
            
            return metadata
            
        finally:
            # Удаляем временный файл
            if os.path.exists(temp_json):
                os.unlink(temp_json)

    def parse_arri_json(self, json_content):
        """Парсинг JSON вывода ARRI Reference Tool"""
        try:
            data = json.loads(json_content)
            metadata = {}
            
            # Рекурсивно обходим JSON структуру
            def extract_values(obj, current_path=""):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        new_path = f"{current_path}/{key}" if current_path else key
                        if isinstance(value, (dict, list)):
                            extract_values(value, new_path)
                        else:
                            metadata[new_path] = str(value)
                elif isinstance(obj, list):
                    for i, item in enumerate(obj):
                        new_path = f"{current_path}[{i}]"
                        if isinstance(item, (dict, list)):
                            extract_values(item, new_path)
                        else:
                            metadata[new_path] = str(item)
                else:
                    metadata[current_path] = str(obj)
            
            extract_values(data)
            return metadata
            
        except json.JSONDecodeError as e:
            raise Exception(f"Ошибка парсинга JSON от ARRI Reference Tool: {e}\nContent: {json_content[:500]}...")

class MXFMetadataViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_file = None
        self.metadata = {}
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('ARRI MXF Metadata Viewer - ARRI Reference Tool')
        self.setGeometry(100, 100, 1400, 900)
        
        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Основной layout
        layout = QVBoxLayout(central_widget)
        
        # Панель управления
        control_layout = QHBoxLayout()
        
        self.select_btn = QPushButton('Выбрать MXF файл')
        self.select_btn.clicked.connect(self.select_file)
        
        self.file_label = QLabel('Файл не выбран')
        self.file_label.setStyleSheet('color: #666; font-style: italic;')
        
        # Выбор инструмента
        self.tool_combo = QComboBox()
        self.tool_combo.addItems(["ExifTool", "ARRI Reference Tool"])
        self.tool_combo.currentTextChanged.connect(self.on_tool_changed)
        
        # Группа для настроек ARRI Reference Tool
        self.art_group = QGroupBox("Настройки ARRI Reference Tool")
        art_layout = QVBoxLayout(self.art_group)
        
        art_path_layout = QHBoxLayout()
        art_path_layout.addWidget(QLabel("Путь к ART:"))
        self.art_path_edit = QLineEdit()
        self.art_path_edit.setPlaceholderText("art-cmd или ARRIReferenceTool_CMD")
        self.art_path_browse = QPushButton("Обзор...")
        self.art_path_browse.clicked.connect(self.browse_art_path)
        art_path_layout.addWidget(self.art_path_edit, 1)
        art_path_layout.addWidget(self.art_path_browse)
        
        art_layout.addLayout(art_path_layout)
        
        # Опции для exiftool
        self.exiftool_group = QGroupBox("Опции ExifTool")
        exiftool_layout = QHBoxLayout(self.exiftool_group)
        
        self.binary_check = QCheckBox("Извлекать бинарные данные")
        self.all_tags_check = QCheckBox("Все теги")
        
        exiftool_layout.addWidget(self.binary_check)
        exiftool_layout.addWidget(self.all_tags_check)
        exiftool_layout.addStretch()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        control_layout.addWidget(self.select_btn)
        control_layout.addWidget(QLabel("Инструмент:"))
        control_layout.addWidget(self.tool_combo)
        control_layout.addWidget(self.art_group)
        control_layout.addWidget(self.exiftool_group)
        control_layout.addWidget(self.file_label, 1)
        control_layout.addWidget(self.progress_bar)
        
        # Создаем вкладки
        self.tab_widget = QTabWidget()
        
        # Вкладка с древовидным представлением
        self.tree_tab = QWidget()
        tree_layout = QVBoxLayout(self.tree_tab)
        
        # Дерево метаданных
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(['Параметр', 'Значение'])
        self.tree_widget.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree_widget.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree_widget.itemDoubleClicked.connect(self.on_tree_item_double_clicked)
        
        tree_layout.addWidget(self.tree_widget)
        
        # Вкладка с плоским списком
        self.flat_tab = QWidget()
        flat_layout = QVBoxLayout(self.flat_tab)
        
        self.flat_text = QTextEdit()
        self.flat_text.setReadOnly(True)
        self.flat_text.setFont(QFont('Courier', 9))
        flat_layout.addWidget(self.flat_text)
        
        # Вкладка со сводкой
        self.summary_tab = QWidget()
        summary_layout = QVBoxLayout(self.summary_tab)
        
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setFont(QFont('Arial', 10))
        summary_layout.addWidget(self.summary_text)
        
        # Вкладка с сырыми данными
        self.raw_tab = QWidget()
        raw_layout = QVBoxLayout(self.raw_tab)
        
        self.raw_text = QTextEdit()
        self.raw_text.setReadOnly(True)
        self.raw_text.setFont(QFont('Courier', 8))
        raw_layout.addWidget(self.raw_text)
        
        # Вкладка с JSON просмотром
        self.json_tab = QWidget()
        json_layout = QVBoxLayout(self.json_tab)
        
        self.json_text = QTextEdit()
        self.json_text.setReadOnly(True)
        self.json_text.setFont(QFont('Courier', 9))
        json_layout.addWidget(self.json_text)
        
        # Добавляем вкладки
        self.tab_widget.addTab(self.tree_tab, "Дерево метаданных")
        self.tab_widget.addTab(self.flat_tab, "Плоский список")
        self.tab_widget.addTab(self.summary_tab, "Сводка")
        self.tab_widget.addTab(self.raw_tab, "Сырые данные")
        self.tab_widget.addTab(self.json_tab, "JSON просмотр")
        
        # Добавляем все в основной layout
        layout.addLayout(control_layout)
        layout.addWidget(self.tab_widget)
        
        # Статус бар
        self.statusBar().showMessage('Готов к работе')
        
        # Инициализируем видимость групп
        self.on_tool_changed(self.tool_combo.currentText())
        
        # Применяем стиль
        self.apply_dark_theme()
        
    def apply_dark_theme(self):
        """Применяем темную тему"""
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QTreeWidget {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QLabel {
                color: #ffffff;
                padding: 5px;
            }
            QProgressBar {
                border: 1px solid #555;
                border-radius: 4px;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                width: 20px;
            }
            QTabWidget::pane {
                border: 1px solid #555;
                background-color: #2b2b2b;
            }
            QTabBar::tab {
                background-color: #3b3b3b;
                color: white;
                padding: 8px 16px;
                border: 1px solid #555;
            }
            QTabBar::tab:selected {
                background-color: #4CAF50;
            }
            QTabBar::tab:hover {
                background-color: #45a049;
            }
            QComboBox {
                background-color: #3b3b3b;
                color: white;
                border: 1px solid #555;
                padding: 5px;
                border-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #3b3b3b;
                color: white;
                selection-background-color: #4CAF50;
            }
            QGroupBox {
                color: #ffffff;
                border: 1px solid #555;
                border-radius: 4px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QCheckBox {
                color: #ffffff;
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
            }
            QCheckBox::indicator:unchecked {
                background-color: #3b3b3b;
                border: 1px solid #555;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
                border: 1px solid #4CAF50;
            }
            QLineEdit {
                background-color: #3b3b3b;
                color: white;
                border: 1px solid #555;
                padding: 5px;
                border-radius: 4px;
            }
        """)
        
    def on_tool_changed(self, tool_name):
        """Обновляем видимость групп настроек в зависимости от выбранного инструмента"""
        if tool_name == "ARRI Reference Tool":
            self.art_group.setVisible(True)
            self.exiftool_group.setVisible(False)
        else:
            self.art_group.setVisible(False)
            self.exiftool_group.setVisible(True)
        
    def browse_art_path(self):
        """Выбор пути к ARRI Reference Tool через диалог"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            'Выберите ARRI Reference Tool (art-cmd или ARRIReferenceTool_CMD)',
            '',
            'ARRI Reference Tool (art-cmd* ARRIReferenceTool_CMD*);;All Files (*)'
        )
        
        if file_path:
            self.art_path_edit.setText(file_path)
    
    def select_file(self):
        """Выбор файла через диалог"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            'Выберите MXF файл',
            '',
            'MXF Files (*.mxf);;All Files (*)'
        )
        
        if file_path:
            self.load_metadata(file_path)
    
    def load_metadata(self, file_path):
        """Загрузка метаданных выбранного файла"""
        self.current_file = file_path
        self.file_label.setText(os.path.basename(file_path))
        
        # Определяем выбранный инструмент и опции
        tool_type = "exiftool" if self.tool_combo.currentText() == "ExifTool" else "arri_reference_tool"
        
        options = {}
        art_path = None
        
        if tool_type == "exiftool":
            options = {
                'extract_binary': self.binary_check.isChecked(),
                'all_tags': self.all_tags_check.isChecked()
            }
        else:
            art_path = self.art_path_edit.text().strip() or None
        
        self.statusBar().showMessage(f'Загрузка метаданных с помощью {tool_type}...')
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # Очищаем предыдущие данные
        self.tree_widget.clear()
        self.flat_text.clear()
        self.summary_text.clear()
        self.raw_text.clear()
        self.json_text.clear()
        
        # Запускаем загрузку в отдельном потоке
        self.loader = MetadataLoader(file_path, tool_type, options, art_path)
        self.loader.metadata_ready.connect(self.on_metadata_ready)
        self.loader.error_occurred.connect(self.on_metadata_error)
        self.loader.progress_update.connect(self.progress_bar.setValue)
        self.loader.info_message.connect(self.statusBar().showMessage)
        self.loader.start()
    
    def on_metadata_ready(self, metadata, source):
        """Обработка загруженных метаданных"""
        self.progress_bar.setVisible(False)
        self.metadata = metadata
        self.statusBar().showMessage(f'Метаданные загружены ({source}): {len(metadata)} параметров')
        
        # Обновляем все представления
        self.update_tree_view(metadata)
        self.update_flat_view(metadata)
        self.update_summary_view(metadata)
        self.update_raw_view(metadata, source)
        self.update_json_view(metadata)
    
    def update_tree_view(self, metadata):
        """Обновление древовидного представления"""
        # Группируем метаданные по группам
        grouped_data = {}
        for key, value in metadata.items():
            # Разбираем путь на группы
            parts = key.split('/')
            if len(parts) > 1:
                group = parts[0]
                param = '/'.join(parts[1:])
            elif ':' in key:
                group, param = key.split(':', 1)
            else:
                group = 'General'
                param = key
            
            if group not in grouped_data:
                grouped_data[group] = []
            
            # Обрабатываем значения
            display_value = self.format_value(value)
            grouped_data[group].append((param, display_value, key))
        
        # Заполняем дерево
        for group_name in sorted(grouped_data.keys()):
            group_item = QTreeWidgetItem(self.tree_widget, [group_name, ''])
            group_item.setExpanded(True)
            
            for param, value, full_key in sorted(grouped_data[group_name]):
                param_item = QTreeWidgetItem(group_item, [param, value])
                param_item.setData(0, Qt.UserRole, full_key)  # Сохраняем полный ключ
                param_item.setToolTip(0, f"Полный путь: {full_key}")
                param_item.setToolTip(1, f"Значение: {value}")
                
                # Подсветка важных параметров ARRI
                if any(keyword in full_key.lower() for keyword in 
                      ['arri', 'sensor', 'optic', 'motor', 'encoder', 'focus', 
                       'camera', 'lens', 'frame', 'resolution', 'codec',
                       'dimensions', 'image', 'recording', 'look', 'color']):
                    param_item.setBackground(0, QColor('#2d5a2d'))
                    param_item.setBackground(1, QColor('#2d5a2d'))
        
        self.tree_widget.resizeColumnToContents(0)
    
    def on_tree_item_double_clicked(self, item, column):
        """Обработка двойного клика по элементу дерева"""
        if item.parent():  # Не корневой элемент
            full_key = item.data(0, Qt.UserRole)
            if full_key and full_key in self.metadata:
                full_value = self.metadata[full_key]
                QMessageBox.information(self, f"Полное значение: {full_key}", 
                                      f"Полный путь: {full_key}\n\nЗначение:\n{full_value}")
    
    def format_value(self, value):
        """Форматирование значения для отображения"""
        if isinstance(value, str) and 'binary data' in value.lower():
            return "[Бинарные данные]"
        elif isinstance(value, (list, dict)):
            return str(value)
        elif isinstance(value, str) and len(value) > 200:
            return value[:200] + "... [усечено]"
        else:
            return str(value)
    
    def update_flat_view(self, metadata):
        """Обновление плоского списка метаданных"""
        flat_text = ""
        
        # Группируем по первому уровню для лучшей читаемости
        groups = {}
        for key, value in metadata.items():
            group = key.split('/')[0] if '/' in key else key.split(':')[0] if ':' in key else 'General'
            if group not in groups:
                groups[group] = []
            groups[group].append((key, value))
        
        for group in sorted(groups.keys()):
            flat_text += f"\n[{group}]\n"
            flat_text += "=" * 80 + "\n"
            for key, value in sorted(groups[group]):
                formatted_value = self.format_value(value)
                flat_text += f"{key}: {formatted_value}\n"
        
        self.flat_text.setText(flat_text)
    
    def update_summary_view(self, metadata):
        """Обновление сводки"""
        summary = "СВОДКА МЕТАДАННЫХ ARRI\n"
        summary += "=" * 50 + "\n\n"
        
        # Извлекаем информацию по категориям
        video_info = self.extract_video_info(metadata)
        camera_info = self.extract_camera_info(metadata)
        lens_info = self.extract_lens_info(metadata)
        scene_info = self.extract_scene_info(metadata)
        arri_specific = self.extract_arri_specific(metadata)
        
        summary += "🎬 ВИДЕО ИНФОРМАЦИЯ:\n"
        for key, value in video_info.items():
            summary += f"  • {key}: {value}\n"
        
        summary += "\n📷 ИНФОРМАЦИЯ О КАМЕРЕ И СЕНСОРЕ:\n"
        for key, value in camera_info.items():
            summary += f"  • {key}: {value}\n"
        
        summary += "\n🔍 ОПТИКА И ФОКУС:\n"
        for key, value in lens_info.items():
            summary += f"  • {key}: {value}\n"
        
        summary += "\n🎞️ СЦЕНИЧНАЯ ИНФОРМАЦИЯ:\n"
        for key, value in scene_info.items():
            summary += f"  • {key}: {value}\n"
        
        if arri_specific:
            summary += "\n🔧 ARRI-СПЕЦИФИЧНЫЕ МЕТАДАННЫЕ:\n"
            for key, value in arri_specific.items():
                summary += f"  • {key}: {value}\n"
        
        # Статистика
        summary += f"\n📊 ОБЩАЯ СТАТИСТИКА:\n"
        summary += f"  • Всего параметров: {len(metadata)}\n"
        
        groups = {}
        for key in metadata.keys():
            group = key.split('/')[0] if '/' in key else key.split(':')[0] if ':' in key else 'General'
            groups[group] = groups.get(group, 0) + 1
        
        for group, count in sorted(groups.items()):
            summary += f"  • {group}: {count} параметров\n"
        
        self.summary_text.setText(summary)
    
    def extract_video_info(self, metadata):
        """Извлекает основную видео информацию"""
        video_info = {}
        
        video_patterns = {
            'Разрешение': ['width', 'height', 'resolution', 'imagewidth', 'imageheight'],
            'Частота кадров': ['framerate', 'fps'],
            'Длительность': ['duration', 'length'],
            'Кодек': ['codec', 'compression'],
            'Глубина цвета': ['bitdepth', 'bitspersample'],
            'Цветовое пространство': ['colorspace', 'colorimetry'],
            'Соотношение сторон': ['aspectratio', 'pixelaspectratio']
        }
        
        return self.extract_by_patterns(metadata, video_patterns)
    
    def extract_camera_info(self, metadata):
        """Извлекает информацию о камере и сенсоре"""
        camera_patterns = {
            'Модель камеры': ['cameramodel', 'model'],
            'Серийный номер': ['cameraserial', 'serialnumber'],
            'Сенсор': ['sensor', 'sensordimensions'],
            'Производитель': ['make', 'manufacturer', 'arri'],
            'Версия прошивки': ['firmware', 'softwareversion']
        }
        
        return self.extract_by_patterns(metadata, camera_patterns)
    
    def extract_lens_info(self, metadata):
        """Извлекает информацию об оптике и фокусе"""
        lens_patterns = {
            'Модель объектива': ['lensmodel', 'lens'],
            'Фокусное расстояние': ['focallength'],
            'Диафрагма': ['aperture', 'fnumber'],
            'Фокус': ['focus', 'focusdistance', 'motor', 'encoder'],
            'ISO': ['iso', 'exposureindex'],
            'Выдержка': ['exposuretime', 'shutterspeed'],
            'Баланс белого': ['whitebalance', 'colortemperature']
        }
        
        return self.extract_by_patterns(metadata, lens_patterns)
    
    def extract_scene_info(self, metadata):
        """Извлекает сценическую информацию"""
        scene_patterns = {
            'Сцена': ['scene', 'scenenumber'],
            'Дубль': ['take', 'takenumber'],
            'Ролл': ['roll', 'rollnumber'],
            'Шот': ['shot', 'shotname'],
            'Проект': ['project', 'projectname'],
            'Рил': ['reel', 'reelname'],
            'Таймкод': ['timecode', 'starttimecode']
        }
        
        return self.extract_by_patterns(metadata, scene_patterns)
    
    def extract_arri_specific(self, metadata):
        """Извлекает ARRI-специфичные метаданные"""
        arri_info = {}
        
        # Ищем специфичные ARRI теги
        arri_patterns = [
            'arri/', 'sensor/', 'optic/', 'motor/', 'encoder/', 
            'look/', 'color/', 'recording/', 'stored_image'
        ]
        
        for key, value in metadata.items():
            key_lower = key.lower()
            if any(pattern in key_lower for pattern in arri_patterns):
                # Создаем читаемое имя
                display_name = key.replace('arri/', '').replace('/', ' → ')
                arri_info[display_name] = self.format_value(value)
        
        return arri_info
    
    def extract_by_patterns(self, metadata, patterns_dict):
        """Общая функция для извлечения данных по паттернам"""
        result = {}
        
        for display_name, patterns in patterns_dict.items():
            for pattern in patterns:
                for key, value in metadata.items():
                    key_lower = key.lower()
                    if pattern in key_lower:
                        result[display_name] = self.format_value(value)
                        break
                if display_name in result:
                    break
        
        return result
    
    def update_raw_view(self, metadata, source):
        """Обновление вкладки с сырыми данными"""
        raw_text = f"Источник: {source}\n"
        raw_text += f"Всего параметров: {len(metadata)}\n"
        raw_text += "=" * 80 + "\n\n"
        
        for key, value in sorted(metadata.items()):
            raw_text += f"{key} = {value}\n"
        
        self.raw_text.setText(raw_text)
    
    def update_json_view(self, metadata):
        """Обновление вкладки с JSON просмотром"""
        # Создаем структурированный JSON из плоских ключей
        structured_data = {}
        for key, value in metadata.items():
            parts = key.split('/')
            current = structured_data
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = value
        
        json_text = json.dumps(structured_data, indent=2, ensure_ascii=False)
        self.json_text.setText(json_text)
    
    def on_metadata_error(self, error_message):
        """Обработка ошибок загрузки"""
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage('Ошибка загрузки метаданных')
        QMessageBox.critical(self, 'Ошибка', f'Не удалось загрузить метаданные:\n{error_message}')

def check_tools():
    """Проверка доступности инструментов"""
    tools = {}
    
    # Проверяем exiftool
    try:
        subprocess.run(['exiftool', '-ver'], capture_output=True, check=True)
        tools['exiftool'] = True
    except:
        tools['exiftool'] = False
    
    # Проверяем ARRI Reference Tool
    art_names = ['./art-cmd', 'art-cmd', 'ARRIReferenceTool_CMD', 'arrireferencetool']
    tools['arri_reference_tool'] = False
    
    for art_name in art_names:
        try:
            if art_name.startswith('./'):
                # Для относительных путей проверяем существование файла
                if os.path.exists(art_name):
                    tools['arri_reference_tool'] = True
                    tools['arri_reference_tool_name'] = art_name
                    break
            else:
                result = subprocess.run([art_name, '--help'], capture_output=True, timeout=10)
                if result.returncode == 0:
                    tools['arri_reference_tool'] = True
                    tools['arri_reference_tool_name'] = art_name
                    break
        except:
            continue
    
    return tools

def main():
    # Проверяем доступность инструментов
    available_tools = check_tools()
    
    if not available_tools['exiftool'] and not available_tools['arri_reference_tool']:
        print("Ошибка: Не найдены инструменты для извлечения метаданных")
        print("Установите хотя бы один из следующих инструментов:")
        print("  ExifTool: sudo apt install libimage-exiftool-perl")
        print("  ARRI Reference Tool: скачайте с https://www.arri.com/en/learn-support/developer-tools")
        print("\nПосле установки ARRI Reference Tool укажите путь к art-cmd в настройках приложения")
        return
    
    # Запускаем приложение
    app = QApplication(sys.argv)
    app.setApplicationName("ARRI MXF Metadata Viewer")
    
    window = MXFMetadataViewer()
    window.show()
    
    # Показываем информацию о доступных инструментах
    tool_info = "Доступные инструменты: "
    tool_info += "ExifTool" if available_tools['exiftool'] else ""
    if available_tools['arri_reference_tool']:
        if available_tools['exiftool']:
            tool_info += ", "
        tool_info += f"ARRI Reference Tool ({available_tools.get('arri_reference_tool_name', 'ART')})"
    
    window.statusBar().showMessage(tool_info)
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()