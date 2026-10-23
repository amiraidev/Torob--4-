"""Repackage a freshly built public catalog after importing an updated dataset."""
import argparse
import json
from pathlib import Path
from catalog_bundle import pack_catalog


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('database', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent.parent/'data/catalog.jsonl.xz')
    args = parser.parse_args()
    info = pack_catalog(args.database, args.output)
    print('Full catalog packed: '+json.dumps(info['counts']))
    print('Compressed bytes: '+str(args.output.stat().st_size))
