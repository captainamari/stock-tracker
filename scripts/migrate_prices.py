"""Read-only audit of legacy CSVs; never imports unknown-basis market data."""
import argparse
import csv
import json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args()
    for path in sorted(args.source.rglob('*.csv')):
        with path.open(encoding='utf-8-sig',newline='') as stream:
            rows=list(csv.DictReader(stream))
        print(json.dumps({'file':str(path),'rows':len(rows),'quality':'legacy_unknown','imported':False},ensure_ascii=False))

if __name__=='__main__':
    main()
