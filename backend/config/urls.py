from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.http import FileResponse,JsonResponse
def frontend(request):
    index=settings.ROOT_DIR/'dist/index.html'
    if not index.exists():return JsonResponse({'detail':'Build React first: npm run build'},status=503)
    if request.method!='GET':return JsonResponse({'detail':'Method not allowed'},status=405)
    return FileResponse(index.open('rb'),content_type='text/html; charset=utf-8')
urlpatterns = [path('admin/',admin.site.urls),path('api/',include('shopping.urls'))]
urlpatterns += [re_path(r'^(?!api/|admin/).*$',frontend)]
admin.site.site_header = 'مدیریت ترب‌یار'
admin.site.site_title = 'ترب‌یار'
