"""Lossless JSON storage; Django and the API still see ordinary Python values."""
from django import forms
from django.core.exceptions import ValidationError
from django.db import models
from .catalog_codec import encode_json, decode_json


class CompactJSONField(models.Field):
    """Opaque JSON document, compressed on disk; no SQL JSON-key lookups.

    Searchable values remain in ordinary indexed columns. Unlike an application
    cache, this encoding retains every JSON value and is used for future writes.
    """
    description = 'Losslessly compressed JSON'

    def get_internal_type(self):
        return 'BinaryField'

    def get_db_prep_value(self, value, connection, prepared=False):
        encoded = encode_json(value)
        return connection.Database.Binary(encoded) if encoded is not None else None

    def from_db_value(self, value, expression, connection):
        return decode_json(value)

    def to_python(self, value):
        if isinstance(value, (bytes, bytearray, memoryview)):
            return decode_json(value)
        return value

    def validate(self, value, model_instance):
        super().validate(value, model_instance)
        try:
            encode_json(value)
        except (ValueError, TypeError) as error:
            raise ValidationError('Enter valid JSON.', code='invalid') from error

    def formfield(self, **kwargs):
        return super().formfield(**{'form_class': forms.JSONField, **kwargs})

    def value_to_string(self, obj):
        return self.value_from_object(obj)
