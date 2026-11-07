"""
FortiClient EMS: Identity provider availability, connector and synchronization health.

Checks consume the shared fortiems agent section. Provider GUIDs appear in
service output while names remain readable; duplicate names remain UNKNOWN.
"""
from datetime import datetime, timezone

from cmk.agent_based.v2 import CheckPlugin, Metric, Result, State, check_levels

from ..lib.common import checking, configured_state, discovery, flag, idp_identity, moment, number


def check_idp_summary_data(record, params, selector):
    """
    Show whether provider collection returned no objects or unusable identities.

    Input:
        record: Tenant data; params/selector: Unused.
    Output:
        Provider inventory status and count for a valid response list.
    """
    entries = record['data']['idps']
    if not isinstance(entries, list):
        raise ValueError('Invalid identity provider list')
    identities = [idp_identity(entry) for entry in entries]
    if any(identity is None for identity in identities) or len(set(identities)) != len(identities):
        yield Result(state=State.UNKNOWN, summary='Provider identities missing or ambiguous; check the idps API response')
        return
    yield Result(state=State.OK, summary=f'{len(entries)} identity provider(s) returned' if entries else 'No identity providers returned for this site',
                 details='\n'.join(identities) or None)
    yield Metric('ems_idp_count', len(entries))


def check_idp_data(record, params, entry):
    """
    Evaluate IDP/connector availability, synchronization health and age.

    Input:
        record: Tenant record; params: States and maximum sync age; entry: IDP.
    Output:
        Connection/sync results plus device, user, progress and sync-age metrics.
    """
    status, conn = entry.get('status') or {}, entry.get('connection_info') or {}
    domain = (entry.get('domain_info') or {}).get('name')
    yield Result(state=State.OK, summary=f'Domain: {domain or "unspecified"}')
    guid = entry.get('guid') or (entry.get('domain_info') or {}).get('guid')
    if isinstance(guid, str) and guid.strip():
        yield Result(state=State.OK, summary=f'GUID: {guid}')
    for title, value, setting in (('IDP', status.get('online'), 'offline_state'),
                                  ('Connector', conn.get('conn_online'), 'connector_state')):
        online = flag(value)
        state = State.UNKNOWN if online is None else State.OK if online else configured_state(params.get(setting, 'crit'))
        yield Result(state=state, summary=f'{title}: ' + ('unknown' if online is None else 'online' if online else 'offline'))
    if status.get('last_error'):
        yield Result(state=configured_state(params.get('error_state', 'crit')), summary='Synchronization error', details=str(status['last_error']))
    else:
        yield Result(state=State.OK, summary='No synchronization error')
    for key, metric, title in (('total_devices', 'ems_idp_devices', 'Devices'), ('total_users', 'ems_idp_users', 'Users')):
        try:
            value = number(entry.get(key))
            yield Metric(metric, value)
            yield Result(state=State.OK, summary=f'{title}: {value:g}')
        except ValueError:
            yield Result(state=State.UNKNOWN, summary=f'{title}: missing or invalid')
    try:
        progress = number(status.get('sync_progress'))
        if progress > 100:
            raise ValueError('Sync progress exceeds 100%')
        yield Metric('ems_sync_progress', progress)
        yield Result(state=State.OK, summary=f'Sync progress: {progress:g}%')
    except ValueError:
        yield Result(state=State.UNKNOWN, summary='Sync progress: missing or invalid')
    last = moment(status.get('last_success_enumerated'))
    age = (datetime.now(timezone.utc) - last).total_seconds()
    if age < 0:
        raise ValueError('Last successful sync lies in the future')
    yield Result(state=State.OK, summary=f'Last successful sync: {last.isoformat()}')
    yield from check_levels(age, levels_upper=params.get('sync_age', ('fixed', (86400.0, 172800.0))),
                            metric_name='ems_sync_age', label='Sync age', render_func=lambda v: f'{v / 3600:.1f} hours')


check_plugin_fortiems_idp = CheckPlugin(name='fortiems_idp', sections=['fortiems'],
    service_name='FortiClient EMS %s', discovery_function=discovery('idp'),
    check_function=checking('idp', check_idp_data), check_ruleset_name='fortiems_idp',
    check_default_parameters={'offline_state': 'crit', 'connector_state': 'crit', 'error_state': 'crit',
                              'sync_age': ('fixed', (86400.0, 172800.0))})

check_plugin_fortiems_idp_summary = CheckPlugin(name='fortiems_idp_summary', sections=['fortiems'],
    service_name='FortiClient EMS %s', discovery_function=discovery('idp_summary'),
    check_function=checking('idp_summary', check_idp_summary_data), check_default_parameters={})
