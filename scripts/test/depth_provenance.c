/* Production diagnostic header with fake read-only FIFO memory. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
static u32 memory[40];
static unsigned reads;
static long long age = -1;
static u32 gcm_io2ea(u32 io) { return io < sizeof memory ? io + 0x1000 : 0; }
static u32 vm_read32(u32 ea) { assert(ea >= 0x1000 && ea < 0x1000 + sizeof memory); reads++; return memory[(ea - 0x1000) / 4]; }
long long pad_milestone_age_ms(const char* name) { assert(!strcmp(name,"Race")); return age; }
#include "rsx_depth_provenance.h"
int main(int argc, char** argv) {
    assert(argc == 3);
    if (!strcmp(argv[1],"unset")) _putenv_s("GCM_DEPTH_PROVENANCE","");
    else if (!strcmp(argv[1],"zero")) _putenv_s("GCM_DEPTH_PROVENANCE","0");
    else _putenv_s("GCM_DEPTH_PROVENANCE",argv[2]);
    _putenv_s("GCM_DEPTH_PROVENANCE_AFTER","Race,100");
    _putenv_s("GCM_DEPTH_PROVENANCE_LIMIT","2");
    memory[0]=0x00780304;memory[31]=0x000C0A6C;
    memory[32]=0x203;memory[33]=1;memory[34]=1;
    memory[35]=0x0004183C;memory[36]=1;memory[37]=0x00020000;
    memory[38]=0xFFFF0010;
    gcm_depth_provenance(memory[31],124,1000,10);
    assert(!reads); /* Missing milestone must not touch guest memory. */
    age=99; gcm_depth_provenance(memory[31],124,1000,10); assert(!reads);
    age=100;
    gcm_depth_provenance(0x00080A6C,124,1000,10); assert(!reads); /* Wrong count. */
    if (!strcmp(argv[1],"existing")) {
        gcm_depth_provenance(memory[31],124,1000,10); assert(!reads); return 0;
    }
    if (!strcmp(argv[1],"unmapped")) {
        gcm_depth_provenance(memory[31],1024,1000,10); assert(!reads); return 0;
    }
    gcm_depth_provenance(memory[31],124,1000,10);
    unsigned first=reads;
    if (!strcmp(argv[1],"unset") || !strcmp(argv[1],"zero")) { assert(!reads); return 0; }
    assert(first==43);
    gcm_depth_provenance(memory[31],124,1000,11);
    assert(reads==first*2);
    gcm_depth_provenance(memory[31],124,1000,12);
    assert(reads==first*2); /* Cap prevents more reads as well as writes. */
    return 0;
}
