"""Plugin pytest della suite del kit: MongoDB simulato con mongomock, per eseguire in locale i test generati delle
collection quando non c'è un server (la CI li esegue su MongoDB vero, con replica set).

  PYTHONPATH=tests/mongo PYTEST_ADDOPTS="-p fake_mongo" KYBES_TEST_MONGO_URL=mongodb://finto verify.py ...

Aggiunge a mongomock: sessioni con transazioni (copia e ripristino dei dati), confronti e ordinamenti di Decimal128.
Non fa parte dei progetti generati.
"""
import copy
import functools
from decimal import Decimal

import mongomock
import pymongo
from bson.decimal128 import Decimal128
from mongomock import filtering

_client_cls = mongomock.MongoClient


class FakeSession:
    def __init__(self, client):
        self.client = client

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def with_transaction(self, callback):
        store = self.client._store
        snapshot = {(d, c): copy.deepcopy(col._documents) for d, db in store._databases.items() for c, col in db._collections.items()}
        try:
            return callback(self)
        except BaseException:
            for (d, c), docs in snapshot.items():
                store._databases[d]._collections[c]._documents = docs
            for d, db in store._databases.items():
                for c, col in db._collections.items():
                    if (d, c) not in snapshot:
                        col._documents.clear()
            raise


class FakeClient(_client_cls):
    def __init__(self, *args, **kwargs):
        kwargs.pop("tz_aware", None)
        super().__init__(tz_aware=True)

    def start_session(self, *args, **kwargs):
        return FakeSession(self)


def _drop_session(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        kwargs.pop("session", None)
        return method(self, *args, **kwargs)
    return wrapper


for name in ("find", "find_one", "insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one",
             "delete_many", "count_documents", "find_one_and_update"):
    setattr(mongomock.collection.Collection, name, _drop_session(getattr(mongomock.collection.Collection, name)))

_plain = lambda v: v.to_decimal() if isinstance(v, Decimal128) else v  # noqa: E731
_compare = filtering.bson_compare
filtering.bson_compare = lambda op, a, b, can_compare_types=True: _compare(op, _plain(a), _plain(b), can_compare_types)
_type = filtering._get_compare_type
filtering._get_compare_type = lambda v: _type(_plain(v))
_sort_key = filtering.BsonComparable.__init__ if hasattr(filtering, "BsonComparable") else None
if _sort_key:
    def _init(self, obj):
        _sort_key(self, _plain(obj))
    filtering.BsonComparable.__init__ = _init

pymongo.MongoClient = FakeClient
mongomock.MongoClient = FakeClient
