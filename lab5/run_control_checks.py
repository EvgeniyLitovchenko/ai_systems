from pathlib import Path
import os, json, time
ROOT=Path(__file__).resolve().parent
os.environ['HF_HOME']=str(ROOT/'.cache'/'huggingface')
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'
import torch, pandas as pd, numpy as np
from torch.utils.data import Dataset
from sklearn.metrics import accuracy_score, f1_score
from transformers import AutoTokenizer, AutoModelForSequenceClassification, DataCollatorWithPadding, Trainer, TrainingArguments, set_seed
set_seed(42)
torch.set_num_threads(8)
revision=(ROOT/'results'/'model_revision.txt').read_text().strip()
tokenizer=AutoTokenizer.from_pretrained('google-bert/bert-base-uncased',revision=revision)
frames={}
for split in ['train','validation']:
 path=ROOT/'.cache'/f'mrpc_{split}.parquet'
 if not path.exists():
  import urllib.request
  urllib.request.urlretrieve(f'https://huggingface.co/datasets/nyu-mll/glue/resolve/main/mrpc/{split}-00000-of-00001.parquet',path)
 frames[split]=pd.read_parquet(path)
class PairDataset(Dataset):
 def __init__(self,frame):
  self.inputs=tokenizer(frame.sentence1.tolist(),frame.sentence2.tolist(),truncation=True)
  self.labels=frame.label.tolist()
 def __len__(self):return len(self.labels)
 def __getitem__(self,i):return {**{k:v[i] for k,v in self.inputs.items()},'labels':self.labels[i]}
model=AutoModelForSequenceClassification.from_pretrained('google-bert/bert-base-uncased',revision=revision,num_labels=2).cuda()
args=TrainingArguments(output_dir=str(ROOT/'.checkpoints'/'mrpc_controls'),num_train_epochs=6,learning_rate=2e-5,
 per_device_train_batch_size=16,per_device_eval_batch_size=64,eval_strategy='epoch',save_strategy='no',
 logging_steps=50,fp16=True,report_to='none',seed=42,disable_tqdm=True)
def metrics(output):
 y=output.label_ids;p=output.predictions.argmax(-1)
 return {'accuracy':accuracy_score(y,p),'f1':f1_score(y,p)}
trainer=Trainer(model=model,args=args,train_dataset=PairDataset(frames['train']),eval_dataset=PairDataset(frames['validation']),
 data_collator=DataCollatorWithPadding(tokenizer=tokenizer),processing_class=tokenizer,compute_metrics=metrics)
torch.cuda.synchronize();start=time.perf_counter()
trainer.train()
torch.cuda.synchronize();seconds=time.perf_counter()-start
history=[x for x in trainer.state.log_history if 'eval_loss' in x]
pairs=[('The lecture starts at nine.','The class begins at 9 a.m.',1),
 ('He sold his old bike.','He bought a new bicycle.',0),
 ('The meeting was cancelled.','The meeting will not take place.',1),
 ('The shop opens on Sunday.','The shop is closed on Sunday.',0)]
model.eval();checks=[]
for a,b,expected in pairs:
 with torch.inference_mode():
  prob=model(**tokenizer(a,b,return_tensors='pt').to('cuda')).logits.softmax(-1)[0,1].item()
 checks.append({'sentence1':a,'sentence2':b,'expected':expected,'predicted':int(prob>0.5),'probability_paraphrase':prob})
result={'dataset':'MRPC','epochs':6,'seconds':seconds,'gpu':torch.cuda.get_device_name(0),'validation_history':history,'own_pairs':checks}
(ROOT/'results'/'control_mrpc.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
pd.DataFrame(history).to_csv(ROOT/'results'/'control_mrpc_epochs.csv',index=False)
print(json.dumps(result,ensure_ascii=False,indent=2))
