"""
Build EMS special-agent commands with Checkmk secret references.
"""
from cmk.server_side_calls.v1 import Secret, SpecialAgentCommand, SpecialAgentConfig, noop_parser


def commands(params, host_config):
    """
    Support nested deployment options and previously saved flat on-prem rules.
    """
    deployment = params.get('mode', ('dedicated', {}))
    if isinstance(deployment, str):
        mode, options = deployment, {'tenants': params.get('tenants', [])}
    else:
        mode, options = deployment
    if mode not in ('dedicated', 'shared', 'cloud', 'cloud_dedicated', 'cloud_shared'):
        raise ValueError('Unsupported EMS deployment type')
    cloud = mode in ('cloud', 'cloud_dedicated', 'cloud_shared')
    shared = mode == 'shared'
    args = ['--timeout', str(params.get('timeout', 30))]
    if cloud:
        access_key = options['access_key']
        if not isinstance(access_key, Secret):
            raise TypeError('Expected a Checkmk Secret for the Access Key')
        args.extend(['--cloud', '--account-email', options['account_email'],
                     '--access-key-id', access_key])
    else:
        password = options.get('password', params.get('password'))
        if not isinstance(password, Secret):
            raise TypeError('Expected a Checkmk Secret')
        address = host_config.primary_ip_config.address or host_config.name
        args.extend(['--site', options.get('site', params.get('site', 'default')),
                     '--address', address, '--user', options.get('user', params.get('user')),
                     '--password-id', password,
                     '--auth-method', options.get('auth_method', params.get('auth_method', 'radius')),
                     '--port', str(params.get('port', 443))])
    if params.get('tls', 'verify') == 'skip':
        args.append('--no-cert-check')
    if shared:
        args.append('--shared')
        for tenant in options.get('tenants', []):
            args.extend(['--tenant', tenant])
    yield SpecialAgentCommand(command_arguments=args)


special_agent_fortiems = SpecialAgentConfig(name='fortiems', parameter_parser=noop_parser, commands_function=commands)
