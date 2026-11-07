"""
FortiClient EMS: JSON section parser and global/tenant collection health.

All checks consume the shared fortiems agent section and preserve existing
service names, ruleset identifiers and performance metric names.
"""
import json

from cmk.agent_based.v2 import AgentSection, CheckPlugin, Result, Service, State

from ..lib.common import checking, discovery


def parse_fortiems(string_table):
    """
    Validate the agent envelope and retain collection errors for the API service.

    Input:
        string_table: Rows from the fortiems JSON section.
    Output:
        A section dictionary, including an explicit error for malformed input.
    """
    try:
        data = json.loads(''.join(row[0] for row in string_table if row))
        if (isinstance(data, dict) and data.get('schema') == 1
                and isinstance(data.get('shared'), bool)
                and isinstance(data.get('errors'), list)
                and isinstance(data.get('tenants'), dict)
                and ('global' not in data or (isinstance(data['global'], dict)
                     and isinstance(data['global'].get('errors'), list)
                     and isinstance(data['global'].get('data'), dict)))
                and all(isinstance(name, str) and isinstance(value, dict)
                        and isinstance(value.get('data'), dict)
                        and isinstance(value.get('errors'), list)
                        for name, value in data['tenants'].items())):
            return data
    except (ValueError, TypeError, IndexError):
        pass
    return {'schema': 1, 'shared': False, 'errors': ['Invalid FortiEMS agent data'], 'tenants': {}}


agent_section_fortiems = AgentSection(name='fortiems', parse_function=parse_fortiems)


def discover_api(section):
    """
    Discover the host-level collection health service even after login failure.

    Input:
        section: Parsed FortiEMS section.
    Output:
        One service without an item.
    """
    yield Service()


def check_api(section):
    """
    Report global and tenant-specific collection failures.

    Input:
        section: Parsed FortiEMS section.
    Output:
        OK for successful collection, otherwise CRIT with sanitized errors.
    """
    errors = list(section['errors'])
    if section.get('global'):
        errors.extend(f'global: {error}' for error in section['global']['errors'])
    if not section['tenants'] and not errors:
        errors.append('No sites collected; check deployment mode, site selection and account site access')
    for name, record in section['tenants'].items():
        errors.extend(f'{name}: {error}' for error in record['errors'])
    yield Result(state=State.CRIT if errors else State.OK,
                 summary='; '.join(errors) if errors else f'API queries successful; {len(section["tenants"])} site(s)')


def check_tenant_api_data(record, params, selector):
    """
    Expose per-tenant collection failures alongside the global API service.

    Input:
        record: Tenant record; params/selector: Unused.
    Output:
        One OK or CRIT result.
    """
    errors = record['errors']
    yield Result(state=State.CRIT if errors else State.OK, summary='; '.join(errors) if errors else 'Tenant queries successful')


check_plugin_fortiems_api = CheckPlugin(name='fortiems_api', sections=['fortiems'],
    service_name='FortiClient EMS API', discovery_function=discover_api, check_function=check_api)


check_plugin_fortiems_tenant_api = CheckPlugin(name='fortiems_tenant_api', sections=['fortiems'],
    service_name='FortiClient EMS %s', discovery_function=discovery('tenant_api'),
    check_function=checking('tenant_api', check_tenant_api_data), check_default_parameters={})
