"""Authored fixtures for bounded official adapters; no live-source claim."""
import json
import unittest
from services.intake.live_sources import SourcePolicy, TransportResponse, BoundedSourceClient, SourceError, parse_nws_alerts, parse_usgs_earthquakes

NWS = "https://api.weather.gov/alerts/active?area=CA"
USGS = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
NOW = "2026-10-10T09:13:00Z"

def packet(url, features):
    return TransportResponse(200, {}, json.dumps({"type":"FeatureCollection","features":features}).encode(), url)

def nws(**kw):
    p={"id":"urn:oid:alert-1","status":"Actual","messageType":"Alert",
       "sent":"2026-10-10T02:00:00-07:00","effective":"2026-10-10T02:01:00-07:00",
       "onset":"2026-10-11T15:00:00-07:00","expires":"2026-10-10T14:00:00-07:00",
       "ends":None,"references":[],"event":"Flood Warning","areaDesc":"Example area",
       "geocode":{"UGC":["CAZ001"]},"affectedZones":[]}
    p.update(kw.pop("properties",{}))
    return {"id":"https://api.weather.gov/alerts/urn:oid:alert-1","type":"Feature",
            "geometry":None,"properties":p,**kw}

def usgs(**kw):
    p={"time":1791623063446,"updated":1791623199297,"status":"automatic",
       "type":"earthquake","mag":2.4,"ids":",aka2026uboihn,","place":"Example"}
    p.update(kw.pop("properties",{}))
    return {"id":"aka2026uboihn","type":"Feature",
            "geometry":{"type":"Point","coordinates":[-151.317,62.569,90.7]},
            "properties":p,**kw}

class Transport:
    def __init__(self,*responses):
        self.responses=list(responses); self.calls=[]
    def __call__(self,url,headers,timeout_s,max_bytes):
        self.calls.append((url,headers,timeout_s,max_bytes))
        x=self.responses.pop(0)
        if isinstance(x,Exception): raise x
        return x

class OfficialSourceTests(unittest.TestCase):
    def test_cached_refresh_and_stale_last_good(self):
        first=packet(NWS,[nws()])
        t=Transport(first,TransportResponse(304,{},b"",NWS),TimeoutError("timeout"),packet(NWS,[]))
        c=BoundedSourceClient(SourcePolicy("nws",(NWS,),min_interval_s=0,max_bytes=10000),t,lambda:NOW)
        a,b,d,e=(c.refresh(NWS) for _ in range(4))
        self.assertEqual([x.state for x in (a,b,d,e)],["fresh","not_modified","stale","fresh"])
        self.assertEqual(d.last_good.sha256,a.last_good.sha256)
        self.assertEqual(parse_nws_alerts(e.last_good),())
    def test_redirect_and_size_limits(self):
        t=Transport(TransportResponse(302,{"Location":"https://evil.example/x"},b"",NWS))
        c=BoundedSourceClient(SourcePolicy("nws",(NWS,),min_interval_s=0),t,lambda:NOW)
        self.assertEqual(c.refresh(NWS).state,"failed")
        self.assertEqual(len(t.calls),1)
        hidden=Transport(TransportResponse(200,{},b"{}","https://evil.example/x"))
        self.assertEqual(BoundedSourceClient(SourcePolicy("nws",(NWS,),min_interval_s=0),hidden,lambda:NOW).refresh(NWS).state,"failed")
        big=Transport(TransportResponse(200,{},b"x"*101,NWS))
        self.assertEqual(BoundedSourceClient(SourcePolicy("nws",(NWS,),min_interval_s=0,max_bytes=100),big,lambda:NOW).refresh(NWS).state,"failed")
    def test_nws_exact_times_null_area_and_references(self):
        f=nws(properties={"messageType":"Update","references":[{"identifier":"old","sender":"w-nws.webmaster@noaa.gov","sent":"2026-10-09T20:00:00-07:00","@id":"https://api.weather.gov/alerts/old"}]})
        x,=parse_nws_alerts(packet(NWS,[f]))
        self.assertEqual(x["sent"],"2026-10-10T09:00:00Z")
        self.assertEqual(x["onset"],"2026-10-11T22:00:00Z")
        self.assertEqual(x["expires"],"2026-10-10T21:00:00Z")
        self.assertIsNone(x["ends"]); self.assertIsNone(x["geometry"])
        self.assertEqual(x["area_label"],"Example area")
        self.assertEqual(x["references"][0]["identifier"],"old")
        self.assertEqual(x["acceptance"],"candidate_hazard")
    def test_nws_status_and_malformed(self):
        for status in ("Test","Exercise"):
            self.assertEqual(parse_nws_alerts(packet(NWS,[nws(properties={"status":status})]))[0]["acceptance"],"not_actual")
        for field,value in (("sent","bad"),("messageType","Magic"),("references",[{"identifier":"old"}]),("id","")):
            with self.subTest(field=field),self.assertRaises(SourceError):
                parse_nws_alerts(packet(NWS,[nws(properties={field:value})]))
    def test_nws_polygon_is_area_not_point(self):
        g={"type":"Polygon","coordinates":[[[-121,39],[-120,39],[-120,40],[-121,39]]]}
        x,=parse_nws_alerts(packet(NWS,[nws(geometry=g)]))
        self.assertEqual(x["geometry"],g); self.assertEqual(x["precision"],"area")
        g["coordinates"][0][0][0]=999
        with self.assertRaises(SourceError): parse_nws_alerts(packet(NWS,[nws(geometry=g)]))
    def test_usgs_ms_ids_type_and_depth(self):
        x,=parse_usgs_earthquakes(packet(USGS,[usgs()]))
        self.assertEqual(x["associated_ids"],("aka2026uboihn",))
        self.assertEqual(x["event_type"],"earthquake"); self.assertEqual(x["status"],"automatic")
        self.assertEqual(x["geometry"]["coordinates"],[-151.317,62.569,90.7])
        self.assertEqual(x["acceptance"],"candidate_hazard")
        self.assertTrue(x["time"].endswith("Z"))
    def test_usgs_nonquake_and_invalid_times_geometry(self):
        self.assertEqual(parse_usgs_earthquakes(packet(USGS,[usgs(properties={"type":"quarry blast"})]))[0]["acceptance"],"not_earthquake")
        for f in (usgs(properties={"time":1791623063}),usgs(properties={"updated":True}),
                  usgs(geometry={"type":"Point","coordinates":[1000,0,0]})):
            with self.subTest(f=f),self.assertRaises(SourceError): parse_usgs_earthquakes(packet(USGS,[f]))
    def test_duplicate_keys_record_bound_and_rolling_disappearance(self):
        dup=TransportResponse(200,{},b'{"type":"FeatureCollection","features":[],"features":[]}',NWS)
        with self.assertRaises(SourceError): parse_nws_alerts(dup)
        with self.assertRaises(SourceError): parse_nws_alerts(packet(NWS,[nws(),nws()]),max_records=1)
        self.assertEqual(parse_usgs_earthquakes(packet(USGS,[])),())
        self.assertNotIn("retracted",parse_usgs_earthquakes(packet(USGS,[usgs()]))[0])

class AdditionalOfficialSourceTests(unittest.TestCase):
    def test_malformed_refresh_does_not_replace_last_good(self):
        good = packet(NWS,[nws()])
        bad = TransportResponse(200,{},b'{"type":"FeatureCollection","features":[{"type":"Feature"}]}',NWS)
        c=BoundedSourceClient(SourcePolicy("nws",(NWS,),min_interval_s=0,max_bytes=10000),
                              Transport(good,bad),lambda:NOW)
        old=c.refresh(NWS)
        stale=c.refresh(NWS)
        self.assertEqual(stale.state,"stale")
        self.assertEqual(stale.last_good.sha256,old.last_good.sha256)
    def test_usgs_unknown_status_is_not_hazard(self):
        with self.assertRaises(SourceError):
            parse_usgs_earthquakes(packet(USGS,[usgs(properties={"status":"unverified-safe"})]))
    def test_nws_reference_requires_sender(self):
        f=nws(properties={"references":[{"identifier":"old",
             "sent":"2026-10-09T20:00:00-07:00","@id":"https://api.weather.gov/alerts/old"}]})
        with self.assertRaises(SourceError): parse_nws_alerts(packet(NWS,[f]))
    def test_raw_hash_is_recomputed_before_parsing(self):
        from services.intake.live_sources import RawDocument
        raw=RawDocument("nws",NWS,NWS,200,(),NOW,packet(NWS,[nws()]).body,"0"*64)
        with self.assertRaises(SourceError): parse_nws_alerts(raw)
    def test_descriptive_user_agent_is_sent(self):
        t=Transport(packet(NWS,[nws()]))
        BoundedSourceClient(SourcePolicy("nws",(NWS,),min_interval_s=0),t,lambda:NOW).refresh(NWS)
        self.assertIn("Knight26",t.calls[0][1]["User-Agent"])
        self.assertIn("github.com",t.calls[0][1]["User-Agent"])
    def test_nws_null_geometry_preserves_zones_and_rejects_unlinked_update(self):
        f=nws(properties={"areaDesc":None,"geocode":{"UGC":["CAZ001"]},
           "affectedZones":["https://api.weather.gov/zones/forecast/CAZ001"]})
        x,=parse_nws_alerts(packet(NWS,[f]))
        self.assertIsNone(x["geometry"])
        self.assertEqual(x["ugc"],("CAZ001",))
        self.assertEqual(x["affected_zones"],("https://api.weather.gov/zones/forecast/CAZ001",))
        self.assertEqual(x["area_label"],"CAZ001")
        with self.assertRaises(SourceError):
            parse_nws_alerts(packet(NWS,[nws(properties={"messageType":"Update","references":[]})]))
    def test_policy_rejects_unregistered_origin_and_path(self):
        for source,url in (("nws","https://evil.example/alerts/active?area=CA"),
                           ("nws","https://api.weather.gov/admin"),
                           ("usgs","https://earthquake.usgs.gov/admin"),
                           ("nws","https://api.weather.gov/alerts/active?area=%43A")):
            with self.subTest(source=source,url=url),self.assertRaises(SourceError):
                SourcePolicy(source,(url,))
    def test_first_failure_has_no_last_good_and_is_not_stale(self):
        c=BoundedSourceClient(SourcePolicy("nws",(NWS,),min_interval_s=0),
                              Transport(TimeoutError("dns unavailable")),lambda:NOW)
        result=c.refresh(NWS)
        self.assertEqual(result.state,"failed")
        self.assertIsNone(result.last_good)
    def test_parser_rejects_cross_provider_transport_and_nonfinite_json(self):
        with self.assertRaises(SourceError):
            parse_nws_alerts(TransportResponse(200,{},packet(NWS,[nws()]).body,"https://evil.example/data"))
        with self.assertRaises(SourceError):
            parse_usgs_earthquakes(TransportResponse(200,{},packet(USGS,[usgs()]).body,NWS))
        bad=TransportResponse(200,{},b'{"type":"FeatureCollection","features":[],"extra":1e999}',NWS)
        with self.assertRaises(SourceError): parse_nws_alerts(bad)
    def test_poll_interval_and_retry_after_bound_calls(self):
        times=iter(("2026-10-10T09:00:00Z","2026-10-10T09:00:30Z","2026-10-10T09:01:00Z"))
        t=Transport(packet(NWS,[nws()]),packet(NWS,[]))
        c=BoundedSourceClient(SourcePolicy("nws",(NWS,),min_interval_s=60),t,lambda:next(times))
        self.assertEqual(c.refresh(NWS).state,"fresh")
        self.assertEqual(c.refresh(NWS).state,"throttled")
        self.assertEqual(len(t.calls),1)
        self.assertEqual(c.refresh(NWS).state,"fresh")
        self.assertEqual(len(t.calls),2)
        times=iter(("2026-10-10T10:00:00Z","2026-10-10T10:01:00Z","2026-10-10T10:02:00Z"))
        t=Transport(TransportResponse(429,{"Retry-After":"120"},b"",NWS),packet(NWS,[]))
        c=BoundedSourceClient(SourcePolicy("nws",(NWS,),min_interval_s=30),t,lambda:next(times))
        self.assertEqual(c.refresh(NWS).state,"failed")
        self.assertEqual(c.refresh(NWS).state,"throttled")
        self.assertEqual(c.refresh(NWS).state,"fresh")
        self.assertEqual(len(t.calls),2)
    def test_allowed_redirect_retains_request_and_final_url(self):
        alternate="https://api.weather.gov/alerts/active?area=NV"
        t=Transport(TransportResponse(302,{"Location":alternate},b"",NWS),
                    TransportResponse(200,{},packet(NWS,[nws()]).body,alternate))
        c=BoundedSourceClient(SourcePolicy("nws",(NWS,alternate),min_interval_s=0),t,lambda:NOW)
        result=c.refresh(NWS)
        self.assertEqual(result.state,"fresh")
        self.assertEqual(result.last_good.request_url,NWS)
        self.assertEqual(result.last_good.final_url,alternate)
    def test_usgs_rejects_malformed_place_and_identity_aliases(self):
        for f in (usgs(properties={"place":{"html":"<script>"}}),
                  usgs(properties={"ids":",aka2026uboihn, aka2026uboihn,"}),
                  usgs(properties={"ids":",aka2026uboihn,aka2026uboihn,"})):
            with self.subTest(f=f),self.assertRaises(SourceError):
                parse_usgs_earthquakes(packet(USGS,[f]))
    def test_excessive_retry_after_never_shortens_provider_wait(self):
        times=iter(("2026-10-10T10:00:00Z","2026-10-10T11:00:00Z"))
        t=Transport(TransportResponse(429,{"Retry-After":"999999999"},b"",NWS))
        c=BoundedSourceClient(SourcePolicy("nws",(NWS,),min_interval_s=30),t,lambda:next(times))
        self.assertEqual(c.refresh(NWS).state,"failed")
        self.assertEqual(c.refresh(NWS).state,"throttled")
        self.assertEqual(len(t.calls),1)
    def test_candidate_provenance_keeps_original_and_final_urls(self):
        alternate="https://api.weather.gov/alerts/active?area=NV"
        t=Transport(TransportResponse(302,{"Location":alternate},b"",NWS),
                    TransportResponse(200,{},packet(NWS,[nws()]).body,alternate))
        doc=BoundedSourceClient(SourcePolicy("nws",(NWS,alternate),min_interval_s=0),t,lambda:NOW).refresh(NWS).last_good
        x,=parse_nws_alerts(doc)
        self.assertEqual(x["request_url"],NWS)
        self.assertEqual(x["final_url"],alternate)
        self.assertEqual(x["source_id"],"nws")
        self.assertEqual(x["raw_sha256"],doc.sha256)
    def test_nws_saved_receipt_url_is_valid_without_relabeling(self):
        actual="https://api.weather.gov/alerts?active=true&area=CA"
        SourcePolicy("nws",(actual,))
        x,=parse_nws_alerts(TransportResponse(200,{},packet(NWS,[nws()]).body,actual))
        self.assertEqual(x["source_url"],actual)

    def test_extreme_numeric_fields_return_stale_or_source_error(self):
        for field, value in (("mag", 10**1000), ("depth", 10**1000)):
            bad = usgs(properties={field: value}) if field == "mag" else usgs(
                geometry={"type":"Point","coordinates":[-151.317,62.569,value]})
            raw = packet(USGS,[bad])
            with self.subTest(field=field), self.assertRaises(SourceError):
                parse_usgs_earthquakes(raw)
            c=BoundedSourceClient(SourcePolicy("usgs",(USGS,),min_interval_s=0),
                                  Transport(packet(USGS,[usgs()]),raw),lambda:NOW)
            self.assertEqual(c.refresh(USGS).state,"fresh")
            self.assertEqual(c.refresh(USGS).state,"stale")
    def test_malformed_feature_url_and_extreme_offset_are_source_errors(self):
        for feature in (nws(id="https://api.weather.gov:bad/alerts/x"),
                        nws(properties={"sent":"0001-01-01T00:00:00+01:00"})):
            with self.subTest(feature=feature),self.assertRaises(SourceError):
                parse_nws_alerts(packet(NWS,[feature]))

    def test_source_url_rejects_whitespace_before_urlsplit(self):
        for url in (" https://api.weather.gov/alerts?active=true&area=CA",
                    "https://api.weather.gov/\nalerts?active=true&area=CA",
                    "https://api.weather.gov/\talerts?active=true&area=CA"):
            with self.subTest(url=url), self.assertRaises(SourceError):
                SourcePolicy("nws", (url,))
