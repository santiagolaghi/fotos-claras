"""Responsive folder selection with an editable path and visible validation errors."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QStandardPaths
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QDialogButtonBox, QFileDialog,
)


def validate_directory(raw, cancel=None):
    """Read-only validation for a worker; never scan/index on selection."""
    cancel = cancel or threading.Event()
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    if not value:
        raise ValueError('Elegí una carpeta o pegá su ruta.')
    if cancel.is_set():
        raise InterruptedError('Selección cancelada.')
    try:
        path = Path(os.path.expandvars(value)).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError('Esa ruta corresponde a un archivo. Elegí la carpeta que contiene tus fotos.')
        with os.scandir(path) as entries:
            next(entries, None)  # Verify read access; do not enumerate a large folder.
    except FileNotFoundError as exc:
        raise ValueError('No encontramos esa carpeta. Revisá la ruta y que el disco esté conectado.') from exc
    except PermissionError as exc:
        raise ValueError('No hay permiso para leer esa carpeta. Elegí otra o revisá sus permisos en Windows.') from exc
    except OSError as exc:
        raise ValueError(f'No se pudo abrir la carpeta: {exc}') from exc
    if cancel.is_set():
        raise InterruptedError('Selección cancelada.')
    return str(path)


class FolderPicker(QDialog):
    """No native shell dialog or nested exec loop is required to choose a path."""
    submitted = Signal(str)

    def __init__(self, parent=None, initial='', recent=()):
        super().__init__(parent)
        self.setObjectName('folderPicker')
        self.setWindowTitle('Elegir carpeta · Fotos Claras')
        self.setWindowModality(Qt.WindowModal)
        self.resize(640, 310)
        self._browser = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(14)
        title = QLabel('¿Dónde guardás tus fotos?')
        title.setObjectName('title')
        layout.addWidget(title)
        hint = QLabel('Elegí la carpeta principal. Se incluirán sus subcarpetas cuando inicies el análisis.')
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.path_edit = QLineEdit(initial)
        self.path_edit.setObjectName('folderPath')
        self.path_edit.setAccessibleName('Ruta de la carpeta de fotografías')
        self.path_edit.setPlaceholderText('Pegá la ruta de una carpeta o tocá Examinar…')
        self.path_edit.setClearButtonEnabled(True)
        row = QHBoxLayout()
        row.addWidget(self.path_edit, 1)
        self.browse_button = QPushButton('Examinar…')
        self.browse_button.setObjectName('browseFolder')
        self.browse_button.clicked.connect(self.browse)
        row.addWidget(self.browse_button)
        layout.addLayout(row)
        self.recent = QComboBox()
        self.recent.addItem('O elegir una carpeta reciente…', '')
        for path in dict.fromkeys(recent):
            self.recent.addItem(path, path)
        self.recent.activated.connect(self.use_recent)
        self.recent.setVisible(self.recent.count() > 1)
        layout.addWidget(self.recent)
        self.feedback = QLabel('La selección no inicia un análisis ni modifica tus fotos.')
        self.feedback.setObjectName('folderFeedback')
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.PlainText)
        layout.addWidget(self.feedback)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        self.submit_button = self.buttons.addButton('Usar esta carpeta', QDialogButtonBox.AcceptRole)
        self.submit_button.setObjectName('primary')
        self.submit_button.setDefault(True)
        self.buttons.accepted.connect(self.submit)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.path_edit.returnPressed.connect(self.submit)

    def use_recent(self, index):
        if self.recent.itemData(index):
            self.path_edit.setText(self.recent.itemData(index))

    def submit(self):
        if not self.submit_button.isEnabled():
            return
        if not self.path_edit.text().strip():
            self.show_error('Elegí una carpeta o pegá su ruta.')
            return
        self.set_busy(True)
        self.submitted.emit(self.path_edit.text())

    def set_busy(self, busy):
        self.path_edit.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)
        self.recent.setEnabled(not busy)
        self.submit_button.setEnabled(not busy)
        if busy:
            self.feedback.setStyleSheet('')
            self.feedback.setText('Comprobando que la carpeta se puede abrir…')

    def show_error(self, message):
        self.set_busy(False)
        self.feedback.setStyleSheet('color:#9b3d29;')
        self.feedback.setText(str(message))
        self.path_edit.setFocus()

    def browse(self):
        if self._browser is not None:
            self._browser.raise_()
            self._browser.activateWindow()
            return
        browser = QFileDialog(self, 'Elegí la carpeta de tus fotografías')
        # Set before all other options. Avoid native Windows COM/shell dialogs.
        browser.setOption(QFileDialog.DontUseNativeDialog, True)
        browser.setOption(QFileDialog.DontUseCustomDirectoryIcons, True)
        browser.setFileMode(QFileDialog.Directory)
        browser.setOption(QFileDialog.ShowDirsOnly, False)
        browser.setAcceptMode(QFileDialog.AcceptOpen)
        browser.setLabelText(QFileDialog.Accept, 'Usar carpeta')
        browser.setLabelText(QFileDialog.Reject, 'Cancelar')
        browser.setLabelText(QFileDialog.FileName, 'Carpeta:')
        start = self.path_edit.text().strip().strip('"')
        browser.setDirectory(start or QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home()))
        self._browser = browser
        browser.finished.connect(self.browser_finished)
        browser.open()  # Keep the event loop and timers running.

    def browser_finished(self, result):
        browser = self._browser
        if browser is None:
            return
        paths = browser.selectedFiles() if result == QDialog.Accepted else []
        self._browser = None
        browser.deleteLater()
        if paths:
            self.path_edit.setText(paths[0])
            self.submit()

    def close_browser(self):
        if self._browser is not None:
            browser = self._browser
            self._browser = None
            browser.reject()
            browser.deleteLater()

    def done(self, result):
        self.close_browser()
        super().done(result)
