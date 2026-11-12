"""Question 13: fp16 4B perplexity on original and shuffled Ukrainian text."""
import json
from pathlib import Path
import random
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

ROOT = Path(__file__).resolve().parents[1]
notebook = ROOT/'local_models_demo.ipynb'
if not notebook.exists():
    notebook = ROOT.parents[1]/'4'/'local_models_demo (1).ipynb'
nb = json.loads(notebook.read_text(encoding='utf-8'))
data = {}
exec(''.join(nb['cells'][33]['source']), data)
model_id = 'Qwen/Qwen3-4B-Instruct-2507'
tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.float16, device_map='cuda', local_files_only=True)
model.eval()
words = data['PPL_TEXT']['Українська'].split()
random.Random(42).shuffle(words)
texts = {'original': data['PPL_TEXT']['Українська'], 'shuffled': ' '.join(words)}
result = {'model':model_id,'dtype':'fp16','seed':42,'gpu':torch.cuda.get_device_name(),'parameters':sum(p.numel() for p in model.parameters()),'texts':texts,'ppl':{}}
for name,text in texts.items():
    ids = tokenizer(text,return_tensors='pt').input_ids.to('cuda')
    with torch.inference_mode():
        result['ppl'][name] = float(torch.exp(model(ids,labels=ids).loss))
(ROOT/'results'/'noise_ppl.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(result['ppl'],flush=True)
