import os
from os.path import exists

import pkg_resources
import six
from tqdm.auto import tqdm

if six.PY2:
    from urllib import urlretrieve
else:
    from urllib.request import urlretrieve

import tarfile

try:
    from .version import __version__  # NOQA
except ImportError:
    raise ImportError("BUG: version.py doesn't exist. Please file a bug report.")

from .htsengine import HTSEngine
from .openjtalk import OpenJTalk
from .utils import merge_njd_marine_features

# Dictionary directory
# defaults to the package directory where the dictionary will be automatically downloaded
OPEN_JTALK_DICT_DIR = os.environ.get(
    "OPEN_JTALK_DICT_DIR",
    pkg_resources.resource_filename(__name__, "open_jtalk_dic_utf_8-1.11"),
).encode("utf-8")
_dict_download_url = "https://github.com/r9y9/open_jtalk/releases/download/v1.11.1"
_DICT_URL = f"{_dict_download_url}/open_jtalk_dic_utf_8-1.11.tar.gz"

# Default mei_normal.voice for HMM-based TTS
DEFAULT_HTS_VOICE = pkg_resources.resource_filename(
    __name__, "htsvoice/mei_normal.htsvoice"
).encode("utf-8")

# Global instance of OpenJTalk
_global_jtalk = None
# Global instance of HTSEngine
# mei_normal.voice is used as default
_global_htsengine = None
# Global instance of Marine
_global_marine = None


# https://github.com/tqdm/tqdm#hooks-and-callbacks
class _TqdmUpTo(tqdm):  # type: ignore
    def update_to(self, b=1, bsize=1, tsize=None):
        if tsize is not None:
            self.total = tsize
        return self.update(b * bsize - self.n)


def _extract_dic():
    global OPEN_JTALK_DICT_DIR
    filename = pkg_resources.resource_filename(__name__, "dic.tar.gz")
    print('Downloading: "{}"'.format(_DICT_URL))
    with _TqdmUpTo(
        unit="B",
        unit_scale=True,
        unit_divisor=1024,
        miniters=1,
        desc="dic.tar.gz",
    ) as t:  # all optional kwargs
        urlretrieve(_DICT_URL, filename, reporthook=t.update_to)
        t.total = t.n
    print("Extracting tar file {}".format(filename))
    with tarfile.open(filename, mode="r|gz") as f:
        f.extractall(path=pkg_resources.resource_filename(__name__, ""))
    OPEN_JTALK_DICT_DIR = pkg_resources.resource_filename(
        __name__, "open_jtalk_dic_utf_8-1.11"
    ).encode("utf-8")
    os.remove(filename)


def _lazy_init():
    if not exists(OPEN_JTALK_DICT_DIR):
        _extract_dic()


def g2p(*args, **kwargs):
    """Grapheme-to-phoeneme (G2P) conversion

    This is just a convenient wrapper around `run_frontend`.

    Args:
        text (str): Unicode Japanese text.
        kana (bool): If True, returns the pronunciation in katakana, otherwise in phone.
          Default is False.
        join (bool): If True, concatenate phones or katakana's into a single string.
          Default is True.

    Returns:
        str or list: G2P result in 1) str if join is True 2) list if join is False.
    """
    global _global_jtalk
    if _global_jtalk is None:
        _lazy_init()
        _global_jtalk = OpenJTalk(dn_mecab=OPEN_JTALK_DICT_DIR)
    return _global_jtalk.g2p(*args, **kwargs)


def estimate_accent(njd_features):
    """Accent estimation using marine

    This function requires marine (https://github.com/6gsn/marine)

    Args:
        njd_result (list): features generated by OpenJTalk.

    Returns:
        list: features for NJDNode with estimation results by marine.
    """
    global _global_marine
    if _global_marine is None:
        try:
            from marine.predict import Predictor
        except BaseException:
            raise ImportError("Please install marine by `pip install pyopenjtalk[marine]`")
        _global_marine = Predictor()
    from marine.utils.openjtalk_util import convert_njd_feature_to_marine_feature

    marine_feature = convert_njd_feature_to_marine_feature(njd_features)
    marine_results = _global_marine.predict(
        [marine_feature], require_open_jtalk_format=True
    )
    njd_features = merge_njd_marine_features(njd_features, marine_results)
    return njd_features


def extract_fullcontext(text, run_marine=False):
    """Extract full-context labels from text

    Args:
        text (str): Input text
        run_marine (bool): Whether estimate accent using marine.
          Default is False. If you want activate this option, you need to install marine
          by `pip install pyopenjtalk[marine]`

    Returns:
        list: List of full-context labels
    """

    njd_features = run_frontend(text)
    if run_marine:
        njd_features = estimate_accent(njd_features)
    return make_label(njd_features)


def synthesize(labels, speed=1.0, half_tone=0.0):
    """Run OpenJTalk's speech synthesis backend

    Args:
        labels (list): Full-context labels
        speed (float): speech speed rate. Default is 1.0.
        half_tone (float): additional half-tone. Default is 0.

    Returns:
        np.ndarray: speech waveform (dtype: np.float64)
        int: sampling frequency (defualt: 48000)
    """
    if isinstance(labels, tuple) and len(labels) == 2:
        labels = labels[1]

    global _global_htsengine
    if _global_htsengine is None:
        _global_htsengine = HTSEngine(DEFAULT_HTS_VOICE)
    sr = _global_htsengine.get_sampling_frequency()
    _global_htsengine.set_speed(speed)
    _global_htsengine.add_half_tone(half_tone)
    return _global_htsengine.synthesize(labels), sr


def tts(text, speed=1.0, half_tone=0.0, run_marine=False):
    """Text-to-speech

    Args:
        text (str): Input text
        speed (float): speech speed rate. Default is 1.0.
        half_tone (float): additional half-tone. Default is 0.
        run_marine (bool): Whether estimate accent using marine.
          Default is False. If you want activate this option, you need to install marine
          by `pip install pyopenjtalk[marine]`

    Returns:
        np.ndarray: speech waveform (dtype: np.float64)
        int: sampling frequency (defualt: 48000)
    """
    return synthesize(
        extract_fullcontext(text, run_marine=run_marine), speed, half_tone
    )


def run_frontend(text):
    """Run OpenJTalk's text processing frontend

    Args:
        text (str): Unicode Japanese text.

    Returns:
        list: features for NJDNode.
    """
    global _global_jtalk
    if _global_jtalk is None:
        _lazy_init()
        _global_jtalk = OpenJTalk(dn_mecab=OPEN_JTALK_DICT_DIR)
    return _global_jtalk.run_frontend(text)


def make_label(njd_features):
    """Make full-context label using features

    Args:
        njd_features (list): features for NJDNode.

    Returns:
        list: full-context labels.
    """
    global _global_jtalk
    if _global_jtalk is None:
        _lazy_init()
        _global_jtalk = OpenJTalk(dn_mecab=OPEN_JTALK_DICT_DIR)
    return _global_jtalk.make_label(njd_features)
