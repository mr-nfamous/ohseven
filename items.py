
import itertools
import json
import operator

from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import namedtuple
from types import MappingProxyType

import attr
import requests

from publicize import public, public_constants


if __name__ == '__main__':
    from config import CONFIG, PATH
    from search_engine import search_setup
    from utils import *
    from _errors import NonExistentItemError
else:
    from .config import CONFIG, PATH
    from .search_engine import search_setup
    from .utils import *
    from ._errors import NonExistentItemError
OSB_IGNORE     = ['8534', '8536', '8538', '8540', '8542', '8544', '8546',
                  '8630', '8632', '8634', '8636', '8638', '8640', '8642',
                  '8644', '8646', '8648']

@attr.s(hash=True)
class Item:
    id=attr.ib(hash=True)
    name=attr.ib(hash=True)
    desc=attr.ib()
    alch=attr.ib()
    membs=attr.ib()
    ge_cache_priority=attr.ib(default=0)

    def get_ge_info(self):
        return ge_lookup(self.id)[self.id]

    def get_osb_info(self):
        return osb_lookup(self.id)[self.id]
    
    def get_best_price(self):
        r = osb_lookup(self.id)[self.id]
        if r:
            if r.price:
                return r
        return ge_lookup(self.id)[self.id]

    @property
    def karamja(self):
        return self.alch * 14 // 2

    @property
    def low_alch(self):
        return self.alch * 2 // 3

    @property
    def store_price(self):
        return self.alch * 5//3    

    def __str__(self):
        return self.name

    def __int__(self):
        return self.id

isiteminstance=Item.__instancecheck__
@safe_repr
class ItemSet(frozenset):
    """Indexable frozenset subclass for holding sets of `Item` instances

    Can be cast to a dict with ItemSet.as_dict(key="id")

    Can be easily sorted by item attribute with ItemSet.sort_by or by
    using the prebuilt sort_by functions.
    
    As a frozenset subclass, the standard binary set operators
    (and their respective methods) work:
        & (intersection)
        | (union)
        - (difference)
        ^ (symmetric difference)
    
    The __contains__ will return True if any element in search(x) is
    in the set. For example:
       -> 6691 in search('sara brew')
          True
       -> "sgs" in search('godsword')
          True
    """
    __slots__ = ('__link',)

    def __new__(cls, *args, ichecker=itertools.repeat((int, str, Item))):
        items = []
        validtypes = map(isinstance, args, ichecker)
        for arg, check in zip(args, validtypes):
            if check:
                if isiteminstance(arg):
                    arg = arg
                else:
                    arg = (get if isintinstance(arg) else get_by_name)(arg)
            if not arg or not check:
                name = arg.__class__.__name__
                sname = cls.__name__
                error = TypeError(f'{sname}(*args) args must be int, str, '
                                  'or Item instances, not {name!r}')
                raise error
            items += [arg]
        self = frozenset.__new__(cls, items)
        self.__link = (*items,)
        return self
    
    @classmethod
    def _from_itemset(cls, args):
        self = frozenset.__new__(cls, args)
        self.__link = (*args,)
        return self
    
    def as_dict(self, key='id', dict=DotDict):
        """Map `self` to a mapping using `key` (any valid Item attr) as
        the dict's key"""
        keys = self.__link
        return dict(zip(map(operator.attrgetter(key), keys), keys))

    def ge_info(self):
        """Map `self` to a dict of Item: ge_price pairs."""
        keys = self.__link
        vals = ge_lookup(*keys)
        return DotDict(zip(keys, [vals[i] for i in map(int, keys)]))
    
    def osb_info(self):
        """Map `self` to a dict of Item: osb_price pairs."""
        keys = self.__link
        vals = osb_lookup(*self)
        return DotDict(zip(keys, [vals[i] for i in map(int, keys)]))

    def _get_info(self, key):
        keys = self.__link
        vals = map(operator.attrgetter(key), keys)
        return DotDict(zip(keys, vals))

    def alch_info(self):
        """Map `self` to a dict of Item: alch pairs."""
        return self._get_info('alch')

    def low_alch_info(self):
        """Map `self` to a dict of Item: alch pairs."""
        return self._get_info('low_alch')

    def karamaja_info(self):
        """Map `self` to a dict of Item: karamja price pairs."""
        return self._get_info('karamja')

    def store_price_info(self):
        """Map `self` to a dict of Item: store_price pairs."""
        return self._get_info('store_price')

    def membs_info(self):
        """Map `self` to a dict of Item: membs pairs."""
        return self._get_info('membs')

    def desc_info(self):
        """Map `self` to a dict of Item: desc pairs."""
        return self._get_info('desc')
    
    def sorted_by(self, attribute, *, reverse=False):
        """Sort `self` according to each Item in `self`'s attributes"""
        link = self.__link
        if attribute == 'ge_price':
            prices = ge_lookup(*link)
            prices = {i:prices[i.id].price for i in link}
            keyfunc = prices.get
        elif attribute == 'osb_price':
            prices = osb_lookup(*link)
            prices = {i:prices[i.id].price for i in link}
            keyfunc = prices.get
        else:
            keyfunc = operator.attrgetter(attribute)
        return sorted(link, key=keyfunc, reverse=reverse)

    def index(self, elem):
        return self.__link.index(elem)

    def __contains__(self, elem, truth=operator.truth):
        r = search(elem)
        if r:
            return truth(super().__and__(r))
        return False
    
    def __iter__(self):
        return iter(self.__link)
    
    def __getitem__(self, index):
        return self.__link[index]
    
    def __or__(self, other):
        return self._from_itemset(super().__or__(other))

    def __xor__(self, other):
        return self._from_itemset(super().__xor__(other))

    def __sub__(self, other):
        return self._from_itemset(super().__sub__(other))

    def __and__(self, other):
        return self._from_itemset(super().__and__(other))

    __ror__ = union = __or__
    __rxor__ = symmetric_difference = __xor__
    __rsub__ = difference = __sub__
    __rand__ = intersection = __and__    

class _PriceInfo:
    def __init_subclass__(cls, *args, **kwargs):
        cls.__doc__ = f'{cls.__name__}({", ".join(cls._fields)})'

    @property
    def delta(self):
        return time_in_seconds() - self.time
    
class ge_info(_PriceInfo, namedtuple('info',('id', 'price', 'time'))):

    pass

class osb_info(_PriceInfo, namedtuple('info',('id', 'price', 'time'))):
    
    def as_dict(self):
        return {'price':self.price, 'time':self.time}

class _Interface:
    
    __instances = {}

    def __init_subclass__(cls, *, cache, info_class=None,
                          cache_file_key=None, price_lookup_url_key=None):
        name = __class__.__name__
        error = None
        if info_class is None:
            error = TypeError(f'{name} subclass requires `info_class` argument.')
        elif not isdictinstance(cache):
            error = TypeError(f'{name} subclass `cache` should be a dict instance.')
        elif cache_file_key not in CONFIG.filenames:
            error = ValueError(f'{name} subclass: bad FILENAME key in `cache_file`.')
        elif price_lookup_url_key not in CONFIG.item_data_urls:
            error = ValueError(f'{name} subclass: bad URL key in `price_lookup_url`.')        
        if error:
            raise error
        cls._cache_file_key = cache_file_key
        cls._price_url_key = price_lookup_url_key
        cls._info_class = info_class
        cls.cache = cache

    def __new__(cls, *args, **kwargs):
        if __class__.__instances.get(cls) is None:
            instance = __class__.__instances[cls] = object.__new__(cls)
            instance.cache.clear()
            instance.last_check = 0
            instance.last_update = 0
            instance._thread = None
            instance._exceptions = {}
            instance.requests = {}
            return instance
        return __class__.__instances[cls]
    
    def auto_cache(self):
        if self._is_autocaching:
            return True
        self._thread = threading.Thread(target=self._auto_cache)
        self._thread.start()

    def _get_most_recent_requests(self, t):
        t = time_in_seconds() - t
        return {k:v for k, v in self.requests.items() if k >= t}

    @property
    def _is_autocaching(self):
        return False if not self._thread else self._thread.is_alive()
    
    @property
    def cache_file(self):
        return PATH/CONFIG.filenames[self._cache_file_key]

    @property
    def price_url(self):
        return CONFIG.item_data_urls[self._price_url_key]

    def lookup_from_cache(self, *ids):
        ids = [*map(int, {*ids})]
        return {i:v for i, v in zip(ids, map(self.cache.get, ids))}
    
    def lookup(self, *ids):
        results = {}
        cached_results = {}
        ids = {*map(int, ids)}
        check = time_in_seconds()
        if check - self.last_check < 300:
            cached_results = self.lookup_from_cache(*ids)
            cached_results = {k:v for k, v in cached_results.items()
                              if v is not None}
        ids -= cached_results.keys()
        if not ids:
            return cached_results
        if len(ids) > 100:
            error = Exception('cannot look up more than 100 items at a time.')
            raise error
        exceptions = {}
        info = self._info_class
        with ThreadPoolExecutor(len(ids)) as executrix:
            futures = map(executrix.submit, itertools.repeat(self._lookup), ids)
            for future in as_completed(futures):
                id, result = future.result()
                if isexceptioninstance(result):
                    exceptions[id] = result
                else:
                    results[id] = info(**result)
        for i, v in results.items():
            if v.time > self.last_update:
                self.cache.clear()
                self.last_update = v.time
                cached_results = self.lookup(*cached_results)
                break
        for i, v in results.items():
            self.cache[i] = v
        self.last_check = check        
        return DotDict(**cached_results, **results, **exceptions)

class OSBInterface(_Interface,
                   cache=DotDict(),
                   info_class=osb_info,
                   cache_file_key='osb_cache',
                   price_lookup_url_key='osb_price_api'):

    @property
    def price_catalogue_url(self):
        return CONFIG.item_data_urls.osb_catalogue
    
    def lookup(self, *ids):
        ids = {*map(int, ids)}
        info = self._info_class
        cache = self.cache
        cache_get = cache.get
        check = time_in_seconds()
        results = {}
        oldest = check - CONFIG.cache_settings.osb_cache_duration
        if check - self.last_check < 300:
            cached_result = {}
            for id in ids:
                cached = cache_get(id)
                if cached:
                    if cached.time >= oldest:
                        cached_result[id] = cached
                        continue
                    else:
                        break
                cached_result[id] = info(id=id, price=0, time=self.last_check)
            else:
                return cached_result        
        response = requests.get(self.price_catalogue_url)
        data = {k:v for k, v in response.json().items() if k not in OSB_IGNORE}        
        for k, v in data.items():
            id = int(k)
            price = v['overall_average']
            result = info(id=id, price=price, time=check)
            if price:
                cache[id] = result
            else:
                cached = cache_get(id)
                if cached:
                    result = cached
            if id in ids:
                results[id] = result
        self.last_check = check
        return results
    
    def _lookup_individual(self, id):
        
        check = time_in_seconds()
        try:
            if not get(id):
                raise NonExistentItemError('id', id)
            self.requests.setdefault(check, 0)
            self.requests[check] += 1
            cached_result = self.cache.get(id)
            if cached_result is not None:
                if cached_result.delta < CACHE_SETTINGS.osb_cache_duration:
                    return cached_result
            for i in range(5):
                response = requests.get(self.price_url%id, timeout=.5)
                if response.ok:
                    text = response.text
                    if text:
                        j = DotDict(response.json())
                        break
                time.sleep(.05)
            else:
                j = DotDict(response.json())    
            price = j.overall or j.selling or j.buying
            if price:
                result = dict(
                    id=id,
                    price=price,
                    time=check,
                    sell_volume=j['sellingQuantity'],
                    buy_volume=j['buyingQuantity'])
            elif cached_result:
                result = cached_result
            else:
                result = dict(id=id,price=0,time=check,sell_volume=0,
                                          buy_volume=0)
            return id, result
        except Exception as error:
            return id, error

    def dump_cache(self, path_override=None, backup_path=None):
        if path_override:
            path = pathlib.Path(path_override)
        else:
            path = self.cache_file
        if backup_path:
            backup_file(path, pathlib.Path(backup_path))
        c = {k:v.as_dict() for k, v in self.cache.items()}
        with open(path, 'w') as fp:
            json.dump(c, fp, indent=1)

    def load_cache(self, path_override=None):
        if path_override:
            path = pathlib.Path(path_override)
        else:
            path = self.cache_file
        with open(path) as fp:
            c = json.load(fp)
        self.cache.update({k:self._info_class(id=k, **v) for k, v in c.items()})

    def _auto_cache(self):
        while True:
            self.lookup()
            time.sleep(CONFIG.cache_settings.osb_auto_cache_frequency)
            
class GeInterface(_Interface,
                  cache=DotDict(),
                  info_class=ge_info,
                  cache_file_key='ge_cache',
                  price_lookup_url_key='ge_price_api'):       

        
    def dump_cache(self, path_override=None, backup_path=None):
        if path_override:
            path = pathlib.Path(path_override)
        else:
            path = self.cache_file
        if backup_path:
            backup_file(path, pathlib.Path(backup_path))
        c = {k:v.price for k, v in self.cache.items()}
        with open(path, 'w') as fp:
            fp.write(f'{self.last_update}\n{json.dumps(c, indent=1)}')

    def load_cache(self, path_override=None):
        if path_override:
            path = pathlib.Path(path_override)
        else:
            path = self.cache_file
        with open(path) as fp:
            last_update, b, c = fp.read().partition('\n')
        last_update = int(last_update)
        if last_update < self.last_update:
            error = Exception('cache file is out of date')
            warnings.warn(error)
        self.last_update = last_update
        c = {int(i):v for i, v in json.loads(c).items()}
        info = self._info_class
        self.cache.update({i:info(**{'id':i, 'price':v, 'time':last_update})
                           for i, v in c.items()})
        
    def _lookup(self, id):
        check = time_in_seconds()
        if id in self.cache and check - self.last_check < 300:
            return self.cache[id]
        try:
            self.requests.setdefault(check, 0)
            self.requests[check] += 1
            response = requests.get(self.price_url%id, timeout=2)
            results = response.json()['daily']
            key = max(results)
        except Exception as error:
            return id, error
        self.last_check = check
        return id, {'id':id, 'price':results[key], 'time':int(key)//1000}

    def _auto_cache(self):
        sorter = operator.attrgetter('ge_cache_priority')
        freq = 86400 / CONFIG.cache_settings.ge_auto_cache_frequency
        if freq < 6.5:
            error = ValueError("ge_auto_cache_frequency cannot be greater "
                               "than 13_000 items per day "
                               "(aka > ~90 lookups per 10 minutes) "
                               "without triggering Jagex's ddos protection.")
            raise error
        while True:
            update_reqs = self._get_most_recent_requests
            cache = self.cache
            self.requests = update_reqs(600)
            past_10 = sum(self.requests.values())
            n = min(20, max(0, 50-past_10))
            if n:
                pool = sorted(list_items(), key=sorter, reverse=True)
                pool = (i for i in sorted(list_items(), key=sorter, reverse=1)
                        if i.id not in cache)
                result = self.lookup(*itertools.islice(pool, n))
                errors = {k:v for k, v in result.items()
                          if isinstance(v, Exception)}
                if errors:
                    self._exceptions[time_in_seconds()] = errors
            sleep_time = freq * (n + max(past_10-20, 0))
            time.sleep(sleep_time)            

def load(__items=DotDict()):
    global get, _search, _items, _by_name
    __items.clear()
    _items = MappingProxyType(__items)
    get = _items.get
    with open(PATH/CONFIG.filenames.item_data) as fp:
        for line in json.load(fp):
            __items[line['id']] = Item(**line)
    _search = search_setup(map(name_getter, _items.values()),
                           *get_search_setup(),
                           result_cls=ItemSet)
    _by_name = DotDict({i.name.lower(): i for i in _items.values()})
    
def get_search_setup():
    'abbv, ngrams, slang'
    with open(PATH/CONFIG.filenames.abbreviations) as fp:
        abbv = json.load(fp)
    with open(PATH/CONFIG.filenames.ngrams) as fp:
        ngrams = json.load(fp)
    with open(PATH/CONFIG.filenames.slang) as fp:
        slang = json.load(fp)
    return abbv, ngrams, slang


def view_items():
    return ItemSet._from_itemset(_items.values())

def list_items():
    return List(_items.values())

def iter_items():
    return iter( _items.values())

def save_itemdb(path_override=None, backup=None):
    '''Save current state of item database to disk.

    If `path_override` is provided, the database is dumped there
    instead of the usual file located in CONFIG.filenames.item_data.

    If `backup` is provided, a copy of the previous database is
    moved there (assuming it exists).
    '''
    if path_override:
        path = pathlib.Path(path_override)
    else:
        path = PATH/CONFIG.filenames.item_data
    items = map(operator.methodcaller('_dump'), iter_items())
    text = json.dumps([*items], indent=2)
    json.loads(text)
    if backup:
        backup_file(path, pathlib.Path(backup))
        backup = pathlib.Path(backup)
    with open(path, 'w') as fp:
        fp.write(text)

def update_itemdb():
    '''Check for new items added to the game and add them to the DB'''
    response = requests.get(CONFIG.item_data_urls['osb_catalogue'])
    data = response.json()
    data = {int(k):v for k, v in data.items() if k not in OSB_IGNORE}
    missing = [i for i in data if not get(i)]
    new = {k:{'id':k,
              'name':v['name'],
              'alch':v['sp']*2//3,
              'membs':v['members']} for k, v in data.items()
           if k in missing}
    
    def desc_getter(id):
        try:
            response = requests.get(CONFIG.item_data_urls['ge_catalogue']%id)
            j = response.json()
            desc = j['item']['description']
            return id, desc
        except:
            return None, None
    while missing:
        chunk = missing[:30]
        with ThreadPoolExecutor(len(chunk)) as executor:
            futures = map(executor.submit, itertools.repeat(desc_getter), chunk)
            for future in as_completed(futures):
                itemid, desc = future.result()
                if isinstance(desc, str):
                    new[itemid]['desc'] = desc
                    missing.remove(itemid)
    for k, v in new.items():
        if k in _items:
            raise ValueError('there already is an item with id {id}')
        _items[k] = Item(**v)
        
def get_by_name(name, default=None):
    return _by_name.get(' '.join(name.lower().split()), default)

def search(*params):
    '''Search the item database

    Parameters can be integers representing item id number or strings.
    Acceptable strings include direct matches, common abbreviations
    such as "ags" for Armadyl godsword, even common misspellings
    are correctly resolved. "blk ele" for example will find
    "Black elegant shirt" and "Black elegant legs" and "rune ore"
    will match "Runite ore".
    '''
    result = ItemSet()
    from_ids = []
    for param in params:
        if isintinstance(param):
            item = get(param)
            if item is None:
                error = ValueError(f'{param} is not a valid item id.')
                raise error
            from_ids += [item]
        elif isstrinstance(param):
            if not param:
                raise ValueError('cannot search for empty string')
            items = _search(param)
            if items:
                result |= items
        else:
            error = TypeError('search parameters must be ints or strs.')
            raise error
    return result | ItemSet(*from_ids)

load()
cls=GeInterface
ge = cls()
osb=OSBInterface()
ge_lookup = GeInterface().lookup
osb_lookup = OSBInterface().lookup
if CONFIG.general_settings.load_osb_cache_on_import:
    osb.load_cache()
if CONFIG.general_settings.load_ge_cache_on_import:
    ge.load_cache()
    
