"""Test the configured private model connection without printing credentials."""
from django.core.management.base import BaseCommand, CommandError
from shopping.services import llm


class Command(BaseCommand):
    help = 'Test BoxAPI using LLM_* server settings. Makes one small, billable request.'

    def handle(self, *args, **options):
        status = llm.request_status()
        if not status['configured']:
            public = llm.public_status(status)
            raise CommandError('اتصال مدل آماده نیست؛ تحلیل AI انجام نشد. [' + public['status'] + ']')
        result = llm.json_call(
            'Reply with ONLY this JSON object: {"ok": true}. Do not add any text.',
            {'task': 'connection_check'}, status=status, max_tokens=80)
        if not result or result.get('ok') is not True:
            if result is not None:
                status['analysis_status'] = 'invalid_response'
            public = llm.public_status(status)
            raise CommandError('اتصال یا پاسخ معتبر مدل تأیید نشد؛ تحلیل AI تکمیل نشد. [' + public['status'] + ']')
        self.stdout.write(self.style.SUCCESS('BoxAPI connection and model response: OK'))
        self.stdout.write('Model: ' + status['model'])
        self.stdout.write('No API key was printed. Product analysis uses real retrieval evidence during chat.')

