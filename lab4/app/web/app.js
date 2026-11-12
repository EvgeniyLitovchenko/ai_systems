const $ = id => document.getElementById(id);
let cards = [];
const sample = 'Квантизація — це зменшення точності числового представлення ваг нейромережі.\nМодель із 4 мільярдами параметрів у FP16 потребує приблизно 8 GB для зберігання ваг.\nKV-кеш зберігає ключі та значення попередніх токенів, щоб не обчислювати їх повторно.\nЗі збільшенням довжини контексту KV-кеш займає більше пам’яті.\nOllama запускає мовні моделі локально та надає OpenAI-сумісний HTTP API.';
function updateCounter() { $('counter').textContent = `${$('source').value.length} / 3000`; }
function status(message, kind = '') { $('status').textContent = message; $('status').className = kind; }
$('source').addEventListener('input', updateCounter);
$('sample').addEventListener('click', () => { $('source').value = sample; updateCounter(); });
$('file').addEventListener('change', async () => {
  const file = $('file').files[0]; if (!file) return;
  try {
    if (file.size > 16000) throw new Error('Файл завеликий. Виберіть фрагмент до 3000 символів.');
    const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
    if (text.length > 3000) throw new Error('Текст перевищує 3000 символів. Виберіть коротший фрагмент.');
    $('source').value = text; updateCounter(); status(`Відкрито ${file.name}`);
  } catch(error) { status(error.message, 'error'); }
  $('file').value = '';
});
function render() {
  $('cards').replaceChildren(); $('card-count').textContent = `${cards.length} карток`;
  for (const [i, card] of cards.entries()) {
    const article = document.createElement('article'); article.className = 'card';
    for (const [tag, text] of [['h3', `${i+1}. ${card.question}`], ['p', card.answer], ['blockquote', `Джерело: «${card.evidence}»`]]) {
      const node = document.createElement(tag); node.textContent = text; article.append(node);
    }
    $('cards').append(article);
  }
  if (!cards.length) { const p = document.createElement('p'); p.textContent = 'У тексті немає достатньо навчальних фактів.'; $('cards').append(p); }
  $('json').disabled = $('csv').disabled = !cards.length;
}
$('generate').addEventListener('click', async () => {
  const text = $('source').value; cards = []; $('cards').replaceChildren();
  $('card-count').textContent = '0 карток'; $('json').disabled = $('csv').disabled = true;
  if (text.trim().length < 30) { status('Введіть навчальний текст завдовжки щонайменше 30 символів.', 'error'); return; }
  $('generate').disabled = true; status('Модель створює картки… Зачекайте.', 'busy');
  try {
    const response = await fetch('/generate', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({text, count:Number($('count').value), model:$('model').value}), signal:AbortSignal.timeout(185000) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Помилка HTTP ${response.status}`);
    cards = result.cards; render(); status(`Створено ${cards.length} карток за ${result.seconds.toFixed(1)} с. Цитати перевірено.`);
  } catch(error) {
    status(error.name === 'TimeoutError' ? 'Час очікування вичерпано. Спробуйте коротший текст.' : error.message === 'Failed to fetch' ? 'Немає зв’язку з локальним сервером. Запустіть python app.py.' : error.message, 'error');
  } finally { $('generate').disabled = false; }
});
function download(text, ext, mime) {
  const url = URL.createObjectURL(new Blob([text], {type:mime})); const a = document.createElement('a');
  a.href = url; a.download = `qa_cards.${ext}`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('json').addEventListener('click', () => download(JSON.stringify({cards}, null, 2), 'json', 'application/json'));
$('csv').addEventListener('click', () => {
  const fields = ['question','answer','evidence']; const quote = s => '"' + s.replaceAll('"','""') + '"';
  download('\uFEFF' + [fields.join(','), ...cards.map(c => fields.map(k => quote(c[k])).join(','))].join('\r\n'), 'csv', 'text/csv;charset=utf-8');
});
