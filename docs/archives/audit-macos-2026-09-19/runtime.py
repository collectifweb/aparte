import os,tempfile,threading,types
from pathlib import Path
from unittest.mock import patch, Mock
with tempfile.TemporaryDirectory(prefix='aparte-mac-runtime-audit-') as root:
    for key in ('XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_RUNTIME_DIR','XDG_CACHE_HOME','TMPDIR'):
        os.environ[key]=root
    os.environ['APARTE_CONFIG']=root+'/config.json'
    tempfile.tempdir=root
    from aparte import macos_recording as mr, macos_tray, macos_insert
    from test_macos_recording import FakeSounddevice,_settings
    with patch.object(mr,'notify') as notify, patch.object(mr,'ensure_microphone_access'):
        def setup(transcribe):
            sd=FakeSounddevice(); now=[0.0]
            c=mr.RecordingController(transcribe,lambda:_settings(),clock=lambda:now[0])
            c._polish=lambda text,settings:text
            c._deliver=Mock()
            return c,sd,now
        paths=[]
        def fail(path):
            paths.append(path)
            raise RuntimeError('synthetic transcription failure')
        c,sd,now=setup(fail)
        with patch.object(mr,'_sounddevice',return_value=sd):
            c.toggle(); sd.streams[0].feed(16000); now[0]=1; c.toggle(); c._worker.join(2)
            print('TRANSCRIBE_FAILURE', {'state':c.state,'wav_exists':paths[0].exists(),'capture_kept':c._capture is not None,'delivery_calls':c._deliver.call_count})
        c.shutdown()
        c,sd,now=setup(lambda path:'synthetic text')
        notify.reset_mock()
        with patch.object(mr,'_sounddevice',return_value=sd):
            c.toggle(); sd.streams[0].feed(16000,status='input overflow'); cap=c._capture; now[0]=1; c.toggle(); c._worker.join(2)
            print('OVERFLOW',{'flag':cap.overflowed,'state':c.state,'delivery_calls':c._deliver.call_count,'notifications':notify.call_count})
        c.shutdown()
        entered=threading.Event(); release=threading.Event()
        def blocked(path):
            entered.set(); release.wait(5); return 'synthetic text'
        c,sd,now=setup(blocked)
        with patch.object(mr,'_sounddevice',return_value=sd):
            c.toggle(); sd.streams[0].feed(16000); now[0]=1; c.toggle(); entered.wait(2)
            print('SHUTDOWN_DURING_TRANSCRIBE',{'shutdown_return':c.shutdown(timeout=.1),'state_after':c.state,'worker_still_alive':c._worker.is_alive(),'worker_daemon':c._worker.daemon})
            release.set(); c._worker.join(2)
    q=Mock()
    with patch.object(macos_insert,'_quartz',return_value=q):
        macos_insert.type_unicode('A😀B')
        args=q.CGEventKeyboardSetUnicodeString.call_args.args
        print('UNICODE',{'passed_length':args[1],'utf16_units':len(args[2].encode('utf-16-le'))//2})
    with patch.dict(os.environ,{},clear=True):
        print('TRAY_WITHOUT_POSIX_LOCALE',macos_tray.labels()['idle'])
