
import time
from operator import attrgetter, itemgetter, methodcaller
from collections import OrderedDict as odict, deque, namedtuple
from itertools import *
from publicize import public, public_constants

class Sentinel:
    
    __instance = None
    
    def __new__(cls, *args, **kwargs):
        self = cls.__instance
        if self is None:
            self = cls.__instance = object.__new__(cls)
        return self
    
    def __repr__(self):
        return 'SENTINEL'

    def __hash__(self):
        return 233544130

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other
    
public_constants(
    attrgetter=attrgetter,
    name_getter=attrgetter('name'),
    descg_etter=attrgetter('desc'),
    alchge_tter=attrgetter('alch'),
    
    SENTINEL=Sentinel(),
    time_in_seconds=map(int, starmap(time.time, repeat(()))).__next__,
    isstrinstance=str.__instancecheck__,
    isintinstance=int.__instancecheck__,
    issetinstance=set.__instancecheck__,
    islistinstance=list.__instancecheck__,
    isdictinstance=dict.__instancecheck__,
    isexceptioninstance=Exception.__instancecheck__,
    )

@public
def safe_repr(cls):
    """Don't print 500,000 character reprs on accident."""
    def __repr__(self):
        return f'<{cls.__name__} object with {len(self)} items at 0x{id(self):08X}>'
    cls.__repr__ = __repr__
    return cls

@public
@safe_repr
class List(list):
    pass

@public
@safe_repr
class DotDict(odict):
    """Dict with dot lookup"""
    
    def __getattr__(self, attr):
        result = self.get(attr, SENTINEL)
        if result is SENTINEL:
            error = AttributeError(f'{self.__class__.__name__!r} object has no attribute {attr!r}')
            raise error
        if result.__class__ in (dict, odict):
            return self.__class__(result)
        return result

    def __dir__(self, f=str.isidentifier):
        cdir = set(i for i in super().__dir__() if i.startswith('__'))
        return cdir | {*filter(f, map(str, self))}

@public
def getattrs(obj, attrs):
    return map(getattr, repeat(obj), attrs)


@public
def backup_file(old_path, backup_path):
    if not old_path.exists():
        error = IOError(f'path {old_path} does not exist so cannot be backed up.')
        raise error
    with open(old_path, 'rb') as fpin, open(backup_path, 'wb') as fpout:
        fpout.write(fpin.read())
        
