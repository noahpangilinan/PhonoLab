import sys
import numpy as np
from PyQt6.QtWidgets import (QMainWindow, QApplication, QWidget, QVBoxLayout,
                             QFileDialog, QMenuBar, QMenu, QStackedWidget,
                             QPushButton, QLabel)
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtCore import Qt
import pyqtgraph as pg


# Assuming your imports are structured this way
from src.phonolab.dsp.audio_loader import AudioLoader

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PhonoLab - Advanced Acoustic Analysis")
        self.resize(1100, 700)

        self.loader = AudioLoader() # Uncomment when your loader is ready
        self.show_waveform = True

        # The StackedWidget is the "page manager"
        self.central_stack = QStackedWidget()
        self.setCentralWidget(self.central_stack)

        self.init_start_menu()
        self.init_analysis_ui()
        self.create_menus()

        # Start on the Start Menu (index 0)
        self.central_stack.setCurrentIndex(0)

    def init_start_menu(self):
        """Creates the landing page with centered text and buttons."""
        start_page = QWidget()
        layout = QVBoxLayout(start_page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Title
        title = QLabel("PhonoLab")
        title_font = QFont("Helvetica", 48, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet("color: #2c3e50;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Subtitle
        subtitle = QLabel("Open a file to begin acoustic analysis")
        subtitle.setStyleSheet("color: #7f8c8d; margin-bottom: 20px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Start Button
        self.start_btn = QPushButton("Go to Analysis View")
        self.start_btn.setFixedSize(200, 50)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border-radius: 5px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.start_btn.clicked.connect(lambda: self.central_stack.setCurrentIndex(1))

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.start_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.central_stack.addWidget(start_page)

    def init_analysis_ui(self):
        """The main analysis page with the waveform plot."""
        analysis_page = QWidget()
        layout = QVBoxLayout(analysis_page)



        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.waveform_item = self.plot_widget.plot(pen=pg.mkPen(color='#2c3e50', width=1))

        # Back to Menu Button (optional but helpful)
        back_btn = QPushButton("← Back to Menu")
        back_btn.setFixedWidth(120)
        back_btn.clicked.connect(lambda: self.central_stack.setCurrentIndex(0))

        layout.addWidget(back_btn)
        layout.addWidget(self.plot_widget)

        self.central_stack.addWidget(analysis_page)

    def create_menus(self):
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("&File")

        home_action = QAction("Home Menu", self)
        home_action.triggered.connect(lambda: self.central_stack.setCurrentIndex(0))
        file_menu.addAction(home_action)

        open_action = QAction("Open Audio...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.handle_load)
        file_menu.addAction(open_action)

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View Menu
        view_menu = menubar.addMenu("&View")
        self.wave_action = QAction("Show Waveform", self, checkable=True)
        self.wave_action.setChecked(True)
        self.wave_action.triggered.connect(self.toggle_waveform)
        view_menu.addAction(self.wave_action)

    def toggle_waveform(self, state):
        self.show_waveform = state
        if self.central_stack.currentIndex() == 1:
            self.plot_widget.setVisible(state)

    def handle_load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Audio", "", "Audio (*.wav *.mp3 *.flac)")
        if path:
            signal, sr = self.loader.load_file(path, target_sr=None)
            self.central_stack.setCurrentIndex(1)
            self.update_plot(signal, sr)

    def update_plot(self, signal, sr):
        time_axis = np.linspace(0, len(signal) / sr, num=len(signal))
        self.waveform_item.setData(time_axis, signal)
        self.plot_widget.setLabel('bottom', "Time", units='s')
        self.plot_widget.setLabel('left', "Amplitude")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())