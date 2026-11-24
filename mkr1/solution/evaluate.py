"""Reproducible technical evaluation on user-provided recipe texts; not manual-time evidence."""
from pathlib import Path
import requests,json,time,re,sys
ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'evidence'/'technical'
CASES={
 'borscht':{'expected':['реб','картопл','буряк','моркв','цибул','капуст','олія','сіль','кетчуп','лавр','перець'],
            'optional':['часник','сало','хліб']},
 'cabbage':{'expected':['капуст','стег','моркв','цибул','часник','паприк','перець','сіль','олія'],
            'optional':['кріп']},
 'pizza':{'expected':['борошн','вод','дріждж','цук','сіль','олія','томат','моцарел','шинк','печер','трав'], 'optional':[]}}

def call(path,data):
 r=requests.post('http://127.0.0.1:8765/api/'+path,json=data,headers={'X-Usage-Origin':'technical'},timeout=300)
 if not r.ok:raise RuntimeError(r.text)
 return r.json()
summary=[];all_recipes=[]
for case,reference in CASES.items():
 text=(ROOT/'evidence'/'usage'/f'recipe_{case}.txt').read_text(encoding='utf-8-sig')
 result=call('extract',{'text':text})
 (OUT/f'extract_{case}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 items=[i for r in result['recipes'] for i in r['ingredients']]
 names=[i['name'].casefold() for i in items]
 matched=[x for x in reference['expected'] if any(x in n for n in names)]
 opt=[x for x in reference['optional'] if any(x in n for n in names)]
 unexpected=[n for n in names if not any(x in n for x in reference['expected']+reference['optional']+['вод'])]
 # Name-level recall uses manually enumerated reference concepts. Quantities are checked separately.
 entry={'case':case,'seconds':result['usage']['seconds'],'expected_main':len(reference['expected']),
   'found_main':len(matched),'missing_main':list(set(reference['expected'])-set(matched)),
   'optional_expected':len(reference['optional']),'optional_found':len(opt),'unexpected_names':unexpected,
   'ingredients':len(items),'source_quotes_verified':True,'model':result['usage']['model'],
   'input_tokens':result['usage']['prompt_tokens'],'output_tokens':result['usage']['output_tokens']}
 if case=='pizza':
  mozzarella=[x for x in items if 'моцарел' in x['name'].casefold()]
  entry['duplicate_mozzarella_handled']=len(mozzarella)==1 and mozzarella[0]['quantity_max']==200 and mozzarella[0]['needs_review']
  entry['servings_correct']=result['recipes'][0]['servings']==4
 if case=='cabbage':
  paprika=next((x for x in items if 'паприк' in x['name'].casefold()),{})
  entry['paprika_quantity_correct']=paprika.get('quantity_min')==paprika.get('quantity_max')==1
 if case=='borscht':
  ribs=next((x for x in items if 'реб' in x['name'].casefold()),{})
  entry['range_correct']=ribs.get('quantity_min')==5 and ribs.get('quantity_max')==10
  entry['no_cookware']=not any('кастр' in n for n in names)
  entry['unknown_cabbage_preserved']=next((x for x in items if 'капуст' in x['name'].casefold()),{}).get('quantity_min') is None
 summary.append(entry)
 for recipe in result['recipes']:
  recipe['id']=case+'-'+recipe['id']
  all_recipes.append(recipe)
 print(json.dumps(entry,ensure_ascii=False),flush=True)
merged=call('aggregate',{'recipes':all_recipes})['shopping']
(OUT/'reference_inventory.json').write_text(json.dumps(CASES,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'extraction_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'merged_shopping.json').write_text(json.dumps(merged,ensure_ascii=False,indent=2),encoding='utf-8')
prices=call('prices',{'ingredients':merged})
(OUT/'all_prices.json').write_text(json.dumps(prices,ensure_ascii=False,indent=2),encoding='utf-8')
price_stats={store:{'searched':len(prices['items']),'found':sum(bool(v.get(store,{}).get('products')) for v in prices['items'].values()),
 'unavailable':sum(v.get(store,{}).get('status')=='unavailable' for v in prices['items'].values())} for store in ['atb','silpo']}
(OUT/'price_summary.json').write_text(json.dumps(price_stats,ensure_ascii=False,indent=2),encoding='utf-8')
print('PRICE SUMMARY',json.dumps(price_stats,ensure_ascii=False),flush=True)
