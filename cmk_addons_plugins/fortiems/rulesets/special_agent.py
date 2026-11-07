"""
FortiClient EMS on-prem and cloud datasource configuration.
"""
from cmk.rulesets.v1 import Help, Title
from cmk.rulesets.v1.form_specs import (
    CascadingSingleChoice, CascadingSingleChoiceElement,
    DefaultValue, DictElement, Dictionary, Integer, List, Password, SingleChoice,
    SingleChoiceElement, String, migrate_to_password, validators,
)
from cmk.rulesets.v1.rule_specs import SpecialAgent, Topic


def migrate_parameters(value):
    """
    Move old top-level on-prem credentials/site selections into their branch.
    """
    if not isinstance(value, dict):
        return value
    result = dict(value)
    result.pop('address', None)
    deployment = result.pop('mode', ('dedicated', {}))
    if isinstance(deployment, str):
        mode, options = deployment, {}
    else:
        mode, saved = deployment
        options = dict(saved)
    if mode in ('dedicated', 'shared'):
        for key in ('user', 'password', 'auth_method'):
            if key in result:
                options.setdefault(key, result[key])
        options.setdefault('auth_method', 'radius')
        if mode == 'dedicated':
            options.setdefault('site', result.get('site', 'default'))
        elif 'tenants' in result:
            options.setdefault('tenants', result['tenants'])
    if mode in ('cloud', 'cloud_dedicated', 'cloud_shared'):
        mode = 'cloud'
        options.pop('site', None)
        options.pop('tenants', None)
    for key in ('user', 'password', 'auth_method', 'site', 'tenants'):
        result.pop(key, None)
    result['mode'] = (mode, options)
    return result


def deployment_form(*, cloud, shared):
    """
    Show only credentials and site options applicable to one deployment.
    """
    if cloud:
        elements = {
            'account_email': DictElement(required=True, parameter_form=String(
                title=Title('FortiCloud account email'),
                custom_validate=(validators.LengthInRange(min_value=1),))),
            'access_key': DictElement(required=True, parameter_form=Password(
                title=Title('FortiCloud Access Key'), migrate=migrate_to_password)),
        }
    else:
        elements = {
            'auth_method': DictElement(required=True, parameter_form=SingleChoice(
                title=Title('Authentication method'), prefill=DefaultValue('radius'),
                help_text=Help('RADIUS uses /api/v1/auth/radius; Local uses /api/v1/auth/signin. No automatic fallback.'),
                elements=[SingleChoiceElement(name='radius', title=Title('RADIUS login')),
                          SingleChoiceElement(name='local', title=Title('Local login'))])),
            'user': DictElement(required=True, parameter_form=String(
                title=Title('Username'), custom_validate=(validators.LengthInRange(min_value=1),))),
            'password': DictElement(required=True, parameter_form=Password(
                title=Title('Password'), migrate=migrate_to_password)),
        }
    if cloud:
        return Dictionary(elements=elements)
    if shared:
        elements['tenants'] = DictElement(parameter_form=List(
            title=Title('Sites to monitor (plus global)'),
            element_template=String(custom_validate=(validators.LengthInRange(min_value=1),)),
            help_text=Help('Empty or disabled: all sites including default plus global monitoring. Otherwise: selected sites plus global monitoring. Enter exact lowercase site names.')))
    else:
        elements['site'] = DictElement(required=True, parameter_form=String(
            title=Title('Site'), prefill=DefaultValue('default'),
            help_text=Help('Enter the exact lowercase site name. Use this site during on-prem login.'),
            custom_validate=(validators.LengthInRange(min_value=1),)))
    return Dictionary(elements=elements)


def parameter_form():
    """
    Offer on-prem Dedicated/Shared and Cloud with conditional credentials.
    """
    return Dictionary(migrate=migrate_parameters, elements={
        'mode': DictElement(required=True, parameter_form=CascadingSingleChoice(
            title=Title('Deployment type'), prefill=DefaultValue('dedicated'),
            elements=[
                CascadingSingleChoiceElement(name='dedicated', title=Title('On-prem Dedicated'),
                    parameter_form=deployment_form(cloud=False, shared=False)),
                CascadingSingleChoiceElement(name='shared', title=Title('On-prem Shared'),
                    parameter_form=deployment_form(cloud=False, shared=True)),
                CascadingSingleChoiceElement(name='cloud', title=Title('Cloud'),
                    parameter_form=deployment_form(cloud=True, shared=False)),
            ])),
        'port': DictElement(parameter_form=Integer(title=Title('HTTPS port'),
            prefill=DefaultValue(443), custom_validate=(validators.NetworkPort(),))),
        'timeout': DictElement(parameter_form=Integer(title=Title('Timeout per API request'),
            unit_symbol='seconds', prefill=DefaultValue(30),
            custom_validate=(validators.NumberInRange(min_value=1, max_value=300),))),
        'tls': DictElement(parameter_form=SingleChoice(title=Title('TLS certificate verification'),
            prefill=DefaultValue('verify'), elements=[
                SingleChoiceElement(name='verify', title=Title('Verify certificate')),
                SingleChoiceElement(name='skip', title=Title('Skip certificate verification'))])),
    })


rule_spec_fortiems = SpecialAgent(name='fortiems', title=Title('FortiClient EMS'),
    topic=Topic.NETWORKING, parameter_form=parameter_form)
