"""
FortiClient EMS: License seat capacity, consumption and remaining lifetime.

One service per EMS site selects the active EPP, ZTNA or SASE product from
seat capacity and usage. The product appears in the summary, not the name.
"""
from cmk.agent_based.v2 import CheckPlugin, Metric, Result, State, check_levels

from ..lib.common import checking, discovery, expiry_results, moment, number


def check_license_data(record, params, selector):
    """
    Evaluate license seats and the latest applicable license expiry.

    Input:
        record: Tenant record; params: Levels; selector: Unused.
    Output:
        Seat counts, utilization and lifetime results; invalid fields are UNKNOWN.
    """
    lic = record['data']['license']
    products = {product: (number(lic['vdom_seats'][product]), number(lic['used'][product]))
                for product in ('ztna', 'epp', 'sase')}
    active = [product for product, (maximum, used) in products.items() if maximum or used]
    if len(active) > 1:
        yield Result(state=State.UNKNOWN,
                     summary='Multiple active license types: ' + ', '.join(product.upper() for product in active))
        return
    if not active:
        yield Metric('ems_license_used', 0)
        yield Metric('ems_license_max', 0)
        yield Result(state=State.OK, summary='No seats licensed; utilization unavailable')
        return
    license_type = active[0]
    maximum, used = products[license_type]
    yield Metric('ems_license_used', used)
    yield Metric('ems_license_max', maximum)
    yield Result(state=State.CRIT if used > maximum else State.OK,
                 summary=f'{license_type.upper()}: {used:g} / {maximum:g} seats')
    if maximum:
        yield from check_levels(used / maximum * 100,
                                levels_upper=params.get('utilization', ('fixed', (80.0, 90.0))),
                                metric_name='ems_license_utilization', label='Utilization',
                                render_func=lambda v: f'{v:.1f}%')
    else:
        yield Result(state=State.CRIT if used else State.OK, summary='No seats licensed; utilization unavailable')
    periods = lic.get('licenses')
    if not isinstance(periods, list):
        raise ValueError('Missing license periods')
    # Match explicitly named products. Unclassified periods represent the common
    # license period, as in the supplied EMS examples. Renewals use the latest date.
    applicable = []
    for period in periods:
        if not isinstance(period, dict):
            raise ValueError('Invalid license period')
        product = str(period.get('type', '')).lower()
        types = {key for key in ('ztna', 'epp', 'sase') if key in product}
        if license_type in types or not types:
            applicable.append(period.get('expiry_date'))
    if not applicable:
        if maximum or used:
            raise ValueError('No applicable license expiry')
        return
    latest = max(applicable, key=moment)
    yield from expiry_results(latest, params)


check_plugin_fortiems_license = CheckPlugin(name='fortiems_license', sections=['fortiems'],
    service_name='FortiClient EMS %s', discovery_function=discovery('license'),
    check_function=checking('license', check_license_data), check_ruleset_name='fortiems_license',
    check_default_parameters={'utilization': ('fixed', (80.0, 90.0)), 'expiry': ('fixed', (30, 14))})
