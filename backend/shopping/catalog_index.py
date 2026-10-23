"""A compact FTS5 index referring to the existing product text, with live updates."""


def drop_index(connection):
    if connection.vendor != 'sqlite':
        return
    with connection.cursor() as cursor:
        for name in ('product_fts_insert', 'product_fts_delete', 'product_fts_update'):
            cursor.execute('DROP TRIGGER IF EXISTS '+name)
        cursor.execute('DROP TABLE IF EXISTS product_fts')
        cursor.execute('DROP VIEW IF EXISTS product_fts_content')


def rebuild_index(connection):
    if connection.vendor != 'sqlite':
        return
    drop_index(connection)
    with connection.cursor() as cursor:
        cursor.execute('CREATE VIEW product_fts_content AS SELECT rowid, id AS product_id, search_text FROM shopping_product')
        # Only AND/prefix token searches are used: positions and token counts are unnecessary.
        cursor.execute('''CREATE VIRTUAL TABLE product_fts USING fts5(
            product_id UNINDEXED, search_text, content='product_fts_content',
            content_rowid='rowid', tokenize='unicode61', detail=none, columnsize=0)''')
        cursor.execute("INSERT INTO product_fts(product_fts) VALUES('rebuild')")
        cursor.execute('''CREATE TRIGGER product_fts_insert AFTER INSERT ON shopping_product BEGIN
            INSERT INTO product_fts(rowid,product_id,search_text) VALUES(new.rowid,new.id,new.search_text);
        END''')
        cursor.execute('''CREATE TRIGGER product_fts_delete AFTER DELETE ON shopping_product BEGIN
            INSERT INTO product_fts(product_fts,rowid,product_id,search_text) VALUES('delete',old.rowid,old.id,old.search_text);
        END''')
        cursor.execute('''CREATE TRIGGER product_fts_update AFTER UPDATE OF id,search_text ON shopping_product BEGIN
            INSERT INTO product_fts(product_fts,rowid,product_id,search_text) VALUES('delete',old.rowid,old.id,old.search_text);
            INSERT INTO product_fts(rowid,product_id,search_text) VALUES(new.rowid,new.id,new.search_text);
        END''')
        cursor.execute("INSERT INTO product_fts(product_fts) VALUES('optimize')")
