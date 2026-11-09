"""Guards: B066 all consumers use one conservative clean-row rule."""
import json
from datetime import datetime, timezone
import pytest
from weather.market import lfc_campaign_control as control


@pytest.mark.parametrize('field',['incident','orders_open_unproven','attention_required','postchecks_pending'])
@pytest.mark.parametrize('value',['missing',None,False,True])
def test_clean_rule_handles_every_unknown_or_boolean_field(field,value):
    row={'incident':False,'orders_open_unproven':False,'attention_required':False,'postchecks_pending':False,
         'phase':'IDLE','at_utc':datetime.now(timezone.utc).isoformat()}
    if value=='missing':row.pop(field)
    else:row[field]=value
    assert control.row_is_clean(row) is (value is False)


@pytest.mark.parametrize('phase', ['IDLE', 'COMPLETE', 'RUNNING'])
def test_producer_keeps_unknown_postchecks_visible(tmp_path, phase):
    now = datetime.now(timezone.utc)
    row = control.control_record(tmp_path, 'a'*32, phase=phase, now=now, postchecks_pending=None)
    assert row['postchecks_pending'] is None
    assert control.public_status(row, now=now)['postchecks_pending'] is None
    assert control.watch_status(row, now=now)[1] == 1
    assert not control.row_is_clean(row, now=now)


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
