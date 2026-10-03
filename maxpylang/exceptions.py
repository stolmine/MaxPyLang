"""
Custom warning classes for MaxPyLang.
"""


class UnknownObjectWarning(UserWarning):
    """Raised when a Max object name is not recognized."""
    pass


class DeviceReadError(ValueError):
    """Raised when an .amxd file cannot be parsed."""
    pass


class EncryptedDeviceError(DeviceReadError):
    """Raised when an .amxd is Ableton-encrypted (ciph chunk) and cannot be read."""
    pass
