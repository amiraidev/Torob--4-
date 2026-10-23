"""Merge a packaged catalog into an older database, preserving existing records."""
import json
from pathlib import Path

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from shopping.models import Shop, Product, Offer, ImportState
from shopping.management.commands.import_torob import Command as ImportCommand


class Command(BaseCommand):
    help = 'Initialize bundled catalog records without overwriting existing data.'

    def add_arguments(self, parser):
        parser.add_argument('--seed', type=Path, required=True)
        parser.add_argument('--refresh', action='store_true', help='Explicitly refresh matching catalog records from this seed.')

    def handle(self, *args, **options):
        seed = options['seed'].resolve()
        manifest = seed.with_suffix('.json')
        if not seed.is_file() or not manifest.is_file():
            raise CommandError('Packaged catalog or manifest is missing; rebuild the Docker image.')
        info = json.loads(manifest.read_text(encoding='utf-8'))
        marker = info['source_key']
        if not options['refresh'] and ImportState.objects.filter(source_key=marker, completed=True).exists():
            self.stdout.write('Catalog already initialized; keeping existing records.')
            return
        if connection.vendor != 'sqlite':
            raise CommandError('This single-container package uses SQLite.')
        added = {}
        with connection.cursor() as cursor:
            cursor.execute('ATTACH DATABASE %s AS packaged_catalog', [str(seed)])
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    for model in (Shop, Product, Offer):
                        table = connection.ops.quote_name(model._meta.db_table)
                        columns = ','.join(connection.ops.quote_name(f.column) for f in model._meta.local_fields)
                        if options['refresh']:
                            updates=','.join(connection.ops.quote_name(f.column)+'=excluded.'+connection.ops.quote_name(f.column)
                                for f in model._meta.local_fields if not f.primary_key)
                            cursor.execute(f'INSERT INTO main.{table} ({columns}) SELECT {columns} FROM packaged_catalog.{table} WHERE 1=1 ON CONFLICT(id) DO UPDATE SET {updates}')
                        else:
                            cursor.execute(f'INSERT OR IGNORE INTO main.{table} ({columns}) SELECT {columns} FROM packaged_catalog.{table}')
                        cursor.execute('SELECT changes()')
                        added[model._meta.model_name] = cursor.fetchone()[0]
                ImportCommand().rebuild_fts()
                ImportState.objects.update_or_create(
                    source_key=marker,
                    defaults={'completed': True, 'progress': {'counts': info['counts'], 'packaged_seed': True}})
        finally:
            with connection.cursor() as cursor:
                cursor.execute('DETACH DATABASE packaged_catalog')
        cache.delete('catalog_meta')
        self.stdout.write('Catalog merge complete; existing records preserved: '+str(added))

