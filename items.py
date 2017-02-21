import os
import json
import time
import zlib
import pickle
import threading
import functools
import configparser
import concurrent.futures

import requests

from oh7 import exceptions
from oh7 import search_engine

DATA_DIRECTORY = '.ohseven.data'
URLS           = ('osb_price_api', 'ge_price_api', 'ge_catalogue')
FILES          = ('item_data', 'abbreviations', 'slang', 'metaitems')
ITEM_SETTINGS  = ('max_osb_price_age', 'max_ge_price_age')
OSB_IGNORE     = [8534, 8536, 8538, 8540, 8542, 8544, 8546, 8630, 8632,
                  8634, 8636, 8638, 8640, 8642, 8644, 8646, 8648]

DEBUG = 0

def _delta(then):
    """Time since `then`"""
    return time.time() - then

def get_data_directory():
    path = os.path.expanduser('~')
    path = os.path.join(path, DATA_DIRECTORY)
    if not os.path.exists(path):
        os.mkdir(path)
    return path

def get_filename(filename):
    path = f'{get_data_directory()}\\{filename}'
    if not os.path.exists(path):
        with open(path, 'w') as file:
            pass
    return path

class _ItemDataIO:
    """File i/o to prevent seperate threads opening the same file"""
    busy = False

    @classmethod
    def load(cls, filename, mode):
        if cls.busy:
            raise OSError
        cls.busy = True
        with open(get_filename(filename), mode) as file:
            data = file.read()
        cls.busy = False
        return data

    @classmethod
    def save(cls, filename, data, mode):
        if cls.busy:
            raise OSError
        cls.busy = True
        with open(get_filename(filename), mode) as file:
            file.write(data)
        cls.busy = False

CONFIG = configparser.ConfigParser()
with open(get_filename('config.ini')) as file:
    CONFIG.read_file(file)
for setting in URLS:
    assert CONFIG['urls'][setting]
for setting in FILES :
    assert CONFIG['filenames'][setting]
for setting in ITEM_SETTINGS:
    assert CONFIG['item_settings'][setting]

class ItemProperty:

    def __init__(self, *, default=None, read_only=True, dumpable=True):
        self.read_only = read_only
        self.default   = default
        self.dumpable  = dumpable

    def __set_name__(self, cls, name):
        self.name = name
        cls._set_properties = ()
        if name in cls.__annotations__ and callable(cls.__annotations__[name]):
            self.setter = cls.__annotations__[name]
        else:
            self.setter = None

    def __get__(self, instance, cls):
        if DEBUG: print('ItemProperty.__get__')
        return self if instance is None else instance.__dict__[self.name]

    def __set__(self, instance, value):
        if DEBUG: print('ItemProperty.__set__')
        if self.name not in instance._set_properties or not self.read_only:
            if self.setter is not None:
                value = self.setter(value)
            instance.__dict__[self.name] = value
        else:
            raise ItemPropertyIsReadOnlyError(attr=self.name)
        if self.name not in instance._set_properties:
            instance._set_properties = (*instance._set_properties, self.name)

class ItemMeta(type):
    def __new__(metacls, cls, bases, dict):
        self = super().__new__(metacls, cls, bases, dict)
        props = [v for k,v in dict.items() if isinstance(v, ItemProperty)]
        self._all_properties        = [p.name for p in props]
        self._mutable_properties    = [p.name for p in props if not p.read_only]
        self._immutable_properties  = [p.name for p in props if p.read_only]
        self._dumpable_properties   = [p.name for p in props if p.dumpable]
        return self

class Item(metaclass=ItemMeta):
    """An Oldschool runescape item

"""
    id: int                = ItemProperty(dumpable=False)
    name: str              = ItemProperty()
    alch: int              = ItemProperty()
    membs: bool            = ItemProperty()
    desc: str              = ItemProperty()
    osb_price: int         = ItemProperty(default=0, read_only=False)
    ge_price: int          = ItemProperty(default=0, read_only=False)
    last_osb_update        = ItemProperty(default=None, read_only=False)
    last_ge_update         = ItemProperty(default=None, read_only=False)
    ge_cache_priority: int = ItemProperty(default=0, read_only=False)

    def __init__(self, id, name, alch, membs, desc, **kws):
        for prop in self._all_properties:
            self.__dict__[prop] = type(self).__dict__[prop].default
        self.id    = id
        self.name  = name
        self.alch  = alch
        self.membs = membs
        self.desc  = desc
        for k in kws:
            setattr(self, k, kws[k])

    def _dump(self):
        """Convert Item instance into a dictionary ready for pickling"""

        return {k:getattr(self,k) for k in self._dumpable_properties}

    @property
    def karamja(self):
        return self.alch * 14 // 12

    @property
    def low_alch(self):
        return self.alch * 2 // 3

    @property
    def store_price(self):
        return self.alch * 5 // 3

    def get_best_price(self,
                       osb_expiration=None,
                       ge_expiration=None):
        """Return the OSB price if it is cached, else the GE price

        If expirations are given, it will ignore price data if it is older
        than the expiration value in seconds."""
        if self.osb_price:
            delta = _delta(self.last_osb_update)
            if osb_expiration is None or delta < osb_expiration:
                return self.osb_price
        elif self.ge_price:
            delta = _delta(self.last_ge_update)
            if ge_expiration is None or delta < ge_expiration:
                return self.ge_price
        else:
            return None

    @property
    def price_discrepancy(self):
        if self.osb_price and self.ge_price:
            a, b = self.osb_price, self.ge_price
            a, b = max(a, b), min(a, b)
            return (a-b)/b

    def get_ge_price(self):
        self.ge_price, self.last_ge_update = (*ge_lookup(self.id).items(),)[0]
        return self.ge_price

    def __str__(self):
        return self.name

    def __int__(self):
        return self.id

    def __hash__(self):
        return hash((self.__class__, self.id, self.name))

    def __eq__(self, other):
        return self.__hash__() == getattr(other, '__hash__', None)

    def __repr__(self):
        args = ', '.join(f'{p}={getattr(self,p)!r}'
                         for p in self._immutable_properties)
        return f'{type(self).__name__}({args})'

    def __setattr__(self, attr, value):
        # allow sunder attributes or ItemProperties only
        if attr.startswith('_') or attr in self._all_properties:
            super().__setattr__(attr, value)
        else:
            raise exceptions.ItemPropertyIsReadOnlyError(attr=attr)

    def restore_defaults(self, prop, *properties, all_props=False):
        """Restore an item's default values"""
        
        if all_props:
            properties = self._all_properties
        else:
            properties = (prop, *properties)
        assert all(prop in self._mutable_properties for prop in properties)
        for prop in properties:
            setattr(self, prop, getattr(type(self), prop).default)

class ItemsMeta(type):
    def __new__(metacls, cls, bases, namespace):
        if bases:
            raise TypeError('cannot subclass Items')
        self = super().__new__(metacls, cls, bases, namespace)
        self.reload()
        return self

    def load_item_data(self):
        """Load item data from disk"""

        data = _ItemDataIO.load(CONFIG['filenames']['item_data'], 'rb')
        data = zlib.decompress(data)
        data = pickle.loads(data)
        self._hash_map = {}
        self._data = {}
        for item in (Item(k, **data[k]) for k in data):
            hashval = hash(item)
            self._hash_map[hash(item.id)] = hashval
            self._hash_map[hash(item.name)] = hashval
            self._data[hashval] = item

    def dump_item_data(self, data=None):
        """Save the current state to disk"""

        if data is None:
            data = {i.id:i._dump() for i in self}
        data = pickle.dumps(data)
        data = zlib.compress(data)
        _ItemDataIO.save(CONFIG['filenames']['item_data'], data, 'wb')

    def load_search_func(self):
        """Reload the item search function

       Must be reloaded each time a new item is added"""
        abbv_data  = _ItemDataIO.load(CONFIG['filenames']['abbreviations'], 'r')
        slang_data = _ItemDataIO.load(CONFIG['filenames']['slang'], 'r')
        meta_data  = _ItemDataIO.load(CONFIG['filenames']['metaitems'], 'r')
        return search_engine.setup(
            map(str, self),
            json.loads(abbv_data),
            json.loads(meta_data),
            json.loads(slang_data))

    def restore_defaults(self, *properties, all_props=False):
        """Reset default item properties for all Items"""

        if all_props:
            properties = Item._all_properties
        assert all(prop in Item._mutable_properties for prop in properties)
        for item in self:
            item.restore_defaults(*properties)

    def _cache_loop(self, loop):
        for iteration in loop:
            time.sleep(iteration)

    def _clear_ge_cache(self, ignore_age_settings=False):
        """Clear the ge cache. Does not clear the lru_cache of _ge_lookup.

        If `ignore_age_settings` is True, will remove all ge price info
        regardless of age"""

        if not ignore_age_settings:
            for item in self:
                if _delta(item.last_ge_update) > int(
                    CONFIG['item_settings']['max_ge_price_age']):
                    item.restore_defaults('ge_price', 'last_ge_update')
        else:
            self.restore_defaults('ge_price', 'last_ge_update')
        self.ge_cache = set(i.id for i in self if i.ge_price)

    def _clear_osb_cache(self, ignore_age_settings=False):
        """Clear the osb cache. 

        If `ignore_age_settings` is True, will remove all osb price info
        regardless of age"""

        if not ignore_age_settings:
            for item in self:
                if item.last_osb_update is not None:
                    if _delta(item.last_osb_update) > int(
                        CONFIG['item_settings']['max_osb_price_age']):
                        item.restore_defaults('osb_price', 'last_osb_update')
        else:
            self.restore_defaults('osb_price', 'last_osb_update')
        self.osb_cache = set(i.id for i in self if i.osb_price)

    def _ge_loop(self):
        """Grand Exchange price caching loop.

    """
        self._last_ge_cache_update = 0
        self._last_ge_update = ge_lookup(1965)[1965]['time']
        self._clear_ge_cache()
        def get_next_batch():
            order = sorted(self, key=lambda x: x.ge_cache_priority,reverse=True)
            primary   = [i.id for i in order if
                         not i.osb_price and not i.ge_price]
            secondary = [i.id for i in order if not i.ge_price]
            return (primary + secondary)[:self._ge_cache_batch_size]

        while True:
            batch = get_next_batch()
            if batch:
                prices = ge_lookup(*batch)
                for itemid, data in prices.items():
                    if data['time'] != self._last_ge_update:
                        self._last_ge_update = data['time']
                        self._clear_ge_cache()
                        _ge_lookup.last_clear = time.time()
                        _ge_lookup.cache_clear()
                        break
                    self[itemid].ge_price = data['price']
                    self[itemid].last_ge_update = data['time']
                    self.ge_cache.add(itemid)
                self._last_ge_cache_update = time.time()
            for i in range(max(1, len(batch))):
                yield self._ge_update_delay

    def _osb_loop(self):
        """Osb price caching loop

    """
        self._clear_osb_cache()
        self._last_osb_cache_update = 0
        while True:
            if _delta(self._last_osb_cache_update) > self._osb_update_delay:
                prices = osb_lookup()
                new_items = [i for i in prices if i not in self]
                if new_items:
                    items = self.download_new_items(new_items)
                    self.dump_item_data(items)
                    self.reload()
                self._last_osb_cache_update = int(time.time())
                for itemid, price in prices.items():
                    if price:
                        self[itemid].osb_price = price
                        self[itemid].last_osb_update = (
                            self._last_osb_cache_update)
                        self.osb_cache.add(itemid)
                    else:
                        self[itemid].ge_cache_priority += 1
                        if self[itemid].last_osb_update:
                            delta = (self._last_osb_cache_update -
                                     self[itemid].last_osb_update)
                            if delta > self._osb_price_expiration:
                                self[itemid].restore_default('osb_price',
                                                             'last_osb_update')
            yield self._osb_update_delay

    def download_new_items(self, items):
        if not items or not all(isinstance(i, int) for i in items):
            raise ValueError('items must be a list of itemids')
        if len(items) > 30:
            raise ValueError('cannot download more than 30 new items at once')
        dumped = {i.id:i._dump() for i in self}
        dupes = [i for i in items if i in dumped]
        if dupes:
            raise ValueError(f'items {", ".join(dupes)} already exist')
        data = osb_lookup('sp', 'members', 'name')
        data = {k:{'name':data[k]['name'],
                   'alch':data[k]['sp'] * 3//5,
                   'membs':data[k]['members']} for k in items}
        def description_getter(itemid):
            nonlocal data
            response = _request(CONFIG['urls']['ge_catalogue']%itemid).json()
            data[itemid] = {**data[itemid],
                                            **{'desc':response['item']['description']}}
        with concurrent.futures.ThreadPoolExecutor(len(items)) as executor:
            futures = {executor.submit(description_getter, i):i for i in items}
            concurrent.futures.wait(futures)
        return {**dumped, **data}


    def _delete(self, item):
        if not isinstance(item, Item):
            raise TypeError('item must be Item instance')
        del self._hash_map[hash(item.id)]
        del self._hash_map[hash(item.name)]
        del self._data[hash(item)]

    def __contains__(self, key):
        return hash(key) in self._hash_map

    def __iter__(self):
        return iter(self._data.values())

    def __len__(self):
        return len(self._data)

    def __getitem__(self, key):
        try:
            return self._data[self._hash_map[hash(key)]]
        except:
            raise KeyError(key) from None

class Items(metaclass=ItemsMeta):

    @classmethod
    def reload(cls):
        cls.load_item_data()
        cls._search = cls.load_search_func()

    @classmethod
    def save(cls):
        cls.dump_item_data()

    @classmethod
    def search(cls, query):
        r = cls._search(query)
        if r:
            return [cls[i.lower().capitalize()] for i in r]

    @classmethod
    def start_ge_cache(cls, batch_size=5, update_delay=7.5):
        if hasattr(cls, '_ge_thread') and cls._ge_thread.is_alive():
            raise ValueError('ge thread is already running')
        cls._ge_cache_batch_size=batch_size
        cls._ge_update_delay = update_delay
        cls._ge_thread = threading.Thread(
            target=cls._cache_loop, args=(cls._ge_loop(),))
        cls._ge_thread.start()

    @classmethod
    def start_osb_cache(cls, update_delay=2000, expiration=86400):
        if hasattr(cls, '_osb_thread') and cls._osb_thread.is_alive():
            raise ValueError('osb thread is already running')
        cls._osb_update_delay = update_delay
        cls._osb_price_expiration = expiration
        cls._osb_thread = threading.Thread(
            target=cls._cache_loop, args=(cls._osb_loop(),))
        cls._osb_thread.start()

_ge_request_attempts = 0
_ge_request_successes= 0
def ge_req_success():
    return _ge_request_attempts / max(1, _ge_request_successes)

def _request(url, timeout=2, max_tries=3):
    """Wrapper for request.get to handle occasional repeated timeouts"""
    counter = 0
    while counter < max_tries:
        try:
            data = requests.get(url, timeout=timeout)
            return data
        except:
            counter += 1
            time.sleep(1)
    raise requests.ConnectionError(url)

@functools.lru_cache(maxsize=len(Items))
def _ge_lookup(i, key=None):
    """All ge price lookups go through here in order to use the lru_cache.

     The cache should be cleared once a day, (and it is cleared automagically
     while the caching thread is alive)
  """

    global _ge_request_attempts, _ge_request_successes
    _ge_request_attempts += 1
    response = _request(CONFIG['urls']['ge_price_api']%i)
    results  = response.json()['daily']
    results  = {int(k)//1000:v for k,v in results.items()}
    key      = max(results.keys()) if key is None else key
    _ge_request_successes += 1
    return {i: {'price':results[key], 'time':key}}
_ge_lookup.last_clear = time.time()

def ge_lookup(*items, key=None):
    """Lookup some items on the Grand Exchange api

     The GE api begins to throttle requests once your average reaches > 100 per
     10 minutes. A burst of 100 will go through instantly, but any more than that
     will be severely throttled until requests per 10 mins drops below 6.
"""
    results = {}
    if len(items) == 1 and isinstance(items[0], (list, tuple)):
        items = items[0]
    items = [int(item) for item in items]
    if not items:
        raise ValueError('no items supplied')
    with concurrent.futures.ThreadPoolExecutor(len(items)) as executor:
        futures = {executor.submit(_ge_lookup, i, **{'key':key}): i for i in items}
        for future in concurrent.futures.as_completed(futures):
            try:
                results = {**results, **future.result()}
            except:
                print(f'failed to get ge price data for items {items}')

    return results

def osb_lookup(*values):
    """Download all data from the OsBuddy exchange

    `values` are specific fields. If blank it only returns the price.
    Valid `values` are:
     * `id`
     * `name`
     * `sp` - item's general store price which is 5//3 * its high alch
     * `overall_average - overall buying/selling price. this is what's used
                          automatically
     * `sell_average`
     * `members` - item is member's only
     """
    keys = ('overall_average',) if not values else values
    data = _request(CONFIG['urls']['osb_price_api'])
    data = data.json()
    data = {int(i):data[i] for i in data if int(i) not in OSB_IGNORE}
    if len(keys)==1:
        data = {i:data[i][keys[0]] for i in data}
    else:
        data = {i:{k:data[i][k] for k in keys} for i in data}
    return data

def get_price_discrepancies(min_pct=0):
    """List the price GE/OSB price discrepancies.

     `min_pct` is the threshold. Items with a discrepancy lower than that
     will not be returned
     """

    diffs = {i.id: i.price_discrepancy for i in Items}
    return {k:v for k, v in diffs.items() if v is not None and v > min_pct}

def get_alchlosses(*items, force_osb=True):
    if items:
        if not all(isinstance(item, Item) for item in items):
            raise TypeError('items must be a list of Item objects')
    else:
        items = iter(Items)
    if force_osb:
        items = (item for items in items if item.osb_price)
    else:
        items = (item for item in items if item.get_best_price())
    fn = lambda item: item.osb_price if force_osb else item.get_best_price()
    nature = Items['Nature rune']
    nat_price = fn(nature)
    r = {item.id: item.alch-fn(item)-nat_price for item in items}
    return r


