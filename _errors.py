
from publicize import public

@public
class MissingConfigOptionsError(Exception):
    def __init__(self, opt, subopts):
        missing = ', '.join(map(repr, subopts))
        super().__init__(f'config[{opt!r}] missing options: {missing}')

@public
class BadConfigTypeError(TypeError):
    def __init__(self, opt, subopt, val, correct_typ):
        curtype = type(val).__name__
        cortype = correct_typ.__name__
        super().__init__(f'CONFIG[{opt!r}][{subopt!r}] was of type '
                         f'{curtype!r} but should be type {cortype!r}')
@public
class NonExistentItemError(Exception):
    def __init__(self, attr, value):
        super().__init__(f'There is no item with {attr}={value!r}')
