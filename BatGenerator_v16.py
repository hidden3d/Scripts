import os
import sys
import json
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QCheckBox, QTextEdit, 
                             QGroupBox, QFileDialog, QMessageBox, QScrollArea,
                             QRadioButton, QComboBox, QSpinBox, QDoubleSpinBox,
                             QTreeView, QHeaderView, QDialog, QTabWidget, QDialogButtonBox,
                             QListWidget, QAbstractItemView, QTableWidget, QTableWidgetItem,
                             QGridLayout)
from PyQt5.QtCore import Qt, QDir, QSortFilterProxyModel, QSettings, QStandardPaths
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QIcon, QBrush, QColor, QFont

class NumericSortProxyModel(QSortFilterProxyModel):
    def lessThan(self, left_index, right_index):
        if left_index.column() == 1:  # Столбец с количеством файлов
            left_data = self.sourceModel().data(left_index, Qt.UserRole)
            right_data = self.sourceModel().data(right_index, Qt.UserRole)
            try:
                return int(left_data) < int(right_data)
            except:
                return super().lessThan(left_index, right_index)
        return super().lessThan(left_index, right_index)

class PreviewDialog(QDialog):
    def __init__(self, bat_content, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Предпросмотр BAT-файлов")
        self.setGeometry(200, 200, 800, 600)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        tab_widget = QTabWidget()
        
        # Для режима NoScale будет две вкладки
        if isinstance(bat_content, dict):
            for name, content in bat_content.items():
                text_edit = QTextEdit()
                text_edit.setPlainText(content)
                text_edit.setReadOnly(True)
                text_edit.setFontFamily("Courier New")
                tab_widget.addTab(text_edit, name)
        else:
            # Для режима Scale одна вкладка
            text_edit = QTextEdit()
            text_edit.setPlainText(bat_content)
            text_edit.setReadOnly(True)
            text_edit.setFontFamily("Courier New")
            tab_widget.addTab(text_edit, "Scale BAT")
        
        layout.addWidget(tab_widget)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

class RealityScanBatchGenerator(QMainWindow):
    # Размер шрифта для всего приложения
    FONT_SIZE = 9  # Увеличен для лучшей читаемости
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RealityScan Batch Generator")
        self.setGeometry(100, 100, 1000, 1000)
        
        # Основные переменные
        self.realityscan_path = "C:\\Program Files\\Epic Games\\RealityScan_2.0"
        self.simplify_value = 3000000
        self.use_ai_masks = True
        self.subfolders = []
        self.marker_points = ["16h5:06", "16h5:07", "16h5:08", "16h5:0a", "16h5:0f",
                             "16h5:10", "16h5:17", "16h5:1b", "16h5:1e", "16h5:04",
                             "16h5:09", "16h5:1d", "16h5:03", "16h5:0c", "16h5:11",
                             "16h5:15", "16h5:02", "16h5:12", "16h5:13", "16h5:0b",
                             "16h5:1a", "16h5:0d", "16h5:19", "16h5:05", "16h5:1c",
                             "16h5:0e", "16h5:14", "16h5:18", "16h5:01", "16h5:16"]
        
        # Пресеты команд defineDistance
        self.presets = {
            "34mm": [
                ("16h5:01", "16h5:02", 0.1),
                ("16h5:02", "16h5:03", 0.2),
                ("16h5:04", "16h5:05", 0.5),
                ("16h5:06", "16h5:08", 1.0)
            ],
            "50mm": [
                ("16h5:01", "16h5:02", 0.3),
                ("16h5:02", "16h5:03", 0.4),
                ("16h5:04", "16h5:05", 0.7),
                ("16h5:06", "16h5:08", 2.0)
            ],
            "88.77mm": [
                ("16h5:01", "16h5:02", 0.6),
                ("16h5:02", "16h5:03", 0.7),
                ("16h5:04", "16h5:05", 0.9),
                ("16h5:06", "16h5:08", 3.0)
            ]
        }
        
        # Инициализация списка команд маркеров
        self.distance_commands = []  # Список словарей: {'point1': str, 'point2': str, 'distance': float, 'enabled': bool}
        
        # Инициализация белого списка маркеров
        self.white_list_markers = []
        
        # Храним файл конфигурации рядом со скриптом
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "RealityScanBatchGenerator.ini")
        
        # Инициализируем QSettings с INI-формат
        self.settings = QSettings(config_path, QSettings.IniFormat)
        
        self.init_ui()
        
        # Загрузка настроек ПОСЛЕ инициализации UI
        self.load_settings()
    
    def apply_font(self, widget):
        """Применяет установленный размер шрифта к виджету"""
        font = widget.font()
        font.setPointSize(self.FONT_SIZE)
        widget.setFont(font)
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # Режим работы
        mode_group = QGroupBox("Режим работы")
        mode_layout = QHBoxLayout()
        
        self.mode_noscale = QRadioButton("NoScale (два BAT-файла)")
        self.mode_noscale.setChecked(True)
        
        self.mode_scale = QRadioButton("Scale (один BAT-файл с маркерами)")
        self.mode_scale.setChecked(False)
        
        mode_layout.addWidget(self.mode_noscale)
        mode_layout.addWidget(self.mode_scale)
        mode_group.setLayout(mode_layout)
        main_layout.addWidget(mode_group)
        
        # Применяем шрифт ко всем элементам группы
        self.apply_font(mode_group)
        for widget in [self.mode_noscale, self.mode_scale]:
            self.apply_font(widget)
               
        # Путь к RealityScan
        realityscan_layout = QHBoxLayout()
        realityscan_label = QLabel("Путь к RealityScan:")
        self.realityscan_edit = QLineEdit(self.realityscan_path)
        realityscan_btn = QPushButton("Обзор...")
        realityscan_btn.clicked.connect(self.select_realityscan_path)
        
        realityscan_layout.addWidget(realityscan_label)
        realityscan_layout.addWidget(self.realityscan_edit)
        realityscan_layout.addWidget(realityscan_btn)
        main_layout.addLayout(realityscan_layout)
        
        # Применяем шрифт
        for widget in [realityscan_label, self.realityscan_edit, realityscan_btn]:
            self.apply_font(widget)
        
        # Входные папки
        input_group = QGroupBox("Папки с фотографиями")
        self.apply_font(input_group)
        input_layout = QVBoxLayout()
        
        # Список добавленных папок
        self.input_list = QListWidget()
        self.input_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.apply_font(self.input_list)
        
        input_layout.addWidget(self.input_list)
        
        # Кнопки управления списком папок
        input_buttons_layout = QHBoxLayout()
        
        add_input_btn = QPushButton("Добавить папку")
        add_input_btn.clicked.connect(self.add_input_folder)
        self.apply_font(add_input_btn)
        
        remove_input_btn = QPushButton("Удалить выбранные")
        remove_input_btn.clicked.connect(self.remove_input_folders)
        self.apply_font(remove_input_btn)
        
        input_buttons_layout.addWidget(add_input_btn)
        input_buttons_layout.addWidget(remove_input_btn)
        
        input_layout.addLayout(input_buttons_layout)
        
        # Чекбокс для обрезки даты из имени подпапки
        self.trim_date_checkbox = QCheckBox("Убрать дату из имени подпапки (если начинается с 8 цифр)")
        self.trim_date_checkbox.setChecked(False)
        self.apply_font(self.trim_date_checkbox)
        input_layout.addWidget(self.trim_date_checkbox)
        
        input_group.setLayout(input_layout)
        main_layout.addWidget(input_group)
        
        # Выходная папка для проектов
        output_layout = QHBoxLayout()
        output_label = QLabel("Папка для проектов:")
        self.output_edit = QLineEdit()
        output_btn = QPushButton("Обзор...")
        output_btn.clicked.connect(self.select_output_folder)
        
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(output_btn)
        main_layout.addLayout(output_layout)
        
        # Применяем шрифт
        for widget in [output_label, self.output_edit, output_btn]:
            self.apply_font(widget)
        
        # Настройки экспорта моделей
        export_layout = QHBoxLayout()
        
        # Чекбокс для включения/выключения экспорта
        self.export_checkbox = QCheckBox("Экспорт моделей")
        self.export_checkbox.setChecked(True)
        self.apply_font(self.export_checkbox)
        
        export_layout.addWidget(self.export_checkbox)
        
        # Поле для пути экспорта
        export_path_label = QLabel("Путь для экспорта:")
        self.apply_font(export_path_label)
        
        self.export_path_edit = QLineEdit()
        self.apply_font(self.export_path_edit)
        
        export_path_btn = QPushButton("Обзор...")
        export_path_btn.clicked.connect(self.select_export_path)
        self.apply_font(export_path_btn)
        
        export_layout.addWidget(export_path_label)
        export_layout.addWidget(self.export_path_edit)
        export_layout.addWidget(export_path_btn)
        
        main_layout.addLayout(export_layout)
        
        # Файл BAT
        bat_layout = QHBoxLayout()
        bat_label = QLabel("BAT файл для сохранения:")
        self.bat_edit = QLineEdit()
        bat_btn = QPushButton("Обзор...")
        bat_btn.clicked.connect(self.select_bat_file)
        
        bat_layout.addWidget(bat_label)
        bat_layout.addWidget(self.bat_edit)
        bat_layout.addWidget(bat_btn)
        main_layout.addLayout(bat_layout)
        
        # Применяем шрифт
        for widget in [bat_label, self.bat_edit, bat_btn]:
            self.apply_font(widget)
        
        # Список подпапок с чекбоксами (используем QTreeView)
        self.folders_group = QGroupBox("Выберите подпапки для обработки")
        self.apply_font(self.folders_group)
        folders_layout = QVBoxLayout()
        
        # Модель для отображения подпапок
        self.folders_model = QStandardItemModel()
        # Изменён порядок столбцов: Подпапка, Файлов, Дата изменения
        self.folders_model.setHorizontalHeaderLabels(["Подпапка", "Файлов", "Дата изменения"])
        
        # Прокси-модель для сортировки
        self.proxy_model = NumericSortProxyModel()
        self.proxy_model.setSourceModel(self.folders_model)
        self.proxy_model.setSortCaseSensitivity(Qt.CaseInsensitive)
        
        # Виджет дерева
        self.tree_view = QTreeView()
        self.tree_view.setModel(self.proxy_model)
        self.tree_view.setSortingEnabled(True)
        self.tree_view.sortByColumn(0, Qt.AscendingOrder)  # Сортировка по имени по умолчанию
        self.tree_view.setRootIsDecorated(False)
        self.tree_view.setSelectionMode(QTreeView.NoSelection)
        self.tree_view.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree_view.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree_view.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.apply_font(self.tree_view)  # Применяем шрифт к дереву
        
        # Установка шрифта для заголовков дерева
        header = self.tree_view.header()
        header_font = header.font()
        header_font.setPointSize(self.FONT_SIZE)
        header.setFont(header_font)
        
        folders_layout.addWidget(self.tree_view)
        
        # Кнопки управления
        controls_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Выбрать все")
        self.select_all_btn.clicked.connect(self.select_all_folders)
        self.apply_font(self.select_all_btn)
        
        self.deselect_all_btn = QPushButton("Снять все")
        self.deselect_all_btn.clicked.connect(self.deselect_all_folders)
        self.apply_font(self.deselect_all_btn)
        
        self.clear_folders_btn = QPushButton("Очистить список")
        self.clear_folders_btn.clicked.connect(self.clear_folders_list)
        self.apply_font(self.clear_folders_btn)
        
        controls_layout.addWidget(self.select_all_btn)
        controls_layout.addWidget(self.deselect_all_btn)
        controls_layout.addWidget(self.clear_folders_btn)
        controls_layout.addStretch()
        
        folders_layout.addLayout(controls_layout)
        self.folders_group.setLayout(folders_layout)
        main_layout.addWidget(self.folders_group)

        # Общие настройки для обоих режимов
        common_settings_group = QGroupBox("Общие настройки")
        self.apply_font(common_settings_group)
        common_layout = QHBoxLayout()
        
        # AI Masks
        self.common_ai_masks_check = QCheckBox("Маски -generateAIMasks")
        self.common_ai_masks_check.setChecked(self.use_ai_masks)
        self.apply_font(self.common_ai_masks_check)
        common_layout.addWidget(self.common_ai_masks_check)
        
        # Prior Groups
        prior_group_layout = QHBoxLayout()
        
        self.common_prior_calibration_check = QCheckBox("-setPriorCalibrationGroup -1")
        self.common_prior_calibration_check.setChecked(True)
        self.apply_font(self.common_prior_calibration_check)
        
        self.common_prior_lens_check = QCheckBox("-setPriorLensGroup -1")
        self.common_prior_lens_check.setChecked(True)
        self.apply_font(self.common_prior_lens_check)
        
        prior_group_layout.addWidget(self.common_prior_calibration_check)
        prior_group_layout.addWidget(self.common_prior_lens_check)
        common_layout.addLayout(prior_group_layout)
        
        # Simplify
        simplify_layout = QHBoxLayout()
        simplify_label = QLabel("Количество полигонов:")
        self.apply_font(simplify_label)
        
        self.common_simplify_edit = QSpinBox()
        self.common_simplify_edit.setRange(1, 100000000)
        self.common_simplify_edit.setValue(self.simplify_value)
        self.apply_font(self.common_simplify_edit)
        
        simplify_layout.addWidget(simplify_label)
        simplify_layout.addWidget(self.common_simplify_edit)
        simplify_layout.addStretch()
        common_layout.addLayout(simplify_layout)
        
        common_settings_group.setLayout(common_layout)
        main_layout.addWidget(common_settings_group)

        # Настройки для режима Scale
        self.scale_settings_group = QGroupBox("Настройки Scale режима")
        self.apply_font(self.scale_settings_group)
        scale_settings_layout = QVBoxLayout()
        
        # Настройки маркеров
        marker_group = QGroupBox("Настройки маркеров")
        self.apply_font(marker_group)
        marker_layout = QVBoxLayout()
        
        # Пресеты
        presets_group = QGroupBox("Пресеты маркеров")
        self.apply_font(presets_group)
        presets_layout = QHBoxLayout()
        
        self.presets_combo = QComboBox()
        self.presets_combo.addItems(list(self.presets.keys()))
        self.apply_font(self.presets_combo)
        
        load_preset_btn = QPushButton("Загрузить пресет")
        load_preset_btn.clicked.connect(self.load_preset)
        self.apply_font(load_preset_btn)
        
        clear_markers_btn = QPushButton("Очистить маркеры")
        clear_markers_btn.clicked.connect(self.clear_markers)
        self.apply_font(clear_markers_btn)
        
        presets_layout.addWidget(QLabel("Выберите пресет:"))
        self.apply_font(presets_layout.itemAt(0).widget())  # Применяем к QLabel
        
        presets_layout.addWidget(self.presets_combo)
        presets_layout.addWidget(load_preset_btn)
        presets_layout.addWidget(clear_markers_btn)
        presets_layout.addStretch()
        presets_group.setLayout(presets_layout)
        
        # Форма для добавления новой команды
        new_command_group = QGroupBox("Добавить новую команду defineDistance")
        self.apply_font(new_command_group)
        new_command_layout = QHBoxLayout()
        
        # Создаем выпадающие списки с нумерованными маркерами
        self.point1_combo = QComboBox()
        self.point2_combo = QComboBox()
        
        # Заполняем списки маркеров с порядковыми номерами
        for idx, marker in enumerate(self.marker_points, start=0):
            self.point1_combo.addItem(f"{idx}-{marker}", marker)
            self.point2_combo.addItem(f"{idx}-{marker}", marker)
        
        self.apply_font(self.point1_combo)
        self.apply_font(self.point2_combo)
        self.point2_combo.setCurrentIndex(1)
        
        self.distance_spin = QDoubleSpinBox()
        # Изменён диапазон: от 0 до 10000 с точностью 0.00001
        self.distance_spin.setRange(0.0, 10000.0)
        self.distance_spin.setDecimals(5)
        self.distance_spin.setValue(0.11)
        self.distance_spin.setSingleStep(0.01)
        self.apply_font(self.distance_spin)
        
        add_command_btn = QPushButton("Добавить")
        add_command_btn.clicked.connect(self.add_distance_command)
        self.apply_font(add_command_btn)
        
        new_command_layout.addWidget(QLabel("Точка 1:"))
        self.apply_font(new_command_layout.itemAt(0).widget())  # Применяем к QLabel
        
        new_command_layout.addWidget(self.point1_combo)
        new_command_layout.addWidget(QLabel("Точка 2:"))
        self.apply_font(new_command_layout.itemAt(2).widget())  # Применяем к QLabel
        
        new_command_layout.addWidget(self.point2_combo)
        new_command_layout.addWidget(QLabel("Дистанция (м):"))
        self.apply_font(new_command_layout.itemAt(4).widget())  # Применяем к QLabel
        
        new_command_layout.addWidget(self.distance_spin)
        new_command_layout.addWidget(add_command_btn)
        new_command_group.setLayout(new_command_layout)
        
        # Таблица команд маркеров
        markers_table_group = QGroupBox("Команды маркеров")
        self.apply_font(markers_table_group)
        markers_table_layout = QVBoxLayout()
        
        # Таблица для отображения команд маркеров
        self.markers_table = QTableWidget(0, 5)  # 5 колонок
        self.markers_table.setHorizontalHeaderLabels(["Вкл.", "Точка 1", "Точка 2", "Дистанция", "Управление"])
        self.markers_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.markers_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.markers_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.markers_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.markers_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.markers_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.markers_table.setMaximumHeight(200)
        self.apply_font(self.markers_table)  # Применяем шрифт к таблице
        
        # Установка шрифта для заголовков таблицы
        header = self.markers_table.horizontalHeader()
        header_font = header.font()
        header_font.setPointSize(self.FONT_SIZE)
        header.setFont(header_font)
        
        markers_table_layout.addWidget(self.markers_table)
        markers_table_group.setLayout(markers_table_layout)
        
        # Добавляем группу для выбора маркеров, которые не нужно удалять (в виде сетки)
        white_list_group = QGroupBox("Маркеры, которые не удалять (белый список)")
        self.apply_font(white_list_group)
        white_list_layout = QVBoxLayout()
        
        # Создаем виджет для сетки
        grid_widget = QWidget()
        grid_layout = QGridLayout()
        grid_widget.setLayout(grid_layout)
        
        # Создаем чекбоксы для каждого маркера
        self.white_list_checkboxes = []
        for idx, marker in enumerate(self.marker_points):
            checkbox = QCheckBox(f"{idx}-{marker}")
            checkbox.setFont(QFont("", self.FONT_SIZE))
            row = idx // 10  # 10 колонок в строке
            col = idx % 10   # остаток от деления - колонка
            grid_layout.addWidget(checkbox, row, col)
            self.white_list_checkboxes.append(checkbox)
        
        white_list_layout.addWidget(grid_widget)
        
        # Кнопки для управления белым списком
        white_list_buttons_layout = QHBoxLayout()
        select_all_white_btn = QPushButton("Выбрать все")
        select_all_white_btn.clicked.connect(self.select_all_white_list)
        self.apply_font(select_all_white_btn)
        
        deselect_all_white_btn = QPushButton("Снять все")
        deselect_all_white_btn.clicked.connect(self.deselect_all_white_list)
        self.apply_font(deselect_all_white_btn)
        
        white_list_buttons_layout.addWidget(select_all_white_btn)
        white_list_buttons_layout.addWidget(deselect_all_white_btn)
        white_list_layout.addLayout(white_list_buttons_layout)
        
        white_list_group.setLayout(white_list_layout)
        
        # Добавляем эту группу в marker_layout
        marker_layout.addWidget(white_list_group)
        
        marker_layout.addWidget(presets_group)
        marker_layout.addWidget(new_command_group)
        marker_layout.addWidget(markers_table_group)
        marker_group.setLayout(marker_layout)
        
        # Настройки для NoScale режима
        self.noscale_settings_group = QGroupBox("Настройки NoScale режима")
        self.apply_font(self.noscale_settings_group)
        noscale_settings_layout = QVBoxLayout()
        
        noscale_info_label = QLabel("Для NoScale режима используются общие настройки")
        self.apply_font(noscale_info_label)
        noscale_settings_layout.addWidget(noscale_info_label)
        
        self.noscale_settings_group.setLayout(noscale_settings_layout)
        
        # Добавляем группы настроек в основной layout
        scale_settings_layout.addWidget(marker_group)
        self.scale_settings_group.setLayout(scale_settings_layout)
        
        main_layout.addWidget(self.noscale_settings_group)
        main_layout.addWidget(self.scale_settings_group)
        
        # Обновляем видимость в соответствии с текущим режимом
        self.update_mode_settings()
        
        # Кнопки генерации
        buttons_layout = QHBoxLayout()
        
        preview_btn = QPushButton("Предпросмотр")
        preview_btn.clicked.connect(self.preview_bat)
        self.apply_font(preview_btn)
        
        generate_btn = QPushButton("Сгенерировать BAT файлы")
        generate_btn.clicked.connect(self.generate_bat)
        self.apply_font(generate_btn)
        
        buttons_layout.addWidget(preview_btn)
        buttons_layout.addWidget(generate_btn)
        
        main_layout.addLayout(buttons_layout)
        
        # Информация
        info_group = QGroupBox("Информация")
        self.apply_font(info_group)
        info_layout = QVBoxLayout()
        
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setPlainText(
            "Инструкция:\n"
            "1. Выберите режим работы (NoScale или Scale)\n"
            "2. Укажите путь к RealityScan\n"
            "3. Добавьте папки с фотографиями (в них должны быть подпапки для каждого объекта)\n"
            "4. Укажите папку для сохранения проектов RealityScan\n"
            "5. Укажите путь для сохранения BAT-файла\n"
            "6. Выберите подпапки для обработки\n"
            "7. Настройте параметры выбранного режима\n"
            "8. Нажмите 'Сгенерировать BAT файлы'\n\n"
            "Режимы работы:\n"
            "- NoScale: создает два BAT-файла (создание проектов и их обработка)\n"
            "- Scale: создает один BAT-файл с маркерами для масштабирования\n\n"
            "Сортировка подпапки: щелкните по заголовку столбца для сортировки\n\n"
            f"Настройки сохраняются в: {self.settings.fileName()}"
        )
        self.apply_font(self.info_text)
        
        info_layout.addWidget(self.info_text)
        info_group.setLayout(info_layout)
        main_layout.addWidget(info_group)
        
        # Связываем переключатели режимов с отображением настроек
        self.mode_noscale.toggled.connect(self.update_mode_settings)
        self.mode_scale.toggled.connect(self.update_mode_settings)
        
        # Обновляем таблицу маркеров после инициализации UI
        self.update_markers_table()
        
        # Загружаем состояние белого списка маркеров
        self.load_white_list_settings()
    
    def select_all_white_list(self):
        for checkbox in self.white_list_checkboxes:
            checkbox.setChecked(True)

    def deselect_all_white_list(self):
        for checkbox in self.white_list_checkboxes:
            checkbox.setChecked(False)
    
    def update_mode_settings(self):
        if self.mode_noscale.isChecked():
            self.noscale_settings_group.show()
            self.scale_settings_group.hide()
        else:
            self.noscale_settings_group.hide()
            self.scale_settings_group.show()
    
    def load_preset(self):
        preset_name = self.presets_combo.currentText()
        preset_commands = self.presets[preset_name]
        
        for point1, point2, distance in preset_commands:
            self.add_distance_command_to_list(point1, point2, distance)
    
    def clear_markers(self):
        self.distance_commands = []
        self.update_markers_table()
    
    def add_distance_command(self):
        # Получаем реальные имена маркеров без порядковых номеров
        point1 = self.point1_combo.currentData()
        point2 = self.point2_combo.currentData()
        distance = self.distance_spin.value()
        
        if point1 == point2:
            QMessageBox.warning(self, "Ошибка", "Точки должны быть разными!")
            return
        
        self.add_distance_command_to_list(point1, point2, distance)
    
    def add_distance_command_to_list(self, point1, point2, distance):
        # Проверяем, есть ли уже такая пара точек
        for idx, cmd in enumerate(self.distance_commands):
            if (cmd['point1'] == point1 and cmd['point2'] == point2) or \
               (cmd['point1'] == point2 and cmd['point2'] == point1):
                # Показываем предупреждение
                reply = QMessageBox.question(
                    self, 
                    "Дублирование маркеров",
                    f"Пара точек {point1} и {point2} уже существует!\nЗаменить существующую команду?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    # Обновляем существующую команду
                    self.distance_commands[idx] = {
                        'point1': point1,
                        'point2': point2,
                        'distance': distance,
                        'enabled': True
                    }
                    self.update_markers_table()
                return
        
        # Добавляем новую команду
        self.distance_commands.append({
            'point1': point1,
            'point2': point2,
            'distance': distance,
            'enabled': True
        })
        self.update_markers_table()
    
    def update_markers_table(self):
        self.markers_table.setRowCount(len(self.distance_commands))
        
        for row, cmd in enumerate(self.distance_commands):
            # Получаем порядковые номера маркеров
            try:
                point1_idx = self.marker_points.index(cmd['point1'])
                point1_display = f"{point1_idx}-{cmd['point1']}"
            except ValueError:
                point1_display = cmd['point1']
            
            try:
                point2_idx = self.marker_points.index(cmd['point2'])
                point2_display = f"{point2_idx}-{cmd['point2']}"
            except ValueError:
                point2_display = cmd['point2']
            
            # Чекбокс для включения/выключения команда
            enabled_check = QCheckBox()
            enabled_check.setChecked(cmd['enabled'])
            enabled_check.stateChanged.connect(lambda state, r=row: self.toggle_marker_enabled(r, state))
            self.markers_table.setCellWidget(row, 0, enabled_check)
            self.apply_font(enabled_check)  # Применяем шрифт
            
            # Точка 1 с порядковым номером
            point1_item = QTableWidgetItem(point1_display)
            point1_item.setFlags(point1_item.flags() & ~Qt.ItemIsEditable)
            self.markers_table.setItem(row, 1, point1_item)
            self.apply_font(point1_item)  # Применяем шрифт
            
            # Точка 2 с порядковым номером
            point2_item = QTableWidgetItem(point2_display)
            point2_item.setFlags(point2_item.flags() & ~Qt.ItemIsEditable)
            self.markers_table.setItem(row, 2, point2_item)
            self.apply_font(point2_item)  # Применяем шрифт
            
            # Дистанция
            distance_item = QTableWidgetItem(f"{cmd['distance']:.5f}")
            distance_item.setFlags(distance_item.flags() & ~Qt.ItemIsEditable)
            self.markers_table.setItem(row, 3, distance_item)
            self.apply_font(distance_item)  # Применяем шрифт
            
            # Кнопка удаления
            delete_btn = QPushButton("Удалить")
            delete_btn.clicked.connect(lambda _, r=row: self.delete_marker(r))
            self.markers_table.setCellWidget(row, 4, delete_btn)
            self.apply_font(delete_btn)  # Применяем шрифт
            
            # Обновляем цвет строки
            for col in range(1, 4):
                item = self.markers_table.item(row, col)
                if item:
                    if cmd['enabled']:
                        item.setBackground(QBrush(Qt.white))
                    else:
                        item.setBackground(QBrush(QColor(220, 220, 220)))
    
    def toggle_marker_enabled(self, row, state):
        if 0 <= row < len(self.distance_commands):
            self.distance_commands[row]['enabled'] = (state == Qt.Checked)
            
            # Обновляем цвет строки
            for col in range(1, 4):
                item = self.markers_table.item(row, col)
                if item:
                    if state == Qt.Checked:
                        item.setBackground(QBrush(Qt.white))
                    else:
                        item.setBackground(QBrush(QColor(220, 220, 220)))
    
    def delete_marker(self, row):
        if 0 <= row < len(self.distance_commands):
            self.distance_commands.pop(row)
            self.update_markers_table()
    
    def select_realityscan_path(self):
        path = QFileDialog.getExistingDirectory(self, "Выберите папку с RealityScan", self.realityscan_edit.text())
        if path:
            self.realityscan_edit.setText(path)
    
    def add_input_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с фотографиями")
        if not folder:
            return
            
        # Проверяем, не добавлена ли папка уже
        if folder in [self.input_list.item(i).text() for i in range(self.input_list.count())]:
            return
            
        # Всегда добавляем папку в список
        self.input_list.addItem(folder)
        self.apply_font(self.input_list.item(self.input_list.count()-1))
        
        # Обновляем список подпапок
        self.update_folders_model()

    def remove_input_folders(self):
        selected_items = self.input_list.selectedItems()
        for item in selected_items:
            self.input_list.takeItem(self.input_list.row(item))
        
        # Обновляем список подпапок
        self.update_folders_model()

    def update_folders_model(self):
        """Полностью обновляет модель подпапок на основе текущего списка корневых папок"""
        # Очищаем предыдущий список
        self.folders_model.removeRows(0, self.folders_model.rowCount())
        
        if self.input_list.count() == 0:
            return
        
        try:
            # Показываем курсор ожидания во время подсчета файлов
            QApplication.setOverrideCursor(Qt.WaitCursor)
            QApplication.processEvents()
            
            # Собираем все объекты для обработки
            objects_to_process = []
            
            for i in range(self.input_list.count()):
                root_folder = self.input_list.item(i).text()
                
                if not os.path.exists(root_folder):
                    continue
                
                # Проверяем, есть ли в папке подпапки
                has_subfolders = False
                for entry in os.scandir(root_folder):
                    if entry.is_dir():
                        has_subfolders = True
                        break
                
                # Если есть подпапки - добавляем их как отдельные объекты
                if has_subfolders:
                    for folder_entry in os.scandir(root_folder):
                        if folder_entry.is_dir():
                            folder_name = folder_entry.name
                            folder_path = folder_entry.path
                            mod_date = datetime.fromtimestamp(folder_entry.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                            
                            # Подсчет файлов рекурсивно
                            try:
                                file_count = self.count_files(folder_path)
                            except Exception as e:
                                file_count = 0
                                print(f"Ошибка при подсчете файлов в {folder_path}: {e}")
                            
                            objects_to_process.append((folder_name, folder_path, mod_date, file_count))
                else:
                    # Если нет подпапки - добавляем саму корневую папку как объект
                    folder_name = os.path.basename(root_folder.rstrip('\\/'))
                    folder_path = root_folder
                    mod_date = datetime.fromtimestamp(os.path.getmtime(root_folder)).strftime("%Y-%m-%d %H:%M:%S")
                    
                    try:
                        file_count = self.count_files(root_folder)
                    except Exception as e:
                        file_count = 0
                        print(f"Ошибка при подсчете файлов в {root_folder}: {e}")
                    
                    objects_to_process.append((folder_name, folder_path, mod_date, file_count))
            
            # Добавляем объекты в модель
            for folder_name, folder_path, mod_date, file_count in objects_to_process:
                name_item = QStandardItem(folder_name)
                name_item.setCheckable(True)
                
                # Восстанавливаем состояние чекбокса из настроек
                key = folder_path.replace("\\", "_").replace("/", "_").replace(":", "_")
                folder_state = self.settings.value(f"folder_state/{key}", True, type=bool)
                name_item.setCheckState(Qt.Checked if folder_state else Qt.Unchecked)
                
                name_item.setData(folder_path, Qt.UserRole)  # Сохраняем полный путь
                name_item.setEditable(False)
                name_item.setFont(QFont("", self.FONT_SIZE))
                
                # Элемент с количеством файлов
                count_item = QStandardItem()
                count_item.setData(file_count, Qt.DisplayRole)
                count_item.setData(file_count, Qt.UserRole)
                count_item.setEditable(False)
                count_item.setFont(QFont("", self.FONT_SIZE))
                
                date_item = QStandardItem(mod_date)
                date_item.setEditable(False)
                date_item.setFont(QFont("", self.FONT_SIZE))
                
                # Добавляем строку
                self.folders_model.appendRow([name_item, count_item, date_item])
            
            # Сортировка по имени по умолчанию
            self.proxy_model.sort(0, Qt.AscendingOrder)
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось обновить список подпапки: {str(e)}")
        finally:
            # Восстанавливаем курсор
            QApplication.restoreOverrideCursor()
    
    def count_files(self, folder_path):
        """Рекурсивно подсчитывает количество файлов в папке и всех подпапках"""
        file_count = 0
        for root, dirs, files in os.walk(folder_path):
            file_count += len(files)
        return file_count
    
    def select_all_folders(self):
        for row in range(self.folders_model.rowCount()):
            item = self.folders_model.item(row, 0)
            item.setCheckState(Qt.Checked)
    
    def deselect_all_folders(self):
        for row in range(self.folders_model.rowCount()):
            item = self.folders_model.item(row, 0)
            item.setCheckState(Qt.Unchecked)
    
    def clear_folders_list(self):
        self.folders_model.removeRows(0, self.folders_model.rowCount())
    
    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения проектов", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)
    
    def select_export_path(self):
        """Выбор пути для экспорта моделей"""
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для экспорта моделей", self.export_path_edit.text())
        if folder:
            self.export_path_edit.setText(folder)
    
    def select_bat_file(self):
        file, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить BAT файл как",
            self.bat_edit.text(),
            "Batch Files (*.bat);;All Files (*)"
        )
        if file:
            self.bat_edit.setText(file)
    
    def get_selected_folders(self):
        selected = []
        for row in range(self.folders_model.rowCount()):
            item = self.folders_model.item(row, 0)
            if item.checkState() == Qt.Checked:
                folder_path = item.data(Qt.UserRole)  # Получаем полный путь
                folder_name = os.path.basename(folder_path)
                selected.append((folder_path, folder_name))
        return selected
    
    def preview_bat(self):
        # Получаем содержимое BAT-файлов без сохранения
        bat_content = self.generate_bat_content()
        
        # Показываем диалог предпросмотра
        if bat_content:
            preview_dialog = PreviewDialog(bat_content, self)
            preview_dialog.exec_()
    
    def generate_bat(self):
        # Получаем содержимое BAT-файлов
        bat_content = self.generate_bat_content()
        
        if not bat_content:
            return
        
        try:
            if self.mode_noscale.isChecked():
                # Для NoScale режима - сохраняем два файла
                base_name, ext = os.path.splitext(self.bat_edit.text())
                bat_file1 = f"{base_name}_1{ext}"
                bat_file2 = f"{base_name}_2{ext}"
                
                with open(bat_file1, 'w', encoding='utf-8') as f:
                    f.write(bat_content["Step1.bat"])
                
                with open(bat_file2, 'w', encoding='utf-8') as f:
                    f.write(bat_content["Step2.bat"])
                
                QMessageBox.information(self, "Успех", f"BAT-файлы успешно созданы:\n{bat_file1}\n{bat_file2}")
            else:
                # Для Scale режима - сохраняем один файл
                with open(self.bat_edit.text(), 'w', encoding='utf-8') as f:
                    f.write(bat_content)
                
                QMessageBox.information(self, "Успех", f"BAT-файл успешно создан:\n{self.bat_edit.text()}")
            
            # Сохраняем настройки
            self.save_settings()
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать BAT-файлы: {str(e)}")
    
    def generate_bat_content(self):
        output_folder = self.output_edit.text()
        bat_file = self.bat_edit.text()
        realityscan_path = self.realityscan_edit.text()
        
        if not all([output_folder, bat_file, realityscan_path]):
            QMessageBox.critical(self, "Ошибка", "Заполните все обязательные поля!")
            return None
        
        if self.input_list.count() == 0:
            QMessageBox.critical(self, "Ошибка", "Добавьте хотя бы одну папку с фотографиями!")
            return None
        
        selected_folders = self.get_selected_folders()
        if not selected_folders:
            QMessageBox.warning(self, "Предупреждение", "Не выбрано ни одной подпапки для обработки!")
            return None
        
        try:
            if self.mode_noscale.isChecked():
                return self.generate_noscale_bat_content(output_folder, realityscan_path, selected_folders)
            else:
                return self.generate_scale_bat_content(output_folder, realityscan_path, selected_folders)
        
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сгенерировать BAT-файлы: {str(e)}")
            return None
    
    def generate_noscale_bat_content(self, output_folder, realityscan_path, selected_folders):
        simplify_value = self.common_simplify_edit.value()
        use_ai_masks = self.common_ai_masks_check.isChecked()
        
        # Добавляем параметры для приоритетных групп
        prior_calibration_param = " -setPriorCalibrationGroup -1" if self.common_prior_calibration_check.isChecked() else ""
        prior_lens_param = " -setPriorLensGroup -1" if self.common_prior_lens_check.isChecked() else ""
        
        # Генерация первого BAT-файла
        bat_content1 = "@echo off\n"
        bat_content1 += "REM Batch file generated by RealityScan Batch Generator (Step 1)\n\n"
        bat_content1 += f'set PATH=%PATH%;{realityscan_path}\n\n'
        
        for folder_path, folder_name in selected_folders:
            # Обработка имени папки
            if self.trim_date_checkbox.isChecked() and folder_name[:8].isdigit() and len(folder_name) >= 9:
                project_name = folder_name[9:]
            else:
                project_name = folder_name
                
            # Создаем папку для проекта, если ее нет
            project_dir = os.path.join(output_folder, project_name)
            
            ai_masks_param = " -generateAIMasks" if use_ai_masks else ""
            
            command = (
                f'RealityScan.exe -newScene -stdConsole -set "appIncSubdirs=true" -addFolder {folder_path}\\ '
                f'{ai_masks_param} -selectAllImages {prior_calibration_param}{prior_lens_param} -align '
                f'-save {project_dir}\\{project_name}.rsproj -quit\n'
            )
            bat_content1 += command
        
        bat_content1 += "\necho Step 1 completed! Projects created.\npause\n"
        
        # Генерация второго BAT-файла
        bat_content2 = "@echo off\n"
        bat_content2 += "REM Batch file generated by RealityScan Batch Generator (Step 2)\n\n"
        bat_content2 += f'set PATH=PATH%;{realityscan_path}\n\n'
        
        for folder_path, folder_name in selected_folders:
            # Обработка имени папки
            if self.trim_date_checkbox.isChecked() and folder_name[:8].isdigit() and len(folder_name) >= 9:
                project_name = folder_name[9:]
            else:
                project_name = folder_name
                
            project_dir = os.path.join(output_folder, project_name)
            project_file = os.path.join(project_dir, f"{project_name}.rsproj")
            
            # Добавляем команду экспорта, если включен экспорт и указан путь
            export_command = ""
            if self.export_checkbox.isChecked() and self.export_path_edit.text():
                export_dir = os.path.join(self.export_path_edit.text(), project_name)
                export_file = os.path.join(export_dir, f"{project_name}.obj")
                export_command = f" -exportSelectedModel {export_file}"
            
            command = (
                f'RealityScan.exe -stdConsole -load {project_file} '
                f'-calculateNormalModel -simplify {simplify_value} '
                f'-unwrap -calculateTexture '
                f'-save {project_file}{export_command} -quit\n'
            )
            bat_content2 += command
        
        bat_content2 += "\necho Step 2 completed! Models processed.\npause\n"
        
        return {"Step1.bat": bat_content1, "Step2.bat": bat_content2}
    
    def generate_scale_bat_content(self, output_folder, realityscan_path, selected_folders):
        use_ai_masks = self.common_ai_masks_check.isChecked()
        simplify_value = self.common_simplify_edit.value()
        
        # Добавляем параметры для приоритетных групп
        prior_calibration_param = " -setPriorCalibrationGroup -1" if self.common_prior_calibration_check.isChecked() else ""
        prior_lens_param = " -setPriorLensGroup -1" if self.common_prior_lens_check.isChecked() else ""
        
        # Преобразуем список команд в строку для BAT-файла
        distance_commands_list = []
        # Собираем маркеры, которые используются в defineDistance
        markers_in_define_distance = set()
        for cmd in self.distance_commands:
            if cmd['enabled']:
                # Используем только имя маркера без порядкового номера
                distance_commands_list.append(
                    f"-defineDistance {cmd['point1']} {cmd['point2']} {cmd['distance']:.5f}"
                )
                markers_in_define_distance.add(cmd['point1'])
                markers_in_define_distance.add(cmd['point2'])
        
        # Получаем список маркеров, которые не нужно удалять (белый список)
        white_list = set()
        for idx, checkbox in enumerate(self.white_list_checkboxes):
            if checkbox.isChecked():
                white_list.add(self.marker_points[idx])
        
        # Объединяем маркеры из defineDistance и белого списка
        keep_markers = white_list.union(markers_in_define_distance)
        
        bat_content = "@echo off\n"
        bat_content += "REM Batch file generated by RealityScan Batch Generator (Scale mode)\n\n"
        bat_content += f'set PATH=%PATH%;{realityscan_path}\n\n'
        
        for folder_path, folder_name in selected_folders:
            # Обработка имени папки
            if self.trim_date_checkbox.isChecked() and folder_name[:8].isdigit() and len(folder_name) >= 9:
                project_name = folder_name[9:]
            else:
                project_name = folder_name
                
            # Создаем папку для проекта, если ее нет
            project_dir = os.path.join(output_folder, project_name)
            
            ai_masks_param = " -generateAIMasks" if use_ai_masks else ""
            distance_commands = " ".join(distance_commands_list)
            
            # Формируем команды для удаления маркеров, которые не в белом списке и не в defineDistance
            delete_commands = ""
            for marker in self.marker_points:
                if marker not in keep_markers:
                    delete_commands += f" -selectControlPoint {marker} -deleteControlPoint"
            
            # Добавляем команду экспорта, если включен экспорт и указан путь
            export_command = ""
            if self.export_checkbox.isChecked() and self.export_path_edit.text():
                export_dir = os.path.join(self.export_path_edit.text(), project_name)
                export_file = os.path.join(export_dir, f"{project_name}.obj")
                export_command = f" -exportSelectedModel {export_file}"
            
            command = (
                f'RealityScan.exe -newScene -stdConsole -set "appIncSubdirs=true" -addFolder {folder_path}\\ '
                f' -selectAllImages {prior_calibration_param}{prior_lens_param} -detectMarkers{ai_masks_param}'
                f'{delete_commands} {distance_commands} -align '
                f'-calculateNormalModel -simplify {simplify_value} -unwrap -calculateTexture '
                f'-save {project_dir}\\{project_name}.rsproj{export_command} -quit\n'
            )
            bat_content += command
        
        bat_content += "\necho Processing completed!\npause\n"
        
        return bat_content
    
    def save_settings(self):
        # Сохраняем основные настройки
        self.settings.setValue("realityscan_path", self.realityscan_edit.text())
        self.settings.setValue("output_folder", self.output_edit.text())
        self.settings.setValue("bat_file", self.bat_edit.text())
        
        # Сохраняем настройки экспорта
        self.settings.setValue("export_models", self.export_checkbox.isChecked())
        self.settings.setValue("export_path", self.export_path_edit.text())
        
        # Сохраняем список папок
        input_folders = [self.input_list.item(i).text() for i in range(self.input_list.count())]
        self.settings.setValue("input_folders", input_folders)
        
        # Сохраняем режим
        self.settings.setValue("mode_noscale", self.mode_noscale.isChecked())
        self.settings.setValue("mode_scale", self.mode_scale.isChecked())
        
        # Сохраняем параметры маркеров
        self.settings.setValue("distance_commands", json.dumps(self.distance_commands))
        
        # Сохраняем общие настройки
        self.settings.setValue("common_ai_masks", self.common_ai_masks_check.isChecked())
        self.settings.setValue("common_simplify", self.common_simplify_edit.value())
        self.settings.setValue("common_prior_calibration", self.common_prior_calibration_check.isChecked())
        self.settings.setValue("common_prior_lens", self.common_prior_lens_check.isChecked())
        
        # Сохраняем состояние чекбокса обрезки даты
        self.settings.setValue("trim_date", self.trim_date_checkbox.isChecked())
        
        # Сохраняем состояние выбранных подпапок
        for row in range(self.folders_model.rowCount()):
            item = self.folders_model.item(row, 0)
            folder_path = item.data(Qt.UserRole)
            if folder_path:
                key = folder_path.replace("\\", "_").replace("/", "_").replace(":", "_")
                is_checked = item.checkState() == Qt.Checked
                self.settings.setValue(f"folder_state/{key}", is_checked)
        
        # Сохраняем белый список маркеров
        white_list = []
        for idx, checkbox in enumerate(self.white_list_checkboxes):
            if checkbox.isChecked():
                white_list.append(self.marker_points[idx])
        self.settings.setValue("white_list_markers", white_list)
    
    def load_settings(self):
        # Загрузка основных настроек
        self.realityscan_edit.setText(self.settings.value("realityscan_path", self.realityscan_path))
        self.output_edit.setText(self.settings.value("output_folder", ""))
        self.bat_edit.setText(self.settings.value("bat_file", ""))
        
        # Загрузка настроек экспорта
        self.export_checkbox.setChecked(self.settings.value("export_models", True, type=bool))
        self.export_path_edit.setText(self.settings.value("export_path", ""))
        
        # Загрузка списка папок
        saved_folders = self.settings.value("input_folders", [])
        if saved_folders:
            self.input_list.addItems(saved_folders)
            # Применяем шрифт к элементам списка
            for i in range(self.input_list.count()):
                item = self.input_list.item(i)
                self.apply_font(item)
        
        # Загрузка режима
        self.mode_noscale.setChecked(self.settings.value("mode_noscale", True, type=bool))
        self.mode_scale.setChecked(self.settings.value("mode_scale", False, type=bool))
        
        # Загрузка настроек маркеров
        saved_commands = self.settings.value("distance_commands")
        if saved_commands:
            try:
                self.distance_commands = json.loads(saved_commands)
            except:
                # Обработка старого формата настроек
                try:
                    old_dict = json.loads(saved_commands)
                    if isinstance(old_dict, dict):
                        self.distance_commands = []
                        for (p1, p2), dist in old_dict.items():
                            self.distance_commands.append({
                                'point1': p1,
                                'point2': p2,
                                'distance': dist,
                                'enabled': True
                            })
                except:
                    self.distance_commands = []
        
        # ОБНОВЛЯЕМ ТАБЛИЦУ МАРКЕРОВ ПОСЛЕ ЗАГРУЗКИ КОМАНД
        self.update_markers_table()
        
        # Загрузка общих настроек
        self.common_ai_masks_check.setChecked(self.settings.value("common_ai_masks", self.use_ai_masks, type=bool))
        self.common_simplify_edit.setValue(self.settings.value("common_simplify", self.simplify_value, type=int))
        self.common_prior_calibration_check.setChecked(self.settings.value("common_prior_calibration", True, type=bool))
        self.common_prior_lens_check.setChecked(self.settings.value("common_prior_lens", True, type=bool))
        
        # Загрузка состояния чекбокса обрезки даты
        self.trim_date_checkbox.setChecked(self.settings.value("trim_date", False, type=bool))
        
        # Обновляем модель подпапок, если есть папки
        if self.input_list.count() > 0:
            self.update_folders_model()
    
    def load_white_list_settings(self):
        # Загрузка белого списка маркеров
        white_list = self.settings.value("white_list_markers", [])
        if white_list:
            for idx, checkbox in enumerate(self.white_list_checkboxes):
                marker = self.marker_points[idx]
                checkbox.setChecked(marker in white_list)
    
    def closeEvent(self, event):
        # При закрытии приложения сохраняем настройки
        self.save_settings()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Установка единого шрифта для всего приложения
    font = QFont()
    font.setPointSize(9)  # Размер по умолчанию для элементов, где не указан явно
    app.setFont(font)
    
    try:
        window = RealityScanBatchGenerator()
        window.show()
        app.exec_()
    except Exception as e:
        print(f"Ошибка при запуске приложения: {e}")
        QMessageBox.critical(None, "Ошибка", f"Не удалось запустить приложение: {str(e)}")