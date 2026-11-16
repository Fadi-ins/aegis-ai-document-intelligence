"""Read one PDF on stdin and write bounded, page-numbered JSON on stdout."""
import json
import sys


def restrict_linux_worker():
    """Allow memory management and inherited pipe I/O after parser imports."""
    import ctypes
    import errno
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (384 << 20, 384 << 20))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    lib = ctypes.CDLL("libseccomp.so.2")
    pointer = ctypes.c_void_p
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = pointer
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_rule_add.argtypes = [pointer, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_load.argtypes = [pointer]
    lib.seccomp_release.argtypes = [pointer]
    deny = 0x00050000 | errno.EPERM
    allow = 0x7fff0000
    rules = lib.seccomp_init(deny)
    if not rules:
        raise RuntimeError("Unable to allocate parser filter")
    try:
        calls = ("read write close fstat lseek ioctl brk mmap mmap2 munmap mremap "
                 "mprotect madvise futex futex_time64 clock_gettime clock_gettime64 "
                 "gettimeofday getpid gettid getrandom sched_yield rt_sigaction "
                 "rt_sigprocmask rt_sigreturn sigaltstack exit exit_group")
        for name in calls.split():
            number = lib.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and lib.seccomp_rule_add(rules, allow, number, 0):
                raise RuntimeError("Unable to configure parser filter")
        if lib.seccomp_load(rules):
            raise RuntimeError("Unable to load parser filter")
    finally:
        lib.seccomp_release(rules)


def main():
    import codecs
    import io
    # PdfReader loads these modules lazily. Load trusted parser code before seccomp.
    from pypdf import PdfReader, filters, xmp

    # Load common PDF text codecs before closing filesystem access.
    for encoding in ("utf-16-be", "utf-16-le", "utf-8", "cp1252", "mac_roman",
                     "latin-1", "ascii", "charmap", "gb18030", "big5", "shift_jis"):
        codecs.lookup(encoding)
    if sys.platform.startswith("linux"):
        try:
            restrict_linux_worker()
        except (OSError, RuntimeError):
            return 5
    pdf = PdfReader(io.BytesIO(sys.stdin.buffer.read()), strict=True)
    if pdf.is_encrypted:
        return 2
    if not 1 <= len(pdf.pages) <= 100:
        return 3
    passages = []
    total = 0
    for page_number, page in enumerate(pdf.pages, 1):
        text = " ".join((page.extract_text() or "").replace("\x00", " ").split())
        total += len(text)
        if total > 320_000:
            return 3
        start = 0
        while start < len(text):
            end = min(start + 1100, len(text))
            if end < len(text):
                space = text.rfind(" ", start + 700, end)
                if space >= 0:
                    end = space
            passages.append([page_number, text[start:end]])
            if end == len(text):
                break
            start = end - 100
    if not passages:
        return 4
    json.dump({"pages": len(pdf.pages), "passages": passages}, sys.stdout)
    return 0


if __name__ == "__main__":
    try:
        result = main()
    except Exception:
        result = 1
    sys.exit(result)
