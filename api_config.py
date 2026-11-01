"""File configuration: session overrides > environment > private TOML > defaults."""
import os,tomllib
from pathlib import Path
from dataclasses import fields
from agents.llm import LLMConfig

ROOT=Path(__file__).resolve().parent

def file_config():
    path=Path(os.getenv('MEDICAL_API_CONFIG',str(ROOT/'config/api.local.toml')))
    if not path.exists(): return {}
    try:
        with path.open('rb') as stream: data=tomllib.load(stream)
    except tomllib.TOMLDecodeError:
        raise ValueError('API 配置文件格式错误，请按 api.example.toml 保留引号和字段格式。') from None
    values=data.get('llm',{})
    allowed={item.name for item in fields(LLMConfig)}
    return {key:value for key,value in values.items() if key in allowed}

def configured_values():
    values=file_config()
    env={'base_url':'MEDICAL_LLM_BASE_URL','model':'MEDICAL_LLM_MODEL','api_key':'MEDICAL_LLM_API_KEY',
         'fallback_url':'MEDICAL_LLM_FALLBACK_URL','fallback_model':'MEDICAL_LLM_FALLBACK_MODEL','fallback_key':'MEDICAL_LLM_FALLBACK_KEY',
         'vision_model':'MEDICAL_VISION_MODEL','vision_url':'MEDICAL_VISION_BASE_URL','vision_key':'MEDICAL_VISION_API_KEY'}
    for key,name in env.items():
        if name in os.environ: values[key]=os.environ[name]
    return values
