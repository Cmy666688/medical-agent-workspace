"""原生 BGE + Milvus，检索路径不使用 LangChain。"""
import copy
import json
import os
import shutil
import threading
import time
from collections import OrderedDict
from pathlib import Path
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer
from pymilvus import MilvusClient
from .lexical import KeywordIndex,fuse
from .documents import DocumentStore

ROOT = Path(__file__).resolve().parents[1]

class RetrievalService:
    def __init__(self):
        self.lock = threading.RLock()
        self.cache = OrderedDict()
        run = ROOT / 'runs' / 'check_full_1031'
        if not (run / 'evaluation.json').exists():
            raise RuntimeError('缺少完整训练结果，请先运行 medical_retrieval.py --mode train --run-name check_full_1031')
        self.model_path = run / 'model'
        self.source_db = run / 'full.db'
        self.path = Path(os.getenv('MEDICAL_RUNTIME_DIR',str(ROOT / 'runtime'))) / 'medical.db'
        self.path.parent.mkdir(exist_ok=True)
        self.manifest={}
        manifest_path=self.path.parent/'index_manifest.json'
        if manifest_path.exists():
            self.manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
            self.path=self.path.parent/self.manifest['database']
        if not self.path.exists():
            shutil.copytree(self.source_db, self.path)
        torch.set_num_threads(4)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path, local_files_only=True)
        self.model = AutoModel.from_pretrained(self.model_path, local_files_only=True).eval()
        self.client = MilvusClient(uri=str(self.path))
        self.collection = 'bge_after'
        self.client.load_collection(collection_name=self.collection)
        source = next(ROOT.glob('medical*.json'))
        self.records = [json.loads(x) for x in source.read_text(encoding='utf-8').splitlines() if x.strip()]
        self.by_id = {r['_id']['$oid']: r for r in self.records}
        self.numeric_ids={r['_id']['$oid']:index for index,r in enumerate(self.records)}
        self.keyword=KeywordIndex(self.records)
        self.documents=DocumentStore()
        self.count = self.client.get_collection_stats(self.collection)['row_count']
        self.dimension = self.model.config.hidden_size
        assert self.count == len(self.records) == 8808 and self.dimension == 512

    def search(self, query, k=5, threshold=0.35):
        start = time.perf_counter()
        if not query.strip() or not 1<=k<=50 or not 0<=threshold<=1: raise ValueError('检索参数不正确')
        key = (query, k, threshold,self.documents.revision())
        with self.lock:
            if key in self.cache and time.monotonic() - self.cache[key][0] < 300:
                value = copy.deepcopy(self.cache[key][1])
                value.update(cache_hit=True, latency_ms=(time.perf_counter()-start)*1000)
                return value
            with torch.inference_mode():
                tokens = self.tokenizer(['为这个句子生成表示以用于检索相关文章：'+query], return_tensors='pt', truncation=True, max_length=64)
                vector = F.normalize(self.model(**tokens).last_hidden_state[:, 0], p=2, dim=1)[0].tolist()
            hits = self.client.search(collection_name=self.collection, data=[vector], limit=min(50,max(20,k*4)), output_fields=['doc_id','name'], search_params={'metric_type':'COSINE'})[0]
            keyword_ids=self.keyword.search(query,20)
            found={h['entity']['doc_id'] for h in hits}
            extra=[self.numeric_ids[key] for key in keyword_ids if key not in found]
            if extra:
                for row in self.client.get(collection_name=self.collection,ids=extra,output_fields=['vector','doc_id','name']):
                    similarity=sum(float(a)*float(b) for a,b in zip(vector,row['vector']))
                    hits.append(dict(entity=row,distance=similarity))
            results = []
            for h in hits:
                if h['distance'] < threshold:
                    continue
                entity = h['entity']; r = self.by_id[entity['doc_id']]
                results.append(dict(doc_id=entity['doc_id'], name=r['name'], score=float(h['distance']), symptoms=r.get('symptom', []), content=r.get('desc',''), source='medical.json'))
            results.extend(self.documents.search(vector,min(20,k*4),threshold))
            results.sort(key=lambda item:item['score'],reverse=True)
            by_id={item['doc_id']:item for item in results}
            order=fuse(list(by_id),[key for key in keyword_ids if key in by_id],[key for key in self.documents.keyword_ids(query) if key in by_id])
            results=[by_id[key] for key in order[:k]]
            value = dict(evidences=results, cache_hit=False, latency_ms=(time.perf_counter()-start)*1000,method='向量 + BM25 + RRF',candidates=len(by_id))
            self.cache[key] = (time.monotonic(), copy.deepcopy(value))
            self.cache.move_to_end(key)
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
            return value

    def embed_texts(self,texts):
        with self.lock,torch.inference_mode():
            inputs=self.tokenizer(texts,return_tensors='pt',padding=True,truncation=True,max_length=512)
            return F.normalize(self.model(**inputs).last_hidden_state[:,0],p=2,dim=1).cpu().tolist()

    def info(self):
        return dict(records=self.count, dimension=self.dimension, collection=self.collection, model=str(self.model_path), indexed_at=self.manifest.get('indexed_at'),model_sha256=self.manifest.get('model_sha256'))
