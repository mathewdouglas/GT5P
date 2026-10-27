/* Exercise the lifted profiling attach routine with synthetic DMA memory. */
#include "spu_helpers.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
static unsigned char memory[0x40000];
static unsigned writes, last_write;
int g_spu_ls_watch_n;
void spu_ls_watch_slow(uint32_t lsa, int write, const uint8_t* p, uint32_t pc, uint32_t lr)
{ (void)lsa; (void)write; (void)p; (void)pc; (void)lr; assert(!"unexpected LS diagnostic"); }
void spu_indirect_branch(spu_context* c) { (void)c; }
SPU_THREAD_LOCAL void (*g_spu_trampoline_fn)(spu_context*);
static unsigned lsa, ea, size;
u128 spu_rdch(spu_context* c, uint32_t channel) { (void)c; (void)channel; return spu_il(0x100); }
void spu_wrch(spu_context* c, uint32_t channel, u128 value) {
    unsigned v=value._u32[0];
    if(channel==MFC_LSA)lsa=v;
    if(channel==MFC_EAL)ea=v;
    if(channel==MFC_Size)size=v;
    if(channel==MFC_Cmd) {
        assert(ea+size<=sizeof memory && lsa+size<=SPU_LS_SIZE);
        if(v==MFC_GET_CMD)memcpy(c->ls+lsa,memory+ea,size);
        else if(v==MFC_PUT_CMD){memcpy(memory+ea,c->ls+lsa,size);writes++;last_write=ea;}
        else assert(!"unexpected DMA");
    }
}
#include "profile_attach.inc"
#include "policy_arg.inc"
static void run(int legacy, unsigned lane, unsigned profile) {
    const unsigned queue=0x10000;
    static spu_context c;
    memset(&c,0,sizeof c);c.ls=c.ls_store;c.host_depth=1;
    memset(memory,0x5a,sizeof memory);
    memset(memory+queue,0,0x40);memory[queue+3]=1;
    if(profile){memset(memory+profile,0,0x40);memory[profile+3]=1;}
    unsigned char before[256];memcpy(before,memory+queue,sizeof before);
    writes=0;last_write=0;
    c.gpr[3]=spu_il(lane);
    spurs_pm_set_arg(&c, ((uint64_t)profile << 32) | queue);
    assert(c.gpr[4]._u32[0]==(legacy?queue:profile));
    assert(spu_shlqbyi(c.gpr[4],4)._u32[0]==queue); /* claim path unchanged */
    gt5p_wwsjob_spu_func_00002720(&c);
    if(writes)gt5p_wwsjob_spu_func_00002850(&c);
    if(legacy){assert(writes==2);assert(last_write==queue+0x40+lane*16);assert(memcmp(before,memory+queue,256));
        /* The profiling count vector shifts stale payload words, clipping the
         * upper address bits exactly as in the captured first-job pointers. */
        if(lane==4)assert(memory[queue+0x84]==0x1a);}
    else {assert(!memcmp(before,memory+queue,256));assert(writes==(profile?2:0));if(profile)assert(last_write==profile+0x40+lane*16);}
}
int main(int argc, char** argv){
    assert(argc==2);
    if(!atoi(argv[1])) {
        run(1,3,0);run(1,4,0);puts("legacy argument overwrites progress row / first jobs");
    } else {
        run(0,3,0);run(0,4,0);puts("packed argument keeps queue intact and claim pointer valid");
        run(0,4,0x20000);puts("explicit profiling buffer remains supported");
    }
}
