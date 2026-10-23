from django.urls import path
from .views import HealthView,CatalogView,ChatView,AgentChatView,ProductView,ShopView,LiveView,LiveProductView,LiveOfferView,MapConfigView,PlacesView,PlaceDetailView,PositionView
urlpatterns=[path('health/',HealthView.as_view()),path('catalog/',CatalogView.as_view()),path('chat/',ChatView.as_view()),
    path('agent/chat/',AgentChatView.as_view()),
    path('products/<str:product_id>/',ProductView.as_view()),path('shops/<str:shop_id>/',ShopView.as_view()),path('live-search/',LiveView.as_view()),
    path('live-products/<str:product_id>/',LiveProductView.as_view()),
    path('live-products/<str:product_id>/offers/<str:offer_id>/',LiveOfferView.as_view()),
    path('map-config/',MapConfigView.as_view()),path('places/search/',PlacesView.as_view()),
    path('places/<str:poi_hash>/',PlaceDetailView.as_view()),path('position/',PositionView.as_view())]
