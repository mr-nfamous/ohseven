
import re
from functools import lru_cache, wraps, update_wrapper

__all__ = ['ResultSet', 'setup']

def container_repr(*, max_length=5, fn=None, enclosing=None):
    """Limits the number of items displayed in a container's __repr__

    Useful for large containers whose normal __repr__ would produce a
    30000 character string.

    The container must implement __len__ and __iter__ methods.

    Arguments:
        `max_length`: max number of results to show in the container repr

        `fn`: a function to apply to the container, ie for sorting

        `enclosing`: 2 character string sequence for optional container
        enclosements. "{}" would indicate that the container represents
        a set, and "[]" and "()" would indicate a list and tuple, respectively.
    """
    def wrap(__repr__):
        if isinstance(enclosing, str) and len(enclosing)==2:
            left, rite = enclosing
        elif enclosing is not None:
            raise TypeError('enclosing must be a 2 character string')
        else:
            left, rite = '', ''
        def inner(self):
            data = [*fn(self)] if fn is not None else [*self]       
            left = ', '.join(map(repr, data[:max_length-1]))
            length = len(data)
            if length > max_length:                
                mid  = '{<< and %s more >>}...'%(len(data) - max_length)
                rep = f'{left}, {mid}, {data[-1]!r}'
            elif length == max_length:
                rep = f'{left}, {data[-1]!r}'
            else:
                rep = left
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

    def __add__(self, other):
        if isinstance(other, (tuple, list, set, frozenset)):
            other = self._data + (*other,)
        elif isinstance(other, type(self)):
            other = self._data + other._data
        else:
            raise TypeError(f"can only concatenate {type(self).__name__} or tuple")
        return type(self)(*other)

    def __iadd__(self, other):
        y = self.__add__(other)
        self._data = y._data
        return self

    def __radd__(self, other):
        return self.__add__(other)
    
    def __getitem__(self, index):
        return self._data[index]

    def __hash__(self):
        return hash((type(self), self._data))

    def __eq__(self, other):
        return hash(self) == hash(other)

    @container_repr(max_length=5)
    def __repr__(self):
        pass  

def setup(words, abbreviations, meta, slang_, sep='~',
                    must_contain_all=False, return_as_resultset=False):
    """Create a new search engine function

    The search engine works by splitting an argument up into individual
    "words", or n-grams, which are them compared to the words used in the
    setup.
    
    In order to register a hit, the entire argument must exist within
    an item.

    See the actual files for better examples...
    
    Arguments:
        `words`: - a list of words to be searched through

        `abbreviations`: a dict {abbreviation: full} of
        common abbreviations/acronyms for words. In the context
        of runescape, "ags" is an abbreviation for Armadyl godsword

        `meta`: a list of tuples in the pair of (regex, repl) that represent
        words that exist within other words. In the context of Runescape,
        an example would be Antidote+ and Antidote++. The string
        "antidote+" exists in both items, but the searcher would most likely
        mean to only get results for "antidote+".

        `slang`: a list of tuples in the pair of (regex, repl) that represent
        common misspellings or slang words that don't actually exist in the
        provided items. In the context of Runescape, a scimmy is a scimitar,
        but no actual tems exist that contain the string 'scimmy' within their
        name.

        `sep`: the seperator of the items. It is used in the algorithm,
        and it cannot exist in any of the items. "~" is the default because
        it has the best performance. Invalid ascii characters like \x00
        cause a huge performance drop.

        `must_contain_all`: If set, the entire search argument must exist within
        a word. Wildcards obviously count as any letter.
    
    """

    items        = [i.lower() for i in words]
    letter_freqs = {i[0]:0 for i in items}
    for item in items:
        letter = item[0]
        letter_freqs[letter] += 1
    order    = ''.join(sorted(letter_freqs,key=letter_freqs.get, reverse=True))
    print(len(order))
    by_close = *sorted(items, key=lambda item: order.index(item[0])),
    tok      = '*' if must_contain_all else ''
    by_close = *(f'{tok}{i}' for i in by_close),
    search_str = f'{sep}{sep.join(by_close)}{sep}'
    if (len(sep)>1) or  (sep in set(''.join(items))):
        raise ValueError('"sep" {sep} cannot be used because it is within an item')
    # remove spaces and punctuation
    if must_contain_all:
        re.sub(f'[^\w{sep}*]', '', search_str)
    metaitems = ()
    for prog, repl in meta:
        if not isinstance(prog, str) and isinstance(repl, (list, str)):
            raise ValueError
        metaitems = (*metaitems, (re.compile(prog), repl))

    slang = ()
    for prog, repl in slang_:
        slang = (*slang, (re.compile(prog), repl))
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
            left  = search_str[:index].rindex(sep) + 1
            rite  = index = search_str.index(sep, index)
            item  = rem = search_str[left:rite]
            if must_contain_all:
                for word in words:
                    if word in item:
                        rem = rem.replace(word, '', 1)
                # if the number of letters remaining is less than or equal to
                # the number of wildcards, it passes
                ok = len(rem) < (1 + wildcards)
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
        search_func = update_wrapper(lru_cache(16384)(wrapper), search)
    else:
        search_func = update_wrapper(lru_cache(16384)(search), search)

    return search_func
