"""Kernel sandbox for user code (execution mode ``sandboxed``; Linux x86_64, no root required).

The worker passes a policy to every child in ``DD_SANDBOX_POLICY`` (JSON). The child calls
:func:`enter_from_env` at the point where untrusted code may start (the pipeline: after the inputs were
read and fingerprinted; check_child: before importing the check). Once entered, the restrictions are
irreversible for the process and every thread/descendant, and they apply to built-in code as well.

Layers (all must succeed, otherwise the child exits with code 71 before any user code runs):

1. ``PR_SET_NO_NEW_PRIVS`` - no setuid/file-capability gain.
2. Landlock (ABI >= 1, all rights of the running ABI are handled = default deny):
   * read-only: the Python runtime (stdlib, venv site-packages incl. the pinned core, dd_backend),
     ``/usr``, ``/lib*``, ``/etc/ld.so.cache``, ``/etc/localtime``, ``/dev/urandom``; plus the policy's ``ro``
     paths (this run's snapshot / mart / check file);
   * read-write (create/remove regular files and dirs, no symlinks/fifos/sockets/devices): only the
     policy's ``rw`` paths (this run's artifacts / work dir) and ``/dev/null``;
   * no EXECUTE right anywhere; no ``/proc``, ``/sys``, ``/home``, other runs, the DB, datasets, secrets;
   * ABI >= 4: TCP bind/connect handled with no allowed port = no TCP at all.
3. seccomp-bpf allowlist-by-exception (``EPERM``): ``socket``/``socketpair`` (no network or unix sockets
   of any family), ``execve``/``execveat`` (no shells/binaries), ``fork``/``vfork``/``clone`` without
   ``CLONE_THREAD`` and ``clone3`` (no child processes; threads allowed), ``kill``/``tgkill`` except to
   itself, ``tkill``/pidfd signalling, ``ptrace``/``process_vm_*``, namespaces/mount/chroot, ``bpf``,
   ``perf_event_open``, ``userfaultfd``, ``io_uring`` (bypasses seccomp), keyrings, module loading,
   ``personality`` etc. Foreign architectures and x32 syscalls kill the process.
4. rlimits on top of the supervisor's ones: CPU seconds, open files; no core dumps.

Residual limits (documented, not hidden): no PID/user namespace (AppArmor forbids unprivileged userns on
Ubuntu 24.04), so the code runs as the server uid - Landlock and seccomp are what separate it; disk usage
in the writable dirs is bounded per file (RLIMIT_FSIZE) and by time, not by a quota; CPU/memory are
bounded per execution by rlimits, not by a cgroup.
"""
from __future__ import annotations

import ctypes
import errno
import json
import os
import platform
import resource
import sys
from pathlib import Path

POLICY_ENV = "DD_SANDBOX_POLICY"
EXIT_SANDBOX_FAILED = 71

# ------------------------------------------------------------------ landlock
SYS_landlock_create_ruleset, SYS_landlock_add_rule, SYS_landlock_restrict_self = 444, 445, 446
LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_PATH_BENEATH, LANDLOCK_RULE_NET_PORT = 1, 2

FS_EXECUTE, FS_WRITE_FILE, FS_READ_FILE, FS_READ_DIR = 1 << 0, 1 << 1, 1 << 2, 1 << 3
FS_REMOVE_DIR, FS_REMOVE_FILE, FS_MAKE_CHAR, FS_MAKE_DIR = 1 << 4, 1 << 5, 1 << 6, 1 << 7
FS_MAKE_REG, FS_MAKE_SOCK, FS_MAKE_FIFO, FS_MAKE_BLOCK = 1 << 8, 1 << 9, 1 << 10, 1 << 11
FS_MAKE_SYM, FS_REFER, FS_TRUNCATE, FS_IOCTL_DEV = 1 << 12, 1 << 13, 1 << 14, 1 << 15
NET_BIND_TCP, NET_CONNECT_TCP = 1 << 0, 1 << 1

FS_BY_ABI = {1: (1 << 13) - 1, 2: (1 << 14) - 1, 3: (1 << 15) - 1, 4: (1 << 15) - 1}
FS_ALL_KNOWN = (1 << 16) - 1  # ABI >= 5 (IOCTL_DEV)
FILE_RIGHTS = FS_EXECUTE | FS_WRITE_FILE | FS_READ_FILE | FS_TRUNCATE | FS_IOCTL_DEV
RO = FS_READ_FILE | FS_READ_DIR
RW = RO | FS_WRITE_FILE | FS_TRUNCATE | FS_REMOVE_DIR | FS_REMOVE_FILE | FS_MAKE_DIR | FS_MAKE_REG

SYSTEM_RO = ("/usr", "/lib", "/lib64", "/etc/ld.so.cache", "/etc/localtime", "/dev/urandom", "/dev/zero")
# Single read-only FILES (never their directories) that native libraries (DuckDB) probe for CPU count and
# memory limits. /proc/self is resolved at enter() time, i.e. to this process' own pid - no other process.
SYSTEM_RO_FILES = ("/sys/devices/system/cpu/online", "/sys/devices/system/cpu/possible", "/proc/stat",
                   "/proc/meminfo", "/proc/sys/vm/overcommit_memory", "/proc/self/cgroup")
SYSTEM_RW = ("/dev/null",)


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64), ("handled_access_net", ctypes.c_uint64)]


class _PathBeneath(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


class _NetPort(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("port", ctypes.c_uint64)]


# ------------------------------------------------------------------- seccomp
PR_SET_NO_NEW_PRIVS, PR_SET_SECCOMP, SECCOMP_MODE_FILTER = 38, 22, 2
AUDIT_ARCH_X86_64 = 0xC000003E
X32_SYSCALL_BIT = 0x40000000
CLONE_THREAD = 0x00010000
RET_KILL_PROCESS, RET_ALLOW, RET_ERRNO = 0x80000000, 0x7FFF0000, 0x00050000
BPF_LD_W_ABS, BPF_JEQ_K, BPF_JGE_K, BPF_JSET_K, BPF_RET_K = 0x20, 0x15, 0x35, 0x45, 0x06

# x86_64 syscall numbers denied with EPERM.
DENY_X86_64 = {
    "socket": 41, "socketpair": 53, "fork": 57, "vfork": 58, "execve": 59, "execveat": 322,
    "ptrace": 101, "process_vm_readv": 310, "process_vm_writev": 311, "kcmp": 312,
    "tkill": 200, "pidfd_open": 434, "pidfd_send_signal": 424, "pidfd_getfd": 438,
    "rt_sigqueueinfo": 129, "rt_tgsigqueueinfo": 297,
    "mount": 165, "umount2": 166, "pivot_root": 155, "chroot": 161, "unshare": 272, "setns": 308,
    "open_tree": 428, "move_mount": 429, "fsopen": 430, "fsconfig": 431, "fsmount": 432, "fspick": 433,
    "mount_setattr": 442, "name_to_handle_at": 303, "open_by_handle_at": 304,
    "bpf": 321, "perf_event_open": 298, "userfaultfd": 323, "personality": 135,
    "io_uring_setup": 425, "io_uring_enter": 426, "io_uring_register": 427,
    "keyctl": 250, "add_key": 248, "request_key": 249,
    "init_module": 175, "finit_module": 313, "delete_module": 176, "kexec_load": 246, "kexec_file_load": 320,
    "reboot": 169, "swapon": 167, "swapoff": 168, "acct": 163, "quotactl": 179, "iopl": 172, "ioperm": 173,
    "syslog": 103, "vhangup": 153, "lookup_dcookie": 212, "settimeofday": 164, "clock_settime": 227,
    "adjtimex": 159, "clock_adjtime": 305, "sethostname": 170, "setdomainname": 171,
    "uselib": 134, "mbind": 237, "migrate_pages": 256, "move_pages": 279,
    "landlock_create_ruleset": 444, "landlock_add_rule": 445, "landlock_restrict_self": 446,
}
NR_CLONE, NR_CLONE3, NR_KILL, NR_TGKILL = 56, 435, 62, 234


class SandboxError(RuntimeError):
    pass


def _libc():
    return ctypes.CDLL(None, use_errno=True)


def landlock_abi() -> int:
    """Running kernel's Landlock ABI version; 0 when unavailable/disabled."""
    libc = _libc()
    libc.syscall.restype = ctypes.c_long
    v = libc.syscall(ctypes.c_long(SYS_landlock_create_ruleset), None, ctypes.c_size_t(0),
                     ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION))
    return int(v) if v > 0 else 0


def supported() -> tuple[bool, str]:
    if sys.platform != "linux":
        return False, "sandboxed mode requires Linux"
    if platform.machine() != "x86_64":
        return False, f"sandboxed mode seccomp filter is defined for x86_64 only (got {platform.machine()})"
    abi = landlock_abi()
    if abi < 1:
        return False, "Landlock LSM is not enabled in this kernel (add 'landlock' to lsm=)"
    return True, f"landlock ABI {abi}, seccomp x86_64"


def runtime_read_paths() -> list[str]:
    """Directories the Python runtime needs to import modules lazily (no cwd, no '' entries)."""
    paths = {sys.prefix, sys.base_prefix, sys.exec_prefix, str(Path(__file__).resolve().parent)}
    for p in sys.path:
        if p and os.path.isabs(p) and os.path.exists(p):
            paths.add(p)
    return sorted(paths)


def _own_cgroup_limit_files() -> list[str]:
    """memory.max / cpu.max of this process' own cgroup v2 (DuckDB sizes its memory/threads from them)."""
    try:
        line = next(l for l in Path("/proc/self/cgroup").read_text().splitlines() if l.startswith("0::"))
    except (OSError, StopIteration):
        return []
    base = Path("/sys/fs/cgroup") / line[3:].lstrip("/")
    return [str(base / f) for f in ("memory.max", "memory.high", "cpu.max") if (base / f).is_file()]


def _covers(parent: str, child: str) -> bool:
    try:
        return os.path.commonpath([os.path.realpath(parent), os.path.realpath(child)]) == os.path.realpath(parent)
    except ValueError:
        return False


# --------------------------------------------------------------- enforcement
def _apply_landlock(ro: list[str], rw: list[str], deny_under: list[str]) -> int:
    abi = landlock_abi()
    if abi < 1:
        raise SandboxError("Landlock unavailable")
    libc = _libc()
    libc.syscall.restype = ctypes.c_long
    handled_fs = FS_BY_ABI.get(abi, FS_ALL_KNOWN)
    attr = _RulesetAttr(handled_fs, (NET_BIND_TCP | NET_CONNECT_TCP) if abi >= 4 else 0)
    size = ctypes.sizeof(_RulesetAttr) if abi >= 4 else 8
    ruleset = libc.syscall(ctypes.c_long(SYS_landlock_create_ruleset), ctypes.byref(attr), ctypes.c_size_t(size),
                           ctypes.c_uint32(0))
    if ruleset < 0:
        raise SandboxError(f"landlock_create_ruleset: {os.strerror(ctypes.get_errno())}")
    try:
        def add(path: str, access: int) -> None:
            try:
                fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            except FileNotFoundError:
                return
            try:
                is_dir = os.path.isdir(path)
                rule = _PathBeneath((access if is_dir else access & FILE_RIGHTS) & handled_fs, fd)
                if libc.syscall(ctypes.c_long(SYS_landlock_add_rule), ctypes.c_int(ruleset),
                                ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH), ctypes.byref(rule), ctypes.c_uint32(0)) < 0:
                    raise SandboxError(f"landlock_add_rule({path}): {os.strerror(ctypes.get_errno())}")
            finally:
                os.close(fd)

        for p in [*SYSTEM_RO, *runtime_read_paths()]:
            # A runtime directory that contains server state (DB, runs, datasets) is never granted.
            if any(_covers(p, d) for d in deny_under):
                continue
            add(p, RO)
        for p in SYSTEM_RO_FILES:
            if os.path.isfile(p):
                add(p, FS_READ_FILE)
        for p in _own_cgroup_limit_files():
            add(p, FS_READ_FILE)
        for p in ro:
            add(p, RO)
        for p in [*SYSTEM_RW, *rw]:
            add(p, RW)
        if libc.syscall(ctypes.c_long(SYS_landlock_restrict_self), ctypes.c_int(ruleset), ctypes.c_uint32(0)) < 0:
            raise SandboxError(f"landlock_restrict_self: {os.strerror(ctypes.get_errno())}")
    finally:
        os.close(ruleset)
    return abi


class _SockFilter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8), ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32)]


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_uint16), ("filter", ctypes.POINTER(_SockFilter))]


def build_filter(pid: int) -> list[tuple[int, object, object, int]]:
    """BPF program as (code, jt, jf, k); jt/jf may be label names resolved by :func:`_assemble`."""
    off_nr, off_arch, off_arg0 = 0, 4, 16
    eperm = RET_ERRNO | errno.EPERM
    prog: list = [
        (BPF_LD_W_ABS, 0, 0, off_arch),
        (BPF_JEQ_K, 0, "kill", AUDIT_ARCH_X86_64),
        (BPF_LD_W_ABS, 0, 0, off_nr),
        (BPF_JGE_K, "kill", 0, X32_SYSCALL_BIT),
    ]
    for nr in sorted(set(DENY_X86_64.values())):
        prog.append((BPF_JEQ_K, "eperm", 0, nr))
    prog += [
        (BPF_JEQ_K, "enosys", 0, NR_CLONE3),  # glibc falls back to clone(), whose flags we can inspect
        (BPF_JEQ_K, "clone", 0, NR_CLONE),
        (BPF_JEQ_K, "selfpid", 0, NR_KILL),
        (BPF_JEQ_K, "selfpid", 0, NR_TGKILL),
        (BPF_RET_K, 0, 0, RET_ALLOW),
        ("label", "clone"), (BPF_LD_W_ABS, 0, 0, off_arg0),
        (BPF_JSET_K, "allow", "eperm", CLONE_THREAD),
        ("label", "selfpid"), (BPF_LD_W_ABS, 0, 0, off_arg0),
        (BPF_JEQ_K, "allow", "eperm", pid),
        ("label", "eperm"), (BPF_RET_K, 0, 0, eperm),
        ("label", "enosys"), (BPF_RET_K, 0, 0, RET_ERRNO | errno.ENOSYS),
        ("label", "kill"), (BPF_RET_K, 0, 0, RET_KILL_PROCESS),
        ("label", "allow"), (BPF_RET_K, 0, 0, RET_ALLOW),  # classic BPF jumps forward only
    ]
    return prog


def _assemble(prog: list) -> list[tuple[int, int, int, int]]:
    labels, out = {}, []
    for ins in prog:
        if ins[0] == "label":
            labels[ins[1]] = len(out)
        else:
            out.append(ins)

    def rel(target, i):
        if isinstance(target, int):
            return target
        d = labels[target] - i - 1
        if not 0 <= d <= 255:
            raise SandboxError(f"BPF jump to {target} out of range ({d})")
        return d
    return [(c, rel(jt, i), rel(jf, i), k) for i, (c, jt, jf, k) in enumerate(out)]


def _apply_seccomp() -> None:
    code = _assemble(build_filter(os.getpid()))
    arr = (_SockFilter * len(code))(*[_SockFilter(c, jt, jf, k) for c, jt, jf, k in code])
    prog = _SockFprog(len(code), arr)
    libc = _libc()
    if libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.byref(prog), 0, 0) != 0:
        raise SandboxError(f"seccomp filter: {os.strerror(ctypes.get_errno())}")


def enter(policy: dict) -> dict:
    """Apply the whole sandbox to the current process (irreversible). Raises SandboxError."""
    ok, why = supported()
    if not ok:
        raise SandboxError(why)
    cpu = int(policy.get("cpu_seconds") or 0)
    if cpu > 0:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5))
    nofile = int(policy.get("max_open_files") or 256)
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    limit = nofile if hard == resource.RLIM_INFINITY else min(nofile, hard)
    resource.setrlimit(resource.RLIMIT_NOFILE, (limit, limit))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    libc = _libc()
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise SandboxError(f"no_new_privs: {os.strerror(ctypes.get_errno())}")
    abi = _apply_landlock(list(policy.get("ro", [])), list(policy.get("rw", [])), list(policy.get("deny_under", [])))
    _apply_seccomp()
    return {"landlock_abi": abi, "seccomp": True}


def enter_from_env() -> bool:
    """Enter the sandbox if the worker requested it. On failure the process exits (fail closed)."""
    raw = os.environ.pop(POLICY_ENV, None)
    if raw is None:
        return False
    try:
        enter(json.loads(raw))
    except Exception as exc:  # never run user code unconfined when confinement was requested
        print(f"SANDBOX_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        os._exit(EXIT_SANDBOX_FAILED)
    return True


def policy_env(*, ro: list[Path], rw: list[Path], deny_under: list[Path], cpu_seconds: int,
               max_open_files: int) -> str:
    return json.dumps({"ro": [str(p) for p in ro], "rw": [str(p) for p in rw],
                       "deny_under": [str(p) for p in deny_under], "cpu_seconds": cpu_seconds,
                       "max_open_files": max_open_files})


# ------------------------------------------------------------------ self-test
_PROBES = r"""
import json, os, socket, subprocess, sys
from pathlib import Path
from dd_backend import sandbox
work, secret = Path(sys.argv[1]), Path(sys.argv[2])
sandbox.enter({"ro": [], "rw": [str(work)], "deny_under": [str(secret.parent)], "cpu_seconds": 30})
res = {}
def probe(name, fn):
    try:
        fn(); res[name] = "allowed"
    except Exception as e:
        res[name] = "denied:" + type(e).__name__
probe("write_work", lambda: (work / "ok.txt").write_text("x"))
probe("read_secret", lambda: secret.read_text())
probe("write_outside", lambda: (secret.parent / "planted.txt").write_text("x"))
probe("read_proc_environ", lambda: Path(f"/proc/{os.getppid()}/environ").read_bytes())
probe("read_etc_passwd", lambda: Path("/etc/passwd").read_text())
probe("symlink", lambda: os.symlink("/etc/passwd", work / "l"))
probe("tcp_connect", lambda: socket.create_connection(("127.0.0.1", 9), timeout=1))
probe("udp_socket", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
probe("unix_socket", lambda: socket.socket(socket.AF_UNIX, socket.SOCK_STREAM))
probe("exec", lambda: subprocess.run(["/bin/true"], check=True))
probe("fork", lambda: os.fork() == 0 and os._exit(0))
probe("signal_parent", lambda: os.kill(os.getppid(), 0))
probe("thread", lambda: __import__("threading").Thread(target=lambda: None).start())
probe("import_stdlib", lambda: __import__("decimal"))
probe("import_core", lambda: __import__("decision_diff.core"))
print(json.dumps(res))
"""
EXPECT_ALLOWED = {"write_work", "thread", "import_stdlib", "import_core"}


def selftest(scratch: Path) -> dict:
    """Run the probes in a fresh interpreter; ok only if every escape is denied and normal work allowed."""
    import subprocess
    import tempfile
    ok, why = supported()
    if not ok:
        return {"ok": False, "reason": why}
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as tmp:
        work, outside = Path(tmp, "work"), Path(tmp, "outside")
        work.mkdir()
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("secret")
        proc = subprocess.run([sys.executable, "-I", "-c", _PROBES, str(work), str(secret)],
                              capture_output=True, text=True, timeout=60,
                              env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(work)})
        try:
            res = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {"ok": False, "reason": f"probe failed (exit {proc.returncode}): {proc.stderr[-300:]}"}
        bad = sorted(k for k, v in res.items() if (k in EXPECT_ALLOWED) != (v == "allowed"))
        planted = (outside / "planted.txt").exists()
        return {"ok": not bad and not planted, "detail": why, "probes": res,
                **({"unexpected": bad} if bad else {})}


_STARTUP: dict | None = None


def require_working(scratch: Path) -> dict:
    """Startup gate for sandboxed mode: run the self-test once; refuse to start when it fails."""
    global _STARTUP
    _STARTUP = selftest(scratch)
    if not _STARTUP["ok"]:
        raise SandboxError("sandboxed execution mode requested but the kernel sandbox self-test failed: "
                           + json.dumps({k: v for k, v in _STARTUP.items() if k != "probes"}))
    return _STARTUP


def startup_result() -> dict | None:
    return _STARTUP


if __name__ == "__main__":
    import tempfile
    print(json.dumps(selftest(Path(tempfile.gettempdir())), indent=2))
