from pathlib import Path
import json
import requests
import warnings
from functools import lru_cache

from publicize import public, public_constants
try:
    from utils import DotDict, backup_file
    from _errors import MissingConfigOptionsError, BadConfigTypeError
except:
    from .utils import DotDict, backup_file
    from ._errors import MissingConfigOptionsError, BadConfigTypeError
public_constants(
    PATH=Path.home()/'.ohseven.data',
    CONFIG=DotDict(),
    )

RAW_ITEM_DATA_URL = 'https://pastebin.com/raw/Hqz7yde3'
SEARCH_PARAMETER_URL = 'https://pastebin.com/raw/zwQTBGy7'
if not PATH.exists():
    PATH.mkdir()

def default_config():
    return dict(
        filenames=dict(
            abbreviations='abbreviations.json',
            backup='original_items.json',
            ge_cache='ge_cache.json',
            item_data='itemdb.json',
            ngrams='ngrams.json',
            osb_cache='osb_cache.json',
            slang='slang.json'),
        general_settings = dict(
            ge_autocache= False,
            load_ge_cache_on_import=True,
            load_items_on_import=True,
            load_osb_cache_on_import=True,
            osb_autocache=False),
        hiscore_urls = dict(
            cml='https://crystalmathlabs.com/tracker/api.php?',
            deadman='http://services.runescape.com/m=hiscore_oldschool_deadman/index_lite.ws?player=%s',
            hardcore='http://services.runescape.com/m=hiscore_oldschool_hardcore_ironman/index_lite.ws?player=%s',
            ironman='http://services.runescape.com/m=hiscore_oldschool_ironman/index_lite.ws?player=%s',
            normal= 'http://services.runescape.com/m=hiscore_oldschool/index_lite.ws?player=%s',
            seasonal= 'http://services.runescape.com/m=hiscore_oldschool_seasonal/index_lite.ws?player=%s',
            ultimate= 'http://services.runescape.com/m=hiscore_oldschool_ultimate/index_lite.ws?player=%s'),
        item_data_urls =dict(
            ge_catalogue= 'http://services.runescape.com/m=itemdb_oldschool/api/catalogue/detail.json?item=%s',
            ge_price_api= 'http://services.runescape.com/m=itemdb_oldschool/api/graph/%s.json',
            osb_catalogue= 'https://rsbuddy.com/exchange/summary.json',
            osb_price_api="https://api.rsbuddy.com/grandExchange?a=guidePrice&i=%s"),
        cache_settings=dict(
            osb_cache_duration=1800,# max ages in seconds price remains in cache
            osb_auto_cache_frequency=2000,# 2000 means one check every 2000 secs
            ge_auto_cache_frequency=6000# 6000 means 6000 lookups per day
            ))

@public
def save_config(path_override=None, backup_path=None):
    if path_override:
        path = Path(path_override)
    else:
        path = PATH/'config.json'
    if backup_path:
        backup_file(path, pathlib.Path(backup_path))
    with open(cfg, 'w') as fp:
        json.dump(CONFIG, fp)
            
@lru_cache(None)
def default_item_data():
    return requests.get(RAW_ITEM_DATA_URL).json()

@lru_cache(None)
def download_search_parameters():
    return requests.get(SEARCH_PARAMETER_URL).json() # abbv, ngrams, slang

@public
def load_config():
    if (PATH/'config.json').exists():
        with open(PATH/'config.json') as fp:
            data = fp.read()
    cfg = DotDict(json.loads(data))
    bad_config_types = []
    missing_config = []
    default = default_config()
    for opt, subopts in default.items():
        if opt not in cfg:
            error = MissingConfigOptionsError(opt, [*subopts])
            missing_config.append(error)
            cfg[opt] = default[opt]
        for subopt, val in subopts.items():
            if subopt not in cfg[opt]:
                error = MissingConfigOptionsError(opt, [subopt])
                missing_config.append(error)
                cfg[opt][subopt] = val
            cfgval = cfg[opt][subopt]
            cls = val.__class__
            if not isinstance(cfgval, cls):
                error = BadConfigTypeError(opt, subopt, cfgval, cls)
                bad_config_types.append(error)
                cfg[opt][subopt] = val
    rewrite = missing_config or bad_config_types
    for error in missing_config:
        warnings.warn(error)
    for error in bad_config_types:
        warnings.warn(error)
    CONFIG.clear()
    CONFIG.update(cfg)
    if rewrite:
        error = ValueError('fix above errors in the config file '
                           'or call `save_config` to replace the '
                           'erroneous options with their default values.')
        raise error
    for k, v in CONFIG.copy().items():
        CONFIG[k] = DotDict(v)
    if (PATH/CONFIG.filenames.item_data).exists():
        with open(PATH/CONFIG.filenames.item_data) as fp:
            data = fp.read()
    try:
        data = json.loads(data)
        assert data
    except:
        print('no valid item database found; creating new.')
        data = default_item_data()
        data = json.dumps(data, indent=2)
        with open(PATH/CONFIG.filenames.item_data, 'w') as fp:
            fp.write(data)
    del data
    getter = CONFIG.filenames.__getitem__
    filenamekeys = ('abbreviations', 'ngrams', 'slang')
    for i, fname in enumerate(PATH/i for i in map(getter, filenamekeys)):
        if fname.exists():
            with open(fname) as fp:
                data = fp.read()
        try:
            data = json.loads(data)
            assert data
        except:
            print(f'could not find valid file {fname}; creating new.')
            r = (abbv, ngram, slang) = download_search_parameters()
            data = json.dumps(r[i], indent=1)
            with open(fname, 'w') as fp:
                fp.write(data)
        del data

load_config()
