"""Предпросмотр и печать схемы на A4 через Qt PrintSupport."""
from math import ceil

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewWidget, QPrintDialog
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QVBoxLayout)


def make_printer(output_path=None):
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    # Configure a PDF device before setting page geometry: a machine can have
    # no default physical printer, in which case the native device is invalid.
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    if output_path is not None:
        printer.setOutputFileName(str(output_path))
    printer.setResolution(96)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageOrientation(QPageLayout.Orientation.Landscape)
    printer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
    return printer


def visible_bounds(scene):
    """The editor removes filtered items from the scene before printing."""
    bounds = scene.itemsBoundingRect()
    return bounds.adjusted(-16, -16, 16, 16) if not bounds.isNull() else QRectF()


def page_geometry(scene, printer, tiled):
    bounds = visible_bounds(scene)
    page = QRectF(printer.pageRect(QPrinter.Unit.DevicePixel))
    if bounds.isEmpty() or page.isEmpty():
        return bounds, page, 0, 0, 1.0
    if tiled:
        return bounds, page, max(1, ceil(bounds.width() / page.width())), max(1, ceil(bounds.height() / page.height())), 1.0
    scale = min(page.width() / bounds.width(), page.height() / bounds.height())
    return bounds, page, 1, 1, scale


def prefer_multiple_pages(scene, printer):
    """Suggest readable pages when fitting the diagram would shrink it too far."""
    _, _, _, _, scale = page_geometry(scene, printer, False)
    _, _, cols, rows, _ = page_geometry(scene, printer, True)
    return scale < .55 and 1 < cols * rows <= 100


def render_pages(scene, printer, tiled=False):
    bounds, page, cols, rows, scale = page_geometry(scene, printer, tiled)
    if not cols or not rows:
        raise ValueError('На схеме нет видимых элементов для печати.')
    if cols * rows > 100:
        raise ValueError('Схема занимает более 100 страниц. Уменьшите область схемы или выберите один лист.')
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError('Не удалось открыть устройство печати.')
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        for row in range(rows):
            for col in range(cols):
                if row or col:
                    if not printer.newPage():
                        raise RuntimeError('Не удалось создать страницу.')
                if tiled:
                    source = QRectF(bounds.left() + col * page.width(), bounds.top() + row * page.height(),
                                    min(page.width(), bounds.width() - col * page.width()),
                                    min(page.height(), bounds.height() - row * page.height()))
                    target = QRectF(0, 0, source.width(), source.height())
                else:
                    source = bounds
                    width, height = bounds.width() * scale, bounds.height() * scale
                    target = QRectF((page.width() - width) / 2, (page.height() - height) / 2, width, height)
                scene.render(painter, target, source, Qt.AspectRatioMode.KeepAspectRatio)
    finally:
        painter.end()


def export_pdf(scene, path, tiled=False):
    printer = make_printer(path)
    render_pages(scene, printer, tiled)


def show_preview(scene, parent=None):
    if visible_bounds(scene).isEmpty():
        QMessageBox.information(parent, 'Печать', 'На схеме нет видимых элементов для печати.')
        return
    dialog = QDialog(parent)
    dialog.setWindowTitle('Предпросмотр A4')
    dialog.resize(1000, 760)
    layout = QVBoxLayout(dialog)
    options = QHBoxLayout()
    options.addWidget(QLabel('Размещение:'))
    mode = QComboBox()
    mode.addItems(['Вся схема на одном листе', 'Несколько листов в читаемом масштабе'])
    options.addWidget(mode)
    status = QLabel()
    options.addWidget(status, 1)
    layout.addLayout(options)
    printer = make_printer()
    if prefer_multiple_pages(scene, printer):
        mode.setCurrentIndex(1)
    preview = QPrintPreviewWidget(printer)
    layout.addWidget(preview, 1)
    buttons = QHBoxLayout()
    save_button = QPushButton('Сохранить PDF…')
    print_button = QPushButton('Печать…')
    close_button = QPushButton('Закрыть')
    buttons.addStretch(1)
    buttons.addWidget(save_button)
    buttons.addWidget(print_button)
    buttons.addWidget(close_button)
    layout.addLayout(buttons)

    def refresh():
        _, _, cols, rows, scale = page_geometry(scene, printer, mode.currentIndex() == 1)
        status.setText(f'Листов: {cols * rows}' + (' — текст может быть мелким' if scale < .55 else ''))
        preview.updatePreview()

    def render(target):
        try:
            render_pages(scene, target, mode.currentIndex() == 1)
        except (ValueError, RuntimeError) as exc:
            status.setText(str(exc))

    def save():
        path, _ = QFileDialog.getSaveFileName(dialog, 'Сохранить PDF', 'Схема потока.pdf', 'PDF (*.pdf)')
        if not path:
            return
        if not path.lower().endswith('.pdf'):
            path += '.pdf'
        try:
            export_pdf(scene, path, mode.currentIndex() == 1)
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(dialog, 'Ошибка печати', str(exc))
            return
        QMessageBox.information(dialog, 'PDF сохранён', path)

    def do_print():
        print_dialog = QPrintDialog(printer, dialog)
        if print_dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                render_pages(scene, printer, mode.currentIndex() == 1)
            except (ValueError, RuntimeError) as exc:
                QMessageBox.warning(dialog, 'Ошибка печати', str(exc))

    preview.paintRequested.connect(render)
    mode.currentIndexChanged.connect(refresh)
    save_button.clicked.connect(save)
    print_button.clicked.connect(do_print)
    close_button.clicked.connect(dialog.accept)
    refresh()
    dialog.exec()
