import argparse, json, random, re, time, zipfile
from pathlib import Path
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset
from transformers import AutoModel, AutoTokenizer, Trainer, TrainingArguments, set_seed
from pymilvus import MilvusClient
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
PROMPT = '为这个句子生成表示以用于检索相关文章：'

def input_file(pattern):
    paths = list(ROOT.glob(pattern))
    if len(paths) != 1: raise RuntimeError(f'Expected exactly one {pattern}, got {paths}')
    return paths[0]

def prepare():
    model_dir = ROOT / 'data' / 'models' / 'bge-small-zh-v1.5'
    if not (model_dir / 'config.json').exists():
        target = model_dir.parent
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(input_file('bge-small-zh-v1.5*.zip')) as z:
            for info in z.infolist():
                if not (target / info.filename).resolve().is_relative_to(target.resolve()):
                    raise ValueError('Unsafe zip path')
            z.extractall(target)
    records = [json.loads(x) for x in input_file('medical*.json').read_text(encoding='utf-8').splitlines() if x.strip()]
    samples = [json.loads(x) for x in input_file('bert_retrieval_samples*.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    train = [x for x in samples if x['split']=='train' and not x.get('weak_label', False)]
    evaluate = [x for x in samples if x['split']=='eval']
    assert (len(records),len(train),len(evaluate)) == (8808,72,24)
    return model_dir, records, train, evaluate

def doc_text(r):
    return f"疾病：{r['name']}。症状：{'、'.join(r.get('symptom', [])[:6])}。简介：{r.get('desc','')[:100]}"

def encode(model, tokenizer, texts, query=False, batch_size=64):
    model.eval(); result=[]
    with torch.inference_mode():
        for start in range(0,len(texts),batch_size):
            batch=texts[start:start+batch_size]
            if query: batch=[PROMPT+x for x in batch]
            tokens=tokenizer(batch,padding=True,truncation=True,max_length=64,return_tensors='pt')
            tokens={k:v.to(next(model.parameters()).device) for k,v in tokens.items()}
            result.append(F.normalize(model(**tokens).last_hidden_state[:,0],p=2,dim=1).cpu().numpy())
            if len(texts)>1000 and (start==0 or start+batch_size>=len(texts) or start%1024==0): print(f'编码 {min(start+batch_size,len(texts))}/{len(texts)}',flush=True)
    return np.concatenate(result).astype('float32')

class Pairs(Dataset):
    def __init__(self, samples, by_id): self.rows=[{'query':x['query'],'document':doc_text(by_id[x['positive_doc_id']])} for x in samples]
    def __len__(self): return len(self.rows)
    def __getitem__(self,i): return self.rows[i]

class PairCollator:
    def __init__(self,tokenizer): self.tokenizer=tokenizer
    def __call__(self,rows):
        def tok(texts): return dict(self.tokenizer(texts,padding=True,truncation=True,max_length=64,return_tensors='pt'))
        return {'query_inputs':tok([PROMPT+r['query'] for r in rows]),'doc_inputs':tok([r['document'] for r in rows])}

class BGERetriever(nn.Module):
    def __init__(self,base):
        super().__init__(); self.encoder=AutoModel.from_pretrained(base,local_files_only=True)
    def forward(self,query_inputs,doc_inputs):
        q=F.normalize(self.encoder(**query_inputs).last_hidden_state[:,0],p=2,dim=1)
        d=F.normalize(self.encoder(**doc_inputs).last_hidden_state[:,0],p=2,dim=1)
        scores=q@d.T*20
        return {'loss':F.cross_entropy(scores,torch.arange(scores.size(0),device=scores.device))}

def create_collection(client,name,vectors,records):
    if client.has_collection(name): client.drop_collection(name)
    client.create_collection(collection_name=name,dimension=512,metric_type='COSINE',id_type='int',auto_id=False)
    for start in range(0,len(records),256):
        data=[{'id':i,'vector':vectors[i].tolist(),'doc_id':records[i]['_id']['$oid'],'name':records[i]['name']} for i in range(start,min(start+256,len(records)))]
        client.insert(collection_name=name,data=data)
    client.flush(collection_name=name)
    print('集合',name,'记录数',client.get_collection_stats(name),flush=True)

def search(client,name,vector,records):
    hits=client.search(collection_name=name,data=[vector.tolist()],limit=10,output_fields=['doc_id','name'],search_params={'metric_type':'COSINE'})[0]
    result=[]
    for i,h in enumerate(hits,1):
        entity=h.get('entity',{}); item={'rank':i,'doc_id':entity.get('doc_id'),'name':entity.get('name'),'score':float(h['distance'])}; result.append(item)
    return result

def metrics(model,tokenizer,records,evals):
    docs=encode(model,tokenizer,[doc_text(r) for r in records]); queries=encode(model,tokenizer,[r['query'] for r in evals],query=True)
    scores=queries@docs.T; lookup={r['_id']['$oid']:i for i,r in enumerate(records)}; rows=[]
    for sample,score in zip(evals,scores):
        order=np.argsort(-score); target=lookup[sample['positive_doc_id']]; rank=int(np.flatnonzero(order==target)[0])+1
        rows.append({'query':sample['query'],'target_id':sample['positive_doc_id'],'target_name':sample['positive_name'],'rank':rank,'top10':[{'doc_id':records[i]['_id']['$oid'],'name':records[i]['name'],'score':float(score[i])} for i in order[:10]]})
    recalls={f'Recall@{k}':sum(r['rank']<=k for r in rows)/len(rows) for k in (1,5,10)}
    return docs,queries,rows,recalls

def main():
    p=argparse.ArgumentParser(description='BGE + Milvus 医疗检索实验')
    p.add_argument('--mode',choices=['demo','train'],default='demo'); p.add_argument('--run-name',default='demo_000000'); p.add_argument('--steps',type=int,default=50); p.add_argument('--logging-steps',type=int,default=5); p.add_argument('--threads',type=int,default=4); p.add_argument('--seed',type=int,default=20261029)
    a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_]+',a.run_name): p.error('run-name 只能包含英文、数字、下划线')
    torch.set_num_threads(a.threads); set_seed(a.seed)
    base,records,train,evals=prepare(); tok=AutoTokenizer.from_pretrained(base,local_files_only=True)
    out=ROOT/'runs'/a.run_name; out.mkdir(parents=True,exist_ok=True)
    device='cuda' if torch.cuda.is_available() else 'cpu'; print('设备:',device,'输出:',out,flush=True)
    model=AutoModel.from_pretrained(base,local_files_only=True).to(device)
    if a.mode=='demo':
        subset=records[:20]; query='咳嗽发热，想查肺部感染的相关疾病资料'; docs=encode(model,tok,[doc_text(r) for r in subset]); q=encode(model,tok,[query],True)[0]
        print('问题向量形状:',q.shape,'前8维:',q[:8]); print('资料向量形状:',docs[0].shape,'前8维:',docs[0,:8]); print('余弦相似度:',float(q@docs[0]))
        db=out/'demo.db'; client=MilvusClient(uri=str(db)); create_collection(client,'medical_demo',docs,subset); hits=search(client,'medical_demo',q,subset); client.close()
        client=MilvusClient(uri=str(db)); again=search(client,'medical_demo',q,subset); client.close()
        assert [x['doc_id'] for x in hits]==[x['doc_id'] for x in again]
        by_id={r['_id']['$oid']:r for r in subset}; print('关闭并重新打开后 Top 10:',json.dumps(again,ensure_ascii=False,indent=2)); print('原始资料:',doc_text(by_id[again[0]['doc_id']]))
        (out/'demo_results.json').write_text(json.dumps({'question':query,'vector_shape':list(q.shape),'question_first8':q[:8].tolist(),'document_first8':docs[0,:8].tolist(),'cosine':float(q@docs[0]),'top10':again},ensure_ascii=False,indent=2),encoding='utf-8'); return
    if a.steps<50 or not 5<=a.logging_steps<=10: p.error('作业要求至少50步，logging-steps为5到10')
    by_id={r['_id']['$oid']:r for r in records}; retriever=BGERetriever(base)
    args=TrainingArguments(output_dir=str(out/'trainer'),learning_rate=2e-5,per_device_train_batch_size=8,max_steps=a.steps,logging_steps=a.logging_steps,save_strategy='no',report_to=[],seed=a.seed,data_seed=a.seed,remove_unused_columns=False,dataloader_num_workers=0,use_cpu=(device=='cpu'))
    trainer=Trainer(model=retriever,args=args,train_dataset=Pairs(train,by_id),data_collator=PairCollator(tok))
    start=time.time(); result=trainer.train(); elapsed=time.time()-start
    final=out/'model'; retriever.encoder.save_pretrained(final,safe_serialization=True); tok.save_pretrained(final)
    logs=trainer.state.log_history; (out/'training_log.json').write_text(json.dumps({'elapsed_seconds':elapsed,'device':device,'steps':trainer.state.global_step,'learning_rate':2e-5,'batch_size':8,'seed':a.seed,'log_history':logs},ensure_ascii=False,indent=2),encoding='utf-8')
    loss=[x for x in logs if 'loss' in x and 'step' in x]; plt.plot([x['step'] for x in loss],[x['loss'] for x in loss],marker='o',color='#2563eb'); plt.title('Training Loss - '+a.run_name); plt.xlabel('Step'); plt.ylabel('Loss'); plt.grid(alpha=.3); plt.tight_layout(); plt.savefig(out/'loss_curve.png',dpi=160); plt.close()
    print('训练完成:',trainer.state.global_step,'step，耗时',round(elapsed,1),'秒',flush=True)
    before_docs,before_q,before_rows,before_metrics=metrics(model,tok,records,evals)
    del model, retriever, trainer
    after=AutoModel.from_pretrained(final,local_files_only=True).to(device)
    after_docs,after_q,after_rows,after_metrics=metrics(after,tok,records,evals)
    client=MilvusClient(uri=str(out/'full.db'))
    create_collection(client,'bge_before',before_docs,records); create_collection(client,'bge_after',after_docs,records)
    chosen=next(i for i,x in enumerate(evals) if '胆囊' not in x['query'] and '胆囊' not in x['positive_name'])
    report={'before':before_metrics,'after':after_metrics,'before_rows':before_rows,'after_rows':after_rows,'selected_before':before_rows[chosen],'selected_after':after_rows[chosen],'milvus_before_top10':search(client,'bge_before',before_q[chosen],records),'milvus_after_top10':search(client,'bge_after',after_q[chosen],records)}
    client.close(); (out/'evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
