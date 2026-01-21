import nuke
import re
import os
import sys

# Проверяем доступность PySide2/PySide6
try:
    from PySide6 import QtCore, QtWidgets, QtGui
    PYSIDE_VERSION = 6
except ImportError:
    try:
        from PySide2 import QtCore, QtWidgets, QtGui
        PYSIDE_VERSION = 2
    except ImportError:
        raise ImportError("Не удалось импортировать PySide2 или PySide6")

class NonBlockingWritePanel(QtWidgets.QDialog):
    """Неблокирующее окно для создания Write нод из метаданных ARRI"""
    
    def __init__(self, parent=None):
        super(NonBlockingWritePanel, self).__init__(parent)
        
        # Настройки по умолчанию
        self.default_camera_field = "arri/camera/camera_model"
        self.default_lens_field = "arri/optic/lens_device/model"
        self.default_focal_field = "arri/optic/lens_state/focal_length"
        self.default_distance_field = "arri/optic/lens_state/focus_distance_metric"
        
        # Единицы измерения по умолчанию
        self.distance_units = "auto"  # auto, meters, mm
        
        # Инициализация UI
        self.init_ui()
        self.setup_connections()
        
        # Обновляем превью пути
        self.update_preview()
    
    def init_ui(self):
        """Инициализация пользовательского интерфейса"""
        # Настройки окна
        self.setWindowTitle("Create Write from ARRI Metadata")
        self.setMinimumSize(900, 1000)
        
        # Устанавливаем иконку окна (если есть)
        try:
            self.setWindowIcon(QtGui.QIcon(nuke.getFileName('nuke')))
        except:
            pass
        
        # Основной layout
        main_layout = QtWidgets.QVBoxLayout()
        
        # Создаем скроллируемую область
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout(scroll_content)
        
        # Заголовок
        title_label = QtWidgets.QLabel("<h2>Создание Write нод из метаданных ARRI</h2>")
        title_label.setAlignment(QtCore.Qt.AlignCenter)
        scroll_layout.addWidget(title_label)
        
        # Разделитель
        scroll_layout.addWidget(self.create_horizontal_line())
        
        # Группа для полей метаданных
        metadata_group = QtWidgets.QGroupBox("Поля метаданных и переопределения")
        metadata_group_layout = QtWidgets.QGridLayout()
        
        # Камера
        metadata_group_layout.addWidget(QtWidgets.QLabel("Поле метаданных камеры:"), 0, 0)
        self.camera_meta_field = QtWidgets.QLineEdit(self.default_camera_field)
        self.camera_meta_field.setToolTip("Поле метаданных для получения модели камеры")
        metadata_group_layout.addWidget(self.camera_meta_field, 0, 1)
        
        metadata_group_layout.addWidget(QtWidgets.QLabel("Значение (переопределение):"), 1, 0)
        self.camera_override = QtWidgets.QLineEdit()
        self.camera_override.setPlaceholderText("Оставьте пустым для использования метаданных")
        self.camera_override.setToolTip("Если заполнено, будет использовано это значение вместо метаданных")
        metadata_group_layout.addWidget(self.camera_override, 1, 1)
        
        # Линза
        metadata_group_layout.addWidget(QtWidgets.QLabel("Поле метаданных линзы:"), 2, 0)
        self.lens_meta_field = QtWidgets.QLineEdit(self.default_lens_field)
        metadata_group_layout.addWidget(self.lens_meta_field, 2, 1)
        
        metadata_group_layout.addWidget(QtWidgets.QLabel("Значение (переопределение):"), 3, 0)
        self.lens_override = QtWidgets.QLineEdit()
        self.lens_override.setPlaceholderText("Оставьте пустым для использования метаданных")
        metadata_group_layout.addWidget(self.lens_override, 3, 1)
        
        # Фокусное расстояние
        metadata_group_layout.addWidget(QtWidgets.QLabel("Поле фокусного расстояния:"), 4, 0)
        self.focal_meta_field = QtWidgets.QLineEdit(self.default_focal_field)
        metadata_group_layout.addWidget(self.focal_meta_field, 4, 1)
        
        metadata_group_layout.addWidget(QtWidgets.QLabel("Значение (переопределение):"), 5, 0)
        self.focal_override = QtWidgets.QLineEdit()
        self.focal_override.setPlaceholderText("Оставьте пустым для использования метаданных")
        metadata_group_layout.addWidget(self.focal_override, 5, 1)
        
        # Дистанция
        metadata_group_layout.addWidget(QtWidgets.QLabel("Поле дистанции фокусировки:"), 6, 0)
        self.distance_meta_field = QtWidgets.QLineEdit(self.default_distance_field)
        metadata_group_layout.addWidget(self.distance_meta_field, 6, 1)
        
        metadata_group_layout.addWidget(QtWidgets.QLabel("Значение (переопределение):"), 7, 0)
        self.distance_override = QtWidgets.QLineEdit()
        self.distance_override.setPlaceholderText("Оставьте пустым для использования метаданных")
        self.distance_override.setToolTip("Значение -1 будет интерпретировано как 100m")
        metadata_group_layout.addWidget(self.distance_override, 7, 1)
        
        # Единицы измерения для дистанции
        metadata_group_layout.addWidget(QtWidgets.QLabel("Единицы измерения дистанции:"), 8, 0)
        self.distance_units_combo = QtWidgets.QComboBox()
        self.distance_units_combo.addItems(["Авто", "Метры", "Миллиметры"])
        self.distance_units_combo.setToolTip(
            "Авто: автоматическое определение (mm > 100 конвертируются в метры)\n"
            "Метры: считаем, что значения уже в метрах\n"
            "Миллиметры: считаем, что значения в миллиметрах и конвертируем в метры"
        )
        metadata_group_layout.addWidget(self.distance_units_combo, 8, 1)
        
        metadata_group.setLayout(metadata_group_layout)
        scroll_layout.addWidget(metadata_group)
        
        # Разделитель
        scroll_layout.addSpacing(10)
        
        # Группа для настроек пути
        path_group = QtWidgets.QGroupBox("Настройки пути")
        path_group_layout = QtWidgets.QVBoxLayout()
        
        # Базовый путь
        base_path_layout = QtWidgets.QHBoxLayout()
        base_path_layout.addWidget(QtWidgets.QLabel("Базовый путь:"))
        self.base_path = QtWidgets.QLineEdit("/studio/proj/ANNA/work/GRIDS/layers/")
        self.base_path.setMinimumWidth(400)
        base_path_layout.addWidget(self.base_path)
        
        self.browse_btn = QtWidgets.QPushButton("Обзор...")
        base_path_layout.addWidget(self.browse_btn)
        path_group_layout.addLayout(base_path_layout)
        
        # Пример пути
        preview_layout = QtWidgets.QVBoxLayout()
        preview_layout.addWidget(QtWidgets.QLabel("Пример пути:"))
        self.preview_path = QtWidgets.QLineEdit()
        self.preview_path.setReadOnly(True)
        self.preview_path.setStyleSheet("""
            QLineEdit {
                background-color: #202020;
                border: 1px solid #a0a0a0;
                padding: 5px;
                font-family: monospace;
                color: #eeeeee;
            }
        """)
        preview_layout.addWidget(self.preview_path)
        path_group_layout.addLayout(preview_layout)
        
        # Информация о структуре пути
        info_label = QtWidgets.QLabel(
            "Структура пути: <b>БАЗОВЫЙ_ПУТЬ/CAMERA_LENS_FOCAL/CAMERA_LENS_FOCAL_DISTANCE.jpg</b><br>"
            "• Дистанции конвертируются в метры (980mm → 0.98m)<br>"
            "• Значение -1 интерпретируется как 100m<br>"
            "• Числовые значения округляются до 3 знаков после запятой"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("""
            QLabel {
                background-color: #202020;
                border: 1px solid #b6e0fe;
                border-radius: 3px;
                padding: 8px;
                margin-top: 10px;
            }
        """)
        path_group_layout.addWidget(info_label)
        
        path_group.setLayout(path_group_layout)
        scroll_layout.addWidget(path_group)
        
        # Разделитель
        scroll_layout.addSpacing(10)
        
        # Группа для настроек JPG
        jpg_group = QtWidgets.QGroupBox("Настройки JPG")
        jpg_group_layout = QtWidgets.QGridLayout()
        
        # Качество
        jpg_group_layout.addWidget(QtWidgets.QLabel("Качество (0.0-1.0):"), 0, 0)
        self.jpeg_quality = QtWidgets.QDoubleSpinBox()
        self.jpeg_quality.setRange(0.0, 1.0)
        self.jpeg_quality.setValue(1.0)
        self.jpeg_quality.setSingleStep(0.1)
        self.jpeg_quality.setDecimals(2)
        self.jpeg_quality.setToolTip("1.0 - максимальное качество")
        jpg_group_layout.addWidget(self.jpeg_quality, 0, 1)
        
        # Субсэмплинг
        jpg_group_layout.addWidget(QtWidgets.QLabel("Субсэмплинг:"), 1, 0)
        self.subsampling = QtWidgets.QComboBox()
        self.subsampling.addItems(["4:4:4", "4:2:2", "4:2:0"])
        self.subsampling.setToolTip("4:4:4 - без сжатия цвета, лучшее качество")
        jpg_group_layout.addWidget(self.subsampling, 1, 1)
        
        jpg_group.setLayout(jpg_group_layout)
        scroll_layout.addWidget(jpg_group)
        
        # Разделитель
        scroll_layout.addSpacing(10)
        
        # Дополнительные настройки
        advanced_group = QtWidgets.QGroupBox("Дополнительные настройки")
        advanced_layout = QtWidgets.QVBoxLayout()
        
        self.test_mode = QtWidgets.QCheckBox("Тестовый режим (без создания нод)")
        self.test_mode.setToolTip("Только проверка путей без создания Write нод")
        advanced_layout.addWidget(self.test_mode)
        
        advanced_group.setLayout(advanced_layout)
        scroll_layout.addWidget(advanced_group)
        
        # Добавляем спейсер в конце
        scroll_layout.addStretch()
        
        # Устанавливаем содержимое скроллируемой области
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)
        
        # Панель кнопок
        button_layout = QtWidgets.QHBoxLayout()
        
        # Кнопка "Показать метаданные"
        self.metadata_btn = QtWidgets.QPushButton("Показать метаданные")
        self.metadata_btn.setMinimumHeight(40)
        self.metadata_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        
        # Кнопка "Создать Write ноды"
        self.create_btn = QtWidgets.QPushButton("Создать Write ноды")
        self.create_btn.setMinimumHeight(40)
        self.create_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        
        # Кнопка "Закрыть"
        self.cancel_btn = QtWidgets.QPushButton("Закрыть")
        self.cancel_btn.setMinimumHeight(40)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        
        button_layout.addWidget(self.metadata_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.create_btn)
        button_layout.addWidget(self.cancel_btn)
        
        main_layout.addLayout(button_layout)
        
        # Информационная панель внизу
        status_bar = QtWidgets.QStatusBar()
        status_bar.showMessage("Готово. Выделите Read ноды для создания Write нод.")
        main_layout.addWidget(status_bar)
        
        # Устанавливаем layout для окна
        self.setLayout(main_layout)
        
        # Устанавливаем окно поверх других окон
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowStaysOnTopHint)
    
    def create_horizontal_line(self):
        """Создает горизонтальную линию-разделитель"""
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        line.setStyleSheet("background-color: #ddd;")
        return line
    
    def setup_connections(self):
        """Настройка сигналов и слотов"""
        # Кнопки
        self.create_btn.clicked.connect(self.create_writes)
        self.cancel_btn.clicked.connect(self.close)
        self.browse_btn.clicked.connect(self.browse_path)
        self.metadata_btn.clicked.connect(self.show_metadata_summary)
        
        # Обновление превью при изменении полей
        self.camera_override.textChanged.connect(self.update_preview)
        self.lens_override.textChanged.connect(self.update_preview)
        self.focal_override.textChanged.connect(self.update_preview)
        self.distance_override.textChanged.connect(self.update_preview)
        self.base_path.textChanged.connect(self.update_preview)
        self.distance_units_combo.currentTextChanged.connect(self.update_preview)
    
    def sanitize_filename(self, text):
        """Очищает строку для использования в имени файла"""
        if not text:
            return "Unknown"
        
        # Удаляем начальные и конечные пробелы
        text = str(text).strip()
        
        # Заменяем недопустимые символы
        text = re.sub(r'[\\/*?:"<>|]', '_', text)
        
        # Заменяем только пробелы на подчеркивания, точки оставляем
        text = re.sub(r'\s+', '_', text)
        
        # Удаляем несколько подчеркиваний подряд
        text = re.sub(r'_+', '_', text)
        
        # Удаляем подчеркивания в начале и конце
        text = text.strip('_')
        
        return text
    
    def sanitize_nodename(self, text):
        """Очищает строку для использования в имени ноды Nuke"""
        if not text:
            return "Unknown"
        
        # Удаляем начальные и конечные пробелы
        text = str(text).strip()
        
        # В именах нод Nuke нельзя использовать: ., ", ', /, \, :, ;, *, ?, <, >, |, [, ], (, ), {, }, @, !, ~, `, #
        # Также нельзя начинать с цифры
        text = re.sub(r'[\\/*?:"<>|\[\](){}\'~`@!;#]', '_', text)
        
        # Заменяем только пробелы на подчеркивания, а точки оставляем
        text = re.sub(r'\s+', '_', text)
        
        # Удаляем несколько подчеркиваний подряд
        text = re.sub(r'_+', '_', text)
        
        # Удаляем подчеркивания в начале и конце
        text = text.strip('_')
        
        # Если начинается с цифры, добавляем префикс
        if text and text[0].isdigit():
            text = 'N' + text
            
        return text
    
    def format_distance_value(self, distance_value):
        """Форматирует значение дистанции: конвертирует mm в метры и округляет до 3 знаков после запятой"""
        if not distance_value:
            return "Unknown"
        
        # Получаем выбранные единицы измерения
        units_mode = self.distance_units_combo.currentText()
        
        # Преобразуем в строку и удаляем пробелы
        distance_str = str(distance_value).strip()
        
        # Проверяем на специальное значение -1
        if distance_str in ["-1", "-1.0", "-1.00", "-1.000", "-1 mm", "-1.0 mm", "-1.00 mm"]:
            return "100m"  # Специальное значение -1 означает 100 метров
        
        # Также проверяем, если строка начинается с -1 (с любыми символами после)
        if distance_str.startswith("-1") and any(c.isdigit() or c == '.' for c in distance_str[:3]):
            # Проверяем, что дальше идет либо конец строки, либо пробел, либо mm
            cleaned = distance_str.replace(" ", "").replace("mm", "")
            try:
                # Пробуем преобразовать в число
                num = float(cleaned)
                if abs(num + 1.0) < 0.001:  # Проверяем, что число близко к -1
                    return "100m"
            except:
                pass
        
        # Пробуем извлечь числовое значение из строки
        # Ищем паттерн числа (возможно с десятичными знаками)
        match = re.search(r'([-+]?\d*\.?\d+)', distance_str)
        
        if match:
            num_value = float(match.group(1))
            
            # Проверяем на -1 после извлечения числа
            if abs(num_value + 1.0) < 0.001:  # Если число близко к -1
                return "100m"
            
            # Если значение отрицательное, возвращаем как есть (после санитизации)
            if num_value < 0:
                return self.sanitize_filename(distance_str)
            
            # Обработка в зависимости от выбранного режима единиц измерения
            if units_mode == "Метры":
                # Режим "Метры": считаем, что значение уже в метрах
                # Округляем до 3 знаков после запятой
                rounded_value = round(num_value, 3)
                # Форматируем, удаляя незначащие нули, но сохраняя точку
                formatted = f"{rounded_value:.3f}".rstrip('0').rstrip('.')
                # Добавляем "m" только если его еще нет в строке
                if 'm' not in distance_str.lower():
                    return f"{formatted}m" if formatted else "0m"
                else:
                    return formatted if formatted else "0"
            
            elif units_mode == "Миллиметры":
                # Режим "Миллиметры": считаем, что значение в миллиметрах и конвертируем в метры
                meters_value = num_value / 1000.0
                # Округляем до 3 знаков после запятой
                rounded_value = round(meters_value, 3)
                # Форматируем, удаляя незначащие нули, но сохраняя точку
                formatted = f"{rounded_value:.3f}".rstrip('0').rstrip('.')
                return f"{formatted}m" if formatted else "0m"
            
            else:
                # Режим "Авто": автоматическое определение
                # Если в строке есть 'mm' или значение больше 100 (предполагаем мм), конвертируем в метры
                if 'mm' in distance_str.lower() or num_value > 100:
                    # Конвертируем мм в метры
                    meters_value = num_value / 1000.0
                    # Округляем до 3 знаков после запятой
                    rounded_value = round(meters_value, 3)
                    # Форматируем, удаляя незначащие нули, но сохраняя точку
                    formatted = f"{rounded_value:.3f}".rstrip('0').rstrip('.')
                    return f"{formatted}m" if formatted else "0m"
                else:
                    # Если уже в метрах или другом формате, проверяем, есть ли точка
                    # Если это просто число с точкой, возвращаем как есть
                    if '.' in distance_str:
                        # Проверяем, что это действительно число с плавающей точкой
                        try:
                            # Округляем до 3 знаков после запятой
                            num = float(distance_str)
                            rounded_value = round(num, 3)
                            # Форматируем, удаляя незначащие нули, но сохраняя точку
                            formatted = f"{rounded_value:.3f}".rstrip('0').rstrip('.')
                            # Добавляем "m" только если его еще нет в строке
                            if 'm' not in distance_str.lower():
                                return f"{formatted}m" if formatted else "0m"
                            else:
                                return formatted if formatted else "0"
                        except:
                            pass
                    # Если нет точки или не удалось преобразовать
                    try:
                        # Пробуем преобразовать в число и округлить
                        num = float(distance_str)
                        rounded_value = round(num, 3)
                        # Форматируем, удаляя незначащие нули, но сохраняя точку
                        formatted = f"{rounded_value:.3f}".rstrip('0').rstrip('.')
                        # Добавляем "m" только если его еще нет в строке
                        if 'm' not in distance_str.lower():
                            return f"{formatted}m" if formatted else "0m"
                        else:
                            return formatted if formatted else "0"
                    except:
                        pass
                    
                    # Если не число, возвращаем санитизированную строку
                    return self.sanitize_filename(distance_str)
        else:
            # Если не нашли число, возвращаем санитизированную строку
            return self.sanitize_filename(distance_str)
    
    def browse_path(self):
        """Открывает диалог выбора папки"""
        # Получаем главное окно Nuke как родительское
        nuke_main_window = None
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if widget.objectName() == "Foundry::UI::DockMainWindow":
                nuke_main_window = widget
                break
        
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self if nuke_main_window is None else nuke_main_window,
            "Выберите базовую папку",
            self.base_path.text()
        )
        
        if folder:
            self.base_path.setText(folder)
    
    def update_preview(self):
        """Обновляет пример пути"""
        try:
            # Получаем значения из полей
            camera_val = self.camera_override.text() or "ALEXA_Mini_LF"
            lens_val = self.lens_override.text() or "ATX_35mm"
            focal_val = self.focal_override.text() or "35mm"
            distance_val = self.distance_override.text() or "2m"
            
            # Очищаем значения
            camera = self.sanitize_filename(camera_val)
            lens = self.sanitize_filename(lens_val)
            focal = self.sanitize_filename(focal_val)
            # Для превью пути также форматируем дистанцию
            distance = self.format_distance_value(distance_val)
            
            # Формируем путь: папка БЕЗ DISTANCE, файл С DISTANCE
            base_path = self.base_path.text()
            folder_name = f"{camera}_{lens}_{focal}"  # Без DISTANCE
            file_name = f"{camera}_{lens}_{focal}_{distance}.jpg"  # С DISTANCE
            preview = os.path.join(base_path, folder_name, file_name).replace("\\", "/")
            
            self.preview_path.setText(preview)
        except Exception as e:
            print(f"Ошибка при обновлении превью: {e}")
    
    def get_field_value(self, metadata, meta_field, override_value, default_name, is_distance=False):
        """Получает значение поля из метаданных или переопределения"""
        # Если есть переопределение, используем его
        if override_value and override_value.strip():
            value = override_value.strip()
        else:
            # Иначе пытаемся получить из метаданных
            value = metadata.get(meta_field, None)
            
            if value is None:
                # Если в метаданных нет, используем название поля как значение
                value = default_name
        
        # Если это поле дистанции, форматируем его
        if is_distance:
            return self.format_distance_value(value)
        else:
            # Для не-дистанций используем стандартную санитизацию
            return self.sanitize_filename(value)
    
    def show_metadata_summary(self):
        """Показывает метаданные выделенных Read нод"""
        selected_nodes = nuke.selectedNodes()
        read_nodes = [node for node in selected_nodes if node.Class() == 'Read']
        
        if not read_nodes:
            QtWidgets.QMessageBox.warning(
                self, "Внимание", 
                "Выделите Read ноды для просмотра метаданных!"
            )
            return
        
        # Создаем диалоговое окно
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Метаданные Read нод")
        dialog.setMinimumSize(800, 600)
        
        layout = QtWidgets.QVBoxLayout()
        
        # Кнопки фильтрации
        filter_layout = QtWidgets.QHBoxLayout()
        filter_label = QtWidgets.QLabel("Фильтр:")
        filter_input = QtWidgets.QLineEdit()
        filter_input.setPlaceholderText("Введите текст для поиска в метаданных...")
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(filter_input)
        layout.addLayout(filter_layout)
        
        # Текстовое поле для вывода метаданных
        text_edit = QtWidgets.QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet("""
            QTextEdit {
                font-family: 'Courier New', monospace;
                font-size: 10pt;
            }
        """)
        
        summary = self.generate_metadata_summary(read_nodes)
        text_edit.setText(summary)
        layout.addWidget(text_edit)
        
        # Функция фильтрации
        def filter_metadata():
            filter_text = filter_input.text().lower()
            if not filter_text:
                text_edit.setText(summary)
                return
            
            lines = summary.split('\n')
            filtered_lines = []
            for line in lines:
                if filter_text in line.lower():
                    filtered_lines.append(line)
            
            text_edit.setText('\n'.join(filtered_lines) if filtered_lines else "Нет совпадений")
        
        filter_input.textChanged.connect(filter_metadata)
        
        # Кнопки
        button_layout = QtWidgets.QHBoxLayout()
        
        copy_btn = QtWidgets.QPushButton("Копировать в буфер")
        copy_btn.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(text_edit.toPlainText()))
        
        export_btn = QtWidgets.QPushButton("Экспорт в файл...")
        export_btn.clicked.connect(lambda: self.export_metadata(summary))
        
        close_btn = QtWidgets.QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.close)
        
        button_layout.addWidget(copy_btn)
        button_layout.addWidget(export_btn)
        button_layout.addStretch()
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
        
        dialog.setLayout(layout)
        
        # Устанавливаем окно поверх других
        dialog.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowStaysOnTopHint)
        dialog.exec_()
    
    def generate_metadata_summary(self, read_nodes):
        """Генерирует сводку метаданных для Read нод"""
        # Получаем текущие настройки полей из интерфейса
        camera_meta = self.camera_meta_field.text() or self.default_camera_field
        lens_meta = self.lens_meta_field.text() or self.default_lens_field
        focal_meta = self.focal_meta_field.text() or self.default_focal_field
        distance_meta = self.distance_meta_field.text() or self.default_distance_field
        
        summary = "=" * 80 + "\n"
        summary += "МЕТАДАННЫЕ ВЫДЕЛЕННЫХ READ НОД\n"
        summary += "=" * 80 + "\n\n"
        
        fields = [
            (camera_meta, "Камера"),
            (lens_meta, "Линза"),
            (focal_meta, "Фокусное"),
            (distance_meta, "Дистанция (оригинал)"),
        ]
        
        for i, read_node in enumerate(read_nodes):
            metadata = read_node.metadata()
            summary += f"{i+1}. {read_node.name()}:\n"
            summary += "-" * 40 + "\n"
            
            for field, name in fields:
                value = metadata.get(field, "Нет данных")
                summary += f"   • {name} ({field}): {value}\n"
            
            # Добавляем информацию о конвертации дистанции
            distance_value = metadata.get(distance_meta, None)
            if distance_value:
                # Получаем текущий режим единиц измерения
                units_mode = self.distance_units_combo.currentText()
                summary += f"   • Режим единиц измерения: {units_mode}\n"
                
                # Пробуем конвертировать
                try:
                    # Проверяем специальное значение -1
                    distance_str = str(distance_value).strip()
                    if distance_str in ["-1", "-1.0", "-1.00", "-1.000", "-1 mm", "-1.0 mm", "-1.00 mm"]:
                        summary += f"   • Дистанция (интерпретация): 100m (специальное значение -1)\n"
                    else:
                        # Извлекаем числовое значение
                        match = re.search(r'([-+]?\d*\.?\d+)', str(distance_value))
                        if match:
                            num_value = float(match.group(1))
                            if abs(num_value + 1.0) < 0.001:
                                summary += f"   • Дистанция (интерпретация): 100m (специальное значение -1)\n"
                            elif units_mode == "Метры":
                                rounded_value = round(num_value, 3)
                                formatted = f"{rounded_value:.3f}".rstrip('0').rstrip('.')
                                summary += f"   • Дистанция (в метрах): {formatted}m (принудительно в метрах)\n"
                            elif units_mode == "Миллиметры":
                                meters_value = num_value / 1000.0
                                rounded_value = round(meters_value, 3)
                                formatted = f"{rounded_value:.3f}".rstrip('0').rstrip('.')
                                summary += f"   • Дистанция (в метрах): {formatted}m (конвертировано из мм)\n"
                            else:  # Авто
                                if 'mm' in str(distance_value).lower() or num_value > 100:
                                    meters_value = num_value / 1000.0
                                    rounded_value = round(meters_value, 3)
                                    formatted = f"{rounded_value:.3f}".rstrip('0').rstrip('.')
                                    summary += f"   • Дистанция (в метрах): {formatted}m (автоконвертация из мм)\n"
                                else:
                                    rounded_value = round(num_value, 3)
                                    formatted = f"{rounded_value:.3f}".rstrip('0').rstrip('.')
                                    summary += f"   • Дистанция (в метрах): {formatted}m (уже в метрах)\n"
                except:
                    pass
            
            # Добавляем информацию о переопределениях
            if self.camera_override.text():
                summary += f"   • Камера (переопределение): {self.camera_override.text()}\n"
            if self.lens_override.text():
                summary += f"   • Линза (переопределение): {self.lens_override.text()}\n"
            if self.focal_override.text():
                summary += f"   • Фокусное (переопределение): {self.focal_override.text()}\n"
            if self.distance_override.text():
                distance_override_formatted = self.format_distance_value(self.distance_override.text())
                summary += f"   • Дистанция (переопределение): {self.distance_override.text()} → {distance_override_formatted}\n"
            
            summary += "\n"
        
        return summary
    
    def show_all_metadata(self, read_node):
        """Показывает все метаданные для конкретной Read ноды"""
        metadata = read_node.metadata()
        
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Все метаданные: {read_node.name()}")
        dialog.setMinimumSize(900, 700)
        
        layout = QtWidgets.QVBoxLayout()
        
        # Фильтр
        filter_layout = QtWidgets.QHBoxLayout()
        filter_label = QtWidgets.QLabel("Поиск:")
        filter_input = QtWidgets.QLineEdit()
        filter_input.setPlaceholderText("Фильтр по ключам или значениям...")
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(filter_input)
        layout.addLayout(filter_layout)
        
        # Таблица метаданных
        table = QtWidgets.QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Ключ", "Значение"])
        table.horizontalHeader().setStretchLastSection(True)
        
        # Заполняем таблицу
        keys = sorted(metadata.keys())
        table.setRowCount(len(keys))
        
        for row, key in enumerate(keys):
            value = metadata[key]
            
            key_item = QtWidgets.QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() & ~QtCore.Qt.ItemIsEditable)
            
            value_item = QtWidgets.QTableWidgetItem(str(value))
            value_item.setFlags(value_item.flags() & ~QtCore.Qt.ItemIsEditable)
            
            table.setItem(row, 0, key_item)
            table.setItem(row, 1, value_item)
        
        layout.addWidget(table)
        
        # Функция фильтрации
        def filter_table():
            filter_text = filter_input.text().lower()
            for row in range(table.rowCount()):
                key = table.item(row, 0).text().lower()
                value = table.item(row, 1).text().lower()
                show = filter_text in key or filter_text in value
                table.setRowHidden(row, not show)
        
        filter_input.textChanged.connect(filter_table)
        
        # Кнопки
        button_layout = QtWidgets.QHBoxLayout()
        
        copy_btn = QtWidgets.QPushButton("Копировать ключ")
        copy_btn.clicked.connect(lambda: self.copy_selected_key(table))
        
        close_btn = QtWidgets.QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.close)
        
        button_layout.addWidget(copy_btn)
        button_layout.addStretch()
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
        
        dialog.setLayout(layout)
        dialog.exec_()
    
    def copy_selected_key(self, table):
        """Копирует выбранный ключ метаданных в буфер обмена"""
        selected_items = table.selectedItems()
        if selected_items:
            key = selected_items[0].text()
            QtWidgets.QApplication.clipboard().setText(key)
            QtWidgets.QMessageBox.information(self, "Скопировано", f"Ключ '{key}' скопирован в буфер обмена")
    
    def export_metadata(self, summary):
        """Экспортирует метаданные в файл"""
        # Получаем главное окно Nuke как родительское
        nuke_main_window = None
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if widget.objectName() == "Foundry::UI::DockMainWindow":
                nuke_main_window = widget
                break
        
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self if nuke_main_window is None else nuke_main_window,
            "Экспорт метаданных",
            "metadata_summary.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(summary)
                QtWidgets.QMessageBox.information(self, "Успех", f"Метаданные экспортированы в:\n{file_path}")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Ошибка", f"Не удалось экспортировать файл:\n{str(e)}")
    
    def create_writes(self):
        """Создает Write ноды для выделенных Read нод"""
        try:
            selected_nodes = nuke.selectedNodes()
            read_nodes = [node for node in selected_nodes if node.Class() == 'Read']
            
            if not read_nodes:
                QtWidgets.QMessageBox.warning(
                    self, "Внимание", 
                    "Пожалуйста, выделите хотя бы одну Read ноду!"
                )
                return
            
            # Получаем значения из UI
            base_path = self.base_path.text()
            quality = self.jpeg_quality.value()
            test_mode = self.test_mode.isChecked()
            
            # Маппинг субсэмплинга
            subsampling_map = {"4:4:4": 0, "4:2:2": 1, "4:2:0": 2}
            subsampling_value = subsampling_map.get(self.subsampling.currentText(), 0)
            
            # Получаем настройки полей метаданных
            camera_meta = self.camera_meta_field.text() or self.default_camera_field
            lens_meta = self.lens_meta_field.text() or self.default_lens_field
            focal_meta = self.focal_meta_field.text() or self.default_focal_field
            distance_meta = self.distance_meta_field.text() or self.default_distance_field
            
            # Получаем значения переопределения
            camera_override = self.camera_override.text()
            lens_override = self.lens_override.text()
            focal_override = self.focal_override.text()
            distance_override = self.distance_override.text()
            
            created_nodes = []
            errors = []
            
            # Прогресс бар
            progress_dialog = None
            if not test_mode and len(read_nodes) > 1:
                progress_dialog = QtWidgets.QProgressDialog(
                    "Создание Write нод...", "Отмена", 0, len(read_nodes), self
                )
                progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
                progress_dialog.setWindowTitle("Прогресс")
                progress_dialog.show()
            
            # Начинаем операцию Undo для группировки всех изменений
            nuke.Undo().begin("Create Write Nodes from Metadata")
            
            try:
                for i, read_node in enumerate(read_nodes):
                    if progress_dialog and progress_dialog.wasCanceled():
                        break
                    
                    if progress_dialog:
                        progress_dialog.setValue(i)
                        progress_dialog.setLabelText(f"Обработка: {read_node.name()} ({i+1}/{len(read_nodes)})")
                        QtWidgets.QApplication.processEvents()
                    
                    try:
                        # Получаем метаданные Read ноды
                        metadata = read_node.metadata()
                        
                        # Получаем значения для каждого поля
                        camera = self.get_field_value(metadata, camera_meta, camera_override, "CAMERA", is_distance=False)
                        lens = self.get_field_value(metadata, lens_meta, lens_override, "LENS", is_distance=False)
                        focal = self.get_field_value(metadata, focal_meta, focal_override, "FOCAL", is_distance=False)
                        distance = self.get_field_value(metadata, distance_meta, distance_override, "DISTANCE", is_distance=True)
                        
                        # Формируем путь: папка БЕЗ DISTANCE, файл С DISTANCE
                        folder_name = f"{camera}_{lens}_{focal}"  # Без DISTANCE
                        file_name = f"{camera}_{lens}_{focal}_{distance}.jpg"  # С DISTANCE
                        full_path = os.path.join(base_path, folder_name, file_name).replace("\\", "/")
                        
                        if test_mode:
                            print(f"Тестовый режим - путь для {read_node.name()}:")
                            print(f"  Папка: {folder_name}")
                            print(f"  Файл: {file_name}")
                            print(f"  Полный путь: {full_path}")
                            
                            # Выводим отладочную информацию о дистанции
                            original_distance = metadata.get(distance_meta, "Нет данных")
                            print(f"  Исходное значение дистанции: {original_distance}")
                            print(f"  Сформатированная дистанция: {distance}")
                            continue
                        
                        # Отключаем обновление UI для предотвращения мигания
                        nuke.Root().begin()
                        
                        # Создаем Write ноду без открытия панели
                        write_node = nuke.createNode("Write", inpanel=False)
                        write_node.hideControlPanel()  # Скрываем панель, если она открылась
                        
                        # Создаем безопасное имя для ноды
                        node_name_base = f"Write_{camera}_{lens}_{focal}"
                        safe_node_name = self.sanitize_nodename(node_name_base)
                        
                        # Проверяем, не слишком ли длинное имя
                        if len(safe_node_name) > 50:
                            safe_node_name = safe_node_name[:50]
                        
                        # Добавляем номер, если это не первая нода с таким именем
                        counter = 1
                        original_safe_name = safe_node_name
                        while nuke.toNode(safe_node_name) is not None:
                            safe_node_name = f"{original_safe_name}_{counter}"
                            counter += 1
                        
                        try:
                            write_node.setName(safe_node_name)
                        except:
                            # Если все еще ошибка, используем простое имя с индексом
                            write_node.setName(f"Write_{i+1}")
                        
                        write_node["file"].setValue(full_path)
                        write_node["file_type"].setValue("jpg")
                        write_node["create_directories"].setValue(True)
                        
                        # Устанавливаем качество
                        quality_params = ["_jpeg_quality", "quality", "_quality"]
                        quality_set = False
                        for param in quality_params:
                            if param in write_node.knobs():
                                write_node[param].setValue(quality)
                                quality_set = True
                                break
                        
                        if not quality_set:
                            try:
                                write_node.knob("_jpeg_quality").setValue(quality)
                            except:
                                print(f"Предупреждение: Не удалось установить качество для {write_node.name()}")
                        
                        # Устанавливаем субсэмплинг
                        subsampling_params = ["_jpeg_sub_sampling", "_jpeg_subsampling", "subsampling", "_subsampling"]
                        subsampling_set = False
                        for param in subsampling_params:
                            if param in write_node.knobs():
                                knob = write_node[param]
                                knob_type = knob.Class()
                                
                                if knob_type == "Int_Knob":
                                    knob.setValue(subsampling_value)
                                elif knob_type == "String_Knob" or knob_type == "Enumeration_Knob":
                                    try:
                                        knob.setValue(str(subsampling_value))
                                    except:
                                        try:
                                            knob.setValue(subsampling_value)
                                        except:
                                            pass
                                subsampling_set = True
                                break
                        
                        if not subsampling_set:
                            try:
                                write_node.knob("_jpeg_sub_sampling").setValue(subsampling_value)
                            except:
                                try:
                                    write_node.knob("_jpeg_subsampling").setValue(subsampling_value)
                                except:
                                    print(f"Предупреждение: Не удалось установить субсэмплинг для {write_node.name()}")
                        
                        # ПОЗИЦИОНИРУЕМ Write ноду НИЖЕ Read ноды - на 500 единиц
                        read_x = read_node.xpos()
                        read_y = read_node.ypos()
                        
                        # Устанавливаем позицию Write ноды
                        write_node.setXpos(int(read_x))
                        write_node.setYpos(int(read_y + 500))  # Опускаем на 500 единиц ниже
                        
                        # Подключаем Write ноду к Read ноде
                        write_node.setInput(0, read_node)
                        
                        # Завершаем обновление UI
                        nuke.Root().end()
                        
                        created_nodes.append((read_node.name(), write_node.name(), full_path, distance, folder_name, file_name))
                        
                        # Выводим информацию в консоль
                        print(f"Создана Write нода: {write_node.name()}")
                        print(f"  Источник: {read_node.name()}")
                        print(f"  Папка: {folder_name}")
                        print(f"  Файл: {file_name}")
                        print(f"  Полный путь: {full_path}")
                        print(f"  Качество: {quality}, Субсэмплинг: {self.subsampling.currentText()}")
                        print(f"  Параметры: Camera={camera}, Lens={lens}, Focal={focal}, Distance={distance}")
                        
                        # Добавляем информацию об исходном значении дистанции
                        original_distance = metadata.get(distance_meta, "Нет данных")
                        print(f"  Исходная дистанция из метаданных: {original_distance}")
                        print(f"  Режим единиц измерения: {self.distance_units_combo.currentText()}")
                        
                        print("-" * 60)
                        
                    except Exception as e:
                        error_msg = f"Ошибка при создании Write ноды для {read_node.name()}: {str(e)}"
                        errors.append(error_msg)
                        print(error_msg)
                        import traceback
                        traceback.print_exc()
            
            finally:
                # Завершаем операцию Undo
                nuke.Undo().end()
                
                if progress_dialog:
                    progress_dialog.close()
            
            # Выводим итоговый отчет
            if not test_mode:
                if created_nodes:
                    # Создаем диалоговое окно с отчетом
                    report_dialog = QtWidgets.QDialog(self)
                    report_dialog.setWindowTitle("Отчет о создании Write нод")
                    report_dialog.setMinimumSize(500, 400)
                    
                    report_layout = QtWidgets.QVBoxLayout()
                    
                    # Заголовок
                    title_label = QtWidgets.QLabel(f"<h3>Успешно создано {len(created_nodes)} Write нод:</h3>")
                    report_layout.addWidget(title_label)
                    
                    # Список созданных нод
                    node_list = QtWidgets.QTextEdit()
                    node_list.setReadOnly(True)
                    
                    report_text = ""
                    for read_name, write_name, path, distance, folder_name, file_name in created_nodes:
                        report_text += f"• {read_name} → {write_name}\n"
                    
                    # Добавляем информацию о структуре пути
                    report_text += f"\nСтруктура пути:\n"
                    report_text += f"  - Папка: CAMERA_LENS_FOCAL\n"
                    report_text += f"  - Файл: CAMERA_LENS_FOCAL_DISTANCE.jpg\n"
                    report_text += f"  - Дистанции конвертируются в метры\n"
                    report_text += f"  - Специальное значение -1 интерпретируется как 100m\n"
                    report_text += f"  - Режим единиц измерения: {self.distance_units_combo.currentText()}\n"
                    report_text += f"  - Числовые значения округляются до 3 знаков после запятой\n"
                    
                    # Добавляем информацию о специальных значениях дистанции
                    special_distances = []
                    for read_name, write_name, path, distance, folder_name, file_name in created_nodes:
                        if distance == "100m":
                            special_distances.append(f"  • {read_name}: -1 → 100m")
                    
                    if special_distances:
                        report_text += f"\nОбнаружены специальные значения дистанции:\n"
                        report_text += "\n".join(special_distances)
                    
                    if errors:
                        report_text += f"\n\nОшибки ({len(errors)}):\n"
                        for error in errors:
                            report_text += f"  • {error}\n"
                    
                    node_list.setText(report_text)
                    report_layout.addWidget(node_list)
                    
                    # Кнопки
                    button_layout = QtWidgets.QHBoxLayout()
                    
                    close_btn = QtWidgets.QPushButton("Закрыть")
                    close_btn.clicked.connect(report_dialog.close)
                    
                    button_layout.addStretch()
                    button_layout.addWidget(close_btn)
                    report_layout.addLayout(button_layout)
                    
                    report_dialog.setLayout(report_layout)
                    report_dialog.exec_()
                elif errors:
                    QtWidgets.QMessageBox.critical(
                        self, "Ошибки",
                        f"Произошли ошибки:\n\n" + "\n".join(errors)
                    )
            else:
                QtWidgets.QMessageBox.information(
                    self, "Тестовый режим",
                    f"Тестовый режим завершен.\nПроверено {len(read_nodes)} Read нод.\n\nСмотрите вывод в Script Editor."
                )
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Критическая ошибка",
                f"Произошла критическая ошибка:\n\n{str(e)}"
            )
            import traceback
            traceback.print_exc()

# Глобальная переменная для хранения окна
_write_panel = None

def show_non_blocking_panel():
    """Показывает неблокирующее окно"""
    global _write_panel
    
    # Закрываем старое окно, если оно открыто
    if _write_panel is not None:
        try:
            _write_panel.close()
            _write_panel.deleteLater()
        except:
            pass
        _write_panel = None
    
    # Создаем новое окно
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    
    # Получаем главное окно Nuke
    nuke_main_window = None
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.objectName() == "Foundry::UI::DockMainWindow":
            nuke_main_window = widget
            break
    
    _write_panel = NonBlockingWritePanel(nuke_main_window)
    _write_panel.show()

# Функция для добавления в меню Nuke
def add_to_menu():
    """Добавляет команды в меню Nuke"""
    menu = nuke.menu("Nuke")
    
    # Создаем подменю ARRI, если его нет
    arri_menu = menu.findItem("GRIDS")
    if not arri_menu:
        arri_menu = menu.addMenu("GRIDS")
    
    # Теперь у нас только одна команда, так как все в одном окне
    arri_menu.addCommand("Create Grids Write from Metadata", show_non_blocking_panel)
    arri_menu.addSeparator()

# Автоматическое добавление в меню при запуске скрипта
add_to_menu()

# Если нужно, можно сразу показать окно
# show_non_blocking_panel()