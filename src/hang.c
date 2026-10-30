// hang.c — TASK 35: the game thread that stops presenting frames.
//
// TASK 34's crash handler proved a silent *crash*; the owner's real playtest also froze with a static
// image and the process alive, which is the other shape: the game thread stops running its frame loop
// (no more Present -> no new image, no more logf from any gameplay path) while the UDP thread and the
// command pipe keep answering. `sync` already prints `frames` (sync.c:4921) - a frozen count with a
// live pipe is the hang.
//
// This thread samples that counter. When it has not moved for HANG_STALL_MS it suspends the game
// thread, reads its CONTEXT and prints EIP/ESP/EBP as module+offset plus a stack scan in the same format
// as crash.c, then resumes it. The report is repeated every HANG_REPEAT_MS while the thread stays
// stuck, so a long hang shows the thread's position each time. Everything is written straight to the
// log handle with WriteFile (crash_write), never through logf: the stuck thread may hold the log lock.
//
// Included from obscoop2.c before sync.c; frame_tick() calls hang_note_frame() and hang_phase().

#define HANG_STALL_MS 3000
#define HANG_REPEAT_MS 5000
// TASK 38: a level load stops the frame loop for seconds and is not a stall. While the game is loading
// (no world yet / not in a level / a load or ChangeLevel request pending) the frame counter standing
// still is expected; it is only reported if it has not moved for this long, which no normal load reaches.
#define HANG_LOAD_MAX_MS 30000
#define HANG_STACK_SCAN 0x400
#define HANG_EBP_FRAMES 16

static HANDLE g_hang_thread;              // the game thread (the one that presents frames)
static DWORD g_hang_tid;
static volatile LONG g_hang_frames;       // game-thread heartbeats (incremented in frame_tick)
static const char *volatile g_hang_phase = "no frame yet";
static volatile LONG g_hang_reports;

// Called first thing in frame_tick, on the game thread: the heartbeat and, once, the thread handle.
static void hang_note_frame(void)
{
	InterlockedIncrement(&g_hang_frames);
	if (!g_hang_tid) {
		DWORD tid = GetCurrentThreadId();
		HANDLE h = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, tid);
		if (h) {
			g_hang_thread = h;
			g_hang_tid = tid;
		}
	}
}

// Called by frame_tick around each step of the mod's own work, so a stall report names the step the game
// thread was in (a string literal; never freed).
static void hang_phase(const char *name)
{
	g_hang_phase = name;
}

// The report for one sample of the stuck thread. The context and the stack are copied while the thread is
// suspended; the formatting (which can touch the loader lock through GetModuleFileNameA) runs after the
// resume, so a game thread stuck inside the loader can never deadlock this thread.
static void hang_report(DWORD stuck_ms, LONG frames)
{
	char line[512], where[300];
	char stack[48][300];
	int nstack = 0;
	DWORD esp = 0, ebp = 0, eip = 0;
	DWORD regs[8] = { 0, 0, 0, 0, 0, 0, 0, 0 };   // eax ebx ecx edx esi edi ebp esp
	int suspended = -1;
	CONTEXT c;
	memset(&c, 0, sizeof c);
	if (g_hang_thread) {
		suspended = (int)SuspendThread(g_hang_thread);
		if (suspended >= 0) {
			c.ContextFlags = CONTEXT_FULL;
			if (GetThreadContext(g_hang_thread, &c)) {
				esp = c.Esp; ebp = c.Ebp; eip = c.Eip;
				regs[0] = c.Eax; regs[1] = c.Ebx; regs[2] = c.Ecx; regs[3] = c.Edx;
				regs[4] = c.Esi; regs[5] = c.Edi; regs[6] = c.Ebp; regs[7] = c.Esp;
				// EBP chain, then a raw scan of the stack for return addresses inside the exe image.
				DWORD b = virt_exe_base(), sz = virt_exe_size();
				DWORD p = ebp, prev = 0;
				for (int i = 0; i < HANG_EBP_FRAMES && p && p != prev && nstack < 40; i++) {
					MEMORY_BASIC_INFORMATION mbi;
					if (!VirtualQuery((const void *)(uintptr_t)p, &mbi, sizeof mbi) || mbi.State != MEM_COMMIT ||
					    (mbi.Protect & PAGE_NOACCESS) || (mbi.Protect & PAGE_GUARD))
						break;
					DWORD next, ret;
					memcpy(&next, (const void *)(uintptr_t)p, 4);
					memcpy(&ret, (const void *)(uintptr_t)(p + 4), 4);
					if (b && ret >= b && ret < b + sz)
						crash_where(ret, stack[nstack++], sizeof stack[0]);
					else if (nstack < 40)
						crash_where(ret, stack[nstack++], sizeof stack[0]);
					prev = p;
					p = next;
				}
				for (DWORD q = esp; q < esp + HANG_STACK_SCAN && nstack < 47; q += 4) {
					MEMORY_BASIC_INFORMATION mbi;
					DWORD v;
					if (!VirtualQuery((const void *)(uintptr_t)q, &mbi, sizeof mbi) || mbi.State != MEM_COMMIT)
						break;
					memcpy(&v, (const void *)(uintptr_t)q, 4);
					if (b && v >= b && v < b + sz) {
						crash_where(v, stack[nstack++], sizeof stack[0]);
					}
				}
			}
			ResumeThread(g_hang_thread);
		}
	}
	InterlockedIncrement(&g_hang_reports);
	_snprintf(line, sizeof line, "\r\n*** obscoop: GAME THREAD STALLED %.1f s - no frame for %lu ms (frames %ld, last mod step \"%s\")\r\n",
		stuck_ms / 1000.0, (unsigned long)stuck_ms, (long)frames, g_hang_phase ? g_hang_phase : "?");
	crash_line(line);
	if (suspended < 0) {
		crash_line("*** could not suspend the game thread (no handle): no context\r\n");
		return;
	}
	if (!eip) {
		crash_line("*** the game thread ended or the context read failed\r\n");
		return;
	}
	crash_where(eip, where, sizeof where);
	_snprintf(line, sizeof line, "*** eip %s\r\n", where);
	crash_line(line);
	crash_where(esp, where, sizeof where);
	_snprintf(line, sizeof line, "*** esp %s (raw 0x%lx)  ebp 0x%lx\r\n", where, (unsigned long)esp, (unsigned long)ebp);
	crash_line(line);
	_snprintf(line, sizeof line,
		"*** eax %08lx ebx %08lx ecx %08lx edx %08lx esi %08lx edi %08lx efl %08lx\r\n",
		(unsigned long)regs[0], (unsigned long)regs[1], (unsigned long)regs[2], (unsigned long)regs[3],
		(unsigned long)regs[4], (unsigned long)regs[5], (unsigned long)c.EFlags);
	crash_line(line);
	crash_line("*** stack (ebp chain, then image addresses found on the stack):\r\n");
	for (int i = 0; i < nstack; i++) {
		_snprintf(line, sizeof line, "***   %s\r\n", stack[i]);
		crash_line(line);
	}
	crash_line("*** the game thread is suspended for this report and resumed after it; the process keeps running\r\n");
	FlushFileBuffers(g_log);
}

// TASK 38: is the game loading (or rebuilding its world) right now? Read from the watchdog thread, so
// every access is guarded: game+0x310 mode (1 in a level), game+0x320 request state (2 load, 3 load by
// name, 4 change level), game+0x378 world (0 = none / being rebuilt), world+0x11c state (7 = a scripted
// event's load/transition), world+0x12c next state.
static int hang_game_loading(void)
{
	if (IsBadReadPtr((const void *)0x6c3068, 4))
		return 0;
	unsigned g = *(volatile unsigned *)0x6c3068;
	if (!g || IsBadReadPtr((const void *)(uintptr_t)(g + 0x310), 4) || IsBadReadPtr((const void *)(uintptr_t)(g + 0x378), 4))
		return 0;
	unsigned mode = *(volatile unsigned *)(uintptr_t)(g + 0x310);
	unsigned req = IsBadReadPtr((const void *)(uintptr_t)(g + 0x320), 4) ? 0 : *(volatile unsigned *)(uintptr_t)(g + 0x320);
	unsigned w = *(volatile unsigned *)(uintptr_t)(g + 0x378);
	if (!w)
		return 1;    // no world: the menu, or the world is being torn down / built
	if (mode != 1)
		return 1;    // the menu / a loading screen
	if (req)
		return 1;    // a load or a ChangeLevel is in progress
	if (!IsBadReadPtr((const void *)(uintptr_t)(w + 0x12c), 4)) {
		unsigned st = *(volatile unsigned *)(uintptr_t)(w + 0x11c);
		unsigned next = *(volatile unsigned *)(uintptr_t)(w + 0x12c);
		if (st != 1 || next != 0)
			return 1;   // a menu (2/5), a scripted event (7) or a transition the world still runs
	}
	return 0;
}

static DWORD WINAPI hang_thread(LPVOID arg)
{
	(void)arg;
	LONG last = -1;
	DWORD still_since = 0, last_report = 0, load_since = 0;
	for (;;) {
		Sleep(250);
		if (!g_log || g_log == INVALID_HANDLE_VALUE)
			continue;
		LONG f = g_hang_frames;
		DWORD now = GetTickCount();
		if (f != last) {
			if (last_report && last >= 0) {
				char line[160];
				_snprintf(line, sizeof line, "*** obscoop: game thread running again (frames %ld, step \"%s\")\r\n",
					(long)f, g_hang_phase ? g_hang_phase : "?");
				crash_line(line);
				FlushFileBuffers(g_log);
				last_report = 0;
			}
			last = f;
			still_since = now;
			continue;
		}
		if (!f || !g_hang_tid)
			continue;   // the first frame has not happened yet (the game is still starting)
		// TASK 38: while the game is loading a level (or rebuilding the world after one) no frame is
		// rendered for seconds and that is not a stall. Keep the stall clock at "now" for the duration of
		// the load; a frame counter that stands still through a load this long IS reported, so a load that
		// wedged the thread is still visible.
		if (hang_game_loading()) {
			if (!load_since)
				load_since = now;
			if (now - load_since < HANG_LOAD_MAX_MS) {
				still_since = now;
				continue;
			}
		} else {
			load_since = 0;
		}
		if (now - still_since < HANG_STALL_MS)
			continue;
		if (last_report && now - last_report < HANG_REPEAT_MS)
			continue;
		last_report = now;
		hang_report(now - still_since, f);
	}
	return 0;
}

static void hang_install(void)
{
	CloseHandle(CreateThread(NULL, 0, hang_thread, NULL, 0, NULL));
	logf("game thread watchdog running (%d ms stall, a report every %d ms while stuck; `sync` prints frames)",
	     HANG_STALL_MS, HANG_REPEAT_MS);
}
