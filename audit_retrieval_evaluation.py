"""Re-evaluate all held-out queries using stored vectors; never train or change labels."""
import json
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import torch
from transformers import AutoModel,AutoTokenizer
from pymilvus import MilvusClient
from medical_retrieval import prepare,encode

ROOT=Path(__file__).resolve().parent


def main():
    torch.set_num_threads(4)
    base,records,_,samples=prepare()
    run=ROOT/'runs/check_full_1031'
    if not (run/'full.db').exists():raise RuntimeError('缺少既有向量集合，不能生成真实逐题审计。')
    saved=json.loads((run/'evaluation.json').read_text(encoding='utf-8'))
    lookup={row['_id']['$oid']:index for index,row in enumerate(records)}
    client=MilvusClient(uri=str(run/'full.db'))
    ranks={};metrics={}
    tokenizer=AutoTokenizer.from_pretrained(base,local_files_only=True)
    try:
        for stage,path in [('before',base),('after',run/'model')]:
            client.load_collection(collection_name='bge_'+stage)
            print('Encoding held-out queries:',stage,flush=True)
            model=AutoModel.from_pretrained(path,local_files_only=True).eval()
            queries=encode(model,tokenizer,[sample['query'] for sample in samples],query=True)
            del model
            vectors=np.zeros((len(records),512),dtype='float32');seen=set()
            for start in range(0,len(records),512):
                rows=client.get(collection_name='bge_'+stage,ids=list(range(start,min(start+512,len(records)))),output_fields=['doc_id','vector'])
                for row in rows:
                    index=lookup[row['doc_id']];vectors[index]=row['vector'];seen.add(index)
            if len(seen)!=len(records):raise RuntimeError('Incomplete stored vector index; audit stopped')
            scores=queries@vectors.T
            stage_ranks=[]
            for sample,score in zip(samples,scores):
                order=np.argsort(-score);target=lookup[sample['positive_doc_id']]
                stage_ranks.append(int(np.flatnonzero(order==target)[0])+1)
            ranks[stage]=stage_ranks
            metrics[stage]={f'Recall@{k}':sum(rank<=k for rank in stage_ranks)/len(samples) for k in (1,5,10)}
            print(stage,metrics[stage],flush=True)
    finally:client.close()
    rows=[dict(query=sample['query'],target_id=sample['positive_doc_id'],target_name=sample['positive_name'],before_rank=a,after_rank=b) for sample,a,b in zip(samples,ranks['before'],ranks['after'])]
    result=dict(created_at=datetime.now(timezone.utc).isoformat(),method='原始固定 eval 问句、原始标签、两个既有向量集合、分别用原始/微调模型编码问题；不训练、不改标签。',metrics=metrics,rows=rows,
                matches_saved_metrics=all(abs(metrics[stage][key]-saved[stage][key])<1e-8 for stage in metrics for key in metrics[stage]))
    (run/'audit_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Per-query audit saved; original evaluation and model untouched.',flush=True)


if __name__=='__main__':main()
