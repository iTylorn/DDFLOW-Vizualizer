# FlowExport для DD FLOW

Внешняя обработка выгружает справочник переделов и карты DD FLOW и записывает согласованные настройки из JSON обмена. Собранная `FlowExport.epf` входит в архив Windows на странице [Releases](https://github.com/iTylorn/DDFLOW-Vizualizer/releases/latest).

Сборка исходников `FlowExport.xml` в отдельной файловой базе через конфигуратор 1С:Предприятия 8.3.27.2130:

```text
1cv8.exe DESIGNER /F "<путь к базе сборки>" /LoadExternalDataProcessorOrReportFromFiles "<путь к one_c/FlowExport.xml>" "<путь к FlowExport.epf>" /Out "<путь к журналу сборки>"
```

Для рабочих проверок нужна совместимая тестовая база 1С ERP с DD FLOW. Сценарий обмена описан в [руководстве](../ОБМЕН_С_1С.md).
