"""Guards: run existing F2 fixtures with either explicitly shipped loss basis.

Legacy policy snapshots and bare F0 ledgers retain their gross identity. Only
new example policies change; durable claims still select the actual gate basis.
Loaded explicitly for the B060 two-basis regression matrix, never by production.
"""


def pytest_addoption(parser):
    parser.addoption('--lfc-default-loss-basis', choices=('gross', 'net_of_retained_gains'),
                     default='net_of_retained_gains')


def pytest_configure(config):
    from weather.market import lfc_f2_policy
    lfc_f2_policy.DEFAULT_SLEEVE_LOSS_BASIS = config.getoption('--lfc-default-loss-basis')
