"""Repeat section 2 on Qwen3-1.7B (CUDA, Quanto). See experiment requirements.
Data/prompts are copied from supplied demo; generic PyTorch unpack on Windows.
"""
import gc
import json
import random
import time
from pathlib import Path
from types import SimpleNamespace
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, QuantoConfig
from optimum.quanto.library.extensions import get_extension, is_extension_available
from optimum.quanto.tensor.weights.qbits import WeightQBitsTensor
from sacrebleu.metrics import BLEU, CHRF

ROOT = Path(__file__).resolve().parents[1]


def main():
    notebook = ROOT/'local_models_demo.ipynb'
    if not notebook.exists():
        notebook = ROOT.parents[1]/'4'/'local_models_demo (1).ipynb'
    nb = json.loads(notebook.read_text(encoding='utf-8'))
    data = {}
    exec(''.join(nb['cells'][33]['source']), data)  # fixed lecture datasets only
    def unpack(packed, bits):
        return torch.cat([(packed >> (bits * i)) & (2**bits-1) for i in range(8//bits)]).to(torch.uint8)
    if is_extension_available('quanto_cuda'):
        get_extension('quanto_cuda')._lib = SimpleNamespace(unpack=unpack)
    # Same generic affine quantization as T4 demo, without Windows CUDA JIT/AWQ.
    WeightQBitsTensor.create = staticmethod(lambda qt, axis, group_size, size, stride, packed, scale, shift, requires_grad=False:
        WeightQBitsTensor(qt, axis, group_size, size, stride, packed, scale, shift, requires_grad))
    model_id = 'Qwen/Qwen3-1.7B'
    tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
    records = {'model': model_id, 'gpu': torch.cuda.get_device_name(), 'capability': torch.cuda.get_device_capability(),
        'torch': torch.__version__, 'notes': 'fp16; generic Quanto unpack and QBits (no AWQ JIT); enable_thinking=False', 'variants': {}}
    saved = ROOT/'results'/'small_model.json'
    if saved.exists():
        records = json.loads(saved.read_text(encoding='utf-8'))
    for name in ['fp16', 'int8', 'int4', 'int2']:
        if name in records['variants']:
            continue
        gc.collect(); torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
        model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.float16, device_map='cuda',
            local_files_only=True, quantization_config=None if name=='fp16' else QuantoConfig(weights=name))
        model.eval()
        r = {'model_memory_gb': torch.cuda.memory_allocated()/1e9, 'parameters': 1720574976}
        def ppl(text):
            ids = tokenizer(text, return_tensors='pt').input_ids.to('cuda')
            with torch.no_grad():
                return float(torch.exp(model(ids, labels=ids).loss))
        r['ppl'] = {lang: ppl(text) for lang, text in data['PPL_TEXT'].items()}
        if name == 'fp16':
            words = data['PPL_TEXT']['Українська'].split()
            random.Random(42).shuffle(words)
            r['random_text'] = ' '.join(words)
            r['random_ppl'] = ppl(r['random_text'])
            r['parameters'] = sum(p.numel() for p in model.parameters())
        def gen(prompt, limit):
            text = tokenizer.apply_chat_template([{'role':'user','content':prompt}], tokenize=False, add_generation_prompt=True, enable_thinking=False)
            inputs = tokenizer(text, return_tensors='pt').to('cuda')
            torch.cuda.synchronize(); start = time.perf_counter()
            with torch.no_grad():
                output = model.generate(**inputs, max_new_tokens=limit, do_sample=False)
            torch.cuda.synchronize()
            seconds = time.perf_counter()-start
            ids = output[0,inputs.input_ids.shape[1]:]
            return dict(text=tokenizer.decode(ids, skip_special_tokens=True).strip(), tokens=len(ids), seconds=seconds)
        r['translations'] = [gen(data['TRANSLATE_PROMPT'].format(src),80)['text'] for src,_ in data['TRANSLATION']]
        refs = [[ref for _,ref in data['TRANSLATION']]]
        r['chrf'] = CHRF().corpus_score(r['translations'],refs).score
        r['bleu'] = BLEU().corpus_score(r['translations'],refs).score
        r['generations'] = [gen(p,200) for p in data['GEN_PROMPTS']]
        r['tokens_per_s'] = sum(x['tokens'] for x in r['generations'])/sum(x['seconds'] for x in r['generations'])
        r['peak_vram_gb'] = torch.cuda.max_memory_allocated()/1e9
        records['variants'][name] = r
        (ROOT/'results'/'small_model.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(name, r['ppl'], r['chrf'],r['bleu'], flush=True)
        del model
        gc.collect(); torch.cuda.empty_cache()


if __name__ == '__main__':
    main()
