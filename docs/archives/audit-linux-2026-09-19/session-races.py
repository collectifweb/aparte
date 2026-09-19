import concurrent.futures, json, os, signal, subprocess, sys, tempfile, threading, time
from pathlib import Path
from unittest import mock
from aparte import session

with tempfile.TemporaryDirectory(prefix='aparte-audit-races-') as td:
    with mock.patch.dict(os.environ,{'APARTE_RUNTIME_DIR':td}):
        root=Path(td); wav=root/'toggle-100.wav';wav.write_bytes(b'\0'*32044)
        rec=session.RecordingSession(999999999,wav,16000,time.time())
        session._claim_session(rec)
        barrier=threading.Barrier(2)
        stop=session._stop_recorder
        def synchronized_stop(rec,number=signal.SIGINT):
            if number==signal.SIGINT:barrier.wait(timeout=3)
            return stop(rec,number)
        with mock.patch.object(session,'_stop_recorder',side_effect=synchronized_stop):
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                results=list(pool.map(lambda _:session.stop_toggle_recording(),range(2)))
        print('SIMULTANEOUS_STOPS_BOTH_ACCEPTED:',len(results))
        print('SIMULTANEOUS_STOPS_SAME_CAPTURE:',results[0].audio_path==results[1].audio_path)
        # Preserve actual subprocess semantics while replacing audio backend only.
        real_popen=subprocess.Popen;children=[]
        def recorder_simulator(command,**kwargs):
            p=real_popen([sys.executable,'-c','import time;time.sleep(30)','arecord',command[-1]],**kwargs)
            children.append(p);return p
        try:
            with mock.patch.object(session.shutil,'which',return_value='/usr/bin/arecord'),mock.patch.object(session.subprocess,'Popen',side_effect=recorder_simulator),mock.patch.object(session,'_claim_session',side_effect=OSError(28,'No space left on device')):
                try:session.start_toggle_recording()
                except OSError as e:print('SESSION_PUBLICATION_ERROR:',e)
            print('FAILED_PUBLICATION_RECORDER_STILL_ALIVE:',children[0].poll() is None)
            print('FAILED_PUBLICATION_SESSION_EXISTS:',(root/'toggle-session.json').exists())
        finally:
            for p in children:p.kill();p.wait(timeout=3)
