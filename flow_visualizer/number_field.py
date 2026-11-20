"""Numeric editor with independent mouse targets for both step directions."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractSpinBox, QHBoxLayout, QPushButton, QSpinBox, QWidget


def number_field(name, value, minimum, maximum):
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    field = QSpinBox()
    field.setObjectName(name)
    field.setRange(minimum, maximum)
    field.setValue(value)
    field.setButtonSymbols(QAbstractSpinBox.NoButtons)
    row.addWidget(field, 1)

    for suffix, symbol, label, step in (
        ('down', '−', 'Уменьшить', field.stepDown),
        ('up', '+', 'Увеличить', field.stepUp),
    ):
        button = QPushButton(symbol)
        button.setObjectName(f'{name}_{suffix}')
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.setAutoDefault(False)
        button.setFocusPolicy(Qt.NoFocus)
        button.clicked.connect(step)
        row.addWidget(button)
    return field, container
