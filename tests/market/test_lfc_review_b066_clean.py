"""Guards: B066 all consumers use one conservative clean-row rule."""
import json
import pytest
from weather.market import lfc_campaign_control as control


@pytest.mark.parametrize('field',['incident','orders_open_unproven','attention_required'])
@pytest.mark.parametrize('value',['missing',None,False,True])
def test_clean_rule_handles_every_unknown_or_boolean_field(field,value):
    row={'incident':False,'orders_open_unproven':False,'attention_required':False}
    if value=='missing':row.pop(field)
    else:row[field]=value
    assert control.row_is_clean(row) is (value is False)


def test_control_watch_and_public_projection_refuse_a_null_record(tmp_path,capsys):
    row={'schema_version':control.CONTROL_SCHEMA,'attempt_id':'a'*32,'phase':'DEFERRED',
         'incident':None,'orders_open_unproven':None,'attention_required':None}
    (tmp_path/'20261111T090000Z-row.json').write_text(json.dumps(row))
    assert control.main(['--root',str(tmp_path)])==1
    public=json.loads(capsys.readouterr().out)
    assert public['clean'] is False and public['attention_required'] is True
    assert control.public_status(row)['attention_required'] is True


@pytest.mark.parametrize('phase',['DEFERRED','REFUSED','INCIDENT','POSTCHECK_PENDING','MISSED','EVIDENCE_GAP'])
def test_failed_phase_cannot_publish_a_silent_clean_record(tmp_path,phase):
    from tests.market.test_lfc_campaign import Clock
    row=control.control_record(tmp_path,'a'*32,phase=phase,now=Clock().now())
    assert row['attention_required'] is True and not control.row_is_clean(row)
