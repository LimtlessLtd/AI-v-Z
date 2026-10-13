"""Native call stacks of every thread of a process (Windows x64), for the game watcher's hang reports (backlog N17).

jcmd's thread dumps show Java frames only: a thread inside the game's audio library shows its last Java call, and a
thread the library started shows nothing at all. This walks each thread's native stack with Windows' own dbghelp
(the unwind data every x64 module carries; no symbol files) and names each frame module!nearest export+offset.
Each thread is suspended only while its stack is read (a few ms). A walk stops at the first Java frame, which has
no unwind data. Read-only: it changes nothing in the process.

Usage: python scripts/native_stacks.py <pid> [part of a thread's name or start module ...]
"""
import ctypes
import sys
from ctypes import wintypes

MAX_FRAMES = 48


class _M128(ctypes.Structure):
    _fields_ = [("lo", ctypes.c_uint64), ("hi", ctypes.c_uint64)]


class _CONTEXT(ctypes.Structure):  # AMD64 CONTEXT (winnt.h)
    _fields_ = [(f"P{i}Home", ctypes.c_uint64) for i in range(1, 7)] + [
        ("ContextFlags", wintypes.DWORD), ("MxCsr", wintypes.DWORD),
        ("SegCs", wintypes.WORD), ("SegDs", wintypes.WORD), ("SegEs", wintypes.WORD), ("SegFs", wintypes.WORD),
        ("SegGs", wintypes.WORD), ("SegSs", wintypes.WORD), ("EFlags", wintypes.DWORD),
    ] + [(f"Dr{i}", ctypes.c_uint64) for i in (0, 1, 2, 3, 6, 7)] + [
        (r, ctypes.c_uint64) for r in ("Rax", "Rcx", "Rdx", "Rbx", "Rsp", "Rbp", "Rsi", "Rdi",
                                       "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15", "Rip")
    ] + [("FltSave", ctypes.c_byte * 512), ("VectorRegister", _M128 * 26), ("VectorControl", ctypes.c_uint64),
         ("DebugControl", ctypes.c_uint64), ("LastBranchToRip", ctypes.c_uint64),
         ("LastBranchFromRip", ctypes.c_uint64), ("LastExceptionToRip", ctypes.c_uint64),
         ("LastExceptionFromRip", ctypes.c_uint64)]


class _ADDRESS64(ctypes.Structure):
    _fields_ = [("Offset", ctypes.c_uint64), ("Segment", wintypes.WORD), ("Mode", ctypes.c_int)]


class _STACKFRAME64(ctypes.Structure):  # KdHelp is padded: dbghelp writes less than this
    _fields_ = [("AddrPC", _ADDRESS64), ("AddrReturn", _ADDRESS64), ("AddrFrame", _ADDRESS64),
                ("AddrStack", _ADDRESS64), ("AddrBStore", _ADDRESS64), ("FuncTableEntry", ctypes.c_void_p),
                ("Params", ctypes.c_uint64 * 4), ("Far", wintypes.BOOL), ("Virtual", wintypes.BOOL),
                ("Reserved", ctypes.c_uint64 * 3), ("KdHelp", ctypes.c_byte * 512)]


class _SYMBOL_INFO(ctypes.Structure):
    _fields_ = [("SizeOfStruct", wintypes.ULONG), ("TypeIndex", wintypes.ULONG), ("Reserved", ctypes.c_uint64 * 2),
                ("Index", wintypes.ULONG), ("Size", wintypes.ULONG), ("ModBase", ctypes.c_uint64),
                ("Flags", wintypes.ULONG), ("Value", ctypes.c_uint64), ("Address", ctypes.c_uint64),
                ("Register", wintypes.ULONG), ("Scope", wintypes.ULONG), ("Tag", wintypes.ULONG),
                ("NameLen", wintypes.ULONG), ("MaxNameLen", wintypes.ULONG), ("Name", ctypes.c_char * 256)]


class _THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD), ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD)]


class _MODULEINFO(ctypes.Structure):
    _fields_ = [("base", ctypes.c_void_p), ("size", wintypes.DWORD), ("entry", ctypes.c_void_p)]


def stacks(pid, want=()):
    """[(thread id, name, start, cpu seconds, [frames])] for the process's threads (those matching want, if given)."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    dbghelp = ctypes.WinDLL("dbghelp", use_last_error=True)
    for f in (k32.OpenProcess, k32.OpenThread, k32.CreateToolhelp32Snapshot):
        f.restype = wintypes.HANDLE
    dbghelp.SymFunctionTableAccess64.restype = ctypes.c_void_p
    dbghelp.SymFunctionTableAccess64.argtypes = [wintypes.HANDLE, ctypes.c_uint64]
    dbghelp.SymGetModuleBase64.restype = ctypes.c_uint64
    dbghelp.SymGetModuleBase64.argtypes = [wintypes.HANDLE, ctypes.c_uint64]
    dbghelp.SymFromAddr.argtypes = [wintypes.HANDLE, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64),
                                    ctypes.POINTER(_SYMBOL_INFO)]
    dbghelp.StackWalk64.argtypes = [wintypes.DWORD, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(_STACKFRAME64),
                                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p]
    table_access = ctypes.WINFUNCTYPE(ctypes.c_void_p, wintypes.HANDLE, ctypes.c_uint64)(
        lambda h, a: dbghelp.SymFunctionTableAccess64(h, a))
    module_base = ctypes.WINFUNCTYPE(ctypes.c_uint64, wintypes.HANDLE, ctypes.c_uint64)(
        lambda h, a: dbghelp.SymGetModuleBase64(h, a))

    hp = wintypes.HANDLE(k32.OpenProcess(0x400 | 0x10, False, pid))  # QUERY_INFORMATION | VM_READ
    if not hp:
        raise OSError(f"can't open process {pid} (error {ctypes.get_last_error()})")
    # UNDNAME | DEFERRED_LOADS | FAIL_CRITICAL_ERRORS | NO_PROMPTS
    dbghelp.SymSetOptions(0x2 | 0x4 | 0x200 | 0x80000)
    if not dbghelp.SymInitializeW(hp, None, True):
        raise OSError(f"SymInitialize failed (error {ctypes.get_last_error()})")
    try:
        mods = (ctypes.c_void_p * 2048)()
        need = wintypes.DWORD()
        psapi.EnumProcessModulesEx(hp, mods, ctypes.sizeof(mods), ctypes.byref(need), 3)
        ranges = []
        for m in mods[: need.value // ctypes.sizeof(ctypes.c_void_p)]:
            if m:
                mi = _MODULEINFO()
                psapi.GetModuleInformation(hp, ctypes.c_void_p(m), ctypes.byref(mi), ctypes.sizeof(mi))
                name = ctypes.create_unicode_buffer(260)
                psapi.GetModuleBaseNameW(hp, ctypes.c_void_p(m), name, 260)
                ranges.append((m, m + mi.size, name.value))

        def where(a):
            mod = next(((lo, n) for lo, hi, n in ranges if lo <= a < hi), None)
            if not mod:
                return f"0x{a:x}"
            si = _SYMBOL_INFO()
            si.SizeOfStruct, si.MaxNameLen = 88, 255
            disp = ctypes.c_uint64()
            if dbghelp.SymFromAddr(hp, a, ctypes.byref(disp), ctypes.byref(si)) and disp.value < 0x10000:
                return f"{mod[1]}!{si.Name.decode(errors='replace')}+0x{disp.value:x}"
            return f"{mod[1]}+0x{a - mod[0]:x}"

        def walk(ht):
            ctx = _CONTEXT()
            ctx.ContextFlags = 0x10000B  # CONTEXT_FULL
            pcs = []
            if k32.SuspendThread(ht) == 0xFFFFFFFF:
                return ["(can't suspend)"]
            try:
                if not k32.GetThreadContext(ht, ctypes.byref(ctx)):
                    return [f"(no context, error {ctypes.get_last_error()})"]
                sf = _STACKFRAME64()
                sf.AddrPC.Offset, sf.AddrPC.Mode = ctx.Rip, 3  # AddrModeFlat
                sf.AddrFrame.Offset, sf.AddrFrame.Mode = ctx.Rbp, 3
                sf.AddrStack.Offset, sf.AddrStack.Mode = ctx.Rsp, 3
                while len(pcs) < MAX_FRAMES and dbghelp.StackWalk64(
                        0x8664, hp, ht, ctypes.byref(sf), ctypes.byref(ctx), None, table_access, module_base, None):
                    if not sf.AddrPC.Offset:
                        break
                    pcs.append(sf.AddrPC.Offset)
            finally:
                k32.ResumeThread(ht)
            return [where(a) for a in pcs]

        snap = wintypes.HANDLE(k32.CreateToolhelp32Snapshot(4, 0))  # TH32CS_SNAPTHREAD
        te = _THREADENTRY32()
        te.dwSize = ctypes.sizeof(te)
        tids = []
        me = k32.GetCurrentThreadId()  # never suspend the thread doing the walking
        ok = k32.Thread32First(snap, ctypes.byref(te))
        while ok:
            if te.th32OwnerProcessID == pid and te.th32ThreadID != me:
                tids.append(te.th32ThreadID)
            ok = k32.Thread32Next(snap, ctypes.byref(te))
        k32.CloseHandle(snap)

        out = []
        for tid in tids:
            # SUSPEND_RESUME | GET_CONTEXT | QUERY_INFORMATION | QUERY_LIMITED_INFORMATION
            ht = wintypes.HANDLE(k32.OpenThread(0x2 | 0x8 | 0x40 | 0x800, False, tid))
            if not ht:
                continue
            try:
                start = ctypes.c_void_p()
                ntdll.NtQueryInformationThread(ht, 9, ctypes.byref(start), 8, None)  # Win32StartAddress
                desc = ctypes.c_wchar_p()
                name = ""
                if k32.GetThreadDescription(ht, ctypes.byref(desc)) >= 0 and desc.value:
                    name = desc.value
                    k32.LocalFree(desc)
                times = [wintypes.FILETIME() for _ in range(4)]
                k32.GetThreadTimes(ht, *[ctypes.byref(t) for t in times])
                cpu = sum(t.dwHighDateTime << 32 | t.dwLowDateTime for t in times[2:]) / 1e7
                st = where(start.value or 0)
                if want and not any(w.lower() in f"{name} {st}".lower() for w in want):
                    continue
                out.append((tid, name, st, cpu, walk(ht)))
            finally:
                k32.CloseHandle(ht)
        return out
    finally:
        dbghelp.SymCleanup(hp)
        k32.CloseHandle(hp)


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[-1])
        return 2
    try:
        threads = stacks(int(argv[1]), argv[2:])
    except OSError as e:
        print(f"native stacks: {e}")
        return 1
    for tid, name, start, cpu, frames in sorted(threads, key=lambda t: -t[3]):
        print(f"thread {tid} '{name}' started at {start}, cpu {cpu:.1f} s")
        for f in frames or ["(no frames)"]:
            print("    " + f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
