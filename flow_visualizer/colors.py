"""Palette for the compact presentation view of the flow diagram."""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor


COMPACT_RKT_COLOR = '#c6a0de'
DEFICIT_COLOR = '#e5484d'


def type_key(provider):
    value = (provider or '').casefold()
    if 'покуп' in value:
        return 'purchase'
    if 'сбор' in value or 'разбор' in value:
        return 'assembly'
    if 'производ' in value:
        return 'production'
    if 'логист' in value:
        return 'logistics'
    if 'услуг' in value:
        return 'services'
    return 'other'

DEFAULT_COLORS = {'purchase': '#ffff00', 'production': '#00aeef', 'logistics': '#c4dfb4',
                  'services': '#d8d8d8', 'assembly': '#74d3ca', 'other': '#e9edef',
                  'rkt': COMPACT_RKT_COLOR, 'assembly_rkt': '#e5a7c4'}


def supports_deficit_color(provider):
    return type_key(provider) in ('production', 'assembly')


def paint_stage_fill(painter, rect, color, deficit=False):
    stripe = QRectF()
    if deficit:
        stripe = QRectF(rect.left(), rect.top(), rect.width() / 4, rect.height())
        main = QRectF(rect)
        main.setLeft(stripe.right())
        painter.fillRect(main, color)
        painter.fillRect(stripe, QColor(DEFICIT_COLOR))
    else:
        painter.fillRect(rect, color)
    return stripe

def compact_color_for_type(provider, palette=None):
    key = type_key(provider)
    return QColor((palette or {}).get(key, DEFAULT_COLORS[key]))

def compact_color_for_stage(stage, palette=None):
    kind = type_key(stage.provider_type)
    if stage.rkt_algorithm and kind in ('production', 'assembly'):
        key = 'assembly_rkt' if kind == 'assembly' else 'rkt'
        return QColor((palette or {}).get(key, DEFAULT_COLORS[key]))
    return compact_color_for_type(stage.provider_type, palette)
