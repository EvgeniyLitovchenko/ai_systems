"""Build a captioned 80-second walkthrough from real browser captures."""
from pathlib import Path
import subprocess
import imageio_ffmpeg
ROOT=Path(__file__).resolve().parent.parent
FRAMES=ROOT/'evidence'/'technical'
scenes=[
 ('01-home.jpg',8,'Смак & Кошик — рецепти, список покупок і ціни','Локальні моделі. Каталоги АТБ та «Сільпо» у Житомирі.'),
 ('02-recipe-list.jpg',8,'Вставляю скопійований рецепт разом із кроками та порадами','Не потрібні спеціальний шаблон або ручне очищення тексту.'),
 ('04-duplicate-packages.jpg',10,'Повтор 200 г моцарели позначено для уточнення','200 г потребують двох упаковок по 180 г або однієї по 300 г.'),
 ('03-categories-prices.jpg',10,'Продукти згруповано за відділами магазину','Ціни мають посилання, фасування й час перевірки. Є вибір іншого товару.'),
 ('07-not-found.jpg',8,'Свинячі ребра в обраному АТБ не знайдені','Це пропуск у кошторисі, а не нульова ціна чи автоматична заміна.'),
 ('08-ai-amounts.jpg',10,'Для попереднього кошика AI оцінює штуки й невідомі кількості','Оцінки для кошторису відокремлені від оригіналу; їх можна переглянути й змінити.'),
 ('09-estimate-applied.jpg',8,'Усі знайдені товари тепер пораховані для попереднього кошика','Оригінальні кількості збережені. Пропуски магазинів перелічені біля суми.'),
 ('05-recipe-chat.jpg',10,'Чат про рецепт використовує поточний список','Повторений рядок не оголошується автоматично подвоєною кількістю.'),
 ('06-general-chat.jpg',8,'Є окремий звичайний чат без передачі рецептів','Історія списків локальна. API-оплата — 0 грн; електроенергія окремо не виміряна.')]
lines=['ffconcat version 1.0']
for file,duration,_,_ in scenes:
 assert (FRAMES/file).exists(),file
 lines.extend([f"file '{file}'",f'duration {duration}'])
lines.append(f"file '{scenes[-1][0]}'")
(FRAMES/'demo_frames.ffconcat').write_text('\n'.join(lines)+'\n',encoding='utf-8')
header='''[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 840
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Segoe UI,23,&H00FFFFFF,&H00FFFFFF,&H0017442D,&H0017442D,0,0,0,0,100,100,0,0,1,0,0,2,34,34,25,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
def at(seconds):return f'{seconds//3600}:{seconds%3600//60:02d}:{seconds%60:02d}.00'
elapsed=0;events=[]
for _,duration,title,caption in scenes:
 text='{\\b1}'+title+'{\\b0}\\N'+caption
 events.append(f'Dialogue: 0,{at(elapsed)},{at(elapsed+duration)},Default,,0,0,0,,{text}')
 elapsed+=duration
(FRAMES/'demo.ass').write_text(header+'\n'.join(events)+'\n',encoding='utf-8-sig')
cmd=[imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-y','-f','concat','-safe','0','-i','demo_frames.ffconcat',
 '-vf','scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:840:(ow-iw)/2:0:color=0x174c3c,setsar=1,subtitles=demo.ass',
 '-r','25','-t',str(elapsed),'-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-movflags','+faststart',
 '-metadata','title=Смак & Кошик — демонстрація МКР',str(ROOT/'demo.mp4')]
subprocess.run(cmd,cwd=FRAMES,check=True)
print('Created demo.mp4:',elapsed,'seconds',round((ROOT/'demo.mp4').stat().st_size/1024/1024,2),'MiB')
