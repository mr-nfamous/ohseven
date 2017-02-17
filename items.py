##"""Just about everything useful about Oldschool Runescape items.    
##
##"""
import pickle
import zlib
import os
import threading
import time
import json
import configparser
import warnings
import functools
import concurrent.futures
import requests

from oh7 import search_engine

__all__    = ['Items']
DATA_DIRECTORY = '.ohseven.data'

# These are items that still exist in the OSB exchange database even though
# Jagex removed them from the grand exchange years ago.
OSB_IGNORE = [8534, 8536, 8538, 8540, 8542, 8544, 8546, 8630, 8632,
              8634, 8636, 8638, 8640, 8642, 8644, 8646, 8648]

class _BaseException(Exception):
  def __init__(self, *args, **kwargs):
    super().__init__(self.msg.format(*args, **kwargs))
    
class FileAlreadyOpenError(_BaseException):
  msg = ''

class IllegalItemAttributeError(_BaseException):
  msg="{name} objects not allowed to set {attr}"

class ItemNotFoundError(_BaseException):
  msg = 'no item exists with {type} {key!r}'

class AttrIsReadOnlyError(_BaseException):
  msg = '{name}.{attr} is read-only'

class CouldntReadConfigWarning(Warning):
  def __init__(self, section):
    super().__init__(f"Couldn't load {section!r} from config file.")
    
class Data:
  _name          = __name__.encode()
  _busy          = False  
  @classmethod
  def add_missing_files(cls):
    files = [cls.item_data, cls.cache_priority, cls.abbreviations,
             cls.slang, cls.metaitems]
    *(cls.get_dir(file, make_dir=True, make_file=True) for file in files),
    
  @classmethod
  def get_dir(cls, filename, make_dir=False, make_file=False):
    user_dir = os.path.expanduser('~')
    user_dir = os.path.join(user_dir, DATA_DIRECTORY)
    if not os.path.exists(user_dir):
      if make_dir==True:
        cls.make_dir(user_dir)
      else:
        raise FileNotFoundError(path)
    user_dir = f'{user_dir}\\{filename}'
    if not os.path.exists(user_dir):
      if make_file:
        cls.make_file(user_dir)
      else:
        raise FileNotFoundError(filename)
    return user_dir

  @classmethod
  def make_dir(cls, path):
    if not os.path.exists(path):
      os.mkdir(path)
    else:
      raise OSError('directory already exists')
    
  @classmethod
  def make_file(cls, path):
    if not os.path.exists(path):
      with open(path, 'w') as file:
        pass
    else:
      raise OSError('file already exists')
    
  @classmethod
  def _load(cls, filename, mode):
    if cls._busy:
      raise FileAlreadyOpenError
    cls._busy = True
    filename  = cls.get_dir(filename)
    with open(filename, mode) as file:
      data = file.read()
    cls._busy = False
    return data

  @classmethod
  def _save(cls, filename, data, mode):
    filename = cls.get_dir(filename)
    if cls._busy:
      raise FileAlreadyOpenError
    cls._busy = True
    with open(filename, mode) as file:
      file.write(data)
    cls._busy = False

  @classmethod
  def load_items(cls, items_are_compressed=True):
    """Reload the (compressed) item list"""
    
    data = cls._load(cls.item_data, 'rb')
    if items_are_compressed:
      data = zlib.decompress(data)
    data = pickle.loads(data)
    return data

  @classmethod
  def dump_items(cls, items, compress=True):
    """Save the item list to disk"""
    
    assert all(isinstance(i, int) for i in items)
    assert all(isinstance(items[i], dict) for i in items)
    dumped = pickle.dumps(items)
    if compress:
      data = zlib.compress(dumped)
    cls._save(cls.item_data, data, 'wb')
    
  @classmethod
  def load_slang(cls):
    data = cls._load(cls.slang, 'r')
    return json.loads(data)

  @classmethod
  def load_abbreviations(cls):
    data = cls._load(cls.abbreviations, 'r')
    return json.loads(data)

  @classmethod
  def load_metaitems(cls):
    data = cls._load(cls.metaitems, 'r')
    return json.loads(data)
  
with open(Data.get_dir('config.ini', make_dir=True, make_file=True)) as file:
  config = configparser.ConfigParser()
  config.read_file(file)
  try:
    Data.osb_price_api  = config['urls']['osb_price_api']
    Data.ge_price_api   = config['urls']['ge_price_api']
    Data.ge_catalogue   = config['urls']['ge_catalogue']
  except configparser.InterpolationSyntaxError:
    m = ("string interpolations '%s' in config file must be escaped with "
         "another %,  ie '.../graph/%%s.json'")
    raise SyntaxError(m) from None  
  except:
    warnings.warn(CouldntReadConfigWarning('urls'))
    Data.osb_price_api  = 'https://rsbuddy.com/exchange/summary.json'
    Data.ge_price_api   = ('http://services.runescape.com/m=itemdb_oldschool'
                           '/api/graph/%s.json')
    Data.ge_catalogue   = ('http://services.runescape.com/m=itemdb_oldschool'
                           '/api/catalogue/detail.json?item=%s')
  try:
    Data.item_data      = config['filenames']['item_data']
    Data.abbreviations  = config['filenames']['abbreviations']
    Data.slang          = config['filenames']['slang']
    Data.metaitems      = config['filenames']['metaitems']
  except:
    warnings.warn(CouldntReadConfigWarning('filenames'))
    Data.item_data      = 'itemdb.zip'
    Data.abbreviations  = 'abbreviations.json'
    Data.slang          = 'slang.json'
    Data.metaitems      = 'metaitems.json'

  try:
    Data.max_osb_price_age = int(config['settings']['max_osb_price_age'])
  except:
    warnings.warn(CouldntReadConfigWarning('settings'))
    Data.max_osb_price_age = 86400
  Data._config = config
  del config

class ItemProperty:
  
  def __init__(self, *, default=None, read_only=True, dumpable=True):
    self.read_only = read_only
    self.default   = default
    self.dumpable  = dumpable
    
  def __set_name__(self, cls, name):
    self.name = name

  def __get__(self, instance, cls):
    try:
      if instance is None:
        return cls.__dict__[self.name]
      else:
        return instance.__dict__[self.name]
    except KeyError:
      if self.default is not None:
        return self.default
    exception = MissingItemAttributeError(name=type(self).__name__,
                                          attr=self.name)
    raise exception

  def _is_settable(self, instance):
    set = getattr(instance, f'_{self.name}', False)
    return True if not set else not self.read_only
      
  def __set__(self, instance, value):    
    if self._is_settable(instance):
      instance.__dict__[self.name] = value
      instance.__dict__[f'_{self.name}'] = value
    else:
      exception =  AttrIsReadOnlyError(name=type(self).__name__, attr=self.name)
      raise exception
    
class ItemMeta(type):
  def __new__(metacls, cls, bases, namespace):
    props = [v for k,v in namespace.items() if isinstance(v, ItemProperty)]
    self = super().__new__(metacls, cls, bases, namespace)
    self._mutable_properties   = [p.name for p in props if not p.read_only]
    self._immutable_properties = [p.name for p in props if p.read_only]
    self._all_properties       = [p.name for p in props]
    self._dumpable_properties  = [p.name for p in props if p.dumpable]
    return self
  
class Item(metaclass=ItemMeta):
  """Oldschool runescape item

"""
  id                = ItemProperty(dumpable=False)
  name              = ItemProperty()
  alch              = ItemProperty()
  membs             = ItemProperty()
  desc              = ItemProperty()
  osb_price         = ItemProperty(default=0, read_only=False)
  ge_price          = ItemProperty(default=0, read_only=False)
  last_osb_update   = ItemProperty(default=None, read_only=False)
  last_ge_update    = ItemProperty(default=None, read_only=False)
  ge_cache_priority = ItemProperty(default=0, read_only=False)
  
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

  @property
  def best_price(self):
    if self.osb_price:
      if (time.time() -self.last_osb_update) < Data.max_osb_price_age:
        return self.osb_price
    if self.ge_price:
      return self.get_ge_price()
    return None
  
  def get_ge_price(self):
    self.ge_price, self.last_ge_update = (*ge_lookup(self.id).items(),)[0]
    return self.ge_price
  
  def __str__(self):
    return self.name

  def __int__(self):
    return self.id

  def __hash__(self):
    return hash((type(self), self.id, self.name, self.alch, self.membs,
                 self.desc))

  def __eq__(self, other):
    return self.__hash__() == other.__hash__()
  
  def __repr__(self):
    args = ', '.join(f'{p}={getattr(self,p)!r}'
                     for p in self._immutable_properties)
    return f'{type(self).__name__}({args})'

  def __setattr__(self, attr, val):
    if attr not in self._all_properties:
      raise IllegalItemAttributeError(name=type(self).__name__, attr=attr)
    self.__dict__[attr] = val

  def restore_default(self, property):
    """Restore an item's property to its default value"""
    
    assert property in self._mutable_properties
    setattr(self, property, getattr(type(self), property).default)

class ItemsMeta(type):
  def __new__(metacls, cls, bases, namespace):
    self = super().__new__(metacls, cls, bases, namespace)
    self.load()
    return self
  
  def __getitem__(self, key):
    try:
      hashed = self._hash_map[key]
      return self._data[hashed]
    except KeyError:
      type = ('id' if isinstance(key, int) else
              'name' if isinstance(key,str) else '')
      if not type:
        TypeError_ = TypeError('__getitem__(key) - key must be int/str')
        raise TypeError_ from None
      raise ItemNotFoundError(type=type,key=key) from None

  def __contains__(self, key):
    return key in self._hash_map or key in self._data

  def __iter__(self):
    return iter(self._data.values())

  def __len__(self):
    return len(self._data)

  def _delete(self, item):
    if item not in self:
      raise ValueError('cannot delete something that is not there.')
    hashval = hash(item)
    aliases = [alias for alias, aliashash in Items._hash_map.items()
               if aliashash==hashval]
    del self._data[hashval]
    for alias in aliases:
      del self._hash_map[alias]
      
class Items(metaclass=ItemsMeta):
  """Oldschool Runescape item api"""
  
  @classmethod
  def load(cls):
    """Reload state from disk"""
    data            = Data.load_items()
    items           = [Item(k, **data[k]) for k in data]
    by_id           = {item.id:hash(item) for item in items}
    by_name         = {item.name: hash(item) for item in items}
    cls._hash_map   = {**by_id, **by_name}
    cls._data       = {hash(item): item for item in items}
    cls._search     = search_engine.setup(
      map(str, items),
      Data.load_abbreviations(),
      Data.load_metaitems(),
      Data.load_slang(),
      return_as_resultset=True)

  @classmethod
  def restore_defaults(cls, *properties, all_props=False, itemcls=Item):
    """Restore some Item properties back to their default values en masse"""
    if all_props:
      properties = itemcls._mutable_properties
    assert all(arg in itemcls._mutable_properties for arg in properties)
    for prop in properties:
      for item in cls:
        item.restore_default(prop)
    cls.dump()
    
  @classmethod
  def dump(cls):
    """Save the current state to disk"""
    Data.dump_items(cls._dumps())

  @classmethod
  def _dumps(cls):
    return {i.id:i._dump() for i in cls}
  
  @classmethod
  def search(cls, query):
    """Search the Oldschool Runescape item database

`query` can be an acronym, abbreviation, or n-gram.

Without a cache hit, searches take at worst 500 µs, but usually only 1-2 µs.

Examples:
  search("ags")       -> [Armadyl godsword]
  search("sigil")     -> [Spectral sigil, Arcane sigil, Elysian sigil]
  search("e ook rec") -> [Pie recipe book]
  search("anti+ 2")   -> [Antidote+(2)]
  """
    r = cls._search(query)
    if r:
      r = [i.lower().capitalize() for i in r]
      return [cls[i] for i in r]
    return r

  @classmethod
  def _ge_cacher(cls, last_ge_update, frequency=10, batch_size=5):
    _last_cache_update = 0
    while True:
      
      priorities = {i.id:i.ge_cache_priority for i in cls}
      batches = sorted(priorities,key=priorities.get,reverse=True)
      batches = iter([batches[i:i+batch_size]
                      for i in range(0, len(batches), batch_size)])
      for batch in batches:
        missing = [i for i in batch if not cls[i].osb_price]
        size = len(missing)
        while time.time() - _last_cache_update < (size * frequency):
          yield
        try:
          response = ge_lookup(*missing)
          for itemid, data in response.items():
            if data['time'] != last_ge_update:
              print('fail your')
              cls.restore_defaults('ge_price', 'last_ge_update')
              _ge_lookup.cache_clear()
              last_ge_update = data['time']
              GeCache.insersection_update({})
              break
            cls[itemid].ge_price       = data['price']
            cls[itemid].last_ge_update = data['time']
            GeCache.add(itemid)
        except:
          print('failed to cache ge prices')
          raise
        else:
          _last_cache_update = time.time()
          
  @classmethod
  def _osb_cacher(cls, frequency=2000):
    last_osb_update = 0
    while True:
      if time.time() - last_osb_update > frequency:        
        try:
          response        = osb_lookup()
          missing = [i for i in response if i not in cls]
          if missing:
            cls.download_new_items(missing)
          last_osb_update = int(time.time())
          for itemid, price in response.items():
            if price:
              cls[itemid].osb_price       = price
              cls[itemid].last_osb_update = last_osb_update
              OsbCache.add(itemid)
            else:
              cls[itemid].ge_cache_priority += 1
              lou = cls[itemid].last_osb_update
              if lou and (last_osb_update-lou > Data.max_osb_price_age):
                cls.restore_defaults('osb_price', 'last_osb_update')
        except:
          pass
      yield

  @staticmethod
  def _cache_mainloop(cachers):
    
    while True:
      for cacher in cachers:
        next(cacher)
      time.sleep(1.0)
      
  @classmethod
  def start_cachers(cls, osb=True, osb_frequency=2000,
                    ge=True, ge_frequency=10, ge_batch_size=5):
    cachers = []    
    if osb:
      cachers.append(cls._osb_cacher(osb_frequency))
    if ge:
      gestart = ge_lookup(1965)[1965]['time']
      cachers.append(cls._ge_cacher(gestart, ge_frequency, ge_batch_size))
    if not cachers:
      raise ValueError("no cachers present")    
    cls.cache_thread = threading.Thread(target=cls._cache_mainloop,
                                        args=(cachers,))
    cls.cache_thread.start()
    
  @classmethod
  def download_new_items(cls, items):
    """Update the item database

called automatically when the osb cacher detects new items"""
    dumped = cls._dumps()
    errors = []
    for item in items:
      if item in dumped:
        errors.append(item)
    if any(errors):
      raise ValueError(
        F"items already exist with ids: {', '.join(map(str,errors))}")
    if len(items) > 30:
      raise ValueError('item list is too large (> 30 items not allowed)')
    data = osb_lookup('sp', 'members')
    data = osb_lookup('sp', 'members')
    data = {k:{'alch':data[k]['sp']*3//5,
               'membs':data[k]['members']} for k in items}
    def getter(i):
      data = _request(Data.ge_catalogue%i)
      response = data.json()['item']
      return i, {'desc':response['description'], 'name':response['name']}
    Executor = concurrent.futures.ThreadPoolExecutor
    with Executor(max_workers=len(items)) as executor:
      try:
        futures={executor.submit(getter, i): i for i in items}
        for future in concurrent.futures.as_completed(futures):
          k, resp = future.result()
          data[k] = {**data[k], **resp}
      except Exception as e:
        raise e from None
    Data.dump_items({**dumped, **data})
    cls.load()
    print(f'downloaded {len(items)} new items...')
  

class Cache(set):
  def __new__(cls):
    return super().__new__(cls)  
  @search_engine.container_repr(enclosing='{}')
  def __repr__(self):
    pass
GeCache = Cache()
OsbCache = Cache()


_ge_request_attempts = 0
_ge_request_successes= 0
def ge_req_success():
  return _ge_request_attempts / max(1, _ge_request_successes)
def _request(url, timeout=2, max_tries=3):
  """Deprecated wrapper of request.get from when trying asyncio..."""
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
The cache should be cleared once a day, (and it is cleared automatically when
the caching thread is alive)"""
  global _ge_request_attempts, _ge_request_successes
  _ge_request_attempts += 1
  response = _request(Data.ge_price_api%i)
  results  = response.json()['daily']
  results  = {int(k)//1000:v for k,v in results.items()}
  key      = max(results.keys()) if key is None else key
  _ge_request_successes += 1
  return {i: {'price':results[key], 'time':key}}

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
  with concurrent.futures.ThreadPoolExecutor(max_workers=len(items)) as executor:
    futures = {executor.submit(_ge_lookup, i, **{'key':key}): i for i in items}
    for future in concurrent.futures.as_completed(futures):
      try:
        results = {**results, **future.result()}
      except:
        print(f'failed to get item data for items {items}')

  return results

def osb_lookup(*values):
  keys = ('overall_average',) if not values else values
  data = _request(Data.osb_price_api)
  data = data.json()
  data = {int(i):data[i] for i in data if int(i) not in OSB_IGNORE}
  if len(keys)==1:
    data = {i:data[i][keys[0]] for i in data}
  else:
    data = {i:{k:data[i][k] for k in keys} for i in data}
  return data


  


