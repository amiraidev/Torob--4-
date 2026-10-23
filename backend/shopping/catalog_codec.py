"""Versioned, lossless document codec shared by Django and catalog packaging."""
import json
import zlib

MAGIC = b'TYJ1'


def encode_json(value):
    if value is None:
        return None
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    compressed = zlib.compress(raw, level=6) if len(raw) >= 192 else raw
    return MAGIC + (b'z' + compressed if len(compressed) < len(raw) else b'j' + raw)


def decode_json(value):
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    raw = bytes(value)
    if raw.startswith(MAGIC):
        encoding, raw = raw[4:5], raw[5:]
        if encoding == b'z':
            raw = zlib.decompress(raw)
        elif encoding != b'j':
            raise ValueError('Unsupported catalog JSON encoding')
    return json.loads(raw.decode('utf-8'))
