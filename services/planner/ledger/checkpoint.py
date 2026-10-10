"""Versioned JSON ledger checkpoints restored through validated public audit replay."""
from dataclasses import asdict,fields
from hashlib import sha256
from json import dumps,loads
from math import isfinite
from .models import Vehicle,Request,Destination,Assignment,LedgerError

SCHEMA="knight26.ledger"
VERSION=1
STATE_FIELDS=("vehicles","requests","destinations","stocks","assignments","_fingerprints",
              "people","outcomes","events","delivered")

def require(condition,message):
    if not condition:
        raise LedgerError("checkpoint: "+message)

def canonical_json(value):
    def validate(item):
        if item is None or isinstance(item,(str,bool)):
            return
        if isinstance(item,(int,float)):
            require(isfinite(item),"nonfinite number")
        elif isinstance(item,(list,tuple)):
            for child in item:
                validate(child)
        elif isinstance(item,dict) and all(isinstance(k,str) for k in item):
            for child in item.values():
                validate(child)
        else:
            raise LedgerError("checkpoint requires JSON values and string keys")
    validate(value)
    return dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False)

def json_copy(value):
    try:
        return loads(canonical_json(value))
    except (TypeError,ValueError,OverflowError,RecursionError) as error:
        raise LedgerError("invalid checkpoint JSON") from error

def keys(value,expected,name):
    require(isinstance(value,dict) and set(value)==set(expected),name+" fields differ")

def seal(body):
    result=json_copy(body)
    result["checksum"]=sha256(canonical_json(result).encode()).hexdigest()
    return result

def unseal(payload,schema,version):
    data=json_copy(payload); require(isinstance(data,dict),"payload must be an object")
    checksum=data.pop("checksum",None)
    require(checksum==sha256(canonical_json(data).encode()).hexdigest(),"checksum mismatch")
    require(data.get("schema")==schema and type(data.get("version")) is int
            and data["version"]==version,"unsupported schema/version")
    return data

def state_for(ledger):
    return json_copy({name:{key:asdict(value) for key,value in ledger.assignments.items()}
                      if name=="assignments" else getattr(ledger,name) for name in STATE_FIELDS})

def make_checkpoint(ledger):
    with ledger._lock:
        ledger.check_invariants()
        return seal(dict(schema=SCHEMA,version=VERSION,initial_config=ledger._initial_config,
                         initial_goods=ledger._initial_goods,state=state_for(ledger)))

def _record(cls,value):
    keys(value,(f.name for f in fields(cls)),cls.__name__)
    return cls(**value)

def restore_checkpoint(ledger_type,payload):
    from .core import _seconds
    try:
        data=unseal(payload,SCHEMA,VERSION)
        keys(data,("schema","version","initial_config","initial_goods","state"),"ledger")
        config=data["initial_config"]; keys(config,("vehicles","requests","destinations","stocks"),"config")
        require(all(isinstance(config[k],list) for k in ("vehicles","requests","destinations")),"config arrays")
        ledger=ledger_type([_record(Vehicle,v) for v in config["vehicles"]],
                          [_record(Request,r) for r in config["requests"]],
                          [_record(Destination,d) for d in config["destinations"]],config["stocks"])
        require(canonical_json(ledger._initial_config)==canonical_json(config)
                and canonical_json(ledger._initial_goods)==canonical_json(data["initial_goods"]),"initial baseline differs")
        state=data["state"]; keys(state,STATE_FIELDS,"state")
        require(all(isinstance(state[k],list if k=="events" else dict) for k in STATE_FIELDS),"collection types")
        require(set(state["_fingerprints"])==set(state["assignments"]),"fingerprint identities")
        assignments=state["assignments"]
        for aid,record in assignments.items():
            keys(record,(f.name for f in fields(Assignment)),"assignment")
            require(record["dispatch_id"]==aid,"assignment ID")
            for name in ("loading_complete_s","service_s","arrival_eta_s","created_s","travel_s","last_event_s"):
                _seconds(record[name],name)
        # Preserve array order: audit times across different vehicles may not be sorted.
        for event in state["events"]:
            keys(event,("event_id","type","dispatch_id","time_s","details"),"event")
            aid=event["dispatch_id"]; require(aid in assignments,"unknown audit assignment")
            saved=assignments[aid]; now=_seconds(event["time_s"],"audit time"); kind=event["type"]
            if kind=="dispatch_committed":
                fp=state["_fingerprints"][aid]
                require(isinstance(fp,list) and len(fp)==8,"fingerprint fields")
                vehicle,request,route,created,loading,service,persons,cargo=fp
                ledger.commit_dispatch(aid,vehicle,request,route,created,person_ids=persons,cargo=cargo,
                                       loading_s=loading,service_s=service)
                # Preserve original tolerated route roundoff unless loading replanning
                # actually changed the committed travel duration. Restore loading
                # reroutes before any possible pre-departure stranding event.
                current=ledger.assignments[aid]
                if current.travel_s!=saved["travel_s"]:
                    ledger.update_eta(aid,saved["loading_complete_s"]+saved["travel_s"])
                if saved["actual_departure_s"] is None and current.arrival_eta_s!=saved["arrival_eta_s"]:
                    ledger.update_eta(aid,saved["arrival_eta_s"])
            elif kind=="departure":
                ledger.mark_departed(aid,now); ledger.update_eta(aid,saved["arrival_eta_s"])
            elif kind=="arrival":
                ledger.update_eta(aid,saved["arrival_eta_s"])
                ledger.record_arrival(aid,now,event["details"]["node_id"])
            elif kind=="service_completed":
                ledger.complete_service(aid,now,ledger.requests[saved["request_id"]]["destination_node"])
            elif kind=="stranded":
                ledger.strand(aid,now,event["details"]["reason"])
            else:
                raise LedgerError("checkpoint: unknown audit event")
        require(canonical_json(state_for(ledger))==canonical_json(state),"reconstructed state differs")
        ledger.check_invariants()
        return ledger
    except LedgerError:
        raise
    except (KeyError,TypeError,ValueError,OverflowError,RecursionError) as error:
        raise LedgerError("checkpoint: malformed ledger") from error
