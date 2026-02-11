#!/usr/bin/env python3
"""Check HuggingFace model cache and show how to use models offline."""

import os
import glob
from pathlib import Path

def check_cache():
    """Check what models are cached locally."""
    cache_dir = os.path.expanduser('~/.cache/huggingface/hub')
    print(f'HuggingFace cache directory: {cache_dir}')
    print(f'Exists: {os.path.exists(cache_dir)}\n')
    
    if not os.path.exists(cache_dir):
        print('No cache directory found.')
        return
    
    models = glob.glob(os.path.join(cache_dir, 'models--*'))
    print(f'Found {len(models)} cached models:\n')
    
    finbert_models = []
    for m in sorted(models):
        model_name = os.path.basename(m)
        # Convert models--ProsusAI--finbert to ProsusAI/finbert
        readable_name = model_name.replace('models--', '').replace('--', '/')
        print(f'  {readable_name}')
        
        if 'finbert' in model_name.lower():
            finbert_models.append((readable_name, m))
    
    if finbert_models:
        print(f'\n✅ Found {len(finbert_models)} FinBERT models:')
        for name, path in finbert_models:
            size_mb = sum(f.stat().st_size for f in Path(path).rglob('*') if f.is_file()) / (1024 * 1024)
            print(f'   {name} ({size_mb:.1f} MB)')
            print(f'   Path: {path}')
    else:
        print('\n❌ No FinBERT models found in cache')

def show_offline_usage():
    """Show how to use models offline."""
    print('\n' + '='*60)
    print('HOW TO USE FINBERT OFFLINE')
    print('='*60)
    
    print('''
1. Download models first (when online):
   
   python3 -c "from transformers import AutoTokenizer, AutoModelForSequenceClassification; \\
   AutoTokenizer.from_pretrained('ProsusAI/finbert'); \\
   AutoModelForSequenceClassification.from_pretrained('ProsusAI/finbert'); \\
   AutoTokenizer.from_pretrained('burakutf/finetuned-finbert-crypto'); \\
   AutoModelForSequenceClassification.from_pretrained('burakutf/finetuned-finbert-crypto')"

2. Use offline mode by setting environment variable:
   
   export TRANSFORMERS_OFFLINE=1
   
   Or in Python before importing transformers:
   
   import os
   os.environ['TRANSFORMERS_OFFLINE'] = '1'
   from transformers import AutoTokenizer, AutoModelForSequenceClassification

3. Use local_files_only parameter:
   
   tokenizer = AutoTokenizer.from_pretrained(
       'ProsusAI/finbert',
       local_files_only=True
   )
   model = AutoModelForSequenceClassification.from_pretrained(
       'ProsusAI/finbert', 
       local_files_only=True
   )

4. Or specify custom cache directory:
   
   cache_dir = "/path/to/models"
   tokenizer = AutoTokenizer.from_pretrained(
       'ProsusAI/finbert',
       cache_dir=cache_dir,
       local_files_only=True
   )
''')

if __name__ == '__main__':
    check_cache()
    show_offline_usage()
