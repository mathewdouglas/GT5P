// Stand-in child for launcher integration checks. No game code or game files.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <initializer_list>

int wmain(int argc, wchar_t** argv) {
    FILE* f = nullptr;
    if (_wfopen_s(&f, L"probe.txt", L"w, ccs=UTF-8") || !f) return 2;
    wchar_t cwd[32768];
    GetCurrentDirectoryW(32768, cwd);
    fwprintf(f, L"cwd=%ls\nargc=%d\npid=%lu\n", cwd, argc, GetCurrentProcessId());
    for (int i = 0; i < argc; ++i) fwprintf(f, L"arg%d=%ls\n", i, argv[i]);
    for (const wchar_t* key : {L"GT5P_ROOT", L"PS3_VFS_ROOT", L"PS3_GAMEDATA_ROOT",
                              L"GT5P_SETTINGS", L"GT5P_GAME_DIR", L"PS3_VERBOSE"}) {
        wchar_t value[32768]{};
        GetEnvironmentVariableW(key, value, 32768);
        fwprintf(f, L"%ls=%ls\n", key, value);
    }
    fclose(f);
    puts("probe stdout"); fflush(stdout);
    fputs("probe stderr\n", stderr); fflush(stderr);
    wchar_t delay[32]{};
    if (GetEnvironmentVariableW(L"GT5P_PROBE_DELAY_MS", delay, 32)) Sleep(_wtoi(delay));
    return 0;
}
