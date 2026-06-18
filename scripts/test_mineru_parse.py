#!/usr/bin/env python3
"""Test MinerU do_parse with hgnet_v2 patch."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
import scripts.mineru_patch  # noqa

from mineru.cli.common import do_parse
import os

if __name__ == '__main__':
    output_dir = '/tmp/mineru_final_test'
    os.makedirs(output_dir, exist_ok=True)

    print('Starting do_parse with pipeline backend...')
    result = do_parse(
        output_dir=output_dir,
        pdf_file_names=['attention'],
        pdf_bytes_list=[open('/tmp/attention.pdf', 'rb').read()],
        p_lang_list=['en'],
        backend='pipeline',
        parse_method='txt',
        formula_enable=True,
        table_enable=True,
        return_md=True,
        return_images=False,
    )
    print(f'Done! Result type: {type(result)}')
    if isinstance(result, dict):
        md = result.get('md_content', '')
        if isinstance(md, dict):
            md = list(md.values())[0] if md else ''
        print(f'Markdown: {len(md)} chars')
        print(md[:500])
    else:
        print(str(result)[:300])
