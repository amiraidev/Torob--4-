import math
from rest_framework import serializers

class PreferencesSerializer(serializers.Serializer):
    task = serializers.ChoiceField(['shopping','store'],required=False,default='shopping')
    store_query = serializers.CharField(max_length=250,allow_blank=True,required=False,default='')
    model = serializers.CharField(max_length=150,allow_blank=True,required=False,default='')
    product_type = serializers.CharField(max_length=150,allow_blank=True,required=False,default='')
    condition = serializers.ChoiceField(['any','new','used'],required=False,default='any')
    size = serializers.CharField(max_length=80,allow_blank=True,required=False,default='')
    search_mode = serializers.ChoiceField(['live','dataset'],required=False,default='live')
    needs = serializers.CharField(max_length=350,allow_blank=True,required=False,default='')
    visit_at = serializers.DateTimeField(allow_null=True,required=False,default=None)
    query = serializers.CharField(max_length=250,allow_blank=True,required=False,default='')
    category = serializers.CharField(max_length=300,allow_blank=True,required=False,default='')
    brand = serializers.CharField(max_length=100,allow_blank=True,required=False,default='')
    color = serializers.CharField(max_length=80,allow_blank=True,required=False,default='')
    brand_any = serializers.BooleanField(required=False,default=False)
    color_any = serializers.BooleanField(required=False,default=False)
    budget_any = serializers.BooleanField(required=False,default=False)
    budget_max = serializers.IntegerField(min_value=1,max_value=10**13,allow_null=True,required=False,default=None)
    budget_min = serializers.IntegerField(min_value=0,max_value=10**13,required=False,default=0)
    only_open = serializers.BooleanField(required=False,default=False)
    installment = serializers.BooleanField(required=False,default=False)
    torobpay = serializers.BooleanField(required=False,default=False)
    fast_delivery = serializers.BooleanField(required=False,default=False)
    radius_km = serializers.FloatField(min_value=.1,max_value=200,allow_null=True,required=False,default=None)
    sort = serializers.ChoiceField(['recommended','price','distance'],required=False,default='recommended')
    def validate(self,attrs):
        if attrs.get('radius_km') is not None and not math.isfinite(attrs['radius_km']):
            raise serializers.ValidationError('شعاع باید عدد متناهی باشد.')
        if attrs.get('budget_max') and attrs.get('budget_min',0)>attrs['budget_max']:
            raise serializers.ValidationError('حداقل بودجه از حداکثر بیشتر است.')
        return attrs

class LocationSerializer(serializers.Serializer):
    lat=serializers.FloatField(min_value=35,max_value=36.2)
    lon=serializers.FloatField(min_value=50.5,max_value=52)
    label=serializers.CharField(max_length=100,required=False,default='موقعیت انتخابی')
    approximate=serializers.BooleanField(required=False,default=True)
    accuracy_m=serializers.FloatField(min_value=0,max_value=100000,allow_null=True,required=False,default=None)
    def validate(self,attrs):
        if not all(math.isfinite(attrs[key]) for key in ('lat','lon')):
            raise serializers.ValidationError('مختصات باید عدد متناهی باشد.')
        if attrs.get('accuracy_m') is not None and not math.isfinite(attrs['accuracy_m']):
            raise serializers.ValidationError('دقت موقعیت معتبر نیست.')
        return attrs

class VisitSerializer(serializers.Serializer):
    store_name=serializers.CharField(max_length=180,required=False,allow_blank=True,default='')
    mall=serializers.CharField(max_length=180,required=False,allow_blank=True,default='')
    floor=serializers.CharField(max_length=50,required=False,allow_blank=True,default='')
    unit=serializers.CharField(max_length=50,required=False,allow_blank=True,default='')
    stage=serializers.ChoiceField(['visit','inspect','checkout','aftercare'],required=False,default='visit')
    quoted_price=serializers.IntegerField(min_value=1,max_value=10**13,required=False,allow_null=True,default=None)

class MessageSerializer(serializers.Serializer):
    role=serializers.ChoiceField(['user','assistant'])
    content=serializers.CharField(max_length=3000)

class ChatSerializer(serializers.Serializer):
    message=serializers.CharField(max_length=1500,allow_blank=True,required=False,default='')
    preferences=PreferencesSerializer(required=False)
    location=LocationSerializer(required=False,allow_null=True)
    history=MessageSerializer(many=True,required=False,max_length=12,default=list)
    visit=VisitSerializer(required=False)
    clarify=serializers.BooleanField(required=False,default=True)
    selected_store=serializers.CharField(max_length=18000,allow_blank=True,required=False,default='')
    agent_state=serializers.CharField(max_length=400000,allow_blank=True,required=False,default='')
    comparison_ids=serializers.ListField(child=serializers.CharField(max_length=100),max_length=4,required=False,default=list)

class SearchSerializer(serializers.Serializer):
    q=serializers.CharField(max_length=200)
