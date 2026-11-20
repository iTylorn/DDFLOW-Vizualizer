"""Generate a synthetic XLSX for a quick demonstration, never 1C data."""
from pathlib import Path
from openpyxl import Workbook
try:
    from .model import COLUMNS
except ImportError:
    from model import COLUMNS


def make_demo(path):
    book = Workbook()
    sheet = book.active
    sheet.title = 'Данные'
    sheet.append(COLUMNS)
    def row(**values):
        sheet.append([values.get(key, '') for key in COLUMNS])
    for ident, label in [('Производство', 'Производство'), ('Покупка', 'Покупка'),
                         ('Промуслуги', 'Промуслуги'), ('Логистика', 'Логистика'),
                         ('СборкаРазборка', 'Сборка / Разборка')]:
        row(kind='provider_option', id=ident, name=label)
    row(kind='rkt_option', id='ГрафикВыпускаПоНоменклатурам', name='График выпуска по номенклатурам')
    row(kind='group', id='demo-division-1', name='Механический цех', code='000000001',
        extra_json='{"parent_id": "", "status": "Действует"}')
    row(kind='warehouse', id='demo-wh-1', name='Входной стеллаж — материалы', code='001',
        extra_json='{"workshop_storage": false}')
    row(kind='warehouse', id='demo-wh-2', name='Кладовая деталей в работе', code='002',
        extra_json='{"workshop_storage": true}')
    row(kind='stage', id='demo-stage-1', name='Закупка материалов', provider_type='Покупка', level=1)
    row(kind='stage', id='demo-stage-2', name='Термическая резка и подготовка деталей', provider_type='Производство', level=2,
        rkt_algorithm='График выпуска по номенклатурам')
    row(kind='stage', id='demo-stage-3', name='Сборка узлов', provider_type='Сборка / Разборка', level=3)
    row(kind='inlet', owner_id='demo-stage-2', warehouse_id='demo-wh-1', primary=1)
    row(kind='stock', owner_id='demo-stage-2', warehouse_id='demo-wh-2', primary=1)
    book.save(path)


if __name__ == '__main__':
    make_demo(Path(__file__).parent / 'Демо_не_данные_1С.xlsx')
