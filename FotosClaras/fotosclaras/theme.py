from PySide6.QtCore import QByteArray,Qt
from PySide6.QtGui import QIcon,QPixmap,QPainter
from PySide6.QtSvg import QSvgRenderer

STYLE='''
QWidget { background:#faf7f1; color:#292c24; font-family:"Segoe UI"; font-size:13px; }
QLabel { background:transparent; }
QMainWindow, QDialog { background:#faf7f1; }
QFrame#sidebar { background:#f1eee6; border-right:1px solid #e6e1d8; }
QLabel#brand { font-family:Georgia; font-size:20px; padding:14px 6px; }
QLabel#eyebrow { color:#7d806e; font-size:10px; letter-spacing:2px; }
QLabel#title { font-family:Georgia; font-size:34px; }
QLabel#hero { font-family:Georgia; font-size:42px; }
QLabel#heroAccent { font-family:Georgia; font-size:46px; font-style:italic; color:#657047; }
QLabel#muted { color:#77796e; }
QLabel#metric { font-family:Georgia; font-size:30px; }
QFrame#card { background:#fffdf9; border:1px solid #e8e2d7; border-radius:14px; }
QFrame#card QLabel { background:transparent; }
QPushButton { background:#f6f3eb; border:1px solid #dedfd2; border-radius:8px; padding:9px 14px; min-height:18px; }
QPushButton:hover { background:#ebeede; border-color:#a6ad8c; }
QPushButton:pressed { background:#dfe4cf; }
QPushButton:disabled { color:#a5a69b; border-color:#e8e5df; }
QPushButton#primary { background:#647047; color:#fffdf8; border:1px solid #647047; }
QPushButton#primary:hover { background:#515c39; }
QPushButton#nav { text-align:left; border:0; background:transparent; padding:12px 16px; }
QPushButton#nav:checked { background:#e1e5d3; color:#3d4829; border-left:3px solid #647047; border-radius:5px; }
QPushButton#nav:hover { background:#e8ebdd; }
QLineEdit, QComboBox, QListWidget, QTableWidget, QTableView { background:#fffdf9; border:1px solid #e2ded4; border-radius:7px; padding:5px; }
QLineEdit { padding:9px; }
QListView { background:transparent; border:0; outline:0; }
QListWidget::item { padding:8px; }
QListWidget::item:selected { background:#e1e5d3; color:#2b3320; }
QComboBox { padding:8px; min-width:110px; min-height:20px; }
QComboBox::drop-down { border:0; width:22px; }
QScrollBar:vertical { background:transparent; width:9px; margin:2px; }
QScrollBar::handle:vertical { background:#c9cbbd; border-radius:3px; min-height:30px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical { background:transparent; }
QProgressBar { background:#e7e5dd; border:0; border-radius:4px; height:7px; max-height:7px; }
QProgressBar::chunk { background:#899566; border-radius:4px; }
QHeaderView::section { background:#f1eee6; border:0; padding:9px; }
QSplitter::handle { background:#e4e1d8; }
QCheckBox { spacing:8px; }
QTabWidget::pane { border:1px solid #e2ded4; border-radius:8px; }
QTabBar::tab { background:#eeeae1; padding:10px 18px; border-radius:5px; margin:3px; }
QTabBar::tab:selected { background:#e1e5d3; color:#3d4829; }
QToolTip { background:#fffdf9; border:1px solid #c9cbbd; padding:5px; }
'''
PATHS={
 'home':'M3 10L12 3l9 7v11h-6v-7H9v7H3z',
 'gallery':'M3 4h18v16H3z M3 16l6-6 5 5 3-3 4 4 M16 8h.01',
 'people':'M15 21v-2a5 5 0 0 0-10 0v2 M10 3a4 4 0 1 0 0 8a4 4 0 1 0 0-8 M17 12a5 5 0 0 1 5 5v4 M18 3a4 4 0 0 1 0 8',
 'copy':'M8 8h13v13H8z M3 16V3h13',
 'versions':'M4 6h16v14H4z M8 2h12 M2 10h2 M8 13l3 3 5-6',
 'album':'M3 6h7l2 2h9v13H3z',
 'none':'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18 M6 18L18 6',
 'settings':'M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2',
}
def icon(name):
    path=PATHS.get(name,PATHS['gallery'])
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path d="{path}" fill="none" stroke="#53623c" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>'
    pix=QPixmap(48,48);pix.fill(Qt.transparent);p=QPainter(pix);QSvgRenderer(QByteArray(svg.encode())).render(p);p.end()
    return QIcon(pix)
