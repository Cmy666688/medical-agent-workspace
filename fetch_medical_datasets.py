"""Fetch small, real research datasets into ignored local storage; never deploy them."""
import csv,gzip,hashlib,io,json,time,urllib.parse,urllib.request,zipfile
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent/'data'/'external'

def fetch(name,url):
    request=urllib.request.Request(url,headers={'User-Agent':'MedicalCourseDatasetResearch/1.0'})
    with urllib.request.urlopen(request,timeout=35) as response:
        raw=response.read(25*1024*1024+1)
        if len(raw)>25*1024*1024: raise ValueError('Download exceeds 25 MB research limit')
        content_type=response.headers.get('Content-Type','')
    if name.endswith(('.gz','.zip','.xpt','.csv','.json')) and ('text/html' in content_type or raw[:30].lower().startswith(b'<!doctype html')):
        raise ValueError('Server returned HTML instead of a dataset')
    path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    entry=dict(path=name,url=url,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),content_type=content_type)
    if name.endswith('.csv'):
        rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        if not rows: raise ValueError('Empty CSV')
        entry.update(rows=len(rows),columns=list(rows[0]))
    elif name.endswith('.csv.gz'):
        rows=list(csv.DictReader(io.StringIO(gzip.decompress(raw).decode('utf-8-sig'))))
        entry.update(rows=len(rows),columns=list(rows[0]) if rows else [])
    elif name.endswith('.json'):
        obj=json.loads(raw)
        if name.startswith('openfda/'):
            results=obj['results']
            entry.update(records=len(results),section_coverage={key:sum(bool(row.get(key)) for row in results) for key in ('contraindications','drug_interactions','warnings','warnings_and_cautions')})
    elif name.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if name.startswith('tfda/'):
                filename=next(item for item in archive.namelist() if item.lower().endswith('.json'))
                if archive.getinfo(filename).file_size>100*1024*1024: raise ValueError('Archive exceeds expanded research limit')
                records=json.loads(archive.read(filename).decode('utf-8-sig'))
                assert isinstance(records,list) and records and isinstance(records[0],dict)
                entry.update(rows=len(records),columns=list(records[0]))
            else:
                filename=next(name for name in archive.namelist() if name.endswith('processed.cleveland.data'))
                cases=list(csv.reader(io.StringIO(archive.read(filename).decode())))
                assert len(cases)==303 and all(len(row)==14 for row in cases)
                entry.update(cleveland_rows=len(cases),cleveland_columns=14)
    elif name.endswith('.xpt'):
        import pandas as pd
        frame=pd.read_sas(io.BytesIO(raw),format='xport')
        entry.update(rows=len(frame),columns=list(frame.columns))
    return entry

def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    jobs={
        'ddinter2/code_A.csv':'https://ddinter2.scbdd.com/static/media/download/ddinter_downloads_code_A.csv',
        'ddinter2/TERMS.html':'https://ddinter2.scbdd.com/terms/',
        'uci_heart/heart_disease.zip':'https://archive.ics.uci.edu/static/public/45/heart+disease.zip',
        'nhanes/BPXO_L.xpt':'https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/BPXO_L.xpt',
        'nhanes/DEMO_L.xpt':'https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/DEMO_L.xpt',
        'tfda/drug_licenses.json.zip':'https://data.fda.gov.tw/data/opendata/export/36/json',
        'tfda/labels_and_packages.json.zip':'https://data.fda.gov.tw/data/opendata/export/39/json',
        'tfda/appearance.json.zip':'https://data.fda.gov.tw/data/opendata/export/42/json',
    }
    prefix='https://physionet.org/files/mimic-iv-ed-demo/2.2/'
    for filename in ('edstays','triage','vitalsign','diagnosis','medrecon','pyxis'):
        jobs['mimic_iv_ed_demo/'+filename+'.csv.gz']=prefix+'ed/'+filename+'.csv.gz'
    jobs['mimic_iv_ed_demo/LICENSE.txt']=prefix+'LICENSE.txt'
    jobs['mimic_iv_ed_demo/SHA256SUMS.txt']=prefix+'SHA256SUMS.txt'
    for drug in ('IBUPROFEN','ACETAMINOPHEN','AMOXICILLIN','METFORMIN HYDROCHLORIDE','WARFARIN SODIUM'):
        query=urllib.parse.urlencode({'search':'openfda.generic_name:"'+drug+'"','limit':3})
        jobs['openfda/'+drug.lower().replace(' ','_')+'.json']='https://api.fda.gov/drug/label.json?'+query
    entries=[]; failures=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(fetch,name,url):name for name,url in jobs.items()}
        for future in as_completed(futures):
            name=futures[future]
            try:
                entry=future.result();entries.append(entry)
                print(json.dumps({key:entry[key] for key in ('path','bytes','rows','records','cleveland_rows') if key in entry}),flush=True)
            except Exception as exc:
                failure=dict(path=name,error=type(exc).__name__,detail=str(exc));failures.append(failure);print(json.dumps(failure),flush=True)
    sums=ROOT/'mimic_iv_ed_demo/SHA256SUMS.txt'
    if sums.exists():
        expected={line.split()[-1].removeprefix('./'):line.split()[0] for line in sums.read_text().splitlines() if line.strip()}
        for entry in entries:
            if entry['path'].startswith('mimic_iv_ed_demo/') and entry['path'].endswith('.csv.gz'):
                key='ed/'+Path(entry['path']).name
                entry['publisher_checksum_verified']=expected.get(key)==entry['sha256']
                if not entry['publisher_checksum_verified']: failures.append(dict(path=entry['path'],error='publisher_checksum_mismatch'))
    report=dict(retrieved_at=datetime.now(timezone.utc).isoformat(),purpose='Offline research only. Not imported into the public app, not uploaded to GitHub, no LLM calls.',files=sorted(entries,key=lambda item:item['path']),failures=failures)
    (ROOT/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(downloaded=len(entries),failures=len(failures))))
    if failures: raise SystemExit(1)

if __name__=='__main__': main()
