import sys
import json
import subprocess
import shutil
from pathlib import Path
from collections import OrderedDict

from PyQt5 import QtWidgets, QtCore, QtGui

# Optional import for pymediainfo
try:
    from pymediainfo import MediaInfo
    HAS_PYMEDIAINFO = True
except Exception:
    HAS_PYMEDIAINFO = False


def flatten(obj, parent_key="", sep="/"):
    """
    Преобразует вложенные dict/list в плоские key/value пары.
    Ключи формируются как parent/child/...; списки индексируются [0],[1],...
    """
    items = OrderedDict()
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else str(k)
            items.update(flatten(v, new_key, sep=sep))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            new_key = f"{parent_key}{sep}[{i}]"
            items.update(flatten(v, new_key, sep=sep))
    else:
        # Примитив
        items[parent_key] = obj
    return items


def ffprobe_parse(path: str):
    """Выполняет ffprobe и возвращает распарсенный JSON."""
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe не найден в PATH. Установи ffmpeg или выбери pymediainfo.")
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe error: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def pymediainfo_parse(path: str):
    """Использует pymediainfo и возвращает dict с данными."""
    if not HAS_PYMEDIAINFO:
        raise RuntimeError("pymediainfo не установлен. Установи pymediainfo или выбери ffprobe.")
    mi = MediaInfo.parse(path)
    result = {"tracks": []}
    for t in mi.tracks:
        # у track есть метод to_data() возвращающий dict в новых версиях
        try:
            data = t.to_data()
        except Exception:
            # fallback: собираем атрибуты
            data = {}
            for attr in dir(t):
                if attr.startswith("_"):
                    continue
                try:
                    val = getattr(t, attr)
                    # отфильтруем callables и Qt-специфику
                    if callable(val) or isinstance(val, (type, QtWidgets.QWidget)):
                        continue
                    # простые типы
                    if isinstance(val, (str, int, float, bool, type(None))):
                        data[attr] = val
                except Exception:
                    continue
        result["tracks"].append(data)
    # также добавим базовую "format" информацию если есть
    try:
        fmt = mi.to_data().get("tracks", [])
        # merge format-like tracks if present
        result["format_tracks"] = fmt
    except Exception:
        pass
    return result


def parse_arri_json(path: str):
    """Парсит ARRI JSON sidecar и собирает metadataSets в словарь."""
    with open(path, "r", encoding="utf-8") as f:
        j = json.load(f)
    combined = {}
    # ожидаемый ключ "metadataSets"
    sets = j.get("metadataSets", [])
    if not sets:
        # иногда структура иной формы: ищем объекты с metadataSetName
        for v in j.values() if isinstance(j, dict) else []:
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict) and "metadataSetName" in item:
                        sets.append(item)
    for m in sets:
        name = m.get("metadataSetName", "Unknown")
        metadata = m.get("metadata", {})
        combined[name] = metadata
    return combined


class ParseWorker(QtCore.QThread):
    finished_parsing = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)

    def __init__(self, file_path: str, method: str):
        super().__init__()
        self.file_path = file_path
        self.method = method  # 'ffprobe' | 'pymediainfo' | 'json'

    def run(self):
        try:
            if self.method == "ffprobe":
                data = ffprobe_parse(self.file_path)
                flat = flatten(data)
            elif self.method == "pymediainfo":
                data = pymediainfo_parse(self.file_path)
                flat = flatten(data)
            elif self.method == "json":
                data = parse_arri_json(self.file_path)
                flat = flatten(data)
            else:
                raise RuntimeError("Неподдерживаемый метод парсинга.")
            # Emit both raw structured data and flattened for UI
            self.finished_parsing.emit({"raw": data, "flat": flat})
        except Exception as e:
            self.error.emit(str(e))


class MetadataViewer(QtWidgets.QWidget):
    CAMERA_KEYWORDS = [
        "camera", "lens", "iso", "exposure", "shutter", "white", "wb", "look",
        "sensor", "gain", "aperture", "fstop", "f-stop", "focus", "focal", "project",
        "scene", "take"
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Universal ARRI Metadata Viewer")
        self.resize(1000, 700)
        self._build_ui()
        self.current_data = None  # will hold {"raw":..., "flat": OrderedDict(...)}

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # top controls
        controls = QtWidgets.QHBoxLayout()
        self.file_edit = QtWidgets.QLineEdit()
        self.file_edit.setPlaceholderText("Выберите MXF/JSON файл или введите путь...")
        btn_browse = QtWidgets.QPushButton("Открыть файл...")
        btn_browse.clicked.connect(self.browse_file)

        self.method_combo = QtWidgets.QComboBox()
        self.method_combo.addItems(["ffprobe", "pymediainfo", "json"])
        # disable pymediainfo option if not installed
        if not HAS_PYMEDIAINFO:
            idx = self.method_combo.findText("pymediainfo")
            if idx >= 0:
                self.method_combo.model().item(idx).setEnabled(False)
                self.method_combo.setToolTip("pymediainfo not installed")

        btn_parse = QtWidgets.QPushButton("Парсить")
        btn_parse.clicked.connect(self.parse_file)

        controls.addWidget(self.file_edit)
        controls.addWidget(btn_browse)
        controls.addWidget(self.method_combo)
        controls.addWidget(btn_parse)
        layout.addLayout(controls)

        # filter and save
        options = QtWidgets.QHBoxLayout()
        self.filter_checkbox = QtWidgets.QCheckBox("Показывать только камерные параметры")
        self.filter_checkbox.setChecked(False)
        self.filter_checkbox.stateChanged.connect(self.update_table_filter)

        self.save_button = QtWidgets.QPushButton("Сохранить JSON")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_json)

        options.addWidget(self.filter_checkbox)
        options.addStretch(1)
        options.addWidget(self.save_button)
        layout.addLayout(options)

        # table view (Key / Value)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Key", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        layout.addWidget(self.table, 60)

        # json preview below
        self.json_preview = QtWidgets.QTextEdit()
        self.json_preview.setReadOnly(True)
        self.json_preview.setPlaceholderText("JSON preview will appear here after save...")
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.json_preview.setFont(font)
        layout.addWidget(QtWidgets.QLabel("Preview of saved JSON:"), 0)
        layout.addWidget(self.json_preview, 40)

        # status bar
        self.status = QtWidgets.QLabel("")
        layout.addWidget(self.status)

    def browse_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Выберите MXF / JSON файл", "", "MXF files (*.mxf);;JSON files (*.json);;All files (*)"
        )
        if path:
            self.file_edit.setText(path)
            # optionally auto-select method based on extension
            if path.lower().endswith(".json"):
                self.method_combo.setCurrentText("json")
            elif path.lower().endswith(".mxf"):
                # prefer ffprobe if available
                if shutil.which("ffprobe"):
                    self.method_combo.setCurrentText("ffprobe")
                elif HAS_PYMEDIAINFO:
                    self.method_combo.setCurrentText("pymediainfo")

    def parse_file(self):
        path = self.file_edit.text().strip()
        if not path:
            QtWidgets.QMessageBox.warning(self, "No file", "Укажи путь к файлу.")
            return
        method = self.method_combo.currentText()
        # start worker
        self.status.setText("Parsing...")
        self.table.setRowCount(0)
        self.json_preview.clear()
        self.save_button.setEnabled(False)
        self.current_data = None

        self.worker = ParseWorker(path, method)
        self.worker.finished_parsing.connect(self.on_parsed)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_parsed(self, result):
        # result: {"raw":..., "flat": OrderedDict(...) }
        self.current_data = result
        self.populate_table(result["flat"])
        self.save_button.setEnabled(True)
        self.status.setText("Parsed successfully.")

    def on_error(self, message):
        QtWidgets.QMessageBox.critical(self, "Parse error", str(message))
        self.status.setText("Error during parsing.")
        self.save_button.setEnabled(False)

    def populate_table(self, flat_dict):
        # flat_dict is OrderedDict-like mapping key->value
        self.table.setRowCount(0)
        items = list(flat_dict.items())
        self.table.setRowCount(len(items))
        for i, (k, v) in enumerate(items):
            key_item = QtWidgets.QTableWidgetItem(str(k))
            val = v
            # convert large structures to compact JSON
            if isinstance(v, (dict, list)):
                val = json.dumps(v, ensure_ascii=False)
            val_item = QtWidgets.QTableWidgetItem(str(val))
            self.table.setItem(i, 0, key_item)
            self.table.setItem(i, 1, val_item)
        self.update_table_filter()
        self.table.resizeColumnsToContents()

    def update_table_filter(self):
        if self.current_data is None:
            return
        show_only_camera = self.filter_checkbox.isChecked()
        if not show_only_camera:
            # show all rows
            for r in range(self.table.rowCount()):
                self.table.setRowHidden(r, False)
            return
        # otherwise hide rows not matching keywords
        keywords = [k.lower() for k in self.CAMERA_KEYWORDS]
        for r in range(self.table.rowCount()):
            key_item = self.table.item(r, 0)
            v = key_item.text().lower() if key_item else ""
            match = any(kw in v for kw in keywords)
            self.table.setRowHidden(r, not match)

    def save_json(self):
        # Save the raw structured data into a single JSON summary
        if self.current_data is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Сохранить JSON", "metadata_summary.json", "JSON files (*.json)")
        if not path:
            return
        # choose what to save: raw (structured) is better
        to_save = self.current_data.get("raw", self.current_data.get("flat"))
        # If flat (OrderedDict), convert to normal dict
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(to_save, f, indent=2, ensure_ascii=False)
            self.status.setText(f"Saved to {path}")
            # show preview
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.json_preview.setPlainText(content)
            QtWidgets.QMessageBox.information(self, "Saved", f"Файл сохранён:\n{path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save error", str(e))


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MetadataViewer()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
