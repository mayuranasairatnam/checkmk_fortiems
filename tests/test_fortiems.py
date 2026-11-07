"""
Offline regression tests for RADIUS transport, tenant isolation and monitoring.

Checkmk API doubles validate the plugin contracts used here. A real Checkmk
installation and an EMS appliance are still required for deployment validation.
"""
import copy
from datetime import datetime, timedelta, timezone
from enum import Enum
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import types
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / 'cmk_addons_plugins/fortiems'


def load(name, path):
    """
    Load a Python module, including the extensionless special agent.

    Input:
        name: Module name used by the source loader.
        path: Path to the Python source file.

    Output:
        Loaded module object.

    """
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    loader.exec_module(module)
    return module


class State(Enum):
    OK, WARN, CRIT, UNKNOWN = range(4)


class Record:
    def __init__(self, **kwargs):
        """
        Store supplied attributes on an offline Checkmk API record.

        Input:
            self: Record instance being initialized.
            **kwargs: Additional attributes stored on the record.

        Output:
            None. Initializes the instance attributes.

        """
        self.__dict__.update(kwargs)


class Result(Record):
    """
    Enforce Checkmk's nonempty result-text contract, including details.
    """
    def __init__(self, *, state, summary, details=None):
        """
        Validate result text and store an offline Checkmk result record.

        Input:
            self: Record instance being initialized.
            state: Monitoring state assigned to the result.
            summary: Nonempty single-line result summary.
            details: Optional nonempty details; None reuses the summary.

        Output:
            None. Initializes the instance attributes.

        """
        for name, value in (('summary', summary), ('details', details)):
            if value is None and name == 'details':
                continue
            if not isinstance(value, str):
                raise TypeError(f'{name} must be a string or None')
            if not value:
                raise ValueError(f'{name} must not be empty')
        if '\n' in summary:
            raise ValueError('Newlines are not allowed in summary')
        super().__init__(state=state, summary=summary, details=details or summary)


class Metric(Record):
    def __init__(self, name, value, **kwargs):
        """
        Create an offline Checkmk metric record containing a name and value.

        Input:
            self: Record instance being initialized.
            name: Metric name.
            value: Measured numeric value stored on the metric.
            **kwargs: Additional attributes stored on the record.

        Output:
            None. Initializes the instance attributes.

        """
        super().__init__(name=name, value=value, **kwargs)


def levels(value, *, levels_upper=None, levels_lower=None, metric_name=None, label='', render_func=str, **kwargs):
    """
    Evaluate fixed upper and lower thresholds using Checkmk API doubles.

    Input:
        value: Numeric measurement to evaluate.
        levels_upper: Optional fixed upper warning and critical levels.
        levels_lower: Optional fixed lower warning and critical levels.
        metric_name: Optional name of the emitted metric.
        label: Label prepended to the result summary.
        render_func: Callable formatting the measurement.
        **kwargs: Additional API options accepted for compatibility.

    Output:
        Iterator yielding a state record and, when requested, a metric.

    """
    state = State.OK
    for setting, lower in ((levels_upper, False), (levels_lower, True)):
        if setting is None or setting[0] == 'no_levels':
            continue
        assert setting[0] == 'fixed'
        warn, crit = setting[1]
        if (value < crit if lower else value >= crit):
            state = State.CRIT
        elif state != State.CRIT and (value < warn if lower else value >= warn):
            state = State.WARN
    yield Record(state=state, summary=f'{label}: {render_func(value)}')
    if metric_name:
        yield Metric(metric_name, value)


def install_doubles():
    """
    Register isolated Checkmk API doubles in sys.modules.

    Input:
        None.

    Output:
        None. Subsequent imports resolve to the registered API doubles.

    """
    module = types.ModuleType('cmk.agent_based.v2')
    for name, value in {'AgentSection': Record, 'CheckPlugin': Record, 'Metric': Metric,
                         'Result': Result, 'Service': Record, 'State': State, 'check_levels': levels}.items():
        setattr(module, name, value)
    sys.modules['cmk.agent_based.v2'] = module
    calls = types.ModuleType('cmk.server_side_calls.v1')
    calls.Secret = type('Secret', (), {})
    calls.SpecialAgentCommand = calls.SpecialAgentConfig = Record
    calls.noop_parser = lambda value: value
    sys.modules['cmk.server_side_calls.v1'] = calls


install_doubles()
agent = load('ems_agent', FAMILY / 'libexec/agent_fortiems')
checks = importlib.import_module('cmk_addons.plugins.fortiems.agent_based.fortiems')
FEATURE_NAMES = ('api', 'system', 'license', 'certificates', 'endpoints', 'idp', 'webfilter')
FEATURES = [importlib.import_module('cmk_addons.plugins.fortiems.agent_based.fortiems_' + name)
            for name in FEATURE_NAMES]
calls = load('ems_calls', FAMILY / 'server_side_calls/fortiems.py')


def fixture():
    """
    Build EMS response fixtures with future license and certificate expiry dates.

    Input:
        None.

    Output:
        Dictionary of synthetic responses indexed by endpoint category.

    """
    future = (datetime.now(timezone.utc) + timedelta(days=100)).date().isoformat()
    return {
        'info': {'name': 'EMS-01', 'system_time': '2026-10-23 12:00:00'},
        'settings': {'auto_upgrade_enabled': True, 'fct_repackager_upload_region': 'North America'},
        'consts': {'System': {'VERSION_FULL': '7.4.5'}},
        'license': {'sn': 'EMS123', 'vdom_seats': {'ztna': 100, 'epp': 0, 'sase': 0},
                    'used': {'ztna': 80, 'epp': 0, 'sase': 0},
                    'licenses': [{'type': 'ZTNA', 'expiry_date': future},
                                 {'type': 'EPP', 'expiry_date': future}]},
        'certificates': [{'name': 'EMS TLS', 'assigned_to': ['web'], 'expiry_date': future}],
        'windows': [{'name': '7.4.3', 'value': 12}, {'name': '7.4.4', 'value': 8}],
        'macos': [],
        'webfilter': {'local': [], 'chrome': [], 'imported': []},
        'idps': [{'id': 7, 'connection_info': {'alias': 'Azure-AD', 'conn_online': True},
                  'domain_info': {'name': 'example.test'}, 'total_devices': 20, 'total_users': 30,
                  'status': {'online': True, 'sync_progress': 100, 'last_error': '',
                             'last_success_enumerated': datetime.now(timezone.utc).isoformat()}}],
    }


def section(data=None, shared=False):
    """
    Wrap EMS fixtures in the special agent section schema.

    Input:
        data: EMS data to wrap; None uses the standard fixture.
        shared: Whether the section represents Shared EMS.

    Output:
        Section dictionary containing schema, errors and tenant data.

    """
    return {'schema': 1, 'shared': shared, 'errors': [],
            'tenants': {'customer-123': {'errors': [], 'data': fixture() if data is None else data}}}


class TransportTests(unittest.TestCase):
    def setUp(self):
        """
        Prepare an isolated client and mocked transport for each test.

        Input:
            self: Test case instance receiving client, response and cleanup state.

        Output:
            None. Registers cleanup callbacks and initializes the test fixtures.

        """
        self.sleep = patch.object(agent.time, 'sleep').start()
        self.addCleanup(patch.stopall)
        self.client = agent.Client('ems.example.test', timeout=9)
        self.response = Mock(status_code=200)
        self.response.json.return_value = {'data': {}}
        self.client.session.request = Mock(return_value=self.response)

    def tearDown(self):
        """
        Close the client session after each transport test.

        Input:
            self: Test case instance containing the client session.

        Output:
            None. Releases the session resources.

        """
        self.client.session.close()

    def test_request_origin_matches_diagnostic_for_default_and_custom_ports(self):
        """
        Verify request origin matches diagnostic for default and custom ports.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for host, port, origin in (
                ('ems.example.test', 443, 'https://ems.example.test'),
                ('ems.example.test', 8443, 'https://ems.example.test:8443'),
                ('192.0.2.10', 443, 'https://192.0.2.10'),
                ('2001:db8::1', 443, 'https://[2001:db8::1]'),
                ('2001:db8::1', 8443, 'https://[2001:db8::1]:8443')):
            with self.subTest(host=host, port=port):
                client = agent.Client(host, port=port)
                try:
                    client.session.cookies.set('csrftoken', 'token')
                    client.session.request = Mock(return_value=self.response)
                    client.switch('example')
                    call = client.session.request.call_args
                    self.assertEqual(call.args, ('POST', origin + '/api/v1/session/update'))
                    self.assertEqual(call.kwargs['headers']['origin'], origin)
                    self.assertEqual(call.kwargs['headers']['referer'], origin + '/')
                    self.assertEqual(call.kwargs['headers']['x-csrftoken'], 'token')
                finally:
                    client.session.close()

    def test_radius_payload_cookie_and_headers(self):
        """
        Verify RADIUS payload cookie and headers.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'first-token')
        self.client.login('monitoring', 'secret', 'site-a')
        args, kwargs = self.client.session.request.call_args
        self.assertEqual(args, ('POST', 'https://ems.example.test/api/v1/auth/radius'))
        self.assertEqual(kwargs['json'], {'name': 'monitoring', 'password': 'secret', 'site': 'site-a'})
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(kwargs['timeout'], 9)
        self.client.get('/api/v1/license/get')
        self.assertEqual(self.client.session.request.call_args.kwargs['headers']['x-csrftoken'], 'first-token')
        self.assertEqual(self.client.session.request.call_args.kwargs['headers']['ems-call-type'], '2')
        self.client.session.cookies.set('csrftoken', 'rotated-token')
        self.client.switch('site-b')
        self.assertEqual(self.client.session.request.call_args.kwargs['json'], {'site': 'site-b'})
        self.assertEqual(self.client.session.request.call_args.kwargs['headers']['x-csrftoken'], 'rotated-token')
        self.assertTrue(self.client.session.verify)
        self.assertFalse(self.client.session.trust_env)

    def test_shared_workflow_discovers_and_collects_all_customer_sites(self):
        """
        Verify shared workflow discovers and collects all customer sites.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for method, endpoint, prelogin_cookie in (('radius', 'radius', False),
                                                   ('local', 'signin', True),
                                                   ('local', 'signin', False)):
            with self.subTest(method=method, prelogin_cookie=prelogin_cookie):
                self.client.session.cookies.clear()
                data = fixture()
                paths = {path: data[key] for key, (path, _) in agent.ENDPOINTS.items()}
                switched = []

                def request(verb, url, **kwargs):
                    """
                    Simulate HTTP responses and state changes for the surrounding test scenario.

                    Input:
                        verb: HTTP method requested by the client.
                        url: Target URL used to select the mocked response.
                        **kwargs: Request headers, JSON payload and transport options.

                    Output:
                        Mock HTTP response; assertions validate the expected request contract.

                    """
                    path = url.removeprefix(self.client.base_url)
                    headers = kwargs['headers']
                    if path == '/':
                        self.assertEqual(method, 'local')
                        self.assertEqual(verb, 'GET')
                        if prelogin_cookie:
                            self.client.session.cookies.set('csrftoken', 'prelogin-token')
                        response = Mock(status_code=200)
                        response.json.side_effect = ValueError('HTML login page')
                        return response
                    if path == '/api/v1/auth/' + endpoint:
                        self.assertEqual(verb, 'POST')
                        self.assertEqual(kwargs['json'], {'name': 'monitoring', 'password': 'secret'})
                        self.assertEqual(headers['origin'], self.client.base_url)
                        if method == 'local' and prelogin_cookie:
                            self.assertEqual(headers['x-csrftoken'], 'prelogin-token')
                        else:
                            self.assertNotIn('x-csrftoken', headers)
                        self.client.session.cookies.set('csrftoken', 'login-token')
                        body = {}
                    elif path == '/api/v1/sites/index':
                        self.assertEqual(verb, 'GET')
                        self.assertEqual(headers['ems-call-type'], '1')
                        self.assertEqual(headers['x-csrftoken'], 'login-token')
                        body = [{'name': name} for name in ('default', 'global', 'Example', 'example', 'Customer-123')]
                    elif path == '/api/v1/session/update':
                        self.assertEqual(verb, 'POST')
                        self.assertEqual(headers['ems-call-type'], '2')
                        self.assertEqual(headers['x-csrftoken'], switched[-1] if switched else 'login-token')
                        switched.append(kwargs['json']['site'])
                        self.client.session.cookies.set('csrftoken', switched[-1])
                        body = {}
                    else:
                        self.assertEqual(verb, 'GET')
                        self.assertEqual(headers['ems-call-type'], '2')
                        self.assertEqual(headers['x-csrftoken'], switched[-1])
                        body = data['consts'] if '/consts/' in path else paths[path]
                    response = Mock(status_code=200)
                    response.json.return_value = {'data': body}
                    return response

                self.client.session.request.side_effect = request
                result = agent.collect(self.client, 'monitoring', 'secret', 'default',
                                       shared=True, auth_method=method)
                self.assertEqual(result['errors'], [])
                self.assertEqual(switched, ['global', 'Customer-123', 'Example', 'default', 'example'])
                self.assertEqual(result['global']['errors'], [])
                self.assertEqual(set(result['tenants']), set(switched) - {'global'})
                for record in result['tenants'].values():
                    self.assertEqual(record['errors'], [])
                    self.assertEqual(record['data']['license']['sn'], 'EMS123')

    def test_missing_csrf_rejects_login(self):
        """
        Verify missing CSRF rejects login.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for method in ('radius', 'local'):
            with self.subTest(method=method), self.assertRaisesRegex(agent.APIError, 'csrftoken'):
                self.client.login('user', 'secret', auth_method=method)

    def test_default_site_is_discovered_even_without_customer_sites(self):
        """
        Verify default site is discovered even without customer sites.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'token')
        self.response.json.return_value = {'data': [{'name': 'global'}, {'name': 'default'}]}
        self.assertEqual(self.client.tenants(), ['default'])

    def test_successful_idp_envelope_without_data_is_an_empty_inventory(self):
        """
        Verify successful IDP envelope without data is an empty inventory.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'token')
        data = fixture()
        paths = {path: data[key] for key, (path, _) in agent.ENDPOINTS.items()}
        def request(method, url, **kwargs):
            """
            Simulate HTTP responses and state changes for the surrounding test scenario.

            Input:
                method: HTTP method requested by the client.
                url: Target URL used to select the mocked response.
                **kwargs: Request headers, JSON payload and transport options.

            Output:
                Mock HTTP response; assertions validate the expected request contract.

            """
            path = url.removeprefix(self.client.base_url)
            response = Mock(status_code=200)
            body = {'result': {'retval': 1, 'message': None}}
            if '/auth/' not in path and path != '/api/v1/idps/index':
                body['data'] = data['consts'] if '/consts/' in path else paths[path]
            response.json.return_value = body
            return response
        self.client.session.request.side_effect = request
        value = agent.collect(self.client, 'monitoring', 'secret')
        self.assertEqual(value['tenants']['default']['data']['idps'], [])
        self.assertEqual(value['tenants']['default']['errors'], [])
        plugin = checks.check_plugin_fortiems_idp_summary
        item = list(plugin.discovery_function(value))[0].item
        output = list(plugin.check_function(item, {}, value))
        self.assertEqual(output[0].state, State.OK)
        self.assertEqual(output[0].summary, 'No identity providers returned for this site')
        self.assertEqual(next(entry.value for entry in output if isinstance(entry, Metric)), 0)
        self.assertEqual(list(checks.check_plugin_fortiems_idp.discovery_function(value)), [])

    def test_missing_idp_data_requires_confirmed_success(self):
        """
        Verify missing IDP data requires confirmed success.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'token')
        for body in ({}, {'result': {}}, {'result': {'retval': 0}},
                     {'result': {'retval': 1}, 'success': False},
                     {'result': {'retval': 1}, 'error': 'private'}):
            with self.subTest(body=body):
                self.response.json.return_value = body
                with self.assertRaises(agent.APIError):
                    self.client.get('/api/v1/idps/index', list)
        self.response.json.return_value = {'result': {'retval': 1}}
        with self.assertRaises(agent.APIError):
            self.client.get('/api/v1/server_certificates/index', list)

    def test_idp_invalid_data_is_not_silently_treated_as_empty(self):
        """
        Verify IDP invalid data is not silently treated as empty.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'token')
        for data, received in ((None, 'NoneType'), ({}, 'dict')):
            with self.subTest(data=data):
                self.response.json.return_value = {'result': {'retval': 1}, 'data': data}
                with self.assertRaisesRegex(agent.APIError, f'expected list, received {received}'):
                    self.client.get('/api/v1/idps/index', list)
        self.response.json.return_value = {'result': {'retval': 1}, 'data': []}
        self.assertEqual(self.client.get('/api/v1/idps/index', list), [])

    def test_local_signin_without_prelogin_cookie_for_dedicated_and_shared(self):
        """
        Verify local signin without prelogin cookie for dedicated and shared.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for site in ('Example', None):
            with self.subTest(site=site):
                self.client.session.cookies.clear()
                self.client.session.request.reset_mock()
                def request(method, url, **kwargs):
                    """
                    Simulate HTTP responses and state changes for the surrounding test scenario.

                    Input:
                        method: HTTP method requested by the client.
                        url: Target URL used to select the mocked response.
                        **kwargs: Request headers, JSON payload and transport options.

                    Output:
                        Mock HTTP response; assertions validate the expected request contract.

                    """
                    if method == 'POST':
                        self.assertTrue(url.endswith('/auth/signin'))
                        self.assertNotIn('x-csrftoken', kwargs['headers'])
                        self.assertEqual(kwargs['headers']['origin'], self.client.base_url)
                        self.assertEqual(kwargs['json'], dict(name='monitoring', password='secret',
                                                             **({'site': site} if site else {})))
                        self.client.session.cookies.set('csrftoken', 'signin-token')
                        self.client.session.cookies.set('sessionid', 'session-token')
                    return self.response
                self.client.session.request.side_effect = request
                self.client.login('monitoring', 'secret', site=site, auth_method='local')
                self.assertEqual(self.client.session.cookies.get('csrftoken'), 'signin-token')
                self.assertEqual([call.args[0] for call in self.client.session.request.call_args_list],
                                 ['GET', 'POST'])

    def test_local_login_preserves_payload_cookies_and_csrf(self):
        """
        Verify local login preserves payload cookies and CSRF.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'local-token')
        self.client.login('monitoring', 'secret', 'customer-site', auth_method='local')
        args, kwargs = self.client.session.request.call_args
        self.assertEqual(args, ('POST', 'https://ems.example.test/api/v1/auth/signin'))
        self.assertEqual(kwargs['json'], {'name': 'monitoring', 'password': 'secret', 'site': 'customer-site'})
        self.assertEqual(kwargs['headers']['ems-call-type'], '2')
        self.assertEqual(kwargs['headers']['x-csrftoken'], 'local-token')
        self.assertEqual(kwargs['headers']['origin'], self.client.base_url)
        self.client.get('/api/v1/license/get')
        self.assertEqual(self.client.session.request.call_args.kwargs['headers']['x-csrftoken'], 'local-token')

    def test_login_failure_does_not_try_another_method(self):
        """
        Verify login failure does not try another method.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for method, path in (('radius', 'radius'), ('local', 'signin')):
            self.client.session.cookies.clear()
            self.client.session.request.reset_mock()

            def request(verb, url, **kwargs):
                """
                Simulate HTTP responses and state changes for the surrounding test scenario.

                Input:
                    verb: HTTP method requested by the client.
                    url: Target URL used to select the mocked response.
                    **kwargs: Request headers, JSON payload and transport options.

                Output:
                    Mock HTTP response; assertions validate the expected request contract.

                """
                if verb == 'GET':
                    self.client.session.cookies.set('csrftoken', 'prelogin-token')
                    return Mock(status_code=200)
                return Mock(status_code=401)

            self.client.session.request.side_effect = request
            with self.assertRaises(agent.APIError):
                self.client.login('user', 'secret', auth_method=method)
            posts = [call for call in self.client.session.request.call_args_list if call.args[0] == 'POST']
            self.assertEqual(len(posts), 1)
            self.assertTrue(posts[0].args[1].endswith('/auth/' + path))

    def test_local_bootstrap_html_cookie_rotation_and_followup(self):
        """
        Verify local bootstrap html cookie rotation and followup.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        def request(verb, url, **kwargs):
            """
            Simulate HTTP responses and state changes for the surrounding test scenario.

            Input:
                verb: HTTP method requested by the client.
                url: Target URL used to select the mocked response.
                **kwargs: Request headers, JSON payload and transport options.

            Output:
                Mock HTTP response; assertions validate the expected request contract.

            """
            if verb == 'GET' and url.endswith('/'):
                self.client.session.cookies.set('csrftoken', 'prelogin-token')
                response = Mock(status_code=200)
                response.json.side_effect = ValueError('HTML login page')
                return response
            if verb == 'POST':
                self.assertEqual(kwargs['headers']['x-csrftoken'], 'prelogin-token')
                self.assertEqual(self.client.session.cookies.get('csrftoken'), 'prelogin-token')
                self.assertEqual(kwargs['headers']['origin'], self.client.base_url)
                self.client.session.cookies.set('csrftoken', 'authenticated-token')
            else:
                self.assertEqual(kwargs['headers']['x-csrftoken'], 'authenticated-token')
            return self.response

        self.client.session.request.side_effect = request
        self.client.login('user', 'secret', site=None, auth_method='local')
        self.client.get('/api/v1/license/get')
        self.assertEqual([call.args[0] for call in self.client.session.request.call_args_list],
                         ['GET', 'POST', 'GET'])

    def test_local_bootstrap_failure_does_not_send_credentials(self):
        """
        Verify local bootstrap failure does not send credentials.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for error in (requests.exceptions.Timeout('private'), requests.exceptions.SSLError('private')):
            with self.subTest(error=type(error).__name__):
                self.client.session.request.reset_mock()
                self.client.session.request.side_effect = error
                with self.assertRaises(agent.APIError) as raised:
                    self.client.login('user', 'secret', auth_method='local')
                self.assertNotIn('private', str(raised.exception))
                expected = 1 if isinstance(error, requests.exceptions.SSLError) else 3
                self.assertEqual(self.client.session.request.call_count, expected)
                for call in self.client.session.request.call_args_list:
                    self.assertEqual(call.args[0], 'GET')
                    self.assertIsNone(call.kwargs['json'])

    def test_transient_site_discovery_recovers_with_bounded_retries(self):
        """
        Verify transient site discovery recovers with bounded retries.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'token')
        unavailable = Mock(status_code=503)
        self.response.json.return_value = {'result': {'retval': 1}, 'data': [{'name': 'Example'}]}
        self.client.session.request.side_effect = [requests.exceptions.Timeout('private'), unavailable, self.response]
        self.assertEqual(self.client.tenants(), ['Example'])
        self.assertEqual(self.client.session.request.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_transient_retry_limit_and_authentication_errors(self):
        """
        Verify transient retry limit and authentication errors.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'token')
        for status, attempts in ((503, 3), (429, 3), (401, 1), (403, 1), (404, 1)):
            with self.subTest(status=status):
                self.client.session.request.reset_mock()
                self.response.status_code = status
                with self.assertRaises(agent.APIError):
                    self.client.tenants()
                self.assertEqual(self.client.session.request.call_count, attempts)

    def test_login_post_is_not_retried_on_transient_error(self):
        """
        Verify login post is not retried on transient error.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.response.status_code = 503
        with self.assertRaises(agent.APIError):
            self.client.login('user', 'secret', auth_method='radius')
        self.client.session.request.assert_called_once()

    def test_http_success_cannot_hide_failed_tenant_switch(self):
        """
        Verify HTTP success cannot hide failed tenant switch.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'token')
        self.response.json.return_value = {'result': {'retval': 0, 'message': 'private'}, 'data': {}}
        with self.assertRaisesRegex(agent.APIError, 'result.retval') as raised:
            self.client.switch('Example')
        self.assertNotIn('private', str(raised.exception))
        self.client.session.request.assert_called_once()

    def test_failed_ems_switch_prevents_queries_for_wrong_tenant(self):
        """
        Verify failed EMS switch prevents queries for wrong tenant.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        client = agent.Client('ems.example.test')
        def request(method, url, **kwargs):
            """
            Simulate HTTP responses and state changes for the surrounding test scenario.

            Input:
                method: HTTP method requested by the client.
                url: Target URL used to select the mocked response.
                **kwargs: Request headers, JSON payload and transport options.

            Output:
                Mock HTTP response; assertions validate the expected request contract.

            """
            response = Mock(status_code=200)
            if url.endswith('/auth/radius'):
                client.session.cookies.set('csrftoken', 'token')
                response.json.return_value = {'result': {'retval': 1}}
            elif url.endswith('/sites/index'):
                response.json.return_value = {'result': {'retval': 1}, 'data': [{'name': 'Example'}]}
            else:
                self.assertTrue(url.endswith('/session/update'))
                response.json.return_value = {'result': {'retval': 0}}
            return response
        client.session.request = Mock(side_effect=request)
        result = agent.collect(client, 'user', 'secret', shared=True)
        self.assertEqual(result['tenants']['Example']['data'], {})
        self.assertIn('result.retval', result['tenants']['Example']['errors'][0])
        self.assertEqual(client.session.request.call_count, 4)
        self.assertTrue(result['global']['errors'])

    def test_invalid_authentication_method_makes_no_request(self):
        """
        Verify invalid authentication method makes no request.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        with self.assertRaisesRegex(agent.APIError, 'Unsupported authentication'):
            self.client.login('user', 'secret', auth_method='unsupported')
        self.client.session.request.assert_not_called()

    def test_api_and_http_failures_are_sanitized(self):
        """
        Verify API and HTTP failures are sanitized.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'token')
        for status, body in [(403, {'secret': 'password'}), (302, {}), (200, {'success': False}),
                             (200, {'error': 'secret'}), (200, {'code': -1}), (200, None),
                             (200, {'data': None}), (200, {'data': {'x': float('nan')}})]:
            with self.subTest(status=status, body=body):
                self.response.status_code = status
                self.response.json.return_value = body
                with self.assertRaises(agent.APIError) as raised:
                    self.client.get('/api/v1/license/get')
                self.assertNotIn('secret', str(raised.exception))

    def test_denied_requests_identify_endpoint_without_query_or_body(self):
        """
        Verify denied requests identify endpoint without query or body.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'secret-token')
        for status in (401, 403):
            with self.subTest(status=status):
                self.response.status_code = status
                self.response.json.return_value = {'password': 'secret-body'}
                with self.assertRaises(agent.APIError) as raised:
                    self.client.get('/api/v1/sites/index?secret-query=value')
                message = str(raised.exception)
                self.assertIn(f'HTTP {status} GET /api/v1/sites/index:', message)
                self.assertNotIn('secret', message)

    def test_invalid_json_timeout_tls_network(self):
        """
        Verify invalid JSON timeout TLS network.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'token')
        self.response.json.side_effect = ValueError('sensitive response')
        with self.assertRaisesRegex(agent.APIError, 'Invalid JSON'):
            self.client.get('/x')
        for error, message in [(requests.exceptions.Timeout('secret'), 'timeout'),
                               (requests.exceptions.SSLError('secret'), 'TLS'),
                               (requests.exceptions.ConnectionError('secret'), 'unreachable')]:
            self.client.session.request.side_effect = error
            with self.assertRaisesRegex(agent.APIError, message):
                self.client.get('/x')

    def test_site_discovery_uses_management_context_and_no_name_regex(self):
        """
        Verify site discovery uses management context and no name regex.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.client.session.cookies.set('csrftoken', 'token')
        self.response.json.return_value = {'data': [{'name': name} for name in ('global', 'default', 'Example', 'example', 'Company', 'test-123')]}
        self.assertEqual(self.client.tenants(), ['Company', 'Example', 'default', 'example', 'test-123'])
        self.assertEqual(self.client.session.request.call_args.kwargs['headers']['ems-call-type'], '1')


class CollectionTests(unittest.TestCase):
    def client(self):
        """
        Create a mocked EMS client backed by the standard response fixtures.

        Input:
            self: Test case instance providing the helper and its fixtures.

        Output:
            Mock client exposing fixture queries and two discoverable sites.

        """
        client = Mock()
        responses = fixture()
        paths = {path: responses[key] for key, (path, expected) in agent.ENDPOINTS.items()}
        def get(path, expected=dict):
            """
            Serve endpoint fixtures for the surrounding collection scenario.

            Input:
                path: EMS API path to query.
                expected: Response type accepted for client API compatibility.

            Output:
                Synthetic endpoint data; configured failure paths raise APIError.

            """
            return responses['consts'] if '/consts/' in path else paths[path]
        client.get.side_effect = get
        client.tenants.return_value = ['a', 'b']
        return client

    def test_dedicated_defaults_no_switch(self):
        """
        Verify dedicated defaults no switch.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        client = self.client()
        result = agent.collect(client, 'user', 'secret')
        client.login.assert_called_once_with('user', 'secret', 'default', auth_method='radius')
        client.tenants.assert_not_called()
        client.switch.assert_not_called()
        client.session.close.assert_called_once()
        self.assertEqual(list(result['tenants']), ['default'])
        self.assertEqual(result['tenants']['default']['errors'], [])

    def test_local_authentication_for_dedicated_and_shared(self):
        """
        Verify local authentication for dedicated and shared.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for shared in (False, True):
            with self.subTest(shared=shared):
                client = self.client()
                result = agent.collect(client, 'user', 'secret', 'login-site', shared=shared, auth_method='local')
                client.login.assert_called_once_with('user', 'secret', None if shared else 'login-site', auth_method='local')
                self.assertFalse(result['errors'])
                self.assertEqual(set(result['tenants']), {'a', 'b'} if shared else {'login-site'})

    def test_global_services_once_for_all_or_selected_sites(self):
        """
        Verify global services once for all or selected sites.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for selected, expected in (((), {'a', 'b'}), (['b'], {'b'})):
            with self.subTest(selected=selected):
                client = self.client()
                value = agent.collect(client, 'user', 'secret', shared=True, selected=selected)
                self.assertEqual(set(value['tenants']), expected)
                self.assertEqual(checks.parse_fortiems([[json.dumps(value)]]), value)
                system = checks.check_plugin_fortiems_system
                items = [entry.item for entry in system.discovery_function(value)]
                self.assertEqual(len(items), 4 + len(expected))
                global_items = [item for item in items if item.startswith('["global"]')]
                self.assertEqual(len(global_items), 4)
                self.assertNotIn('["global"] System Package Region', items)
                for name in expected:
                    self.assertIn(f'["{name}"] System Package Region', items)
                serial = '["global"] System Serial Number'
                output = list(system.check_function(serial, system.check_default_parameters, value))
                self.assertEqual(output[0].state, State.OK)
                self.assertEqual(output[0].summary, 'EMS123')
                certificates = checks.check_plugin_fortiems_certificates
                self.assertEqual([entry.item for entry in certificates.discovery_function(value)],
                                 ['["global"] Certificates'])
                license_items = [entry.item for entry in checks.check_plugin_fortiems_license.discovery_function(value)]
                self.assertEqual(len(license_items), len(expected))
                self.assertFalse(any(item.startswith('["global"]') for item in license_items))
                for record in value['tenants'].values():
                    self.assertFalse({'info', 'certificates', 'consts'} & record['data'].keys())
                info_calls = [call for call in client.get.call_args_list if '/system/info' in call.args[0]]
                self.assertEqual(len(info_calls), 1)

    def test_shared_package_region_uses_each_sites_settings(self):
        """
        Verify shared package region uses each sites settings.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        client = self.client()
        active = [None]
        client.switch.side_effect = lambda name: active.__setitem__(0, name)
        original = client.get.side_effect
        def get(path, expected=dict):
            """
            Serve endpoint fixtures for the surrounding collection scenario.

            Input:
                path: EMS API path to query.
                expected: Response type accepted for client API compatibility.

            Output:
                Synthetic endpoint data; configured failure paths raise APIError.

            """
            if path == '/api/v1/settings/server/get':
                return {'auto_upgrade_enabled': True,
                        'fct_repackager_upload_region': {'global': 'Global value',
                                                        'a': 'Europe', 'b': 'North America'}[active[0]]}
            return original(path, expected)
        client.get.side_effect = get
        value = agent.collect(client, 'user', 'secret', shared=True)
        self.assertNotIn('fct_repackager_upload_region', value['global']['data']['settings'])
        system = checks.check_plugin_fortiems_system
        for name, region in (('a', 'Europe'), ('b', 'North America')):
            output = list(system.check_function(f'["{name}"] System Package Region',
                                               system.check_default_parameters, value))
            self.assertEqual(output[0].state, State.OK)
            self.assertEqual(output[0].summary, region)
            self.assertNotIn('auto_upgrade_enabled', value['tenants'][name]['data']['settings'])

    def test_shared_empty_idp_inventory_is_ok_with_valid_checkmk_details(self):
        """
        Verify shared empty IDP inventory is ok with valid checkmk details.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        client = self.client()
        client.tenants.return_value = ['customerb']
        original = client.get.side_effect
        client.get.side_effect = lambda path, expected=dict: [] if path == '/api/v1/idps/index' else original(path, expected)
        value = agent.collect(client, 'user', 'secret', shared=True)
        value = checks.parse_fortiems([[json.dumps(value)]])
        plugin = checks.check_plugin_fortiems_idp_summary
        output = list(plugin.check_function('["customerb"] Identity Providers', {}, value))
        self.assertEqual(output[0].state, State.OK)
        self.assertEqual(output[0].summary, 'No identity providers returned for this site')
        self.assertTrue(output[0].details)
        self.assertEqual(next(entry.value for entry in output if isinstance(entry, Metric)), 0)
        self.assertEqual(list(checks.check_api(value))[0].state, State.OK)

    def test_global_failure_does_not_hide_healthy_sites(self):
        """
        Verify global failure does not hide healthy sites.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        client = self.client()
        def switch(name):
            """
            Simulate a rejected site switch for the isolation scenario.

            Input:
                name: Exact site name requested by the collector.

            Output:
                None for an allowed switch; raises APIError for the rejected site.

            """
            if name == 'global':
                raise agent.APIError('global permission denied')
        client.switch.side_effect = switch
        value = agent.collect(client, 'user', 'secret', shared=True, selected=['b'])
        self.assertEqual(value['global']['data'], {})
        self.assertEqual(value['tenants']['b']['errors'], [])
        self.assertEqual(list(checks.check_api(value))[0].state, State.CRIT)
        system = checks.check_plugin_fortiems_system
        result = list(system.check_function('["global"] System Hostname', system.check_default_parameters, value))
        self.assertEqual(result[0].state, State.UNKNOWN)

    def test_failed_switch_cannot_contaminate_tenant_data(self):
        """
        Verify failed switch cannot contaminate tenant data.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        client = self.client()
        def switch(name):
            """
            Simulate a rejected site switch for the isolation scenario.

            Input:
                name: Exact site name requested by the collector.

            Output:
                None for an allowed switch; raises APIError for the rejected site.

            """
            if name == 'a':
                raise agent.APIError('switch denied')
        client.switch.side_effect = switch
        result = agent.collect(client, 'user', 'secret', shared=True)
        self.assertEqual(result['tenants']['a']['data'], {})
        self.assertTrue(result['tenants']['a']['errors'])
        self.assertEqual(result['tenants']['b']['data']['license']['sn'], 'EMS123')
        self.assertEqual(client.get.call_count, 11)  # Five global and six successful site queries.

    def test_login_failure_is_identified_and_stops_discovery(self):
        """
        Verify login failure is identified and stops discovery.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for method in ('local', 'radius'):
            with self.subTest(method=method):
                client = self.client()
                client.login.side_effect = agent.APIError('HTTP 401')
                result = agent.collect(client, 'user', 'secret', shared=True, auth_method=method)
                self.assertEqual(result['errors'], [f'{method} login: HTTP 401'])
                self.assertEqual(result['tenants'], {})
                client.tenants.assert_not_called()
                client.switch.assert_not_called()
                client.get.assert_not_called()
                client.session.close.assert_called_once()

    def test_discovery_failure_does_not_fall_back_to_default(self):
        """
        Verify discovery failure does not fall back to default.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        client = self.client()
        client.tenants.side_effect = agent.APIError('Discovery denied')
        result = agent.collect(client, 'user', 'secret', shared=True)
        self.assertEqual(result['errors'], ['Site discovery: Discovery denied'])
        self.assertFalse(result['tenants'])
        client.get.assert_not_called()
        client.session.close.assert_called_once()

    def test_selected_tenant_missing_does_not_hide_other_results(self):
        """
        Verify selected tenant missing does not hide other results.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        client = self.client()
        result = agent.collect(client, 'user', 'secret', shared=True, selected=['b', 'missing'])
        self.assertTrue(result['errors'])
        self.assertEqual(list(result['tenants']), ['b'])
        self.assertEqual([call.args[0] for call in client.switch.call_args_list], ['global', 'b'])

    def test_empty_shared_discovery_is_an_error_for_both_login_methods(self):
        """
        Verify empty shared discovery is an error for both login methods.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for method in ('local', 'radius'):
            with self.subTest(method=method):
                client = self.client()
                client.tenants.return_value = []
                result = agent.collect(client, 'user', 'secret', shared=True, auth_method=method)
                self.assertIn('No monitoring sites discovered', result['errors'][0])
                self.assertEqual(result['tenants'], {})
                client.switch.assert_called_once_with('global')
                self.assertEqual(result['global']['errors'], [])
                client.session.close.assert_called_once()

    def test_tenant_selection_reports_exact_discovered_names(self):
        """
        Verify tenant selection reports exact discovered names.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        client = self.client()
        client.tenants.return_value = ['example']
        result = agent.collect(client, 'user', 'secret', shared=True, selected=['Example'])
        self.assertIn('Example; discovered customer sites (case-sensitive): example', result['errors'][0])
        client.switch.assert_called_once_with('global')
        result = agent.collect(self.client(), 'user', 'secret', shared=True, selected=['b'])
        self.assertEqual(list(result['tenants']), ['b'])
        self.assertEqual(result['errors'], [])

    def test_partial_query_failure_preserves_success_and_no_zero(self):
        """
        Verify partial query failure preserves success and no zero.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        client = self.client()
        original = client.get.side_effect
        client.get.side_effect = lambda path, expected=dict: (_ for _ in ()).throw(agent.APIError('timeout')) if '/donut' in path else original(path, expected)
        result = agent.collect(client, 'user', 'secret')
        record = result['tenants']['default']
        self.assertNotIn('windows', record['data'])
        self.assertIn('license', record['data'])
        self.assertEqual(len(record['errors']), 2)

    def test_output_projection_excludes_passwords_and_preserves_assigned_list(self):
        """
        Verify output projection excludes passwords and preserves assigned list.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        data['settings']['smtp_password'] = 'secret'
        data['license']['session_token'] = 'secret'
        for key, value in data.items():
            projected = agent.project(value, agent.FIELDS[key])
            self.assertNotIn('secret', json.dumps(projected))
        self.assertEqual(agent.project(data['certificates'], agent.FIELDS['certificates'])[0]['assigned_to'], ['web'])

    def test_webfilter_profiles_collect_deduplicated_ids_and_exclude_contents(self):
        """
        Verify webfilter profiles collect deduplicated ids and exclude contents.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        client = self.client()
        original = client.get.side_effect
        def get(path, expected=dict):
            """
            Serve endpoint fixtures for the surrounding collection scenario.

            Input:
                path: EMS API path to query.
                expected: Response type accepted for client API compatibility.

            Output:
                Synthetic endpoint data; configured failure paths raise APIError.

            """
            if path.endswith('/webfilter/index'):
                return {'local': [{'id': 1, 'name': 'Standard'}], 'chrome': [{'id': '1'}],
                        'imported': [{'fp_name': 'FW', 'profiles': [{'profile_id': 2}]}]}
            if path.endswith('/1/get'):
                return {'name': 'Standard', 'smtp_password': 'secret', 'json': {'webfilter': {
                    'enabled': 1, 'fortiguard': {'enabled': 1},
                    'categories': [{'internal': 'secret'}], 'urls': [{'url': 'secret'}]}}}
            if path.endswith('/2/get'):
                raise agent.APIError('permission denied')
            return original(path, expected)
        client.get.side_effect = get
        value = agent.collect(client, 'user', 'password')
        data = value['tenants']['default']['data']
        self.assertEqual(len(data['webfilter_profiles']), 2)
        self.assertEqual(data['webfilter_profiles'][0]['categories'], 1)
        self.assertEqual(data['webfilter_profiles'][0]['urls'], 1)
        self.assertIn('error', data['webfilter_profiles'][1])
        self.assertNotIn('secret', json.dumps(value))
        self.assertTrue(value['tenants']['default']['errors'])
        self.assertEqual(sum(call.args[0].endswith('/1/get') for call in client.get.call_args_list), 1)

    def test_malformed_webfilter_index_is_not_an_empty_inventory(self):
        """
        Verify malformed webfilter index is not an empty inventory.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for index in ({}, {'local': None}, {'chrome': [None]}, {'local': [{'id': '../x'}]}):
            with self.subTest(index=index), self.assertRaises(agent.APIError):
                agent.webfilter_profile_ids(index)
        self.assertEqual(agent.webfilter_profile_ids({'local': [], 'chrome': [], 'imported': []}), [])


class CheckTests(unittest.TestCase):
    def run_check(self, kind, data=None, params=None, shared=False, index=0):
        """
        Discover a service and execute its check against synthetic EMS data.

        Input:
            self: Test case instance providing the helper and its fixtures.
            kind: Check plugin suffix, such as license or webfilter.
            data: EMS data override; None uses the standard fixture.
            params: Check parameters; None uses the plugin defaults.
            shared: Whether to use Shared EMS service naming.
            index: Position of the discovered service to check.

        Output:
            List of result and metric records emitted by the check.

        """
        value = section(data, shared)
        plugin = getattr(checks, 'check_plugin_fortiems_' + kind)
        item = list(plugin.discovery_function(value))[index].item
        return list(plugin.check_function(item, params if params is not None else plugin.check_default_parameters, value))

    def states(self, output):
        """
        Extract monitoring states from check output.

        Input:
            self: Test case instance providing the helper and its fixtures.
            output: Iterable of check result and metric records.

        Output:
            List of state values in emission order.

        """
        return [entry.state for entry in output if hasattr(entry, 'state')]

    def metrics(self, output):
        """
        Extract named metric values from check output.

        Input:
            self: Test case instance providing the helper and its fixtures.
            output: Iterable of check result and metric records.

        Output:
            Dictionary mapping metric names to measured values.

        """
        return {entry.name: entry.value for entry in output if isinstance(entry, Metric)}

    def test_api_without_collected_sites_cannot_report_success(self):
        """
        Verify API without collected sites cannot report success.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for shared in (False, True):
            with self.subTest(shared=shared):
                value = {'schema': 1, 'shared': shared, 'errors': [], 'tenants': {}}
                output = list(checks.check_api(value))
                self.assertEqual(self.states(output), [State.CRIT])
                self.assertIn('No sites collected', output[0].summary)

    def test_single_license_service_selects_each_product_and_switches(self):
        """
        Select EPP, SASE or ZTNA per tenant under the same service identity.
        """
        plugin = checks.check_plugin_fortiems_license
        for shared in (False, True):
            value = section(shared=shared)
            data = value['tenants']['customer-123']['data']
            items = [entry.item for entry in plugin.discovery_function(value)]
            self.assertEqual(items, ['["customer-123"] License'] if shared else ['License'])
            for product in ('epp', 'sase', 'ztna'):
                with self.subTest(shared=shared, product=product):
                    lic = data['license']
                    lic['vdom_seats'] = dict.fromkeys(('epp', 'sase', 'ztna'), 0)
                    lic['used'] = dict.fromkeys(('epp', 'sase', 'ztna'), 0)
                    lic['vdom_seats'][product] = 6
                    lic['used'][product] = 3
                    # Other zero-seat products may still have an expiry date.
                    lic['licenses'] = [{'type': name.upper(), 'expiry_date':
                        (datetime.now(timezone.utc) + timedelta(days=100 if name == product else -3)).date().isoformat()}
                        for name in ('epp', 'sase', 'ztna')]
                    output = list(plugin.check_function(items[0], plugin.check_default_parameters, value))
                    self.assertEqual(set(self.states(output)), {State.OK})
                    summaries = [entry.summary for entry in output if isinstance(entry, Result)]
                    self.assertEqual(summaries[0], f'{product.upper()}: 3 / 6 seats')
                    self.assertFalse(any('No seats' in text for text in summaries))
                    self.assertEqual(self.metrics(output)['ems_license_utilization'], 50)
                    self.assertGreater(self.metrics(output)['ems_remaining_days'], 90)
                    self.assertEqual([entry.item for entry in plugin.discovery_function(value)], items)

    def test_multiple_license_products_are_unknown_without_mixed_metrics(self):
        """
        Do not silently select one product when EMS reports multiple active types.
        """
        data = fixture()
        data['license']['vdom_seats']['epp'] = 6
        output = self.run_check('license', data)
        self.assertEqual(self.states(output), [State.UNKNOWN])
        self.assertEqual(self.metrics(output), {})
        self.assertIn('Multiple active license types', output[0].summary)

    def test_license_threshold_and_metric_calculation(self):
        """
        Verify license threshold and metric calculation.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        output = self.run_check('license')
        self.assertIn(State.WARN, self.states(output))
        metrics = self.metrics(output)
        self.assertEqual(metrics['ems_license_used'], 80)
        self.assertEqual(metrics['ems_license_max'], 100)
        self.assertEqual(metrics['ems_license_utilization'], 80)
        output = self.run_check('license', params={'utilization': ('fixed', (85, 95))})
        self.assertEqual(set(self.states(output)), {State.OK})

    def test_assigned_and_used_seat_metrics_include_zero_values(self):
        """
        Verify assigned and used seat metrics include zero values.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for assigned, used in ((2, 0), (0, 0), (2, 1)):
            with self.subTest(assigned=assigned, used=used):
                data = fixture()
                data['license']['vdom_seats']['ztna'] = 0
                data['license']['used']['ztna'] = 0
                data['license']['vdom_seats']['epp'] = assigned
                data['license']['used']['epp'] = used
                output = self.run_check('license', data)
                metrics = self.metrics(output)
                self.assertEqual(metrics['ems_license_max'], assigned)
                self.assertEqual(metrics['ems_license_used'], used)

    def test_failed_license_is_unknown_without_metrics(self):
        """
        Verify failed license is unknown without metrics.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        del data['license']
        output = self.run_check('license', data)
        self.assertEqual(self.states(output), [State.UNKNOWN])
        self.assertEqual(self.metrics(output), {})

    def test_zero_capacity_and_overuse(self):
        """
        Verify zero capacity and overuse.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        data['license']['vdom_seats']['ztna'] = 0
        data['license']['used']['ztna'] = 0
        output = self.run_check('license', data)
        self.assertNotIn(State.UNKNOWN, self.states(output))
        self.assertNotIn('ems_license_utilization', self.metrics(output))
        data['license']['used']['sase'] = 1
        self.assertIn(State.CRIT, self.states(self.run_check('license', data)))

    def test_expiry_per_product_and_renewals(self):
        """
        Verify expiry per product and renewals.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        old = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
        data['license']['licenses'].append({'type': 'ZTNA', 'expiry_date': old})
        self.assertNotIn(State.CRIT, self.states(self.run_check('license', data)))
        data['license']['licenses'][0]['expiry_date'] = old
        self.assertIn(State.CRIT, self.states(self.run_check('license', data)))
        data['license']['vdom_seats']['ztna'] = 0
        data['license']['used']['ztna'] = 0
        data['license']['vdom_seats']['epp'] = 50
        data['license']['used']['epp'] = 10
        self.assertNotIn(State.CRIT, self.states(self.run_check('license', data)))

    def test_earliest_assigned_certificate_only(self):
        """
        Verify earliest assigned certificate only.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        past = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
        data['certificates'].append({'name': 'Unused', 'assigned_to': [], 'expiry_date': past})
        self.assertEqual(set(self.states(self.run_check('certificates', data))), {State.OK})
        data['certificates'][-1]['assigned_to'] = ['endpoint']
        output = self.run_check('certificates', data)
        self.assertIn(State.CRIT, self.states(output))
        self.assertEqual(self.metrics(output)['ems_remaining_days'], -2)

    def test_system_upgrade_rule_and_identity(self):
        """
        Verify system upgrade rule and identity.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.assertEqual(set(self.states(self.run_check('system'))), {State.OK})
        self.assertEqual([entry.summary for entry in self.run_check('system')], ['EMS-01'])
        data = fixture()
        data['settings']['auto_upgrade_enabled'] = False
        self.assertIn(State.WARN, self.states(self.run_check('system', data, index=3)))
        self.assertIn(State.CRIT, self.states(self.run_check('system', data, {'disabled_state': 'crit'}, index=3)))
        self.assertEqual(set(self.states(self.run_check('system', data, {'disabled_state': 'ok'}, index=3))), {State.OK})
        self.assertEqual(self.metrics(self.run_check('system', data, index=3)), {'ems_auto_upgrade_enabled': 0})
        self.assertEqual(self.metrics(self.run_check('system', index=3)), {'ems_auto_upgrade_enabled': 1})

    def test_system_fields_are_separate_and_independent(self):
        """
        Verify system fields are separate and independent.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        value = section()
        plugin = checks.check_plugin_fortiems_system
        items = [service.item for service in plugin.discovery_function(value)]
        self.assertEqual(items, ['System Hostname', 'System Serial Number', 'System Version', 'System Auto Upgrade', 'System Package Region'])
        data = fixture()
        del data['license']
        del data['settings']
        self.assertEqual(self.states(self.run_check('system', data)), [State.OK])
        self.assertEqual(self.states(self.run_check('system', data, index=1)), [State.UNKNOWN])
        self.assertEqual(self.states(self.run_check('system', data, index=2)), [State.OK])
        self.assertEqual(self.states(self.run_check('system', data, index=3)), [State.UNKNOWN])
        self.assertEqual(self.metrics(self.run_check('system', data, index=3)), {})
        value['shared'] = True
        self.assertTrue(all(service.item.startswith('["customer-123"] System ') for service in plugin.discovery_function(value)))
        old = list(plugin.check_function('System', plugin.check_default_parameters, value))
        self.assertEqual(self.states(old), [State.UNKNOWN])

    def test_package_region_projection_discovery_and_missing_values(self):
        """
        Verify package region projection discovery and missing values.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        data['settings']['scheduled_backup_password'] = 'secret'
        data['settings'] = agent.project(data['settings'], agent.FIELDS['settings'])
        self.assertNotIn('secret', json.dumps(data['settings']))
        output = self.run_check('system', data, index=4)
        self.assertEqual(self.states(output), [State.OK])
        self.assertEqual(output[0].summary, 'North America')
        self.assertEqual(self.metrics(output), {})
        value = section(data, shared=True)
        items = [service.item for service in checks.check_plugin_fortiems_system.discovery_function(value)]
        self.assertIn('["customer-123"] System Package Region', items)
        for region in (None, '', '  ', [], 123):
            data['settings']['fct_repackager_upload_region'] = region
            self.assertEqual(self.states(self.run_check('system', data, index=4)), [State.UNKNOWN])
        del data['settings']['fct_repackager_upload_region']
        self.assertEqual(self.states(self.run_check('system', data, index=4)), [State.UNKNOWN])
        self.assertEqual(self.states(self.run_check('system', data)), [State.OK])

    def test_enabled_auto_upgrade_defaults_to_warn_and_can_be_overridden(self):
        """
        Verify enabled auto upgrade defaults to warn and can be overridden.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.assertEqual(self.states(self.run_check('system', index=3)), [State.WARN])
        # Previously saved rules lack enabled_state and must use the new default.
        self.assertEqual(self.states(self.run_check('system', params={'disabled_state': 'ok'}, index=3)), [State.WARN])
        for setting, state in (('ok', State.OK), ('warn', State.WARN), ('crit', State.CRIT)):
            output = self.run_check('system', params={'enabled_state': setting}, index=3)
            self.assertEqual(self.states(output), [state])
            self.assertEqual(self.metrics(output), {'ems_auto_upgrade_enabled': 1})
        data = fixture()
        data['settings']['auto_upgrade_enabled'] = None
        output = self.run_check('system', data, {'enabled_state': 'ok', 'disabled_state': 'ok'}, index=3)
        self.assertEqual(self.states(output), [State.UNKNOWN])
        self.assertEqual(self.metrics(output), {})

    def test_endpoints_empty_is_zero_but_invalid_is_not(self):
        """
        Verify endpoints empty is zero but invalid is not.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        self.assertEqual(self.metrics(self.run_check('endpoints'))['ems_endpoints'], 20)
        self.assertEqual(self.metrics(self.run_check('endpoints', index=1))['ems_endpoints'], 0)
        for invalid in (None, -1, True, 'nan', 'infinity', 1.2):
            data = fixture()
            data['windows'][0]['value'] = invalid
            output = self.run_check('endpoints', data)
            self.assertEqual(self.metrics(output), {})
            self.assertEqual(self.states(output), [State.UNKNOWN])
        data = fixture()
        del data['windows']
        self.assertEqual(self.metrics(self.run_check('endpoints', data)), {})

    def test_versions_are_summarized_in_os_services(self):
        """
        Show dynamic version counts in each OS summary and graph only totals.
        """
        for shared in (False, True):
            with self.subTest(shared=shared):
                value = section(shared=shared)
                data = value['tenants']['customer-123']['data']
                data['macos'] = [{'name': '7.4.8.1977', 'value': 1}]
                plugin = checks.check_plugin_fortiems_endpoints
                items = [service.item for service in plugin.discovery_function(value)]
                self.assertEqual(len(items), 2)
                self.assertTrue(all(' Version ' not in item for item in items))
                self.assertEqual(all('customer-123' in item for item in items), shared)
                macos = next(item for item in items if item.endswith('macOS'))
                output = list(plugin.check_function(macos, {}, value))
                self.assertEqual(self.metrics(output),
                                 {'ems_endpoints': 1})
                self.assertEqual(next(entry.summary for entry in output if isinstance(entry, Result)),
                                 '1 endpoints, FortiClient 7.4.8.1977: 1')
                # A new version appears on the next check, without discovery.
                data['macos'].append({'name': '7.4.9.2000', 'value': 2})
                data['macos'].append({'name': '7.4.8.1977', 'value': 3})
                output = list(plugin.check_function(macos, {}, value))
                updated = self.metrics(output)
                self.assertEqual(updated, {'ems_endpoints': 6})
                self.assertEqual(next(entry.summary for entry in output if isinstance(entry, Result)),
                                 '6 endpoints, FortiClient 7.4.8.1977: 4, FortiClient 7.4.9.2000: 2')
                data['macos'].reverse()
                self.assertEqual(self.metrics(plugin.check_function(macos, {}, value)), updated)
                data['macos'] = []
                self.assertEqual(self.metrics(plugin.check_function(macos, {}, value)),
                                 {'ems_endpoints': 0})
        self.assertFalse(hasattr(checks, 'check_plugin_fortiems_versions'))

    def test_version_counts_in_windows_summary_preserve_labels(self):
        """
        Keep distinct API version labels in the summary without version metrics.
        """
        labels = ['7.4.8.1977', '7_4_8_1977', 'Unknown', 'unknown', '7.4.8-beta',
                  '7.4.8 beta', 'ä', 'encoded_c3a4', '07.4.8.1977']
        data = fixture()
        data['windows'] = [{'name': label, 'value': index}
                           for index, label in enumerate(labels)]
        output = self.run_check('endpoints', data)
        self.assertEqual(self.metrics(output), {'ems_endpoints': sum(range(len(labels)))})
        summary = next(entry.summary for entry in output if isinstance(entry, Result))
        for index, label in enumerate(labels):
            self.assertIn(f'FortiClient {label}: {index}', summary)
        data['windows'] = [{'name': '7.4.8\nbeta', 'value': 1}]
        output = self.run_check('endpoints', data)
        self.assertIn('FortiClient 7.4.8 beta: 1', next(
            entry.summary for entry in output if isinstance(entry, Result)))
        data['windows'] = []
        output = self.run_check('endpoints', data)
        result = next(entry for entry in output if isinstance(entry, Result))
        self.assertEqual(result.summary, '0 endpoints')
        self.assertEqual(result.details, 'No endpoints')

    def test_idp_states_sync_age_and_metrics(self):
        """
        Verify IDP states sync age and metrics.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        output = self.run_check('idp')
        self.assertEqual(set(self.states(output)), {State.OK})
        self.assertEqual(self.metrics(output)['ems_idp_users'], 30)
        data = fixture()
        entry = data['idps'][0]
        entry['connection_info']['conn_online'] = False
        entry['status']['online'] = False
        entry['status']['last_error'] = 'sync failed'
        entry['status']['last_success_enumerated'] = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        self.assertIn(State.CRIT, self.states(self.run_check('idp', data)))
        params = {'connector_state': 'warn', 'offline_state': 'warn', 'error_state': 'warn', 'sync_age': ('no_levels', None)}
        output = self.run_check('idp', data, params)
        self.assertIn(State.WARN, self.states(output))
        self.assertNotIn(State.CRIT, self.states(output))

    def test_real_ems_idp_shape_with_empty_alias_and_provider_guid(self):
        """
        Verify real EMS IDP shape with empty alias and provider guid.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        entry = data['idps'][0]
        entry.pop('id')
        entry['guid'] = '00000000-0000-4000-8000-000000000001'
        entry['connection_info'] = {'alias': '', 'id': 1, 'conn_online': True}
        entry['domain_info'] = {'name': 'example.test', 'guid': entry['guid']}
        entry['group_info'] = {'id': 3, 'path': 'example.test'}
        entry['status']['sync_progress'] = '100.00'
        entry['total_devices'], entry['total_users'] = 25, 5
        # Pass through the collector's actual allowlist before discovering.
        data['idps'] = agent.project(data['idps'], agent.FIELDS['idps'])
        value = section(data)
        plugin = checks.check_plugin_fortiems_idp
        items = list(plugin.discovery_function(value))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].item, 'IDP example.test')
        self.assertNotIn(entry['guid'], items[0].item)
        output = self.run_check('idp', data)
        self.assertEqual(set(self.states(output)), {State.OK})
        self.assertEqual(self.metrics(output)['ems_idp_devices'], 25)
        self.assertEqual(self.metrics(output)['ems_idp_users'], 5)
        self.assertEqual(self.metrics(output)['ems_sync_progress'], 100)
        self.assertIn('GUID: ' + entry['guid'], [result.summary for result in output if hasattr(result, 'summary')])

    def test_duplicate_idp_names_are_not_merged_after_hiding_guids(self):
        """
        Verify duplicate IDP names are not merged after hiding guids.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        first = data['idps'][0]
        first.pop('id')
        first['guid'] = 'provider-a'
        second = copy.deepcopy(first)
        second['guid'] = 'provider-b'
        data['idps'].append(second)
        self.assertEqual(self.states(self.run_check('idp', data)), [State.UNKNOWN])
        self.assertEqual(self.states(self.run_check('idp_summary', data)), [State.UNKNOWN])

    def test_idp_inventory_distinguishes_empty_missing_and_invalid(self):
        """
        Verify IDP inventory distinguishes empty missing and invalid.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        data['idps'] = []
        output = self.run_check('idp_summary', data)
        self.assertEqual(self.states(output), [State.OK])
        self.assertEqual(self.metrics(output), {'ems_idp_count': 0})
        data['idps'] = [{}]
        output = self.run_check('idp_summary', data)
        self.assertEqual(self.states(output), [State.UNKNOWN])
        self.assertEqual(self.metrics(output), {})
        del data['idps']
        self.assertEqual(self.states(self.run_check('idp_summary', data)), [State.UNKNOWN])

    def test_webfilter_service_names_use_profile_name_and_disambiguate_duplicates(self):
        """
        Verify webfilter service names use profile name and disambiguate duplicates.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        value = section(shared=True)
        record = value['tenants'].pop('customer-123')
        value['tenants']['example'] = record
        profiles = record['data']['webfilter_profiles'] = [
            {'id': 46, 'name': 'Default', 'enabled': False, 'fortiguard_enabled': True,
             'categories': 91, 'urls': 0, 'is_default': False},
            {'id': 47, 'name': 'Default - Chromebooks', 'enabled': True,
             'fortiguard_enabled': True, 'categories': 91, 'urls': 0, 'is_default': False}]
        plugin = checks.check_plugin_fortiems_webfilter_profiles
        items = [entry.item for entry in plugin.discovery_function(value)]
        self.assertEqual(items, ['["example"] Webfilter Profile Default',
                                 '["example"] Webfilter Profile Default - Chromebooks'])
        output = list(plugin.check_function(items[1], {}, value))
        self.assertEqual(set(self.states(output)), {State.OK})
        self.assertEqual(self.metrics(output)['ems_webfilter_enabled'], 1)
        profiles.append(dict(profiles[0], id=50))
        items = [entry.item for entry in plugin.discovery_function(value)]
        self.assertIn('["example"] Webfilter Profile Default (ID 46)', items)
        self.assertIn('["example"] Webfilter Profile Default (ID 50)', items)
        profiles.append({'id': 51, 'error': 'unavailable'})
        self.assertIn('["example"] Webfilter Profile 51',
                      [entry.item for entry in plugin.discovery_function(value)])

    def test_ems_default_webfilter_profiles_are_not_discovered(self):
        """
        Verify EMS default webfilter profiles are not discovered.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for shared in (False, True):
            with self.subTest(shared=shared):
                value = section(shared=shared)
                data = value['tenants']['customer-123']['data']
                data['webfilter_profiles'] = [
                    {'id': 46, 'name': 'Default', 'is_default': True},
                    {'id': 47, 'name': 'Default - Chromebooks', 'is_default': True},
                    {'id': 50, 'name': 'Default', 'is_default': False},
                    {'id': 51, 'name': 'Custom import', 'is_imported': True}]
                plugin = checks.check_plugin_fortiems_webfilter_profiles
                items = [entry.item for entry in plugin.discovery_function(value)]
                prefix = '["customer-123"] ' if shared else ''
                self.assertEqual(items, [prefix + 'Webfilter Profile Default',
                                         prefix + 'Webfilter Profile Custom import'])
                data['webfilter_profiles'] = data['webfilter_profiles'][:2]
                self.assertEqual(list(plugin.discovery_function(value)), [])

    def test_webfilter_summary_separates_ems_default_profiles(self):
        """
        Verify webfilter summary separates EMS default profiles.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        data['webfilter_profiles'] = [
            {'id': 46, 'name': 'Default', 'is_default': True},
            {'id': 47, 'name': 'Default - Chromebooks', 'is_default': True}]
        output = self.run_check('webfilter', data)
        self.assertIn('0 non-default profile(s), 2 EMS default profile(s)', output[0].summary)
        self.assertEqual(self.states(output), [State.OK])
        self.assertEqual(self.metrics(output)['ems_webfilter_profiles'], 2)

    def test_webfilter_summary_and_profile_checks(self):
        """
        Verify webfilter summary and profile checks.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        data['webfilter_profiles'] = []
        self.assertEqual(self.metrics(self.run_check('webfilter', data)), {'ems_webfilter_profiles': 0, 'ems_webfilter_imports': 0})
        data['webfilter_profiles'] = [{'id': 1, 'name': 'Standard', 'enabled': True,
                                       'fortiguard_enabled': True, 'categories': 10, 'urls': 0}]
        output = self.run_check('webfilter_profiles', data)
        self.assertEqual(set(self.states(output)), {State.OK})
        self.assertEqual(self.metrics(output)['ems_webfilter_categories'], 10)
        data['webfilter_profiles'][0]['enabled'] = False
        self.assertIn(State.WARN, self.states(self.run_check('webfilter_profiles', data)))
        self.assertEqual(set(self.states(self.run_check('webfilter_profiles', data, {'disabled_state': 'ok'}))), {State.OK})
        data['webfilter_profiles'] = [{'id': 1, 'error': 'timeout'}]
        self.assertEqual(self.metrics(self.run_check('webfilter_profiles', data)), {})
        self.assertEqual(self.states(self.run_check('webfilter_profiles', data)), [State.UNKNOWN])
        self.assertIn(State.UNKNOWN, self.states(self.run_check('webfilter', data)))

    def test_imported_webfilter_sync_rules_and_shared_services(self):
        """
        Verify imported webfilter sync rules and shared services.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        firewall = {'fp_name': 'Test-FW', 'task': {'enabled': True, 'last_error': '',
                    'last_successful_run_time': datetime.now(timezone.utc).isoformat()}, 'profiles': []}
        data['webfilter']['imported'] = [firewall]
        self.assertEqual(set(self.states(self.run_check('webfilter_imports', data, shared=True))), {State.OK})
        firewall['task']['last_error'] = 'Connection failed'
        self.assertIn(State.CRIT, self.states(self.run_check('webfilter_imports', data)))
        firewall['task']['last_successful_run_time'] = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        firewall['task']['last_error'] = ''
        self.assertIn(State.CRIT, self.states(self.run_check('webfilter_imports', data)))
        firewall['task']['enabled'] = False
        output = self.run_check('webfilter_imports', data, {'sync_disabled_state': 'ok'})
        self.assertEqual(set(self.states(output)), {State.OK})
        self.assertEqual(self.metrics(output), {})

    def test_sync_age_alarms_for_idp_import_and_webfilter_summary(self):
        """
        Verify sync age alarms for IDP import and webfilter summary.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for hours, expected in ((0, State.OK), (25, State.WARN), (49, State.CRIT)):
            with self.subTest(hours=hours):
                data = fixture()
                stamp = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
                data['idps'][0]['status']['last_success_enumerated'] = stamp
                data['webfilter_profiles'] = []
                data['webfilter']['imported'] = [{'fp_name': 'Test-FW', 'task': {
                    'enabled': True, 'last_error': '', 'last_successful_run_time': stamp}}]
                for kind in ('idp', 'webfilter_imports', 'webfilter'):
                    output = self.run_check(kind, data)
                    states = set(self.states(output))
                    self.assertIn(expected, states)
                    if expected == State.OK:
                        self.assertEqual(states, {State.OK})
                    self.assertIn('ems_sync_age', self.metrics(output))
                # Rule overrides apply independently to each matching service.
                params = {'sync_age': ('no_levels', None)}
                self.assertEqual(set(self.states(self.run_check('webfilter', data, params))), {State.OK})

    def test_webfilter_summary_rolls_up_errors_and_unknown_sync_data(self):
        """
        Verify webfilter summary rolls up errors and unknown sync data.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        data['webfilter_profiles'] = []
        task = {'enabled': True, 'last_error': 'Connection failed',
                'last_successful_run_time': datetime.now(timezone.utc).isoformat()}
        data['webfilter']['imported'] = [{'fp_name': 'Test-FW', 'task': task}]
        self.assertIn(State.CRIT, self.states(self.run_check('webfilter', data)))
        self.assertIn(State.WARN, self.states(self.run_check('webfilter', data, {'sync_error_state': 'warn'})))
        task['last_error'] = ''
        task['last_successful_run_time'] = None
        output = self.run_check('webfilter', data)
        self.assertIn(State.UNKNOWN, self.states(output))
        self.assertNotIn('ems_sync_age', self.metrics(output))
        task['enabled'] = False
        self.assertIn(State.WARN, self.states(self.run_check('webfilter', data)))

    def test_webfilter_summary_graph_uses_oldest_complete_active_sync(self):
        """
        Verify webfilter summary graph uses oldest complete active sync.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        data = fixture()
        data['webfilter_profiles'] = []
        def firewall(name, hours):
            """
            Build an imported firewall fixture with a known synchronization age.

            Input:
                name: Firewall name used in the fixture.
                hours: Hours since the last successful synchronization.

            Output:
                Firewall dictionary containing an enabled synchronization task.

            """
            return {'fp_name': name, 'task': {'enabled': True, 'last_error': '',
                    'last_successful_run_time': (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()}}
        data['webfilter']['imported'] = [firewall('A', 2), firewall('B', 26)]
        output = self.run_check('webfilter', data)
        self.assertIn(State.WARN, self.states(output))
        self.assertAlmostEqual(self.metrics(output)['ems_sync_age'], 26 * 3600, delta=5)
        data['webfilter']['imported'][0]['task']['last_successful_run_time'] = 'invalid'
        self.assertNotIn('ems_sync_age', self.metrics(self.run_check('webfilter', data)))

    def test_shared_service_names_are_unique_and_site_bound(self):
        """
        Verify shared service names are unique and site bound.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        value = section(shared=True)
        value['tenants']['second-company'] = copy.deepcopy(value['tenants']['customer-123'])
        names = []
        for module in FEATURES:
            for key, plugin in vars(module).items():
                if key.startswith('check_plugin_') and key != 'check_plugin_fortiems_api':
                    for service in plugin.discovery_function(value):
                        names.append(plugin.service_name % service.item)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all('customer-123' in name or 'second-company' in name for name in names))

    def test_parser_and_global_api_failures(self):
        """
        Verify parser and global API failures.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for raw in ('null', '{}', '{bad', '{"schema":1,"tenants": []}'):
            parsed = checks.parse_fortiems([[raw]])
            self.assertEqual(list(checks.check_api(parsed))[0].state, State.CRIT)
        value = section()
        self.assertEqual(checks.parse_fortiems([[json.dumps(value)]]), value)
        value['tenants']['customer-123']['errors'] = ['license: timeout']
        self.assertEqual(list(checks.check_api(value))[0].state, State.CRIT)


class IntegrationTests(unittest.TestCase):
    def test_feature_registrations_are_unique_and_compatibility_is_lazy(self):
        """
        Verify feature registrations are unique and compatibility is lazy.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        plugins = {}
        sections = []
        for module in FEATURES:
            for key, value in vars(module).items():
                if key.startswith('check_plugin_'):
                    self.assertNotIn(value.name, plugins)
                    plugins[value.name] = value
                    self.assertIs(getattr(checks, key), value)
                    self.assertEqual(value.sections, ['fortiems'])
                elif key.startswith('agent_section_'):
                    sections.append(value)
                    self.assertIs(getattr(checks, key), value)
        self.assertEqual(len(plugins), 11)
        self.assertNotIn('fortiems_versions', plugins)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].name, 'fortiems')
        self.assertFalse(any(name.startswith(('check_plugin_', 'agent_section_')) for name in vars(checks)))
        with self.assertRaises(AttributeError):
            getattr(checks, 'unknown_attribute')

    def test_ruleset_forms_use_public_choice_types_and_dedicated_defaults(self):
        """
        Verify ruleset forms use public choice types and dedicated defaults.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        class Form:
            def __init__(self, *args, **kwargs):
                """
                Store constructor arguments on a Checkmk form API double.

                Input:
                    self: Record instance being initialized.
                    *args: Positional arguments accepted by the API double.
                    **kwargs: Additional attributes stored on the record.

                Output:
                    None. Initializes the instance attributes.

                """
                self.args = args
                self.__dict__.update(kwargs)

            @classmethod
            def __class_getitem__(cls, item):
                """
                Accept generic type subscription on the form API double.

                Input:
                    cls: Form class receiving the subscription.
                    item: Type argument accepted for API compatibility.

                Output:
                    The same form class.

                """
                return cls

        class ChoiceElement(Form):
            def __init__(self, *, name, title):
                """
                Validate and store the name and title of a form choice.

                Input:
                    self: Record instance being initialized.
                    name: Identifier of the choice element.
                    title: Display title of the choice element.

                Output:
                    None. Initializes the instance attributes.

                """
                self_test.assertIsInstance(name, str)
                self_test.assertTrue(name.isidentifier())
                super().__init__(name=name, title=title)

        class Choice(Form):
            def __init__(self, **kwargs):
                """
                Validate that a choice prefill names an available element.

                Input:
                    self: Record instance being initialized.
                    **kwargs: Additional attributes stored on the record.

                Output:
                    None. Initializes the instance attributes.

                """
                if 'prefill' in kwargs:
                    self_test.assertIn(kwargs['prefill'].args[0], [value.name for value in kwargs['elements']])
                super().__init__(**kwargs)

        self_test = self
        base = types.ModuleType('cmk.rulesets.v1')
        base.Title = base.Help = str
        specs = types.ModuleType('cmk.rulesets.v1.form_specs')
        for name in ('DefaultValue', 'DictElement', 'Dictionary', 'Integer', 'List', 'Password',
                     'String', 'Float', 'Percentage', 'SimpleLevels'):
            setattr(specs, name, Form)
        specs.SingleChoiceElement = ChoiceElement
        specs.SingleChoice = Choice
        specs.CascadingSingleChoiceElement = Form
        specs.CascadingSingleChoice = Choice
        specs.LevelDirection = Record(UPPER='upper', LOWER='lower')
        specs.migrate_to_password = lambda value: value
        specs.validators = Record(LengthInRange=Form, NetworkPort=Form, NumberInRange=Form)
        rules = types.ModuleType('cmk.rulesets.v1.rule_specs')
        rules.SpecialAgent = rules.CheckParameters = rules.HostAndItemCondition = Form
        rules.Topic = Record(NETWORKING='networking', APPLICATIONS='applications')
        with patch.dict(sys.modules, {'cmk.rulesets.v1': base, 'cmk.rulesets.v1.form_specs': specs,
                                     'cmk.rulesets.v1.rule_specs': rules}):
            source = load('ems_form_test', FAMILY / 'rulesets/special_agent.py')
            elements = source.parameter_form().elements
            self.assertEqual(elements['mode'].parameter_form.prefill.args[0], 'dedicated')
            self.assertNotIn('address', elements)
            self.assertNotIn('tenants', elements)
            branches = {choice.name: choice.parameter_form for choice in elements['mode'].parameter_form.elements}
            self.assertEqual(set(branches), {'dedicated', 'shared', 'cloud'})
            self.assertEqual(set(branches['dedicated'].elements), {'user', 'password', 'auth_method', 'site'})
            self.assertIn('tenants', branches['shared'].elements)
            dedicated = branches['dedicated'].elements
            self.assertEqual(dedicated['site'].parameter_form.prefill.args[0], 'default')
            self.assertTrue(dedicated['auth_method'].required)
            self.assertEqual(dedicated['auth_method'].parameter_form.prefill.args[0], 'radius')
            self.assertEqual([choice.name for choice in dedicated['auth_method'].parameter_form.elements], ['radius', 'local'])
            self.assertEqual(set(branches['cloud'].elements), {'account_email', 'access_key'})
            self.assertTrue(branches['cloud'].elements['access_key'].required)
            legacy = {'user': 'monitor'}
            self.assertEqual(source.migrate_parameters(legacy), {'mode': ('dedicated', {
                'auth_method': 'radius', 'user': 'monitor', 'site': 'default'})})
            self.assertEqual(legacy, {'user': 'monitor'})
            local = {'auth_method': 'local', 'user': 'monitor', 'mode': ('shared', {'tenants': ['Company']})}
            migrated_local = source.migrate_parameters(local)
            self.assertEqual(migrated_local, {'mode': ('shared', {'tenants': ['Company'],
                                                          'auth_method': 'local', 'user': 'monitor'})})
            self.assertEqual(source.migrate_parameters(migrated_local), migrated_local)
            self.assertEqual(local['mode'][1], {'tenants': ['Company']})
            old = {'mode': 'shared', 'tenants': ['Company'], 'address': 'obsolete.example', 'auth_method': 'local'}
            migrated = source.migrate_parameters(old)
            self.assertEqual(migrated, {'mode': ('shared', {'tenants': ['Company'], 'auth_method': 'local'})})
            self.assertEqual(source.migrate_parameters(migrated), migrated)
            self.assertEqual(old['tenants'], ['Company'])
            self.assertTrue(dedicated['password'].required)
            access_key = calls.Secret()
            cloud = {'mode': ('cloud_shared', {'account_email': 'test@example.test',
                                              'access_key': access_key, 'tenants': ['example']})}
            migrated_cloud = source.migrate_parameters(cloud)
            self.assertEqual(migrated_cloud, {'mode': ('cloud', {'account_email': 'test@example.test', 'access_key': access_key})})
            self.assertEqual(cloud['mode'][1]['tenants'], ['example'])
            self.assertEqual(source.migrate_parameters(migrated_cloud), migrated_cloud)
            parameters = load('ems_parameter_test', FAMILY / 'rulesets/check_parameters.py')
            for name in ('system_form', 'license_form', 'certificates_form', 'idp_form', 'webfilter_form'):
                self.assertTrue(getattr(parameters, name)().elements)
            upgrade = parameters.system_form().elements
            self.assertEqual(upgrade['enabled_state'].parameter_form.prefill.args[0], 'warn')
            self.assertIn('ok', [choice.name for choice in upgrade['enabled_state'].parameter_form.elements])

    def test_graphs_reference_defined_namespaced_metrics(self):
        """
        Verify graphs reference defined namespaced metrics.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        class Graphic:
            def __init__(self, *args, **kwargs):
                """
                Store graphing attributes on a Checkmk graph API double.

                Input:
                    self: Record instance being initialized.
                    *args: Positional arguments accepted by the API double.
                    **kwargs: Additional attributes stored on the record.

                Output:
                    None. Initializes the instance attributes.

                """
                self.__dict__.update(kwargs)

        base = types.ModuleType('cmk.graphing.v1')
        base.Title = str
        metrics = types.ModuleType('cmk.graphing.v1.metrics')
        for name in ('AutoPrecision', 'DecimalNotation', 'Metric', 'StrictPrecision', 'Unit'):
            setattr(metrics, name, Graphic)
        metrics.Color = Record(BLUE='blue', GREEN='green', ORANGE='orange')
        graphs = types.ModuleType('cmk.graphing.v1.graphs')
        graphs.Graph = graphs.MinimalRange = Graphic
        with patch.dict(sys.modules, {'cmk.graphing.v1': base, 'cmk.graphing.v1.metrics': metrics,
                                     'cmk.graphing.v1.graphs': graphs}):
            source = load('ems_graph_test', FAMILY / 'graphing/fortiems.py')
        self.assertEqual(source.graph_fortiems_license.simple_lines,
                         ['ems_license_max', 'ems_license_used'])
        names = {value.name for name, value in vars(source).items() if name.startswith('metric_')}
        self.assertTrue(all(name.startswith('ems_') for name in names))
        # Version counts belong in the OS summary, not in graph definitions.
        self.assertFalse(any(name.startswith('ems_version_') for name in names))
        for name, value in vars(source).items():
            if name.startswith('graph_'):
                self.assertFalse(any(metric.startswith('ems_version_')
                                     for metric in value.simple_lines))
                self.assertTrue(set(value.simple_lines) <= names)
        graphed = {metric for key, graph in vars(source).items() if key.startswith('graph_') for metric in graph.simple_lines}
        # Verify that actual numeric service output is covered by the shipped graphs.
        for kind, index in (('system', 3), ('license', 0), ('certificates', 0), ('endpoints', 0),
                            ('idp', 0), ('idp_summary', 0), ('webfilter', 0), ('webfilter_profiles', 0)):
            plugin = getattr(checks, 'check_plugin_fortiems_' + kind)
            value = section()
            value['tenants']['customer-123']['data']['webfilter_profiles'] = [
                {'id': 1, 'enabled': True, 'fortiguard_enabled': True, 'categories': 10, 'urls': 0}]
            item = list(plugin.discovery_function(value))[index].item
            output = plugin.check_function(item, plugin.check_default_parameters, value)
            exported = {entry.name for entry in output if isinstance(entry, Metric)}
            self.assertTrue(exported)
            self.assertTrue(exported <= graphed)

    def test_commands_default_to_dedicated_default_site_and_secret(self):
        """
        Verify commands default to dedicated default site and secret.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        secret = calls.Secret()
        host = Record(primary_ip_config=Record(address='192.0.2.1'), name='ems')
        args = list(calls.commands({'user': 'monitor', 'password': secret}, host))[0].command_arguments
        self.assertIn(secret, args)
        self.assertEqual(args[args.index('--site') + 1], 'default')
        self.assertEqual(args[args.index('--auth-method') + 1], 'radius')
        self.assertNotIn('--shared', args)
        params = {'user': 'monitor', 'password': secret, 'mode': 'shared', 'site': 'admin', 'tenants': ['Company'], 'tls': 'skip', 'auth_method': 'local'}
        args = list(calls.commands(params, host))[0].command_arguments
        self.assertIn('--shared', args)
        self.assertIn('--no-cert-check', args)
        self.assertEqual(args[args.index('--auth-method') + 1], 'local')
        self.assertEqual(args[args.index('--tenant') + 1], 'Company')
        with self.assertRaises(TypeError):
            list(calls.commands({'user': 'monitor', 'password': 'plaintext'}, host))

    def test_nested_deployment_options_and_host_address(self):
        """
        Verify nested deployment options and host address.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        secret = calls.Secret()
        host = Record(primary_ip_config=Record(address='192.0.2.1'), name='ems.example')
        for mode in ('shared', 'dedicated'):
            params = {'user': 'monitor', 'password': secret, 'address': 'obsolete.example',
                      'mode': (mode, {'tenants': ['Company']})}
            args = list(calls.commands(params, host))[0].command_arguments
            self.assertEqual(args[args.index('--address') + 1], '192.0.2.1')
            self.assertEqual('--tenant' in args, mode == 'shared')
            self.assertEqual('--shared' in args, mode == 'shared')
            if mode == 'shared':
                self.assertEqual(args[args.index('--tenant') + 1], 'Company')
        host.primary_ip_config.address = ''
        args = list(calls.commands({'user': 'monitor', 'password': secret}, host))[0].command_arguments
        self.assertEqual(args[args.index('--address') + 1], 'ems.example')

    def test_cloud_and_nested_onprem_commands_keep_secrets_out_of_plaintext(self):
        """
        Verify cloud and nested onprem commands keep secrets out of plaintext.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        host = Record(primary_ip_config=Record(address='192.0.2.1'), name='ems.example')
        secret = calls.Secret()
        for mode in ('cloud', 'cloud_dedicated', 'cloud_shared'):
            with self.subTest(mode=mode):
                options = {'account_email': 'account@example.test', 'access_key': secret,
                           'site': 'default', 'tenants': ['example']}
                args = list(calls.commands({'mode': (mode, options)}, host))[0].command_arguments
                self.assertIn('--cloud', args)
                self.assertIn(secret, args)
                self.assertNotIn('--password-id', args)
                self.assertNotIn('--address', args)
                self.assertNotIn('--user', args)
                self.assertEqual(args[args.index('--access-key-id') + 1], secret)
                self.assertNotIn('--shared', args)
                self.assertNotIn('--tenant', args)
                self.assertNotIn('--site', args)
        params = {'mode': ('shared', {'user': 'monitor', 'password': secret,
                                     'auth_method': 'local', 'tenants': ['example']})}
        args = list(calls.commands(params, host))[0].command_arguments
        self.assertIn('--shared', args)
        self.assertEqual(args[args.index('--auth-method') + 1], 'local')
        with self.assertRaises(TypeError):
            list(calls.commands({'mode': ('cloud_dedicated', {'account_email': 'account@example.test',
                                                           'access_key': 'plaintext'})}, host))

    def test_password_read_failure_is_an_api_section(self):
        """
        Verify password read failure is an API section.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        with patch.object(agent.sys, 'stdin', io.StringIO('')), patch('sys.stdout', new_callable=io.StringIO) as output:
            agent.main(['--address', 'ems', '--user', 'monitor', '--password-stdin'])
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[0], '<<<fortiems:sep(0)>>>')
        self.assertTrue(json.loads(lines[1])['errors'])

    def test_cli_forwards_authentication_method(self):
        """
        Verify CLI forwards authentication method.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        client = Mock()
        payload = {'schema': 1, 'shared': False, 'errors': [], 'tenants': {}}
        with patch.object(agent, 'Client', return_value=client), patch.object(agent, 'collect', return_value=payload) as collect_mock:
            with patch.object(agent.sys, 'stdin', io.StringIO('secret\n')), patch('sys.stdout', new_callable=io.StringIO):
                agent.main(['--address', 'ems', '--user', 'monitor', '--password-stdin', '--auth-method', 'local'])
        collect_mock.assert_called_once_with(client, 'monitor', 'secret', 'default', False, [], auth_method='local')

    def test_package_is_deterministic_and_contains_only_ems(self):
        """
        Verify package is deterministic and contains only EMS.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        builder = load('ems_builder', ROOT / 'build_mkp.py')
        first = builder.build().read_bytes()
        second = builder.build().read_bytes()
        self.assertEqual(first, second)
        with tarfile.open(fileobj=io.BytesIO(first), mode='r:gz') as archive:
            info = json.load(archive.extractfile('info.json'))
            self.assertEqual(info['name'], 'check_fortiems')
            inner = archive.extractfile('cmk_addons_plugins.tar').read()
        with tarfile.open(fileobj=io.BytesIO(inner)) as archive:
            names = archive.getnames()
            self.assertTrue(all(name.startswith('fortiems/') for name in names))
            self.assertIn('fortiems/libexec/agent_fortiems', names)
            for feature in FEATURE_NAMES:
                self.assertIn(f'fortiems/agent_based/fortiems_{feature}.py', names)
            self.assertIn('fortiems/agent_based/fortiems.py', names)
            self.assertIn('fortiems/lib/common.py', names)
            self.assertEqual(archive.getmember('fortiems/libexec/agent_fortiems').mode, 0o755)


if __name__ == '__main__':
    unittest.main()
