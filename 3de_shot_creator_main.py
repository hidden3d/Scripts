import sys
import argparse
import os
import json
import subprocess
import glob
import re
import ast
import time
import importlib.util
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QFileDialog, QTreeWidget,
                             QTreeWidgetItem, QHeaderView, QCheckBox, QProgressBar,
                             QLabel, QMessageBox, QTextEdit, QDialog, QFormLayout,
                             QLineEdit, QDoubleSpinBox, QSpinBox, QDialogButtonBox, 
                             QSizePolicy, QStyledItemDelegate, QInputDialog, QColorDialog, QSplitter, QMenu,
                             QTableWidget, QTableWidgetItem, QDockWidget, QShortcut)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QMutex, QWaitCondition, QByteArray, QTimer
from PyQt5.QtGui import QColor, QFont, QBrush, QKeySequence

# Попытка импорта exifread
try:
    import exifread
except ImportError:
    exifread = None
    print("exifread not installed. JPEG metadata will not be read. Install: pip install exifread")

# Попытка импорта Pillow для чтения JPEG разрешения
try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("Pillow not installed. JPEG resolution reading will be limited.")

# Попытка импорта OpenEXR для чтения EXR-файлов
try:
    import OpenEXR
    import Imath
    OPENEXR_AVAILABLE = True
    print("OpenEXR installed.")
except ImportError:
    OPENEXR_AVAILABLE = False
    print("OpenEXR not installed. EXR metadata reading will be limited. Install: pip install openexr")


BUTTONS_IN_TREE = False

RESOURCES_FONT_SIZE = 9   # размер шрифта панели ресурсов

TIMER_DELAY_TO_SAVE = 5000

# ================== Константы оформления дерева ==================
SHOT_ROW_HEIGHT = 20           # высота строки шота (корневого элемента)
CHILD_ROW_HEIGHT = 15            # высота строки дочернего элемента (слоя, группы, модели)
BOLD_FONT_SIZE_OFFSET = 0      # на сколько пунктов увеличить жирный шрифт для шотов
SHOT_FONT_SIZE_OFFSET = 0       # на сколько пунктов увеличить шрифт шота относительно базового
CHILD_FONT_SIZE_OFFSET = -2     # на сколько пунктов уменьшить шрифт дочерних элементов

# --- в начало файла после импортов добавим список стоп-слов ---
STOP_WORDS = {
    "selected", "folder", "appears", "shot", "layer", "found", "from", "by", "to", "of", "in", "on", "at",
    "with", "for", "and", "or", "but", "not", "are", "is", "was", "were", "has", "have", "will", "be", "can",
    "could", "should", "would", "this", "that", "these", "those", "there", "their", "they", "them", "it", "its",
    "processing", "sensor", "focal", "mm", "px", "frames", "frame", "camera", "model", "extracted", "from",
    "using", "resolution", "key", "value", "scanning", "checking", "item", "folder", "layers", "tracking", "name"
}

# ================== Helper functions ==================
def make_pattern_from_file(filepath):
    """Convert file path .../name.0001.jpg to .../name.####.jpg for makeBCFile."""
    dirname = os.path.dirname(filepath)
    basename = os.path.basename(filepath)
    match = re.search(r'(\d+)\.jpg$', basename)
    if match:
        digits = match.group(1)
        pattern_name = basename.replace(digits, '#' * len(digits))
        return os.path.join(dirname, pattern_name)
    return None

def extract_base_name(filename):
    """Extract base name without frame number and extension."""
    base = os.path.basename(filename)
    match = re.search(r'^(.*)\.(\d+)\.jpg$', base)
    if match:
        return match.group(1)
    return base[:-4] if base.endswith('.jpg') else base

def expected_bc_name(first_file):
    basename = os.path.basename(first_file)
    base_without_ext = os.path.splitext(basename)[0]
    name_with_x = re.sub(r'\d+', 'x', base_without_ext)
    return name_with_x + '.jpg.3de_bcompress'


# ================== EXR metadata helpers (unchanged) ==================
def decode_metadata_value(v):
    if isinstance(v, bytes):
        try:
            return v.decode('utf-8', errors='ignore')
        except:
            return str(v)
    if isinstance(v, str):
        if v.startswith("b'") and v.endswith("'"):
            try:
                return ast.literal_eval(v).decode('utf-8', errors='ignore')
            except:
                pass
    return str(v)

def parse_sensor_size(sensor_str):
    match = re.search(r'([\d.]+)\s*(?:mm)?\s*x\s*([\d.]+)\s*(?:mm)?', sensor_str, re.IGNORECASE)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None, None

def get_sensor_from_camera_db(camera_db, camera_model, resolution):
    if not camera_db or 'cameras' not in camera_db:
        return None, None
    cam_info = camera_db['cameras'].get(camera_model)
    if not cam_info:
        return None, None
    sensor_str = cam_info.get('resolutions', {}).get(resolution)
    if sensor_str:
        return parse_sensor_size(sensor_str)
    return None, None

def detect_camera_by_rules(metadata, rules, log_func=None):
    for rule in rules:
        field = rule.get('field')
        value = rule.get('value')
        camera = rule.get('camera')
        for key in metadata:
            if field.lower() in key.lower():
                if str(metadata[key]) == value:
                    if log_func:
                        log_func(f"      Camera found by rule: {field} = {value} -> {camera}", "info")
                    return camera
    for key, val in metadata.items():
        if 'camera' in key.lower():
            if log_func:
                log_func(f"      Camera found by fallback: {key} = {val}", "info")
            return str(val)
    return None

def parse_resolution_by_type(value_str, rule_type):
    if rule_type == 'range':
        match = re.match(r'\((\d+),\s*(\d+)\)\s*-\s*\((\d+),\s*(\d+)\)', value_str)
        if match:
            min_x, min_y, max_x, max_y = map(int, match.groups())
            return (max_x - min_x + 1, max_y - min_y + 1)
        match = re.match(r'(\d+)\s+(\d+)\s+(\d+)\s+(\d+)', value_str)
        if match:
            min_x, min_y, max_x, max_y = map(int, match.groups())
            return (max_x - min_x + 1, max_y - min_y + 1)
    elif rule_type == 'single_w':
        nums = re.findall(r'\d+', value_str)
        if nums:
            return int(nums[0])
    elif rule_type == 'single_h':
        nums = re.findall(r'\d+', value_str)
        if nums:
            return int(nums[0])
    elif rule_type == 'combined':
        match = re.match(r'\(?\s*(\d+)\s*[xX×:]\s*(\d+)\s*\)?', value_str)
        if match:
            return (int(match.group(1)), int(match.group(2)))
    return None

def detect_resolution_by_rules(metadata, rules, log_func=None):
    resolutions = []
    for rule in rules:
        field = rule.get('field')
        rule_type = rule.get('type')
        for key in metadata:
            if field.lower() in key.lower():
                value = str(metadata[key])
                parsed = parse_resolution_by_type(value, rule_type)
                if parsed:
                    if log_func:
                        log_func(f"      Resolution from rule {field} ({rule_type}): {parsed}", "info")
                    if rule_type == 'single_w':
                        resolutions.append((parsed, None))
                    elif rule_type == 'single_h':
                        resolutions.append((None, parsed))
                    else:
                        resolutions.append(parsed)
    if not resolutions and 'dataWindow' in metadata:
        parsed = parse_resolution_by_type(metadata['dataWindow'], 'range')
        if parsed:
            if log_func:
                log_func(f"      Resolution from dataWindow: {parsed}", "info")
            resolutions.append(parsed)
    full = [(w, h) for w, h in resolutions if w and h]
    if full:
        full.sort(key=lambda x: x[0]*x[1], reverse=True)
        w, h = full[0]
        if log_func:
            log_func(f"      Selected full resolution: {w}x{h}", "info")
        return f"{w}x{h}"
    widths = [w for w, h in resolutions if w and not h]
    heights = [h for w, h in resolutions if not w and h]
    if widths and heights:
        result = f"{max(widths)}x{max(heights)}"
        if log_func:
            log_func(f"      Combined resolution: {result}", "info")
        return result
    elif widths:
        result = f"{max(widths)}x?"
        if log_func:
            log_func(f"      Width only: {result}", "info")
        return result
    elif heights:
        result = f"?x{max(heights)}"
        if log_func:
            log_func(f"      Height only: {result}", "info")
        return result
    return None

def read_exr_metadata_with_rules(exr_path, camera_db, rules, log_func=None):
    if not OPENEXR_AVAILABLE:
        if log_func:
            log_func("      OpenEXR not available", "error")
        return None, None
    try:
        exr_file = OpenEXR.InputFile(exr_path)
        header = exr_file.header()
        metadata = {str(k): decode_metadata_value(v) for k, v in header.items()}
        if log_func:
            log_func(f"      EXR header keys: {list(metadata.keys())}", "info")
            camera_keys = [k for k in metadata.keys() if 'camera' in k.lower()]
            if camera_keys:
                log_func(f"      Camera-related keys: {camera_keys}", "info")
                for k in camera_keys:
                    log_func(f"        {k}: {metadata[k]}", "info")
        
        camera_model = None
        if rules and 'camera_rules' in rules:
            camera_model = detect_camera_by_rules(metadata, rules['camera_rules'], log_func)
        else:
            camera_model = detect_camera_by_rules(metadata, [], log_func)
        
        resolution = None
        if rules and 'resolution_rules' in rules:
            resolution = detect_resolution_by_rules(metadata, rules['resolution_rules'], log_func)
        else:
            resolution = detect_resolution_by_rules(metadata, [], log_func)
        
        if log_func:
            log_func(f"      Camera model: {camera_model}", "info")
            log_func(f"      Resolution: {resolution}", "info")
        
        if camera_model and resolution:
            sensor = get_sensor_from_camera_db(camera_db, camera_model, resolution)
            if log_func:
                log_func(f"      Sensor from DB: {sensor}", "info")
            if sensor[0] and sensor[1]:
                return sensor
        else:
            if log_func:
                log_func("      Cannot determine sensor: missing camera or resolution", "warning")
    except Exception as e:
        if log_func:
            log_func(f"      Error reading EXR: {e}", "error")
    return None, None

def extract_focal_from_exr(exr_path):
    if not OPENEXR_AVAILABLE:
        return None
    try:
        exr_file = OpenEXR.InputFile(exr_path)
        header = exr_file.header()
        for key in header:
            if 'focal' in key.lower():
                val = str(header[key])
                match = re.search(r'([\d.]+)', val)
                if match:
                    return float(match.group(1))
    except:
        pass
    return None

def read_simple_exr_sensor(exr_path, camera_db):
    if not OPENEXR_AVAILABLE:
        return None, None
    try:
        exr_file = OpenEXR.InputFile(exr_path)
        header = exr_file.header()
        dw = header['dataWindow']
        width = dw.max.x - dw.min.x + 1
        height = dw.max.y - dw.min.y + 1
        resolution = f"{width}x{height}"
        camera_model = None
        for key in header:
            if 'cameraModel' in key or 'camera_type' in key or 'Camera Model' in key:
                camera_model = str(header[key])
                break
        if camera_model:
            return get_sensor_from_camera_db(camera_db, camera_model, resolution)
    except:
        pass
    return None, None


class ProjectResources:
    """Управление ресурсами проекта (модели и текстуры)."""
    def __init__(self, project_name, resources_dir=None):
        if resources_dir is None:
            resources_dir = os.path.dirname(__file__)  # рядом с приложением
        self.resources_dir = resources_dir
        self.project_name = project_name
        self.json_path = os.path.join(resources_dir, f"{project_name}_resources.json")
        self.models = []  # список словарей: {"name": str, "model_path": str, "texture_path": str}
        self.load()

    def load(self):
        """Загрузить ресурсы из JSON."""
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.models = data.get("models", [])
            except Exception as e:
                print(f"Ошибка загрузки ресурсов: {e}")
                self.models = []
        else:
            self.models = []

    def save(self):
        """Сохранить ресурсы в JSON."""
        try:
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump({"models": self.models}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения ресурсов: {e}")

    def add_model(self, model_path, texture_path="", name=None):
        """Добавить модель в ресурсы, если ещё не существует.
        Возвращает True, если добавлена, False – если уже есть."""
        # Проверяем существование по model_path
        for m in self.models:
            if m["model_path"] == model_path:
                return False
        if name is None:
            name = os.path.splitext(os.path.basename(model_path))[0]
        self.models.append({
            "name": name,
            "model_path": model_path,
            "texture_path": texture_path
        })
        self.save()
        return True

    def remove_model(self, index):
        """Удалить модель по индексу."""
        if 0 <= index < len(self.models):
            del self.models[index]
            self.save()

    def update_model(self, index, name=None, model_path=None, texture_path=None):
        """Обновить поля модели по индексу."""
        if 0 <= index < len(self.models):
            if name is not None:
                self.models[index]["name"] = name
            if model_path is not None:
                self.models[index]["model_path"] = model_path
            if texture_path is not None:
                self.models[index]["texture_path"] = texture_path
            self.save()

    def get_model_dict_for_shot(self, model_data):
        """Преобразовать запись из ресурсов в словарь модели для шота."""
        return {
            "path": model_data["model_path"],
            "enabled": True,
            "texture": {
                "path": model_data["texture_path"],
                "enabled": bool(model_data["texture_path"])
            }
        }





class TextFloatDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        return editor

    def setEditorData(self, editor, index):
        value = index.model().data(index, Qt.DisplayRole)
        if value is not None:
            editor.setText(str(value))
        else:
            editor.setText("")

    def setModelData(self, editor, model, index):
        text = editor.text().strip()
        text = text.replace(',', '.')
        try:
            value = float(text)
            model.setData(index, str(value), Qt.EditRole)
        except ValueError:
            model.setData(index, "", Qt.EditRole)



class MainTreeDelegate(QStyledItemDelegate):
    """Делегат для дерева: обрабатывает редактирование чисел, высоту строк и шрифт."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.normal_font = QFont()
        self.bold_font = QFont()
        self.bold_font.setBold(True)
        # Увеличиваем размер шрифта для корневых элементов (шотов) на 2 пункта
        self.bold_font.setPointSize(self.bold_font.pointSize() + BOLD_FONT_SIZE_OFFSET)
        
    def sizeHint(self, option, index):
        """Увеличивает высоту строк для корневых элементов (шотов)."""
        size = super().sizeHint(option, index)
        #print(f"Shot row height: {size}")
        if not index.parent().isValid():  # корневой элемент
            #print(f"Shot row height: {size}")
            size.setHeight(max(size.height(), SHOT_ROW_HEIGHT))
        else:
            #print(f"Shot row height: {size}")
            size.setHeight(max(size.height(), CHILD_ROW_HEIGHT))
        return size

    def paint(self, painter, option, index):
        """Переопределяем отрисовку, чтобы для корневых элементов использовать жирный шрифт."""
        # Сохраняем оригинальный шрифт
        old_font = painter.font()
        if not index.parent().isValid():  # корневой элемент
            painter.setFont(self.bold_font)
        super().paint(painter, option, index)
        painter.setFont(old_font)

    def createEditor(self, parent, option, index):
        """Создаём редактор для числовых колонок (1, 2, 3)."""
        if index.column() in (1, 2, 3):
            editor = QLineEdit(parent)
            return editor
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        """Загружаем данные в редактор."""
        if index.column() in (1, 2, 3):
            value = index.model().data(index, Qt.DisplayRole)
            if value is not None:
                editor.setText(str(value))
            else:
                editor.setText("")
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        """Сохраняем отредактированные данные."""
        if index.column() in (1, 2, 3):
            text = editor.text().strip()
            text = text.replace(',', '.')
            try:
                value = float(text) if text else None
                # Сохраняем как строку, чтобы отображалось корректно
                model.setData(index, str(value) if value is not None else "", Qt.EditRole)
            except ValueError:
                model.setData(index, "", Qt.EditRole)
        else:
            super().setModelData(editor, model, index)

# ================== Data models ==================
class Sequence:
    def __init__(self, folder_path, base_name, base_item, layer_folder):
        self.folder_path = folder_path
        self.base_name = base_name
        self.full_name = base_name
        self.is_main = (base_name == layer_folder)
        self.files = []
        self.first_frame = None
        self.last_frame = None
        self.has_gaps = False
        self.sensor_width = None
        self.sensor_height = None
        self.focal = None
        self.metadata_from_exif = False
        self.logging = False

    def scan_files(self, file_list):
        self.files = sorted(file_list)
        if not self.files:
            return
        frame_numbers = []
        for f in self.files:
            base = os.path.basename(f)
            match = re.search(r'(\d+)\.jpg$', base)
            if match:
                frame_numbers.append(int(match.group(1)))
        if frame_numbers:
            self.first_frame = min(frame_numbers)
            self.last_frame = max(frame_numbers)
            unique_sorted = sorted(set(frame_numbers))
            expected = list(range(self.first_frame, self.last_frame+1))
            self.has_gaps = (unique_sorted != expected) or (len(frame_numbers) != len(unique_sorted))

    def read_metadata(self, default_values, camera_db=None, exr_viewer_rules=None, log_func=None):
        if not self.files:
            return
        first_file = self.files[0]
        self.metadata_from_exif = False
        tags = {}
        if exifread:
            try:
                with open(first_file, 'rb') as f:
                    tags = exifread.process_file(f, details=False)
            except:
                pass

        model_value = None
        for candidate in ['Image Model', 'EXIF Model', 'Model']:
            if candidate in tags:
                model_value = str(tags[candidate])
                break

        if model_value:
            focal_match = re.search(r'FOCAL LENGTH:\s*([\d.]+)\s*(?:mm)?', model_value, re.IGNORECASE)
            if focal_match:
                try:
                    self.focal = float(focal_match.group(1))
                    self.metadata_from_exif = True
                    if log_func:
                        log_func(f"      Extracted focal from Model tag: {self.focal} mm", 'success')
                except:
                    pass

            sensor_match = re.search(r'DETECTED SENSOR\s*:?\s*([\d.]+)\s*(?:mm)?\s*x\s*([\d.]+)\s*(?:mm)?', model_value, re.IGNORECASE)
            if sensor_match:
                try:
                    self.sensor_width = float(sensor_match.group(1))
                    self.sensor_height = float(sensor_match.group(2))
                    self.metadata_from_exif = True
                    if log_func:
                        log_func(f"      Extracted sensor from Model tag: {self.sensor_width} x {self.sensor_height} mm", 'success')
                except:
                    pass
            else:
                filmback_match = re.search(r'FILMBACK:\s*([A-Za-z0-9\s]+)(?=\s+DETECTED SENSOR|$)', model_value, re.IGNORECASE)
                if filmback_match and camera_db:
                    camera_model = filmback_match.group(1).strip()
                    if PILLOW_AVAILABLE and self.files:
                        try:
                            with Image.open(self.files[0]) as img:
                                width, height = img.size
                                resolution = f"{width}x{height}"
                                w, h = get_sensor_from_camera_db(camera_db, camera_model, resolution)
                                if w and h:
                                    self.sensor_width = w
                                    self.sensor_height = h
                                    self.metadata_from_exif = True
                                    if log_func:
                                        log_func(f"      Extracted sensor from FILMBACK and resolution: {self.sensor_width} x {self.sensor_height} mm", 'success')
                        except Exception as e:
                            if log_func:
                                log_func(f"      Could not read JPEG resolution: {e}", 'error')

        if not self.metadata_from_exif and camera_db:
            source_exr = self.find_source_exr(tags)
            if source_exr and os.path.exists(source_exr):
                if exr_viewer_rules:
                    w, h = read_exr_metadata_with_rules(source_exr, camera_db, exr_viewer_rules, log_func)
                else:
                    w, h = None, None
                if not w and h:
                    w, h = read_simple_exr_sensor(source_exr, camera_db)
                if w and h:
                    self.sensor_width = w
                    self.sensor_height = h
                    self.metadata_from_exif = True
                    if log_func:
                        log_func(f"      Extracted sensor from source EXR: {self.sensor_width} x {self.sensor_height} mm", 'success')
                focal = extract_focal_from_exr(source_exr)
                if focal and self.focal is None:
                    self.focal = focal
                    if log_func:
                        log_func(f"      Extracted focal from source EXR: {self.focal} mm", 'success')

        if not self.metadata_from_exif and log_func:
            log_func("      No metadata found", 'info')

    def find_source_exr(self, tags):
        for key, value in tags.items():
            key_lower = key.lower()
            val = str(value)
            if 'exif' in key_lower and 'make' in key_lower:
                if val.lower().endswith('.exr'):
                    return val
            if 'source' in key_lower or 'original' in key_lower:
                if val.lower().endswith('.exr'):
                    return val
        for key, value in tags.items():
            val = str(value)
            if val.lower().endswith('.exr') and ('/' in val or '\\' in val):
                return val
        return None

class Shot:
    def __init__(self, path, name, layer_folder, log_func=None):
        self.path = path
        self.base_item = os.path.basename(path)
        self.name = name
        self.layer_folder = layer_folder
        self.sequences = []
        self.has_project = False
        self.selected = False
        self.has_gaps = False
        self.has_metadata = False
        self.frame_count = 0
        self.user_sensor_width = None
        self.user_sensor_height = None
        self.user_focal = None
        self.processed = False          # обработан ли шот (успешно или нет)
        self.processed_success = False  # True - успех, False - ошибка
        self.mismatched_frame_count = False   # новый атрибут
        self._saving_config = False  # новый флаг
        self._save_timer = None
        self.log_func = log_func
        self._dirty = False

        # New attributes for point groups and layer selection
        self.sequence_selected = {}       # seq.full_name -> bool
        # NEW: point_groups stores dict: group_name -> list of model dicts
        self.point_groups = {}            # group name -> list of model dicts
        self.point_groups["CAMERA"] = []  # default group

    def get_config_path(self):
        return os.path.join(self.path, "tracking", f"{self.name}_config.json")
    
    def schedule_save(self, delay_ms = TIMER_DELAY_TO_SAVE):
        if self._save_timer is None:
            self._save_timer = QTimer()
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self.save_config)
        self._save_timer.stop()
        self._save_timer.start(delay_ms)

    def save_config(self):
        if not self._dirty:
            return
        if self._saving_config:
            return
        self._saving_config = True
        try:   
            if self.log_func:
                self.log_func(f"Saving config for shot {self.name}", "info")
            config = {
                "sequence_selected": self.sequence_selected,
                "point_groups": self.point_groups,
                "processed": self.processed,
                "processed_success": self.processed_success,
                "user_sensor_width": self.user_sensor_width,
                "user_sensor_height": self.user_sensor_height,
                "user_focal": self.user_focal,
            }
            # Удаляем None-значения, чтобы не хранить лишнее
            for key in ["user_sensor_width", "user_sensor_height", "user_focal"]:
                if config[key] is None:
                    del config[key]
            class SafeEncoder(json.JSONEncoder):
                def default(self, obj):
                    if isinstance(obj, (dict, list, str, int, float, bool, type(None))):
                        return super().default(obj)
                    return str(obj)  # преобразуем всё остальное в строку
                    
            try:
                with open(self.get_config_path(), 'w') as f:
                    json.dump(config, f, indent=2, cls=SafeEncoder)
                    self._dirty = False
                    print ({self.name})  #смотрим что записываем

            except Exception as e:
                print(f"Error saving config for {self.name}: {e}")
        finally:
            self._saving_config = False

    def load_config(self):
        path = self.get_config_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            self.sequence_selected = data.get("sequence_selected", {})
            self.processed = data.get("processed", False)
            self.processed_success = data.get("processed_success", False)
            self.user_sensor_width = data.get("user_sensor_width", None)
            self.user_sensor_height = data.get("user_sensor_height", None)
            self.user_focal = data.get("user_focal", None)
            loaded_groups = data.get("point_groups", {})
            self.point_groups = {}
            for group_name, items in loaded_groups.items():
                # Поддержка старого формата (только пути)
                if items and isinstance(items[0], str):
                    new_items = []
                    for path in items:
                        name = os.path.splitext(os.path.basename(path))[0]
                        new_items.append({
                            "name": name,
                            "path": path,
                            "enabled": True,
                            "texture": {"path": "", "enabled": False}
                        })
                    self.point_groups[group_name] = new_items
                else:
                    # Для нового формата убеждаемся, что поле name присутствует
                    for m in items:
                        if "name" not in m:
                            m["name"] = os.path.splitext(os.path.basename(m["path"]))[0]
                    self.point_groups[group_name] = items
            if "CAMERA" not in self.point_groups:
                self.point_groups["CAMERA"] = []
        except Exception as e:
            print(f"Error loading config for {self.name}: {e}")

    # New methods for model management
    def add_model_to_group(self, group_name, model_path, enabled=True, texture_path=None, texture_enabled=False, name=None):
        """Добавляет модель в группу. Если name не указан, берёт имя из пути."""
        if name is None:
            name = os.path.splitext(os.path.basename(model_path))[0]
        model_dict = {
            "name": name,
            "path": model_path,
            "enabled": enabled,
            "texture": {
                "path": texture_path or "",
                "enabled": texture_enabled if texture_path else False
            }
        }
        if group_name not in self.point_groups:
            self.point_groups[group_name] = []
        self.point_groups[group_name].append(model_dict)
        self._dirty = True
        self.schedule_save()

    def remove_model_from_group(self, group_name, model_path):
        if group_name in self.point_groups:
            self.point_groups[group_name] = [m for m in self.point_groups[group_name] if m["path"] != model_path]
            self._dirty = True
            self.schedule_save()

    def set_model_enabled(self, group_name, model_path, enabled):
        for m in self.point_groups.get(group_name, []):
            if m["path"] == model_path:
                m["enabled"] = enabled
                self._dirty = True
                self.schedule_save()
                break

    def set_texture_path(self, group_name, model_path, texture_path, enabled=None):
        for m in self.point_groups.get(group_name, []):
            if m["path"] == model_path:
                m["texture"]["path"] = texture_path
                if enabled is not None:
                    m["texture"]["enabled"] = enabled
                self._dirty = True
                self.schedule_save()
                break

    def set_texture_enabled(self, group_name, model_path, enabled):
        for m in self.point_groups.get(group_name, []):
            if m["path"] == model_path:
                m["texture"]["enabled"] = enabled
                self._dirty = True
                self.schedule_save()
                break

    def scan(self, default_metadata, camera_db=None, exr_viewer_rules=None, log_func=None):
        layers_path = os.path.join(self.path, "layers")
        tracking_path = os.path.join(self.path, "tracking")
        if not os.path.isdir(layers_path) or not os.path.isdir(tracking_path):
            return False

        folder = os.path.join(layers_path, self.layer_folder)
        if not os.path.isdir(folder):
            return False

        if log_func:
            log_func(f"  Scanning shot {self.name} from folder {self.layer_folder} (base_item={self.base_item})")

        all_jpgs = glob.glob(os.path.join(folder, "*.jpg"))
        if not all_jpgs:
            return False

        groups = defaultdict(list)
        for f in all_jpgs:
            base_name = extract_base_name(f)
            groups[base_name].append(f)

        self.sequences.clear()
        for base_name, file_list in groups.items():
            seq = Sequence(folder, base_name, self.base_item, self.layer_folder)
            seq.scan_files(file_list)
            seq.read_metadata(default_metadata, camera_db=camera_db, exr_viewer_rules=exr_viewer_rules, log_func=log_func)
            self.sequences.append(seq)
            if seq.has_gaps:
                self.has_gaps = True
            if seq.metadata_from_exif:
                self.has_metadata = True
            if log_func:
                log_func(f"    Sequence '{base_name}', is_main={seq.is_main}, files={len(file_list)}")

        frame_counts = []
        for seq in self.sequences:
            if seq.first_frame is not None and seq.last_frame is not None:
                frame_counts.append(seq.last_frame - seq.first_frame + 1)
        if len(set(frame_counts)) > 1:
            self.mismatched_frame_count = True
        else:
            self.mismatched_frame_count = False

        # Initialize sequence_selected for all sequences
        for seq in self.sequences:
            if seq.full_name not in self.sequence_selected:
                self.sequence_selected[seq.full_name] = True
        # Load saved config (overwrites if exists)
        self.load_config()
        # Ensure all sequences have entry (in case of new sequences)
        for seq in self.sequences:
            if seq.full_name not in self.sequence_selected:
                self.sequence_selected[seq.full_name] = True

        if len(self.sequences) == 1:
            main_seq = self.sequences[0]
        else:
            main_seq = next((seq for seq in self.sequences if seq.is_main), None)
            if main_seq is None:
                indexed = [(seq, self._get_index_suffix(seq.base_name)) for seq in self.sequences]
                indexed = [(seq, idx) for seq, idx in indexed if idx is not None]
                if indexed:
                    indexed.sort(key=lambda x: x[1])
                    main_seq = indexed[0][0]
                else:
                    main_seq = self.sequences[0]
            if log_func:
                log_func(f"    Main sequence selected: {main_seq.base_name}")

        if main_seq:
            self.frame_count = main_seq.last_frame - main_seq.first_frame + 1
        else:
            self.frame_count = 0

        project_files = glob.glob(os.path.join(tracking_path, f"{self.name}_track_v*.3de"))
        self.has_project = len(project_files) > 0

        if log_func:
            log_func(f"    has_project={self.has_project}, sequences count={len(self.sequences)}, frame_count={self.frame_count}")

        if self.sequences and not self.has_project:
            self.selected = True
            if log_func:
                log_func(f"    -> shot selected automatically")

        if self.sequences:
            frame_counts = []
            for seq in self.sequences:
                if seq.first_frame is not None and seq.last_frame is not None:
                    frame_counts.append(seq.last_frame - seq.first_frame + 1)
            if len(set(frame_counts)) > 1:
                self.mismatched_frame_count = True
            else:
                self.mismatched_frame_count = False
        else:
            self.mismatched_frame_count = False

        return len(self.sequences) > 0
    
    def _get_index_suffix(self, base_name):
        match = re.search(r'_(\d{2})$', base_name)
        if match:
            return int(match.group(1))
        return None

# ================== Settings ==================
class Settings:
    def __init__(self, config_path=None):
        if config_path is None:
            self.config_path = os.path.join(os.path.dirname(__file__), "3de_shot_craetor_config.json")
        else:
            self.config_path = config_path
        self.data = {
            "path_makeBCFile": "",
            "path_tde4": "",
            "sensor_width": 35.0,
            "sensor_height": 24.0,
            "focal": 24.0,
            "bc_quality": 90,
            "bc_black": 0,
            "bc_white": 255,
            "bc_gamma": 1.0,
            "bc_softclip": 0.0,
            "import_exr_display_window": False,
            "import_sxr_right_eye": False,
            "start_frame": 1001,
            "logging_enabled": True,
            "log_lines": 5,
            "font_size": 12,
            "ui_font_size": 10,
            "ui_font_bold": False,
            "log_font_bold": False,
            "log_highlight_important": False,
            "camera_sensor_json_path": "",
            "exr_metadata_reader_path": "",
            "exr_viewer_settings_path": "",
            "file_permissions": "664",
            "dir_permissions": "775",
            "color_processing": (173, 216, 230),  # светло-голубой
            "color_success": (144, 238, 144),     # светло-зелёный
            "color_failure": (255, 182, 193),     # светло-красный
            "color_mismatch": (255, 165, 0),   # оранжевый
        }
        self.load()

    def load(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self.data.update(loaded)
            except:
                pass
        else:
            self.save()

    def save(self):
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=4)

# ================== Processing Worker ==================
class ProcessingWorker(QThread):
    log_signal = pyqtSignal(str, str)
    progress_global = pyqtSignal(int, int)
    progress_shot = pyqtSignal(int, int)
    progress_sequence = pyqtSignal(int, int)
    shot_started = pyqtSignal(str)
    shot_finished = pyqtSignal(str, bool, str)
    finished = pyqtSignal(dict)

    def __init__(self, shots, settings):
        super().__init__()
        self.shots = shots
        self.settings = settings
        self.mutex = QMutex()
        self.pause_condition = QWaitCondition()
        self._is_paused = False
        self._is_stopped = False
        self._is_aborted = False
        self.processed_projects = {}

    def pause(self):
        self.mutex.lock()
        self._is_paused = True
        self.mutex.unlock()

    def resume(self):
        self.mutex.lock()
        self._is_paused = False
        self.pause_condition.wakeAll()
        self.mutex.unlock()

    def stop(self):
        self.mutex.lock()
        self._is_stopped = True
        self.pause_condition.wakeAll()
        self.mutex.unlock()

    def abort(self):
        self.mutex.lock()
        self._is_aborted = True
        self.pause_condition.wakeAll()
        self.mutex.unlock()

    def run(self):
        total_shots = len(self.shots)
        self.emit_log(f"Start processing {total_shots} shots", "info")
        for idx, shot in enumerate(self.shots):
            self.mutex.lock()
            if self._is_aborted:
                self.mutex.unlock()
                self.emit_log("Processing aborted by user", "error")
                break
            if self._is_stopped:
                self.mutex.unlock()
                self.emit_log("Processing stopped by user", "info")
                break
            while self._is_paused:
                self.pause_condition.wait(self.mutex)
            self.mutex.unlock()

            self.progress_global.emit(idx, total_shots)
            self.shot_started.emit(shot.name)
            self.emit_log(f"Processing shot {shot.name}...", "info")
            self.emit_log(f"DEBUG: point_groups = {shot.point_groups}", "info")
            success, project_path = self.process_shot(shot)
            self.shot_finished.emit(shot.name, success, project_path)
            if success and project_path:
                self.processed_projects[shot.name] = project_path

        self.progress_global.emit(total_shots, total_shots)
        self.finished.emit(self.processed_projects)

    def emit_log(self, msg, level="info"):
        self.log_signal.emit(msg, level)

    def process_shot(self, shot):
        self.emit_log(f"Point groups for {shot.name}: {shot.point_groups}", "info")
        if shot.has_gaps:
            self.emit_log(f"Warning: shot {shot.name} has frame number gaps", "error")

        tracking_dir = os.path.join(shot.path, "tracking")
        if not os.path.exists(tracking_dir):
            os.makedirs(tracking_dir)

        version = self.get_next_version(tracking_dir, shot.name)
        project_filename = f"{shot.name}_track_v{version:03d}.3de"
        project_path = os.path.join(tracking_dir, project_filename)

        bc_files = []          # для передачи в скрипт
        bc_files_paths = []    # для установки прав
        selected_seqs = [seq for seq in shot.sequences if shot.sequence_selected.get(seq.full_name, True)]
        total_seqs = len(selected_seqs)
        for seq_idx, seq in enumerate(selected_seqs):
            self.progress_shot.emit(seq_idx, total_seqs)
            self.emit_log(f"  Generating bc for {seq.full_name}...", "info")
            bc_path = self.generate_bc(seq, tracking_dir)
            if bc_path:
                bc_files.append((seq, bc_path))
                bc_files_paths.append(bc_path)
            else:
                self.emit_log(f"  Failed to generate bc for {seq.full_name}", "error")

        main_seq = next((s for s in shot.sequences if s.is_main), None)
        if main_seq is None and shot.sequences:
            main_seq = shot.sequences[0]
            self.emit_log(f"  Warning: no exact main sequence, using first: {main_seq.full_name}", "info")
        if main_seq is None:
            self.emit_log(f"  Error: no sequences for shot {shot.name}", "error")
            return False, None

        proxy_seqs = [seq for seq in selected_seqs if seq != main_seq]

        self.emit_log(f"  Creating project {project_filename}...", "info")
        created_files = self.create_3de_project(shot, main_seq, proxy_seqs, bc_files, project_path)
        if created_files is not None:
            self.emit_log(f"  Project created: {project_path}", "success")
            all_files = bc_files_paths + created_files
            self.fix_permissions(all_files)
            return True, project_path
        else:
            self.emit_log(f"  Failed to create project", "error")
            return False, None
        
        

    def get_next_version(self, tracking_dir, shot_name):
        pattern = os.path.join(tracking_dir, f"{shot_name}_track_v*.3de")
        files = glob.glob(pattern)
        max_v = 0
        for f in files:
            base = os.path.basename(f)
            match = re.search(r'_v(\d+)\.3de$', base)
            if match:
                v = int(match.group(1))
                if v > max_v:
                    max_v = v
        return max_v + 1

    def generate_bc(self, seq, out_dir):
        makebc = self.settings.data["path_makeBCFile"]
        if not os.path.isfile(makebc):
            self.emit_log(f"makeBCFile not found: {makebc}", "error")
            return None

        if not seq.files:
            self.emit_log(f"  No files for {seq.full_name}", "error")
            return None

        pattern = make_pattern_from_file(seq.files[0])
        if not pattern:
            self.emit_log(f"  Could not create pattern from {seq.files[0]}", "error")
            return None

        cmd = [
            makebc,
            "-source", pattern,
            "-start", str(seq.first_frame),
            "-end", str(seq.last_frame),
            "-out", out_dir,
            "-quality", str(self.settings.data["bc_quality"]),
            "-black", str(self.settings.data["bc_black"]),
            "-white", str(self.settings.data["bc_white"]),
            "-gamma", str(self.settings.data["bc_gamma"]),
            "-softclip", str(self.settings.data["bc_softclip"])
        ]
        if self.settings.data["import_exr_display_window"]:
            cmd.append("-import_exr_display_window")
        if self.settings.data["import_sxr_right_eye"]:
            cmd.append("-import_sxr_right_eye")

        self.emit_log(f"  Running: {' '.join(cmd)}", "info")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    universal_newlines=True, bufsize=1)
            for line in iter(proc.stdout.readline, ''):
                line = line.strip()
                if line:
                    self.emit_log(f"    {line}", "info")
                    match = re.search(r'(\d+)/(\d+) image files processed', line)
                    if match:
                        current = int(match.group(1))
                        total = int(match.group(2))
                        self.progress_sequence.emit(current, total)
            proc.wait()
            if proc.returncode != 0:
                self.emit_log(f"  makeBCFile finished with error (code {proc.returncode})", "error")
                return None
        except Exception as e:
            self.emit_log(f"  Error running makeBCFile: {e}", "error")
            return None

        expected_name = expected_bc_name(seq.files[0])
        expected_path = os.path.join(out_dir, expected_name)
        if os.path.isfile(expected_path):
            return expected_path
        else:
            bc_files = glob.glob(os.path.join(out_dir, "*.3de_bcompress"))
            if bc_files:
                latest = max(bc_files, key=os.path.getmtime)
                self.emit_log(f"  Found bc file: {os.path.basename(latest)}", "success")
                return latest
            else:
                self.emit_log(f"  File {expected_path} not found after generation", "error")
                return None

    def create_3de_project(self, shot, main_seq, proxy_seqs, bc_files, project_path):
        tde4_path = self.settings.data["path_tde4"]
        if not os.path.isfile(tde4_path):
            self.emit_log(f"3DE4 not found: {tde4_path}", "error")
            return None
        if not os.access(tde4_path, os.X_OK):
            self.emit_log(f"3DE4 not executable: {tde4_path}", "error")
            return None

        script_content = self.generate_tde4_script(shot, main_seq, proxy_seqs, bc_files, project_path)
        if script_content is None:
            self.emit_log(f"Failed to generate script for {shot.name}", "error")
            return None
        script_filename = f"_temp_{shot.name}_create_project.py"
        script_file = os.path.join(shot.path, "tracking", script_filename)
        with open(script_file, 'w', encoding='utf-8') as f:
            f.write(script_content)
        os.chmod(script_file, int(self.settings.data.get("file_permissions", "664"), 8))

        self.emit_log(f"  Temporary script saved: {script_file}", "info")

        cmd = [tde4_path, "-run_script", script_file]
        self.emit_log(f"  Launching 3DE4: {' '.join(cmd)}", "info")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=os.environ,
                encoding='utf-8',
                text=True
            )
            for line in iter(proc.stdout.readline, ''):
                line = line.strip()
                if line:
                    self.emit_log(f"    3DE4: {line}", "info")
            proc.wait()
            self.emit_log(f"  3DE4 finished with code {proc.returncode}", "info")
            if proc.returncode == 0:
                self.emit_log(f"  Project successfully created: {project_path}", "success")
                # Собираем файлы, созданные этим методом
                created_files = [script_file, project_path]
                screenshot_path = project_path + ".jpg"
                if os.path.exists(screenshot_path):
                    created_files.append(screenshot_path)
                return created_files
            else:
                self.emit_log(f"  Project creation failed (exit code {proc.returncode})", "error")
                return None
        except Exception as e:
            self.emit_log(f"  Error running 3DE4: {e}", "error")
            return None

    def find_texture_for_model(self, obj_path):
        """Ищет текстуру для OBJ-модели по правилу:
        - база = имя файла без расширения
        - удаляются суффиксы: _reduced, _p[0-9]+, _v[0-9]+, _high, _low, _mid, _LOD[0-9]*
        - текстура = база + '_diffuse.1001.jpg' в той же папке
        """
        folder = os.path.dirname(obj_path)
        base = os.path.splitext(os.path.basename(obj_path))[0]
        # Удаляем суффиксы
        clean_base = re.sub(r'_(reduced|p[0-9]+|v[0-9]+|high|low|mid|LOD[0-9]*)$', '', base)
        texture_name = f"{clean_base}_diffuse.1001.jpg"
        texture_path = os.path.join(folder, texture_name)
        if os.path.isfile(texture_path):
            return texture_path
        # Если не найдено, попробуем исходное имя без удаления суффиксов (на случай, если суффикс не был удалён)
        texture_name2 = f"{base}_diffuse.1001.jpg"
        texture_path2 = os.path.join(folder, texture_name2)
        if os.path.isfile(texture_path2):
            return texture_path2
        return None

    def generate_tde4_script(self, shot, main_seq, proxy_seqs, bc_files, project_path):
        """Генерирует Python-скрипт для 3DE4 как последовательность команд без проверок."""
        if not main_seq.files:
            self.emit_log(f"Error: main sequence {main_seq.full_name} has no files", "error")
            return None
        if main_seq.first_frame is None or main_seq.last_frame is None:
            self.emit_log(f"Error: main sequence {main_seq.full_name} has invalid frame range", "error")
            return None

        main_pattern = make_pattern_from_file(main_seq.files[0])
        if not main_pattern:
            self.emit_log(f"Error: could not create pattern from {main_seq.files[0]}", "error")
            return None

        default_sensor_width = self.settings.data.get("sensor_width", 35.0)
        default_sensor_height = self.settings.data.get("sensor_height", 24.0)
        default_focal = self.settings.data.get("focal", 24.0)

        sensor_width = shot.user_sensor_width if shot.user_sensor_width is not None else (
            main_seq.sensor_width if main_seq.sensor_width is not None else default_sensor_width)
        sensor_height = shot.user_sensor_height if shot.user_sensor_height is not None else (
            main_seq.sensor_height if main_seq.sensor_height is not None else default_sensor_height)
        focal = shot.user_focal if shot.user_focal is not None else (
            main_seq.focal if main_seq.focal is not None else default_focal)

        lines = []
        lines.append("import tde4")
        lines.append("import os")
        lines.append("print('=== 3DE Project Setup ===')")
        lines.append("")

        # 1. Линза
        lines.append("lens = tde4.getFirstLens()")
        lines.append(f"print('Setting lens: sensor {sensor_width:.1f} x {sensor_height:.1f} mm, focal {focal:.1f} mm')")
        lines.append(f"tde4.setLensFBackWidth(lens, {sensor_width / 10:.2f})")
        lines.append(f"tde4.setLensFBackHeight(lens, {sensor_height / 10:.2f})")
        lines.append(f"tde4.setLensFocalLength(lens, {focal / 10:.2f})")
        lines.append("tde4.setLensPixelAspect(lens, 1.0)")
        lines.append(f"tde4.setLensFBackWidth(lens, {sensor_width / 10:.2f})")

        lines.append("tde4.setParameterAdjustFlag(lens, 'ADJUST_LENS_FOCAL_LENGTH', '', 1)")
        lines.append("tde4.setParameterAdjustFlag(lens, 'ADJUST_LENS_DISTORTION_PARAMETER', 'Distortion - Degree 2', 1)")
        lines.append("tde4.setParameterAdjustFlag(lens, 'ADJUST_LENS_DISTORTION_PARAMETER', 'Quartic Distortion - Degree 4', 1)")
        lines.append("")

        # 2. Камера
        lines.append("cam = tde4.getFirstCamera()")
        lines.append(f"tde4.setCameraName(cam, '{main_seq.full_name}')")
        lines.append("tde4.setCameraLens(cam, lens)")
        lines.append(f"tde4.setCameraPath(cam, r'{main_pattern}')")
        lines.append(f"tde4.setCameraSequenceAttr(cam, {main_seq.first_frame}, {main_seq.last_frame}, 1)")
        offset = self.settings.data["start_frame"]
        lines.append(f"tde4.setCameraFrameOffset(cam, {offset})")
        lines.append(f"tde4.setCamera8BitColorBlackWhite(cam, {self.settings.data['bc_black']}, {self.settings.data['bc_white']})")
        lines.append(f"tde4.setCamera8BitColorGamma(cam, {self.settings.data['bc_gamma']})")
        lines.append(f"tde4.setCamera8BitColorSoftclip(cam, {self.settings.data['bc_softclip']})")
        lines.append("")

        # 3. Установка ближней плоскости отсечения
        lines.append("tde4.setNearClippingPlane(0.1)")
        lines.append("tde4.setNearClippingPlaneF6(0.1)")
        lines.append("")

        # 4. Прокси-последовательности
        if proxy_seqs:
            lines.append("# Прокси-последовательности")
            for idx, seq in enumerate(proxy_seqs, start=1):
                if not seq.files:
                    continue
                proxy_pattern = make_pattern_from_file(seq.files[0])
                if not proxy_pattern:
                    continue
                lines.append(f"tde4.setCameraProxyFootage(cam, {idx})")
                lines.append(f"tde4.setCameraPath(cam, r'{proxy_pattern}')")
                lines.append(f"tde4.setCameraSequenceAttr(cam, {seq.first_frame}, {seq.last_frame}, 1)")
                lines.append(f"print('Added proxy slot {idx}: {seq.full_name}')")
            lines.append("tde4.setCameraProxyFootage(cam, 0)")
            lines.append("")

        # 5. Группы точек и 3D-модели
        lines.append("# === ГРУППЫ ТОЧЕК И 3D-МОДЕЛИ ===")

        # 5.1 Основная группа CAMERA
        lines.append("first_group = tde4.getFirstPGroup()")
        lines.append("tde4.setPGroupName(first_group, 'CAMERA')")
        lines.append("print('Group CAMERA ready')")
        lines.append("")

        # Import models only if enabled
        for group_name, models in shot.point_groups.items():
            # Determine which pgroup to use
            if group_name == "CAMERA":
                pgroup_line = "first_group"
            else:
                pgroup_line = f"pgroup_{group_name.replace(' ', '_')}"
                lines.append(f"{pgroup_line} = tde4.createPGroup('OBJECT')")
                lines.append(f"tde4.setPGroupName({pgroup_line}, '{group_name}')")
                lines.append(f"print('Created group {group_name}')")
            for model_dict in models:
                if not model_dict["enabled"]:
                    continue
                model_path = model_dict["path"]
                safe_path = repr(model_path.replace('\\', '/'))
                model_name = os.path.splitext(os.path.basename(model_path))[0]
                lines.append(f'print("  Importing model: {model_name} from " + {safe_path})')
                lines.append(f"model = tde4.create3DModel({pgroup_line}, 0)")
                # Set flags
                lines.append(f"tde4.set3DModelSurveyFlag({pgroup_line}, model, 1)")
                lines.append(f"tde4.set3DModelReferenceFlag({pgroup_line}, model, 1)")
                lines.append(f"tde4.set3DModelPerformanceRenderingFlag({pgroup_line}, model, 1)")
                lines.append(f"tde4.importOBJ3DModel({pgroup_line}, model, {safe_path})")
                lines.append("tde4.flushEventQueue()")
                
                lines.append(f"tde4.set3DModelName({pgroup_line}, model, '{model_name}')")
                lines.append(f"tde4.set3DModelColor({pgroup_line}, model, 0.22, 0.45, 0.65, 0.05)")
                lines.append(f"tde4.set3DModelRenderingFlags({pgroup_line}, model, 1, 0, 1)")
                # Texture
                if model_dict["texture"]["enabled"] and model_dict["texture"]["path"]:
                    texture_path = model_dict["texture"]["path"]
                    safe_texture = repr(texture_path.replace('\\', '/'))
                    lines.append(f'print("    Texture: " + {safe_texture})')
                    lines.append(f"tde4.set3DModelTextureMapMode({pgroup_line}, model, 'TEXMAP_UV')")
                    lines.append(f"tde4.set3DModelUVTextureMap({pgroup_line}, model, {safe_texture})")
                    lines.append("tde4.flushEventQueue()")
                else:
                    lines.append(f'print("    No texture set for model {model_name}")')
                lines.append(f"tde4.set3DModelVisibleFlag({pgroup_line}, model, 1)")
            if group_name != "CAMERA":
                lines.append("")

        # 6. Сохранение и скриншот
        lines.append("print('Saving project...')")
        lines.append(f"tde4.saveProject(r'{project_path}')")
        lines.append("tde4.flushEventQueue()")
        lines.append("print('Project saved')")
        lines.append("tde4.updateGUI()")
        screenshot_path = project_path + ".jpg"
        lines.append("resx, resy = tde4.getMainWindowResolution()")
        lines.append(f"tde4.saveMainWindowScreenShot(r'{screenshot_path}', 'IMAGE_JPEG', 0, 0, resx, resy)")
        lines.append("tde4.flushEventQueue()")
        lines.append("print('Screenshot saved')")
        lines.append("tde4.updateGUI()")
        lines.append("print('=== Done ===')")
        lines.append("raise SystemExit(0)")

        return "\n".join(lines)

    def fix_permissions(self, file_list):
        try:
            file_perm = int(self.settings.data.get("file_permissions", "664"), 8)
            for file_path in file_list:
                if os.path.exists(file_path):
                    os.chmod(file_path, file_perm)
            self.emit_log(f"Permissions set for {len(file_list)} files (mode: {oct(file_perm)})", "info")
        except Exception as e:
            self.emit_log(f"Error setting permissions: {e}", "error")

# ================== Log Window ==================
class LogWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Logs")
        self.resize(600, 400)
        layout = QVBoxLayout()
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)
        self.setLayout(layout)

    def append_log(self, msg):
        self.text_edit.append(msg)

# ================== Edit Model Dialog ==================



class EditModelDialog(QDialog):
    def __init__(self, model_dict=None, parent=None, project_resources=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Model")
        self.resize(500, 300)
        self.model_dict = model_dict or {"name": "", "path": "", "enabled": True, "texture": {"path": "", "enabled": False}}
        self.project_resources = project_resources
        layout = QVBoxLayout()

        # Name
        layout.addWidget(QLabel("Model name:"))
        self.name_edit = QLineEdit(self.model_dict.get("name", ""))
        layout.addWidget(self.name_edit)

        # Model section
        model_group = QWidget()
        model_layout = QHBoxLayout(model_group)
        self.model_path_edit = QLineEdit(self.model_dict["path"])
        model_layout.addWidget(self.model_path_edit)
        btn_browse_model = QPushButton("Browse...")
        btn_browse_model.clicked.connect(lambda: self.browse_model())
        model_layout.addWidget(btn_browse_model)
        self.model_enabled_cb = QCheckBox("Enabled")
        self.model_enabled_cb.setChecked(self.model_dict["enabled"])
        model_layout.addWidget(self.model_enabled_cb)
        layout.addWidget(QLabel("Model OBJ:"))
        layout.addWidget(model_group)

        # Texture section
        texture_group = QWidget()
        texture_layout = QHBoxLayout(texture_group)
        self.texture_path_edit = QLineEdit(self.model_dict["texture"]["path"])
        texture_layout.addWidget(self.texture_path_edit)
        btn_browse_texture = QPushButton("Browse...")
        btn_browse_texture.clicked.connect(lambda: self.browse_texture())
        texture_layout.addWidget(btn_browse_texture)
        self.texture_enabled_cb = QCheckBox("Enable texture")
        self.texture_enabled_cb.setChecked(self.model_dict["texture"]["enabled"])
        texture_layout.addWidget(self.texture_enabled_cb)
        layout.addWidget(QLabel("Texture:"))
        layout.addWidget(texture_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def browse_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select OBJ model", "", "OBJ files (*.obj)")
        if path:
            self.model_path_edit.setText(path)

    def browse_texture(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select texture", "", "Image files (*.jpg *.png *.tif *.exr)")
        if path:
            self.texture_path_edit.setText(path)

    def get_model_dict(self):
        return {
            "name": self.name_edit.text(),
            "path": self.model_path_edit.text(),
            "enabled": self.model_enabled_cb.isChecked(),
            "texture": {
                "path": self.texture_path_edit.text(),
                "enabled": self.texture_enabled_cb.isChecked() if self.texture_path_edit.text() else False
            }
        }

    def accept(self):
        model_dict = self.get_model_dict()
        if self.project_resources and model_dict["path"]:
            exists = any(m["model_path"] == model_dict["path"] for m in self.project_resources.models)
            if not exists:
                self.project_resources.add_model(model_dict["path"], model_dict["texture"]["path"], model_dict["name"])
        super().accept()

# ================== Main Window ==================
class MainWindow(QMainWindow):


    NUM_SHOT_COLORS = 10
    SHOT_COLORS = [
        QColor(228, 240, 250),  # очень светлый серый
        QColor(226, 238, 248),
        QColor(224, 236, 246),
        QColor(222, 234, 244),
        QColor(220, 232, 242),
        QColor(218, 230, 240),
        QColor(216, 228, 238),
        QColor(214, 226, 236),
        QColor(212, 224, 234),
        QColor(210, 222, 232)
    ]




    def __init__(self, forced_path=None, headless=False):
        super().__init__()
        self.forced_path = forced_path
        self.setWindowTitle("3DE Shot Processor")
        self.resize(1800, 1200)

        self.settings = Settings()
        self.root_path = ""
        self.shots = []
        self.log_window = None
        self.worker = None
        self.worker_thread = None
        self.camera_db = None
        self.exr_reader = None
        self.exr_viewer_rules = None
        self.current_processing_shot_name = None
        self._sorting = False
        self.current_project_name = None
        self.project_resources = None
        self.resources_dock = None
        self._saved_scroll_value = 0
        self._saved_selected_path = None


        self.apply_ui_font()
        self.init_ui()
        self.apply_log_settings()
        self.init_external_modules()
        self.headless = headless
        self.auto_quit_on_finish = False
        self._apply_forced_path()
        self._disable_saving = False
        self.copied_model_data = None   # хранит (group_name, model_dict) для копирования


        # Восстанавливаем состояние сплиттера, если оно сохранено
        if hasattr(self, 'splitter') and "splitter_state" in self.settings.data:
            state_str = self.settings.data["splitter_state"]
            state = QByteArray.fromBase64(state_str.encode())
            self.splitter.restoreState(state)


    def _store_tree_state(self):
        """Сохраняет состояние дерева: позицию скролла и выделенный элемент."""
        self._saved_scroll_value = self.tree.verticalScrollBar().value()
        self._saved_selected_path = None
        current = self.tree.currentItem()
        if current:
            # Строим путь из текстов элементов, разделённых '|'
            path_parts = []
            item = current
            while item:
                path_parts.append(item.text(0))
                item = item.parent()
            self._saved_selected_path = '|'.join(reversed(path_parts))

    def _restore_tree_state(self):
        """Восстанавливает состояние дерева после обновления."""
        if hasattr(self, '_saved_scroll_value'):
            self.tree.verticalScrollBar().setValue(self._saved_scroll_value)
        if hasattr(self, '_saved_selected_path') and self._saved_selected_path:
            path_parts = self._saved_selected_path.split('|')
            parent = None
            found = None
            for i, part in enumerate(path_parts):
                if i == 0:
                    # Ищем среди корневых элементов
                    for j in range(self.tree.topLevelItemCount()):
                        if self.tree.topLevelItem(j).text(0) == part:
                            parent = self.tree.topLevelItem(j)
                            found = parent
                            break
                else:
                    # Ищем среди детей текущего parent
                    found = None
                    for j in range(parent.childCount()):
                        if parent.child(j).text(0) == part:
                            found = parent.child(j)
                            break
                    if not found:
                        break
                    parent = found
            if found:
                self.tree.setCurrentItem(found)
                self.tree.scrollToItem(found)

    def fix_permissions(self, file_list):
        """Установка прав на файлы (для головного режима)."""
        try:
            file_perm = int(self.settings.data.get("file_permissions", "664"), 8)
            for file_path in file_list:
                if os.path.exists(file_path):
                    os.chmod(file_path, file_perm)
            self.log_info(f"Permissions set for {len(file_list)} files (mode: {oct(file_perm)})")
        except Exception as e:
            self.log_error(f"Error setting permissions: {e}")


    def get_shot_color(self, idx, selected):
        """Возвращает цвет для шота с индексом idx и состоянием выбора."""
        base_color = self.SHOT_COLORS[idx % self.NUM_SHOT_COLORS]
        if not selected:
            # Затемняем цвет (делаем темно-серым)
            gray = (base_color.red() + base_color.green() + base_color.blue()) // 3
            dark_gray = max(gray * 5 // 6, 150)
            return QColor(dark_gray, dark_gray, dark_gray)
        return base_color


    def _apply_forced_path(self):
        if self.forced_path:
            path = self.forced_path
            if not os.path.exists(path):
                self.log_error(f"Provided path does not exist: {path}")
            elif not os.path.isdir(path):
                self.log_error(f"Provided path is not a directory: {path}")
            else:
                self.root_path = path
                self.path_edit.setText(path)
                self.path_edit.setReadOnly(True)
                self.btn_browse.setEnabled(False)
                if not self.headless:
                    self.auto_quit_on_finish = True   # <--- добавить
                QTimer.singleShot(100, self.scan_shots)

    def _reset_sorting_flag(self):
        self._sorting = False

    def apply_ui_font(self):
        font_size = self.settings.data.get("ui_font_size", 10)
        bold = self.settings.data.get("ui_font_bold", False)
        font = QApplication.font()
        font.setPointSize(font_size)
        font.setBold(bold)
        QApplication.setFont(font)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Enter or select root folder...")
        self.path_edit.textChanged.connect(self.on_path_changed)
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self.browse_root)
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.btn_browse)
        main_layout.addLayout(path_layout)

        buttons_layout = QHBoxLayout()
        self.btn_scan = QPushButton("Scan")
        self.btn_scan.clicked.connect(self.scan_shots)
        self.btn_scan.setEnabled(False)
        buttons_layout.addWidget(self.btn_scan)

        self.btn_settings = QPushButton("Settings")
        self.btn_settings.clicked.connect(self.open_settings)
        buttons_layout.addWidget(self.btn_settings)

        self.btn_logs = QPushButton("Logs")
        self.btn_logs.clicked.connect(self.show_logs)
        buttons_layout.addWidget(self.btn_logs)

        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.clicked.connect(self.select_all_shots)
        buttons_layout.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton("Deselect All")
        self.btn_deselect_all.clicked.connect(self.deselect_all_shots)
        buttons_layout.addWidget(self.btn_deselect_all)

        self.btn_add_group = QPushButton("Add point group")
        self.btn_add_group.clicked.connect(self.add_point_group)
        buttons_layout.addWidget(self.btn_add_group)

        self.btn_add_model = QPushButton("Add model")
        self.btn_add_model.clicked.connect(self.add_model_to_selected_group)
        buttons_layout.addWidget(self.btn_add_model)

        self.btn_remove = QPushButton("Remove selected")
        self.btn_remove.clicked.connect(self.remove_selected_item)
        buttons_layout.addWidget(self.btn_remove)

        self.btn_resources = QPushButton("Resources")
        self.btn_resources.clicked.connect(self.toggle_resources_panel)
        buttons_layout.addWidget(self.btn_resources)

        buttons_layout.addStretch()
        main_layout.addLayout(buttons_layout)





        # Tree widget: Name + чекбокс в колонке 0, остальное в 1-4
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Sensor W", "Sensor H", "Focal", "Info"])
        self.tree.setColumnCount(5)

        # Настройка ширины
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)   # Name
        self.tree.header().setSectionResizeMode(1, QHeaderView.Fixed)     # Sensor W
        self.tree.header().setSectionResizeMode(2, QHeaderView.Fixed)     # Sensor H
        self.tree.header().setSectionResizeMode(3, QHeaderView.Fixed)     # Focal
        self.tree.header().setSectionResizeMode(4, QHeaderView.Fixed)     # Info

        self.tree.header().setStretchLastSection(False)

        self.tree.header().sortIndicatorChanged.connect(self.on_sort_indicator_changed)

        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 100)
        self.tree.setColumnWidth(3, 100)
        self.tree.setColumnWidth(4, 200)

        # Делегаты для числовых полей
        # float_delegate = TextFloatDelegate()
        # self.tree.setItemDelegateForColumn(1, float_delegate)  # Sensor W
        # self.tree.setItemDelegateForColumn(2, float_delegate)  # Sensor H
        # self.tree.setItemDelegateForColumn(3, float_delegate)  # Focal

        # ЧЕРЕДОВАНИЕ ЦВЕТОВ СТРОК (сетка)
        self.tree.setAlternatingRowColors(True)

        self.tree.setIndentation(50)   # ширина отступов
        self.tree.installEventFilter(self)



        

        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree.itemChanged.connect(self.on_tree_item_changed)

        self.tree.setItemDelegate(MainTreeDelegate(self))

#==========================================панель==================================

        # ========== Панель ресурсов ==========
        self.resources_dock = QDockWidget("Project Resources", self)
        self.resources_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        self.resources_dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)

        resources_widget = QWidget()
        resources_layout = QVBoxLayout(resources_widget)

        # Кнопки управления ресурсами
        btn_layout = QHBoxLayout()
        self.btn_add_resource = QPushButton("Add Model")
        self.btn_add_resource.clicked.connect(self.add_resource_model)
        btn_layout.addWidget(self.btn_add_resource)

        self.btn_remove_resource = QPushButton("Remove Model")
        self.btn_remove_resource.clicked.connect(self.remove_resource_model)
        btn_layout.addWidget(self.btn_remove_resource)

        self.btn_copy_resource = QPushButton("Copy Model")
        self.btn_copy_resource.clicked.connect(self.copy_resource_model)
        btn_layout.addWidget(self.btn_copy_resource)

        btn_layout.addStretch()
        resources_layout.addLayout(btn_layout)

        # Дерево ресурсов (3 колонки: имя/тип, путь, кнопка)
        self.resources_tree = QTreeWidget()
        self.resources_tree.setColumnCount(3)
        self.resources_tree.setHeaderLabels(["", "Path", ""])
        self.resources_tree.setIndentation(20)

        # Настройка ширины колонок
        self.resources_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)   # имя модели по содержимому
        self.resources_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)           # путь растягивается
        self.resources_tree.header().setSectionResizeMode(2, QHeaderView.Fixed)             # фиксированная ширина для кнопки
        self.resources_tree.setColumnWidth(2, 70)  # ширина колонки с кнопкой
        self.resources_tree.header().setStretchLastSection(False)  # важно для фиксации последней колонки

        self.resources_tree.setEditTriggers(QTreeWidget.DoubleClicked | QTreeWidget.EditKeyPressed)
        self.resources_tree.itemChanged.connect(self.on_resource_item_changed)

        self.resources_tree.installEventFilter(self)

        self.resources_tree.setAlternatingRowColors(True)

        # Устанавливаем шрифт для дерева ресурсов
        resources_font = QFont()
        resources_font.setPointSize(RESOURCES_FONT_SIZE)
        self.resources_tree.setFont(resources_font)

        resources_layout.addWidget(self.resources_tree)

        self.resources_dock.setWidget(resources_widget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.resources_dock)
        self.resources_dock.hide()  # по умолчанию скрыта


#======================панель==================
        

        # Создаём контейнер для лога
        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_label = QLabel("Log:")
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.WidgetWidth)
        self.log_text.setFontFamily("Courier New")
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_layout.addWidget(log_label)
        log_layout.addWidget(self.log_text)

        # Создаём вертикальный сплиттер и добавляем дерево и контейнер лога
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(log_container)

        # Установка начальных размеров: дерево – 700 пикселей, лог – 300 пикселей
        self.splitter.setSizes([700, 300])

        # Добавляем сплиттер в основной layout вместо отдельных виджетов
        main_layout.addWidget(self.splitter)

        # Прогресс-бары
        progress_layout = QHBoxLayout()
        self.global_progress = QProgressBar()
        self.global_progress.setRange(0, 100)
        self.global_progress.setFormat("Shot %v/%m")
        progress_layout.addWidget(QLabel("Overall:"))
        progress_layout.addWidget(self.global_progress)
        self.shot_progress = QProgressBar()
        self.shot_progress.setRange(0, 100)
        progress_layout.addWidget(QLabel("Shot:"))
        progress_layout.addWidget(self.shot_progress)
        self.seq_progress = QProgressBar()
        self.seq_progress.setRange(0, 100)
        progress_layout.addWidget(QLabel("Sequence:"))
        progress_layout.addWidget(self.seq_progress)
        main_layout.addLayout(progress_layout)

        # Кнопки управления
        control_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_start.clicked.connect(self.start_processing)
        self.btn_start.setEnabled(False)
        control_layout.addWidget(self.btn_start)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.clicked.connect(self.pause_processing)
        self.btn_pause.setEnabled(False)
        control_layout.addWidget(self.btn_pause)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.clicked.connect(self.stop_processing)
        self.btn_stop.setEnabled(False)
        control_layout.addWidget(self.btn_stop)
        self.btn_abort = QPushButton("Abort")
        self.btn_abort.clicked.connect(self.abort_processing)
        self.btn_abort.setEnabled(False)
        control_layout.addWidget(self.btn_abort)
        self.cb_logging = QCheckBox("Logging (console)")
        self.cb_logging.setChecked(self.settings.data.get("logging_enabled", True))
        control_layout.addWidget(self.cb_logging)
        main_layout.addLayout(control_layout)

    def setup_project_resources(self, root_path):
        project_name = self.determine_project_name(root_path)
        if not project_name:
            self.log_info("Не удалось определить проект, ресурсы не загружены.")
            self.current_project_name = None
            self.project_resources = None
            self.resources_tree.clear()
            return
        self.current_project_name = project_name
        self.project_resources = ProjectResources(project_name)
        self.populate_resources_tree()
        self.log_info(f"Загружены ресурсы проекта '{project_name}' ({len(self.project_resources.models)} моделей)")



    def populate_resources_tree(self):
        """Заполнить дерево ресурсов из self.project_resources.models."""
        self.resources_tree.blockSignals(True)
        self.resources_tree.clear()
        if not self.project_resources:
            self.resources_tree.blockSignals(False)
            return

        # Получаем базовый шрифт дерева
        base_font = self.resources_tree.font()
        base_size = base_font.pointSize()
        # Увеличиваем размер шрифта для корневых элементов
        model_font = QFont(base_font)
        model_font.setPointSize(base_size + 2)   # на 2 больше

        for idx, m in enumerate(self.project_resources.models):
            # Корневой элемент – модель
            model_item = QTreeWidgetItem([m["name"], "", ""])
            model_item.setFlags(model_item.flags() | Qt.ItemIsEditable)
            model_item.setData(0, Qt.UserRole, ("model", idx))
            # Устанавливаем увеличенный шрифт для всех колонок модели
            for col in range(3):
                model_item.setFont(col, model_font)
            self.resources_tree.addTopLevelItem(model_item)

            # Дочерний элемент – путь модели
            path_item = QTreeWidgetItem(["Model path:", m["model_path"], ""])
            path_item.setFlags(path_item.flags() | Qt.ItemIsEditable)
            path_item.setData(0, Qt.UserRole, ("model_path", idx))
            # Для дочерних элементов шрифт не меняем (остаётся базовым)
            model_item.addChild(path_item)
            # Кнопка для выбора файла модели
            btn_model = QPushButton("Browse")
            btn_model.clicked.connect(lambda checked, i=idx: self.browse_model_for_resource(i))
            self.resources_tree.setItemWidget(path_item, 2, btn_model)

            # Дочерний элемент – путь текстуры
            tex_item = QTreeWidgetItem(["Texture path:", m["texture_path"], ""])
            tex_item.setFlags(tex_item.flags() | Qt.ItemIsEditable)
            tex_item.setData(0, Qt.UserRole, ("texture_path", idx))
            model_item.addChild(tex_item)
            # Кнопка для выбора текстуры
            btn_tex = QPushButton("Browse")
            btn_tex.clicked.connect(lambda checked, i=idx: self.browse_texture_for_resource(i))
            self.resources_tree.setItemWidget(tex_item, 2, btn_tex)

            # Визуальное отделение моделей: устанавливаем фон корневого элемента
            if idx % 2 == 0:
                brush = QBrush(QColor(245, 245, 245))
            else:
                brush = QBrush(QColor(235, 235, 235))
            model_item.setBackground(0, brush)
            model_item.setBackground(1, brush)
            model_item.setBackground(2, brush)

        self.resources_tree.expandAll()
        # Принудительно устанавливаем фиксированную ширину для колонки с кнопками
        self.resources_tree.header().setSectionResizeMode(2, QHeaderView.Fixed)
        self.resources_tree.setColumnWidth(2, 70)
        self.resources_tree.blockSignals(False)

    def on_resource_item_changed(self, item, column):
        data = item.data(0, Qt.UserRole)
        if not data or not isinstance(data, tuple):
            return
        data_type, idx = data
        if not self.project_resources or idx >= len(self.project_resources.models):
            return
        m = self.project_resources.models[idx]
        if data_type == "model" and column == 0:
            m["name"] = item.text(0)
        elif data_type == "model_path" and column == 1:
            m["model_path"] = item.text(1)
        elif data_type == "texture_path" and column == 1:
            m["texture_path"] = item.text(1)
        self.project_resources.save()


    def add_resource_model(self):
        """Добавить новую модель в ресурсы."""
        if not self.project_resources:
            QMessageBox.warning(self, "Warning", "Не определён проект. Сначала отсканируйте папку с проектом.")
            return
        self.project_resources.add_model("", "", "unnamed")
        self.populate_resources_tree()

    def remove_resource_model(self):
        """Удалить выбранную модель из ресурсов."""
        current = self.resources_tree.currentItem()
        if not current:
            return
        # Определяем, является ли выбранный элемент корневым (моделью)
        while current.parent():
            current = current.parent()
        # current теперь корневой элемент модели
        data = current.data(0, Qt.UserRole)
        if not data or not isinstance(data, tuple) or data[0] != "model":
            return
        idx = data[1]
        reply = QMessageBox.question(self, "Delete", f"Удалить модель '{current.text(0)}' из ресурсов?",
                                    QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.project_resources.remove_model(idx)
            self.populate_resources_tree()

    def copy_resource_model(self):
        """Копировать выбранную модель из ресурсов в буфер (copied_model_data)."""
        current = self.resources_tree.currentItem()
        if not current or not self.project_resources:
            return
        while current.parent():
            current = current.parent()
        data = current.data(0, Qt.UserRole)
        if not data or not isinstance(data, tuple) or data[0] != "model":
            return
        idx = data[1]
        m = self.project_resources.models[idx]
        model_dict = {
            "name": m["name"],                     # <-- добавлено
            "path": m["model_path"],
            "enabled": True,
            "texture": {
                "path": m["texture_path"],
                "enabled": bool(m["texture_path"])
            }
        }
        self.copied_model_data = (None, model_dict)
        self.log_info(f"Скопирована модель '{m['name']}' из ресурсов")

    def eventFilter(self, obj, event):
        if hasattr(self, 'tree') and obj is self.tree and event.type() == event.KeyPress:
            if event.modifiers() == Qt.ControlModifier:
                if event.key() == Qt.Key_C:
                    self.copy_selected_model()
                    return True
                elif event.key() == Qt.Key_V:
                    self.paste_model_to_selected()
                    return True
        elif obj is self.resources_tree and event.type() == event.KeyPress:
            if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_C:
                self.copy_resource_model()
                return True
        return super().eventFilter(obj, event)


    def determine_project_name(self, path):
        """Извлекает имя проекта из пути. Проект — это папка, находящаяся на уровень выше папки 'work'."""
        path = os.path.normpath(path)
        # Разбиваем путь на компоненты
        parts = path.split(os.sep)
        # Ищем 'work' среди компонент
        try:
            work_index = parts.index('work')
            # Если work найден, то имя проекта — это предыдущая компонента
            if work_index > 0:
                return parts[work_index - 1]
            else:
                # Если work в корне, то нет имени проекта — используем basename
                return os.path.basename(path)
        except ValueError:
            # work не найден, используем basename
            return os.path.basename(path)

    def toggle_resources_panel(self):
        if self.resources_dock.isVisible():
            self.resources_dock.hide()
        else:
            self.resources_dock.show()

    def closeEvent(self, event):
        for shot in self.shots:
            if hasattr(shot, '_save_timer') and shot._save_timer and shot._save_timer.isActive():
                shot._save_timer.stop()
            if shot._dirty:
                shot.save_config()
        if hasattr(self, 'splitter'):
            # Сохраняем состояние сплиттера как base64-строку
            state_bytes = self.splitter.saveState().toBase64().data()
            self.settings.data["splitter_state"] = state_bytes.decode()
            self.settings.save()
        event.accept()



    def highlight_important(self, text):
        """Добавляет <b> теги вокруг важных данных в логе."""
        if not self.settings.data.get("log_highlight_important", False):
            return text

        # Паттерны для выделения
        patterns = [
            # Пути (начинающиеся с /, \, или содержащие .obj/.jpg и т.п.)
#            (r'([/\\][\w\s/\\\-\.]+\.(?:obj|jpg|exr|png|tif))', r'<b>\1</b>'),
#            (r'([A-Za-z]:[/\\][\w\s/\\\-\.]+)', r'<b>\1</b>'),
            # Значения сенсора: число x число mm
            (r'(\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?\s*mm)', r'<b>\1</b>'),
            # Фокусное: focal \d+ mm
            (r'(focal\s*:\s*\d+(?:\.\d+)?\s*mm)', r'<b>\1</b>'),
            # Имена камер (после "camera:" или "camera model:")
            (r'(camera\s*(?:model)?\s*:\s*[A-Za-z0-9_]+)', r'<b>\1</b>'),
            # Числовые значения (в контексте)
            (r'(\d+(?:\.\d+)?\s*(?:mm|px|frames?))', r'<b>\1</b>'),
            # Выделение идентификаторов (содержат цифры или подчёркивания, не стоп-слова)
            (r'\b([A-Za-z0-9_]+)\b', self._replace_important_word),
        ]

        for pattern, replacement in patterns:
            if callable(replacement):
                text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            else:
                text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    def _replace_important_word(self, match):
        word = match.group(1)
        # Выделяем, если слово не является стоп-словом и содержит цифру или подчёркивание
        if word.lower() not in STOP_WORDS and (any(c.isdigit() for c in word) or '_' in word):
            return f'<b>{word}</b>'
        return word

    def _set_child_font(self, item):
        """Устанавливает шрифт элемента на 2 пункта меньше базового."""
        font = item.font(0)
        font.setPointSize(font.pointSize() + CHILD_FONT_SIZE_OFFSET)
        for col in range(self.tree.columnCount()):
            item.setFont(col, font)

    def on_sort_indicator_changed(self, logicalIndex, order):
        self._sorting = True
        QTimer.singleShot(0, self._reset_sorting_flag)
        self.recolor_shots()

    def recolor_shots(self):
        self._disable_saving = True
        
        
        mismatch_color_rgb = self.settings.data.get("color_mismatch", (255, 165, 0))
        mismatch_color = QColor(*mismatch_color_rgb)
        for idx in range(self.tree.topLevelItemCount()):
            shot_item = self.tree.topLevelItem(idx)
            shot = shot_item.data(0, Qt.UserRole)
            if shot:
                if self.current_processing_shot_name == shot.name:
                    proc_color = self.settings.data.get("color_processing", (173, 216, 230))
                    color = QColor(*proc_color)
                elif shot.processed:
                    if shot.processed_success:
                        color_rgb = self.settings.data.get("color_success", (144, 238, 144))
                    else:
                        color_rgb = self.settings.data.get("color_failure", (255, 182, 193))
                    color = QColor(*color_rgb)
                else:
                    if shot.selected:
                        color = self.get_shot_color(idx, True)
                    else:
                        if shot.mismatched_frame_count:
                            color = mismatch_color
                        else:
                            color = self.get_shot_color(idx, False)
                self._set_item_background_recursive(shot_item, color)
        self._disable_saving = False


    def init_external_modules(self):
        camera_json = self.settings.data.get("camera_sensor_json_path", "")
        if camera_json and os.path.exists(camera_json):
            try:
                with open(camera_json, 'r', encoding='utf-8') as f:
                    self.camera_db = json.load(f)
                self.log_info(f"Camera database loaded from {camera_json}")
            except Exception as e:
                self.log_error(f"Failed to load camera database: {e}")
        else:
            self.log_info("Camera database not configured or file not found")

        reader_path = self.settings.data.get("exr_metadata_reader_path", "")
        if reader_path and os.path.exists(reader_path):
            try:
                spec = importlib.util.spec_from_file_location("exr_metadata_reader", reader_path)
                if spec and spec.loader:
                    self.exr_reader = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(self.exr_reader)
                    self.log_info(f"exr_metadata_reader imported from {reader_path}")
            except Exception as e:
                self.log_error(f"Failed to import exr_metadata_reader: {e}")

        exr_viewer_path = self.settings.data.get("exr_viewer_settings_path", "")
        if exr_viewer_path and os.path.exists(exr_viewer_path):
            try:
                with open(exr_viewer_path, 'r', encoding='utf-8') as f:
                    settings_data = json.load(f)
                self.exr_viewer_rules = settings_data.get('camera_detection', {})
                self.log_info(f"EXR viewer settings loaded from {exr_viewer_path}")
            except Exception as e:
                self.log_error(f"Failed to load EXR viewer settings: {e}")
        else:
            self.log_info("EXR viewer settings not configured or file not found")


    def save_tree_expansion_state(self):
        state = {}
        root = self.tree.invisibleRootItem()
        self._save_expansion_state_recursive(root, state, "")
        return state

    def _save_expansion_state_recursive(self, item, state, prefix):
        """Итеративный сбор состояния развёрнутости."""
        stack = [(item, prefix)]
        while stack:
            current_item, current_prefix = stack.pop()
            if current_item == self.tree.invisibleRootItem():
                # обрабатываем корневые элементы
                for i in range(current_item.childCount()):
                    stack.append((current_item.child(i), ""))
                continue
            key = current_prefix + current_item.text(0)
            state[key] = current_item.isExpanded()
            # добавляем детей в стек
            for i in range(current_item.childCount()):
                stack.append((current_item.child(i), key + "|"))

    def restore_tree_expansion_state(self, state):
        root = self.tree.invisibleRootItem()
        self._restore_expansion_state_recursive(root, state, "")


    def _restore_expansion_state_recursive(self, item, state, prefix):
        """Итеративное восстановление состояния развёрнутости."""
        stack = [(item, prefix)]
        while stack:
            current_item, current_prefix = stack.pop()
            if current_item == self.tree.invisibleRootItem():
                for i in range(current_item.childCount()):
                    stack.append((current_item.child(i), ""))
                continue
            key = current_prefix + current_item.text(0)
            if key in state:
                current_item.setExpanded(state[key])
            for i in range(current_item.childCount()):
                stack.append((current_item.child(i), key + "|"))



    def on_path_changed(self, text):
        self.btn_scan.setEnabled(bool(text.strip()))

    def log_with_level(self, msg, level='info'):
        if level == 'success':
            self.log_success(msg)
        elif level == 'error':
            self.log_error(msg)
        else:
            self.log_info(msg)

    def apply_log_settings(self):
        lines = self.settings.data.get("log_lines", 5)
        font_size = self.settings.data.get("font_size", 12)
        bold = self.settings.data.get("log_font_bold", False)
        font = self.log_text.font()
        font.setPointSize(font_size)
        font.setBold(bold)
        self.log_text.setFont(font)
        line_height = int(font_size * 1.5)
        self.log_text.setMinimumHeight(line_height * lines + 10)

    def log_info(self, msg):
        formatted = self.highlight_important(msg)
        self.log_text.append(f"<span style='color: black;'>{formatted}</span>")
        # self.log_text.append(f"<span style='color: black;'>{msg}</span>")  # Удаляем дублирование
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        if self.log_window:
            self.log_window.append_log(msg)

    def log_success(self, msg):
        self.log_text.append(f"<span style='color: green;'>{msg}</span>")
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        if self.log_window:
            self.log_window.append_log(msg)

    def log_error(self, msg):
        self.log_text.append(f"<span style='color: red;'>{msg}</span>")
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        if self.log_window:
            self.log_window.append_log(msg)

    def browse_root(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select root folder with shots")
        if dir_path:
            self.path_edit.setText(dir_path)
            self.root_path = dir_path
            self.btn_scan.setEnabled(True)

    def flush_pending_saves(self):
        """Немедленно сохранить все изменённые шоты."""
        for shot in self.shots:
            if shot._dirty:
                if shot._save_timer and shot._save_timer.isActive():
                    shot._save_timer.stop()
                shot.save_config()

    def select_all_shots(self):
        self.flush_pending_saves()
        # Останавливаем таймеры всех шотов
        for shot in self.shots:
            if shot._save_timer and shot._save_timer.isActive():
                shot._save_timer.stop()

        # Отключаем обработчик изменения элементов
        self.tree.itemChanged.disconnect(self.on_tree_item_changed)
        self._disable_saving = True
        try:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                item.setCheckState(0, Qt.Checked)
                shot = item.data(0, Qt.UserRole)
                if shot:
                    shot.selected = True
        finally:
            # Восстанавливаем обработчик
            self.tree.itemChanged.connect(self.on_tree_item_changed)
            self._disable_saving = False
        self._disable_saving = True
        self.recolor_shots()
        self._disable_saving = False

    def deselect_all_shots(self):
        self.flush_pending_saves()
        for shot in self.shots:
            if shot._save_timer and shot._save_timer.isActive():
                shot._save_timer.stop()

        self.tree.itemChanged.disconnect(self.on_tree_item_changed)
        self._disable_saving = True
        try:
            for i in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(i)
                item.setCheckState(0, Qt.Unchecked)
                shot = item.data(0, Qt.UserRole)
                if shot:
                    shot.selected = False
        finally:
            self.tree.itemChanged.connect(self.on_tree_item_changed)
            self._disable_saving = False
        self._disable_saving = True
        self.recolor_shots()
        self._disable_saving = False

    def _set_item_background_recursive(self, root_item, color):
        """Итеративный обход дерева с отслеживанием посещённых элементов по id."""
        stack = [root_item]
        visited = set()
        while stack:
            item = stack.pop()
            item_id = id(item)
            if item_id in visited:
                continue
            visited.add(item_id)
            for col in range(self.tree.columnCount()):
                item.setBackground(col, QBrush(color))
            for i in range(item.childCount()):
                child = item.child(i)
                if id(child) not in visited:
                    stack.append(child)

    def copy_selected_model(self):
        """Копировать выбранную модель (корневой элемент модели)."""
        selected = self.tree.selectedItems()
        if not selected:
            return
        item = selected[0]
        data = item.data(0, Qt.UserRole)
        # Если выбран model_path или texture_path, поднимаемся к model_root
        if isinstance(data, tuple) and data[0] in ("model_path", "texture_path"):
            item = item.parent()
            data = item.data(0, Qt.UserRole)
        if isinstance(data, tuple) and data[0] == "model_root":
            group_name = data[1]
            model_path = data[2]
            shot_item = item.parent().parent().parent()
            shot = shot_item.data(0, Qt.UserRole)
            if not shot:
                return
            for m in shot.point_groups.get(group_name, []):
                if m["path"] == model_path:
                    import copy
                    self.copied_model_data = (group_name, copy.deepcopy(m))
                    self.log_info(f"Copied model '{m['name']}' from group '{group_name}'")
                    return
        self.log_info("No model selected to copy")

    def paste_model_to_selected(self):
        """Вставить скопированную модель в выбранный элемент."""
        if not self.copied_model_data:
            self.log_info("Nothing to paste")
            return

        src_group_name, model_dict = self.copied_model_data
        if src_group_name is None:
            src_group_name = "CAMERA"

        selected = self.tree.selectedItems()
        if not selected:
            self.log_info("No target selected for paste")
            return
        item = selected[0]
        # Определяем целевой шот и целевую группу
        target_shot = None
        target_group_name = None

        # Если выбран шот (корневой элемент)
        if item.parent() is None:
            target_shot = item.data(0, Qt.UserRole)
            if target_shot:
                groups = target_shot.point_groups
                if len(groups) == 1:
                    target_group_name = next(iter(groups.keys()))
                elif src_group_name in groups:
                    target_group_name = src_group_name
                else:
                    target_group_name = "CAMERA"
        else:
            # Ищем родительский шот и группу
            shot_item = item
            while shot_item.parent():
                shot_item = shot_item.parent()
            target_shot = shot_item.data(0, Qt.UserRole)
            if not target_shot:
                return
            # Определяем группу: если выбран элемент группы, модели или текстуры
            data = item.data(0, Qt.UserRole)
            if isinstance(data, tuple) and data[0] == "group":
                target_group_name = data[1]
            elif isinstance(data, tuple) and data[0] in ("model_root", "model_path", "texture_path"):
                # поднимаемся к группе
                group_item = item
                while group_item and group_item.parent() and group_item.parent().text(0) != "Point Groups":
                    group_item = group_item.parent()
                if group_item and group_item.parent() and group_item.parent().text(0) == "Point Groups":
                    group_data = group_item.data(0, Qt.UserRole)
                    if isinstance(group_data, tuple) and group_data[0] == "group":
                        target_group_name = group_data[1]
            else:
                # Если выбран "Point Groups" или другой элемент, ищем первую группу?
                target_group_name = "CAMERA"

        if not target_shot:
            self.log_info("Could not determine target shot")
            return
        if not target_group_name:
            target_group_name = "CAMERA"

        # Проверяем существование группы в целевом шоте, создаём если нужно
        if target_group_name not in target_shot.point_groups:
            target_shot.point_groups[target_group_name] = []
            self.log_info(f"Created group '{target_group_name}' in shot '{target_shot.name}'")

        # Добавляем модель (глубокую копию)
        import copy
        new_model = copy.deepcopy(model_dict)
        # Если у модели нет имени, создаём из пути
        if "name" not in new_model:
            new_model["name"] = os.path.splitext(os.path.basename(new_model["path"]))[0]

        target_shot.point_groups[target_group_name].append(new_model)
        target_shot._dirty = True
        target_shot.schedule_save()
        self.log_info(f"Pasted model '{new_model['name']}' into group '{target_group_name}' of shot '{target_shot.name}'")

        # Обновляем дерево
        self.populate_tree()

    def populate_tree(self):
        self._store_tree_state()                     
        self._sorting = False
        self._updating_tree = True
        state = self.save_tree_expansion_state()
        self.tree.clear()
        for idx, shot in enumerate(self.shots):
            bg_color = QColor(240, 240, 240) if idx % 2 == 0 else QColor(220, 220, 220)

            main_seq = next((s for s in shot.sequences if s.is_main), shot.sequences[0] if shot.sequences else None)
            if main_seq:
                sensor_w = str(shot.user_sensor_width if shot.user_sensor_width is not None else main_seq.sensor_width if main_seq.sensor_width is not None else '')
                sensor_h = str(shot.user_sensor_height if shot.user_sensor_height is not None else main_seq.sensor_height if main_seq.sensor_height is not None else '')
                focal_val = str(shot.user_focal if shot.user_focal is not None else main_seq.focal if main_seq.focal is not None else '')
            else:
                sensor_w = str(shot.user_sensor_width if shot.user_sensor_width is not None else '')
                sensor_h = str(shot.user_sensor_height if shot.user_sensor_height is not None else '')
                focal_val = str(shot.user_focal if shot.user_focal is not None else '')

            shot_item = QTreeWidgetItem([shot.name, sensor_w, sensor_h, focal_val, f"Frames: {shot.frame_count}"])
            font = shot_item.font(0)
            font.setBold(True)
            font.setPointSize(font.pointSize() + SHOT_FONT_SIZE_OFFSET)
            for col in range(self.tree.columnCount()):
                shot_item.setFont(col, font)

            shot_item.setFlags(shot_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
            shot_item.setCheckState(0, Qt.Checked if shot.selected else Qt.Unchecked)
            shot_item.setData(0, Qt.UserRole, shot)
            self.tree.addTopLevelItem(shot_item)
            shot_item.setExpanded(False)

            # Layers
            layers_item = QTreeWidgetItem(["Layers", "", "", "", ""])
            self._set_child_font(layers_item)
            shot_item.addChild(layers_item)
            for seq in shot.sequences:
                seq_item = QTreeWidgetItem([seq.full_name, "", "", "", f"{len(seq.files)} frames"])
                seq_item.setFlags(seq_item.flags() | Qt.ItemIsUserCheckable)
                seq_item.setCheckState(0, Qt.Checked if shot.sequence_selected.get(seq.full_name, True) else Qt.Unchecked)
                seq_item.setData(0, Qt.UserRole, ("seq", seq.full_name))
                self._set_child_font(seq_item)
                layers_item.addChild(seq_item)

            # Point Groups
            groups_item = QTreeWidgetItem(["Point Groups", "", "", "", ""])
            self._set_child_font(groups_item)
            shot_item.addChild(groups_item)
            group_names = sorted(shot.point_groups.keys())
            if "CAMERA" in group_names:
                group_names.remove("CAMERA")
                group_names.insert(0, "CAMERA")
            for group_name in group_names:
                models = shot.point_groups[group_name]
                group_item = QTreeWidgetItem([group_name, "", "", "", f"{len(models)} model(s)"])
                group_item.setFlags(group_item.flags() | Qt.ItemIsEditable)
                group_item.setData(0, Qt.UserRole, ("group", group_name))
                self._set_child_font(group_item)
                groups_item.addChild(group_item)

                for model in models:
                    # Корневой элемент модели (имя)
                    model_root_item = QTreeWidgetItem([model["name"], "", "", "", ""])
                    model_root_item.setFlags(model_root_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
                    model_root_item.setCheckState(0, Qt.Checked if model["enabled"] else Qt.Unchecked)
                    model_root_item.setData(0, Qt.UserRole, ("model_root", group_name, model["path"]))
                    self._set_child_font(model_root_item)
                    group_item.addChild(model_root_item)

                    # Путь модели (без текстового префикса)
                    model_path_item = QTreeWidgetItem([model["path"], "", ""])
                    model_path_item.setFlags(model_path_item.flags() | Qt.ItemIsEditable)
                    model_path_item.setData(0, Qt.UserRole, ("model_path", group_name, model["path"]))
                    self._set_child_font(model_path_item)
                    model_root_item.addChild(model_path_item)
                    if BUTTONS_IN_TREE:
                        btn_model_browse = QPushButton("Browse")
                        btn_model_browse.clicked.connect(lambda checked, g=group_name, m=model: self.browse_model_for_model(g, m))
                        self.tree.setItemWidget(model_path_item, 2, btn_model_browse)

                    # Текстура (без текстового префикса)
                    texture_item = QTreeWidgetItem([model["texture"]["path"], "", ""])
                    texture_item.setFlags(texture_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
                    texture_item.setCheckState(0, Qt.Checked if model["texture"]["enabled"] else Qt.Unchecked)
                    texture_item.setData(0, Qt.UserRole, ("texture_path", group_name, model["path"]))
                    self._set_child_font(texture_item)
                    model_root_item.addChild(texture_item)
                    if BUTTONS_IN_TREE:
                        btn_texture_browse = QPushButton("Browse")
                        btn_texture_browse.clicked.connect(lambda checked, g=group_name, m=model: self.browse_texture_for_model(g, m))
                        self.tree.setItemWidget(texture_item, 2, btn_texture_browse)

                group_item.setExpanded(True)

        self.restore_tree_expansion_state(state)
        self.recolor_shots()
        self._updating_tree = False
        self.tree.update()
        self.tree.viewport().update()
        QTimer.singleShot(0, self._restore_tree_state)

    def on_tree_item_changed(self, item, column):
        if self._disable_saving:
            return
        if self._sorting:
            return
        if self._updating_tree:
            return
        # Шот (нет родителя)
        if item.parent() is None:
            shot = item.data(0, Qt.UserRole)
            if shot:
                if column == 0:  # чекбокс
                    shot.selected = item.checkState(0) == Qt.Checked
                    if not shot.processed:
                        self.recolor_shots()
                elif column == 1:  # sensor W
                    text = item.text(1).strip()
                    try:
                        shot.user_sensor_width = float(text) if text else None
                    except ValueError:
                        shot.user_sensor_width = None
                    shot._dirty = True
                    shot.schedule_save()
                    if shot.user_sensor_width is not None:
                        item.setText(1, str(shot.user_sensor_width))
                    else:
                        item.setText(1, "")
                elif column == 2:  # sensor H
                    text = item.text(2).strip()
                    try:
                        shot.user_sensor_height = float(text) if text else None
                    except ValueError:
                        shot.user_sensor_height = None
                    shot._dirty = True
                    shot.schedule_save()
                    if shot.user_sensor_height is not None:
                        item.setText(2, str(shot.user_sensor_height))
                    else:
                        item.setText(2, "")
                elif column == 3:  # focal
                    text = item.text(3).strip()
                    try:
                        shot.user_focal = float(text) if text else None
                    except ValueError:
                        shot.user_focal = None
                    shot._dirty = True
                    shot.schedule_save()
                    if shot.user_focal is not None:
                        item.setText(3, str(shot.user_focal))
                    else:
                        item.setText(3, "")
            return

        # Слой (Layers)
        parent = item.parent()
        if parent and parent.text(0) == "Layers":
            shot_item = parent.parent()
            if shot_item:
                shot = shot_item.data(0, Qt.UserRole)
                if shot and column == 0:
                    seq_name = item.text(0)
                    selected = item.checkState(0) == Qt.Checked
                    shot.sequence_selected[seq_name] = selected
                    shot._dirty = True
                    shot.schedule_save()
            return

        # Группа, модель, текстура
        data = item.data(0, Qt.UserRole)
        if isinstance(data, tuple):
            if data[0] == "group" and column == 0:
                # Переименование группы
                group_name = data[1]
                new_name = item.text(0)
                if new_name != group_name:
                    shot_item = item.parent().parent()
                    if shot_item:
                        shot = shot_item.data(0, Qt.UserRole)
                        if shot:
                            models = shot.point_groups.pop(group_name, [])
                            shot.point_groups[new_name] = models
                            shot._dirty = True
                            shot.schedule_save()
                            item.setData(0, Qt.UserRole, ("group", new_name))
            elif data[0] == "model_root":
                # Корневой элемент модели: чекбокс включения или редактирование имени
                group_name = data[1]
                model_path = data[2]
                shot_item = item.parent().parent().parent()
                shot = shot_item.data(0, Qt.UserRole)
                if shot:
                    if column == 0:
                        enabled = item.checkState(0) == Qt.Checked
                        shot.set_model_enabled(group_name, model_path, enabled)
                    elif column == 0 and item.isSelected():
                        new_name = item.text(0)
                        for m in shot.point_groups.get(group_name, []):
                            if m["path"] == model_path:
                                m["name"] = new_name
                                shot._dirty = True
                                shot.schedule_save()
                                break
            elif data[0] == "model_path":
                # Путь модели (колонка 0 редактируется)
                group_name = data[1]
                model_path = data[2]
                shot_item = item.parent().parent().parent().parent()
                shot = shot_item.data(0, Qt.UserRole)
                if shot and column == 0:
                    new_path = item.text(0)
                    for m in shot.point_groups.get(group_name, []):
                        if m["path"] == model_path:
                            m["path"] = new_path
                            # Обновляем имя, если оно совпадало со старым именем файла
                            old_name = m["name"]
                            old_base = os.path.splitext(os.path.basename(old_name))[0]
                            new_base = os.path.splitext(os.path.basename(new_path))[0]
                            if old_name == old_base or old_name == "":
                                m["name"] = new_base
                            shot._dirty = True
                            shot.schedule_save()
                            break
            elif data[0] == "texture_path":
                # Текстура: чекбокс включения (колонка 0) или редактирование пути (колонка 0)
                group_name = data[1]
                model_path = data[2]
                shot_item = item.parent().parent().parent().parent()
                shot = shot_item.data(0, Qt.UserRole)
                if shot:
                    # Для различения: если изменился текст пути, то item.text(0) не равен текущему пути в модели
                    new_path = item.text(0)
                    for m in shot.point_groups.get(group_name, []):
                        if m["path"] == model_path:
                            if new_path != m["texture"]["path"]:
                                # Редактирование пути
                                m["texture"]["path"] = new_path
                                m["texture"]["enabled"] = bool(new_path)
                                shot._dirty = True
                                shot.schedule_save()
                            else:
                                # Изменение чекбокса
                                enabled = item.checkState(0) == Qt.Checked
                                m["texture"]["enabled"] = enabled
                                shot._dirty = True
                                shot.schedule_save()
                            break

    def browse_model_for_model(self, group_name, model):
        """Обработчик кнопки Browse для пути модели."""
        path, _ = QFileDialog.getOpenFileName(self, "Select OBJ model", "", "OBJ files (*.obj)")
        if path:
            model["path"] = path
            # Если имя модели не задано или равно старому имени файла, обновляем
            old_name = model["name"]
            old_base = os.path.splitext(os.path.basename(old_name))[0]
            new_base = os.path.splitext(os.path.basename(path))[0]
            if old_name == old_base or old_name == "":
                model["name"] = new_base
            shot = self.find_shot_for_model(group_name, model["path"])
            if shot:
                shot._dirty = True
                shot.schedule_save()
                self.populate_tree()

    def browse_texture_for_model(self, group_name, model):
        """Обработчик кнопки Browse для текстуры."""
        path, _ = QFileDialog.getOpenFileName(self, "Select texture", "", "Image files (*.jpg *.png *.tif *.exr)")
        if path:
            model["texture"]["path"] = path
            model["texture"]["enabled"] = True
            shot = self.find_shot_for_model(group_name, model["path"])
            if shot:
                shot._dirty = True
                shot.schedule_save()
                self.populate_tree()

    def find_shot_for_model(self, group_name, model_path):
        """Находит шот, содержащий данную модель в указанной группе."""
        for shot in self.shots:
            if group_name in shot.point_groups:
                for m in shot.point_groups[group_name]:
                    if m["path"] == model_path:
                        return shot
        return None


    def update_resources_panel(self):
        """Обновить панель ресурсов (перестроить дерево)."""
        self.populate_resources_tree()


    def browse_model_for_resource(self, idx):
        """Выбрать OBJ-файл для модели в ресурсах."""
        if not self.project_resources or idx >= len(self.project_resources.models):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select OBJ model", "", "OBJ files (*.obj)")
        if path:
            self.project_resources.models[idx]["model_path"] = path
            # Если имя модели ещё не задано, установить по имени файла
            if not self.project_resources.models[idx]["name"] or self.project_resources.models[idx]["name"] == "unnamed":
                name = os.path.splitext(os.path.basename(path))[0]
                self.project_resources.models[idx]["name"] = name
            self.project_resources.save()
            self.populate_resources_tree()

    def browse_texture_for_resource(self, idx):
        """Выбрать текстуру для модели в ресурсах."""
        if not self.project_resources or idx >= len(self.project_resources.models):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select texture", "", "Image files (*.jpg *.png *.tif *.exr)")
        if path:
            self.project_resources.models[idx]["texture_path"] = path
            self.project_resources.save()
            self.populate_resources_tree()

    def show_tree_context_menu(self, position):
        item = self.tree.itemAt(position)
        if not item:
            return
        data = item.data(0, Qt.UserRole)
        if isinstance(data, tuple):
            # Обработка группы
            if data[0] == "group":
                group_name = data[1]
                menu = QMenu()
                add_model_action = menu.addAction("Add 3D model")
                rename_action = menu.addAction("Rename group")
                delete_action = menu.addAction("Delete group")
                paste_action = menu.addAction("Paste model")
                action = menu.exec_(self.tree.viewport().mapToGlobal(position))
                if action == add_model_action:
                    self.add_model_to_group(item, group_name)
                elif action == rename_action:
                    self.rename_group(item, group_name)
                elif action == delete_action:
                    self.delete_group(item, group_name)
                elif action == paste_action:
                    self.paste_model_to_selected()
            # Обработка элементов модели (корневой, путь, текстура)
            elif data[0] in ("model_root", "model_path", "texture_path"):
                group_name = data[1]
                model_path = data[2]
                # Определяем родительский элемент группы (для model_root это элемент самого model_root, для других – parent)
                if data[0] == "model_root":
                    group_item = item.parent()
                else:
                    group_item = item.parent().parent()  # для model_path/texture_path
                # Создаём меню
                menu = QMenu()
                edit_action = menu.addAction("Edit model")
                remove_action = menu.addAction("Remove model")
                copy_action = menu.addAction("Copy model")
                paste_action = menu.addAction("Paste model")
                action = menu.exec_(self.tree.viewport().mapToGlobal(position))
                if action == edit_action:
                    self.edit_model(group_item, group_name, model_path)
                elif action == remove_action:
                    self.remove_model_from_group(group_item, group_name, model_path, item)
                elif action == copy_action:
                    self.copy_selected_model()
                elif action == paste_action:
                    self.paste_model_to_selected()
        else:
            # Шот или Point Groups
            if item.parent() is None:
                shot = item.data(0, Qt.UserRole)
                if shot:
                    menu = QMenu()
                    add_group_action = menu.addAction("Add point group")
                    paste_action = menu.addAction("Paste model")
                    action = menu.exec_(self.tree.viewport().mapToGlobal(position))
                    if action == add_group_action:
                        self.add_point_group_to_shot(shot)
                    elif action == paste_action:
                        self.paste_model_to_selected()
            elif item.text(0) == "Point Groups":
                shot_item = item.parent()
                if shot_item:
                    shot = shot_item.data(0, Qt.UserRole)
                    if shot:
                        menu = QMenu()
                        add_group_action = menu.addAction("Add point group")
                        paste_action = menu.addAction("Paste model")
                        action = menu.exec_(self.tree.viewport().mapToGlobal(position))
                        if action == add_group_action:
                            self.add_point_group_to_shot(shot)
                        elif action == paste_action:
                            self.paste_model_to_selected()


    def edit_texture(self, group_item, group_name, model_path, texture_item):
        shot_item = group_item.parent().parent()
        shot = shot_item.data(0, Qt.UserRole)
        if not shot:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Select texture", "", "Image files (*.jpg *.png *.tif *.exr)")
        if path:
            shot.set_texture_path(group_name, model_path, path, enabled=True)
            self.populate_tree()

    def remove_texture(self, group_item, group_name, model_path, texture_item):
        shot_item = group_item.parent().parent()
        shot = shot_item.data(0, Qt.UserRole)
        if not shot:
            return
        shot.set_texture_path(group_name, model_path, "", enabled=False)
        self.populate_tree()



    def add_model_to_group(self, group_item, group_name):
        shot_item = group_item.parent().parent()
        shot = shot_item.data(0, Qt.UserRole)
        if not shot:
            return
        dialog = EditModelDialog(parent=self, project_resources=self.project_resources)
        if dialog.exec_():
            model_dict = dialog.get_model_dict()
            if model_dict["path"]:
                shot.add_model_to_group(
                    group_name,
                    model_dict["path"],
                    model_dict["enabled"],
                    model_dict["texture"]["path"],
                    model_dict["texture"]["enabled"],
                    name=model_dict["name"] if model_dict["name"] else None
                )
                self.populate_tree()

    def edit_model(self, group_item, group_name, model_path):
        shot_item = group_item.parent().parent()
        shot = shot_item.data(0, Qt.UserRole)
        if not shot:
            return
        # Находим model_dict
        model_dict = None
        for m in shot.point_groups.get(group_name, []):
            if m["path"] == model_path:
                model_dict = m
                break
        if model_dict:
            dialog = EditModelDialog(model_dict, self, project_resources=self.project_resources)
            if dialog.exec_():
                new_dict = dialog.get_model_dict()
                idx = shot.point_groups[group_name].index(model_dict)
                shot.point_groups[group_name][idx] = new_dict
                shot._dirty = True
                shot.schedule_save()
                self.populate_tree()

    def rename_group(self, group_item, old_name):
        # Inline edit is already handled by on_tree_item_changed, but keep dialog as fallback
        # We'll just trigger edit mode on the item
        group_item.setFlags(group_item.flags() | Qt.ItemIsEditable)
        self.tree.editItem(group_item, 1)

    def delete_group(self, group_item, group_name):
        shot_item = group_item.parent().parent()
        shot = shot_item.data(0, Qt.UserRole)
        if not shot:
            return
        if group_name == "CAMERA":
            QMessageBox.warning(self, "Warning", "Cannot delete the default CAMERA group.")
            return
        reply = QMessageBox.question(self, "Delete group", f"Delete group '{group_name}' and all its models?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            shot.point_groups.pop(group_name, None)
            shot._dirty = True
            shot.schedule_save()
            self.populate_tree()

    def remove_model_from_group(self, group_item, group_name, model_path, model_item):
        shot_item = group_item.parent().parent()
        shot = shot_item.data(0, Qt.UserRole)
        if not shot:
            return
        shot.remove_model_from_group(group_name, model_path)
        self.populate_tree()

    def on_item_double_clicked(self, item, column):
        # Шот: редактирование сенсора/фокусного
        if item.parent() is None and column in (1,2,3):
            self.tree.editItem(item, column)
            return
        data = item.data(0, Qt.UserRole)
        if isinstance(data, tuple):
            if data[0] == "group" and column == 0:
                self.tree.editItem(item, 0)
            elif data[0] in ("model_root", "model_path", "texture_path") and column == 0:
                self.tree.editItem(item, 0)

    def add_point_group_to_shot(self, shot):
        name, ok = QInputDialog.getText(self, "New point group", "Group name:")
        if ok and name:
            if name in shot.point_groups:
                QMessageBox.warning(self, "Warning", f"Group '{name}' already exists.")
                return
            shot.point_groups[name] = []
            shot._dirty = True
            shot.schedule_save()
            self.populate_tree()

    def add_point_group(self):
        selected = self.tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Warning", "Select a shot or point group to add a new group.")
            return
        shot = None
        for item in selected:
            # Ищем шот (элемент без родителя)
            if item.parent() is None:
                shot = item.data(0, Qt.UserRole)
                break
        if not shot:
            QMessageBox.warning(self, "Warning", "Please select a shot or an item within a shot.")
            return
        self.add_point_group_to_shot(shot)

    def add_model_to_selected_group(self):
        selected = self.tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Warning", "Select a point group to add a model.")
            return
        group_item = None
        for item in selected:
            data = item.data(0, Qt.UserRole)
            if isinstance(data, tuple) and data[0] == "group":
                group_item = item
                break
        if not group_item:
            QMessageBox.warning(self, "Warning", "Please select a point group.")
            return
        group_name = group_item.data(0, Qt.UserRole)[1]
        self.add_model_to_group(group_item, group_name)

    def remove_selected_item(self):
        """Удалить выбранный элемент (группу или модель)."""
        selected = self.tree.selectedItems()
        if not selected:
            return
        item = selected[0]
        data = item.data(0, Qt.UserRole)
        if isinstance(data, tuple):
            if data[0] == "group":
                self.delete_group(item, data[1])
            elif data[0] == "model":
                group_item = item.parent()
                if group_item:
                    group_data = group_item.data(0, Qt.UserRole)
                    if isinstance(group_data, tuple) and group_data[0] == "group":
                        self.remove_model_from_group(group_item, group_data[1], data[2], item)
            elif data[0] == "texture":
                # Remove texture only if needed? For now, just edit via double-click
                pass


    def scan_shots(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Warning", "Please enter or select a root folder.")
            return

        if not os.path.exists(path):
            self.log_error(f"Path does not exist: {path}")
            QMessageBox.warning(self, "Error", f"The selected path does not exist:\n{path}")
            return
        if not os.path.isdir(path):
            self.log_error(f"Path is not a directory: {path}")
            QMessageBox.warning(self, "Error", f"The selected path is not a directory:\n{path}")
            return

        self.root_path = path
        # Загружаем ресурсы проекта сразу после определения корневой папки
        self.setup_project_resources(path)

        self.shots.clear()
        self.tree.clear()
        self.tree.setSortingEnabled(False)

        logging_enabled = self.cb_logging.isChecked()

        layers_path_candidate = os.path.join(path, "layers")
        tracking_path_candidate = os.path.join(path, "tracking")
        is_shot_folder = os.path.isdir(layers_path_candidate) and os.path.isdir(tracking_path_candidate)

        if is_shot_folder:
            self.log_info(f"Selected folder appears to be a shot folder: {path}")
            base_item = os.path.basename(path)
            layers_path = layers_path_candidate
            if os.path.isdir(layers_path):
                for sub in os.listdir(layers_path):
                    sub_path = os.path.join(layers_path, sub)
                    if not os.path.isdir(sub_path):
                        continue
                    pattern = re.compile(rf"^{re.escape(base_item)}(.*)_track$")
                    match = pattern.match(sub)
                    if not match:
                        continue
                    suffix = match.group(1)
                    shot_name = base_item + suffix if suffix else base_item
                    self.log_info(f"  Found layer folder: {sub} -> shot name '{shot_name}'")
                    shot = Shot(path, shot_name, sub, log_func=self.log_with_level)
                    shot.scan(self.settings.data, camera_db=self.camera_db,
                            exr_viewer_rules=self.exr_viewer_rules, log_func=self.log_with_level)
                    for seq in shot.sequences:
                        seq.logging = logging_enabled
                    if shot.sequences:
                        self.shots.append(shot)
                        self.populate_tree()
                        if not self.headless:
                            QApplication.processEvents()
            else:
                self.log_error(f"Layers folder not found in {path}")
        else:
            self.log_info(f"Selected folder treated as root shots folder: {path}")
            try:
                items = os.listdir(path)
            except OSError as e:
                self.log_error(f"Cannot list directory {path}: {e}")
                return
            for item in items:
                full_path = os.path.join(path, item)
                if not os.path.isdir(full_path):
                    continue
                self.log_info(f"Checking item: {item}")
                layers_path = os.path.join(full_path, "layers")
                tracking_path = os.path.join(full_path, "tracking")
                if not os.path.isdir(layers_path) or not os.path.isdir(tracking_path):
                    continue
                pattern = re.compile(rf"^{re.escape(item)}(.*)_track$")
                for sub in os.listdir(layers_path):
                    sub_path = os.path.join(layers_path, sub)
                    if not os.path.isdir(sub_path):
                        continue
                    match = pattern.match(sub)
                    if not match:
                        continue
                    suffix = match.group(1)
                    shot_name = item + suffix if suffix else item
                    self.log_info(f"  Found layer folder: {sub} -> shot name '{shot_name}'")
                    shot = Shot(full_path, shot_name, sub, log_func=self.log_with_level)
                    shot.scan(self.settings.data, camera_db=self.camera_db,
                            exr_viewer_rules=self.exr_viewer_rules, log_func=self.log_with_level)
                    for seq in shot.sequences:
                        seq.logging = logging_enabled
                    if shot.sequences:
                        self.shots.append(shot)
                        self.populate_tree()
                        if not self.headless:
                            QApplication.processEvents()

        self.tree.setSortingEnabled(True)
        self.btn_start.setEnabled(True)
#        if self.auto_quit_on_finish:
            # запускаем обработку после небольшой паузы, чтобы GUI успел отрисоваться
#            QTimer.singleShot(500, self.start_processing)

        msg = f"Scan complete. Found shots: {len(self.shots)}"
        self.log_info(msg)

    def find_shot_item(self, shot_name):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.text(0) == shot_name:
                return item
        return None

    def on_shot_started(self, shot_name):
        self.current_processing_shot_name = shot_name
        item = self.find_shot_item(shot_name)
        if item:
            proc_color = self.settings.data.get("color_processing", (173, 216, 230))
            color = QColor(*proc_color)
            self._set_item_background_recursive(item, color)

    def on_shot_finished(self, shot_name, success, project_path):
        self.current_processing_shot_name = None
        item = self.find_shot_item(shot_name)
        if item:
            shot = item.data(0, Qt.UserRole)
            if shot:
                shot.processed = True
                shot.processed_success = success
                shot.save_config()
                # Снимаем галочку
                item.setCheckState(0, Qt.Unchecked)
                # Устанавливаем цвет в зависимости от успеха
                if success:
                    color_rgb = self.settings.data.get("color_success", (144, 238, 144))
                else:
                    color_rgb = self.settings.data.get("color_failure", (255, 182, 193))
                color = QColor(*color_rgb)
                self._set_item_background_recursive(item, color)

    def open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec_():
            self.settings.save()
            self.apply_log_settings()
            self.cb_logging.setChecked(self.settings.data.get("logging_enabled", True))
            self.apply_ui_font()
            self.init_external_modules()

    def show_logs(self):
        if not self.log_window:
            self.log_window = LogWindow(self)
            self.log_window.text_edit.setPlainText(self.log_text.toPlainText())
        self.log_window.show()
        self.log_window.raise_()

    def start_processing(self):
        selected_shots = [s for s in self.shots if s.selected]
        if not selected_shots:
            QMessageBox.warning(self, "Warning", "No shots selected.")
            return
        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.btn_abort.setEnabled(True)
        self.btn_scan.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.worker = ProcessingWorker(selected_shots, self.settings)
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker.log_signal.connect(self.on_log)
        self.worker.progress_global.connect(self.update_global_progress)
        self.worker.progress_shot.connect(self.update_shot_progress)
        self.worker.progress_sequence.connect(self.update_seq_progress)
        self.worker.shot_started.connect(self.on_shot_started)
        self.worker.shot_finished.connect(self.on_shot_finished)
        self.worker.finished.connect(self.on_processing_finished)
        self.worker_thread.start()

    def on_log(self, msg, level):
        if level == "success":
            self.log_success(msg)
        elif level == "error":
            self.log_error(msg)
        else:
            self.log_info(msg)
        if self.cb_logging.isChecked():
            print(msg)

    def update_global_progress(self, current, total):
        self.global_progress.setMaximum(total)
        self.global_progress.setValue(current + 1)
        self.global_progress.setFormat(f"Shot {current+1}/{total}")

    def update_shot_progress(self, current, total):
        self.shot_progress.setMaximum(total)
        self.shot_progress.setValue(current)

    def update_seq_progress(self, current, total):
        self.seq_progress.setMaximum(total)
        self.seq_progress.setValue(current)

    def on_processing_finished(self, processed_projects):
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_abort.setEnabled(False)
        self.btn_scan.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.global_progress.reset()
        self.shot_progress.reset()
        self.seq_progress.reset()
        if processed_projects:
            self.log_success("Processing finished. Created projects:")
            for shot_name, proj_path in processed_projects.items():
                self.log_success(f"  {shot_name}: {proj_path}")
        else:
            self.log_info("Processing finished. No projects created.")
        QMessageBox.information(self, "Done", "Processing finished.")
        if self.auto_quit_on_finish:
            QApplication.quit()

    def pause_processing(self):
        if self.worker:
            self.worker.pause()
            self.btn_pause.setText("Resume")
            self.btn_pause.clicked.disconnect()
            self.btn_pause.clicked.connect(self.resume_processing)

    def resume_processing(self):
        if self.worker:
            self.worker.resume()
            self.btn_pause.setText("Pause")
            self.btn_pause.clicked.disconnect()
            self.btn_pause.clicked.connect(self.pause_processing)

    def stop_processing(self):
        if self.worker:
            self.worker.stop()
            self.btn_stop.setEnabled(False)

    def abort_processing(self):
        if self.worker:
            self.worker.abort()
            self.btn_abort.setEnabled(False)


    def run_headless(self):
        """Безголовый режим: сканирование и создание проектов без GUI."""
        print("=== Запуск безголового режима ===")
        try:
            self.scan_shots()
        except Exception as e:
            print(f"Ошибка при сканировании: {e}")
            sys.exit(1)

        if not self.shots:
            print("Не найдено шотов для обработки.")
            sys.exit(1)

        success_count = 0
        for shot in self.shots:
            if not shot.sequences:
                continue
            print(f"\nОбработка шота: {shot.name}")
            try:
                success, project_path = self.process_shot_headless(shot)
            except Exception as e:
                print(f"  Критическая ошибка при обработке шота {shot.name}: {e}")
                success = False
            if success:
                print(f"  Проект создан: {project_path}")
                success_count += 1
            else:
                print(f"  ОШИБКА: не удалось создать проект для {shot.name}")

        print(f"\n=== Обработка завершена. Успешно: {success_count} из {len(self.shots)} ===")
        QApplication.quit()  # на случай, если есть активные события
        sys.exit(0 if success_count == len(self.shots) else 1)

    def process_shot_headless(self, shot):
        """Синхронное создание проекта для одного шота без добавления моделей."""
        # 1. Проверка на пропуски кадров
        if shot.has_gaps:
            print(f"  Предупреждение: шот {shot.name} имеет пропуски кадров")

        # 2. Подготовка директории tracking
        tracking_dir = os.path.join(shot.path, "tracking")
        if not os.path.exists(tracking_dir):
            os.makedirs(tracking_dir)

        # 3. Фиксированная версия v000 (перезапись)
        version = 0
        project_filename = f"{shot.name}_track_v{version:03d}.3de"
        project_path = os.path.join(tracking_dir, project_filename)

        # 4. Генерация bc-файлов для всех последовательностей
        selected_seqs = shot.sequences  # все
        bc_files = []          # для передачи в скрипт
        bc_files_paths = []    # для установки прав
        for seq in selected_seqs:
            print(f"  Генерация bc для {seq.full_name}...")
            bc_path = self.generate_bc_headless(seq, tracking_dir)
            if bc_path:
                bc_files.append((seq, bc_path))
                bc_files_paths.append(bc_path)
            else:
                print(f"  Не удалось сгенерировать bc для {seq.full_name}")

        # 5. Определение основной последовательности
        main_seq = next((s for s in shot.sequences if s.is_main), None)
        if main_seq is None and shot.sequences:
            main_seq = shot.sequences[0]
            print(f"  Предупреждение: нет точной основной последовательности, используем {main_seq.full_name}")
        if main_seq is None:
            print(f"  Ошибка: нет последовательностей для шота {shot.name}")
            return False, None

        proxy_seqs = [seq for seq in selected_seqs if seq != main_seq]

        # 6. Генерация скрипта 3DE (без моделей)
        script_content = self.generate_tde4_script_headless(shot, main_seq, proxy_seqs, bc_files, project_path)
        if script_content is None:
            print(f"  Ошибка: не удалось сгенерировать скрипт для {shot.name}")
            return False, None

        script_filename = f"_temp_{shot.name}_create_project.py"
        script_file = os.path.join(tracking_dir, script_filename)
        with open(script_file, 'w', encoding='utf-8') as f:
            f.write(script_content)
        os.chmod(script_file, int(self.settings.data.get("file_permissions", "664"), 8))
        print(f"  Временный скрипт сохранён: {script_file}")

        # 7. Запуск 3DE4
        tde4_path = self.settings.data["path_tde4"]
        if not os.path.isfile(tde4_path):
            print(f"  Ошибка: 3DE4 не найден: {tde4_path}")
            return False, None
        if not os.access(tde4_path, os.X_OK):
            print(f"  Ошибка: 3DE4 не исполняемый: {tde4_path}")
            return False, None

        cmd = [tde4_path, "-run_script", script_file]
        print(f"  Запуск 3DE4: {' '.join(cmd)}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=os.environ,
                encoding='utf-8',
                text=True
            )
            for line in iter(proc.stdout.readline, ''):
                line = line.strip()
                if line:
                    print(f"    3DE4: {line}")
            proc.wait()
            if proc.returncode == 0:
                print(f"  Проект успешно создан: {project_path}")
                # Собираем все созданные файлы
                created_files = [script_file, project_path]
                screenshot_path = project_path + ".jpg"
                if os.path.exists(screenshot_path):
                    created_files.append(screenshot_path)
                all_files = bc_files_paths + created_files
                self.fix_permissions(all_files)
                return True, project_path
            else:
                print(f"  Создание проекта завершилось с ошибкой (код {proc.returncode})")
                return False, None
        except Exception as e:
            print(f"  Ошибка при запуске 3DE4: {e}")
            return False, None

    def get_next_version_headless(self, tracking_dir, shot_name):
        """Определение следующего номера версии для проекта."""
        pattern = os.path.join(tracking_dir, f"{shot_name}_track_v*.3de")
        files = glob.glob(pattern)
        max_v = 0
        for f in files:
            base = os.path.basename(f)
            match = re.search(r'_v(\d+)\.3de$', base)
            if match:
                v = int(match.group(1))
                if v > max_v:
                    max_v = v
        return max_v + 1

    def generate_bc_headless(self, seq, out_dir):
        """Генерация bc-файла (синхронно, без сигналов)."""
        makebc = self.settings.data["path_makeBCFile"]
        if not os.path.isfile(makebc):
            print(f"  makeBCFile не найден: {makebc}")
            return None

        if not seq.files:
            print(f"  Нет файлов для {seq.full_name}")
            return None

        pattern = make_pattern_from_file(seq.files[0])
        if not pattern:
            print(f"  Не удалось создать шаблон из {seq.files[0]}")
            return None

        cmd = [
            makebc,
            "-source", pattern,
            "-start", str(seq.first_frame),
            "-end", str(seq.last_frame),
            "-out", out_dir,
            "-quality", str(self.settings.data["bc_quality"]),
            "-black", str(self.settings.data["bc_black"]),
            "-white", str(self.settings.data["bc_white"]),
            "-gamma", str(self.settings.data["bc_gamma"]),
            "-softclip", str(self.settings.data["bc_softclip"])
        ]
        if self.settings.data["import_exr_display_window"]:
            cmd.append("-import_exr_display_window")
        if self.settings.data["import_sxr_right_eye"]:
            cmd.append("-import_sxr_right_eye")

        print(f"  Запуск: {' '.join(cmd)}")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    universal_newlines=True, bufsize=1)
            for line in iter(proc.stdout.readline, ''):
                line = line.strip()
                if line:
                    print(f"    {line}")
            proc.wait()
            if proc.returncode != 0:
                print(f"  makeBCFile завершился с ошибкой (код {proc.returncode})")
                return None
        except Exception as e:
            print(f"  Ошибка при запуске makeBCFile: {e}")
            return None

        expected_name = expected_bc_name(seq.files[0])
        expected_path = os.path.join(out_dir, expected_name)
        if os.path.isfile(expected_path):
            return expected_path
        else:
            bc_files = glob.glob(os.path.join(out_dir, "*.3de_bcompress"))
            if bc_files:
                latest = max(bc_files, key=os.path.getmtime)
                print(f"  Найден bc-файл: {os.path.basename(latest)}")
                return latest
            else:
                print(f"  Файл {expected_path} не найден после генерации")
                return None

    def generate_tde4_script_headless(self, shot, main_seq, proxy_seqs, bc_files, project_path):
        """Генерация скрипта 3DE (без моделей)."""
        if not main_seq.files:
            print(f"Ошибка: основная последовательность {main_seq.full_name} не содержит файлов")
            return None
        if main_seq.first_frame is None or main_seq.last_frame is None:
            print(f"Ошибка: основная последовательность {main_seq.full_name} имеет неверный диапазон кадров")
            return None

        main_pattern = make_pattern_from_file(main_seq.files[0])
        if not main_pattern:
            print(f"Ошибка: не удалось создать шаблон из {main_seq.files[0]}")
            return None

        default_sensor_width = self.settings.data.get("sensor_width", 35.0)
        default_sensor_height = self.settings.data.get("sensor_height", 24.0)
        default_focal = self.settings.data.get("focal", 24.0)

        sensor_width = shot.user_sensor_width if shot.user_sensor_width is not None else (
            main_seq.sensor_width if main_seq.sensor_width is not None else default_sensor_width)
        sensor_height = shot.user_sensor_height if shot.user_sensor_height is not None else (
            main_seq.sensor_height if main_seq.sensor_height is not None else default_sensor_height)
        focal = shot.user_focal if shot.user_focal is not None else (
            main_seq.focal if main_seq.focal is not None else default_focal)

        lines = []
        lines.append("import tde4")
        lines.append("import os")
        lines.append("print('=== 3DE Project Setup ===')")
        lines.append("")

        # 1. Линза
        lines.append("lens = tde4.getFirstLens()")
        lines.append(f"print('Setting lens: sensor {sensor_width:.1f} x {sensor_height:.1f} mm, focal {focal:.1f} mm')")
        lines.append(f"tde4.setLensFBackWidth(lens, {sensor_width / 10:.2f})")
        lines.append(f"tde4.setLensFBackHeight(lens, {sensor_height / 10:.2f})")
        lines.append(f"tde4.setLensFocalLength(lens, {focal / 10:.2f})")
        lines.append("tde4.setLensPixelAspect(lens, 1.0)")
        lines.append(f"tde4.setLensFBackHeight(lens, {sensor_height / 10:.2f})")
        lines.append("tde4.setParameterAdjustFlag(lens, 'ADJUST_LENS_FOCAL_LENGTH', '', 1)")
        lines.append("tde4.setParameterAdjustFlag(lens, 'ADJUST_LENS_DISTORTION_PARAMETER', 'Distortion - Degree 2', 1)")
        lines.append("tde4.setParameterAdjustFlag(lens, 'ADJUST_LENS_DISTORTION_PARAMETER', 'Quartic Distortion - Degree 4', 1)")
        lines.append("")

        # 2. Камера
        lines.append("cam = tde4.getFirstCamera()")
        lines.append(f"tde4.setCameraName(cam, '{main_seq.full_name}')")
        lines.append("tde4.setCameraLens(cam, lens)")
        lines.append(f"tde4.setCameraPath(cam, r'{main_pattern}')")
        lines.append(f"tde4.setCameraSequenceAttr(cam, {main_seq.first_frame}, {main_seq.last_frame}, 1)")
        offset = self.settings.data["start_frame"]
        lines.append(f"tde4.setCameraFrameOffset(cam, {offset})")
        lines.append(f"tde4.setCamera8BitColorBlackWhite(cam, {self.settings.data['bc_black']}, {self.settings.data['bc_white']})")
        lines.append(f"tde4.setCamera8BitColorGamma(cam, {self.settings.data['bc_gamma']})")
        lines.append(f"tde4.setCamera8BitColorSoftclip(cam, {self.settings.data['bc_softclip']})")
        lines.append("")

        # 3. Ближняя плоскость отсечения
        lines.append("tde4.setNearClippingPlane(0.1)")
        lines.append("tde4.setNearClippingPlaneF6(0.1)")
        lines.append("")

        # 4. Прокси-последовательности
        if proxy_seqs:
            lines.append("# Прокси-последовательности")
            for idx, seq in enumerate(proxy_seqs, start=1):
                if not seq.files:
                    continue
                proxy_pattern = make_pattern_from_file(seq.files[0])
                if not proxy_pattern:
                    continue
                lines.append(f"tde4.setCameraProxyFootage(cam, {idx})")
                lines.append(f"tde4.setCameraPath(cam, r'{proxy_pattern}')")
                lines.append(f"tde4.setCameraSequenceAttr(cam, {seq.first_frame}, {seq.last_frame}, 1)")
                lines.append(f"print('Added proxy slot {idx}: {seq.full_name}')")
            lines.append("tde4.setCameraProxyFootage(cam, 0)")
            lines.append("")

        # 5. МОДЕЛИ НЕ ДОБАВЛЯЮТСЯ

        # 6. Сохранение и скриншот
        lines.append("print('Saving project...')")
        lines.append(f"tde4.saveProject(r'{project_path}')")
        lines.append("tde4.flushEventQueue()")
        lines.append("print('Project saved')")
        lines.append("tde4.updateGUI()")
        screenshot_path = project_path + ".jpg"
        lines.append("resx, resy = tde4.getMainWindowResolution()")
        lines.append(f"tde4.saveMainWindowScreenShot(r'{screenshot_path}', 'IMAGE_JPEG', 0, 0, resx, resy)")
        lines.append("tde4.flushEventQueue()")
        lines.append("print('Screenshot saved')")
        lines.append("tde4.updateGUI()")
        lines.append("print('=== Done ===')")
        lines.append("raise SystemExit(0)")

        return "\n".join(lines)

# ================== Settings Dialog ==================
class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._updating_tree = False
        
        
        self.setWindowTitle("Settings")
        self.setModal(True)
        layout = QFormLayout()

        self.edit_makebc = QLineEdit(settings.data["path_makeBCFile"])
        layout.addRow("Path to makeBCFile:", self.edit_makebc)
        btn_browse_makebc = QPushButton("Browse...")
        btn_browse_makebc.clicked.connect(lambda: self.browse_file(self.edit_makebc))
        layout.addRow("", btn_browse_makebc)

        self.edit_tde4 = QLineEdit(settings.data["path_tde4"])
        layout.addRow("Path to 3DE4:", self.edit_tde4)
        btn_browse_tde4 = QPushButton("Browse...")
        btn_browse_tde4.clicked.connect(lambda: self.browse_file(self.edit_tde4))
        layout.addRow("", btn_browse_tde4)

        self.spin_sensorw = QDoubleSpinBox()
        self.spin_sensorw.setRange(0.1, 1000)
        self.spin_sensorw.setValue(settings.data["sensor_width"])
        layout.addRow("Sensor width (mm):", self.spin_sensorw)

        self.spin_sensorh = QDoubleSpinBox()
        self.spin_sensorh.setRange(0.1, 1000)
        self.spin_sensorh.setValue(settings.data["sensor_height"])
        layout.addRow("Sensor height (mm):", self.spin_sensorh)

        self.spin_focal = QDoubleSpinBox()
        self.spin_focal.setRange(0.1, 1000)
        self.spin_focal.setValue(settings.data["focal"])
        layout.addRow("Focal length (mm):", self.spin_focal)

        self.spin_quality = QSpinBox()
        self.spin_quality.setRange(1, 100)
        self.spin_quality.setValue(settings.data["bc_quality"])
        layout.addRow("BC quality:", self.spin_quality)

        self.spin_black = QSpinBox()
        self.spin_black.setRange(0, 255)
        self.spin_black.setValue(settings.data["bc_black"])
        layout.addRow("Black point:", self.spin_black)

        self.spin_white = QSpinBox()
        self.spin_white.setRange(0, 255)
        self.spin_white.setValue(settings.data["bc_white"])
        layout.addRow("White point:", self.spin_white)

        self.spin_gamma = QDoubleSpinBox()
        self.spin_gamma.setRange(0.1, 10.0)
        self.spin_gamma.setValue(settings.data["bc_gamma"])
        layout.addRow("Gamma:", self.spin_gamma)

        self.spin_softclip = QDoubleSpinBox()
        self.spin_softclip.setRange(0.0, 1.0)
        self.spin_softclip.setSingleStep(0.01)
        self.spin_softclip.setValue(settings.data["bc_softclip"])
        layout.addRow("Softclip:", self.spin_softclip)

        self.chk_exr_disp = QCheckBox()
        self.chk_exr_disp.setChecked(settings.data["import_exr_display_window"])
        layout.addRow("Import EXR display window:", self.chk_exr_disp)

        self.chk_sxr = QCheckBox()
        self.chk_sxr.setChecked(settings.data["import_sxr_right_eye"])
        layout.addRow("Import SXR right eye:", self.chk_sxr)

        self.spin_start_frame = QSpinBox()
        self.spin_start_frame.setRange(1, 99999)
        self.spin_start_frame.setValue(settings.data["start_frame"])
        layout.addRow("Start frame (default):", self.spin_start_frame)

        self.chk_logging = QCheckBox()
        self.chk_logging.setChecked(settings.data.get("logging_enabled", True))
        layout.addRow("Enable logging by default:", self.chk_logging)

        self.spin_log_lines = QSpinBox()
        self.spin_log_lines.setRange(1, 100)
        self.spin_log_lines.setValue(settings.data.get("log_lines", 5))
        layout.addRow("Number of log lines (minimum):", self.spin_log_lines)

        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(6, 72)
        self.spin_font_size.setValue(settings.data.get("font_size", 12))
        layout.addRow("Log font size:", self.spin_font_size)

        self.spin_ui_font_size = QSpinBox()
        self.spin_ui_font_size.setRange(6, 72)
        self.spin_ui_font_size.setValue(settings.data.get("ui_font_size", 10))
        layout.addRow("UI font size:", self.spin_ui_font_size)

        self.chk_ui_bold = QCheckBox()
        self.chk_ui_bold.setChecked(settings.data.get("ui_font_bold", False))
        layout.addRow("Bold UI font:", self.chk_ui_bold)

        self.chk_log_bold = QCheckBox()
        self.chk_log_bold.setChecked(settings.data.get("log_font_bold", False))
        layout.addRow("Bold log font:", self.chk_log_bold)

        self.chk_highlight = QCheckBox()
        self.chk_highlight.setChecked(settings.data.get("log_highlight_important", False))
        layout.addRow("Highlight important data (bold):", self.chk_highlight)

        self.edit_camera_json = QLineEdit(settings.data.get("camera_sensor_json_path", ""))
        layout.addRow("Camera sensor database:", self.edit_camera_json)
        btn_browse_cam_json = QPushButton("Browse...")
        btn_browse_cam_json.clicked.connect(lambda: self.browse_file(self.edit_camera_json))
        layout.addRow("", btn_browse_cam_json)

        self.edit_exr_reader = QLineEdit(settings.data.get("exr_metadata_reader_path", ""))
        layout.addRow("exr_metadata_reader.py:", self.edit_exr_reader)
        btn_browse_exr = QPushButton("Browse...")
        btn_browse_exr.clicked.connect(lambda: self.browse_file(self.edit_exr_reader))
        layout.addRow("", btn_browse_exr)

        self.edit_exr_viewer = QLineEdit(settings.data.get("exr_viewer_settings_path", ""))
        layout.addRow("exr_viewer_settings.json:", self.edit_exr_viewer)
        btn_browse_exr_viewer = QPushButton("Browse...")
        btn_browse_exr_viewer.clicked.connect(lambda: self.browse_file(self.edit_exr_viewer))
        layout.addRow("", btn_browse_exr_viewer)

        self.edit_file_perm = QLineEdit(settings.data.get("file_permissions", "664"))
        layout.addRow("File permissions (octal):", self.edit_file_perm)

        self.edit_dir_perm = QLineEdit(settings.data.get("dir_permissions", "775"))
        layout.addRow("Directory permissions (octal):", self.edit_dir_perm)

        # Цвета
        self.btn_processing_color = QPushButton("Choose...")
        self.lbl_processing_color = QLabel()
        self.lbl_processing_color.setFixedSize(50, 20)
        self.lbl_processing_color.setAutoFillBackground(True)
        self.set_color_label(self.lbl_processing_color, settings.data.get("color_processing", (173,216,230)))
        self.btn_processing_color.clicked.connect(lambda: self.choose_color(self.lbl_processing_color, "color_processing"))
        layout.addRow("Processing color:", self.btn_processing_color)
        layout.addRow("", self.lbl_processing_color)

        self.btn_success_color = QPushButton("Choose...")
        self.lbl_success_color = QLabel()
        self.lbl_success_color.setFixedSize(50, 20)
        self.lbl_success_color.setAutoFillBackground(True)
        self.set_color_label(self.lbl_success_color, settings.data.get("color_success", (144,238,144)))
        self.btn_success_color.clicked.connect(lambda: self.choose_color(self.lbl_success_color, "color_success"))
        layout.addRow("Success color:", self.btn_success_color)
        layout.addRow("", self.lbl_success_color)

        self.btn_failure_color = QPushButton("Choose...")
        self.lbl_failure_color = QLabel()
        self.lbl_failure_color.setFixedSize(50, 20)
        self.lbl_failure_color.setAutoFillBackground(True)
        self.set_color_label(self.lbl_failure_color, settings.data.get("color_failure", (255,182,193)))
        self.btn_failure_color.clicked.connect(lambda: self.choose_color(self.lbl_failure_color, "color_failure"))
        layout.addRow("Failure color:", self.btn_failure_color)
        layout.addRow("", self.lbl_failure_color)

        # В методе __init__ после настройки цветов failure:
        self.btn_mismatch_color = QPushButton("Choose...")
        self.lbl_mismatch_color = QLabel()
        self.lbl_mismatch_color.setFixedSize(50, 20)
        self.lbl_mismatch_color.setAutoFillBackground(True)
        self.set_color_label(self.lbl_mismatch_color, settings.data.get("color_mismatch", (255, 165, 0)))
        self.btn_mismatch_color.clicked.connect(lambda: self.choose_color(self.lbl_mismatch_color, "color_mismatch"))
        layout.addRow("Mismatched frame count color:", self.btn_mismatch_color)
        layout.addRow("", self.lbl_mismatch_color)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.setLayout(layout)


    def _apply_forced_path(self):
        if self.forced_path:
            path = self.forced_path
            if not os.path.exists(path):
                self.log_error(f"Provided path does not exist: {path}")
            elif not os.path.isdir(path):
                self.log_error(f"Provided path is not a directory: {path}")
            else:
                self.root_path = path
                self.path_edit.setText(path)
                self.path_edit.setReadOnly(True)
                self.btn_browse.setEnabled(False)
                if not self.headless:
                    self.auto_quit_on_finish = True   # <-- добавить
                QTimer.singleShot(100, self.scan_shots)

    def set_color_label(self, label, color_rgb):
        """Устанавливает фон QLabel в заданный цвет."""
        palette = label.palette()
        palette.setColor(label.backgroundRole(), QColor(*color_rgb))
        label.setPalette(palette)

    def choose_color(self, label, key):
        """Открывает диалог выбора цвета и сохраняет его в settings.data."""
        current = self.settings.data.get(key, (0,0,0))
        color = QColorDialog.getColor(QColor(*current), self)
        if color.isValid():
            rgb = (color.red(), color.green(), color.blue())
            self.settings.data[key] = rgb
            self.set_color_label(label, rgb)


    def browse_file(self, line_edit):
        path, _ = QFileDialog.getOpenFileName(self, "Select file")
        if path:
            line_edit.setText(path)

    def accept(self):
        self.settings.data["path_makeBCFile"] = self.edit_makebc.text()
        self.settings.data["path_tde4"] = self.edit_tde4.text()
        self.settings.data["sensor_width"] = self.spin_sensorw.value()
        self.settings.data["sensor_height"] = self.spin_sensorh.value()
        self.settings.data["focal"] = self.spin_focal.value()
        self.settings.data["bc_quality"] = self.spin_quality.value()
        self.settings.data["bc_black"] = self.spin_black.value()
        self.settings.data["bc_white"] = self.spin_white.value()
        self.settings.data["bc_gamma"] = self.spin_gamma.value()
        self.settings.data["bc_softclip"] = self.spin_softclip.value()
        self.settings.data["import_exr_display_window"] = self.chk_exr_disp.isChecked()
        self.settings.data["import_sxr_right_eye"] = self.chk_sxr.isChecked()
        self.settings.data["start_frame"] = self.spin_start_frame.value()
        self.settings.data["logging_enabled"] = self.chk_logging.isChecked()
        self.settings.data["log_lines"] = self.spin_log_lines.value()
        self.settings.data["font_size"] = self.spin_font_size.value()
        self.settings.data["ui_font_size"] = self.spin_ui_font_size.value()
        self.settings.data["ui_font_bold"] = self.chk_ui_bold.isChecked()
        self.settings.data["log_font_bold"] = self.chk_log_bold.isChecked()
        self.settings.data["camera_sensor_json_path"] = self.edit_camera_json.text()
        self.settings.data["exr_metadata_reader_path"] = self.edit_exr_reader.text()
        self.settings.data["exr_viewer_settings_path"] = self.edit_exr_viewer.text()
        self.settings.data["file_permissions"] = self.edit_file_perm.text()
        self.settings.data["dir_permissions"] = self.edit_dir_perm.text()
        self.settings.data["log_highlight_important"] = self.chk_highlight.isChecked()
        self.settings.data["color_mismatch"] = self.lbl_mismatch_color.palette().color(self.lbl_mismatch_color.backgroundRole()).getRgb()[:3]
        super().accept()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="3DE Shot Processor")
    parser.add_argument("-p", "--path", help="Path to root shots folder or single shot folder")
    parser.add_argument("--nosetup", action="store_true", help="Run in headless mode without GUI (requires --path)")
    args = parser.parse_args()

    app = QApplication(sys.argv)

    forced_path = args.path if args.path else None
    headless = args.nosetup

    if headless and not forced_path:
        print("Ошибка: параметр --nosetup требует указания --path")
        sys.exit(1)

    window = MainWindow(forced_path=forced_path, headless=headless)

    if headless:
        # Безголовый режим: не показываем окно, запускаем обработку
        window.run_headless()
    else:
        # Обычный режим: показываем окно
        window.show()
        sys.exit(app.exec_())