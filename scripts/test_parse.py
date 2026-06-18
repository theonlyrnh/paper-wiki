"""Test MinerU parsing with hgnet_v2 patch."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Apply hgnet_v2 patch before importing mineru
import scripts.mineru_patch  # noqa

from mineru.cli.common import do_parse
import os

if __name__ == '__main__':
    output_dir = '/tmp/mineru_test7'
    os.makedirs(output_dir, exist_ok=True)

    print('Starting parse...')
    result = do_parse(
        output_dir=output_dir,
        pdf_file_names=['attention'],
        pdf_bytes_list=[open('/tmp/attention.pdf', 'rb').read()],
        p_lang_list=['en'],
        backend='pipeline',
        parse_method='auto',
        formula_enable=True,
        table_enable=True,
        return_md=True,
        return_images=False,
    )
    print(f'Result type: {type(result)}')
    if isinstance(result, dict):
        md = result.get('md_content', '')
        if isinstance(md, dict):
            md = list(md.values())[0] if md else ''
        if md:
            print(f'Markdown: {len(md)} chars')
            print(md[:800])
        else:
            print('No markdown content. Keys:', list(result.keys()))
    else:
        print(str(result)[:500])
