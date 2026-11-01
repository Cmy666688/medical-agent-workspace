"""Own a separate public web/worker/tunnel process group. No local user DB is copied."""
import json,os,re,secrets,shutil,subprocess,sys,time
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'runtime'/'public'
STATE=RUNTIME/'hosting.json'
PORT=8503

class ExistingProcess:
    """Attach only to a previously recorded, verified public tunnel or worker."""
    def __init__(self,pid,kind):
        import ctypes
        from ctypes import wintypes
        self.pid=int(pid)
        script=f'Get-CimInstance Win32_Process -Filter "ProcessId = {self.pid}" | Select-Object Name,CommandLine | ConvertTo-Json -Compress'
        result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,text=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
        record=json.loads(result.stdout)
        command=record.get('CommandLine') or ''
        valid=(kind=='tunnel' and record['Name']=='cloudflared.exe' and '--url http://127.0.0.1:8503' in command) or (kind=='worker' and str(ROOT/'reminder_worker.py') in command and '--runtime-profile public' in command)
        if not valid: raise RuntimeError('Recorded public process does not match its expected command')
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        self.api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];self.api.OpenProcess.restype=wintypes.HANDLE
        self.api.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        self.api.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
        self.api.CloseHandle.argtypes=[wintypes.HANDLE]
        self.handle=self.api.OpenProcess(0x100000|0x1000|0x1,False,self.pid)
        if not self.handle: raise OSError('Cannot attach to existing public process')
    def poll(self):
        from ctypes import byref
        from ctypes.wintypes import DWORD
        code=DWORD()
        if not self.api.GetExitCodeProcess(self.handle,byref(code)): return 1
        return None if code.value==259 else code.value
    def terminate(self): self.api.TerminateProcess(self.handle,0)
    def close(self): self.api.CloseHandle(self.handle)

def write_state(data):
    temporary=STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,indent=2),encoding='utf-8')
    temporary.replace(STATE)

def run():
    RUNTIME.mkdir(parents=True,exist_ok=True)
    previous=json.loads(STATE.read_text(encoding='utf-8-sig')) if '--reuse-tunnel' in sys.argv else None
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
        if previous:
            if not re.fullmatch(r'https://[a-z0-9-]+\.trycloudflare\.com',previous['url']): raise ValueError('Invalid recorded tunnel URL')
            for kind in ('tunnel','worker'):
                process=ExistingProcess(previous[kind+'_pid'],kind);children.append(process);state[kind+'_pid']=process.pid
            state['url']=previous['url']
        else:
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
        if not previous: worker=launch('worker',[sys.executable,str(ROOT/'reminder_worker.py'),'--runtime-profile','public'])
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
            if isinstance(process,ExistingProcess): process.close()
        for log in logs: log.close()

if __name__=='__main__': run()
