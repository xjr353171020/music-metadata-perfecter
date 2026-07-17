# Third-Party Notices

Music Metadata Perfecter is distributed under the GNU General Public License v3.0 only. The release build also contains third-party components governed by their own licenses.

## Python dependencies

| Component | License | Project |
| --- | --- | --- |
| PyQt6 | GPL-3.0-only or commercial | https://www.riverbankcomputing.com/software/pyqt/ |
| Qt 6 libraries distributed with PyQt6 | Qt commercial, LGPL, or GPL terms depending on the component | https://www.qt.io/licensing/ |
| Requests | Apache-2.0 | https://requests.readthedocs.io/ |
| Mutagen | GPL-2.0-or-later | https://github.com/quodlibet/mutagen |
| Pillow | HPND / MIT-CMU style terms | https://python-pillow.org/ |
| pypinyin | MIT | https://github.com/mozillazg/python-pinyin |
| pykakasi | GPL-3.0-or-later | https://codeberg.org/miurahr/pykakasi |
| PyInstaller | GPL-2.0-or-later with the PyInstaller bootloader exception | https://pyinstaller.org/ |

The exact dependency versions used for a release are determined by `requirements.txt`, `requirements-build.txt`, and the release build environment. Refer to each upstream distribution for its complete license text and notices.

## Bundled NCM converter

`Ncm拖一拖.exe` is bundled as a separate converter component so the application's NCM workflow can invoke it. The repository owner confirmed permission to redistribute this binary for this project on 2026-07-17. Its embedded Windows version metadata does not identify an upstream project, copyright holder, or license.

This notice does not relicense the converter under GPL-3.0-only. Do not assume rights to extract, modify, or redistribute it separately beyond permissions supplied by its rights holder.
