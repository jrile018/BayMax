"""Read one root-published incident snapshot without accepting browser-provided evidence.

The configured directory is a trusted server-side boundary. Hashes detect
corruption or mismatched publication files, not source authenticity.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

VERSION="knight26-snapshot-publication-v1"
INCIDENT_VERSION="knight26-incident-v1"
HASH=re.compile(r"^[0-9a-f]{64}$")
CATEGORIES=("hazard","needs","closures","vehicles","stock","capacity")


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_regular(directory_fd,name,limit):
    try:
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ValueError("Unsafe publication file") from error
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size>limit:
            raise ValueError("Invalid publication file")
        data=bytearray()
        while len(data)<=limit:
            chunk=os.read(fd,min(65536,limit+1-len(data)))
            if not chunk:break
            data.extend(chunk)
        if len(data)>limit:raise ValueError("Publication file exceeds limit")
        return bytes(data)
    finally:
        os.close(fd)


class PublicationReader:
    """Consume a pointer and immutable publication created by SnapshotPublisher."""

    def __init__(self,directory):
        self.directory=Path(directory)
        if not self.directory.is_absolute() or ".." in self.directory.parts:
            raise ValueError("Publication directory must be absolute without traversal")

    def _open_directory(self):
        fd=os.open("/",os.O_RDONLY|os.O_DIRECTORY)
        try:
            for part in self.directory.parts[1:]:
                if part in ("",".",".."):raise ValueError("Invalid publication directory")
                new=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                os.close(fd);fd=new
            return fd
        except FileNotFoundError:
            os.close(fd)
            return None
        except BaseException:
            os.close(fd)
            raise

    def read(self):
        fd=self._open_directory()
        if fd is None:return None
        try:
            pointer_bytes=_read_regular(fd,"current.json",4096)
            if pointer_bytes is None:return None
            pointer=json.loads(pointer_bytes)
            if (not isinstance(pointer,dict) or
                    set(pointer)!={"publication_version","view_hash","publication_file","publication_sha256"} or
                    pointer["publication_version"]!=VERSION or
                    not isinstance(pointer["view_hash"],str) or not HASH.fullmatch(pointer["view_hash"]) or
                    not isinstance(pointer["publication_sha256"],str) or not HASH.fullmatch(pointer["publication_sha256"]) or
                    pointer["publication_file"]!=f"publication-{pointer['view_hash']}.json"):
                raise ValueError("Invalid current publication pointer")
            content=_read_regular(fd,pointer["publication_file"],16_777_216)
            if content is None or hashlib.sha256(content).hexdigest()!=pointer["publication_sha256"]:
                raise ValueError("Publication bytes mismatch")
            publication=json.loads(content)
            if content!=_canonical(publication)+b"\n":
                raise ValueError("Publication is not canonical")
            return self._snapshot(publication,pointer["view_hash"])
        except (UnicodeDecodeError,json.JSONDecodeError,TypeError,KeyError,OverflowError,RecursionError) as error:
            raise ValueError("Invalid incident publication") from error
        finally:
            os.close(fd)

    @staticmethod
    def _snapshot(p,expected_view):
        if (not isinstance(p,dict) or p.get("publication_version")!=VERSION or
                p.get("view_hash")!=expected_view or
                not isinstance(p.get("capabilities"),dict) or
                set(p["capabilities"])!={"can_calculate_operational_outcomes","can_dispatch"} or
                p["capabilities"]["can_calculate_operational_outcomes"] is not False or
                p["capabilities"]["can_dispatch"] is not False):
            raise ValueError("Invalid incident publication")
        s=p.get("snapshot")
        if not isinstance(s,dict) or s.get("schema_version")!=INCIDENT_VERSION:
            raise ValueError("Invalid accepted incident snapshot")
        snapshot_hash=s.get("snapshot_hash")
        if not isinstance(snapshot_hash,str) or not HASH.fullmatch(snapshot_hash):
            raise ValueError("Invalid incident snapshot hash")
        plain={key:value for key,value in s.items() if key!="snapshot_hash"}
        if _digest(plain)!=snapshot_hash:
            raise ValueError("Incident snapshot hash mismatch")
        if p.get("incident_id")!=s.get("incident_id") or p.get("cutoff_utc")!=s.get("cutoff_utc"):
            raise ValueError("Incident identity or cutoff mismatch")
        cats=s.get("categories")
        if not isinstance(cats,dict) or set(cats)!=set(CATEGORIES) or any(
                value is not None and not isinstance(value,list) for value in cats.values()):
            raise ValueError("Invalid incident categories")
        projection=p.get("projection_input")
        if projection is not None:
            if not isinstance(projection,dict) or projection.get("initial_snapshot_hash")!=snapshot_hash:
                raise ValueError("Projection snapshot mismatch")
            projection_hash=projection.get("projection_input_hash")
            if (not isinstance(projection_hash,str) or not HASH.fullmatch(projection_hash) or
                    _digest({k:v for k,v in projection.items() if k!="projection_input_hash"})!=projection_hash or
                    projection.get("can_calculate_operational_outcomes") is not False):
                raise ValueError("Invalid projection")
        attestations=p.get("metadata_attestations")
        mission={
            "publication_version":VERSION,"incident_id":s["incident_id"],
            "bbox_lonlat":s["bbox_lonlat"],"cutoff_utc":s["cutoff_utc"],
            "categories":cats,"revision_history":s["revision_history"],
            "unconfirmed_leads":s["unconfirmed_leads"],
            "accepted_source_refs":s["accepted_source_refs"],
            "ledger_watermark":s["ledger_watermark"],
            "in_flight_commitments":s["in_flight_commitments"],
            "metadata_attestations":attestations,
            "geography_binding":p.get("geography_binding"),
        }
        mission_hash=_digest(mission)
        if p.get("mission_hash")!=mission_hash:raise ValueError("Mission publication hash mismatch")
        view={
            "publication_version":VERSION,"mission_hash":mission_hash,
            "snapshot_hash":snapshot_hash,"source_health":s["source_health"],
            "synopsis":p.get("synopsis"),
            "projection_input_hash":projection["projection_input_hash"] if projection is not None else None,
        }
        if _digest(view)!=expected_view:raise ValueError("View publication hash mismatch")
        return s
