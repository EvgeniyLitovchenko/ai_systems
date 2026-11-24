"""Deterministic invariants for aggregation and catalog arithmetic. No LLM/network."""
import unittest,copy,json
from unittest.mock import patch
from core import aggregate,AppError
from stores import estimate,package_amount,match_score

def ing(name,q,unit='г',**kw):
 return {'name':name,'query':name,'quantity_min':q,'quantity_max':q,'unit':unit,'source_quote':name,'excluded':False,**kw}
def recipe(items,rid='r1'):return {'id':rid,'title':rid,'ingredients':items}
class Invariants(unittest.TestCase):
 def test_units_merge(self):
  rows=aggregate([recipe([ing('борошно',.5,'кг')]),recipe([ing('борошно',250)],'r2')])
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['quantity_max'],750)
 def test_unknown_never_invented(self):
  rows=aggregate([recipe([ing('капуста',1200)]),recipe([ing('капуста',None,'')],'r2')])
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['quantity_max'],1200);self.assertTrue(rows[0]['unknown_quantity'])
 def test_no_piece_mass_conversion(self):
  rows=aggregate([recipe([ing('морква',2,'шт'),ing('морква',100,'г')])]);self.assertEqual(len(rows),2)
 def test_onion_and_oil_aliases(self):
  rows=aggregate([recipe([ing('цибуля ріпчаста середня',2,'шт'),ing('цибуля ріпчаста',1,'шт')])]);self.assertEqual(rows[0]['quantity_max'],3)
 def test_optional_excluded(self):
  rows=aggregate([recipe([ing('кріп',None,'',excluded=True)])]);self.assertTrue(rows[0]['excluded']);self.assertTrue(rows[0]['unknown_quantity'])
 def test_serving_multiplier(self):
  rows=aggregate([recipe([ing('борошно',500)])],{'r1':.5});self.assertEqual(rows[0]['quantity_max'],250)
 def test_invalid_multiplier(self):
  with self.assertRaises(AppError):aggregate([recipe([ing('борошно',500)])],{'r1':float('nan')})
 def test_package_parsing(self):
  self.assertEqual(package_amount('Борошно 1,8 кг пшеничне'),(1800,'г'));self.assertEqual(package_amount('Молоко 2.5% 900 мл'),(900,'мл'));self.assertEqual(package_amount('Яйця 10 шт.'),(10,'шт'))
 def test_whole_package_cost(self):
  row={'quantity_min':200,'quantity_max':200,'unit':'г'}
  p={'package_quantity':180,'package_unit':'г','weighted':False,'price':59.9,'stock':10}
  self.assertEqual(estimate(row,p)['purchase_cost'],119.8)
 def test_weighted_price_not_100g(self):
  row={'quantity_min':1200,'quantity_max':1200,'unit':'г'}
  p={'package_quantity':1000,'package_unit':'г','weighted':True,'price':15.99,'step':.1,'price_unit':'кг','stock':20}
  self.assertEqual(estimate(row,p)['purchase_cost'],19.19)
 def test_mismatch_does_not_price(self):
  p={'package_quantity':1000,'package_unit':'г','weighted':True,'price':15.99,'step':.1,'price_unit':'кг'}
  self.assertIsNone(estimate({'quantity_max':2,'unit':'шт'},p)['purchase_cost'])
 def test_unknown_total_not_priced(self):
  p={'package_quantity':1000,'package_unit':'г','weighted':False,'price':20}
  self.assertIsNone(estimate({'quantity_min':500,'quantity_max':500,'unit':'г','unknown_quantity':True},p)['purchase_cost'])
 def test_ready_food_rejected(self):
  self.assertEqual(match_score('капуста','Салат з капусти'),0)
 def test_oil_is_not_chocolate(self):
  self.assertEqual(match_score('олія оливкова','Шоколад молочний Kit Kat начинка зі смаком тіста для печива'),0)
 def test_prepared_food_rejected(self):
  self.assertEqual(match_score('томатний соус','Квасоля Верес в томатному соусі'),0)
  self.assertEqual(match_score('копчена паприка','Хумус Hungry Papa з копченою паприкою'),0)
  self.assertEqual(match_score('італійські трави','Гріссіні з сумішшю італійських трав'),0)
 def test_fresh_mushroom(self):
  self.assertEqual(match_score('печериці','Печериці мариновані'),0)
 def test_categories(self):
  from core import category
  self.assertEqual(category('борошно'),'Бакалія');self.assertEqual(category('моцарела'),'Молочні продукти та яйця')
 def test_estimated_piece_count_preserved(self):
  from core import suggest
  row={'id':'p','name':'картопля','quantity_min':3,'quantity_max':5,'unit':'шт'}
  output={'suggestions':[{'id':'p','quantity_min':100,'quantity_max':200,'unit':'г','basis':'per_unit','reason':'Маса однієї картоплини.'}]}
  with patch('core.call_model',return_value=(json.dumps(output),{'seconds':1})):
   result=suggest([row],'3–5 картоплин')['suggestions'][0]
  self.assertEqual((result['quantity_min'],result['quantity_max']),(300,1000))
 def test_wrong_estimate_basis_rejected(self):
  from core import suggest
  row={'id':'p','name':'картопля','quantity_min':3,'quantity_max':5,'unit':'шт'}
  output={'suggestions':[{'id':'p','quantity_min':4,'quantity_max':6,'unit':'г','basis':'total','reason':'Wrong basis'}]}
  with patch('core.call_model',return_value=(json.dumps(output),{'seconds':1})):
   self.assertEqual(suggest([row],'3–5 картоплин')['suggestions'],[])
 def test_duplicate_chat_uses_actual_list(self):
  from core import answer
  context={'shopping':[{'name':'моцарела','quantity_min':200,'quantity_max':200,'unit':'г','notes':['Повторений рядок: перевірте.']}]}
  with patch('core.call_model',side_effect=AssertionError('Direct fact must use verified data')):
   r=answer([{'role':'user','content':'Чи купувати 400 г моцарели, якщо двічі написано 200 г?'}],context)
  self.assertIn('200 г',r['answer']);self.assertIn('не слід',r['answer'])
 def test_budget_draft_does_not_change_recipe(self):
  row={'name':'картопля','quantity_min':3,'quantity_max':5,'unit':'шт','budget_estimate':{'quantity_min':450,'quantity_max':1250,'unit':'г'}}
  p={'package_quantity':1000,'package_unit':'г','weighted':True,'price':14.49,'step':.1,'price_unit':'кг','stock':100}
  result=estimate(row,p)
  self.assertEqual(result['purchase_cost'],18.84);self.assertTrue(result['approximate'])
  self.assertEqual((row['quantity_min'],row['quantity_max'],row['unit']),(3,5,'шт'))
 def test_unknown_pantry_one_pack_is_explicit(self):
  row={'name':'сіль','quantity_min':None,'quantity_max':None,'unit':'','unknown_quantity':True}
  p={'package_quantity':1000,'package_unit':'г','weighted':False,'price':20.9,'stock':100}
  result=estimate(row,p)
  self.assertEqual(result['purchase_cost'],20.9);self.assertTrue(result['approximate']);self.assertIn('попередньо',result['purchase_label'])
  self.assertIsNone(row['quantity_max'])
 def test_fresh_ribs_rank_before_more_expensive_frozen(self):
  import stores
  def mocked(store,*args,**kwargs):
   return {'store':store,'products':[{'id':'frozen','match_score':1.17,'name':'Реберця свинячі заморожені','price':454.41,'price_unit':'кг','weighted':True,'package_quantity':1000,'package_unit':'г','step':.1,'stock':20},
    {'id':'fresh','match_score':1.0,'name':'Свинячі ребра охолоджені','price':254,'price_unit':'кг','weighted':True,'package_quantity':1000,'package_unit':'г','step':.1,'stock':3}]}
  row={'id':'r','name':'ребра свинячі','quantity_min':5,'quantity_max':10,'unit':'шт'}
  with patch('stores.search',side_effect=mocked):result=stores.compare([row])
  self.assertEqual(result['items']['r']['silpo']['products'][0]['id'],'fresh')
 def test_partial_unknown_adds_known_floor(self):
  from core import suggest
  row={'id':'c','name':'капуста','quantity_min':1200,'quantity_max':1200,'unit':'г','unknown_quantity':True}
  output={'suggestions':[{'id':'c','quantity_min':300,'quantity_max':500,'unit':'г','basis':'missing_part','reason':'Додаткова капуста для борщу.'}]}
  with patch('core.call_model',return_value=(json.dumps(output),{'seconds':1})):
   result=suggest([row],'1200 г + капуста без кількості')['suggestions'][0]
  self.assertEqual((result['quantity_min'],result['quantity_max']),(1500,1700))
 def test_stock_insufficient(self):
  p={'package_quantity':180,'package_unit':'г','weighted':False,'price':59.9,'stock':1}
  self.assertIsNone(estimate({'quantity_min':200,'quantity_max':200,'unit':'г'},p)['purchase_cost'])
if __name__=='__main__':unittest.main(verbosity=2)
