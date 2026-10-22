#include "spu_context.h"
#include <assert.h>
#include <intrin.h>
#include <math.h>
#include <stdio.h>
u128 audio_reference(u128,u128,u128,int);
u128 audio_fast(u128,u128,u128,int);
static __attribute__((target("xsave"),noinline)) uint64_t xcr0(void){return _xgetbv(0);}
static uint32_t rng=0x93abcd;
static uint32_t next(void){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;return rng;}
int main(void){
 int cpu[4];__cpuidex(cpu,1,0);
 const unsigned required=(1u<<12)|(1u<<27)|(1u<<28);
 if(((unsigned)cpu[2]&required)!=required||(xcr0()&6)!=6){puts("native arithmetic skipped: CPU/OS lacks FMA");return 0;}
 unsigned csr=_mm_getcsr(); unsigned long long tested=0;
 for(unsigned n=0;n<500000;n++){
  u128 a,b,c;
  for(int i=0;i<4;i++){
   a._u32[i]=(next()&0x807fffff)|((next()%254)<<23);
   b._u32[i]=(next()&0x807fffff)|((next()%254)<<23);
   c._u32[i]=(next()&0x807fffff)|((next()%254)<<23);
  }
  for(int op=0;op<3;op++){
   u128 ref=audio_reference(a,b,c,op),got=audio_fast(a,b,c,op);
   for(int i=0;i<4;i++){assert(ref._u32[i]==got._u32[i]||(isnan(ref._f32[i])&&isnan(got._f32[i])));tested++;}
  }
 }
 assert((_mm_getcsr()&~0x3fu)==(csr&~0x3fu));
 printf("native fused arithmetic: %llu lanes match scalar fmaf; MXCSR controls unchanged\n",tested);
}
