import sys
import exifread
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QTextEdit, QFileDialog, 
                             QLabel, QMessageBox)
from PyQt6.QtCore import Qt

class MetadataViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle('Просмотр метаданных EXIF')
        self.setGeometry(300, 300, 600, 500)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout()
        central_widget.setLayout(layout)
        
        # Кнопка выбора файла
        self.btn_open = QPushButton('Выбрать файл')
        self.btn_open.clicked.connect(self.open_file)
        layout.addWidget(self.btn_open)
        
        # Поле для вывода метаданных
        self.text_output = QTextEdit()
        self.text_output.setReadOnly(True)
        layout.addWidget(self.text_output)

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            'Выберите изображение',
            '',
            'Images (*.png *.jpg *.jpeg *.tiff *.bmp *.arw *.*)'
        )
        
        if file_path:
            self.show_metadata(file_path)
            
    def show_metadata(self, file_path):
        try:
            with open(file_path, 'rb') as f:
                tags = exifread.process_file(f, details=False)
                
            if not tags:
                self.text_output.setText('Метаданные не найдены')
                return
                
            metadata_str = ""
            for tag, value in tags.items():
                if tag not in ('JPEGThumbnail', 'TIFFThumbnail', 'Filename', 'EXIF MakerNote'):
                    metadata_str += f"{tag:25} : {value}\n"
                    
            self.text_output.setText(metadata_str)
            
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка', f'Не удалось прочитать файл: {str(e)}')

if __name__ == '__main__':
    app = QApplication(sys.argv)
    viewer = MetadataViewer()
    viewer.show()
    sys.exit(app.exec())