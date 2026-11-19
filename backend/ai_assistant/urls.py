from django.urls import path
from .views import AssistantView

app_name = 'ai_assistant'

urlpatterns = [
    path('chat/', AssistantView.as_view(), name='chat'),
]