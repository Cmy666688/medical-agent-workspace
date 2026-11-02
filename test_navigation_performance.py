"""Page switches must never initialize inference or run a healthy scheduler."""
import cProfile
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

runtime=Path(tempfile.mkdtemp(prefix='navigation_test_',dir='runtime'))
os.environ['MEDICAL_RUNTIME_DIR']=str(runtime)
manifest=Path('runtime/index_manifest.json')
if manifest.exists(): (runtime/manifest.name).write_bytes(manifest.read_bytes())
from streamlit.testing.v1 import AppTest
from agents import family as f
from agents import accounts
from agents import telemetry
import ui

account=accounts.register('performance_user','Performance-password-123','Performance test')['token']
member=f.create_family('Performance family','Me',account)
person=f.profile(member['token'])
app=AppTest.from_file('app.py',default_timeout=40).run()
app.session_state.personal_token=account
app.session_state.family_token=member['token']
app.run()
pages=['coordinator','agent_consultation','agent_medication','agent_risk','agent_education',
       'agent_family','agent_care','agent_schedule','family_home','knowledge','monitor']
result={}
f._last_poll.clear()
profiler=cProfile.Profile()
with patch.object(ui,'retrieval',side_effect=AssertionError('Navigation loaded the model')) as model, \
     patch.object(f,'worker_status',return_value=f.now().isoformat()), \
     patch.object(f,'tick',side_effect=AssertionError('Navigation reran the healthy worker')):
    profiler.enable()
    for cycle in range(3):
        for name in pages:
            start=time.perf_counter()
            app.switch_page('app_pages/'+name+'.py').run()
            assert not app.exception,[x.message for x in app.exception]
            assert not app.error,[x.value for x in app.error]
            result.setdefault(name,[]).append(round((time.perf_counter()-start)*1000,1))
    profiler.disable()
    assert model.call_count==0

# WAL readers can still authorize and read while the scheduler owns a write transaction.
with f.connect() as writer:
    writer.execute('BEGIN IMMEDIATE')
    assert f.profile(member['token'])['id']==person['id']

# Standalone use still dispatches reminders, at most once per 15 seconds.
f._last_poll.clear()
with patch.object(f,'worker_status',return_value=None),patch.object(f,'tick') as tick:
    for stamp in [100,101,108,116]:
        with patch.object(f.time,'monotonic',return_value=stamp): f.poll_reminders()
    assert tick.call_count==2

telemetry.record('navigation','old','request')
telemetry.record('excluded','skip','request')
telemetry.record('navigation','latest','request')
assert [x['request'] for x in telemetry.events(limit=1,kind='request',exclude_session='excluded')]==['latest']
Path('runtime/navigation_after.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
print('Navigation, scheduler fallback and concurrent database reads passed')
