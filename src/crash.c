// crash.c — fatal-exception report (TASK 34).
//
// The owner's real playtest lost three sessions to silent crashes: the guest log ended mid-line with no
// error, so nothing said where the game died. This installs a first-chance vectored handler and an
// unhandled-exception filter that write one report for a fatal code: the code, the faulting address as
// module+offset, the general registers, a short stack walk and the last 64 formatted log lines (the ring
// logf feeds, i.e. the sync/net/scene events just before the crash). It only logs; it never handles or
// continues an exception, so the game's and the debugger's behaviour is unchanged.
//
// Nothing here allocates or uses the stdio layer: the process is already dying, a second fault just ends
// it. The log handle is the mod's own append handle, and logf flushes every line.

#define CRASH_LOG_RING 64
#define CRASH_LOG_LINE 256
static char g_logring[CRASH_LOG_RING][CRASH_LOG_LINE];
static volatile LONG g_logring_n;

static volatile LONG g_crash_reported;
static DWORD g_crash_code, g_crash_addr;

// TASK 49: the report is written by this thread, not by the faulting one, and the MINIMAL line is
// written before anything is formatted. A stack overflow (0xc00000fd) leaves the faulting thread without
// room for crash_report's ~1 KB of locals, and a second fault inside the handler used to end the process
// with no line at all - the owner's 2.0 playtest guest log ends with no report. The context is copied to
// these statics (a CONTEXT is ~700 bytes, too big for a stack-overflowed thread's leftovers), the minimal
// line goes straight to the log from a preformatted static buffer, and the rest runs on g_crash_thread
// with its own 256 KB stack.
static CONTEXT g_crash_ctx;
static DWORD g_crash_info0, g_crash_info1;
static const char *g_crash_how;
static HANDLE g_crash_go, g_crash_done, g_crash_thread;
static char g_crash_min[192];
static int g_crash_min_code, g_crash_min_addr;

static const char *crash_name(DWORD code)
{
	switch (code) {
	case 0xc0000005: return "access violation";
	case 0xc0000006: return "in-page error";
	case 0xc0000008: return "invalid handle";
	case 0xc000001d: return "illegal instruction";
	case 0xc0000025: return "noncontinuable exception";
	case 0xc0000026: return "invalid disposition";
	case 0xc000008c: return "array bounds exceeded";
	case 0xc000008d: return "float denormal operand";
	case 0xc000008e: return "float divide by zero";
	case 0xc000008f: return "float inexact result";
	case 0xc0000090: return "float invalid operation";
	case 0xc0000091: return "float overflow";
	case 0xc0000092: return "float stack check";
	case 0xc0000093: return "float underflow";
	case 0xc0000094: return "integer divide by zero";
	case 0xc0000095: return "integer overflow";
	case 0xc0000096: return "privileged instruction";
	case 0xc00000fd: return "stack overflow";
	case 0xc0000135: return "dll not found";
	case 0xc0000139: return "entry point not found";
	case 0xc0000142: return "dll init failed";
	default: return "exception";
	}
}

// A fatal code is one the game cannot continue from. Breakpoints, single steps and guard pages are not.
static int crash_fatal(DWORD code)
{
	switch (code) {
	case 0xc0000005: case 0xc0000006: case 0xc0000008: case 0xc000001d:
	case 0xc0000025: case 0xc0000026: case 0xc000008c: case 0xc000008e:
	case 0xc0000090: case 0xc0000094: case 0xc0000096: case 0xc00000fd:
	case 0xc0000374:   // TASK 49: heap corruption - a code the process cannot continue from
	case 0xc0000409:   // TASK 49: stack buffer overrun (/GS) - when it is raised instead of a __fastfail
		return 1;
	}
	return 0;
}

// Writes straight to the mod's log handle (no CRT, no locks: the crashing thread may hold the log lock).
static void crash_write(const char *s, int n)
{
	DWORD w;
	if (g_log != INVALID_HANDLE_VALUE && n > 0)
		WriteFile(g_log, s, (DWORD)n, &w, NULL);
}

static void crash_line(const char *s)
{
	crash_write(s, (int)strlen(s));
}

// "name+0xoffset (base 0x...)" for an address inside a mapped module, else the raw address.
static void crash_where(DWORD addr, char *out, size_t outsz)
{
	MEMORY_BASIC_INFORMATION mbi;
	char path[MAX_PATH];
	DWORD base = 0;
	path[0] = 0;
	if (VirtualQuery((const void *)(uintptr_t)addr, &mbi, sizeof mbi)) {
		base = (DWORD)(uintptr_t)mbi.AllocationBase;
		if (base && !GetModuleFileNameA((HMODULE)(uintptr_t)base, path, sizeof path))
			path[0] = 0;
	}
	if (base && path[0]) {
		const char *name = strrchr(path, '\\');
		name = name ? name + 1 : path;
		_snprintf(out, outsz, "%s+0x%lx (base 0x%lx, image 0x%lx)", name, (unsigned long)(addr - base),
			(unsigned long)base, (unsigned long)virt_exe_base());
	} else {
		_snprintf(out, outsz, "0x%lx (not in a module)", (unsigned long)addr);
	}
	out[outsz - 1] = 0;
}

static void crash_report_body(void)
{
	CONTEXT *c = &g_crash_ctx;
	DWORD code = g_crash_code, addr = g_crash_addr;
	const char *how = g_crash_how;
	DWORD info0 = g_crash_info0, info1 = g_crash_info1;
	char line[512], where[300];
	_snprintf(line, sizeof line, "\r\n*** obscoop: FATAL EXCEPTION %s (0x%08lx) on the %s path\r\n",
		crash_name(code), (unsigned long)code, how);
	crash_line(line);
	crash_where(addr, where, sizeof where);
	_snprintf(line, sizeof line, "*** fault at %s  params %08lx %08lx\r\n", where, (unsigned long)info0,
		(unsigned long)info1);
	crash_line(line);
	crash_where(c->Eip, where, sizeof where);
	_snprintf(line, sizeof line,
		"*** eip %s\r\n*** eax %08lx ebx %08lx ecx %08lx edx %08lx esi %08lx edi %08lx ebp %08lx esp %08lx efl %08lx\r\n",
		where, (unsigned long)c->Eax, (unsigned long)c->Ebx, (unsigned long)c->Ecx, (unsigned long)c->Edx,
		(unsigned long)c->Esi, (unsigned long)c->Edi, (unsigned long)c->Ebp, (unsigned long)c->Esp,
		(unsigned long)c->EFlags);
	crash_line(line);
	// Stack walk: the EBP chain while it is readable and monotonic, then a raw scan of the stack for
	// return addresses that fall inside the exe image (the chain is unreliable after a stack overrun).
	crash_line("*** stack (ebp chain, then image addresses found on the stack):\r\n");
	DWORD ebp = c->Ebp, prev = 0, esp = c->Esp;
	int n = 0;
	while (ebp && ebp != prev && n < 16) {
		MEMORY_BASIC_INFORMATION mbi;
		if (!VirtualQuery((const void *)(uintptr_t)ebp, &mbi, sizeof mbi) || (mbi.Protect & 0x101) ||
		    mbi.State != MEM_COMMIT)
			break;
		DWORD next = *(DWORD *)(uintptr_t)ebp;
		DWORD ret = *(DWORD *)(uintptr_t)(ebp + 4);
		crash_where(ret, where, sizeof where);
		_snprintf(line, sizeof line, "***   [ebp+4] %s\r\n", where);
		crash_line(line);
		prev = ebp;
		ebp = next;
		n++;
	}
	DWORD base = virt_exe_base(), size = virt_exe_size();
	int seen = 0;
	for (DWORD p = esp; p < esp + 0x400 && seen < 16; p += 4) {
		MEMORY_BASIC_INFORMATION mbi;
		if (!VirtualQuery((const void *)(uintptr_t)p, &mbi, sizeof mbi) || mbi.State != MEM_COMMIT)
			break;
		DWORD v;
		memcpy(&v, (const void *)(uintptr_t)p, 4);
		if (base && v >= base && v < base + size) {
			crash_where(v, where, sizeof where);
			_snprintf(line, sizeof line, "***   [esp+0x%lx] %s\r\n", (unsigned long)(p - esp), where);
			crash_line(line);
			seen++;
		}
	}
	crash_line("*** last sync/net log lines:\r\n");
	LONG total = g_logring_n;
	int have = total < CRASH_LOG_RING ? (int)total : CRASH_LOG_RING;
	for (int i = have; i > 0; i--) {
		int idx = (int)((total - i) % CRASH_LOG_RING);
		crash_write("***   ", 6);
		crash_write(g_logring[idx], (int)strlen(g_logring[idx]));
		crash_write("\r\n", 2);
	}
	crash_line("*** end of the crash report\r\n");
	FlushFileBuffers(g_log);
}

// The writer thread: waits for a report request and writes the full one on its own stack, so a fault on
// the faulting thread's stack (or in here) still leaves the minimal line already on disk.
static DWORD WINAPI crash_thread_main(LPVOID unused)
{
	(void)unused;
	WaitForSingleObject(g_crash_go, INFINITE);
	crash_report_body();
	if (g_crash_done)
		SetEvent(g_crash_done);
	return 0;
}

// Writes the two 8-digit hex fields of the preformatted minimal line in place: no formatting, no stack.
static void crash_patch_hex(char *p, DWORD v)
{
	static const char hexd[] = "0123456789abcdef";
	for (int i = 7; i >= 0; i--) {
		p[i] = hexd[v & 0xf];
		v >>= 4;
	}
}

// Entry point of the handlers: the MINIMAL line first (already on disk and flushed before anything else
// can fail), then the full report on the writer thread. If the thread could not be created, the rest runs
// here as before (TASK 34 behaviour).
static void crash_report(CONTEXT *c, DWORD code, DWORD addr, const char *how, DWORD info0, DWORD info1)
{
	if (InterlockedExchange(&g_crash_reported, 1))
		return;
	g_crash_code = code;
	g_crash_addr = addr;
	g_crash_how = how;
	g_crash_info0 = info0;
	g_crash_info1 = info1;
	if (g_log != INVALID_HANDLE_VALUE) {
		DWORD w;
		if (g_crash_min[0]) {
			crash_patch_hex(g_crash_min + g_crash_min_code, code);
			crash_patch_hex(g_crash_min + g_crash_min_addr, addr);
			WriteFile(g_log, g_crash_min, (DWORD)strlen(g_crash_min), &w, NULL);
			FlushFileBuffers(g_log);
		} else {
			static const char fallback[] = "\r\n*** obscoop: FATAL EXCEPTION (minimal line, full report follows)\r\n";
			WriteFile(g_log, fallback, (DWORD)(sizeof fallback - 1), &w, NULL);
			FlushFileBuffers(g_log);
		}
	}
	if (c && c != &g_crash_ctx)
		g_crash_ctx = *c;
	if (g_crash_thread && g_crash_go && g_crash_done) {
		SetEvent(g_crash_go);
		WaitForSingleObject(g_crash_done, 5000);
	} else {
		crash_report_body();
	}
}

// 1 when the address lies in KERNEL32/KERNELBASE. IsBadReadPtr/IsBadWritePtr probe memory under SEH: every
// probe of an invalid page raises a first-chance access violation inside KERNEL32 that the API itself
// swallows. Those are not crashes (the mod probes pointers constantly), so the vectored handler ignores
// them; an unhandled one still reaches the filter below and is reported there.
static int crash_in_kernel(DWORD addr)
{
	MEMORY_BASIC_INFORMATION mbi;
	char path[MAX_PATH], *name;
	if (!VirtualQuery((const void *)(uintptr_t)addr, &mbi, sizeof mbi) || !mbi.AllocationBase)
		return 0;
	if (!GetModuleFileNameA((HMODULE)mbi.AllocationBase, path, sizeof path))
		return 0;
	name = strrchr(path, '\\');
	name = name ? name + 1 : path;
	return _strnicmp(name, "kernel32", 8) == 0 || _strnicmp(name, "kernelbase", 10) == 0 ||
	       _strnicmp(name, "ntdll", 5) == 0;
}

// Logs a fatal first-chance exception. It is only a log: the search continues, so a handler of the game's
// own still gets it (and an unhandled one reaches SetUnhandledExceptionFilter below).
static LONG CALLBACK crash_veh(EXCEPTION_POINTERS *e)
{
	DWORD code = e->ExceptionRecord->ExceptionCode;
	if (crash_fatal(code) && !g_crash_reported &&
	    !crash_in_kernel((DWORD)(uintptr_t)e->ExceptionRecord->ExceptionAddress))
		crash_report(e->ContextRecord, code, (DWORD)(uintptr_t)e->ExceptionRecord->ExceptionAddress,
			"vectored", e->ExceptionRecord->NumberParameters > 0 ? (DWORD)e->ExceptionRecord->ExceptionInformation[0] : 0,
			e->ExceptionRecord->NumberParameters > 1 ? (DWORD)e->ExceptionRecord->ExceptionInformation[1] : 0);
	return EXCEPTION_CONTINUE_SEARCH;
}

static LONG WINAPI crash_filter(EXCEPTION_POINTERS *e)
{
	DWORD code = e->ExceptionRecord->ExceptionCode;
	if (crash_fatal(code) && !g_crash_reported)
		crash_report(e->ContextRecord, code, (DWORD)(uintptr_t)e->ExceptionRecord->ExceptionAddress,
			"unhandled", e->ExceptionRecord->NumberParameters > 0 ? (DWORD)e->ExceptionRecord->ExceptionInformation[0] : 0,
			e->ExceptionRecord->NumberParameters > 1 ? (DWORD)e->ExceptionRecord->ExceptionInformation[1] : 0);
	else if (!g_crash_reported) {
		// A code outside the fatal list still ends the process when unhandled: record it too.
		crash_report(e->ContextRecord, code, (DWORD)(uintptr_t)e->ExceptionRecord->ExceptionAddress,
			"unhandled-other", 0, 0);
	}
	return EXCEPTION_CONTINUE_SEARCH;
}

static PVOID g_crash_veh_handle;
static void crash_install(void)
{
	if (!g_crash_veh_handle)
		g_crash_veh_handle = AddVectoredExceptionHandler(1, crash_veh);
	SetUnhandledExceptionFilter(crash_filter);
	// TASK 49: the minimal line is formatted ONCE here (no formatting at crash time); the writer thread
	// gets its own 256 KB stack so a stack overflow still produces the full report.
	if (g_log != INVALID_HANDLE_VALUE) {
		int n = _snprintf(g_crash_min, sizeof g_crash_min,
			"\r\n*** obscoop: FATAL EXCEPTION code 0x00000000 at 0x00000000 (minimal line; full report follows)\r\n");
		if (n > 0) {
			char *pc = strstr(g_crash_min, "code 0x"), *pa = strstr(g_crash_min, "at 0x");
			if (pc && pa) {
				g_crash_min_code = (int)(pc - g_crash_min) + 7;
				g_crash_min_addr = (int)(pa - g_crash_min) + 5;
			}
		}
	}
	g_crash_go = CreateEventA(NULL, TRUE, FALSE, NULL);
	g_crash_done = CreateEventA(NULL, TRUE, FALSE, NULL);
	g_crash_thread = CreateThread(NULL, 256 * 1024, crash_thread_main, NULL, 0, NULL);
	logf("crash handler installed (vectored first chance + unhandled filter, %d log lines kept, report thread %s)",
		CRASH_LOG_RING, g_crash_thread ? "ready" : "UNAVAILABLE");
}
