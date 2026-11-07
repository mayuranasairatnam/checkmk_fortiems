"""
FortiClient EMS: Assigned EMS certificates and the earliest expiry.

All checks consume the shared fortiems agent section and preserve existing
service names, ruleset identifiers and performance metric names.
"""
from cmk.agent_based.v2 import CheckPlugin, Result, State

from ..lib.common import checking, discovery, expiry_results, moment


def check_certificates_data(record, params, selector):
    """
    Evaluate every assigned certificate and the earliest remaining lifetime.

    Input:
        record: Tenant record; params: Lifetime levels; selector: Unused.
    Output:
        Assigned certificate details and the earliest expiry metric.
    """
    certificates = record['data']['certificates']
    if not isinstance(certificates, list):
        raise ValueError('Invalid certificate list')
    assigned = []
    for cert in certificates:
        if not isinstance(cert, dict):
            raise ValueError('Invalid certificate entry')
        if cert.get('assigned_to'):
            assigned.append(cert)
    if not assigned:
        yield Result(state=State.UNKNOWN, summary='No assigned EMS certificates returned')
        return
    earliest = min(assigned, key=lambda cert: moment(cert.get('expiry_date')))
    for cert in assigned:
        yield Result(state=State.OK, summary=f'{cert.get("name", "Unnamed")}: {cert.get("expiry_date")}, assigned to {cert["assigned_to"]}')
    yield from expiry_results(earliest['expiry_date'], params)


check_plugin_fortiems_certificates = CheckPlugin(name='fortiems_certificates', sections=['fortiems'],
    service_name='FortiClient EMS %s', discovery_function=discovery('certificates'),
    check_function=checking('certificates', check_certificates_data), check_ruleset_name='fortiems_certificates',
    check_default_parameters={'expiry': ('fixed', (30, 14))})
