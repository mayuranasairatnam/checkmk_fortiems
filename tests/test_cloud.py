"""
Offline regression coverage for the supplied FortiCloud gateway protocol.
"""
import io
import json
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

from test_fortiems import State, agent, checks, fixture


class CloudTests(unittest.TestCase):
    def setUp(self):
        """
        Prepare an isolated client and mocked transport for each test.

        Input:
            self: Test case instance receiving client, response and cleanup state.

        Output:
            None. Registers cleanup callbacks and initializes the test fixtures.

        """
        patch.object(agent.time, 'sleep').start()
        self.client = agent.CloudClient(timeout=7)
        self.closed = patch.object(self.client.session, 'close', wraps=self.client.session.close).start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.client.session.close)
        self.calls = []
        self.active = None
        data = fixture()
        # Match the Cloud response shapes supplied by the live diagnostic.
        data['consts'] = {'System': {'VERSION': '7.4.7', 'VERSION_FULL': '7.4.7.2194'}}
        data['info'] = {'cloud_account_id': '123456', 'cloud_sni': None}
        data['settings'].pop('auto_upgrade_enabled')
        data['license']['seats'] = data['license'].pop('vdom_seats')
        data['license']['seats']['ztna'] = 0
        data['license']['used']['ztna'] = 0
        data['license']['seats']['epp'] = 6
        data['license']['used']['epp'] = 3
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
            path = url.removeprefix('https://forticlient.forticloud.com/fct/api/public/v1')
            self.calls.append((method, path, kwargs))
            response = Mock(status_code=200)
            if path == '/ems_api_cloud/login/':
                self.assertEqual(kwargs['json'], {'access_key': 'private-key', 'account_email': 'account@example.test'})
                self.assertNotIn('Authorization', kwargs['headers'])
                self.active = 'default'
                response.json.return_value = {'result': 'login', 'session_id': 'private-session'}
                return response
            self.assertEqual(kwargs['headers']['Authorization'], 'private-session')
            self.assertNotIn('x-csrftoken', kwargs['headers'])
            if path == '/ems_api_cloud/logout/':
                response.json.return_value = {'result': 'logout'}
                return response
            self.assertEqual(kwargs['headers']['Ems-Api-Header-Content-Type'], 'application/json')
            self.assertTrue(path.startswith('/ems_api/api/v1/'))
            ems_path = path.removeprefix('/ems_api')
            self.assertNotIn('Ems-Api-Header-ems-call-type', kwargs['headers'])
            self.assertNotIn(ems_path, ('/api/v1/sites/index', '/api/v1/session/update'))
            if '/consts/' in ems_path:
                self.assertEqual(urlsplit(ems_path).path, '/api/v1/system/consts/get')
                self.assertEqual(parse_qs(urlsplit(ems_path).query), {
                    'system_update_time': ['1970-01-01T00:00:00'],
                    'vdom_update_time': ['1970-01-01T00:00:00']})
                body = data['consts']
            else:
                self.assertIsNotNone(self.active)
                body = paths[ems_path]
            response.json.return_value = {'result': {'retval': 1}, 'data': body}
            return response

        self.client.session.request = Mock(side_effect=request)

    def test_cloud_collects_without_site_discovery_or_switching(self):
        """
        Verify cloud collects without site discovery or switching.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        value = agent.collect(self.client, 'account@example.test', 'private-key', auth_method='cloud')
        self.assertEqual(value['errors'], [])
        self.assertFalse(value['shared'])
        self.assertTrue(value['tenants']['default']['data'])
        self.assertEqual(self.calls[0][1], '/ems_api_cloud/login/')
        self.assertEqual(self.calls[-1][1], '/ems_api_cloud/logout/')
        self.assertFalse(any(path.endswith(('/sites/index', '/session/update')) for _, path, _ in self.calls))
        self.assertIsNone(self.client._cloud_session_id)
        self.assertNotIn('private-', json.dumps(value))
        self.closed.assert_called_once()

    def test_cloud_uses_documented_initial_session_context(self):
        """
        Verify Cloud queries use the initial session without site selection.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        value = agent.collect(self.client, 'account@example.test', 'private-key', auth_method='cloud')
        self.assertEqual(value['errors'], [])
        self.assertEqual(value['tenants']['default']['errors'], [])
        self.assertFalse(any(path.endswith('/session/update') for _, path, _ in self.calls))
        self.assertEqual(self.calls[-1][1], '/ems_api_cloud/logout/')

    def test_shared_cloud_collection_is_rejected_before_login(self):
        """
        Verify shared cloud collection is rejected before login.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        value = agent.collect(self.client, 'account@example.test', 'private-key',
                              shared=True, auth_method='cloud')
        self.assertIn('does not support tenants', value['errors'][0])
        self.assertEqual(self.calls, [])
        self.closed.assert_called_once()

    def test_cloud_client_rejects_site_discovery_and_switching(self):
        """
        Verify cloud client rejects site discovery and switching.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for operation in (self.client.tenants, lambda: self.client.switch('example'),
                          lambda: self.client.login('account@example.test', 'private-key', 'example')):
            with self.assertRaises(agent.APIError):
                operation()
        self.assertEqual(self.calls, [])

    def test_transient_cloud_query_is_retried_without_repeating_login(self):
        """
        Verify transient cloud query is retried without repeating login.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        original = self.client.session.request.side_effect
        failures = [True]
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
            if url.endswith('/system/info?is_basic=true') and failures:
                failures.pop()
                return Mock(status_code=503)
            return original(method, url, **kwargs)
        self.client.session.request.side_effect = request
        value = agent.collect(self.client, 'account@example.test', 'private-key', auth_method='cloud')
        self.assertEqual(value['errors'], [])
        self.assertEqual(value['tenants']['default']['errors'], [])
        self.assertEqual(failures, [])
        self.assertEqual(sum(path == '/ems_api_cloud/login/' for _, path, _ in self.calls), 1)

    def test_http_failure_still_logs_out_and_hides_error_body(self):
        """
        Verify HTTP failure still logs out and hides error body.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        original = self.client.session.request.side_effect
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
            if url.endswith('/system/info?is_basic=true'):
                response = Mock(status_code=401)
                response.json.return_value = {'error': 'private-session private-key'}
                return response
            return original(method, url, **kwargs)
        self.client.session.request.side_effect = request
        value = agent.collect(self.client, 'account@example.test', 'private-key', auth_method='cloud')
        self.assertIn('HTTP 401', value['tenants']['default']['errors'][0])
        self.assertEqual(self.calls[-1][1], '/ems_api_cloud/logout/')
        self.assertNotIn('private-', json.dumps(value))
        self.closed.assert_called_once()

    def test_logout_failure_preserves_measurements_and_closes_session(self):
        """
        Verify logout failure preserves measurements and closes session.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        original = self.client.session.request.side_effect
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
            if url.endswith('/logout/'):
                return Mock(status_code=503)
            return original(method, url, **kwargs)
        self.client.session.request.side_effect = request
        value = agent.collect(self.client, 'account@example.test', 'private-key', auth_method='cloud')
        self.assertTrue(value['tenants']['default']['data'])
        self.assertIn('Cloud logout:', value['errors'][0])
        self.assertIsNone(self.client._cloud_session_id)
        self.closed.assert_called_once()

    def test_rejected_cloud_login_has_one_attempt_and_no_secret_output(self):
        """
        Verify rejected cloud login has one attempt and no secret output.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        response = Mock(status_code=401)
        response.json.return_value = {'access_key': 'private-key', 'session_id': 'private-session'}
        self.client.session.request = Mock(return_value=response)
        value = agent.collect(self.client, 'account@example.test', 'private-key', auth_method='cloud')
        self.assertIn('HTTP 401', value['errors'][0])
        self.assertNotIn('private-', json.dumps(value))
        self.client.session.request.assert_called_once()
        self.closed.assert_called_once()

    def test_invalid_login_envelopes_do_not_start_api_or_logout_requests(self):
        """
        Verify invalid login envelopes do not start API or logout requests.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for body in ({'result': 'login'}, {'result': 'failed', 'session_id': 'private-session'},
                     {'result': 'login', 'session_id': ''}):
            with self.subTest(body=body):
                response = Mock(status_code=200)
                response.json.return_value = body
                self.client.session.request = Mock(return_value=response)
                value = agent.collect(self.client, 'account@example.test', 'private-key', auth_method='cloud')
                self.assertTrue(value['errors'])
                self.client.session.request.assert_called_once()
                self.assertIsNone(self.client._cloud_session_id)

    def test_cloud_cli_resolves_access_key_and_uses_common_section(self):
        """
        Verify cloud CLI resolves access key and uses common section.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        with patch.object(agent, 'CloudClient', return_value=self.client), \
                patch.object(agent, 'collect', return_value={'schema': 1, 'shared': False,
                                                            'errors': [], 'tenants': {}}) as collect, \
                patch.object(agent.sys, 'stdin', io.StringIO('private-key\n')), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            agent.main(['--cloud', '--account-email', 'account@example.test',
                        '--access-key-stdin'])
        collect.assert_called_once_with(self.client, 'account@example.test', 'private-key',
                                        'default', False, [], auth_method='cloud')
        self.assertNotIn('private-key', output.getvalue())
        self.assertTrue(output.getvalue().startswith('<<<fortiems:sep(0)>>>'))

    def test_cloud_cli_rejects_tenant_options_before_login(self):
        """
        Verify cloud CLI rejects tenant options before login.

        Input:
            self: Test case instance; scenario data and mocks are defined in this test.

        Output:
            None. Assertions fail if the expected behavior changes.

        """
        for flags in (['--shared'], ['--site', 'example'], ['--shared', '--tenant', 'example']):
            with self.subTest(flags=flags), patch('sys.stderr', new_callable=io.StringIO), \
                    patch.object(agent.sys, 'stdin') as stdin:
                with self.assertRaises(SystemExit) as error:
                    agent.main(['--cloud', '--account-email', 'account@example.test', '--access-key-stdin'] + flags)
                self.assertEqual(error.exception.code, 2)
                stdin.readline.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_cloud_omits_certificate_query_and_service(self):
        """
        Verify Cloud collection skips the unavailable certificate endpoint and service.

        Input:
            self: Cloud test case with mocked gateway responses.

        Output:
            None. Assertions verify requests, parsed discovery and API health.

        """
        value = agent.collect(self.client, 'account@example.test', 'private-key', auth_method='cloud')
        self.assertTrue(value['cloud'])
        self.assertEqual(value['errors'], [])
        self.assertEqual(value['tenants']['default']['errors'], [])
        self.assertNotIn('certificates', value['tenants']['default']['data'])
        self.assertFalse(any(path.endswith('/server_certificates/index') for _, path, _ in self.calls))
        parsed = checks.parse_fortiems([[json.dumps(value)]])
        plugin = checks.check_plugin_fortiems_certificates
        self.assertEqual(list(plugin.discovery_function(parsed)), [])
        self.assertEqual(list(checks.check_api(parsed))[0].state, State.OK)
        # On-prem retains certificate discovery, including missing-data reporting.
        parsed.pop('cloud')
        self.assertEqual(len(list(plugin.discovery_function(parsed))), 1)

    def test_cloud_response_shapes_produce_healthy_services_and_seat_graphs(self):
        """
        Verify Cloud seats and available system fields using the reported response schema.

        Input:
            self: Test case with Cloud-shaped info, settings and license fixtures.

        Output:
            None. Assertions validate API state, discovered services and seat metrics.

        """
        value = agent.collect(self.client, 'account@example.test', 'private-key', auth_method='cloud')
        parsed = checks.parse_fortiems([[json.dumps(value)]])
        self.assertEqual(list(checks.check_api(parsed))[0].state, State.OK)
        self.assertEqual(sum(urlsplit(path).path.endswith('/system/consts/get') for _, path, _ in self.calls), 1)
        system = checks.check_plugin_fortiems_system
        items = {service.item for service in system.discovery_function(parsed)}
        self.assertEqual(items, {'System Serial Number', 'System Version', 'System Package Region'})
        for item in items:
            output = list(system.check_function(item, system.check_default_parameters, parsed))
            self.assertEqual(output[0].state, State.OK)
            if item == 'System Version':
                self.assertEqual(output[0].summary, '7.4.7.2194')
        license_plugin = checks.check_plugin_fortiems_license
        self.assertEqual([service.item for service in license_plugin.discovery_function(parsed)], ['License'])
        output = list(license_plugin.check_function('License',
                      license_plugin.check_default_parameters, parsed))
        self.assertNotIn(State.UNKNOWN, [entry.state for entry in output if hasattr(entry, 'state')])
        self.assertEqual(output[2].summary, 'EPP: 3 / 6 seats')
        metrics = {entry.name: entry.value for entry in output if hasattr(entry, 'name')}
        self.assertEqual(metrics['ems_license_max'], 6)
        self.assertEqual(metrics['ems_license_used'], 3)
        self.assertEqual(metrics['ems_license_utilization'], 50)

    def test_cloud_missing_capacity_remains_unknown_without_zero_metrics(self):
        """
        Verify missing Cloud seat capacity is reported rather than replaced by zero.

        Input:
            self: Cloud test case with a license response missing seats.

        Output:
            None. Assertions require UNKNOWN and no fabricated license metrics.

        """
        original = self.client.session.request.side_effect
        def request(method, url, **kwargs):
            """
            Remove seat capacity from a successful Cloud license response.

            Input:
                method: HTTP method requested by the client.
                url: Target URL identifying the license endpoint.
                **kwargs: Request options forwarded to the mocked transport.

            Output:
                Mock response with seat capacity removed from license data.

            """
            response = original(method, url, **kwargs)
            if url.endswith('/license/get'):
                response.json.return_value['data'].pop('seats')
            return response
        self.client.session.request.side_effect = request
        value = agent.collect(self.client, 'account@example.test', 'private-key', auth_method='cloud')
        plugin = checks.check_plugin_fortiems_license
        output = list(plugin.check_function('License', plugin.check_default_parameters, value))
        self.assertEqual(output[0].state, State.UNKNOWN)
        self.assertFalse(any(hasattr(entry, 'name') for entry in output))

    def test_cloud_constants_failure_is_reported_and_logout_still_runs(self):
        """
        Verify a failed Cloud version query stays visible without losing other data.

        Input:
            self: Cloud test case with an HTTP failure on the constants endpoint.

        Output:
            None. Assertions require API errors, UNKNOWN version and session cleanup.

        """
        original = self.client.session.request.side_effect
        def request(method, url, **kwargs):
            """
            Simulate an unavailable constants endpoint through the Cloud gateway.

            Input:
                method: HTTP method requested by the client.
                url: Gateway URL used to select the failing endpoint.
                **kwargs: Options forwarded to the mocked request.

            Output:
                HTTP 404 response for constants; normal fixture responses otherwise.

            """
            if urlsplit(url).path.endswith('/system/consts/get'):
                return Mock(status_code=404)
            return original(method, url, **kwargs)
        self.client.session.request.side_effect = request
        value = agent.collect(self.client, 'account@example.test', 'private-key', auth_method='cloud')
        self.assertIn('consts: HTTP 404', value['tenants']['default']['errors'][0])
        self.assertEqual(list(checks.check_api(value))[0].state, State.CRIT)
        self.assertTrue(value['tenants']['default']['data']['license'])
        plugin = checks.check_plugin_fortiems_system
        output = list(plugin.check_function('System Version', plugin.check_default_parameters, value))
        self.assertEqual(output[0].state, State.UNKNOWN)
        self.assertEqual(self.calls[-1][1], '/ems_api_cloud/logout/')
        self.closed.assert_called_once()
