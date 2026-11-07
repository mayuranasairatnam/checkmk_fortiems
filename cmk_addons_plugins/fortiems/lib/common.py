"""
Shared FortiClient EMS validation, tenant identities and discovery/check helpers.

Missing or invalid API measurements remain explicit errors. Helpers are shared
by the feature modules without registering additional Checkmk plugins.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import math

from cmk.agent_based.v2 import Result, Service, State, check_levels

SYSTEM_FIELDS = ('Hostname', 'Serial Number', 'Version', 'Auto Upgrade', 'Package Region')


def configured_state(value):
    """
    Translate the ruleset's state choice into an Agent-based API state.

    Input:
        value: ok, warn or crit from the Setup rule.
    Output:
        The corresponding Checkmk State.
    """
    return {'ok': State.OK, 'warn': State.WARN, 'crit': State.CRIT}[value]


def number(value):
    """
    Read a finite, non-negative measurement without substituting a default.

    Input:
        value: Number or numeric string from EMS.
    Output:
        A float; raises ValueError for missing, boolean or invalid values.
    """
    if value is None or isinstance(value, bool):
        raise ValueError('Missing or invalid measurement')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Missing or invalid measurement') from None
    if not math.isfinite(result) or result < 0:
        raise ValueError('Missing or invalid measurement')
    return result


def flag(value):
    """
    Normalize EMS boolean fields, preserving an unknown state.

    Input:
        value: Boolean, 0/1, or a corresponding boolean string.
    Output:
        True, False, or None when the API value is absent or unsupported.
    """
    if value is True or value in (1, '1', 'true', 'True'):
        return True
    if value is False or value in (0, '0', 'false', 'False'):
        return False
    return None


def moment(value):
    """
    Parse an EMS ISO date or timestamp in UTC.

    Input:
        value: ISO date or datetime; timezone-less timestamps are treated as UTC.
    Output:
        An aware UTC datetime; raises ValueError for invalid dates.
    """
    if not isinstance(value, str) or not value:
        raise ValueError('Missing or invalid date')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        raise ValueError('Missing or invalid date') from None


def remaining(value):
    """
    Calculate remaining lifetime using UTC calendar dates.

    Input:
        value: Expiry date supplied by EMS.
    Output:
        Signed number of calendar days until expiry.
    """
    return (moment(value).date() - datetime.now(timezone.utc).date()).days


def label(section, tenant, suffix):
    """
    Build unambiguous service items for dedicated and shared deployments.

    Input:
        section: Agent section; tenant: Site name; suffix: Object description.
    Output:
        Dedicated suffix or a JSON-quoted tenant prefix followed by the suffix.
    """
    return f'[{json.dumps(tenant, ensure_ascii=False)}] {suffix}' if section['shared'] else suffix


def idp_identity(entry):
    """
    Identify an EMS provider even when its connector alias is empty.

    Input:
        entry: Provider with optional alias, domain, group path and identifiers.
    Output:
        Display name without GUIDs, or None for an unidentifiable response row.
        Duplicate display names are reported as ambiguous by the checks.
    """
    if not isinstance(entry, dict):
        return None
    conn = entry.get('connection_info')
    domain = entry.get('domain_info')
    group = entry.get('group_info')
    conn = conn if isinstance(conn, dict) else {}
    domain = domain if isinstance(domain, dict) else {}
    group = group if isinstance(group, dict) else {}
    name = next((value.strip() for value in (conn.get('alias'), entry.get('name'),
                 domain.get('name'), group.get('path')) if isinstance(value, str) and value.strip()), None)
    ident = entry.get('id')
    if ident is not None:
        return f'{name} (ID {ident})' if name else f'ID {ident}'
    # GUIDs belong in service output. Never combine providers sharing a name;
    # the normal object lookup reports ambiguous names as UNKNOWN.
    guid = entry.get('guid') or domain.get('guid')
    if isinstance(guid, str) and guid.strip():
        return name or 'Unnamed provider'
    return name


def objects(section, kind):
    """
    Enumerate discoverable objects from successfully retrieved collections.

    Input:
        section: Parsed section; kind: One of the supported check categories.
    Output:
        Tuples of service item, tenant data, and object-specific selector.
    """
    if kind == 'certificates' and section.get('cloud') is True:
        return
    split_global = section['shared'] and 'global' in section
    if split_global and kind in ('system', 'certificates', 'tenant_api'):
        record = section['global']
        if kind == 'system':
            for field in SYSTEM_FIELDS:
                if field != 'Package Region':
                    yield label(section, 'global', 'System ' + field), record, field
        else:
            yield label(section, 'global', 'Certificates' if kind == 'certificates' else 'API'), record, None
    for tenant, record in section['tenants'].items():
        if split_global and kind == 'system':
            yield label(section, tenant, 'System Package Region'), record, 'Package Region'
            continue
        if split_global and kind == 'certificates':
            continue
        data = record['data']
        if kind == 'system':
            for field in SYSTEM_FIELDS:
                # Cloud version comes from constants; hostname and the appliance
                # auto-upgrade flag are unavailable in the supplied Cloud responses.
                if section.get('cloud') is True and field not in ('Serial Number', 'Version', 'Package Region'):
                    continue
                yield label(section, tenant, 'System ' + field), record, field
        elif kind in ('certificates', 'tenant_api', 'idp_summary', 'webfilter_summary'):
            suffix = {'certificates': 'Certificates', 'tenant_api': 'API',
                      'idp_summary': 'Identity Providers', 'webfilter_summary': 'Webfilter'}[kind]
            yield label(section, tenant, suffix), record, None
        elif kind == 'license':
            yield label(section, tenant, 'License'), record, None
        elif kind == 'endpoints':
            for os_key, os_name in (('windows', 'Windows'), ('macos', 'macOS')):
                yield label(section, tenant, 'Endpoints ' + os_name), record, os_key
        elif kind == 'idp' and isinstance(data.get('idps'), list):
            for entry in data['idps']:
                identity = idp_identity(entry)
                if identity:
                    yield label(section, tenant, 'IDP ' + identity), record, entry
        elif kind == 'webfilter_profiles' and isinstance(data.get('webfilter_profiles'), list):
            profiles = [(profile['name'].strip() if isinstance(profile.get('name'), str)
                         and profile['name'].strip() else str(profile['id']), profile)
                        for profile in data['webfilter_profiles']
                        if isinstance(profile, dict) and profile.get('id') is not None
                        and flag(profile.get('is_default')) is not True]
            counts = Counter(name for name, _ in profiles)
            for name, profile in profiles:
                display = name if counts[name] == 1 else f'{name} (ID {profile["id"]})'
                yield label(section, tenant, 'Webfilter Profile ' + display), record, profile
        elif kind == 'webfilter_imports' and isinstance(data.get('webfilter'), dict):
            imports = data['webfilter'].get('imported', [])
            if isinstance(imports, list):
                for firewall in imports:
                    if not isinstance(firewall, dict):
                        continue
                    name = firewall.get('fp_name') or firewall.get('host')
                    if name:
                        yield label(section, tenant, 'Webfilter Import ' + str(name)), record, firewall


def expiry_results(value, params, metric='ems_remaining_days', title='Remaining lifetime'):
    """
    Evaluate remaining lifetime and enforce CRIT after expiration.

    Input:
        value: Expiry date; params: Rule levels; metric/title: Output labels.
    Output:
        Lifetime results and a historical days metric.
    """
    days = remaining(value)
    yield Result(state=State.CRIT if days <= 0 else State.OK, summary=f'Expiry: {value}')
    yield from check_levels(days, levels_lower=params.get('expiry', ('fixed', (30, 14))),
                            metric_name=metric, label=title, render_func=lambda v: f'{v:.0f} days')


def discovery(kind):
    """
    Build a discovery callback for a category.

    Input:
        kind: Check category.
    Output:
        Checkmk discovery callback yielding unique service items.
    """
    def discover(section):
        """
        Discover unique items in the selected category.

        Input:
            section: Parsed agent data.
        Output:
            Service objects for the category.
        """
        seen = set()
        for item, record, selector in objects(section, kind):
            if kind == 'tenant_api' and not section['shared']:
                continue
            if item not in seen:
                seen.add(item)
                yield Service(item=item)
    return discover


def checking(kind, callback):
    """
    Build a check callback with explicit missing-data handling.

    Input:
        kind: Category; callback: Category-specific evaluator.
    Output:
        Checkmk callback producing UNKNOWN when data or an object is absent.
    """
    def check(item, params, section):
        """
        Find one object and evaluate it without fabricating absent measurements.

        Input:
            item: Service identity; params: Rule parameters; section: Agent data.
        Output:
            Monitoring results and available performance metrics.
        """
        matches = [(record, selector) for name, record, selector in objects(section, kind) if name == item]
        if len(matches) != 1:
            yield Result(state=State.UNKNOWN, summary='Object unavailable or ambiguous; check EMS API and run discovery')
            return
        record, selector = matches[0]
        try:
            yield from callback(record, params, selector)
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            yield Result(state=State.UNKNOWN, summary='Required EMS data missing or invalid; check EMS API')
    return check
