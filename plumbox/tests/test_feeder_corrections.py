import pytest
from app.mappings import meta_for, display_value, native_value


@pytest.mark.parametrize('level',['100','50','30'])
def test_feed_correction_metadata_and_native_values(level):
 name=f'feeder_correction_{level}'
 meta=meta_for(name)
 assert meta['unit']=='%'
 assert meta['risk']=='advanced'
 assert 'Korekta czasu podawania pelletu' in meta['label']
 for value in [0,80,100,130]:
  shown=display_value(name,value,airflow_correction_enabled=True)
  assert shown==value
  assert native_value(name,shown,airflow_correction_enabled=True)==value
