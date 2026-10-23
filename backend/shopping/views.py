import os
from django.conf import settings
from django.core.cache import cache
from django.db.models import Count
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from .models import Product,Offer,Shop
from .serializers import ChatSerializer,PreferencesSerializer,SearchSerializer,LocationSerializer
from .services.intent import infer
from .services.search import search_products,serialize_shop
from .services import llm
from .services.research import attach_research
from .services.live import search_live,search_live_in_person,live_product_detail,live_offer_detail,LiveSearchError
from .services.preferences import missing_questions
from .services.questions import clarifications
from .services.web_research import research_product
from .services.visit import assist
from .services.places import search_places,neshan_detail,reverse,ProviderError

class HealthView(APIView):
    throttle_classes=[]
    def get(self,request):
        ai=llm.public_status(llm.request_status())
        return Response({'status':'ok','backend':'django','service':'torob-yar','api_version':3,
            'app_version':'3.0.0','agentic_enabled':True,'instance_id':os.getenv('TOROB_INSTANCE_ID',''),
            'providers':{'neshan_map':bool(settings.NESHAN_MAP_KEY),'neshan_services':bool(settings.NESHAN_SERVICE_KEY),
                         'google_search':bool(settings.SERPER_API_KEY),'google_places':bool(settings.GOOGLE_PLACES_API_KEY)},
            'llm_configured':ai['configured'],'llm_provider':ai['provider'],
            'llm_model':ai['model'],'llm_status':ai['status'],
            'catalog_ready':Product.objects.exists() and Offer.objects.exists(),
            'database_readonly':settings.DATABASE_READONLY,
            'live_search_enabled':settings.TOROB_LIVE_ENABLED,'contacts_published':settings.PUBLISH_PHONE_CONTACTS})

class CatalogView(APIView):
    def get(self,request):
        data=cache.get('catalog_meta')
        if data is None:
            data={'products':Product.objects.count(),'offers':Offer.objects.count(),'shops':Shop.objects.count(),
                'categories':list(Product.objects.values('category').annotate(count=Count('id')).order_by('-count')[:150]),
                'source':'uploaded_dataset','contacts_published':settings.PUBLISH_PHONE_CONTACTS}
            cache.set('catalog_meta',data,60)
        return Response(data)

class AgentChatView(APIView):
    throttle_classes=[ScopedRateThrottle]
    throttle_scope='chat'
    def post(self,request):
        serializer=ChatSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        from .services.agent import run
        return Response(run(serializer.validated_data))

class ChatView(APIView):
    throttle_classes=[ScopedRateThrottle]
    throttle_scope='chat'
    def post(self,request):
        serializer=ChatSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        data=serializer.validated_data;message=data['message'];prefs=infer(message,data.get('preferences',{}))
        ai_status=llm.request_status()
        prefs,_=llm.extract(message,prefs,data['history'],status=ai_status) if message else (prefs,False)
        validator=PreferencesSerializer(data=prefs);validator.is_valid(raise_exception=True);prefs=dict(validator.validated_data)
        questions=[];analysis=None
        if prefs.get('task')=='store':
            visit_result=assist(prefs,data.get('location'),data.get('visit'),message,data['history'],ai_status,data.get('selected_store',''))
            return Response({'products':[],'matched_count':0,'source':'store_research','preferences':prefs,
                'origin':data.get('location'),'analysis':None,'llm':llm.public_status(ai_status),**visit_result})
        missing=missing_questions(prefs,data.get('location'))
        if message and data.get('clarify',True) and missing:
            return Response({'products':[],'matched_count':0,'source':'clarification','origin':data.get('location'),
                'reply':'برای اینکه نتیجه با خواسته‌ات جور باشد، اول این موارد را مشخص کنیم.',
                'preferences':prefs,'questions':missing,'analysis':None,'llm':llm.public_status(ai_status),
                'stage':'clarify','notice':'فیلترهای گفته‌شده حفظ شده‌اند؛ هنوز قیمت یا فروشگاهی تأیید نشده است.'})
        if not prefs.get('category') and not prefs.get('query'):
            questions=[{'key':'product','text':'دنبال چه محصولی هستی؟','choices':['گوشی موبایل','لپ تاپ','هدفون','اسپرسو ساز']}]
            result={'products':[],'matched_count':0,'source':'uploaded_dataset','origin':data.get('location')}
            reply='بگو چه چیزی می‌خوای بخری تا قیمت‌ها و فروشگاه‌های مناسب را با هم بررسی کنیم.'
        else:
            if prefs['search_mode']=='live':
                try:
                    result=search_live_in_person(prefs,data.get('location'))
                except LiveSearchError as e:
                    if settings.TOROB_FALLBACK_TO_DATASET:
                        result=search_products(prefs,data.get('location'),limit=16 if llm.enabled() else 12)
                        result.update(requested_source='live',fallback_reason=e.code,
                            market={'products':[],'status':'unavailable','code':e.code,
                                'message':'دریافت زنده از ترب انجام نشد. نتایج زیر از فایل داده ثبت‌شده‌اند؛ قیمت و موجودی امروز نیاز به تأیید دارند.'})
                    else:
                        result={'products':[],'matched_count':0,'source':'torob_unavailable','origin':data.get('location'),
                            'market':{'products':[],'status':'unavailable','message':str(e),'code':e.code}}
            else:
                result=search_products(prefs,data.get('location'),limit=16 if llm.enabled() else 12)
            questions=clarifications(prefs,result)
            if not data.get('location'):questions.append({'key':'location','text':'برای پیدا کردن نزدیک‌ترین فروشگاه، مبدأ خریدت را انتخاب کن.','choices':[]})
            n=result['matched_count']
            if result.get('source')=='torob_unavailable':
                reply='جستجوی زنده انجام نشد؛ هنوز نمی‌توانم درباره موجودی یا مناسب‌ترین فروشگاه نتیجه‌گیری کنم. مشکل اتصال را در پیام وضعیت ببین یا منبع را به فایل داده تغییر بده.'
            elif result.get('source')=='torob_live':
                checked=result.get('checked_product_count',0)
                reply=f'در بررسی {checked} نتیجه ترب، {n} محصول با فروشنده حضوری تهران و شرایط انتخابی تو پیدا شد.' if n else f'در {checked} نتیجه بررسی‌شده ترب، فروشنده حضوری تهرانی با همه شرایط تو پیدا نشد؛ این به معنی نبودن محصول در کل بازار نیست.'
                if not n and result.get('detail_failures'):
                    reply='فهرست محصولات ترب دریافت شد، اما بخشی از جزئیات فروشندگان در دسترس نبود. هنوز نمی‌توانم درباره مناسب‌ترین فروشگاه نتیجه مطمئن بدهم.'
                if n:
                    best=result['products'][0]['best_offer'];shop=best['shop']
                    reply+=f' پیشنهاد اول «{shop["name"]}» با قیمت {best["price_toman"]:,} تومان است.'
                    if best['distance_km'] is not None:reply+=f' فاصله مستقیم از مبدأ تو {best["distance_km"]} کیلومتر است.'
                    reply+=' '+shop['opening']['label']+'؛ پیش از حرکت موجودی و ساعت حضور را تأیید کن.'
            else:
                reply=f'{n} محصول با پیشنهاد فروش ثبت‌شده با انتخاب‌های تو سازگار است. این نتایج از فایل‌اند؛ موجودی امروز را پیش از حرکت تأیید کن.' if n else 'با همه شرایط انتخابی، پیشنهادی در فایل ثبت‌شده پیدا نشد.'
            attach_research(result['products'],prefs)
            result['web_research']=research_product(prefs,result['products'])
            # Analysis runs independently of extraction, including filter-only requests.
            if llm.enabled():
                analysis=llm.analyze(prefs,result['products'],message=message,history=data['history'],
                    retrieval=result,status=ai_status)
            if result['products'] and prefs.get('needs') and not ai_status['analysis_used']:
                evidence=result['products'][0]['research']['relevant_specs']
                if evidence:
                    reply+=' برای نیاز «'+prefs['needs']+'»، این مشخصاتِ پیشنهاد اول ثبت شده: '+'؛ '.join(str(s['key'])+': '+str(s['value'])[:120] for s in evidence[:2])+'. مقایسه فنی کامل را در جزئیات محصول ببین.'
                else:reply+=' برای ارزیابی نیاز «'+prefs['needs']+'»، مشخصات کافی ثبت نشده است.'
            if analysis:
                order=analysis['ranked_product_ids']
                # With no evidence the server keeps its factual no-results/error message.
                if result['products']:reply=analysis['explanation']
                if order and prefs.get('sort')=='recommended':
                    by_id={r['id']:r for r in result['products']}
                    result['products']=[by_id[i] for i in order]+[r for r in result['products'] if r['id'] not in order]
                    for i,r in enumerate(result['products']):
                        r['badges']=[b for b in r.get('badges',[]) if b not in ('پیشنهاد ترب‌یار','پیشنهاد زنده ترب‌یار')]
                        if i==0:r['badges'].insert(0,'پیشنهاد ترب‌یار')
                elif prefs.get('sort') in ('price','distance'):
                    analysis['ranked_product_ids']=[r['id'] for r in result['products'][:12]]
                if analysis['follow_up'] and not (analysis['follow_up']['key']=='budget' and (prefs.get('budget_max') or prefs.get('budget_any'))) and not (analysis['follow_up']['key']=='color' and (prefs.get('color') or prefs.get('color_any'))):
                    questions=[analysis['follow_up']]+[q for q in questions if q['key']=='location']
            result['products']=result['products'][:12]
            if analysis:
                visible={r['id'] for r in result['products']}
                analysis['product_analysis']=[a for a in analysis['product_analysis'] if a['product_id'] in visible]
                by_id={a['product_id']:a for a in analysis['product_analysis']}
                for product in result['products']:
                    if product['id'] in by_id:product['ai_analysis']=by_id[product['id']]
        return Response({**result,'reply':reply,'preferences':prefs,'questions':questions[:2],
            'llm':llm.public_status(ai_status),'analysis':analysis,
            'notice':'منبع هر کارت مشخص است. دریافت زنده آگهی یا ساعت اعلام‌شده، تضمین موجودی یا حضور واقعی فروشنده نیست.'})

class ProductView(APIView):
    def post(self,request,product_id):
        serializer=ChatSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        data=serializer.validated_data
        result=search_products(dict(data.get('preferences',{})),location=data.get('location'),product_id=product_id,limit=1)
        if not result['products']:return Response({'detail':'فروشنده سازگار با فیلترهای فعلی پیدا نشد.'},status=404)
        return Response(result['products'][0])
    def get(self,request,product_id):
        location=None
        if 'lat' in request.query_params or 'lon' in request.query_params:
            serializer=LocationSerializer(data=request.query_params);serializer.is_valid(raise_exception=True);location=serializer.validated_data
        result=search_products({},location=location,product_id=product_id,limit=1)
        if not result['products']:return Response({'detail':'محصول دارای پیشنهاد فروش پیدا نشد.'},status=404)
        return Response(result['products'][0])

class ShopView(APIView):
    def get(self,request,shop_id):
        try:shop=Shop.objects.get(pk=shop_id)
        except Shop.DoesNotExist:return Response({'detail':'فروشگاه پیدا نشد.'},status=404)
        return Response({**serialize_shop(shop),'product_count':shop.offers.values('product_id').distinct().count()})

class LiveView(APIView):
    throttle_classes=[ScopedRateThrottle]
    throttle_scope='live'
    def get(self,request):
        serializer=SearchSerializer(data=request.query_params);serializer.is_valid(raise_exception=True)
        prefs=PreferencesSerializer(data={**request.query_params.dict(),'query':serializer.validated_data['q']});prefs.is_valid(raise_exception=True)
        try:return Response(search_live_in_person(prefs.validated_data).get('market'))
        except LiveSearchError as e:return Response({'detail':str(e),'code':e.code,'source':'torob_live','available':False},status=502)
    def post(self,request):
        serializer=ChatSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        data=serializer.validated_data;prefs=PreferencesSerializer(data=data.get('preferences',{}));prefs.is_valid(raise_exception=True)
        if not any(prefs.validated_data.get(k) for k in ('category','query','model')):return Response({'detail':'محصول یا مدل را مشخص کن.'},status=400)
        try:return Response(search_live_in_person(prefs.validated_data,data.get('location'))['market'])
        except LiveSearchError as e:return Response({'detail':str(e),'code':e.code,'source':'torob_live','available':False},status=502)

class MapConfigView(APIView):
    def get(self,request):
        return Response({'provider':'neshan','default_provider':'google','map_key':settings.NESHAN_MAP_KEY,
            'google_browser_key':settings.GOOGLE_MAPS_BROWSER_KEY,
            'sdk_url':'https://static.neshan.org/sdk/maplibre/5.24.3/neshan-maplibre-sdk.umd.js',
            'sdk_css':'https://static.neshan.org/sdk/maplibre/5.24.3/neshan-maplibre-sdk.css',
            'style':'https://static.neshan.org/sdk/maplibre/styles/light.json'})

class PlacesView(APIView):
    throttle_classes=[ScopedRateThrottle];throttle_scope='live'
    def post(self,request):
        from rest_framework import serializers
        class Query(serializers.Serializer):
            query=serializers.CharField(max_length=250)
            location=LocationSerializer(required=False,allow_null=True)
        s=Query(data=request.data);s.is_valid(raise_exception=True)
        return Response(search_places(s.validated_data['query'],s.validated_data.get('location')))

class PlaceDetailView(APIView):
    throttle_classes=[ScopedRateThrottle];throttle_scope='live'
    def get(self,request,poi_hash):
        try:return Response(neshan_detail(poi_hash))
        except ProviderError as e:return Response({'detail':'اطلاعات این مکان از نشان دریافت نشد.','code':'neshan_'+e.code},status=502)

class PositionView(APIView):
    throttle_classes=[ScopedRateThrottle];throttle_scope='live'
    def post(self,request):
        s=LocationSerializer(data=request.data);s.is_valid(raise_exception=True)
        try:return Response(reverse(s.validated_data))
        except ProviderError as e:return Response({'detail':'تبدیل موقعیت به آدرس از نشان انجام نشد.','code':'neshan_'+e.code},status=502)

class LiveProductView(APIView):
    throttle_classes=[ScopedRateThrottle]
    throttle_scope='live'
    def post(self,request,product_id):
        serializer=ChatSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        data=serializer.validated_data
        try:
            product=live_product_detail(product_id,dict(data.get('preferences',{})),data.get('location'))
            if not product:return Response({'detail':'فروشنده حضوری سازگار با شرایط انتخابی پیدا نشد.'},status=404)
            attach_research([product],dict(data.get('preferences',{})))
            return Response(product)
        except LiveSearchError as e:return Response({'detail':str(e),'code':e.code},status=502)

class LiveOfferView(APIView):
    throttle_classes=[ScopedRateThrottle]
    throttle_scope='live'
    def post(self,request,product_id,offer_id):
        serializer=ChatSerializer(data=request.data);serializer.is_valid(raise_exception=True)
        data=serializer.validated_data
        try:
            offer=live_offer_detail(product_id,offer_id,dict(data.get('preferences',{})),data.get('location'))
            if not offer:return Response({'detail':'پیشنهاد فروش سازگار با انتخاب فعلی پیدا نشد.'},status=404)
            return Response(offer)
        except LiveSearchError as e:return Response({'detail':str(e),'code':e.code},status=502)
