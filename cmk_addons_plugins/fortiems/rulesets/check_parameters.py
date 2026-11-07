"""
Thresholds and configurable states for FortiClient EMS services.
"""
from cmk.rulesets.v1 import Title
from cmk.rulesets.v1.form_specs import (
    DefaultValue, DictElement, Dictionary, Float, Integer, LevelDirection,
    Percentage, SimpleLevels, SingleChoice, SingleChoiceElement,
)
from cmk.rulesets.v1.rule_specs import CheckParameters, HostAndItemCondition, Topic


def state_choice(title, default='crit', allow_ok=False):
    """
    Construct an explicit monitoring-state selector.

    Input:
        title: Field label; default: State number; allow_ok: Include OK.
    Output:
        Required rule element with WARN/CRIT and optionally OK choices.
    """
    choices = ([('ok', 'OK')] if allow_ok else []) + [('warn', 'WARN'), ('crit', 'CRIT')]
    return DictElement(required=True, parameter_form=SingleChoice(title=Title(title),
        prefill=DefaultValue(default), elements=[SingleChoiceElement(name=value, title=Title(name))
                                               for value, name in choices]))


def lifetime():
    """
    Build configurable lower levels for days until expiry.

    Input:
        None.
    Output:
        Required lifetime rule element, default WARN/CRIT 30/14 days.
    """
    return DictElement(required=True, parameter_form=SimpleLevels[int](
        title=Title('Remaining lifetime'), form_spec_template=Integer(unit_symbol='days'),
        level_direction=LevelDirection.LOWER, prefill_fixed_levels=DefaultValue((30, 14))))


def system_form():
    """
    Build the auto-upgrade status rule.

    Input:
        None.
    Output:
        Dictionary with independent states for enabled and disabled upgrades.
    """
    return Dictionary(elements={
        'enabled_state': state_choice('Auto upgrade enabled', 'warn', True),
        'disabled_state': state_choice('Auto upgrade disabled', 'warn', True),
    })


def license_form():
    """
    Build license consumption and lifetime threshold rules.

    Input:
        None.
    Output:
        Dictionary with utilization and remaining-day levels.
    """
    return Dictionary(elements={
        'utilization': DictElement(required=True, parameter_form=SimpleLevels[float](
            title=Title('License utilization'), form_spec_template=Percentage(),
            level_direction=LevelDirection.UPPER, prefill_fixed_levels=DefaultValue((80.0, 90.0)))),
        'expiry': lifetime(),
    })


def certificates_form():
    """
    Build assigned-certificate lifetime thresholds.

    Input:
        None.
    Output:
        Dictionary containing lower expiry levels.
    """
    return Dictionary(elements={'expiry': lifetime()})


def idp_form():
    """
    Build IDP availability, connector and synchronization rules.

    Input:
        None.
    Output:
        Dictionary with configurable error states and sync-age thresholds.
    """
    return Dictionary(elements={
        'offline_state': state_choice('IDP offline'),
        'connector_state': state_choice('Connector offline'),
        'error_state': state_choice('Synchronization error'),
        'sync_age': DictElement(required=True, parameter_form=SimpleLevels[float](
            title=Title('Time since last successful synchronization'),
            form_spec_template=Float(unit_symbol='seconds'), level_direction=LevelDirection.UPPER,
            prefill_fixed_levels=DefaultValue((86400.0, 172800.0)))),
    })


def webfilter_form():
    """
    Build webfilter activation and imported-firewall synchronization rules.

    Input:
        None.
    Output:
        Configurable disabled/error states and maximum synchronization age for
        imported-firewall services and the Webfilter summary service.
    """
    return Dictionary(elements={
        'disabled_state': state_choice('Webfilter profile disabled', 'warn', True),
        'sync_disabled_state': state_choice('Imported firewall synchronization disabled', 'warn', True),
        'sync_error_state': state_choice('Imported firewall synchronization error'),
        'sync_age': DictElement(required=True, parameter_form=SimpleLevels[float](
            title=Title('Time since last successful firewall synchronization'),
            form_spec_template=Float(unit_symbol='seconds'), level_direction=LevelDirection.UPPER,
            prefill_fixed_levels=DefaultValue((86400.0, 172800.0)))),
    })


rule_spec_fortiems_webfilter = CheckParameters(name='fortiems_webfilter', title=Title('FortiClient EMS webfilter'),
    topic=Topic.APPLICATIONS, parameter_form=webfilter_form,
    condition=HostAndItemCondition(item_title=Title('Site / Webfilter service')))


rule_spec_fortiems_system = CheckParameters(name='fortiems_system', title=Title('FortiClient EMS auto upgrade'),
    topic=Topic.APPLICATIONS, parameter_form=system_form,
    condition=HostAndItemCondition(item_title=Title('Site / System')))
rule_spec_fortiems_license = CheckParameters(name='fortiems_license', title=Title('FortiClient EMS licenses'),
    topic=Topic.APPLICATIONS, parameter_form=license_form,
    condition=HostAndItemCondition(item_title=Title('Site / License')))
rule_spec_fortiems_certificates = CheckParameters(name='fortiems_certificates', title=Title('FortiClient EMS certificate expiry'),
    topic=Topic.APPLICATIONS, parameter_form=certificates_form,
    condition=HostAndItemCondition(item_title=Title('Site / Certificates')))
rule_spec_fortiems_idp = CheckParameters(name='fortiems_idp', title=Title('FortiClient EMS identity providers'),
    topic=Topic.APPLICATIONS, parameter_form=idp_form,
    condition=HostAndItemCondition(item_title=Title('Site / Identity provider')))
