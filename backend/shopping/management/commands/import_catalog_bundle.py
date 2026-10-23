"""Load the compact full dataset into an empty build database."""
from pathlib import Path
import sys
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from shopping.catalog_index import drop_index, rebuild_index
from shopping.models import ImportState


class Command(BaseCommand):
    help = 'Load a verified compact catalog into an empty staging database.'

    def add_arguments(self, parser):
        parser.add_argument('source', type=Path)

    def handle(self, *args, **options):
        if connection.vendor != 'sqlite':
            raise CommandError('The compact catalog package requires SQLite.')
        sys.path.insert(0, str(Path(__file__).resolve().parents[4]/'scripts'))
        from catalog_bundle import load_catalog
        # Refuse before changing any index if the destination already has data.
        with connection.cursor() as cursor:
            for table in ('shopping_shop','shopping_product','shopping_offer'):
                cursor.execute('SELECT EXISTS(SELECT 1 FROM '+table+')')
                if cursor.fetchone()[0]:
                    raise CommandError('Use an empty staging database; existing records are preserved.')
        drop_index(connection)
        try:
            info = load_catalog(options['source'], connection.settings_dict['NAME'])
            with transaction.atomic():
                rebuild_index(connection)
                ImportState.objects.update_or_create(source_key=info['source_key'],
                    defaults={'completed': True, 'progress': {'counts': info['counts'], 'compact_bundle': True}})
        except (ValueError, RuntimeError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write('Compact catalog ready: '+str(info['counts']))
