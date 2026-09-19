import argparse, contextlib, json, os, signal, subprocess, sys, tempfile, time
from pathlib import Path
from unittest import mock
from aparte import session, cli, tray
from aparte.config import Settings

with tempfile.TemporaryDirectory(prefix='aparte-audit-') as td:
    root = Path(td)
    env = {'APARTE_RUNTIME_DIR':td,'APARTE_CONFIG':str(root/'config.json'), 'XDG_STATE_HOME':str(root/'state')}
    with mock.patch.dict(os.environ,env):
        fake=root/'arecord'
        fake.write_text('#!/bin/sh\necho "ALSA: No such device" >&2\nexit 1\n')
        fake.chmod(0o700)
        with mock.patch.object(session.shutil,'which',return_value=str(fake)):
            try: session.start_toggle_recording()
            except session.RecordingError as e: print('ERROR_WITH_MISSING_DEVICE:',str(e))
        # A real child whose /proc has recorder markers but never opens audio.
        pth=root/f'toggle-{int(time.time()*1000)}.wav'
        p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)','arecord',str(pth)],start_new_session=True)
        rec=session.RecordingSession(p.pid,pth,16000,time.time())
        pth.write_bytes(b'\0'*32044)
        try:
            session._claim_session(rec)
            dummy=object.__new__(tray.Tray)
            dummy.on_quit=mock.Mock()
            with mock.patch.object(tray,'Gtk',mock.Mock(),create=True): dummy._quit()
            print('QUIT_LEAVES_RECORDER_ALIVE:',p.poll() is None)
            p.terminate();p.wait(timeout=3)
            dummy.labels=tray.LABELS['en'];dummy.recording=False;dummy.indicator=mock.Mock()
            dummy._refresh()
            print('DEAD_RECORDER_TRAY_LABEL:',dummy.indicator.set_title.call_args.args[0])
            args=argparse.Namespace(status=False,sample_rate=16000,no_polish=False,style=None,cleanup_level=None,target='paste',keep_audio=False)
            with mock.patch.object(cli,'transcribe_path',side_effect=RuntimeError('GPU unavailable')),mock.patch.object(cli,'notify') as notify:
                try: cli.toggle_dictation(args,Settings())
                except RuntimeError as e: print('TRANSCRIBE_ERROR:',e)
            print('FAILED_TRANSCRIBE_AUDIO_RETAINED:',pth.exists())
            print('FAILED_TRANSCRIBE_NOTIFICATIONS:',[c.args[0] for c in notify.call_args_list])
        finally:
            if p.poll() is None:p.kill();p.wait()
