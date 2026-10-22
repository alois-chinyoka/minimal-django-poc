from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json
from tasks.models import Task

def health_check(request):
    """Health check endpoint for Kubernetes probes"""
    return JsonResponse({'status': 'healthy'})

def task_list(request):
    """List all tasks"""
    tasks = Task.objects.all().values('id', 'title', 'description', 'completed', 'created_at')
    return JsonResponse({'tasks': list(tasks)})

@require_http_methods(["POST"])
@csrf_exempt
def task_create(request):
    """Create a new task"""
    try:
        data = json.loads(request.body)
        task = Task.objects.create(
            title=data.get('title'),
            description=data.get('description', '')
        )
        return JsonResponse({
            'id': task.id,
            'title': task.title,
            'description': task.description,
            'completed': task.completed,
            'created_at': task.created_at.isoformat()
        }, status=201)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
