"""Isolated backend audit probes; takes an Aparté checkout, never serves HTTP."""
import errno
import json
import os
import sys
import tempfile
import threading
from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

checkout = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(checkout / 'src'))
from aparte import __version__, config, desktop, history
from aparte.config import Settings


def request(method, path, body=b'', headers=None, handler_class=None):
    cls = handler_class or desktop.handler_factory(Settings())
    handler = cls.__new__(cls)
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    if 'Host' not in message:
        message['Host'] = '127.0.0.1:8765'
    if body:
        message['Content-Length'] = str(len(body))
    handler.headers = message
    handler.path = path
    handler.command = method
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    captured = {'status': None}
    handler.send_response = lambda code, *a: captured.update(status=int(code))
    handler.send_header = lambda *a: None
    handler.end_headers = lambda: None
    handler.send_error = lambda code, *a, **k: captured.update(status=int(code))
    (handler.do_GET if method == 'GET' else handler.do_POST)()
    captured['body'] = handler.wfile.getvalue().decode()
    return captured


with tempfile.TemporaryDirectory(prefix='aparte-backend-probe-') as directory:
    root = Path(directory)
    env = {
        'APARTE_CONFIG': str(root / 'config.json'),
        'APARTE_RUNTIME_DIR': str(root / 'run'),
        'XDG_STATE_HOME': str(root / 'state'),
        'XDG_CONFIG_HOME': str(root / 'cfg'),
        'XDG_DATA_HOME': str(root / 'data'),
    }
    with patch.dict(os.environ, env):
        print('MODULE', desktop.__file__, 'VERSION', __version__)
        handler_class = desktop.handler_factory(Settings())
        with patch.object(desktop.tempfile, 'NamedTemporaryFile', side_effect=OSError(errno.ENOSPC, 'No space left on device')):
            failure = request('POST', '/api/transcribe', b'synthetic audio', handler_class=handler_class)
        preview = request('POST', '/api/transcribe?preview=1', b'synthetic audio', handler_class=handler_class)
        assert failure['status'] == 500 and json.loads(preview['body'])['busy']
        print('LOCK_FAILURE', failure, 'NEXT_PREVIEW', preview)
        history.record('synthetic confidential dictation')
        foreign = {'Host': 'rebound.attacker.invalid:8765', 'Origin': 'http://rebound.attacker.invalid:8765'}
        get = request('GET', '/api/history', headers=foreign)
        post = request('POST', '/api/history', b'{}', headers=foreign)
        assert get['status'] == 200 and 'synthetic confidential' in get['body'] and post['status'] == 403
        print('FOREIGN_HOST_HISTORY_GET', get, 'POST', post)
        config.update_config({'model': 'small'})
        original_dump = json.dump
        observed = []
        def during_dump(*args, **kwargs):
            try:
                config.load_config()
            except Exception as exc:
                observed.append(type(exc).__name__)
            return original_dump(*args, **kwargs)
        with patch.object(config.json, 'dump', side_effect=during_dump):
            config.update_config({'model': 'base'})
        assert observed == ['JSONDecodeError']
        print('CONFIG_READ_DURING_SAVE', observed)
        with patch.object(config.json, 'dump', side_effect=OSError(errno.ENOSPC, 'No space left on device')):
            try:
                config.update_config({'model': 'tiny'})
            except OSError:
                pass
        remaining = (root / 'config.json').read_text()
        assert remaining == ''
        print('CONFIG_AFTER_WRITE_FAILURE', repr(remaining))
        history.clear()
        barrier = threading.Barrier(2)
        original_entries = history.entries
        def concurrent_entries(*args, **kwargs):
            result = original_entries(*args, **kwargs)
            barrier.wait(timeout=3)
            return result
        with patch.object(history, 'entries', side_effect=concurrent_entries):
            threads = [threading.Thread(target=history.record, args=(text,)) for text in ('dictation A', 'dictation B')]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)
        remaining_history = [item['text'] for item in history.entries()]
        assert len(remaining_history) < 2
        print('HISTORY_CONCURRENT_WRITES', remaining_history)
