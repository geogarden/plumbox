import asyncio
from datetime import datetime,timedelta,timezone
from app.database import Database

def test_retention_keeps_active_alarms_and_prunes_closed_and_audit(tmp_path):
    db=Database(str(tmp_path/"retention.db"),retention_days=30)
    asyncio.run(db.initialize())
    old=(datetime.now(timezone.utc)-timedelta(days=60)).isoformat()
    recent=datetime.now(timezone.utc).isoformat()
    with db._connect() as conn:
        for ident,active,ended in [("active",1,None),("closed",0,old),("recent",0,recent),("undated",0,None)]:
            conn.execute("INSERT INTO alarms(signature,code,name,started_at,ended_at,active,raw_json) VALUES(?,1,?, ?,?,?, '{}')",(ident,ident,None if ident=="undated" else old,ended,active))
        for ts in [old,recent]:conn.execute("INSERT INTO audit(ts,scope,device_index,parameter,success) VALUES(?,'ecomax',0,'test',1)",(ts,))
    asyncio.run(db.cleanup())
    with db._connect() as conn:
        assert {r[0] for r in conn.execute("SELECT signature FROM alarms")}=={"active","recent","undated"}
        assert [r[0] for r in conn.execute("SELECT ts FROM audit")]==[recent]

from app.boiler_monitor import CycleTracker,DEFAULT_NOTIFICATIONS,EventStore

def test_temperature_hold_restarts_below_threshold_without_rearming_notification():
    tracker=CycleTracker();settings={**DEFAULT_NOTIFICATIONS,"temperature_threshold":50,"threshold_hold_seconds":10,"temperature_hysteresis":3}
    start=datetime.now(timezone.utc)
    def step(seconds,temp):return tracker.evaluate_alerts({"alerts":[],"values":{"feeder_temp":temp}},settings,start+timedelta(seconds=seconds))[0]
    assert not step(0,50);assert not step(1,49);assert not step(12,50)
    assert any(e[0]=="temperature" for e in step(22,50))
    assert not step(23,49);assert not step(34,50)
    assert not step(35,47);assert not step(36,50)
    assert any(e[0]=="temperature" for e in step(46,50))

def test_cycle_id_cache_only_retains_current_history(tmp_path):
    store=EventStore(tmp_path/"events.db");store.initialize()
    store.checkpoint({"history":[{"id":str(i)} for i in range(2000)]})
    store.checkpoint({"history":[{"id":str(i)} for i in range(1000,3000)]})
    assert store.saved_cycle_ids=={str(i) for i in range(1000,3000)}


import ast
import logging
from pathlib import Path
import yaml
import pytest
from app.routers import boiler

@pytest.mark.parametrize("raw,expected",[({"enabled":True,"target":"mobile_app_saved"},["mobile_app_saved"]),({"enabled":False,"target":"mobile_app_old","targets":[]},[])])
def test_real_startup_notification_parser_keeps_legacy_target(tmp_path,raw,expected):
    # Execute the actual startup parser block with a temporary config, not the transport.
    source=Path(__file__).resolve().parents[1]/"app/main.py"
    tree=ast.parse(source.read_text(encoding="utf-8"))
    block=next(n for n in ast.walk(tree) if isinstance(n,ast.Try) and any(isinstance(x,ast.Name) and x.id=="notification_settings" for x in ast.walk(n)))
    config=tmp_path/"config.yaml";config.write_text(yaml.safe_dump({"notifications":raw}),encoding="utf-8")
    ns={"yaml":yaml,"Path":Path,"CONFIG_PATH":str(config),"boiler":boiler,"DEFAULT_NOTIFICATIONS":{},"_LOGGER":logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[block],type_ignores=[]),str(source),"exec"),ns)
    assert ns["notification_settings"]["targets"]==expected
