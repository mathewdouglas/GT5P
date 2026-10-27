/* Deterministic inline-callback/condition wait race, using the real syscall. */
#include "sys_cond.h"
#include "vm.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
uint8_t* vm_base;
uint32_t ppu_vm_size;
sys_mutex_info g_sys_mutexes[SYS_MUTEX_MAX];
static int pending, delivered, committed;
/* The standalone fixture has no PPU creation scheduler. */
void ppu_thread_note_block(uint64_t tid) { (void)tid; }
void ps3_gcm_pump_if_present(void) {
    if (!pending) return;
    pending=0; delivered++;
    sys_mutex_info* m=&g_sys_mutexes[0];
    int depth=m->lock_count; uint64_t owner=m->owner_tid;
    EnterCriticalSection(&m->cs);m->owner_tid=1;m->lock_count=depth+1;
    committed = g_sys_conds[0].waiters != NULL;
    ppu_context c={0};c.thread_id=1;c.gpr[3]=1;
    assert(sys_cond_signal(&c)==CELL_OK);
    m->owner_tid=owner;m->lock_count=depth;LeaveCriticalSection(&m->cs);
}
static void take(int depth){
    for(int i=0;i<depth;i++)EnterCriticalSection(&g_sys_mutexes[0].cs);
    g_sys_mutexes[0].owner_tid=1;g_sys_mutexes[0].lock_count=depth;
}
static void release(int depth){
    assert(g_sys_mutexes[0].owner_tid==1 && g_sys_mutexes[0].lock_count==depth);
    g_sys_mutexes[0].owner_tid=0;g_sys_mutexes[0].lock_count=0;
    for(int i=0;i<depth;i++)LeaveCriticalSection(&g_sys_mutexes[0].cs);
}
int main(int argc,char** argv){
    (void)argc; int fixed=atoi(argv[1]);
    InitializeCriticalSection(&g_sys_mutexes[0].cs);g_sys_mutexes[0].active=1;
    ppu_context c={0};c.thread_id=1;c.gpr[4]=1;
    assert(sys_cond_create(&c)==CELL_OK);
    take(1);pending=1;
    if(!fixed)ps3_gcm_pump_if_present(); /* old lv2 entry placement */
    c.gpr[3]=1;c.gpr[4]=30000;
    int32_t r=(int32_t)sys_cond_wait(&c);
    assert(delivered==1 && committed==fixed);
    assert(r==(fixed?CELL_OK:(int32_t)CELL_ETIMEDOUT));release(1);
    if(fixed){
        /* Timeout remains real when no callback signals. */
        take(1);c.gpr[3]=1;c.gpr[4]=30000;
        assert((int32_t)sys_cond_wait(&c)==(int32_t)CELL_ETIMEDOUT);release(1);
        /* Recursive guest ownership is fully released then restored. */
        take(2);pending=1;c.gpr[3]=1;c.gpr[4]=30000;
        assert(sys_cond_wait(&c)==CELL_OK);assert(committed);release(2);
    }
    c.gpr[3]=1;assert(sys_cond_destroy(&c)==CELL_OK);
    DeleteCriticalSection(&g_sys_mutexes[0].cs);
    puts(fixed?"deferred callback wait: passed":"legacy lost wake reproduced");
}
