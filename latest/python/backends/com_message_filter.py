"""Bounded per-RPC retries for AutoCAD's STA busy responses on Windows.

RetryRejectedCall is invoked only when the server rejected that COM call.
It never replays a Python tool that may already have created an entity.
"""
import ctypes as ct
import logging
import threading
import uuid

log = logging.getLogger(__name__)
_local = threading.local()
_DWORD = ct.c_uint32
_HRESULT = ct.c_int32
_PTR = ct.c_void_p
_QI = ct.WINFUNCTYPE(_HRESULT, _PTR, _PTR, ct.POINTER(_PTR))
_REF = ct.WINFUNCTYPE(_DWORD, _PTR)
_INCOMING = ct.WINFUNCTYPE(_DWORD, _PTR, _DWORD, _PTR, _DWORD, _PTR)
_RETRY = ct.WINFUNCTYPE(_DWORD, _PTR, _PTR, _DWORD, _DWORD)
_PENDING = ct.WINFUNCTYPE(_DWORD, _PTR, _PTR, _DWORD, _DWORD)


class _VTable(ct.Structure):
    _fields_ = [('query', _QI), ('add_ref', _REF), ('release', _REF),
                ('incoming', _INCOMING), ('retry', _RETRY), ('pending', _PENDING)]


class _Interface(ct.Structure):
    _fields_ = [('vtable', ct.POINTER(_VTable))]


_register = ct.OleDLL('ole32').CoRegisterMessageFilter
_register.argtypes = [_PTR, ct.POINTER(_PTR)]
_register.restype = _HRESULT
_supported = {uuid.UUID(s).bytes_le for s in (
    '00000000-0000-0000-C000-000000000046',
    '00000016-0000-0000-C000-000000000046',
)}


class _MessageFilter:
    def __init__(self):
        self.references = 1
        self.retry_count = 0
        self.previous = _PTR()
        # Keep every callback and the interface alive for the entire apartment.
        self.callbacks = (
            _QI(self.query), _REF(self.add_ref), _REF(self.release),
            _INCOMING(lambda *_: 0), _RETRY(self.retry), _PENDING(lambda *_: 2),
        )
        self.vtable = _VTable(*self.callbacks)
        self.interface = _Interface(ct.pointer(self.vtable))

    def query(self, this, iid, result):
        if ct.string_at(iid, 16) not in _supported:
            result[0] = None
            return -2147467262  # E_NOINTERFACE
        result[0] = this
        self.add_ref(this)
        return 0

    def add_ref(self, _):
        self.references += 1
        return self.references

    def release(self, _):
        self.references -= 1
        return self.references

    def retry(self, this, callee, elapsed_ms, reject_type):
        if reject_type in (1, 2) and elapsed_ms < 5000:
            self.retry_count += 1
            log.debug('AutoCAD rejected RPC; retrying in 100 ms (elapsed=%d)', elapsed_ms)
            return 100
        return 0xFFFFFFFF


def register():
    if getattr(_local, 'filter', None) is not None:
        return
    instance = _MessageFilter()
    hr = _register(ct.byref(instance.interface), ct.byref(instance.previous))
    if hr != 0:
        raise RuntimeError(f'CoRegisterMessageFilter failed: {hr}')
    _local.filter = instance


def _release(pointer):
    if pointer:
        obj = ct.cast(pointer, ct.POINTER(_Interface)).contents
        obj.vtable.contents.release(pointer)


def unregister():
    instance = getattr(_local, 'filter', None)
    if instance is None:
        return
    replaced = _PTR()
    hr = _register(instance.previous, ct.byref(replaced))
    if hr != 0:
        raise RuntimeError(f'CoRegisterMessageFilter restore failed: {hr}')
    _release(replaced)
    _release(instance.previous)
    log.info('AutoCAD RPC filter handled %d transient rejections', instance.retry_count)
    del _local.filter
