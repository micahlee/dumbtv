#!/usr/bin/env python3
"""Resolve one serial-bound local ADB service through macOS Bonjour, without browsing."""
import ctypes as C
import json
import re
import select
import socket
import sys
import time

SERVICE = re.compile(r'adb-([A-Za-z0-9_-]{1,64})\Z')


def serial(service):
    match = SERVICE.fullmatch(service) if isinstance(service, str) else None
    if not match:
        raise ValueError('Invalid serial-based TV service')
    return match[1]


def resolve(service, timeout=3):
    serial(service)
    # Darwin re-exports DNS-SD through libSystem (there may be no libdns_sd.dylib).
    # Resolve immediately before each connection, per Apple's DNS-SD guidance.
    lib = C.CDLL('/usr/lib/libSystem.B.dylib')
    ref = C.c_void_p()
    callback_type = C.CFUNCTYPE(None, C.c_void_p, C.c_uint32, C.c_uint32, C.c_int32,
                               C.c_char_p, C.c_char_p, C.c_uint16, C.c_uint16,
                               C.c_void_p, C.c_void_p)
    lib.DNSServiceResolve.argtypes = [C.POINTER(C.c_void_p), C.c_uint32, C.c_uint32,
                                     C.c_char_p, C.c_char_p, C.c_char_p, callback_type, C.c_void_p]
    lib.DNSServiceResolve.restype = C.c_int32
    lib.DNSServiceRefSockFD.argtypes = [C.c_void_p]
    lib.DNSServiceRefSockFD.restype = C.c_int
    lib.DNSServiceProcessResult.argtypes = [C.c_void_p]
    lib.DNSServiceProcessResult.restype = C.c_int32
    lib.DNSServiceRefDeallocate.argtypes = [C.c_void_p]
    lib.DNSServiceRefDeallocate.restype = None
    results = []

    @callback_type
    def reply(_ref, _flags, _interface, error, _name, host, port, _length, _txt, _context):
        # Callback errors cannot escape through ctypes. Validate before returning.
        if not error and host:
            results.append((host.decode('ascii', errors='replace').rstrip('.'), socket.ntohs(port)))
        else:
            results.append(None)

    if lib.DNSServiceResolve(C.byref(ref), 0, 0, service.encode('ascii'), b'_adb._tcp', b'local.', reply, None):
        raise RuntimeError('TV service discovery unavailable')
    try:
        fd = lib.DNSServiceRefSockFD(ref)
        deadline = time.monotonic() + timeout
        while fd >= 0 and not results:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                break
            if lib.DNSServiceProcessResult(ref):
                break
        if results and results[0]:
            host, port = results[0]
            if re.fullmatch(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.local', host, re.IGNORECASE) and 0 < port <= 65535:
                return host, port
        raise RuntimeError('TV service discovery unavailable')
    finally:
        lib.DNSServiceRefDeallocate(ref)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('One serial-based service is required')
        host, port = resolve(sys.argv[1])
        print(json.dumps({'device': host + ':' + str(port), 'serial': serial(sys.argv[1])}))
    except (ValueError, RuntimeError, OSError):
        sys.exit(1)  # Discovery failure never prints a stale or generic fallback.
