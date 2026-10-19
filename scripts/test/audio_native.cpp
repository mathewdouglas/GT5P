/* CPU dispatch tests use inert image entries, never AVX instructions. */
#include <assert.h>
#include <string.h>
#include <intrin.h>
static unsigned caps = (1u<<12)|(1u<<27)|(1u<<28), xreads;
static unsigned long long state = 6;
static void test_cpuid(int* out, int, int) { memset(out,0,16); out[2]=(int)caps; }
static unsigned long long test_xgetbv(unsigned) { ++xreads; return state; }
#define __cpuidex test_cpuid
#define _xgetbv test_xgetbv
#include "../../src/gt5p_audio_native.cpp"
static int swaps, overrides, probes, bad_id;
static bool omit;
extern "C" int spu_override_function(int image, uint32_t addr, spu_lifted_fn fn) {
    if(image==7 && omit && addr==0x100)return 0;
    if(fn)++overrides;else ++probes;
    return 1;
}
static void stock(spu_context*) {}
extern "C" spu_lifted_entry_fn spu_workload_find_img(uint64_t fp,int* id) {
    *id=fp==0x307E5DC790A6786DULL?4:fp==0x65DD2F533DE508CBULL?7:9;
    if(*id==7 && bad_id)*id=8;
    return stock;
}
extern "C" void spu_workload_register_img(uint64_t,spu_lifted_entry_fn,int,const char*){++swaps;}
#define STUB(name) \
 extern "C" void gt5p_audio_##name##_spu_func_00000000(spu_context*){} \
 extern "C" void gt5p_audio_##name##_spu_recomp_register(void){ \
 gt5p_audio_register_function(0,gt5p_audio_##name##_spu_func_00000000); \
 gt5p_audio_register_function(0x100,gt5p_audio_##name##_spu_func_00000000);}
STUB(j307E5DC7)
STUB(j65DD2F53)
STUB(j8AAB90A4)
int main(int argc,char** argv){
 assert(argc==2);const char* mode=argv[1];
 if(!strcmp(mode,"cpu"))caps=0;
 if(!strcmp(mode,"os"))state=2;
 if(!strcmp(mode,"missing"))omit=true;
 if(!strcmp(mode,"identity"))bad_id=1;
 gt5p_audio_select_native();
 bool disabled=!strcmp(mode,"off")||!strcmp(mode,"cpu")||!strcmp(mode,"os");
 assert(swaps==(disabled?0:(omit||bad_id?2:3)));
 assert(overrides==2*swaps);
 if(!strcmp(mode,"cpu")||!strcmp(mode,"off"))assert(xreads==0);
 if(omit)assert(probes==5); /* image 7 validated, never partially installed */
 puts(mode);
}
