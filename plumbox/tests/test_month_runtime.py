import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.routers import api


@pytest.mark.parametrize('current,expected,label',[
 ('2026-11-01T08:00:00+00:00','2026-10-31T23:00:00+00:00','01–30.11.2026'),
 ('2024-02-29T12:00:00+00:00','2024-01-31T23:00:00+00:00','01–29.02.2024'),
 ('2026-03-31T12:00:00+00:00','2026-02-28T23:00:00+00:00','01–31.03.2026'),
 ('2026-11-30T23:01:00+00:00','2026-11-30T23:00:00+00:00','01–31.12.2026'),
])
def test_month_runtime_starts_at_local_month_boundary(monkeypatch,current,expected,label):
 now=datetime.fromisoformat(current)
 class Clock(datetime):
  @classmethod
  def now(cls,tz=None): return now
 class DB:
  async def power_runtime(self,since,until,**kw):
   assert since==datetime.fromisoformat(expected)
   assert until==now
   return {'seconds':{'100':10,'50':20,'30':30}}
 monkeypatch.setattr(api,'datetime',Clock)
 monkeypatch.setattr(api.state,'database',DB())
 monkeypatch.setattr(api.state,'config',SimpleNamespace(timezone='Europe/Warsaw',history=SimpleNamespace(sample_interval_seconds=30)))
 result=asyncio.run(api.power_runtime('month'))
 assert result['period_label']==label
 assert result['seconds']['100']==10


def test_48_hour_runtime_remains_available(monkeypatch):
 class DB:
  async def power_runtime(self,since,until,**kw):
   assert until-since==timedelta(hours=48)
   return {'seconds':None}
 monkeypatch.setattr(api.state,'database',DB())
 result=asyncio.run(api.power_runtime('48h'))
 assert result['period']=='48h'
