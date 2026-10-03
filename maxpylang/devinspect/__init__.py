"""
maxpylang.devinspect — read-only inspection of existing Max for Live devices.

    import maxpylang as mp

    d = mp.describe("Some Device.amxd")      # plain, frozen or meta-less .amxd, or .maxpat
    print(d.to_markdown())                   # concise summary for people / LLM agents
    data = d.to_json()                       # full detail
    mp.extract("Some Device.amxd", "out/")   # main patch as .maxpat + embedded files
    for row in mp.survey("M4L devices/"):    # one summary dict per device in a folder
        print(row)

Encrypted (ciph) devices raise maxpylang.exceptions.EncryptedDeviceError.
Input files are never written.
"""

from .extract import extract, survey, survey_device
from .model import DeviceDescription, describe, load_any
from .params import format_param

__all__ = ["describe", "extract", "survey", "survey_device", "DeviceDescription",
           "load_any", "format_param"]
