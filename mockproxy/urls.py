from django.urls import re_path

from mocks import views

# first match wins. Exact paths stay exact, the admin api tolerates a trailing slash.
# Whatever no route claims (and /api/send, /api/version, /rule-content with the wrong
# method) is the rule engine's: that is how /api/users can be mocked.
urlpatterns = [
    re_path(r"^health$", views.health),
    re_path(r"^(?:ui)?$", views.ui),
    re_path(r"^ca\.(?:pem|crt)$", views.ca_pem),
    re_path(r"^api/send$", views.send),
    re_path(r"^api/proxy/decide$", views.proxy_decide),
    re_path(r"^api/proxy/seen$", views.proxy_seen),
    re_path(r"^api/version(?:/.*)?$", views.version),
    re_path(r"^api/mock-state(?:/.*)?$", views.mock_state),
    re_path(r"^api/metrics/?$", views.metrics),
    re_path(r"^api/metrics/reset/?$", views.metrics_reset),
    re_path(r"^api/rules/?$", views.rules),
    re_path(r"^api/rules/(?P<name>[^/]+)/?$", views.rule_item),
    re_path(r"^api/rules/(?P<name>[^/]+)/toggle/?$", views.rule_toggle),
    re_path(r"^api/history/?$", views.history),
    re_path(r"^api/history/(?P<ident>[^/]+)/restore/?$", views.history_restore),
    re_path(r"^api/rule-content/?$", views.content_list),
    re_path(r"^api/rule-content/(?P<name>[^/]+)/?$", views.content_item),
    re_path(
        r"^api/(?:mock-state|metrics|rules|history|rule-content|proxy)(?:/.*)?$",
        views.no,
    ),
    re_path(r"^rule-content/(?P<name>.*)$", views.content_serve),
    re_path(r"^", views.mock),
]
