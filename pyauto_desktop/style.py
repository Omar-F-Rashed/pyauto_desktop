
DARK_THEME = """QMainWindow {
    background-color: #2b2b2b;
    color: #ffffff;
}
QWidget {
    font-family: 'Segoe UI', sans-serif;
    font-size: 14px;
}
QGroupBox {
    border: 1px solid #555;
    border-radius: 5px;
    margin-top: 1.5em;
    font-weight: bold;
    color: #ddd;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}
QLabel {
    color: #e0e0e0;
}
QPushButton {
    background-color: #0d6efd;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #0b5ed7;
}
QPushButton:pressed {
    background-color: #0a58ca;
}
QPushButton:disabled {
    background-color: #444;
    color: #888;
}
/* Specific Button Styles */
QPushButton#stop_btn {
    background-color: #dc3545;
}
QPushButton#stop_btn:hover {
    background-color: #bb2d3b;
}
QPushButton#secondary_btn {
    background-color: #6c757d;
}
QPushButton#secondary_btn:hover {
    background-color: #5c636a;
}
/* Sliders */
QSlider::groove:horizontal {
    border: 1px solid #555;
    height: 8px;
    background: #444;
    margin: 2px 0;
    border-radius: 4px;
}

QSlider::handle:horizontal {
    background: #0d6efd;
    border: 1px solid #0d6efd;
    width: 18px;
    height: 18px;
    margin: -7px 0;
    border-radius: 9px;
}
/* Inputs */
QTextEdit {
    background-color: #1e1e1e;
    color: #00ff00;
    font-family: Consolas, monospace;
    border: 1px solid #444;
    border-radius: 4px;
}
"""