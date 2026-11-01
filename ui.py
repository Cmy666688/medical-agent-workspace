import os
import json
from pathlib import Path
from dataclasses import replace
import streamlit as st
from agents.coordinator import LLMConfig

@st.cache_resource(show_spinner=False)
def retrieval():
    from agents.retrieval import RetrievalService
    return RetrievalService()

@st.cache_resource(show_spinner=False)
def document_jobs():
    from agents.documents import IndexJobs
    return IndexJobs(retrieval)


def index_info():
    """Read published index metadata without loading the model or vector engine."""
    root=Path(os.getenv('MEDICAL_RUNTIME_DIR',str(Path(__file__).resolve().parent/'runtime')))
    manifest=root/'index_manifest.json'
    if not manifest.exists(): return None
    stat=manifest.stat()
    return _index_info(str(manifest),stat.st_mtime_ns,stat.st_size)


@st.cache_data(max_entries=8,show_spinner=False)
def _index_info(path,modified,size):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    return {key:data.get(key) for key in ('records','dimension','collection','indexed_at','model_sha256')}

def llm_config():
    from api_config import configured_values
    values=configured_values()
    for key in LLMConfig.__dataclass_fields__:
        state_key={'model':'llm_model','budget_tokens':'budget'}.get(key,key)
        if state_key in st.session_state: values[key]=st.session_state[state_key]
    return LLMConfig(**values)

def evidence_cards(evidences):
    for i,r in enumerate(evidences,1):
        with st.expander(f"[{i}] {r['name']} · 相关性 {r['score']:.3f}",icon=':material/article:'):
            st.caption(f"来源：{r['source']} · 记录 ID：{r['doc_id']}")
            st.write('症状：'+'、'.join(r['symptoms']))
            st.write(r['content'])
