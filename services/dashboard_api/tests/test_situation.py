import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from services.dashboard_api.situation import PublicationReader


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class PublicationReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)
        self.snapshot={
            'schema_version':'knight26-incident-v1','incident_id':'test-incident',
            'bbox_lonlat':[-122,39,-121,40],'cutoff_utc':'2026-10-10T09:00:00Z',
            'categories':{key:None for key in ('hazard','needs','closures','vehicles','stock','capacity')},
            'revision_history':[],'unconfirmed_leads':[],'accepted_source_refs':[],
            'ledger_watermark':None,'in_flight_commitments':None,'source_health':None,
        }
        self.snapshot['snapshot_hash']=digest(self.snapshot)

    def publish(self):
        version='knight26-snapshot-publication-v1'
        s=self.snapshot
        attest={'ledger_watermark':None,'in_flight_commitments':None}
        mission={
            'publication_version':version,'incident_id':s['incident_id'],
            'bbox_lonlat':s['bbox_lonlat'],'cutoff_utc':s['cutoff_utc'],
            'categories':s['categories'],'revision_history':s['revision_history'],
            'unconfirmed_leads':s['unconfirmed_leads'],
            'accepted_source_refs':s['accepted_source_refs'],
            'ledger_watermark':s['ledger_watermark'],
            'in_flight_commitments':s['in_flight_commitments'],
            'metadata_attestations':attest,'geography_binding':None,
        }
        mission_hash=digest(mission)
        view={
            'publication_version':version,'mission_hash':mission_hash,
            'snapshot_hash':s['snapshot_hash'],'source_health':s['source_health'],
            'synopsis':None,'projection_input_hash':None,
        }
        view_hash=digest(view)
        publication={
            'publication_version':version,'incident_id':s['incident_id'],
            'cutoff_utc':s['cutoff_utc'],'mission_hash':mission_hash,
            'view_hash':view_hash,'snapshot':s,'projection_input':None,
            'geography_binding':None,'metadata_attestations':attest,'synopsis':None,
            'capabilities':{'can_calculate_operational_outcomes':False,'can_dispatch':False},
        }
        body=canonical(publication)+b'\n'
        name=f'publication-{view_hash}.json'
        (self.directory/name).write_bytes(body)
        pointer={
            'publication_version':version,'view_hash':view_hash,
            'publication_file':name,'publication_sha256':hashlib.sha256(body).hexdigest(),
        }
        (self.directory/'current.json').write_bytes(canonical(pointer)+b'\n')
        return name

    def test_missing_pointer_is_unavailable(self):
        self.assertIsNone(PublicationReader(self.directory).read())

    def test_reads_pinned_immutable_publication(self):
        self.publish()
        self.assertEqual(PublicationReader(self.directory).read(),self.snapshot)

    def test_rejects_changed_publication_or_pointer(self):
        name=self.publish()
        (self.directory/name).write_bytes((self.directory/name).read_bytes()+b' ')
        with self.assertRaises(ValueError):PublicationReader(self.directory).read()
        (self.directory/name).write_bytes(canonical(json.loads((self.directory/name).read_bytes()))+b'\n')
        (self.directory/'current.json').write_text(json.dumps({'publication_file':'../outside.json'}))
        with self.assertRaises(ValueError):PublicationReader(self.directory).read()

    def test_rejects_nonboolean_capability_even_if_publication_hash_matches(self):
        name=self.publish()
        publication=json.loads((self.directory/name).read_bytes())
        publication['capabilities']['can_dispatch']=0
        body=canonical(publication)+b'\n'
        (self.directory/name).write_bytes(body)
        pointer=json.loads((self.directory/'current.json').read_bytes())
        pointer['publication_sha256']=hashlib.sha256(body).hexdigest()
        (self.directory/'current.json').write_bytes(canonical(pointer)+b'\n')
        with self.assertRaises(ValueError):PublicationReader(self.directory).read()

    def test_rejects_symlink_pointer(self):
        self.publish()
        (self.directory/'current.json').unlink()
        (self.directory/'current.json').symlink_to(self.directory/'elsewhere.json')
        with self.assertRaises(ValueError):PublicationReader(self.directory).read()


    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO required')
    def test_rejects_fifo_pointer_without_blocking(self):
        os.mkfifo(self.directory/'current.json')
        probe = (
            'import sys\n'
            'from services.dashboard_api.situation import PublicationReader\n'
            'try:\n'
            '    PublicationReader(sys.argv[1]).read()\n'
            'except ValueError:\n'
            '    print("rejected")\n'
        )
        result = subprocess.run(
            [sys.executable, '-c', probe, str(self.directory)],
            text=True, capture_output=True, timeout=2, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'rejected')


if __name__=='__main__':unittest.main()
