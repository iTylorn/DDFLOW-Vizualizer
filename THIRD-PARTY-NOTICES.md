# Сторонние компоненты Windows-сборки

FlowVizualizer использует библиотеки **Qt 6.11.2, PySide6 6.11.2 и Shiboken6 6.11.2 по GNU LGPL версии 3**. Полные тексты LGPLv3 и GPLv3 приложены в каталоге `third_party`. Условия MIT относятся к оригинальным исходникам FlowVizualizer.

## Соответствующие исходники Qt и Qt for Python

- [Qt 6.11.2, исходный архив](https://download.qt.io/archive/qt/6.11/6.11.2/single/qt-everywhere-src-6.11.2.tar.xz). В Windows-сборку входят библиотеки Qt Base и плагины Qt SVG и Qt Image Formats.
- [PySide6 и Shiboken6 6.11.2, исходный архив](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/pyside-setup-everywhere-src-6.11.2.tar.xz). [Инструкция Qt по сборке](https://doc.qt.io/qtforpython-6/building_from_source/index.html).
- [Сторонний код Qt 6.11](https://doc.qt.io/qt-6.11/licenses-used-in-qt.html) и [лицензии стороннего кода Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html). Сведения для поставленных библиотек сохранены также в `third_party`.

Перечисленные библиотеки взяты из колёс PyPI без изменений исходного кода. EXE загружает их динамически. Чтобы использовать изменённую совместимую сборку, распакуйте копию архива и замените соответствующие DLL, модули Python и плагины в папках `_internal/PySide6` и `_internal/shiboken6`, сохранив имена и структуру каталогов. Версии Python, архитектура и интерфейсы библиотек должны совпадать. Условия LGPL разрешают модифицировать библиотеки и исследовать работу приложения для отладки этих модификаций.

## Остальные компоненты

Тексты лицензий см. в `third_party`.

| Компонент | Версия | Лицензия или ссылка |
|---|---|---|
| CPython | 3.10.11 | [PSF License и уведомления CPython](https://github.com/python/cpython/blob/v3.10.11/LICENSE) |
| OpenSSL | 1.1.1t | [OpenSSL и SSLeay](https://github.com/openssl/openssl/blob/OpenSSL_1_1_1t/LICENSE). This product includes software developed by the OpenSSL Project for use in the OpenSSL Toolkit. This product includes cryptographic software written by Eric Young (eay@cryptsoft.com). |
| openpyxl | 3.1.5 | MIT |
| et_xmlfile | 2.0.0 | MIT и уведомления в комплекте |
| PyInstaller | 6.16.0 | [GPL с исключением для сборок и лицензия загрузчика](https://pyinstaller.org/en/v6.16.0/license.html) |
| packaging, setuptools | 26.3, 65.5.0 | Тексты лицензий из соответствующих пакетов |
