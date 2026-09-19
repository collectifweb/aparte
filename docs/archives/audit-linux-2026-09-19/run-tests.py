import os, pathlib, subprocess, tempfile
root=pathlib.Path(tempfile.mkdtemp(prefix='aparte-audit-tests-'))
e=os.environ.copy()
for key in list(e):
    if key.startswith(('APARTE_', 'MURMUR_')):
        del e[key]
for key,suffix in [('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_STATE_HOME','state'),('XDG_RUNTIME_DIR','run'),('XDG_CACHE_HOME','cache')]:
    p=root/suffix
    p.mkdir(mode=0o700)
    e[key]=str(p)
e['APARTE_CONFIG']=str(root/'config'/'test.json')
e['PYTHONPATH']='src'
e['PYTHONDONTWRITEBYTECODE']='1'
e['LC_ALL']='fr_CA.UTF-8'
e['LANG']='fr_CA.UTF-8'
print('ISOLATION',root,flush=True)
with (root/'unittest.log').open('w') as out:
    result=subprocess.run(['python3','-m','unittest','discover','-s','tests','-t','tests'],env=e,stdout=out,stderr=subprocess.STDOUT,timeout=240)
print('EXIT',result.returncode)
print((root/'unittest.log').read_text()[-7000:])
