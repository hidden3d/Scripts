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
                             QProgressBar, QGroupBox, QMessageBox, QSpinBox, QGridLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QTextCursor, QColor

class PhotoOrganizerThread(QThread):
    """Поток для организации фотографий без блокировки GUI"""
    log_signal = pyqtSignal(str, str)  # Теперь передаем и текст, и цвет
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)
    metadata_progress_signal = pyqtSignal(int)  # Сигнал для прогресса чтения метаданных
    
    def __init__(self, source_root, exported_root, output_root, 
                 use_suffix, suffix_text, check_without_suffix, 
                 compare_metadata, compare_hash, max_workers, buffer_size_kb,
                 max_retries, retry_delay, source_extensions):
        super().__init__()
        self.source_root = source_root
        self.exported_root = exported_root
        self.output_root = output_root
        self.use_suffix = use_suffix
        self.suffix_text = suffix_text
        self.check_without_suffix = check_without_suffix
        self.compare_metadata_flag = compare_metadata
        self.compare_hash = compare_hash
        self.max_workers = max_workers
        self.buffer_size = buffer_size_kb * 1024  # Конвертируем КБ в байты
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.source_extensions = source_extensions
        self.canceled = False
        
        # Создаем уникальный идентификатор для исходной папки
        source_root_hash = hashlib.md5(source_root.encode()).hexdigest()[:8]
        self.cache_dir = os.path.join(self.output_root, f".metadata_cache_{source_root_hash}")
        
        # Блокировки для файлов, которые уже обрабатываются
        self.file_locks = {}
        self.lock = threading.Lock()
        
    def run(self):
        try:
            self.organize_photos()
            self.finished_signal.emit(True, "Операция завершена успешно!")
        except Exception as e:
            self.finished_signal.emit(False, f"Ошибка: {str(e)}")
    
    def cancel(self):
        self.canceled = True
        self.log_signal.emit("Операция отменена пользователем", "red")
    
    def get_exif_data_optimized(self, image_path):
        """Оптимизированное чтение EXIF-данных с повторными попытками и блокировками"""
        # Используем блокировку для этого конкретного файла
        with self.lock:
            if image_path not in self.file_locks:
                self.file_locks[image_path] = threading.Lock()
        
        with self.file_locks[image_path]:
            retries = 0
            delay = self.retry_delay
            
            while retries < self.max_retries:
                try:
                    with open(image_path, 'rb') as f:
                        # Для RAW файлов читаем больше данных
                        if any(image_path.lower().endswith(ext) for ext in ['.cr2', '.nef', '.arw']):
                            # Читаем первые 256KB для RAW файлов
                            data = f.read(262144)
                        else:
                            # Читаем только первые 64KB файла (где обычно находятся EXIF-данные)
                            data = f.read(65536)
                        
                        # Ищем маркер начала EXIF данных (0xFFE1)
                        exif_start = data.find(b'\xFF\xE1')
                        if exif_start == -1:
                            # Если не нашли EXIF в этом файле, прекращаем попытки
                            return {}
                        
                        # Позиционируемся на начало EXIF данных
                        f.seek(exif_start + 4)  # Пропускаем 4 байта (длина сегмента)
                        
                        # Читаем только EXIF-данные
                        tags = exifread.process_file(f, details=False)
                        
                        # Фильтруем только нужные теги
                        required_tags = ['EXIF DateTimeOriginal', 'EXIF BrightnessValue']
                        result = {tag: tags[tag] for tag in required_tags if tag in tags}
                        
                        # Если получили хоть какие-то метаданные, возвращаем их
                        if result:
                            return result
                        else:
                            # Если метаданные пустые, пробуем еще раз
                            retries += 1
                            if retries < self.max_retries:
                                time.sleep(delay)
                                delay *= 2  # Экспоненциальная задержка
                                
                except Exception as e:
                    # Увеличиваем счетчик попыток и ждем перед следующей попыткой
                    retries += 1
                    if retries < self.max_retries:
                        time.sleep(delay)
                        delay *= 2  # Экспоненциальная задержка
                    else:
                        # Добавляем полный путь к файлу в сообщение об ошибке
                        self.log_signal.emit(f"Ошибка чтения EXIF из файла {image_path} после {self.max_retries} попыток: {str(e)}", "red")
                        return {}
            
            return {}
    
    def read_metadata_parallel(self, file_list):
        """Многопоточное чтение метаданных с ограничением количества одновременных операций"""
        metadata_cache = {}
        
        def read_single_metadata(file_info):
            path, name = file_info
            return path, self.get_exif_data_optimized(path)
        
        # Ограничиваем количество одновременных операций чтения метаданных
        # чтобы избежать конфликтов при доступе к файлам
        metadata_workers = min(self.max_workers, 4)  # Не более 4 потоков для чтения метаданных
        
        self.log_signal.emit(f"Чтение метаданных из {len(file_list)} файлов с использованием {metadata_workers} потоков...", "blue")
        
        with ThreadPoolExecutor(max_workers=metadata_workers) as executor:
            futures = {executor.submit(read_single_metadata, file_info): file_info for file_info in file_list}
            
            processed = 0
            for future in as_completed(futures):
                if self.canceled:
                    return {}
                
                path, metadata = future.result()
                if metadata:
                    metadata_cache[path] = metadata
                
                # Обновляем прогресс
                processed += 1
                if processed % 10 == 0:  # Обновляем каждые 10 файлов
                    progress = int(processed / len(file_list) * 100)
                    self.metadata_progress_signal.emit(progress)
                    self.log_signal.emit(f"Обработано {processed} из {len(file_list)} файлов метаданных ({progress}%)", "blue")
        
        self.log_signal.emit(f"Метаданные успешно прочитаны для {len(metadata_cache)} файлов", "green")
        return metadata_cache
    
    def create_metadata_index(self, source_files):
        """Создание индекса метаданных для быстрого поиска"""
        # Создаем директорию для кэша
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Создаем уникальное имя для индекса на основе исходной папки
        source_root_hash = hashlib.md5(self.source_root.encode()).hexdigest()[:16]
        index_path = os.path.join(self.cache_dir, f"metadata_index_{source_root_hash}.pkl")
        
        # Если индекс существует и актуален
        if os.path.exists(index_path):
            try:
                # Получаем время изменения самого нового исходного файла
                source_mtime = 0
                for src_path, _ in source_files:
                    if os.path.exists(src_path):
                        file_mtime = os.path.getmtime(src_path)
                        if file_mtime > source_mtime:
                            source_mtime = file_mtime
                
                index_mtime = os.path.getmtime(index_path)
                
                # Если индекс новее всех исходных файлов, используем его
                if index_mtime > source_mtime:
                    self.log_signal.emit("Используется существующий кэш метаданных...", "blue")
                    with open(index_path, 'rb') as f:
                        return pickle.load(f)
            except Exception as e:
                self.log_signal.emit(f"Ошибка загрузки кэша метаданных: {str(e)}", "red")
                # Если индекс поврежден, создаем заново
        
        # Создаем новый индекс
        self.log_signal.emit("Создание нового индекса метаданных...", "blue")
        metadata_index = self.read_metadata_parallel(source_files)
        
        # Сохраняем индекс
        try:
            with open(index_path, 'wb') as f:
                pickle.dump(metadata_index, f)
            self.log_signal.emit(f"Индекс метаданных сохранен в кэш: {index_path}", "green")
        except Exception as e:
            self.log_signal.emit(f"Ошибка сохранения кэша метаданных: {str(e)}", "red")
            # Если не удалось сохранить индекс, продолжаем без него
        
        return metadata_index
    
    def format_exif_value(self, tag_name, tag_value):
        """Форматирование значения EXIF для читаемого вывода"""
        try:
            # Для некоторых тегов можно сделать специальное форматирование
            if 'DateTime' in tag_name:
                return str(tag_value)
            elif 'Brightness' in tag_name:
                return f"{tag_value.values[0]}/{tag_value.values[1]} (EV)"
            else:
                return str(tag_value)
        except:
            return str(tag_value)
    
    def compare_metadata_values(self, exp_exif, src_exif, exp_name, src_name, exp_path, src_path):
        """Сравнение определенных метаданных для подтверждения соответствия"""
        log_messages = []
        
        # Список тегов для сравнения
        tags_to_compare = [
            'EXIF DateTimeOriginal',  # Дата и время съемки
            'EXIF BrightnessValue',   # Значение яркости
        ]
        
        log_messages.append((f"--- Сравнение метаданных для файлов: {exp_name} -> {src_name} ---", "black"))
        log_messages.append((f"  Экспортированный файл: {exp_path}", "black"))
        log_messages.append((f"  Исходный файл: {src_path}", "black"))
        
        all_tags_present = True
        all_tags_match = True
        
        for tag in tags_to_compare:
            if tag in exp_exif and tag in src_exif:
                exp_value = self.format_exif_value(tag, exp_exif[tag])
                src_value = self.format_exif_value(tag, src_exif[tag])
                
                log_messages.append((f"  {tag}:", "black"))
                log_messages.append((f"    Экспорт: {exp_value}", "black"))
                log_messages.append((f"    Исходный: {src_value}", "black"))
                
                if str(exp_exif[tag]) == str(src_exif[tag]):
                    log_messages.append((f"    ✓ Совпадение", "green"))
                else:
                    log_messages.append((f"    ✗ Различие", "red"))
                    all_tags_match = False
            else:
                # Логируем отсутствующие теги
                if tag not in exp_exif:
                    log_messages.append((f"  {tag}: отсутствует в экспортированном файле {exp_path}", "red"))
                if tag not in src_exif:
                    log_messages.append((f"  {tag}: отсутствует в исходном файла {src_path}", "red"))
                all_tags_present = False
                all_tags_match = False
        
        # Оба теги должны присутствовать и совпадать
        result = all_tags_present and all_tags_match
        
        if result:
            log_messages.append((f"--- Результат: все теги присутствуют и совпадают ---", "green"))
        else:
            if not all_tags_present:
                log_messages.append((f"--- Результат: не все теги присутствуют ---", "red"))
            else:
                log_messages.append((f"--- Результат: не все теги совпадают ---", "red"))
        
        return result, log_messages
    
    def calculate_file_hash(self, file_path, hash_algo='md5'):
        """Вычисление хеша файла с настраиваемым буфером"""
        hasher = hashlib.new(hash_algo)
        try:
            with open(file_path, 'rb') as f:
                while True:
                    data = f.read(self.buffer_size)
                    if not data:
                        break
                    hasher.update(data)
                    if self.canceled:
                        return None
            return hasher.hexdigest()
        except Exception as e:
            self.log_signal.emit(f"Ошибка чтения файла {file_path}: {str(e)}", "red")
            return None
    
    def create_source_index(self, source_files):
        """Создание индекса исходных файлов для быстрого поиска"""
        source_index = {}
        for src_path, src_name in source_files:
            src_base = os.path.splitext(src_name)[0]
            if src_base not in source_index:
                source_index[src_base] = []
            source_index[src_base].append((src_path, src_name))
        return source_index
    
    def find_matching_source_files(self, exp_base_name, source_index):
        """Быстрый поиск исходных файлов через индекс"""
        matching_sources = []
        
        # Базовое имя без суффикса (если применимо)
        base_name_without_suffix = exp_base_name
        if self.use_suffix and self.suffix_text and exp_base_name.endswith(self.suffix_text):
            base_name_without_suffix = exp_base_name[:-len(self.suffix_text)]
        
        # Поиск по точному совпадению через индекс
        if exp_base_name in source_index:
            matching_sources.extend(source_index[exp_base_name])
        
        if base_name_without_suffix in source_index and base_name_without_suffix != exp_base_name:
            matching_sources.extend(source_index[base_name_without_suffix])
        
        # Поиск по началу имени (только если включено сравнение метаданных)
        if self.compare_metadata_flag:
            for src_base in source_index:
                if src_base.startswith(exp_base_name) or exp_base_name.startswith(src_base):
                    matching_sources.extend(source_index[src_base])
                
                if self.use_suffix and self.suffix_text:
                    if src_base.startswith(base_name_without_suffix) or base_name_without_suffix.startswith(src_base):
                        matching_sources.extend(source_index[src_base])
        
        # Удаляем дубликаты
        return list(set(matching_sources))
    
    def process_single_file(self, exp_file, source_index, source_metadata_cache, hash_cache):
        """Обработка одного файла в отдельном потоке"""
        exp_path, exp_name = exp_file
        
        if self.canceled:
            return None, None, None, []
            
        # Базовое имя экспортированного файла (без расширения)
        exp_base_name = os.path.splitext(exp_name)[0]
        
        # Быстрый поиск соответствующих исходных файлов через индекс
        matching_sources = self.find_matching_source_files(exp_base_name, source_index)
        
        # Поиск наилучшего соответствия
        matched_source = None
        matched_source_name = None
        log_messages = []
        
        for src_path, src_name in matching_sources:
            # Дополнительные проверки, если включены
            if self.compare_metadata_flag or self.compare_hash:
                match_found = True
                
                # Проверка метаданных (используем кэш)
                if self.compare_metadata_flag and match_found:
                    exp_exif = self.get_exif_data_optimized(exp_path)
                    src_exif = source_metadata_cache.get(src_path, {})
                    
                    if exp_exif and src_exif:
                        match_found, compare_logs = self.compare_metadata_values(
                            exp_exif, src_exif, exp_name, src_name, exp_path, src_path
                        )
                        if not match_found:
                            log_messages.extend(compare_logs)
                    else:
                        # Если не удалось прочитать метаданные, но включена проверка хешей, продолжаем
                        if not exp_exif:
                            log_messages.append((f"Не удалось прочитать метаданные из экспортированного файла {exp_path}", "yellow"))
                        if not src_exif:
                            log_messages.append((f"Не удалось прочитать метаданные из исходного файла {src_path}", "yellow"))
                        
                        # Если проверка хешей отключена, считаем это ошибкой
                        if not self.compare_hash:
                            match_found = False
                
                # Проверка хеша (используем кэш)
                if self.compare_hash and match_found:
                    if exp_path not in hash_cache:
                        hash_cache[exp_path] = self.calculate_file_hash(exp_path)
                    if src_path not in hash_cache:
                        hash_cache[src_path] = self.calculate_file_hash(src_path)
                    
                    exp_hash = hash_cache[exp_path]
                    src_hash = hash_cache[src_path]
                    
                    if exp_hash and src_hash and exp_hash != src_hash:
                        match_found = False
                        log_messages.append((f"Хеши не совпадают для файлов {exp_path} и {src_path}", "red"))
                    elif not exp_hash or not src_hash:
                        match_found = False
                        log_messages.append((f"Не удалось вычислить хеш для файлов {exp_path} или {src_path}", "red"))
                
                # Если проверки пройдены, используем это соответствие
                if match_found:
                    if matched_source is None:
                        matched_source = src_path
                        matched_source_name = src_name
                        log_messages.append((f"Найдено соответствие: {exp_name} -> {src_name}", "green"))
                        log_messages.append((f"  Экспортированный файл: {exp_path}", "black"))
                        log_messages.append((f"  Исходный файл: {src_path}", "black"))
                    else:
                        log_messages.append((f"Найдено несколько совпадений для {exp_name}, используется первое", "blue"))
                        break
            else:
                # Если проверки отключены, считаем файлы соответствующими
                if matched_source is None:
                    matched_source = src_path
                    matched_source_name = src_name
                    log_messages.append((f"Найдено соответствие: {exp_name} -> {src_name}", "green"))
                    log_messages.append((f"  Экспортированный файл: {exp_path}", "black"))
                    log_messages.append((f"  Исходный файл: {src_path}", "black"))
                else:
                    log_messages.append((f"Найдено несколько совпадений для {exp_name}, используется первое", "blue"))
                    break
        
        if not matched_source:
            log_messages.append((f"Не найдено соответствие для: {exp_name}", "red"))
            log_messages.append((f"  Путь к файлу: {exp_path}", "black"))
        
        return exp_path, matched_source, exp_name, log_messages
    
    def organize_photos(self):
        """Основная функция организации фотографий с многопоточной оптимизацией"""
        # Создание выходной директории
        os.makedirs(self.output_root, exist_ok=True)
        
        # Поиск всех файлов в исходной директории (только выбранные расширения)
        source_files = []
        for root, dirs, files in os.walk(self.source_root):
            for file in files:
                # Проверяем расширение файла
                file_ext = os.path.splitext(file.lower())[1]
                if file_ext in self.source_extensions:
                    src_path = os.path.join(root, file)
                    source_files.append((src_path, file))
            
            if self.canceled:
                return
        
        # Создаем индекс для быстрого поиска
        source_index = self.create_source_index(source_files)
        
        # Создаем или загружаем индекс метаданных
        self.log_signal.emit("Чтение метаданных исходных файлов...", "blue")
        source_metadata_cache = self.create_metadata_index(source_files)
        
        # Поиск всех файлов в экспортированной директории
        exported_files = []
        for root, dirs, files in os.walk(self.exported_root):
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.tiff', '.dng')):
                    exported_files.append((os.path.join(root, file), file))
            
            if self.canceled:
                return
        
        self.log_signal.emit(f"Найдено {len(source_files)} исходных файлов", "black")
        self.log_signal.emit(f"Найдено {len(exported_files)} экспортированных файлов", "black")
        
        # Сопоставление файлов с использованием многопоточности
        matches = {}
        hash_cache = {}
        all_log_messages = []
        
        # Используем ThreadPoolExecutor для параллельной обработки
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Создаем futures для всех файлов
            futures = {
                executor.submit(
                    self.process_single_file, 
                    exp_file, 
                    source_index, 
                    source_metadata_cache, 
                    hash_cache
                ): exp_file for exp_file in exported_files
            }
            
            # Обрабатываем результаты по мере их поступления
            processed = 0
            for future in as_completed(futures):
                if self.canceled:
                    # Отменяем все задачи
                    for f in futures:
                        f.cancel()
                    return
                
                try:
                    exp_path, matched_source, exp_name, log_messages = future.result()
                    
                    if matched_source:
                        matches[exp_path] = (matched_source, exp_name)
                    
                    # Добавляем все сообщения в общий список
                    all_log_messages.extend(log_messages)
                    
                    # Обновляем прогресс
                    processed += 1
                    progress = int(processed / len(exported_files) * 100)
                    self.progress_signal.emit(progress)
                    
                except Exception as e:
                    self.log_signal.emit(f"Ошибка при обработке файла: {str(e)}", "red")
        
        # Выводим все сообщения лога в правильном порядке
        for message, color in all_log_messages:
            self.log_signal.emit(message, color)
        
        self.log_signal.emit(f"Найдено {len(matches)} соответствий", "black")
        
        # Перемещение файлов с сохранением структуры
        moved_count = 0
        for exp_path, (src_path, exp_name) in matches.items():
            if self.canceled:
                return
                
            # Получение относительного пути исходного файла
            relative_path = os.path.relpath(src_path, self.source_root)
            # Получаем только путь к папке (без имени файла)
            relative_dir = os.path.dirname(relative_path)
            # Создание целевого пути с оригинальным именем экспортированного файла
            target_path = os.path.join(self.output_root, relative_dir, exp_name)
            # Создание директорий для целевого пути
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            
            # Перемещение файла
            try:
                shutil.move(exp_path, target_path)
                moved_count += 1
                self.log_signal.emit(f"Перемещено: {os.path.basename(exp_path)} -> {target_path}", "green")
            except Exception as e:
                self.log_signal.emit(f"Ошибка перемещения файла {exp_path}: {str(e)}", "red")
        
        self.log_signal.emit(f"Перемещено {moved_count} файлов", "black")
        self.log_signal.emit(f"Результат сохранен в: {self.output_root}", "black")

class PhotoOrganizerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.organizer_thread = None
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Организатор фотографий")
        self.setGeometry(100, 100, 800, 700)  # Увеличиваем высоту окна
        
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
        self.suffix_check.setChecked(False)  # По умолчанию снята галочка
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
        self.metadata_check = QCheckBox("Сравнивать метаданные EXIF (DateTimeOriginal, BrightnessValue)")
        self.metadata_check.setChecked(True)  # По умолчанию включено
        settings_layout.addWidget(self.metadata_check)
        self.hash_check = QCheckBox("Сравнивать хеш-суммы файлов")
        settings_layout.addWidget(self.hash_check)
        
        # Новая группа: Расширения исходных файлов
        extensions_group = QGroupBox("Расширения исходных файлов")
        extensions_layout = QHBoxLayout()  # Изменено на горизонтальный layout
        
        # Создаем чекбоксы для расширений в нужном порядке
        extensions_order = ['.arw', '.cr2', '.dng', '.nef', '.jpg', '.jpeg', '.png', '.tiff']
        self.extension_checks = {}
        
        for ext in extensions_order:
            check = QCheckBox(ext)
            # Устанавливаем галочки только для .arw и .cr2
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
        
        # Размер буфера
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
        
        # Создаем формат с нужным цветом
        format = cursor.charFormat()
        format.setForeground(QColor(color))
        cursor.setCharFormat(format)
        
        # Добавляем текст
        cursor.insertText(message + "\n")
        
        # Прокручиваем к концу
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
        compare_hash = self.hash_check.isChecked()
        max_workers = self.threads_spinbox.value()
        buffer_size_kb = self.buffer_size_spinbox.value()
        max_retries = self.retry_spinbox.value()
        retry_delay = self.retry_delay_spinbox.value() / 1000  # Конвертируем мс в секунды
        
        # Получаем выбранные расширения исходных файлов
        source_extensions = []
        for ext, checkbox in self.extension_checks.items():
            if checkbox.isChecked():
                source_extensions.append(ext)
        
        if not source_extensions:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы одно расширение для исходных файлов")
            return
        
        # Если указан суффикс, но поле пустое
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
            compare_metadata, compare_hash, max_workers, buffer_size_kb,
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
        self.hash_check.setEnabled(enabled)
        
        # Включаем/выключаем чекбоксы расширений
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