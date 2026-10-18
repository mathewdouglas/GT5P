#pragma once
#include <stdio.h>
#include <windows.h>

/* Opt-in through [debug].export_enabled; =0 in the environment is a kill switch. */
void gt5p_debug_init();
void gt5p_debug_enable(int on);
bool gt5p_debug_enabled();
bool gt5p_debug_logs_active();
void gt5p_debug_shutdown();
void gt5p_debug_request(HWND game);
void gt5p_debug_open_folder();
/* 0 disabled, 1 ready, 2 busy, 3 saved, -1 failed. */
int gt5p_debug_status(char* text, size_t size);

/* Independent, best-effort snapshots: never wait for the renderer or suspend it. */
extern "C" void gt5p_debug_snapshot(FILE* out);
extern "C" void gt5p_pv_export(FILE* out);
