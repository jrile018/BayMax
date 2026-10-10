"""Produce a clearly labeled CPU rule-baseline review trace."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from .schema import Report
from .providers import RuleBaseline
from .review import ReviewStore

def run():
    text='At Pine School, 12 people need evacuation now. East Road is blocked.'
    aliases={'Pine School':{'entity_id':'pine','entity_type':'node','source':'fictional tiny graph v1'},
             'East Road':{'entity_id':'east','entity_type':'edge','source':'fictional tiny graph v1'}}
    store=ReviewStore(aliases); provider=RuleBaseline()
    report=Report('demo:accepted','fictional development exercise',10,text)
    raw=provider.extract(report); pending=store.submit(report,raw,provider.name)
    edited=dict(raw); edited['claims']=raw['claims'][:1]
    corrected=store.edit(pending.proposal_id,edited,'human:demonstration-editor')
    claim=corrected.proposal.claims[0]
    confirmation={'claim_id':claim.claim_id,'kind':'need','mapped_entity_id':'pine',
                  'confirmed_values':{'category':claim.label,'quantity':claim.quantity.value,
                                      'unit':claim.unit.value,'location':claim.location.value,
                                      'urgency':claim.urgency.value if claim.urgency else None},
                  'semantic_override_reason':None}
    accepted=store.review(pending.proposal_id,'accepted','scripted:demonstration-reviewer',
                          expected_revision=corrected.revision,confirmations=(confirmation,))
    rejected_report=Report('demo:rejected','fictional development exercise',11,'At Pine School, 4 people need evacuation now.')
    rejected=store.submit(rejected_report,provider.extract(rejected_report),provider.name)
    rejected=store.review(rejected.proposal_id,'rejected','human:demonstration-reviewer')
    repost=Report('demo:repost',report.source,report.received_time_s,'Repost: '+text)
    duplicate=store.submit(repost,provider.extract(repost),provider.name)
    return {'mode':'deterministic CPU development demonstration','provider':provider.name,
        'human_actions':'scripted confirmations, not recorded human acceptance',
        'simulator_mutation':False,'pending':asdict(pending),'corrected':asdict(corrected),
        'accepted':asdict(accepted),'rejected':asdict(rejected),'repost':asdict(duplicate),
        'integration_requirement':'authenticate actual human, show full source and final command, require inspected revision and deliberate per-command action, then atomically consume effect idempotency keys'}

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); result=run(); args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'output':str(args.output),'provider':result['provider'],
        'accepted_command_count':len(result['accepted']['effects']),'simulator_mutation':False}))

if __name__=='__main__': main()
