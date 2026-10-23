"""Checked, streaming snapshots of catalog values, without duplicate SQL indexes."""
from contextlib import closing
import hashlib
import json
import lzma
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'backend'))
from shopping.catalog_codec import encode_json, decode_json

TABLES = ('shopping_shop', 'shopping_product', 'shopping_offer')
DOCUMENTS = {
    'shopping_shop': ('categories', 'images', 'licenses', 'weekly_hours', 'contacts', 'payment_options'),
    'shopping_product': ('specs', 'images'),
    'shopping_offer': ('warranty',),
}


def compact_line(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8')


def inspect_catalog(database):
    with closing(sqlite3.connect(database)) as connection:
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('SQLite catalog integrity check failed.')
        if connection.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Catalog contains broken product/shop references.')
        counts = {label: connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                  for label, table in zip(('shops','products','offers'), TABLES)}
        marker = connection.execute('SELECT source_key FROM shopping_importstate WHERE completed=1 ORDER BY updated_at DESC LIMIT 1').fetchone()
        if not marker or not all(counts.values()):
            raise RuntimeError('Catalog import did not complete.')
    return {'schema_version': 2, 'source_key': marker[0], 'counts': counts, 'storage_codec': 'TYJ1'}


def pack_catalog(database, output):
    database, output = Path(database), Path(output)
    info = inspect_catalog(database)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.catalog-', dir=output.parent)
    os.close(fd)
    digest = hashlib.sha256()
    try:
        with closing(sqlite3.connect(database)) as connection:
            if connection.execute('SELECT count(*) FROM auth_user').fetchone()[0]:
                raise RuntimeError('Refusing to package a catalog containing user accounts.')
            columns = {table:[r[1] for r in connection.execute('PRAGMA table_info('+table+')')] for table in TABLES}
            header = {'format': 'torob-catalog', 'version': 2, 'columns': columns}
            with open(temporary, 'wb') as target, lzma.open(target, 'wb', preset=6) as compressed:
                def write(value):
                    line = compact_line(value)
                    digest.update(line)
                    compressed.write(line)
                write(header)
                def rows(table, order):
                    docs = [columns[table].index(name) for name in DOCUMENTS[table]]
                    names = ','.join('"'+name+'"' for name in columns[table])
                    for row in connection.execute('SELECT '+names+' FROM '+table+' NOT INDEXED ORDER BY '+order):
                        values=list(row)
                        for pos in docs:values[pos]=decode_json(values[pos])
                        yield values
                # Store each FK once: offers live under their product, and shops
                # use small ordinal references. Public IDs are restored unchanged.
                shop_id_pos=columns[TABLES[0]].index('id')
                shops={}
                for values in rows(TABLES[0],'id'):
                    shops[values[shop_id_pos]]=len(shops)
                    write([0,values])
                p_id=columns[TABLES[1]].index('id')
                p_title=columns[TABLES[1]].index('title')
                o_product=columns[TABLES[2]].index('product_id')
                o_shop=columns[TABLES[2]].index('shop_id')
                o_title=columns[TABLES[2]].index('seller_title')
                offers=iter(rows(TABLES[2],'product_id,id'))
                offer=next(offers,None)
                for product in rows(TABLES[1],'id'):
                    linked=[]
                    while offer is not None and offer[o_product]==product[p_id]:
                        offer[o_shop]=shops[offer[o_shop]]
                        if offer[o_title]==product[p_title]:offer[o_title]=None
                        linked.append([v for pos,v in enumerate(offer) if pos!=o_product])
                        offer=next(offers,None)
                    write([1,product,linked])
                if offer is not None:raise RuntimeError('Snapshot has an unlinked offer.')
        info.update(bundle_version=2, catalog_kind='full', logical_sha256=digest.hexdigest())
        os.replace(temporary, output)
        output.with_name('catalog.json').write_text(json.dumps(info, indent=2)+'\n', encoding='utf-8')
    finally:
        Path(temporary).unlink(missing_ok=True)
    return info


def load_catalog(archive, database):
    """Populate only an empty, migrated staging DB. Never overwrite a user's DB."""
    archive, database = Path(archive), Path(database)
    info = json.loads(archive.with_name('catalog.json').read_text(encoding='utf-8'))
    if info.get('bundle_version') != 2 or info.get('storage_codec') != 'TYJ1':
        raise RuntimeError('Unsupported packaged catalog; regenerate its snapshot.')
    digest = hashlib.sha256()
    counts = [0, 0, 0]
    with closing(sqlite3.connect(database)) as connection, lzma.open(archive, 'rb') as source:
        connection.execute('PRAGMA foreign_keys=ON')
        if any(connection.execute('SELECT EXISTS(SELECT 1 FROM '+t+')').fetchone()[0] for t in TABLES):
            raise RuntimeError('Snapshot loading requires an empty staging catalog.')
        line = source.readline()
        digest.update(line)
        header = json.loads(line)
        columns = {table:[r[1] for r in connection.execute('PRAGMA table_info('+table+')')] for table in TABLES}
        if header.get('format') != 'torob-catalog' or header.get('version') != 2 or header.get('columns') != columns:
            raise RuntimeError('Snapshot schema does not match this application.')
        inserts = ['INSERT INTO '+table+' VALUES('+','.join('?' for _ in columns[table])+')' for table in TABLES]
        docs = [[columns[table].index(name) for name in DOCUMENTS[table]] for table in TABLES]
        # Construct secondary indexes once; PK and FK constraints stay active.
        indexes = connection.execute("SELECT name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL AND tbl_name IN (?,?,?)", TABLES).fetchall()
        with connection:
            connection.execute('BEGIN')
            for name, _ in indexes:
                connection.execute('DROP INDEX "'+name.replace('"','""')+'"')
            batches=[[],[],[]]
            shops=[];previous=0
            p_id=columns[TABLES[1]].index('id')
            p_title=columns[TABLES[1]].index('title')
            o_product=columns[TABLES[2]].index('product_id')
            o_shop=columns[TABLES[2]].index('shop_id')
            o_title=columns[TABLES[2]].index('seller_title')
            def add(index,values):
                if not isinstance(values,list) or len(values)!=len(columns[TABLES[index]]):
                    raise RuntimeError('Malformed catalog values.')
                for pos in docs[index]:values[pos]=encode_json(values[pos])
                batches[index].append(values)
                counts[index]+=1
            def flush():
                for index,batch in enumerate(batches):
                    if batch:connection.executemany(inserts[index],batch)
                    batch.clear()
            for line in source:
                digest.update(line)
                record=json.loads(line)
                index=record[0]
                if type(index) is not int or index not in (0,1) or index < previous or len(record)!=(2 if index==0 else 3):
                    raise RuntimeError('Malformed catalog record.')
                values=record[1]
                if index==0:
                    shops.append(values[columns[TABLES[0]].index('id')])
                else:
                    product_id,title=values[p_id],values[p_title]
                    for offer in record[2]:
                        offer.insert(o_product,product_id)
                        ref=offer[o_shop]
                        if type(ref) is not int or not 0<=ref<len(shops):raise RuntimeError('Invalid shop reference.')
                        offer[o_shop]=shops[ref]
                        if offer[o_title] is None:offer[o_title]=title
                        add(2,offer)
                add(index,values)
                previous=index
                if max(map(len,batches))>=1000:flush()
            flush()
            expected = [info['counts'][label] for label in ('shops','products','offers')]
            if counts != expected or digest.hexdigest() != info['logical_sha256']:
                raise RuntimeError('Catalog checksum/count verification failed; use an intact project ZIP.')
            for _, sql in indexes:
                connection.execute(sql)
        return info
