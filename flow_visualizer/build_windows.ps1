param(
    [string]$Python = "python",
    [string]$AdditionalPackages = "",
    [string]$DistDirectory = "dist",
    [string]$AppName = "FlowVisualizer"
)
$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$distDir = Join-Path $projectDir $DistDirectory
$buildDir = Join-Path $projectDir 'build'
$specDir = Join-Path $buildDir 'spec'
New-Item -ItemType Directory -Force -Path $distDir, $buildDir, $specDir | Out-Null
$installerArgs = @('-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
    '--name', $AppName, '--distpath', $distDir, '--workpath', $buildDir,
    '--specpath', $specDir, '--exclude-module', 'pandas', '--exclude-module', 'numpy',
    '--exclude-module', 'matplotlib', '--exclude-module', 'lxml')
if ($AdditionalPackages) { $installerArgs += @('--paths', $AdditionalPackages) }
$installerArgs += (Join-Path $projectDir 'gui.py')
& $Python @installerArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с кодом $LASTEXITCODE" }
# Qt6 in this PySide release uses Windows' unversioned ICU. PyInstaller can
# discover a different, version-suffixed ICU from PATH; shipping it makes Qt
# fail to load. Rely on the Windows 10/11 system ICU instead.
$internalDir = Join-Path (Join-Path $distDir $AppName) '_internal'
# PyInstaller's Qt hook also collects optional plugins and their dependencies.
# PDF export uses QtPrintSupport, so the PDF image plugin is unnecessary.
$unusedFiles = @(
    'icuuc.dll', 'icudt78.dll', 'libcrypto-3-x64.dll', 'libssl-3-x64.dll',
    'PySide6/opengl32sw.dll', 'PySide6/Qt6OpenGL.dll', 'PySide6/Qt6Pdf.dll',
    'PySide6/Qt6Qml.dll', 'PySide6/Qt6QmlMeta.dll', 'PySide6/Qt6QmlModels.dll',
    'PySide6/Qt6QmlWorkerScript.dll', 'PySide6/Qt6Quick.dll', 'PySide6/Qt6VirtualKeyboard.dll',
    'PySide6/plugins/imageformats/qpdf.dll',
    'PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll',
    'PySide6/plugins/tls/qopensslbackend.dll'
)
foreach ($name in $unusedFiles) {
    $candidate = Join-Path $internalDir $name
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { Remove-Item -LiteralPath $candidate }
}
# Use the system CRT. Microsoft supplies it via Windows or the official
# Microsoft Visual C++ Redistributable.
foreach ($folder in @($internalDir, (Join-Path $internalDir 'PySide6'))) {
    Get-ChildItem -LiteralPath $folder -File | Where-Object {
        $_.Name -match '^(?:api-ms-win-.*|ucrtbase|vcruntime140(?:_\d+)?|msvcp140(?:_\d+)?)\.dll$'
    } | ForEach-Object { Remove-Item -LiteralPath $_.FullName }
}
Write-Host "Готово: $(Join-Path (Join-Path $distDir $AppName) ($AppName + '.exe'))"
