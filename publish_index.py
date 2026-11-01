"""从已训练模型对应的向量重新建库，生成可追溯的索引发布清单。"""
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
from pymilvus import MilvusClient

ROOT=Path(__file__).resolve().parent
def publish():
    run=ROOT/'runs/check_full_1031'; output=ROOT/'runtime'; output.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    target=output/f'index_{stamp}.db'
    source=MilvusClient(uri=str(run/'full.db')); client=MilvusClient(uri=str(target))
    try:
        source.load_collection('bge_after')
        client.create_collection(collection_name='bge_after',dimension=512,metric_type='COSINE',id_type='int',auto_id=False)
        for start in range(0,8808,256):
            rows=source.get(collection_name='bge_after',ids=list(range(start,min(start+256,8808))),output_fields=['vector','doc_id','name'])
            assert len(rows)==min(256,8808-start)
            client.insert(collection_name='bge_after',data=[dict(id=r['id'],vector=r['vector'],doc_id=r['doc_id'],name=r['name']) for r in rows])
        client.flush('bge_after'); count=client.get_collection_stats('bge_after')['row_count']; assert count==8808
        with (run/'model/model.safetensors').open('rb') as file: digest=hashlib.file_digest(file,'sha256').hexdigest()
        manifest=dict(database=target.name,collection='bge_after',records=count,dimension=512,indexed_at=datetime.now(timezone.utc).isoformat(),model_sha256=digest,model_directory=str(run/'model'),origin='reindexed_from_verified_training_vectors')
        temp=output/'index_manifest.tmp'; temp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8'); temp.replace(output/'index_manifest.json')
        print(json.dumps(manifest,ensure_ascii=False,indent=2))
    finally: source.close(); client.close()

if __name__=='__main__': publish()
