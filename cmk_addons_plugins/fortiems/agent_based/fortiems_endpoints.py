"""
FortiClient EMS: Endpoint OS totals, version distribution and historical counts.

Versions and their endpoint counts appear in the OS service summary.
Only the total endpoint count is recorded as a metric.
"""
from cmk.agent_based.v2 import CheckPlugin, Metric, Result, State

from ..lib.common import checking, discovery, number


def endpoint_counts(entries):
    """
    Validate and aggregate the full endpoint version distribution.

    Input:
        entries: EMS donut data list, including a valid empty list.
    Output:
        Version-to-count mapping; invalid rows raise ValueError.
    """
    if not isinstance(entries, list):
        raise ValueError('Missing endpoint distribution')
    counts = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not entry['name']:
            raise ValueError('Invalid endpoint version')
        count = number(entry.get('value'))
        if not count.is_integer():
            raise ValueError('Invalid fractional endpoint count')
        counts[entry['name']] = counts.get(entry['name'], 0) + count
    return counts


def check_endpoints_data(record, params, os_key):
    """
    Report total and per-version endpoint counts without losing version identity.

    Input:
        record: Tenant record; params: Unused; os_key: windows or macos.
    Output:
        Total endpoint metric and a summary containing each version count.
    """
    counts = endpoint_counts(record['data'][os_key])
    total = sum(counts.values())
    yield Metric('ems_endpoints', total)
    versions = [f'FortiClient {" ".join(version.split())}: {count:g}'
                for version, count in sorted(counts.items())]
    yield Result(state=State.OK, summary=', '.join([f'{total:g} endpoints', *versions]),
                 details='\n'.join(f'{version}: {count:g}' for version, count in sorted(counts.items())) or 'No endpoints')


check_plugin_fortiems_endpoints = CheckPlugin(name='fortiems_endpoints', sections=['fortiems'],
    service_name='FortiClient EMS %s', discovery_function=discovery('endpoints'),
    check_function=checking('endpoints', check_endpoints_data), check_default_parameters={})
