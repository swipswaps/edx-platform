"""
Test the enterprise support utils.
"""

import json

import ddt
import mock
from django.conf import settings
from django.test import TestCase
from django.test.utils import override_settings

from edx_toggles.toggles.testutils import override_waffle_flag
from openedx.core.djangolib.testing.utils import skip_unless_lms
from openedx.features.enterprise_support.tests import FEATURES_WITH_ENTERPRISE_ENABLED
from openedx.features.enterprise_support.tests.factories import (
    EnterpriseCustomerBrandingConfigurationFactory,
    EnterpriseCustomerUserFactory
)
from openedx.features.enterprise_support.utils import (
    ENTERPRISE_HEADER_LINKS,
    clear_data_consent_share_cache,
    enterprise_fields_only,
    get_data_consent_share_cache_key,
    get_enterprise_learner_portal,
    get_enterprise_sidebar_context,
    handle_enterprise_cookies_for_logistration,
    update_logistration_context_for_enterprise,
    update_third_party_auth_context_for_enterprise,
)
from student.tests.factories import UserFactory


@ddt.ddt
@override_settings(FEATURES=FEATURES_WITH_ENTERPRISE_ENABLED)
@skip_unless_lms
class TestEnterpriseUtils(TestCase):
    """
    Test enterprise support utils.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = UserFactory.create(password='password')
        super(TestEnterpriseUtils, cls).setUpTestData()

    @mock.patch('openedx.features.enterprise_support.utils.get_cache_key')
    def test_get_data_consent_share_cache_key(self, mock_get_cache_key):
        expected_cache_key = mock_get_cache_key.return_value

        assert expected_cache_key == get_data_consent_share_cache_key('some-user-id', 'some-course-id')

        mock_get_cache_key.assert_called_once_with(
            type='data_sharing_consent_needed',
            user_id='some-user-id',
            course_id='some-course-id',
        )

    @mock.patch('openedx.features.enterprise_support.utils.get_cache_key')
    @mock.patch('openedx.features.enterprise_support.utils.TieredCache')
    def test_clear_data_consent_share_cache(self, mock_tiered_cache, mock_get_cache_key):
        user_id = 'some-user-id'
        course_id = 'some-course-id'

        clear_data_consent_share_cache(user_id, course_id)

        mock_get_cache_key.assert_called_once_with(
            type='data_sharing_consent_needed',
            user_id='some-user-id',
            course_id='some-course-id',
        )
        mock_tiered_cache.delete_all_tiers.assert_called_once_with(mock_get_cache_key.return_value)

    @mock.patch('openedx.features.enterprise_support.utils.update_third_party_auth_context_for_enterprise')
    def test_update_logistration_context_no_customer_data(self, mock_update_tpa_context):
        request = mock.Mock()
        context = {}
        enterprise_customer = {}

        update_logistration_context_for_enterprise(request, context, enterprise_customer)

        assert context['enable_enterprise_sidebar'] is False
        mock_update_tpa_context.assert_called_once_with(request, context, enterprise_customer)

    @mock.patch('openedx.features.enterprise_support.utils.update_third_party_auth_context_for_enterprise')
    @mock.patch('openedx.features.enterprise_support.utils.get_enterprise_sidebar_context', return_value={})
    def test_update_logistration_context_no_sidebar_context(self, mock_sidebar_context, mock_update_tpa_context):
        request = mock.Mock(GET={'proxy_login': False})
        context = {}
        enterprise_customer = {'key': 'value'}

        update_logistration_context_for_enterprise(request, context, enterprise_customer)

        assert context['enable_enterprise_sidebar'] is False
        mock_update_tpa_context.assert_called_once_with(request, context, enterprise_customer)
        mock_sidebar_context.assert_called_once_with(enterprise_customer, False)

    @mock.patch('openedx.features.enterprise_support.utils.update_third_party_auth_context_for_enterprise')
    @mock.patch('openedx.features.enterprise_support.utils.get_enterprise_sidebar_context')
    @mock.patch('openedx.features.enterprise_support.utils.enterprise_fields_only')
    def test_update_logistration_context_with_sidebar_context(
            self, mock_enterprise_fields_only, mock_sidebar_context, mock_update_tpa_context
    ):
        request = mock.Mock(GET={'proxy_login': False})
        context = {
            'data': {
                'registration_form_desc': {
                    'thing-1': 'one',
                    'thing-2': 'two',
                },
            },
        }
        enterprise_customer = {'name': 'pied-piper'}
        mock_sidebar_context.return_value = {
            'sidebar-1': 'one',
            'sidebar-2': 'two',
        }

        update_logistration_context_for_enterprise(request, context, enterprise_customer)

        assert context['enable_enterprise_sidebar'] is True
        mock_update_tpa_context.assert_called_once_with(request, context, enterprise_customer)
        mock_enterprise_fields_only.assert_called_once_with(context['data']['registration_form_desc'])
        mock_sidebar_context.assert_called_once_with(enterprise_customer, False)

    @ddt.data(
        {'is_proxy_login': True, 'branding_configuration': {'logo': 'path-to-logo'}},
        {'is_proxy_login': True, 'branding_configuration': {}},
        {'is_proxy_login': False, 'branding_configuration': {'nonsense': 'foo'}},
    )
    @ddt.unpack
    def test_get_enterprise_sidebar_context(self, is_proxy_login, branding_configuration):
        enterprise_customer = {
            'name': 'pied-piper',
            'branding_configuration': branding_configuration,
        }
        actual_result = get_enterprise_sidebar_context(enterprise_customer, is_proxy_login)

        assert 'pied-piper' == actual_result['enterprise_name']
        expected_logo_url = branding_configuration.get('logo', '')
        assert expected_logo_url == actual_result['enterprise_logo_url']
        self.assertIn('pied-piper', str(actual_result['enterprise_branded_welcome_string']))

    @ddt.data(
        ('notfoundpage', 0),
    )
    @ddt.unpack
    def test_enterprise_customer_for_request_called_on_404(self, resource, expected_calls):
        """
        Test enterprise customer API is not called from 404 page
        """
        self.client.login(username=self.user.username, password='password')

        with mock.patch(
            'openedx.features.enterprise_support.api.enterprise_customer_for_request'
        ) as mock_customer_request:
            self.client.get(resource)
            self.assertEqual(mock_customer_request.call_count, expected_calls)

    @mock.patch('openedx.features.enterprise_support.utils.configuration_helpers.get_value')
    def test_enterprise_fields_only(self, mock_get_value):
        mock_get_value.return_value = ['cat', 'dog', 'sheep']
        fields = {
            'fields': [
                {'name': 'cat', 'value': 1},
                {'name': 'fish', 'value': 2},
                {'name': 'dog', 'value': 3},
                {'name': 'emu', 'value': 4},
                {'name': 'sheep', 'value': 5},
            ],
        }

        expected_fields = [
            {'name': 'fish', 'value': 2},
            {'name': 'emu', 'value': 4},
        ]
        assert expected_fields == enterprise_fields_only(fields)

    @mock.patch('openedx.features.enterprise_support.utils.third_party_auth')
    def test_update_third_party_auth_context_for_enterprise(self, mock_tpa):
        context = {
            'data': {
                'third_party_auth': {
                    'errorMessage': 'Widget error.',
                },
            },
        }

        enterprise_customer = mock.Mock()
        request = mock.Mock()

        # This will directly modify context
        update_third_party_auth_context_for_enterprise(request, context, enterprise_customer)

        self.assertIn(
            'We are sorry, you are not authorized',
            str(context['data']['third_party_auth']['errorMessage'])
        )
        self.assertIn(
            'Widget error.',
            str(context['data']['third_party_auth']['errorMessage'])
        )
        assert [] == context['data']['third_party_auth']['providers']
        assert [] == context['data']['third_party_auth']['secondaryProviders']
        self.assertFalse(context['data']['third_party_auth']['autoSubmitRegForm'])
        self.assertIn(
            'Just a couple steps',
            str(context['data']['third_party_auth']['autoRegisterWelcomeMessage'])
        )
        assert 'Continue' == str(context['data']['third_party_auth']['registerFormSubmitButtonText'])

    @mock.patch('openedx.features.enterprise_support.utils.standard_cookie_settings', return_value={})
    def test_handle_enterprise_cookies_for_logistration(self, mock_cookie_settings):
        context = {'enable_enterprise_sidebar': True}
        request = mock.Mock()
        response = mock.Mock()

        handle_enterprise_cookies_for_logistration(request, response, context)

        response.set_cookie.assert_called_once_with(
            'experiments_is_enterprise',
            'true',
        )
        response.delete_cookie.assert_called_once_with(
            settings.ENTERPRISE_CUSTOMER_COOKIE_NAME,
            domain=settings.BASE_COOKIE_DOMAIN,
        )
        mock_cookie_settings.assert_called_once_with(request)

    @override_waffle_flag(ENTERPRISE_HEADER_LINKS, True)
    def test_get_enterprise_learner_portal_uncached(self):
        """
        Test that only an enabled enterprise portal is returned,
        and that it matches the customer UUID provided in the request.
        """
        enterprise_customer_user = EnterpriseCustomerUserFactory(active=True, user_id=self.user.id)
        EnterpriseCustomerBrandingConfigurationFactory(
            enterprise_customer=enterprise_customer_user.enterprise_customer,
        )
        enterprise_customer_user.enterprise_customer.enable_learner_portal = True
        enterprise_customer_user.enterprise_customer.save()

        request = mock.MagicMock(session={}, user=self.user)
        # Indicate the "preferred" customer in the request
        request.GET = {'enterprise_customer': enterprise_customer_user.enterprise_customer.uuid}

        # Create another enterprise customer association for the same user.
        # There should be no data returned for this customer's portal,
        # because we filter for only the enterprise customer uuid found in the request.
        other_enterprise_customer_user = EnterpriseCustomerUserFactory(active=True, user_id=self.user.id)
        other_enterprise_customer_user.enable_learner_portal = True
        other_enterprise_customer_user.save()

        portal = get_enterprise_learner_portal(request)
        self.assertDictEqual(portal, {
            'name': enterprise_customer_user.enterprise_customer.name,
            'slug': enterprise_customer_user.enterprise_customer.slug,
            'logo': enterprise_customer_user.enterprise_customer.safe_branding_configuration.safe_logo_url,
        })

    @override_waffle_flag(ENTERPRISE_HEADER_LINKS, True)
    def test_get_enterprise_learner_portal_no_branding_config(self):
        """
        Test that only an enabled enterprise portal is returned,
        and that it matches the customer UUID provided in the request,
        even if no branding config is associated with the customer.
        """
        enterprise_customer_user = EnterpriseCustomerUserFactory.create(active=True, user_id=self.user.id)
        enterprise_customer_user.enterprise_customer.enable_learner_portal = True
        enterprise_customer_user.enterprise_customer.save()

        request = mock.MagicMock(session={}, user=self.user)
        # Indicate the "preferred" customer in the request
        request.GET = {'enterprise_customer': enterprise_customer_user.enterprise_customer.uuid}

        portal = get_enterprise_learner_portal(request)
        self.assertDictEqual(portal, {
            'name': enterprise_customer_user.enterprise_customer.name,
            'slug': enterprise_customer_user.enterprise_customer.slug,
            'logo': enterprise_customer_user.enterprise_customer.safe_branding_configuration.safe_logo_url,
        })

    @override_waffle_flag(ENTERPRISE_HEADER_LINKS, True)
    def test_get_enterprise_learner_portal_no_customer_from_request(self):
        """
        Test that only one enabled enterprise portal is returned,
        even if enterprise_customer_uuid_from_request() returns None.
        """
        # Create another enterprise customer association for the same user.
        # There should be no data returned for this customer's portal,
        # because another customer is later created with a more recent active/modified time.
        other_enterprise_customer_user = EnterpriseCustomerUserFactory(active=True, user_id=self.user.id)
        other_enterprise_customer_user.enable_learner_portal = True
        other_enterprise_customer_user.save()

        enterprise_customer_user = EnterpriseCustomerUserFactory(active=True, user_id=self.user.id)
        EnterpriseCustomerBrandingConfigurationFactory(
            enterprise_customer=enterprise_customer_user.enterprise_customer,
        )
        enterprise_customer_user.enterprise_customer.enable_learner_portal = True
        enterprise_customer_user.enterprise_customer.save()

        request = mock.MagicMock(session={}, user=self.user)

        with mock.patch(
                'openedx.features.enterprise_support.api.enterprise_customer_uuid_for_request',
                return_value=None,
        ):
            portal = get_enterprise_learner_portal(request)

        self.assertDictEqual(portal, {
            'name': enterprise_customer_user.enterprise_customer.name,
            'slug': enterprise_customer_user.enterprise_customer.slug,
            'logo': enterprise_customer_user.enterprise_customer.safe_branding_configuration.safe_logo_url,
        })

    @override_waffle_flag(ENTERPRISE_HEADER_LINKS, True)
    def test_get_enterprise_learner_portal_cached(self):
        enterprise_customer_data = {
            'name': 'Enabled Customer',
            'slug': 'enabled_customer',
            'logo': 'https://logo.url',
        }
        request = mock.MagicMock(session={
            'enterprise_learner_portal': json.dumps(enterprise_customer_data)
        }, user=self.user)
        portal = get_enterprise_learner_portal(request)
        self.assertDictEqual(portal, enterprise_customer_data)
