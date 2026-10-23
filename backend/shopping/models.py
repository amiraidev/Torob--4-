from django.db import models
from .fields import CompactJSONField

class ImportState(models.Model):
    """Committed input offsets, saved in the same transaction as each data batch."""
    source_key = models.CharField(max_length=64, primary_key=True)
    progress = models.JSONField(default=dict)
    completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

class Shop(models.Model):
    id = models.CharField(max_length=80,primary_key=True)
    name = models.CharField(max_length=500)
    business_type = models.CharField(max_length=120,blank=True)
    description = models.TextField(blank=True)
    categories = CompactJSONField(default=list)
    images = CompactJSONField(default=list)
    licenses = CompactJSONField(default=list)
    torob_since = models.DateField(null=True,blank=True)
    address = models.TextField(blank=True)
    location_label = models.CharField(max_length=300,blank=True)
    lat = models.FloatField(null=True,blank=True)
    lon = models.FloatField(null=True,blank=True)
    weekly_hours = CompactJSONField(default=dict)
    contacts = CompactJSONField(default=list)
    payment_options = CompactJSONField(default=list)
    supports_fast_delivery = models.BooleanField(null=True,blank=True)
    supports_kalabarg = models.BooleanField(null=True,blank=True)
    website_url = models.TextField(blank=True)
    instagram = models.TextField(blank=True)
    class Meta:
        verbose_name = 'فروشگاه'
        verbose_name_plural = 'فروشگاه‌ها'
    def __str__(self): return self.name

class Product(models.Model):
    id = models.CharField(max_length=80,primary_key=True)
    title = models.CharField(max_length=1500)
    english_title = models.CharField(max_length=1500,blank=True)
    brand = models.CharField(max_length=300,blank=True,db_index=True)
    category = models.CharField(max_length=300,blank=True,db_index=True)
    model = models.CharField(max_length=1000,blank=True)
    specs = CompactJSONField(default=list)
    images = CompactJSONField(default=list)
    search_text = models.TextField(blank=True)
    color_text = models.TextField(blank=True)
    class Meta:
        verbose_name = 'محصول'
        verbose_name_plural = 'محصولات'
    def __str__(self): return self.title

class Offer(models.Model):
    id = models.CharField(max_length=80,primary_key=True)
    # Composite indexes below already cover these foreign-key prefixes.
    product = models.ForeignKey(Product,on_delete=models.CASCADE,related_name='offers',db_index=False)
    shop = models.ForeignKey(Shop,on_delete=models.CASCADE,related_name='offers',db_index=False)
    seller_title = models.TextField(blank=True)
    description = models.TextField(blank=True)
    price_toman = models.PositiveBigIntegerField(null=True,blank=True,db_index=True)
    warranty = CompactJSONField(null=True,blank=True)
    last_price_changed_at = models.DateTimeField(null=True,blank=True)
    class Meta:
        indexes = [models.Index(fields=['product','price_toman']),models.Index(fields=['shop','product'])]
        verbose_name = 'پیشنهاد فروش'
        verbose_name_plural = 'پیشنهادهای فروش'
    def __str__(self): return self.seller_title[:80]
