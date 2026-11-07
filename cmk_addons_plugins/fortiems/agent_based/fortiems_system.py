"""
FortiClient EMS: System identity, firmware, auto upgrades and package region.

Each identity field has its own service. Auto-upgrade status includes a numeric
metric for historical graphs and retains the existing monitoring ruleset.
"""
from cmk.agent_based.v2 import CheckPlugin, Metric, Result, State

from ..lib.common import checking, configured_state, discovery, flag


def check_system_data(record, params, selector):
    """
    Evaluate one system field independently of the other API responses.

    Input:
        record: Tenant record; params: Rule; selector: System field name.
    Output:
        A field value or auto-upgrade state with a historical 0/1 metric.
    """
    data = record['data']
    if selector == 'Auto Upgrade':
        enabled = flag(data['settings'].get('auto_upgrade_enabled'))
        if enabled is None:
            state = State.UNKNOWN
        else:
            setting = 'enabled_state' if enabled else 'disabled_state'
            state = configured_state(params.get(setting, 'warn'))
        yield Result(state=state, summary='Auto upgrade status missing or invalid in EMS settings (auto_upgrade_enabled)' if enabled is None else 'Enabled' if enabled else 'Disabled')
        if enabled is not None:
            yield Metric('ems_auto_upgrade_enabled', int(enabled), boundaries=(0, 1))
        return
    if selector == 'Hostname':
        value = data['info'].get('name')
    elif selector == 'Serial Number':
        value = data['license'].get('sn')
    elif selector == 'Version':
        system = data.get('consts', {}).get('System', {})
        value = system.get('VERSION_FULL') or system.get('VERSION') or data.get('info', {}).get('version')
    elif selector == 'Package Region':
        # EMS labels this setting "Cloud Region to Repackage Installers".
        value = data['settings'].get('fct_repackager_upload_region')
    else:
        raise ValueError('Unknown system field')
    valid = isinstance(value, str) and bool(value.strip())
    yield Result(state=State.OK if valid else State.UNKNOWN,
                 summary=value if valid else f'{selector}: missing or invalid')


check_plugin_fortiems_system = CheckPlugin(name='fortiems_system', sections=['fortiems'],
    service_name='FortiClient EMS %s', discovery_function=discovery('system'),
    check_function=checking('system', check_system_data), check_ruleset_name='fortiems_system',
    check_default_parameters={'enabled_state': 'warn', 'disabled_state': 'warn'})
