"""Guards: B063 peer GET work cannot consume another band's cash wait budget."""
from tests.market.test_lfc_f2_repost import fixture
from weather.market.lfc_f2_repost import bounded_read_progress


def test_peer_bounded_reads_do_not_spend_waiting_bands_cash_poll_budget(tmp_path, monkeypatch):
    controller, account, status, ledger, clock, runtime, read = fixture(tmp_path, seconds=600)
    account.fills_enabled=False
    peer, waiting=controller.bands
    raw=account.raws[1]
    began=[]; pauses=[]
    authorize=waiting.authorize_post
    def enter(*args, **kwargs):
        if not began: began.append(clock.seconds)
        return authorize(*args, **kwargs)
    monkeypatch.setattr(waiting,'authorize_post',enter)
    balances=raw.balances
    def lagged_balance():
        row=balances()
        if began and not pauses:
            row['available_collateral']='299'
            row['collateral_evidence']['balance']='299000000'
        return row
    monkeypatch.setattr(raw,'balances',lagged_balance)
    ordinary=peer.quote_steps
    def peer_reads(**kwargs):
        for delay in ordinary(**kwargs):
            if began and not pauses:
                # Three separate bounded 50s GETs, with the ordinary heartbeat
                # progress the real reader observer supplies. No order call.
                for part in range(3):
                    with bounded_read_progress(peer):
                        for tick in range(10):
                            clock.sleep(5)
                            # Preserve independently required read freshness;
                            # only the waiting generator's cash retry is paused.
                            # These checkpoints read, never submit an order.
                            for band in controller.bands: band.control()
                pauses.append(clock.seconds)
            yield delay
    monkeypatch.setattr(peer,'quote_steps',peer_reads)
    result=controller.run()
    assert pauses and pauses[0]-began[0]>120
    assert waiting.posts==2, controller.results[waiting.session_id]
    assert controller.results[waiting.session_id]['reason']=='fixed_end'
    assert not result['unknown_submit'] and account.cancel_all_calls==[600]
