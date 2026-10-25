# PyInstaller spec — one-dir Windows build of the LitUbik launcher.
# Build:  packaging/build_windows.ps1  (or: pyinstaller packaging/litubik.spec)
# Output: dist/LitUbik/LitUbik.exe  (console app: closing the window stops it)
#
# playwright is EXCLUDED on purpose (~50 MB): the bot-protected OA tier and
# the institutional EZProxy/CAS tier already degrade silently without it —
# researchers who need those run from source (start.bat / pip) instead.
import os
import shutil
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))  # noqa: F821
sys.path.insert(0, os.path.join(ROOT, 'backend'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from PyInstaller.utils.hooks import collect_submodules

from gen_third_party_licenses import write_notices

# Full licence texts of everything bundled (Python distributions installed in
# this environment + the npm packages of the web interface): MIT/BSD-style
# licences ask for their notice to travel with every copy.
os.makedirs(workpath, exist_ok=True)  # noqa: F821
NOTICES = os.path.join(workpath, 'THIRD_PARTY_NOTICES.txt')  # noqa: F821
write_notices(NOTICES)

block_cipher = None

a = Analysis(
    ['launcher_entry.py'],
    pathex=['../backend'],
    binaries=[],
    datas=[
        ('../frontend/dist', 'frontend_dist'),
        ('../backend/alembic', 'alembic'),
        ('../backend/alembic.ini', '.'),
        ('../docs/help', 'docs_help'),
        ('../backend/app/data', 'app_data'),
    ],
    hiddenimports=(
        collect_submodules('uvicorn')
        + collect_submodules('app')
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['playwright', 'tkinter', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LitUbik',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon='litubik.ico',  # the citation-tree tile, same as the favicon
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='LitUbik',
)

# AGPLv3 §4-6: conveying the program means conveying its licence with it, and
# the third-party notices with theirs. Next to LitUbik.exe, where a user looks,
# rather than inside _internal/.
_out = os.path.join(DISTPATH, 'LitUbik')  # noqa: F821
for _name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_LICENSES.md'):
    shutil.copy2(os.path.join(ROOT, _name), os.path.join(_out, _name))
shutil.copy2(NOTICES, os.path.join(_out, 'THIRD_PARTY_NOTICES.txt'))
