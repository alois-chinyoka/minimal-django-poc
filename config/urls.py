from django.urls import path
from tasks.views import task_list, task_create, health_check

urlpatterns = [
    path('health/', health_check, name='health'),
    path('api/tasks/', task_list, name='task_list'),
    path('api/tasks/create/', task_create, name='task_create'),
]
