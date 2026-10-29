/* Serializer/opt-in regression; no D3D device or game data. */
#define CINTERFACE
#include <windows.h>
#include <d3d12.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include "rsx_fp_decompiler.h"
typedef struct { u64 raw,hlsl,shader_cache; u32 bytes,identity_bytes,gpu; } PsoProvenanceVertex;
typedef struct {
    u32 blend,nrt,rtfmt,exp32,cmask,cull,stencil,unnorm,cube_mask,vmask,ghi,shd,unhi;
    u64 samp_key;
} VPFPEntry;
#define FP_UCODE_MAX 32768
static u64 pso_hash_bytes(u64 h,const void* p,size_t n) {
    const unsigned char* b=p; while(n--) {h^=*b++;h*=1099511628211ull;} return h;
}
static int pso_warm_write(const char* path,const void* p,size_t n) {
    FILE* f=fopen(path,"wb");if(!f)return 0;
    int ok=fwrite(p,1,n,f)==n;return fclose(f)==0&&ok;
}
#include "rsx_pso_provenance.h"
int main(int argc,char** argv) {
    assert(argc==2);
    if (!strcmp(argv[1],"unset")) _putenv_s("RSX_PSO_PROVENANCE","");
    else _putenv_s("RSX_PSO_PROVENANCE",argv[1]);
    _putenv_s("RSX_PSO_PROVENANCE_LIMIT","1");
    if (!strcmp(argv[1],"unset")||!strcmp(argv[1],"0")) {
        PsoProvenanceVertex vertex={0};
        pso_provenance_vertex(&vertex,NULL,0,0,0,NULL,0);
        pso_provenance_link(NULL,0,NULL,0,NULL,NULL,NULL,0,0,E_PENDING);
        assert(!pso_provenance_on()&&!s_prov_log&&!vertex.raw);
        puts("Disabled recorder performed no input reads or output initialization");return 0;
    }
    /* Halfword-swapped END instruction, without constants. */
    u8 raw[16]={0,1,0,0};
    const char* text="synthetic shader text";
    PsoProvenanceVertex vertex={0};
    pso_provenance_vertex(&vertex,raw,16,16,1,text,123);
    VPFPEntry state={0}; state.nrt=1;state.cmask=15;
    D3D12_GRAPHICS_PIPELINE_STATE_DESC pd={0};
    pd.VS.pShaderBytecode=text;pd.VS.BytecodeLength=strlen(text);
    pd.PS=pd.VS;
    pso_provenance_link(&pd,10,raw,15,&state,&vertex,text,123,0,E_PENDING);
    pso_provenance_link(&pd,10,raw,15,&state,&vertex,text,123,0,S_OK);
    pso_provenance_link(&pd,11,raw,15,&state,&vertex,text,123,0,S_OK);
    assert(s_prov_count==1); /* duplicate suppressed and second pipeline capped */
    assert(s_prov_log);fclose(s_prov_log);s_prov_log=NULL;
    puts("One queued link, duplicate suppression and configured capture limit passed");
    return 0;
}
