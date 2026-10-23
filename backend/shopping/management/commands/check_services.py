"""Show safe configuration status and optionally run bounded read-only checks."""
import json
from django.core.management.base import BaseCommand
from django.conf import settings
from shopping.services.places import search_places,reverse,ProviderError
from shopping.services.web_research import google_search
from shopping.services.live import search_live,LiveSearchError
from shopping.services import llm

class Command(BaseCommand):
    help='Check Torob/Neshan/Google integrations; --live performs external requests.'
    def add_arguments(self,p):
        p.add_argument('--live',action='store_true')
        p.add_argument('--query',default='پاساژ چارسو')
        p.add_argument('--lat',type=float,default=35.695)
        p.add_argument('--lon',type=float,default=51.414)
    def handle(self,*args,**options):
        result={'configured':{'neshan_map':bool(settings.NESHAN_MAP_KEY),'neshan_services':bool(settings.NESHAN_SERVICE_KEY),
            'google_search':bool(settings.SERPER_API_KEY),'google_places':bool(settings.GOOGLE_PLACES_API_KEY)},
            'llm':llm.public_status(llm.request_status()),'live_checks':options['live']}
        if options['live']:
            location={'lat':options['lat'],'lon':options['lon']};query=options['query']
            result['places']=search_places(query,location)
            result['web']=google_search(query)
            try:result['reverse']=reverse(location)
            except ProviderError as e:result['reverse']={'status':e.code}
            try:
                market=search_live('سامسونگ A55');result['torob']={'status':market['status'],'count':len(market['products']),'retrieved_at':market['retrieved_at']}
            except LiveSearchError as e:result['torob']={'status':e.code}
        self.stdout.write(json.dumps(result,ensure_ascii=False,indent=2,default=str))
