"""Run the owned synthetic fixture and export inspectable routing fields."""
import argparse
import hashlib
import json
from pathlib import Path
from .adapter import simulate, edge_access


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--fixture',required=True)
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    raw=Path(args.fixture).read_bytes(); fixture=json.loads(raw)
    hazard=simulate(fixture['config'])
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    outputs={'hazard.json':hazard}
    if hazard['status']=='ok':outputs['edge-access.json']=edge_access(hazard,fixture['edges'],0,safety_buffer_s=fixture.get('safety_buffer_s',0))
    for name,body in outputs.items():
        (out/name).write_text(json.dumps(body,indent=2,sort_keys=True,allow_nan=False)+'\n')
    manifest={'schema_version':'wildfire-artifact-v1','fixture_sha256':hashlib.sha256(raw).hexdigest(),
              'scenario_id':fixture['config']['scenario_id'],'status':hazard['status'],
              'files':{name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in outputs}}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    print(json.dumps(manifest,sort_keys=True))
    return 0 if hazard['status']=='ok' else 2


if __name__=='__main__':raise SystemExit(main())
