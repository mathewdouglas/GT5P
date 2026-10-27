/* Standalone Windows integration checks against the runtime sources.
 * SDL virtual pads are process-local. Audio uses real WASAPI streams behind
 * a test enumerator; no OS devices or default-output settings are changed. */
#include "libs/input/cellPad.c"
#include "libs/audio/cellAudio.c"

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); exit(1); } } while (0)

/* Unused guest API entry points in these translation units still need their
 * link dependencies. Fail if a test accidentally enters guest-memory code. */
uint8_t* vm_base;
uint32_t ppu_vm_size, g_ww_lo, g_ww_hi;
uint32_t cellGcm_flip_request_count(void) { return 0; }
int g_resv_store_active;
void ps3_ww_report_inline(uint32_t a, uint64_t v, int w) { CHECK(0); }
int spu_coh_is_reserved(uint32_t a) { CHECK(0); return 0; }
void spu_lockline_lock(void) { CHECK(0); }
void spu_lockline_unlock(void) { CHECK(0); }
void spu_coh_notify_write(uint32_t a) { CHECK(0); }
void ppu_resv_break_store(uint64_t a) { CHECK(0); }
uint32_t sys_event_queue_create_direct(uint64_t k, int32_t n) { CHECK(0); return 0; }
uint32_t sys_event_find_queue_by_key(uint64_t k) { CHECK(0); return 0; }
int sys_event_queue_push_by_id(uint32_t q, uint64_t s, uint64_t a, uint64_t b, uint64_t c)
{ CHECK(0); return 0; }

static int (*attach_virtual)(int, int, int, int);
static int (*detach_virtual)(int);
static void* (*joystick_open)(int);
static void (*joystick_close)(void*);
static int (*set_button)(void*, int, unsigned char);
static int (*set_axis)(void*, int, short);

static void load_virtual_api(void)
{
#define LOAD(dst, name) *(FARPROC*)&dst = GetProcAddress(s_sdl.dll, name); CHECK(dst)
    LOAD(attach_virtual, "SDL_JoystickAttachVirtual");
    LOAD(detach_virtual, "SDL_JoystickDetachVirtual");
    LOAD(joystick_open, "SDL_JoystickOpen");
    LOAD(joystick_close, "SDL_JoystickClose");
    LOAD(set_button, "SDL_JoystickSetVirtualButton");
    LOAD(set_axis, "SDL_JoystickSetVirtualAxis");
#undef LOAD
}

static int virtual_port(int id)
{
    for (int i = 0; i < PAD_MAX_HOST_PORTS; i++)
        if (s_sdl_pad[i] && s_sdl.JoystickInstanceID(
            s_sdl.GameControllerGetJoystick(s_sdl_pad[i])) == id) return i;
    return -1;
}

static void test_pad_ports(void)
{
    CHECK(pad_sdl_dyn_init());
    load_virtual_api();
    pad_poll_sdl_dyn();
    int index = attach_virtual(1 /* GAMECONTROLLER */, 6, 15, 0);
    CHECK(index >= 0);
    int id = s_sdl.JoystickGetDeviceInstanceID(index);
    void* stick = joystick_open(index);
    CHECK(stick);
    Sleep(1050);
    pad_poll_sdl_dyn();
    int port = virtual_port(id);
    CHECK(port >= 0); /* Need at least one free port on this machine. */
    CHECK(set_button(stick, 0, 1) == 0);
    CHECK(set_axis(stick, 0, 32767) == 0);
    pad_poll_sdl_dyn();
    CHECK(s_sdl_state[port].buttons & CELL_PAD_CTRL_CROSS);
    CHECK(s_sdl_state[port].analog_lx == 255);
    CHECK(detach_virtual(index) == 0);
    joystick_close(stick);
    pad_poll_sdl_dyn();
    CHECK(!s_sdl_state[port].connected);
    CHECK(!s_sdl_state[port].buttons && s_sdl_state[port].analog_lx == 128);
    /* Reconnect, then replace an attached handle without an intervening poll.
     * The old scan-before-close order assigned the replacement to a new port. */
    for (int cycle = 0; cycle < 5; cycle++) {
        index = attach_virtual(1, 6, 15, 0);
        CHECK(index >= 0);
        id = s_sdl.JoystickGetDeviceInstanceID(index);
        Sleep(1050);
        pad_poll_sdl_dyn();
        CHECK(virtual_port(id) == port);
        CHECK(detach_virtual(index) == 0);
    }
    pad_poll_sdl_dyn();
    CHECK(!s_sdl_state[port].connected);
    puts("PASS: SDL input, neutral disconnect, five replacements keep their port");
}

static int snapshot_has_cross(void)
{
    CHECK(pad_sdl_dyn_read());
    for (int i = 0; i < PAD_MAX_HOST_PORTS; i++)
        if (s_host_state[i].connected && (s_host_state[i].buttons & CELL_PAD_CTRL_CROSS)) return 1;
    return 0;
}

static void test_pad_worker(void)
{
    CHECK(pad_sdl_dyn_read());
    load_virtual_api();
    for (int cycle = 0; cycle < 3; cycle++) {
        int index = attach_virtual(1, 6, 15, 0);
        CHECK(index >= 0);
        void* stick = joystick_open(index);
        CHECK(stick && set_button(stick, 0, 1) == 0);
        ULONGLONG deadline = GetTickCount64() + 2500;
        while (!snapshot_has_cross() && GetTickCount64() < deadline) Sleep(5);
        CHECK(snapshot_has_cross());
        CHECK(detach_virtual(index) == 0);
        joystick_close(stick);
        deadline = GetTickCount64() + 2500;
        while (snapshot_has_cross() && GetTickCount64() < deadline) Sleep(5);
        CHECK(!snapshot_has_cross());
    }
    puts("PASS: SDL worker discovers three virtual reconnects and releases input");
}

static IMMDevice* real_device;
static IAudioClient* real_client;
static IAudioRenderClient* real_render;
static int no_device, fail_open, endpoint = 1, opens, fail_stage, default_calls;
static HRESULT STDMETHODCALLTYPE test_activate(IMMDevice* self, REFIID iid, DWORD ctx,
                                               PROPVARIANT* params, void** out)
{
    (void)self;
    opens++;
    if (fail_open) { *out = NULL; return E_FAIL; }
    return real_device->lpVtbl->Activate(real_device, iid, ctx, params, out);
}
static HRESULT STDMETHODCALLTYPE test_id(IMMDevice* self, LPWSTR* out)
{
    (void)self;
    *out = CoTaskMemAlloc(64 * sizeof(WCHAR));
    CHECK(*out);
    swprintf_s(*out, 64, L"test-output-%d", endpoint);
    return S_OK;
}
static ULONG STDMETHODCALLTYPE test_device_release(IMMDevice* self) { (void)self; return 1; }
static IMMDeviceVtbl test_device_vt = {
    .Release = test_device_release, .Activate = test_activate, .GetId = test_id
};
static IMMDevice test_device = { &test_device_vt };
static HRESULT STDMETHODCALLTYPE test_default(IMMDeviceEnumerator* self, EDataFlow flow,
                                              ERole role, IMMDevice** out)
{
    (void)self; CHECK(flow == eRender && role == eConsole);
    default_calls++;
    *out = no_device ? NULL : &test_device;
    return no_device ? E_NOTFOUND : S_OK;
}
static ULONG STDMETHODCALLTYPE test_enum_release(IMMDeviceEnumerator* self) { (void)self; return 1; }
static IMMDeviceEnumeratorVtbl test_enum_vt = {
    .Release = test_enum_release, .GetDefaultAudioEndpoint = test_default
};
static IMMDeviceEnumerator test_enumerator = { &test_enum_vt };
static HRESULT STDMETHODCALLTYPE test_padding(IAudioClient* self, UINT32* padding)
{ (void)self; (void)padding; return AUDCLNT_E_DEVICE_INVALIDATED; }
static HRESULT STDMETHODCALLTYPE test_stop(IAudioClient* self)
{ (void)self; return real_client->lpVtbl->Stop(real_client); }
static ULONG STDMETHODCALLTYPE test_client_release(IAudioClient* self)
{ (void)self; return real_client->lpVtbl->Release(real_client); }
static IAudioClientVtbl test_client_vt = {
    .Release = test_client_release, .Stop = test_stop, .GetCurrentPadding = test_padding
};
static IAudioClient test_client = { &test_client_vt };
static HRESULT STDMETHODCALLTYPE test_buffer(IAudioRenderClient* self, UINT32 n, BYTE** out)
{
    (void)self;
    if (fail_stage == 1) return AUDCLNT_E_DEVICE_INVALIDATED;
    return real_render->lpVtbl->GetBuffer(real_render, n, out);
}
static HRESULT STDMETHODCALLTYPE test_release_buffer(IAudioRenderClient* self, UINT32 n, DWORD flags)
{
    (void)self;
    CHECK(SUCCEEDED(real_render->lpVtbl->ReleaseBuffer(real_render, n, flags)));
    return AUDCLNT_E_DEVICE_INVALIDATED;
}
static ULONG STDMETHODCALLTYPE test_render_release(IAudioRenderClient* self)
{ (void)self; return real_render->lpVtbl->Release(real_render); }
static IAudioRenderClientVtbl test_render_vt = {
    .Release = test_render_release, .GetBuffer = test_buffer, .ReleaseBuffer = test_release_buffer
};
static IAudioRenderClient test_render = { &test_render_vt };

static void refresh_now(void) { s_wasapi_next_check = 0; audio_backend_refresh(); }
static void check_audio_live(void)
{
    CHECK(s_wasapi_client && s_wasapi_render && s_wasapi_device_id);
    CHECK(audio_backend_room() >= CELL_AUDIO_BLOCK_SAMPLES);
    float silence[CELL_AUDIO_BLOCK_SAMPLES * 2] = {0};
    audio_backend_submit(silence, CELL_AUDIO_BLOCK_SAMPLES);
    CHECK(s_wasapi_client);
    CHECK(s_ports[0].read_index == 123); /* Device recovery preserves guest state. */
}
static void test_audio(void)
{
    CHECK(SUCCEEDED(CoInitializeEx(NULL, COINIT_MULTITHREADED)));
    IMMDeviceEnumerator* en = NULL;
    CHECK(SUCCEEDED(CoCreateInstance(&CLSID_MMDeviceEnumerator, NULL, CLSCTX_ALL,
                                    &IID_IMMDeviceEnumerator, (void**)&en)));
    CHECK(SUCCEEDED(en->lpVtbl->GetDefaultAudioEndpoint(en, eRender, eConsole, &real_device)));
    en->lpVtbl->Release(en);
    s_wasapi_enumerator = &test_enumerator;
    s_audio_hotplug = 1;
    s_ports[0].read_index = 123;
    no_device = 1; refresh_now(); CHECK(!s_wasapi_client);
    no_device = 0; refresh_now(); check_audio_live();
    int before = opens;
    refresh_now(); CHECK(opens == before); /* Same endpoint keeps the stream. */
    endpoint++; refresh_now(); CHECK(opens == before + 1); check_audio_live();
    no_device = 1; refresh_now(); CHECK(!s_wasapi_client && !s_wasapi_event);
    no_device = 0; fail_open = 1; refresh_now(); CHECK(!s_wasapi_client);
    before = opens; audio_backend_refresh(); CHECK(opens == before); /* Backoff. */
    fail_open = 0; refresh_now(); check_audio_live();
    real_client = s_wasapi_client; s_wasapi_client = &test_client;
    CHECK(audio_backend_room() == -1 && !s_wasapi_client);
    refresh_now(); check_audio_live();
    float silence[CELL_AUDIO_BLOCK_SAMPLES * 2] = {0};
    for (fail_stage = 1; fail_stage <= 2; fail_stage++) {
        real_render = s_wasapi_render; s_wasapi_render = &test_render;
        audio_backend_submit(silence, CELL_AUDIO_BLOCK_SAMPLES);
        CHECK(!s_wasapi_client && !s_wasapi_event);
        refresh_now(); check_audio_live();
    }
    for (int cycle = 0; cycle < 10; cycle++) {
        endpoint++; refresh_now(); check_audio_live();
    }
    /* Notifications: no endpoint query while streaming until a change is
     * reported; the reported change then switches outputs. */
    s_wasapi_notify = 1; s_wasapi_change = 0;
    before = default_calls;
    for (int i = 0; i < 5; i++) { s_wasapi_next_check = 1; audio_backend_refresh(); }
    CHECK(default_calls == before);
    endpoint++; before = opens; int queries = default_calls;
    s_audio_notify.lpVtbl->OnDefaultDeviceChanged(&s_audio_notify, eRender, eConsole, L"x");
    s_wasapi_next_check = 1; audio_backend_refresh();
    CHECK(default_calls == queries + 1 && opens == before + 1); check_audio_live();
    s_audio_notify.lpVtbl->OnDefaultDeviceChanged(&s_audio_notify, eCapture, eConsole, L"x");
    before = default_calls; s_wasapi_next_check = 1; audio_backend_refresh(); CHECK(default_calls == before);
    s_wasapi_notify = 0;
    s_audio_hotplug = 0; before = opens; endpoint++;
    s_wasapi_next_check = 1; audio_backend_refresh(); CHECK(opens == before);
    audio_backend_shutdown();
    CHECK(!s_wasapi_client && !s_wasapi_render && !s_wasapi_event && !s_wasapi_device_id);
    real_device->lpVtbl->Release(real_device);
    CoUninitialize();
    /* Exercise actual mixer-thread COM startup/shutdown as well as recovery. */
    for (int cycle = 0; cycle < 2; cycle++) {
        CHECK(cellAudioInit() == CELL_OK);
        Sleep(500);
        CHECK(cellAudioQuit() == CELL_OK);
        CHECK(!s_mix_thread && !s_wasapi_enumerator && !s_wasapi_client);
    }
    puts("PASS: WASAPI endpoint changes, notifications, absent device, failed open, three stream errors, backoff and cleanup");
}

int main(int argc, char** argv)
{
    CHECK(argc == 2);
    if (!strcmp(argv[1], "ports")) test_pad_ports();
    else if (!strcmp(argv[1], "worker")) test_pad_worker();
    else if (!strcmp(argv[1], "audio")) test_audio();
    else CHECK(0);
    return 0;
}
