"""Produce supporting artifacts from real outputs and screenshots."""
from pathlib import Path
import json
import subprocess
import sys
import hashlib
import urllib.request
from sacrebleu.metrics import BLEU, CHRF
from PIL import Image, ImageOps, ImageDraw, ImageFont
import imageio.v2 as imageio
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
results = ROOT/'results'
ref = 'Зустріч перенесли на четвер на третю годину.'
hyp = 'Зустріч перенесли на четвер, о 15 годин.'
metrics = {'reference':ref, 'hypothesis':hyp,
    'bleu':BLEU(effective_order=True).sentence_score(hyp,[ref]).score,
    'chrf':CHRF().sentence_score(hyp,[ref]).score}
(results/'translation_metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
tests = subprocess.run([sys.executable,str(ROOT/'app'/'test_app.py')], capture_output=True, text=True,encoding='utf-8')
(results/'test_results.txt').write_text(tests.stdout+tests.stderr,encoding='utf-8')
if tests.returncode:
    raise RuntimeError('Contract tests failed')
metadata = {}
for label in ['q8','q4']:
    payload = json.dumps({'model':'lab4-qa-'+label}).encode()
    req = urllib.request.Request('http://127.0.0.1:11434/api/show',payload,{'Content-Type':'application/json'})
    with urllib.request.urlopen(req) as response:
        metadata[label] = json.load(response)
    metadata[label].pop('template',None)
    # /api/show returns the tokenizer vocabulary as empty arrays by default.
(results/'model_metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
source = ROOT.parents[1]/'4'/'методичні'
provenance = {}
for original, copied in [(source/'bench.py',ROOT/'app'/'bench.py'),
                         (source/'web'/'client.js',ROOT/'app'/'web'/'client.js'),
                         (source/'web'/'style.css',ROOT/'app'/'web'/'style.css')]:
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in [original,copied]]
    if hashes[0] != hashes[1]:
        raise RuntimeError('Method file differs: '+copied.name)
    provenance[copied.name] = {'sha256':hashes[0], 'unchanged':True}
provenance['bench.html'] = {'changes':'navigation link, initial local proxy URL, initial Q8 model only; measurement code unchanged'}
(results/'method_provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
shots = ['01-empty.jpg','02-input.jpg','03-cards.jpg','04-bench.jpg','05-empty-error.jpg','03-cards.jpg']
labels = ['1. Vebzastosunok','2. Navchalnyi tekst','3. Stvoreni kartky Q8','4. Bench iz metodychnykh','5. Perevirka porozhnoho vvodu','6. Rezultat']
# A clearly labelled step-by-step video made from actual UI screenshots.
with imageio.get_writer(str(ROOT/'demo'/'demo.mp4'),fps=1,codec='libx264',quality=8,macro_block_size=16) as writer:
    for shot,label in zip(shots,labels):
        with Image.open(ROOT/'demo'/shot) as im:
            frame = Image.new('RGB',(1280,1440),'#eef1ec')
            scaled = ImageOps.contain(im.convert('RGB'),(1240,1340))
            frame.paste(scaled,((1280-scaled.width)//2,75))
            draw = ImageDraw.Draw(frame)
            draw.text((24,18),'LAB 4 | Step-by-step demo from actual browser screenshots',fill='#245c49')
            draw.text((24,42),label,fill='#245c49')
            for _ in range(3):
                writer.append_data(np.asarray(frame))
(ROOT/'demo'/'README.md').write_text('''# Демонстрація

`demo.mp4` — покадрова відеодемонстрація з реальних знімків браузерної перевірки, 18 секунд. Це змонтована послідовність станів, не безперервний запис екрана.

1. Початкова сторінка.
2. Навчальний текст із кнопки «Спробувати приклад».
3. Чотири картки Q8 із перевіреними цитатами.
4. Оригінальний вебbench: `web-check`, 2 запити, 1 клієнт, 64 токени, 0 помилок.
5. Зрозуміла помилка порожнього вводу.

`qa_cards.json` завантажено кнопкою вебзастосунку. Основні вимірювання before/after містяться в `../bench_results.csv`; короткий браузерний запуск — у `../results/web_bench_check.csv`.
''',encoding='utf-8')
print('Tests OK; copied methods verified; video and metrics written.')
