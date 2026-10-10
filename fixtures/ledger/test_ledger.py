import unittest
from services.planner.ledger import *
class Tests(unittest.TestCase):
 def make(self,kind="evacuation",deadline=None):
  return Ledger([Vehicle("v",{"evacuation":"bus","medical":"ambulance","supply":"truck"}[kind],"o",2,5)],[Request("r",kind,"o","d",() if kind=="supply" else ("p",),{"w":5} if kind=="supply" else {},deadline)],[Destination("d","d","medical" if kind=="medical" else "shelter",2)],{"o":{"w":5}})
 def route(self):return dict(status="feasible",safety_validated=True,source_node="o",destination_node="d",departure_s=2,arrival_s=12,edge_ids=["e"])
 def test_actual_service(self):
  for kind in ("evacuation","medical","supply"):
   l=self.make(kind);l.commit_dispatch("x","v","r",self.route(),0,loading_s=2,service_s=3)
   with self.assertRaises(LedgerError):l.mark_departed("x",1)
   l.mark_departed("x",2)
   with self.assertRaises(LedgerError):l.complete_service("x",15,"d")
   l.record_arrival("x",12,"d")
   with self.assertRaises(LedgerError):l.complete_service("x",14,"d")
   out=l.complete_service("x",15,"d");self.assertEqual(out,l.complete_service("x",15,"d"));self.assertTrue(l.check_invariants())
 def test_failure(self):
  l=self.make("supply");r=self.route();r["safety_validated"]=False;before=l.export_state()
  with self.assertRaises(LedgerError):l.commit_dispatch("x","v","r",r,0,loading_s=2)
  self.assertEqual(before,l.export_state());r["safety_validated"]=True
  l.commit_dispatch("x","v","r",r,0,loading_s=2);l.mark_departed("x",2);l.strand("x",5,"closure")
  with self.assertRaises(LedgerError):l.record_arrival("x",12,"d")
  self.assertTrue(l.check_invariants())
 def test_atomic_stock(self):
  from concurrent.futures import ThreadPoolExecutor
  l=Ledger([Vehicle(v,"truck","o",0,5) for v in ("a","b")],[Request(v,"supply","o","d",goods={"w":5}) for v in ("a","b")],[],{"o":{"w":5}})
  r=self.route();r["departure_s"]=0
  def attempt(v):
   try:l.commit_dispatch(v,v,v,r,0);return 1
   except LedgerError:return 0
  with ThreadPoolExecutor(2) as pool:self.assertEqual(sum(pool.map(attempt,("a","b"))),1)
  self.assertTrue(l.check_invariants())
if __name__=="__main__":unittest.main()
