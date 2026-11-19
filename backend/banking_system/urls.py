"""
URL Configuration for SecureBank
"""

from django.contrib import admin
from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve

from core.views import HomeView

urlpatterns = [
    path(
        "",
        HomeView.as_view(),
        name="home"
    ),

    path(
        "accounts/",
        include(
            "accounts.urls",
            namespace="accounts"
        )
    ),

    path(
        "transactions/",
        include(
            "transactions.urls",
            namespace="transactions"
        )
    ),

    path(
        "assistant/",
        include(
            "ai_assistant.urls",
            namespace="ai_assistant"
        )
    ),

    path("api/", include("api.urls", namespace="api")),

    # React frontend (served from ../frontend)
    re_path(r"^app/(?P<path>.*)$", lambda r, path: serve(r, path or "index.html", document_root=settings.FRONTEND_DIR)),

    path(
        "admin/",
        admin.site.urls
    ),
]