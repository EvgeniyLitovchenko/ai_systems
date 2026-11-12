"""Collect actual Base/Thinking/tokenization experiments for questions 1,7,9."""
import json
from pathlib import Path
import time
import urllib.request
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]


def call(path, body):
    req = urllib.request.Request('http://127.0.0.1:11434' + path,
        json.dumps(body).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def main():
    data = {}
    prompt = 'Запитання: Яка столиця Італії?\nВідповідь: Рим.\n\nЗапитання: Яка столиця Німеччини?\nВідповідь: Берлін.\n\nЗапитання: Яка столиця Франції?\nВідповідь:'
    data['base'] = dict(prompt=prompt, result=call('/api/generate', {
        'model': 'hf.co/mradermacher/Qwen3-1.7B-Base-GGUF:Q4_K_M', 'prompt': prompt,
        'raw': True, 'stream': False, 'options': {'temperature': 0, 'seed': 1, 'num_predict': 40, 'stop': ['\n']}}))
    prompts = [
        'Що більше: 9.11 чи 9.9? Відповідай коротко.',
        'У слові «трансформер» скільки літер «р»? Відповідай лише числом.',
        'П’ять машин виготовляють п’ять деталей за п’ять хвилин. За скільки хвилин сто машин виготовлять сто деталей? Відповідай коротко.',
        'У коробці 17 червоних і 23 синіх кульки. Яку найменшу кількість кульок треба витягти навмання без повернення, щоб гарантовано мати хоча б 3 червоні та 4 сині? Відповідай числом.',
        'Обчисли 17 * 23 - 19 * 21. Відповідай числом.',
        'У черзі Анна стоїть п’ятою з початку і восьмою з кінця. Скільки людей у черзі? Відповідай числом.',
    ]
    data['thinking'] = []
    for prompt in prompts:
        pair = {'prompt': prompt}
        for think in [False, True]:
            result = call('/api/chat', {'model': 'qwen3:1.7b', 'messages': [{'role': 'user', 'content': prompt}],
                'think': think, 'stream': False, 'options': {'temperature': 0, 'seed': 1, 'num_predict': 4096, 'num_ctx': 8192}})
            pair[str(think)] = result
            print(prompt, think, result['message']['content'], result.get('eval_count'), flush=True)
        data['thinking'].append(pair)
        (ROOT / 'results' / 'extra_experiments.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
