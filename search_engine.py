
import re
from functools import lru_cache, wraps, update_wrapper
__all__ = ['ResultSet', 'setup']

def container_repr(*, max_length=5, fn=None, enclosing=None):
  """Only allow max_length results in the objects __repr__

Object must have __iter__ and __len__ methods defined.
If fn is given, it is applied to the objects data, ie for sorting"""
  def wrap(__repr__):
    def inner(self):
      data = [*fn(self)] if fn is not None else [i for i in self]        
      left = ', '.join(map(repr, data[:max_length-1]))
      length = len(data)
      if length > max_length:                
        mid  = '{<< and %s more >>}...'%(len(data) - max_length)
        rep = f'{left}, {mid}, {data[-1]!r}'
      elif length == max_length:
        rep = f'{left}, {data[-1]!r}'
      else:
        rep = left
      left, rite = enclosing if enclosing is not None else ('', '')
      return f'{type(self).__name__}({left}{rep}{rite})'
    return inner
  return wrap

class ResultSet:
  
  def __init__(self, *args):
    self._data = args
  
  def extend(self, it):
    self._data = (*self._data, *it)

  def append(self, item):
    self._data = (*self._data, it,)

  def __len__(self):
    return len(self._data)
  
  def __contains__(self, item):
    return item in self._data

  def __iter__(self):
    return iter(self._data)

  def __add__(self, x):
    if isinstance(x, (tuple, list, set, frozenset)):
      x = self._data + (*x,)
    elif isinstance(x, type(self)):
      x = self._data + x._data
    else:
      raise TypeError(f"can only concatenate {type(self).__name__} or tuple")
    return type(self)(*x)
  
  def __iadd__(self, x):
    y = self.__add__(x)
    self._data = y._data
    return self
  
  def __getitem__(self, index):
    return self._data[index]
  
  def __hash__(self):
    return hash((type(self), self._data))

  def __eq__(self, other):
    return hash(self) == hash(other)
  
  @container_repr(max_length=5)
  def __repr__(self):
    pass  

def setup(items, abbreviations, meta, slang_, sep='~',
          must_contain_all=False, return_as_resultset=False):
  items        = [i.lower() for i in items]
  letter_freqs = {i[0]:0 for i in items}
  for item in items:
    letter = item[0]
    letter_freqs[letter] += 1
  order    = ''.join(sorted(letter_freqs,key=letter_freqs.get, reverse=True))
  by_close = *sorted(items, key=lambda item: order.index(item[0])),
  tok      = '*' if must_contain_all else ''
  by_close = *(f'{tok}{i}' for i in by_close),
  search_str = f'{sep}{sep.join(by_close)}{sep}'
  if (len(sep)>1) or  (sep in set(''.join(items))):
    raise ValueError('"sep" {sep} cannot be used because it is within an item')
  metaitems = ()
  for prog, repl in meta:
    if not isinstance(prog, str) and isinstance(repl, (list, str)):
      raise ValueError
    metaitems = (*metaitems, (re.compile(prog), repl))

  slang = ()
  for prog, repl in slang_:
    slang = (*slang, (re.compile(prog), repl))
  #@
  def search(query, wildcards=0):
    if query in abbreviations:
      return abbreviations[query]
    x = query
    x = x.lower()
    for prog, repl in slang:
      q = prog.search(x)
      if q:
        x = prog.sub(repl, x)
        if q.groups():
          x %= q.groups()

    for prog, repl in metaitems:
      q = prog.search(x)
      if q:
        if isinstance(repl, str):
          return repl%q.groups()
        elif isinstance(repl, list):
          return repl

    y = x.replace(' ','')
    if len(y) < 4:
      if y in by_close:
        return y

    words = [i for i in x.strip().split(' ')]
    counts= {i:search_str.count(i) for i in words}
    if not must_contain_all:
      if 0 in counts.values():
        return None
      k, *words = sorted(words, key=counts.get)
    else:
      k, words = '*', sorted(words, key=counts.get)
    index = 0
    rindex = search_str.rindex(k)
    r = []
    while index < rindex:
      index = search_str.index(k, index)
      left = search_str[:index].rindex(sep) + 1
      rite = index = search_str.index(sep, index)
      item = rem = search_str[left:rite]
      if must_contain_all:
        for word in words:
          if word in item:
            rem = rem.replace(word, '', 1)
        ok = len(rem) <= (1 + wild)
        if ok:
          item = item.replace(k, '')
      else:
        ok = True
        for word in words:
          if rem:
            ok = ok and word in rem
            if not ok:
              break
            rem = rem.replace(word, '', 1)
          else:
            break
      if ok:
        r.append(item)
    return r
  if return_as_resultset:
    def wrapper(*args, **kwargs):
      r = search(*args, **kwargs)
      if isinstance(r, str):
        return ResultSet(r)
      return ResultSet(*r) if r is not None else r
    return update_wrapper(lru_cache(16384)(wrapper), search)
  else:
    return update_wrapper(lru_cache(16384)(search), search)


