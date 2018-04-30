import re

from collections import Counter
from functools import lru_cache, update_wrapper, wraps
from operator import methodcaller, attrgetter, itemgetter
from itertools import chain, starmap
from publicize import public
isstrinstance = str.__instancecheck__
islistinstance = list.__instancecheck__
class _extra:
    def __init__(self, n):
        self.n = n
    def __repr__(self):
        return f'... and {self.n} more results'
    
class ResultSet(list):
    
    def __init__(self, *args):
        super().extend(args)
        
    def __iter__(self):
        return iter(super().__getitem__(slice(0, 5)))
    
    def __repr__(self):
        length = len(self)
        x = super().__getitem__(slice(0, 5))
        if length > 5:
            x += [_extra(length-5)]
        return f'ResultSet({x!r})'
    
    def __getitem__(self, index):
        if isinstance(index, int):
            return super().__getitem__(index)    
        return type(self)(*super().__getitem__(index))
    @property
    def all(self):
        return super().__getitem__(slice(None))

@public
def search_setup(words,
                 abbreviations,
                 ngrams,
                 slang_,
                 sep='~',*,
                 match_exact=False,
                 cache=True,
                 cache_size=2**14,
                 result_cls=ResultSet):
    """Create a new search engine function

    The search engine works by splitting an argument up into individual
    n-grams and comparing them to each item given to setup. In order to
    register a hit, the entire argument must exist within an item.

    See the actual files for better examples...
    
    Arguments:
        `words`: The list of words searched

        `abbreviations`: Mapping of abbreviations: word pairs

        `ngrams`: List of (regex, replacement) pairs
        This is to be used when a a word is also a substring of other
        words and it is obvious that this input means the substring.
        'bat' is a substring of 'acrobat', but the user most likely
        would want 'bat' and not all of the many words that contain
        the sequence of letters 'bat'.

        `slang`: A list of (regexp, repl) pairs
        Obvious misspellings or abbreviations with multiple variants
        that can fit into a regex pattern. If regex groups are present
        then the same amount of variable replacement fields must exist.
        For example:
        "(?:black) mysti?c?(.*)", "mystic %s (dark)"
        in that pattern if the search term was "black myst robe",
        it would be converted to "mystic %s (dark)"%("robe",).

        `sep` is a character used internally by the search algorithm.
        In the algorithm, all items are concatenated into a giant string
        seperated by `sep`. As sep is used to delineate each seperate
        item, it cannot exist within any of the items.
        Note that on-ascii characters such as \x00 cause a significant
        performance drop.

        `cache` if True uses functools.lru_cache to speed up searches

        `cache_size` is the size if cache (works best with power of 2)
        
        `result_cls` should be a container that takes multiple *args
    """

    items        = [i.lower() for i in words]
    letter_freqs = Counter(map(itemgetter(0), items))
    # an optimization is to sort items by first letter frequency
    #letter_freqs = {i[0]:0 for i in items}
    #for item in items:
    #    letter = item[0]
    #    letter_freqs[letter] += 1
    order    = ''.join(sorted(letter_freqs,key=letter_freqs.get, reverse=True))
    by_close = *sorted(items, key=lambda item: order.index(item[0])),
    search_str = f'{sep}{sep.join(by_close)}{sep}'
    if (len(sep)>1) or  (sep in set(''.join(items))):
        raise ValueError(
            '"sep" {sep} cannot be used because it is within an item')
    def compile_first(pat, repl, comp=re.compile):
        if not isinstance(pat, str) or not isinstance(repl, (str, list, tuple)):
            raise TypeError(f'{pat} -> {repl!r}\n pattern must be a string '
                            '(regex pattern) and repl must be a string '
                            'or list/tuple of replacement fields.')
        return comp(pat), repl
    ngrams = *starmap(compile_first, ngrams),
    slang = *starmap(compile_first, slang_),
    get_index = search_str.index
    get_rindex = search_str.rindex
    word_counter = methodcaller('count')
    def search(query):
        if query in abbreviations:
            return abbreviations[query]
        x = query.lower()
        for prog, repl in slang:
            q = prog.search(x)
            if q:
                x = prog.sub(repl, x)
                if q.groups():
                    x %= q.groups()
        for prog, repl in ngrams:
            q = prog.search(x)
            if q:
                if isstrinstance(repl):
                    return repl % q.groups()
                elif islistinstance(repl):
                    return repl
        y = x.replace(' ','')
        if len(y) < 4 or match_exact:
            if y in by_close:
                return y
        words = x.strip().split(' ')
        counts= {i:search_str.count(i) for i in words}
        if 0 in counts.values():
            return None        
        index_word, *words = sorted(words, key=counts.get)
        index = 0
        rindex = get_rindex(index_word)
        r = []
        append = r.append
        while index < rindex:
            index = get_index(index_word, index)
            left  = search_str[:index].rindex(sep) + 1
            rite  = index = get_index(sep, index)
            item  = rem = search_str[left:rite]
            ok    = True
            for word in words:
                if word not in rem:
                    ok = not rem
                    break
                rem = rem.replace(word, '', 1)
            if ok:
                append(item)
        return r
    
    def wrapper(*args, **kwargs):
        r = search(*args, **kwargs)
        if isstrinstance(r):
            return result_cls(r)
        return result_cls(*r) if r is not None else r
    if cache:
        resulting_func = update_wrapper(lru_cache(16384)(wrapper), search)
    else:
        resulting_func = update_wrapper(wrapper, search)
    resulting_func.by_close = by_close
    resulting_func.ngrams = ngrams
    resulting_func.abbreviations = abbreviations
    resulting_func.slang = slang
    return resulting_func
