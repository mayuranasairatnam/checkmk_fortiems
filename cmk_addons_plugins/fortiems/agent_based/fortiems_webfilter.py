"""
FortiClient EMS webfilter inventory, profile settings and imported firewall sync.

Each service belongs to its tenant. Failed API queries remain UNKNOWN and do
not generate zero counts. Profile contents and credentials are not exported.
"""
from datetime import datetime, timezone

from cmk.agent_based.v2 import CheckPlugin, Metric, Result, State, check_levels

from ..lib.common import checking, configured_state, discovery, flag, moment, number


def check_webfilter_data(record, params, selector):
    """
    Report inventory and roll up imported-firewall synchronization alarms.

    Input:
        record: Tenant data; params: Sync states and age levels; selector: Unused.
    Output:
        Inventory counts, per-firewall sync results and the oldest active sync
        age when every enabled task has a valid timestamp.
    """
    index = record['data']['webfilter']
    profiles = record['data']['webfilter_profiles']
    if not isinstance(index, dict) or not isinstance(profiles, list):
        raise ValueError('Missing webfilter inventory')
    imports = index.get('imported', [])
    if not isinstance(imports, list):
        raise ValueError('Invalid imported firewall list')
    failures = sum(bool(profile.get('error')) for profile in profiles)
    defaults = sum(flag(profile.get('is_default')) is True for profile in profiles)
    classified = sum(flag(profile.get('is_default')) is not None for profile in profiles)
    description = f'{len(profiles)} profile(s)'
    if classified == len(profiles) and profiles:
        description = f'{len(profiles) - defaults} non-default profile(s), {defaults} EMS default profile(s)'
    yield Result(state=State.UNKNOWN if failures else State.OK,
                 summary=f'{description}, {len(imports)} imported firewall(s), {failures} profile query failure(s)',
                 details='Profile inventory returned by EMS, including built-in profiles. Endpoint assignments and active use are not queried.')
    yield Metric('ems_webfilter_profiles', len(profiles))
    yield Metric('ems_webfilter_imports', len(imports))
    ages = []
    complete = True
    for firewall in imports:
        name = (firewall.get('fp_name') or firewall.get('host') or 'Unnamed firewall') if isinstance(firewall, dict) else 'Invalid firewall'
        try:
            output = list(check_webfilter_import_data(record, params, firewall))
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            complete = False
            yield Result(state=State.UNKNOWN, summary=f'{name}: synchronization data missing or invalid')
            continue
        for entry in output:
            if isinstance(entry, Metric):
                if entry.name == 'ems_sync_age':
                    ages.append(entry.value)
            else:
                yield Result(state=entry.state, summary=f'{name}: {entry.summary}',
                             details=getattr(entry, 'details', None) or None)
                if entry.state == State.UNKNOWN:
                    complete = False
    if ages and complete:
        yield Metric('ems_sync_age', max(ages))


def check_webfilter_profile_data(record, params, profile):
    """
    Evaluate one profile's activation and FortiGuard state with list counts.

    Input:
        record: Tenant data; params: Configurable states; profile: Safe summary.
    Output:
        Profile results and historical enabled/category/URL measurements.
    """
    if profile.get('error'):
        raise ValueError('Profile query failed')
    yield Result(state=State.OK, summary=str(profile.get('name') or f'Profile {profile["id"]}'),
                 details='Profile configuration returned by EMS. Enabled describes the profile setting; endpoint assignment and active use are not queried.')
    enabled = flag(profile.get('enabled'))
    state = State.UNKNOWN if enabled is None else State.OK if enabled else configured_state(params.get('disabled_state', 'warn'))
    yield Result(state=state, summary='Webfilter: ' + ('unknown' if enabled is None else 'enabled' if enabled else 'disabled'))
    if enabled is not None:
        yield Metric('ems_webfilter_enabled', int(enabled), boundaries=(0, 1))
    guard = flag(profile.get('fortiguard_enabled'))
    yield Result(state=State.UNKNOWN if guard is None else State.OK,
                 summary='FortiGuard: ' + ('unknown' if guard is None else 'enabled' if guard else 'disabled'))
    for key, title in (('categories', 'Categories'), ('urls', 'URL entries')):
        try:
            count = number(profile.get(key))
        except ValueError:
            yield Result(state=State.UNKNOWN, summary=f'{title}: missing or invalid')
        else:
            yield Metric('ems_webfilter_' + key, count)
            yield Result(state=State.OK, summary=f'{title}: {count:g}')
    if profile.get('update_time'):
        yield Result(state=State.OK, summary=f'Last update: {profile["update_time"]}')


def check_webfilter_import_data(record, params, firewall):
    """
    Evaluate the synchronization task for one imported firewall.

    Input:
        record: Tenant data; params: Error states and age levels; firewall: Task.
    Output:
        Activation, error and last-success results; sync age when available.
    """
    task = firewall['task']
    enabled = flag(task.get('enabled'))
    state = State.UNKNOWN if enabled is None else State.OK if enabled else configured_state(params.get('sync_disabled_state', 'warn'))
    yield Result(state=state, summary='Synchronization: ' + ('unknown' if enabled is None else 'enabled' if enabled else 'disabled'))
    if task.get('last_error'):
        yield Result(state=configured_state(params.get('sync_error_state', 'crit')),
                     summary='Synchronization error', details=str(task['last_error']))
    else:
        yield Result(state=State.OK, summary='No synchronization error')
    if enabled:
        last = moment(task.get('last_successful_run_time'))
        age = (datetime.now(timezone.utc) - last).total_seconds()
        if age < 0:
            raise ValueError('Last successful sync lies in the future')
        yield Result(state=State.OK, summary=f'Last successful sync: {last.isoformat()}')
        yield from check_levels(age, levels_upper=params.get('sync_age', ('fixed', (86400.0, 172800.0))),
                                metric_name='ems_sync_age', label='Sync age', render_func=lambda value: f'{value / 3600:.1f} hours')


check_plugin_fortiems_webfilter = CheckPlugin(name='fortiems_webfilter', sections=['fortiems'],
    service_name='FortiClient EMS %s', discovery_function=discovery('webfilter_summary'),
    check_function=checking('webfilter_summary', check_webfilter_data), check_ruleset_name='fortiems_webfilter',
    check_default_parameters={'sync_disabled_state': 'warn', 'sync_error_state': 'crit',
                              'sync_age': ('fixed', (86400.0, 172800.0))})

check_plugin_fortiems_webfilter_profiles = CheckPlugin(name='fortiems_webfilter_profiles', sections=['fortiems'],
    service_name='FortiClient EMS %s', discovery_function=discovery('webfilter_profiles'),
    check_function=checking('webfilter_profiles', check_webfilter_profile_data), check_ruleset_name='fortiems_webfilter',
    check_default_parameters={'disabled_state': 'warn'})

check_plugin_fortiems_webfilter_imports = CheckPlugin(name='fortiems_webfilter_imports', sections=['fortiems'],
    service_name='FortiClient EMS %s', discovery_function=discovery('webfilter_imports'),
    check_function=checking('webfilter_imports', check_webfilter_import_data), check_ruleset_name='fortiems_webfilter',
    check_default_parameters={'sync_disabled_state': 'warn', 'sync_error_state': 'crit',
                              'sync_age': ('fixed', (86400.0, 172800.0))})
