# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（SRS §9.3）。

构建：

    pip install pyinstaller
    pyinstaller packaging/app.spec --noconfirm

产物：

    dist/app/app.exe          单文件 EXE（主交付）
    dist/app/_internal/       onedir 备选形态

SRS §9.3 要点：

1. 显式包含 GUI 入口、图标、data（config/drivers）、隐藏导入；
2. ``--windowed``（无控制台窗口）+ ``--name app`` + ``--icon app.ico``；
3. CH340 驱动建议由安装器（Inno Setup）在安装时运行，而不是打进 EXE；
4. 打包后需在干净 Windows 虚拟机上做冒烟测试。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_ROOT = Path(SPECPATH).parent
PACKAGE_ROOT = PROJECT_ROOT / "daccs"
icon_path = PROJECT_ROOT / "packaging" / "app.ico"

block_cipher = None

# 打包时把默认配置一并带上（运行期可被外部 config/default.json 覆盖）
datas = [
    (str(PACKAGE_ROOT / "config" / "default.json"), "config"),
]
# drivers/ 目录若存在则一并打包（CH340 驱动由安装器负责运行）
drivers_dir = PROJECT_ROOT / "drivers"
if drivers_dir.exists():
    datas.append((str(drivers_dir), "drivers"))

hiddenimports = [
    "pyserial",
    "serial.tools.list_ports",
    "cv2",
    "PySide6",
    "openpyxl",
    "docx",
    "matplotlib.backends.backend_agg",
    "pandas",
    "scipy",
    "numpy",
]
hiddenimports += collect_submodules("openpyxl")
hiddenimports += collect_submodules("docx")
datas += collect_data_files("openpyxl", include_py_files=True)
datas += collect_data_files("docx", include_py_files=True)

a = Analysis(
    [str(PACKAGE_ROOT / "__main__.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib.backends.backend_qt5agg",
        "matplotlib.backends.backend_qtagg",
        "PySide6.QtWebEngineCore",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="app",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # --windowed
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # 图标可选：缺失时回退到 PyInstaller 默认图标，避免打包直接失败
    **({"icon": str(icon_path)} if icon_path.exists() else {}),
)
