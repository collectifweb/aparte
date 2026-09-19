from pathlib import Path
from unittest.mock import patch
from tempfile import TemporaryDirectory
from aparte import macos_install, macos_desktop

with TemporaryDirectory(prefix='aparte-install-audit-') as directory:
    root = Path(directory)
    destination = root / 'Applications' / 'Aparté.app'
    destination.mkdir(parents=True)
    (destination / 'existing-install').write_text('valid old bundle')

    def fake_build(staging, *args):
        fresh = staging / 'Aparté.app'
        fresh.mkdir()
        return fresh

    with patch.object(macos_desktop, 'bundle_path', return_value=destination), \
         patch.object(macos_install, '_build', side_effect=fake_build), \
         patch.object(macos_install, 'read_cdhash', side_effect=['newhash', 'oldhash']), \
         patch.object(macos_install.shutil, 'move', side_effect=OSError('simulated cross-device copy failure')):
        try:
            macos_install.install_app('/fake/python', force=True)
        except OSError as exc:
            print('REPLACEMENT FAILURE:', exc)
            print('OLD BUNDLE STILL PRESENT:', destination.exists())
            assert not destination.exists(), 'Unexpected: the vulnerable path changed'
