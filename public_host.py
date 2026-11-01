"""Own a separate public web/worker/tunnel process group. No local user DB is copied."""
import json,os,re,secrets,shutil,subprocess,sys,time
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'runtime'/'public'
STATE=RUNTIME/'hosting.json'
PORT=8503

def write_state(data):
    temporary=STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,indent=2),encoding='utf-8')
    temporary.replace(STATE)

def run():
    RUNTIME.mkdir(parents=True,exist_ok=True)
    binary=shutil.which('cloudflared')
    if not binary: raise RuntimeError('Install official cloudflared first.')
    env=dict(os.environ,MEDICAL_PUBLIC_MODE='1',MEDICAL_RUNTIME_DIR=str(RUNTIME),MEDICAL_API_CONFIG=str(ROOT/'config'/'api.local.toml'),PYTHONIOENCODING='utf-8')
    secret=RUNTIME/'cookie-secret.txt'
    if not secret.exists(): secret.write_text(secrets.token_urlsafe(48),encoding='utf-8')
    env['STREAMLIT_SERVER_COOKIE_SECRET']=secret.read_text(encoding='utf-8').strip()
    env['STREAMLIT_SERVER_ENABLE_CORS']='true'
    env['STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION']='true'
    env['STREAMLIT_CLIENT_SHOW_ERROR_DETAILS']='none'
    env['STREAMLIT_SERVER_MAX_UPLOAD_SIZE']='10'
    env['STREAMLIT_SERVER_MAX_MESSAGE_SIZE']='20'
    manifest=RUNTIME/'index_manifest.json'
    if not manifest.exists():
        manifest.write_text(json.dumps(dict(database='medical.db',collection='bge_after',records=8808,dimension=512,indexed_at=None)),encoding='utf-8')
    state=dict(supervisor_pid=os.getpid(),port=PORT,phase='starting',runtime=str(RUNTIME))
    write_state(state)
    children=[]; logs=[]
    def launch(name,args):
        log=(RUNTIME/(name+'.log')).open('w',encoding='utf-8')
        logs.append(log)
        process=subprocess.Popen(args,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        children.append(process); state[name+'_pid']=process.pid; write_state(state)
        return process
    try:
        tunnel=launch('tunnel',[binary,'tunnel','--no-autoupdate','--protocol','http2','--edge-ip-version','4','--url',f'http://127.0.0.1:{PORT}'])
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            if tunnel.poll() is not None: raise RuntimeError('Tunnel exited; see tunnel.log')
            content=(RUNTIME/'tunnel.log').read_text(encoding='utf-8',errors='replace')
            match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',content)
            if match: break
            time.sleep(.3)
        else: raise RuntimeError('No public hostname returned; see tunnel.log')
        state['url']=match.group(0)
        host=state['url'].split('://',1)[1]
        env['STREAMLIT_BROWSER_SERVER_ADDRESS']=host
        env['STREAMLIT_BROWSER_SERVER_PORT']='443'
        web=launch('web',[sys.executable,'-m','streamlit','run',str(ROOT/'app.py'),'--server.address','127.0.0.1','--server.port',str(PORT)])
        worker=launch('worker',[sys.executable,str(ROOT/'reminder_worker.py'),'--runtime-profile','public'])
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if web.poll() is not None: raise RuntimeError('Public web service exited; see web.log')
            try:
                with urlopen(f'http://127.0.0.1:{PORT}/_stcore/health',timeout=2) as response:
                    if response.read()==b'ok': break
            except OSError: pass
            time.sleep(.3)
        else: raise RuntimeError('Public web service not ready; see web.log')
        state['phase']='ready'; write_state(state)
        while True:
            for process in children:
                if process.poll() is not None: raise RuntimeError('A public service stopped; rerun start_public.ps1')
            time.sleep(2)
    except BaseException as exc:
        state['phase']='stopped'; state['error']=str(exc); write_state(state)
        raise
    finally:
        for process in children:
            if process.poll() is None: process.terminate()
        for log in logs: log.close()

if __name__=='__main__': run()
