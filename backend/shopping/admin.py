from django.contrib import admin
from .models import Shop, Product, Offer
@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ['name','location_label','supports_fast_delivery']
    search_fields = ['name','address','id']
    list_filter = ['supports_fast_delivery']
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['title','brand','category']
    search_fields = ['title','id']
    list_filter = ['category']
@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ['seller_title','price_toman','last_price_changed_at']
    search_fields = ['seller_title','id']
    raw_id_fields = ['product','shop']
