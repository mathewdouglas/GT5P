// Native first-run launcher. No game code, decryption keys or game data belong here.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <commctrl.h>
#include <bcrypt.h>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <vector>
#include <string>
#include <array>
#include <cstdio>
#include <algorithm>
#include <cwctype>

namespace fs = std::filesystem;
struct Failure { std::wstring message; };
[[noreturn]] static void fail(const std::wstring& s) { throw Failure{s}; }
struct Handle {
    HANDLE h = INVALID_HANDLE_VALUE;
    explicit Handle(HANDLE v) : h(v) {}
    ~Handle() { if (h && h != INVALID_HANDLE_VALUE) CloseHandle(h); }
    Handle(const Handle&) = delete;
};
static fs::path install, data;
static bool quiet = false;
static bool silent_errors = false;
static std::wstring profile(const fs::path& file, const wchar_t* section, const wchar_t* key) {
    std::array<wchar_t, 32768> b{};
    const DWORD n = GetPrivateProfileStringW(section, key, L"", b.data(), (DWORD)b.size(), file.c_str());
    if (n == b.size() - 1) fail(L"A configuration path is too long.");
    return b.data();
}
static void setting(const fs::path& file, const wchar_t* key, const fs::path& value) {
    if (!WritePrivateProfileStringW(L"game", key, value.c_str(), file.c_str()))
        fail(L"Could not save setup: " + file.wstring());
}
static std::wstring env(const wchar_t* key) {
    DWORD n = GetEnvironmentVariableW(key, nullptr, 0);
    if (!n) return {};
    std::vector<wchar_t> b(n);
    GetEnvironmentVariableW(key, b.data(), n);
    return b.data();
}
static void setenv(const wchar_t* key, const std::wstring& value) {
    if (!SetEnvironmentVariableW(key, value.c_str())) fail(L"Could not set launch environment.");
}
// The current runtime's VFS uses ANSI CRT file paths. Reject lossy conversion
// instead of accepting a path which will silently refer to a different file.
static void runtime_path(const fs::path& p) {
    BOOL lossy = FALSE;
    UINT cp = GetACP();
    int n = WideCharToMultiByte(cp, cp == CP_UTF8 ? WC_ERR_INVALID_CHARS : WC_NO_BEST_FIT_CHARS,
        p.c_str(), -1, nullptr, 0, nullptr, cp == CP_UTF8 ? nullptr : &lossy);
    if (!n || lossy || n >= 480)
        fail(L"The current game runtime cannot use this path. Choose a shorter folder with characters supported by your Windows language:\n\n" + p.wstring());
}
static std::wstring hash(const fs::path& file) {
    std::ifstream in(file, std::ios::binary);
    if (!in) fail(L"Cannot read: " + file.wstring());
    BCRYPT_ALG_HANDLE alg = nullptr;
    BCRYPT_HASH_HANDLE ctx = nullptr;
    if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0)
        fail(L"Windows SHA-256 is unavailable.");
    DWORD bytes = 0, got = 0;
    NTSTATUS rc = BCryptGetProperty(alg, BCRYPT_OBJECT_LENGTH, (PUCHAR)&bytes, sizeof bytes, &got, 0);
    std::vector<unsigned char> obj(bytes), block(65536);
    std::array<unsigned char, 32> digest{};
    if (rc >= 0) rc = BCryptCreateHash(alg, &ctx, obj.data(), bytes, nullptr, 0, 0);
    while (rc >= 0 && in) {
        in.read((char*)block.data(), block.size());
        if (in.gcount()) rc = BCryptHashData(ctx, block.data(), (ULONG)in.gcount(), 0);
    }
    if (rc >= 0 && !in.bad()) rc = BCryptFinishHash(ctx, digest.data(), (ULONG)digest.size(), 0);
    else rc = (NTSTATUS)0xC0000001L;
    if (ctx) BCryptDestroyHash(ctx);
    BCryptCloseAlgorithmProvider(alg, 0);
    if (rc < 0) fail(L"Could not hash: " + file.wstring());
    std::wstring out;
    for (auto b : digest) { out += L"0123456789abcdef"[b >> 4]; out += L"0123456789abcdef"[b & 15]; }
    return out;
}
static std::vector<unsigned char> read_small(const fs::path& p) {
    if (!fs::is_regular_file(p) || fs::file_size(p) > 65536) fail(L"Missing or invalid PARAM.SFO.");
    std::ifstream f(p, std::ios::binary);
    return std::vector<unsigned char>(std::istreambuf_iterator<char>(f), {});
}
static unsigned le(const std::vector<unsigned char>& b, size_t at, size_t n) {
    if (at > b.size() || n > b.size() - at) fail(L"Malformed PARAM.SFO.");
    unsigned v = 0;
    for (size_t i = 0; i < n; ++i) v |= unsigned(b[at+i]) << (8*i);
    return v;
}
static std::string text_at(const std::vector<unsigned char>& b, size_t at, size_t n) {
    if (at > b.size() || n > b.size() - at) fail(L"Malformed PARAM.SFO.");
    std::string s;
    for (size_t i = 0; i < n && b[at+i]; ++i) s += char(b[at+i]);
    return s;
}
static fs::path game_folder(fs::path p) {
    if (!fs::exists(p / L"PARAM.SFO") && fs::exists(p / L"PS3_GAME")) p /= L"PS3_GAME";
    auto b = read_small(p / L"PARAM.SFO");
    if (le(b, 0, 4) != 0x46535000) fail(L"This is not a PS3 game folder.");
    size_t keys = le(b, 8, 4), values = le(b, 12, 4), count = le(b, 16, 4);
    if (count > 256) fail(L"Malformed PARAM.SFO table.");
    std::string id, version;
    for (size_t i = 0; i < count; ++i) {
        size_t at = 20 + i * 16, key = keys + le(b, at, 2);
        if (key >= b.size()) fail(L"Malformed PARAM.SFO key.");
        auto name = text_at(b, key, b.size()-key);
        auto value = text_at(b, values + le(b, at+12, 4), le(b, at+4, 4));
        if (name == "TITLE_ID") id = value;
        if (name == "VERSION") version = value;
    }
    if (id != "BCUS98158" || version != "03.00")
        fail(L"This release supports Gran Turismo 5 Prologue BCUS98158 v03.00 (US disc). Select that extracted game's folder.");
    for (const wchar_t* name : { L"GT.VOL", L"TV.DAT" })
        if (!fs::is_regular_file(p / L"USRDIR" / name) || !fs::file_size(p / L"USRDIR" / name))
            fail(L"The selected dump is missing USRDIR\\" + std::wstring(name) + L". An ISO must be extracted first.");
    p = fs::canonical(p);
    runtime_path(p);
    return p;
}
static fs::path pick(bool folder, const wchar_t* title, const wchar_t* label = L"Decrypted executable", const wchar_t* pattern = L"*.elf") {
    IFileOpenDialog* dialog = nullptr;
    if (FAILED(CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&dialog))))
        fail(L"Windows file picker could not be opened.");
    DWORD flags = FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST | FOS_NOCHANGEDIR;
    dialog->SetOptions(flags | (folder ? FOS_PICKFOLDERS : FOS_FILEMUSTEXIST));
    COMDLG_FILTERSPEC filter{label, pattern};
    if (!folder) dialog->SetFileTypes(1, &filter);
    dialog->SetTitle(title);
    HRESULT hr = dialog->Show(nullptr);
    fs::path result;
    if (SUCCEEDED(hr)) {
        IShellItem* item = nullptr;
        if (SUCCEEDED(dialog->GetResult(&item))) {
            PWSTR path = nullptr;
            if (SUCCEEDED(item->GetDisplayName(SIGDN_FILESYSPATH, &path))) { result = path; CoTaskMemFree(path); }
            item->Release();
        }
    }
    dialog->Release();
    if (hr == HRESULT_FROM_WIN32(ERROR_CANCELLED)) return {};
    if (FAILED(hr) || result.empty()) fail(L"The selected path could not be read.");
    return result;
}
// Windows argv quoting, not shell quoting. No user paths are sent to cmd.exe.
static std::wstring quote(const fs::path& p) {
    std::wstring out = L"\"";
    unsigned slashes = 0;
    for (wchar_t c : p.wstring()) {
        if (c == L'\\') { ++slashes; continue; }
        out.append(slashes * (c == L'"' ? 2 : 1), L'\\'); slashes = 0;
        if (c == L'"') out += L'\\';
        out += c;
    }
    out.append(slashes * 2, L'\\');
    return out + L'"';
}
static DWORD run(const fs::path& exe, const std::wstring& args, const fs::path& cwd, const wchar_t* tag) {
    fs::create_directories(data / L"logs");
    SECURITY_ATTRIBUTES sa{sizeof sa, nullptr, TRUE};
    Handle out(CreateFileW((data/L"logs"/(std::wstring(tag)+L".out")).c_str(), GENERIC_WRITE,
        FILE_SHARE_READ, &sa, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr));
    Handle err(CreateFileW((data/L"logs"/(std::wstring(tag)+L".err")).c_str(), GENERIC_WRITE,
        FILE_SHARE_READ, &sa, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr));
    Handle input(CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ|FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, nullptr));
    if (out.h == INVALID_HANDLE_VALUE || err.h == INVALID_HANDLE_VALUE || input.h == INVALID_HANDLE_VALUE)
        fail(L"Could not open launch logs in " + (data/L"logs").wstring());
    STARTUPINFOW si{}; si.cb = sizeof si; si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = input.h; si.hStdOutput = out.h; si.hStdError = err.h;
    Handle job(CreateJobObjectW(nullptr, nullptr));
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!job.h || !SetInformationJobObject(job.h, JobObjectExtendedLimitInformation, &limits, sizeof limits))
        fail(L"Could not create the application process group.");
    PROCESS_INFORMATION pi{};
    std::wstring command = quote(exe) + L" " + args;
    if (!CreateProcessW(exe.c_str(), command.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW|CREATE_SUSPENDED, nullptr, cwd.c_str(), &si, &pi))
        fail(L"Could not start " + exe.wstring() + L" (Windows error " + std::to_wstring(GetLastError()) + L"). Re-extract the complete release ZIP.");
    Handle process(pi.hProcess), thread(pi.hThread);
    if (!AssignProcessToJobObject(job.h, process.h)) {
        TerminateProcess(process.h, 1); // only the suspended child created above
        fail(L"Could not attach the launched application to its process group.");
    }
    if (ResumeThread(thread.h) == (DWORD)-1) fail(L"Could not resume the launched application.");
    // Keep this thread's dialogs responsive while either child is running.
    for (;;) {
        DWORD w = MsgWaitForMultipleObjects(1, &process.h, FALSE, INFINITE, QS_ALLINPUT);
        if (w == WAIT_OBJECT_0) break;
        if (w == WAIT_FAILED) fail(L"Could not wait for the launched application.");
        MSG msg;
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    }
    DWORD code = 1; GetExitCodeProcess(process.h, &code); return code;
}
static fs::path executable_for(const fs::path& disc, const std::wstring& expected) {
    auto candidate = disc / L"USRDIR" / L"EMAIN.ELF";
    if (fs::is_regular_file(candidate) && hash(candidate) == expected) return candidate;
    TASKDIALOG_BUTTON buttons[] = {{100,L"Select my decrypted EMAIN.ELF"}, {101,L"Create it using my installed RPCS3"}};
    TASKDIALOGCONFIG td{}; td.cbSize = sizeof td;
    td.dwFlags = (TASKDIALOG_FLAGS)(TDF_USE_COMMAND_LINKS | TDF_ALLOW_DIALOG_CANCELLATION);
    td.pszWindowTitle = L"GT5P - executable setup"; td.pszMainInstruction = L"One game file needs to be decrypted";
    td.pszContent = L"The download contains no game data or decryption keys. If your dump already has a decrypted EMAIN.ELF, select it. Otherwise select your installed RPCS3; it will decrypt a temporary copy of EMAIN.SELF. Your original dump is left unchanged.";
    td.cButtons = 2; td.pButtons = buttons; td.dwCommonButtons = TDCBF_CANCEL_BUTTON;
    int choice = IDCANCEL;
    if (FAILED(TaskDialogIndirect(&td, &choice, nullptr, nullptr))) fail(L"Could not open the executable setup dialog.");
    if (choice == IDCANCEL) return {};
    if (choice == 100) return pick(false, L"Select decrypted EMAIN.ELF (BCUS98158 v03.00)");
    auto rpcs3 = pick(false, L"Select your installed RPCS3", L"RPCS3 executable", L"rpcs3.exe");
    if (rpcs3.empty()) return {};
    if (!fs::is_regular_file(disc/L"USRDIR"/L"EMAIN.SELF")) fail(L"The dump is missing USRDIR\\EMAIN.SELF.");
    // Each attempt has its own directory; never overwrite an earlier import.
    fs::path temp = data/L"imports"/(std::to_wstring(GetCurrentProcessId())+L"-"+std::to_wstring(GetTickCount64()));
    fs::create_directories(temp);
    fs::copy_file(disc/L"USRDIR"/L"EMAIN.SELF", temp/L"EMAIN.SELF");
    if (run(rpcs3, L"--decrypt " + quote(temp/L"EMAIN.SELF"), rpcs3.parent_path(), L"decrypt") != 0)
        fail(L"RPCS3 decryption failed. See logs\\decrypt.err in the GT5P user-data folder. You can also use RPCS3's Decrypt PS3 Binaries menu, then select the resulting ELF on the next setup attempt.");
    candidate = temp/L"EMAIN.elf";
    if (!fs::is_regular_file(candidate)) fail(L"RPCS3 did not produce EMAIN.elf. Use its Decrypt PS3 Binaries menu, then select the resulting ELF.");
    return candidate;
}
static std::wstring release_value(const wchar_t* key) {
    return profile(install/L"release.ini", L"release", key);
}
static bool setup(const std::wstring& expected) {
    auto chosen = pick(true, L"Select your GT5P dump folder (or its PS3_GAME folder)");
    if (chosen.empty()) return false;
    fs::path disc = game_folder(chosen), elf = data/L"input"/L"EMAIN.ELF";
    if (!fs::is_regular_file(elf) || hash(elf) != expected) {
        auto source = executable_for(disc, expected);
        if (source.empty()) return false;
        if (hash(source) != expected) fail(L"That executable does not match this GT5P release. Use a decrypted EMAIN.SELF from the supported BCUS98158 v03.00 dump.");
        fs::create_directories(elf.parent_path());
        fs::copy_file(source, elf.wstring()+L".tmp", fs::copy_options::overwrite_existing);
        if (!MoveFileExW((elf.wstring()+L".tmp").c_str(), elf.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
            fail(L"Could not save the verified game executable.");
    }
    // Commit a complete configuration atomically; cancel/failure leaves the old one.
    fs::path staged = data/L"setup.new.ini";
    { std::ofstream f(staged, std::ios::binary|std::ios::trunc); f.write("\xff\xfe", 2); }
    setting(staged, L"directory", disc);
    WritePrivateProfileStringW(nullptr, nullptr, nullptr, staged.c_str());
    if (!MoveFileExW(staged.c_str(), (data/L"setup.ini").c_str(), MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))
        fail(L"Could not finish saving setup.");
    return true;
}
static void report(const std::wstring& message) {
    try {
        if (!data.empty() && fs::is_directory(data)) {
            fs::create_directories(data/L"logs");
            int n = WideCharToMultiByte(CP_UTF8, 0, message.c_str(), (int)message.size(), nullptr, 0, nullptr, nullptr);
            std::string text(n, '\0');
            WideCharToMultiByte(CP_UTF8, 0, message.c_str(), (int)message.size(), text.data(), n, nullptr, nullptr);
            std::ofstream out(data/L"logs"/L"setup.err"); out << text << '\n';
        }
    } catch (const std::exception&) {}
    fwprintf(stderr, L"%ls\n", message.c_str());
    if (!quiet && !silent_errors) MessageBoxW(nullptr, message.c_str(), L"GT5P setup", MB_OK|MB_ICONERROR);
}
static bool within(const fs::path& a, const fs::path& b) {
    auto x = a.lexically_normal().wstring(), y = b.lexically_normal().wstring();
    std::transform(x.begin(), x.end(), x.begin(), towlower);
    std::transform(y.begin(), y.end(), y.begin(), towlower);
    if (x == y) return true;
    if (!y.empty() && y.back() != L'\\') y += L'\\';
    return x.compare(0, y.size(), y) == 0;
}
// Copy before switching the locator. Keep the old profile as a recovery copy.
static void relocate(const fs::path& chosen, const fs::path& home) {
    fs::path destination = fs::weakly_canonical(fs::absolute(chosen));
    auto source = fs::weakly_canonical(data);
    runtime_path(destination);
    if (within(destination, source) && within(source, destination)) return;
    if (within(destination, source) || within(source, destination) ||
        within(install, destination) || within(home, destination))
        fail(L"Choose a separate storage folder, outside the current data folder and containing neither the launcher nor its configuration folder.");
    if (fs::exists(destination) && (!fs::is_directory(destination) || !fs::is_empty(destination)))
        fail(L"Choose an empty folder for GT5P storage. Existing files will not be overwritten.");
    // Check the entire source before copying; do not follow directory links.
    for (const auto& entry : fs::recursive_directory_iterator(source))
        if (GetFileAttributesW(entry.path().c_str()) & FILE_ATTRIBUTE_REPARSE_POINT)
            fail(L"The existing storage contains a linked file or folder. Relocation stopped; the original storage is unchanged.");
    fs::create_directories(destination);
    Handle lock(CreateFileW((destination/L"launcher.lock").c_str(), GENERIC_WRITE, 0, nullptr, OPEN_ALWAYS, 0, nullptr));
    if (lock.h == INVALID_HANDLE_VALUE) fail(L"The selected storage folder is not writable or is in use.");
    for (const auto& entry : fs::recursive_directory_iterator(source)) {
        auto relative = entry.path().lexically_relative(source);
        if (relative == L"launcher.lock" || relative == L"storage.lock" ||
            relative == L"storage.ini" || relative == L"storage.new.ini") continue;
        auto target = destination/relative;
        if (entry.is_directory()) fs::create_directories(target);
        else if (entry.is_regular_file()) {
            fs::copy_file(entry.path(), target);
            if (hash(entry.path()) != hash(target)) fail(L"Storage copy verification failed. The original storage remains selected.");
        } else fail(L"Unsupported file in storage. The original storage remains selected.");
    }
    auto staged = home/L"storage.new.ini";
    { std::ofstream f(staged, std::ios::binary|std::ios::trunc); f.write("\xff\xfe", 2); }
    setting(staged, L"directory", destination);
    WritePrivateProfileStringW(nullptr, nullptr, nullptr, staged.c_str());
    if (!MoveFileExW(staged.c_str(), (home/L"storage.ini").c_str(), MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))
        fail(L"Could not remember the storage folder. The original storage remains selected.");
    data = destination;
}
static fs::path storage_picker() {
    TASKDIALOG_BUTTON buttons[] = {{100,L"Keep the current storage folder"}, {101,L"Choose a folder (including an external SSD)"}};
    TASKDIALOGCONFIG td{}; td.cbSize = sizeof td;
    td.dwFlags = (TASKDIALOG_FLAGS)(TDF_USE_COMMAND_LINKS | TDF_ALLOW_DIALOG_CANCELLATION);
    td.pszWindowTitle = L"GT5P - storage location";
    td.pszMainInstruction = L"Where should GT5P store its files?";
    std::wstring content = L"Saves, settings, shader cache and the verified executable will be stored here:\n\n" + data.wstring() +
        L"\n\nYour game dump stays where it is. The launcher stays where you extracted it; you can put that entire folder on your SSD too. Changing storage copies existing data and keeps the original as a backup.";
    td.pszContent = content.c_str(); td.cButtons = 2; td.pButtons = buttons;
    td.dwCommonButtons = TDCBF_CANCEL_BUTTON;
    int choice = IDCANCEL;
    if (FAILED(TaskDialogIndirect(&td, &choice, nullptr, nullptr))) fail(L"Could not open storage setup.");
    if (choice == IDCANCEL) return {};
    if (choice == 100) return data;
    return pick(true, L"Choose an empty folder for GT5P saves, settings and cache");
}
int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    HRESULT com = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    try {
        int argc = 0; auto argv = CommandLineToArgvW(GetCommandLineW(), &argc);
        if (!argv) fail(L"Could not read launcher options.");
        bool force = false, open = false, unknown = false, choose_storage = false;
        fs::path storage;
        for (int i = 1; i < argc; ++i) {
            if (!wcscmp(argv[i], L"--setup")) force = true;
            else if (!wcscmp(argv[i], L"--check")) quiet = true;
            else if (!wcscmp(argv[i], L"--open-data")) open = true;
            else if (!wcscmp(argv[i], L"--choose-storage")) choose_storage = true;
            else if (!wcscmp(argv[i], L"--set-storage") && i+1 < argc) storage = argv[++i];
            else unknown = true;
        }
        LocalFree(argv);
        silent_errors = !storage.empty();
        if (unknown || (quiet && (choose_storage || !storage.empty() || open)))
            fail(L"Supported options: --setup, --check, --open-data, --choose-storage, --set-storage <empty folder>. Storage changes cannot be combined with --check.");
        if (FAILED(com)) fail(L"Windows COM initialization failed.");
        std::array<wchar_t, 32768> module{};
        DWORD n = GetModuleFileNameW(nullptr, module.data(), (DWORD)module.size());
        if (!n || n >= module.size()) fail(L"Could not locate the launcher.");
        install = fs::path(module.data()).parent_path();
        PWSTR local = nullptr;
        if (FAILED(SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &local))) fail(L"Could not locate Local AppData.");
        auto home = env(L"GT5P_LAUNCHER_HOME").empty() ? fs::path(local)/L"GT5PRecomp" : fs::absolute(env(L"GT5P_LAUNCHER_HOME"));
        CoTaskMemFree(local);
        bool override_data = !env(L"GT5P_USER_DIR").empty();
        data = override_data ? fs::absolute(env(L"GT5P_USER_DIR")) : home;
        runtime_path(home);
        if (override_data && (choose_storage || !storage.empty())) fail(L"Unset GT5P_USER_DIR before changing the remembered storage location.");
        if (!override_data) {
            auto saved = profile(home/L"storage.ini", L"game", L"directory");
            if (!saved.empty()) {
                data = saved;
                if (!fs::is_directory(data)) {
                    data = home;
                    fail(L"Your selected GT5P storage is unavailable:\n\n" + saved + L"\n\nReconnect the drive and try again. Your saved selection has been kept.");
                }
            }
        }
        runtime_path(data); runtime_path(install);
        fs::create_directories(data);
        if (open) {
            if ((INT_PTR)ShellExecuteW(nullptr, L"open", data.c_str(), nullptr, nullptr, SW_SHOWNORMAL) <= 32)
                fail(L"Explorer could not open the user-data directory.");
            CoUninitialize(); return 0;
        }
        // Serialize locator changes and launches even while data lives elsewhere.
        if (!override_data) fs::create_directories(home);
        Handle home_lock(override_data ? INVALID_HANDLE_VALUE : CreateFileW((home/L"storage.lock").c_str(), GENERIC_WRITE, 0, nullptr, OPEN_ALWAYS, 0, nullptr));
        if (!override_data && home_lock.h == INVALID_HANDLE_VALUE) fail(L"GT5P is already running or storage setup is in use.");
        Handle lock(CreateFileW((data/L"launcher.lock").c_str(), GENERIC_WRITE, 0, nullptr, OPEN_ALWAYS, 0, nullptr));
        if (lock.h == INVALID_HANDLE_VALUE) fail(L"GT5P is already running or this user-data folder is not writable.");
        auto expected = release_value(L"elf_sha256");
        if (release_value(L"schema") != L"1" || release_value(L"target") != L"BCUS98158" ||
            release_value(L"version") != L"03.00" || expected.size() != 64)
            fail(L"Missing or incompatible release.ini. Re-extract the full release ZIP.");
        auto game = install/L"runtime"/L"gt5p.exe";
        if (!fs::is_regular_file(game) || hash(game) != release_value(L"game_sha256")) fail(L"The game executable does not match release.ini. Re-extract the complete ZIP.");
        bool first_storage = !override_data && !fs::exists(data/L"setup.ini") &&
            env(L"GT5P_STORAGE_PICKER") != L"0" && env(L"GT5P_LAUNCHER_SETUP") != L"0" && !quiet && !open;
        if (!override_data && (choose_storage || !storage.empty() || first_storage || (force && !quiet && env(L"GT5P_STORAGE_PICKER") != L"0"))) {
            auto selected = storage.empty() ? storage_picker() : storage;
            if (selected.empty()) { CoUninitialize(); return 0; }
            auto previous = data;
            relocate(selected, home);
            if (data != previous) {
                CloseHandle(lock.h);
                lock.h = CreateFileW((data/L"launcher.lock").c_str(), GENERIC_WRITE, 0, nullptr, OPEN_ALWAYS, 0, nullptr);
                if (lock.h == INVALID_HANDLE_VALUE) fail(L"The selected storage folder is in use or not writable.");
            }
            if (choose_storage || !storage.empty()) { CoUninitialize(); return 0; }
        }
        bool valid = false;
        auto disc = fs::path(profile(data/L"setup.ini", L"game", L"directory"));
        if (!force && !disc.empty()) {
            try { disc = game_folder(disc); valid = hash(data/L"input"/L"EMAIN.ELF") == expected; }
            catch (const Failure&) {} catch (const fs::filesystem_error&) {}
        }
        if (!valid) {
            if (quiet || env(L"GT5P_LAUNCHER_SETUP") == L"0") fail(L"Setup is missing or no longer valid. Run GT5P.exe --setup.");
            if (!setup(expected)) { CoUninitialize(); return 0; }
            disc = game_folder(profile(data/L"setup.ini", L"game", L"directory"));
        }
        if (quiet) { CoUninitialize(); return 0; }
        // Keep all mutable state outside the ZIP/install directory. Assets are
        // small, distributable glyph art; this never copies the game dump.
        if (!fs::is_directory(install/L"assets")) fail(L"The release assets folder is missing.");
        fs::copy(install/L"assets", data/L"assets", fs::copy_options::recursive|fs::copy_options::overwrite_existing);
        fs::create_directories(data/L"gamedata"/L"dev_hdd0");
        auto settings = data/L"gt5p_settings.toml";
        if (!fs::exists(settings)) {
            std::ofstream f(settings);
            f << "# First-run preset. Change this in the game's F1 settings.\n[video]\nresolution = \"720p\"\naspect = \"16:9\"\nmsaa = 2\nshader_precompile = true\npipeline_async = true\n";
            if (!f) fail(L"Could not write initial video settings.");
        }
        setenv(L"GT5P_ROOT", data.wstring());
        setenv(L"PS3_VFS_ROOT", data.wstring());
        setenv(L"PS3_GAMEDATA_ROOT", (data/L"gamedata").wstring());
        setenv(L"GT5P_SETTINGS", settings.wstring());
        setenv(L"GT5P_GAME_DIR", disc.wstring()+L"/");
        if (env(L"PS3_VERBOSE").empty()) setenv(L"PS3_VERBOSE", L"0");
        DWORD code = run(game, quote(data/L"input"/L"EMAIN.ELF"), data, L"play");
        if (code) fail(L"The game exited with code " + std::to_wstring(code) + L". Logs are in:\n\n" + (data/L"logs").wstring());
        CoUninitialize(); return 0;
    } catch (const Failure& e) {
        report(e.message);
    } catch (const std::exception&) {
        report(L"A file operation failed. Check free space and folder access, then run GT5P.exe --setup again.");
    }
    if (SUCCEEDED(com)) CoUninitialize();
    return 1;
}
