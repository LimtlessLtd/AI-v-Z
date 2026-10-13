"""The game's own audio for agent/hearing.py: Windows process-loopback capture of Project Zomboid.

Windows 10 2004 and later can capture what one process tree renders, before it is mixed with anything else
(ActivateAudioInterfaceAsync on "VAD\\Process_Loopback", AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK; Microsoft's
ApplicationLoopback sample). So this hears the game and nothing else: no microphone, no other app. A daemon
thread finds ProjectZomboid64.exe, captures 16-bit stereo at 48 kHz in WINDOW_S windows, and reconnects when the
game restarts. Needs comtypes (installed) and numpy. Measured on the owner's PC on 2026-10-13: 10 ms packets, about
2% of a core. If the game's own volume is 0 the windows are silent: that is what a player would hear too.

`available` and `reason` say whether it is capturing; nothing is ever made up when it isn't.
"""

import ctypes
import sys
import threading
import time
from collections import deque
from ctypes import wintypes as wt

GAME_EXE = "ProjectZomboid64.exe"
RATE = 48000
WINDOW_S = 0.25
RETRY_S = 10.0


def find_pid(exe=GAME_EXE):
    """The process id of the first process named `exe`, or None (Toolhelp snapshot, no extra packages)."""
    if sys.platform != "win32":
        return None

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
    if snap in (None, wt.HANDLE(-1).value):
        return None
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(e)
        ok = k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            if e.szExeFile.lower() == exe.lower():
                return int(e.th32ProcessID)
            ok = k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return None


def _com():
    """comtypes, with this thread in the multithreaded apartment the activation callback needs."""
    if "comtypes" not in sys.modules:
        sys.coinit_flags = 0   # COINIT_MULTITHREADED: read by comtypes when it initialises COM on import
        import comtypes
    else:
        import comtypes
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    return comtypes


def _interfaces(comtypes):
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown
    P = ctypes.POINTER

    class IActivateAudioInterfaceAsyncOperation(IUnknown):
        _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
        _methods_ = [COMMETHOD([], HRESULT, "GetActivateResult", (["out"], P(HRESULT), "hr"),
                               (["out"], P(P(IUnknown)), "iface"))]

    class IActivateAudioInterfaceCompletionHandler(IUnknown):
        _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
        _methods_ = [COMMETHOD([], HRESULT, "ActivateCompleted", (["in"], P(IActivateAudioInterfaceAsyncOperation), "op"))]

    class IAgileObject(IUnknown):
        _iid_ = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")
        _methods_ = []

    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [("wFormatTag", wt.WORD), ("nChannels", wt.WORD), ("nSamplesPerSec", wt.DWORD),
                    ("nAvgBytesPerSec", wt.DWORD), ("nBlockAlign", wt.WORD), ("wBitsPerSample", wt.WORD),
                    ("cbSize", wt.WORD)]

    class IAudioClient(IUnknown):
        _iid_ = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Initialize", (["in"], ctypes.c_int, "mode"), (["in"], wt.DWORD, "flags"),
                      (["in"], ctypes.c_longlong, "buffer"), (["in"], ctypes.c_longlong, "period"),
                      (["in"], P(WAVEFORMATEX), "fmt"), (["in"], ctypes.c_void_p, "session")),
            COMMETHOD([], HRESULT, "GetBufferSize", (["out"], P(ctypes.c_uint32), "n")),
            COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], P(ctypes.c_longlong), "t")),
            COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], P(ctypes.c_uint32), "n")),
            COMMETHOD([], HRESULT, "IsFormatSupported", (["in"], ctypes.c_int, "m"), (["in"], ctypes.c_void_p, "f"),
                      (["in"], ctypes.c_void_p, "c")),
            COMMETHOD([], HRESULT, "GetMixFormat", (["out"], P(ctypes.c_void_p), "f")),
            COMMETHOD([], HRESULT, "GetDevicePeriod", (["out"], P(ctypes.c_longlong), "d"), (["out"], P(ctypes.c_longlong), "m")),
            COMMETHOD([], HRESULT, "Start"),
            COMMETHOD([], HRESULT, "Stop"),
            COMMETHOD([], HRESULT, "Reset"),
            COMMETHOD([], HRESULT, "SetEventHandle", (["in"], wt.HANDLE, "h")),
            COMMETHOD([], HRESULT, "GetService", (["in"], P(GUID), "iid"), (["out"], P(P(IUnknown)), "ppv")),
        ]

    class IAudioCaptureClient(IUnknown):
        _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetBuffer", (["out"], P(ctypes.c_void_p), "data"), (["out"], P(ctypes.c_uint32), "frames"),
                      (["out"], P(wt.DWORD), "flags"), (["out"], P(ctypes.c_uint64), "pos"), (["out"], P(ctypes.c_uint64), "qpc")),
            COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], ctypes.c_uint32, "n")),
            COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], P(ctypes.c_uint32), "n")),
        ]

    class Handler(comtypes.COMObject):
        _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

        def __init__(self):
            super().__init__()
            self.done = threading.Event()

        def ActivateCompleted(self, op):
            self.done.set()
            return 0

    return IActivateAudioInterfaceAsyncOperation, IActivateAudioInterfaceCompletionHandler, WAVEFORMATEX, \
        IAudioClient, IAudioCaptureClient, Handler


class _LoopbackParams(ctypes.Structure):
    _fields_ = [("TargetProcessId", wt.DWORD), ("ProcessLoopbackMode", ctypes.c_int)]


class _ActivationParams(ctypes.Structure):
    _fields_ = [("ActivationType", ctypes.c_int), ("ProcessLoopbackParams", _LoopbackParams)]


class _Blob(ctypes.Structure):
    _fields_ = [("cbSize", wt.ULONG), ("pBlobData", ctypes.c_void_p)]


class _PropVariant(ctypes.Structure):
    _fields_ = [("vt", wt.USHORT), ("r1", wt.WORD), ("r2", wt.WORD), ("r3", wt.WORD), ("blob", _Blob)]


class ProcessLoopbackSource:
    """A hearing.Hearing source: windows of the game's stereo audio, captured on a daemon thread."""

    def __init__(self, exe=GAME_EXE, window_s=WINDOW_S, keep=64):
        self.exe, self.window = exe, int(RATE * window_s)
        self.available, self.reason = False, "starting"
        self.pid = None
        self._out = deque(maxlen=keep)   # (monotonic time at the window's end, left, right, rate)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        if sys.platform != "win32":
            self.reason = "process loopback capture is Windows-only"
            return
        threading.Thread(target=self._run, name="hearing-capture", daemon=True).start()

    def read(self):
        with self._lock:
            out = list(self._out)
            self._out.clear()
        return out

    def close(self):
        self._stop.set()

    def _run(self):
        try:
            import numpy  # noqa: F401  (the windows are numpy arrays)
            com = _com()
            ifaces = _interfaces(com)
        except Exception as e:   # no comtypes or numpy: say so, and stop
            self.available, self.reason = False, f"capture unavailable: {type(e).__name__}: {e}"
            return
        while not self._stop.is_set():
            pid = find_pid(self.exe)
            if not pid:
                self.available, self.reason, self.pid = False, f"{self.exe} is not running", None
                self._stop.wait(RETRY_S)
                continue
            try:
                self._capture(pid, ifaces)   # returns when the game exits or capture fails
                self.reason = f"capture of {self.exe} ({pid}) ended"
            except Exception as e:
                self.reason = f"capture of {self.exe} ({pid}) failed: {type(e).__name__}: {e}"
            self.available = False
            self._stop.wait(RETRY_S)

    def _capture(self, pid, ifaces):
        import numpy as np
        IOp, IHandler, WAVEFORMATEX, IAudioClient, IAudioCaptureClient, Handler = ifaces
        from comtypes import GUID, HRESULT
        act = ctypes.WinDLL("Mmdevapi").ActivateAudioInterfaceAsync
        act.restype = HRESULT
        act.argtypes = [wt.LPCWSTR, ctypes.POINTER(GUID), ctypes.POINTER(_PropVariant), ctypes.POINTER(IHandler),
                        ctypes.POINTER(ctypes.POINTER(IOp))]
        params = _ActivationParams(1, _LoopbackParams(pid, 0))   # PROCESS_LOOPBACK, include the process tree
        pv = _PropVariant()
        pv.vt = 65   # VT_BLOB
        pv.blob.cbSize = ctypes.sizeof(params)
        pv.blob.pBlobData = ctypes.cast(ctypes.pointer(params), ctypes.c_void_p)
        handler = Handler()
        op = ctypes.POINTER(IOp)()
        act("VAD\\Process_Loopback", ctypes.byref(IAudioClient._iid_), ctypes.byref(pv),
            handler.QueryInterface(IHandler), ctypes.byref(op))
        if not handler.done.wait(5):
            raise TimeoutError("audio activation did not complete")
        hr, unk = op.GetActivateResult()
        if hr != 0:
            raise OSError(f"audio activation failed 0x{hr & 0xFFFFFFFF:08x}")
        client = unk.QueryInterface(IAudioClient)
        fmt = WAVEFORMATEX(1, 2, RATE, RATE * 4, 4, 16, 0)   # PCM 16-bit stereo
        LOOPBACK, EVENTCALLBACK, AUTOCONVERT = 0x00020000, 0x00040000, 0x80000000
        client.Initialize(0, LOOPBACK | EVENTCALLBACK | AUTOCONVERT, 2_000_000, 0, ctypes.byref(fmt), None)
        k32 = ctypes.windll.kernel32
        event = k32.CreateEventW(None, False, False, None)
        client.SetEventHandle(event)
        cap = client.GetService(ctypes.byref(IAudioCaptureClient._iid_)).QueryInterface(IAudioCaptureClient)
        client.Start()
        self.pid, self.available, self.reason = pid, True, ""
        buf, have, last_check = np.zeros((self.window, 2), dtype=np.float32), 0, time.monotonic()
        try:
            while not self._stop.is_set():
                k32.WaitForSingleObject(event, 200)
                while cap.GetNextPacketSize() > 0:
                    data, frames, flags, _, _ = cap.GetBuffer()
                    if flags & 0x2:   # AUDCLNT_BUFFERFLAGS_SILENT
                        chunk = np.zeros((frames, 2), dtype=np.float32)
                    else:
                        raw = ctypes.string_at(data, frames * 4)
                        chunk = np.frombuffer(raw, dtype=np.int16).reshape(-1, 2).astype(np.float32) / 32768.0
                    cap.ReleaseBuffer(frames)
                    i = 0
                    while i < len(chunk):   # cut into whole windows
                        n = min(self.window - have, len(chunk) - i)
                        buf[have:have + n] = chunk[i:i + n]
                        have, i = have + n, i + n
                        if have == self.window:
                            with self._lock:
                                self._out.append((time.monotonic(), buf[:, 0].copy(), buf[:, 1].copy(), RATE))
                            have = 0
                if time.monotonic() - last_check > RETRY_S:   # the game may have closed: its stream just goes quiet
                    last_check = time.monotonic()
                    if find_pid(self.exe) != pid:
                        return
        finally:
            client.Stop()
            k32.CloseHandle(event)
