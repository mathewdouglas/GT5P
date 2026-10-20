/* Synthetic pipeline only: tests the extracted production queue on D3D12 WARP. */
#define CINTERFACE
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <initguid.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <d3dcompiler.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
typedef uint32_t u32; typedef uint64_t u64;
#define CHECK(c) do {if(!(c)){fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#c);exit(1);}}while(0)
#define PSO_WARM_MAX 4096
#define PSO_WARM_INPUTS 32
#define PSO_WARM_CODE_MAX (4u*1024u*1024u)
typedef struct {D3D12_INPUT_ELEMENT_DESC desc;char name[32];} PsoWarmInput;
typedef struct {u64 hash,vs_hash,ps_hash;u32 vs_bytes,ps_bytes;D3D12_GRAPHICS_PIPELINE_STATE_DESC desc;PsoWarmInput input[32];} PsoWarmRecipe;
static struct {ID3D12Device* device;ID3D12RootSignature* vp_root_sig;} s_d3d;
static volatile LONG g_rsx_shaders_pending, g_rsx_shader_busy, calls;
static u32 s_pso_warm_loaded,s_pso_warm_rejected;
static volatile LONG trace_count;
static u32 trace[1024];
static DWORD caller,driver;
static DWORD delay_ms=100;
static HANDLE allow_driver;
static char folder[1024];
static D3D12_GRAPHICS_PIPELINE_STATE_DESC template;
static void* vertex;static void* pixel;
static SRWLOCK warm_lock=SRWLOCK_INIT;
static SRWLOCK s_pso_warm_lock=SRWLOCK_INIT;
static u32 s_pso_warm_n;
static ID3D12PipelineState* warm;
static int shc_async_on(void){return 1;}
static void ps3_name_thread(const wchar_t* s){(void)s;}
static int pso_warm_dir(char* p,size_t n){snprintf(p,n,"%s",folder);return 1;}
static int pso_warm_get(u64 hash,ID3D12PipelineState** out){
    int hit=0;AcquireSRWLockShared(&warm_lock);
    if(hash==0x222 && warm){*out=warm;warm->lpVtbl->AddRef(warm);hit=1;}
    ReleaseSRWLockShared(&warm_lock);return hit;
}
static u64 guest_pso_hash(const D3D12_GRAPHICS_PIPELINE_STATE_DESC* pd){(void)pd;return 0x222;}
static HRESULT create_guest_pso_cached(const D3D12_GRAPHICS_PIPELINE_STATE_DESC* pd,ID3D12PipelineState** out){
    LONG t=InterlockedIncrement(&trace_count)-1;if(t<1024)trace[t]=pd->SampleMask;
    InterlockedIncrement(&calls);driver=GetCurrentThreadId();CHECK(driver!=caller);
    CHECK(WaitForSingleObject(allow_driver,5000)==WAIT_OBJECT_0);Sleep(delay_ms);
    HRESULT result=s_d3d.device->lpVtbl->CreateGraphicsPipelineState(s_d3d.device,pd,&IID_ID3D12PipelineState,(void**)out);
    if(SUCCEEDED(result)){
        AcquireSRWLockExclusive(&warm_lock);
        if(!warm){warm=*out;warm->lpVtbl->AddRef(warm);}
        ReleaseSRWLockExclusive(&warm_lock);
    }
    return result;
}
/* Demand jobs share the stub; the production one only differs in retention. */
static HRESULT create_guest_pso_job(const D3D12_GRAPHICS_PIPELINE_STATE_DESC* pd,ID3D12PipelineState** out){
    return create_guest_pso_cached(pd,out);
}
static u32 pso_resident_max(void){return PSO_WARM_MAX;}
static void pso_touch_file(const char* path){(void)path;}
static int pso_warm_read_recipe(const char* path,PsoWarmRecipe* r){
    if(!strstr(path,"0000000000000222.recipe"))return 0;
    memset(r,0,sizeof *r);r->hash=0x222;r->vs_hash=1;r->ps_hash=2;
    r->desc=template;r->vs_bytes=(u32)template.VS.BytecodeLength;r->ps_bytes=(u32)template.PS.BytecodeLength;
    r->input[0].desc=template.InputLayout.pInputElementDescs[0];strcpy(r->input[0].name,"POSITION");return 1;
}
static void* pso_warm_read_code(const char* dir,u64 hash,u32 bytes){
    (void)dir;void* p=malloc(bytes);memcpy(p,hash==1?vertex:pixel,bytes);return p;
}
#include "queue.inc"
static ID3DBlob* compile(const char* text,const char* target){
    ID3DBlob *blob=NULL,*err=NULL;
    HRESULT hr=D3DCompile(text,strlen(text),NULL,NULL,NULL,"main",target,0,0,&blob,&err);
    if(err){fwrite(err->lpVtbl->GetBufferPointer(err),1,err->lpVtbl->GetBufferSize(err),stderr);err->lpVtbl->Release(err);}
    CHECK(SUCCEEDED(hr));return blob;
}
static volatile LONG loaders_returned;
static DWORD WINAPI load_script(LPVOID ignored){(void)ignored;pso_race_notify("LoadingRoot.gpb");InterlockedIncrement(&loaders_returned);return 0;}
static HRESULT poll(u64 hash,ID3D12PipelineState** pso){
    ULONGLONG began=GetTickCount64();HRESULT hr;
    while((hr=pso_queue_get(hash,&template,pso))==E_PENDING){CHECK(GetTickCount64()-began<5000);Sleep(1);}return hr;
}
int main(int argc,char** argv){
    _putenv_s("RSX_SHADER_WARMUP_BACKGROUND","0");CHECK(!pso_startup_background());
    _putenv_s("RSX_SHADER_WARMUP_BACKGROUND","1");CHECK(pso_startup_background());
    _putenv_s("GT5P_SHADER_PRECOMPILE_ONLY","1");CHECK(!pso_startup_background());
    _putenv_s("GT5P_SHADER_PRECOMPILE_ONLY","");
    CHECK(argc==2);snprintf(folder,sizeof folder,"%s",argv[1]);caller=GetCurrentThreadId();
    IDXGIFactory4* factory=NULL;IDXGIAdapter* adapter=NULL;
    CHECK(SUCCEEDED(CreateDXGIFactory1(&IID_IDXGIFactory4,(void**)&factory)));
    CHECK(SUCCEEDED(factory->lpVtbl->EnumWarpAdapter(factory,&IID_IDXGIAdapter,(void**)&adapter)));
    CHECK(SUCCEEDED(D3D12CreateDevice((IUnknown*)adapter,D3D_FEATURE_LEVEL_11_0,&IID_ID3D12Device,(void**)&s_d3d.device)));
    adapter->lpVtbl->Release(adapter);factory->lpVtbl->Release(factory);
    D3D12_ROOT_SIGNATURE_DESC root={0};root.Flags=D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT;
    ID3DBlob* serialized=NULL;CHECK(SUCCEEDED(D3D12SerializeRootSignature(&root,D3D_ROOT_SIGNATURE_VERSION_1,&serialized,NULL)));
    CHECK(SUCCEEDED(s_d3d.device->lpVtbl->CreateRootSignature(s_d3d.device,0,serialized->lpVtbl->GetBufferPointer(serialized),serialized->lpVtbl->GetBufferSize(serialized),&IID_ID3D12RootSignature,(void**)&s_d3d.vp_root_sig)));
    serialized->lpVtbl->Release(serialized);
    ID3DBlob* vs=compile("float4 main(float4 p:POSITION):SV_POSITION{return p;}","vs_5_0");
    ID3DBlob* ps=compile("float4 main():SV_TARGET{return float4(1,0,0,1);}","ps_5_0");
    template.pRootSignature=s_d3d.vp_root_sig;
    template.VS.pShaderBytecode=vertex=vs->lpVtbl->GetBufferPointer(vs);template.VS.BytecodeLength=vs->lpVtbl->GetBufferSize(vs);
    template.PS.pShaderBytecode=pixel=ps->lpVtbl->GetBufferPointer(ps);template.PS.BytecodeLength=ps->lpVtbl->GetBufferSize(ps);
    D3D12_INPUT_ELEMENT_DESC input={0};input.SemanticName="POSITION";input.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
    template.InputLayout.pInputElementDescs=&input;template.InputLayout.NumElements=1;
    template.RasterizerState.FillMode=D3D12_FILL_MODE_SOLID;template.RasterizerState.CullMode=D3D12_CULL_MODE_NONE;
    template.BlendState.RenderTarget[0].RenderTargetWriteMask=15;
    template.SampleMask=~0u;template.SampleDesc.Count=1;template.PrimitiveTopologyType=D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    template.NumRenderTargets=1;template.RTVFormats[0]=DXGI_FORMAT_R8G8B8A8_UNORM;
    allow_driver=CreateEventA(NULL,TRUE,FALSE,NULL);
    /* Enqueue using caller-owned buffers, then destroy those buffers before the
     * driver uses them. A shallow copy fails D3D12 validation or reads garbage. */
    D3D12_GRAPHICS_PIPELINE_STATE_DESC owned=template;
    void* ownvs=malloc(template.VS.BytecodeLength);void* ownps=malloc(template.PS.BytecodeLength);
    memcpy(ownvs,vertex,template.VS.BytecodeLength);memcpy(ownps,pixel,template.PS.BytecodeLength);
    D3D12_INPUT_ELEMENT_DESC owninput=input;char* name=_strdup("POSITION");owninput.SemanticName=name;
    serialized=NULL;CHECK(SUCCEEDED(D3D12SerializeRootSignature(&root,D3D_ROOT_SIGNATURE_VERSION_1,&serialized,NULL)));
    ID3D12RootSignature* ownroot=NULL;
    CHECK(SUCCEEDED(s_d3d.device->lpVtbl->CreateRootSignature(s_d3d.device,0,serialized->lpVtbl->GetBufferPointer(serialized),serialized->lpVtbl->GetBufferSize(serialized),&IID_ID3D12RootSignature,(void**)&ownroot)));
    serialized->lpVtbl->Release(serialized);owned.pRootSignature=ownroot;
    owned.VS.pShaderBytecode=ownvs;owned.PS.pShaderBytecode=ownps;owned.InputLayout.pInputElementDescs=&owninput;
    ID3D12PipelineState* pso=NULL;ULONGLONG began=GetTickCount64();
    CHECK(pso_queue_get(1,&owned,&pso)==E_PENDING);CHECK(GetTickCount64()-began<80);
    ownroot->lpVtbl->Release(ownroot);
    memset(ownvs,0,template.VS.BytecodeLength);memset(ownps,0,template.PS.BytecodeLength);memset(name,'x',8);
    free(ownvs);free(ownps);free(name);
    for(int i=0;i<100;i++)CHECK(pso_queue_get(1,&template,&pso)==E_PENDING);
    CHECK(s_pso_queued==1);SetEvent(allow_driver);
    CHECK(SUCCEEDED(poll(1,&pso)));CHECK(pso!=NULL && calls==1);pso->lpVtbl->Release(pso);
    puts("PASS: delayed driver stays off caller; requests coalesce; bytecode and semantic lifetimes are owned");
    /* Native validation failure is retained, rather than retried each frame. */
    D3D12_GRAPHICS_PIPELINE_STATE_DESC invalid=template;invalid.SampleDesc.Count=0;
    CHECK(pso_queue_get(2,&invalid,&pso)==E_PENDING);CHECK(FAILED(poll(2,&pso)));LONG failed_calls=calls;
    CHECK(FAILED(pso_queue_get(2,&template,&pso)));CHECK(calls==failed_calls);
    /* Preload set uses a valid recipe and a rejected one; the loading gate
     * completes, and a second race reuses resident state without driver work. */
    AcquireSRWLockExclusive(&warm_lock);warm->lpVtbl->Release(warm);warm=NULL;ReleaseSRWLockExclusive(&warm_lock);
    char path[1200];snprintf(path,sizeof path,"%s/race-v1.txt",folder);FILE* f=fopen(path,"w");CHECK(f);
    fputs("0000000000000222\n0000000000000999\n",f);fclose(f);
    pso_race_notify("LoadingRoot.gpb");CHECK(s_race_loaded==1 && s_race_rejected==1);
    LONG before=calls;pso_race_notify("PitSceneRoot.gpb");pso_race_notify("LoadingRoot.gpb");CHECK(calls==before);
    CHECK(SUCCEEDED(pso_queue_get(0x222,&template,&pso)));pso->lpVtbl->Release(pso);
    puts("PASS: loading gate prepares valid race state, rejects missing recipes and reuses resident pipelines");
    AcquireSRWLockExclusive(&warm_lock);warm->lpVtbl->Release(warm);warm=NULL;ReleaseSRWLockExclusive(&warm_lock);
    ResetEvent(allow_driver);_putenv_s("RSX_RACE_PREWARM_WAIT_MS","5");
    pso_race_notify("PitSceneRoot.gpb");began=GetTickCount64();pso_race_notify("LoadingRoot.gpb");
    CHECK(GetTickCount64()-began<80);SetEvent(allow_driver);CHECK(WaitForSingleObject(s_race_ready,5000)==WAIT_OBJECT_0);
    puts("PASS: loading timeout releases the caller while background preparation finishes");
    AcquireSRWLockExclusive(&warm_lock);warm->lpVtbl->Release(warm);warm=NULL;ReleaseSRWLockExclusive(&warm_lock);
    s_pso_warm_n=PSO_WARM_MAX;before=calls;CHECK(!pso_race_recipe(0x222));CHECK(calls==before);s_pso_warm_n=0;
    /* Startup request returns before slow driver work. Learned menu recipes
     * lead the scan; a draw queued during one build wins the next worker turn. */
    snprintf(path,sizeof path,"%s/menu-v1.txt",folder);f=fopen(path,"w");CHECK(f);fputs("0000000000000222\n",f);fclose(f);
    snprintf(path,sizeof path,"%s/pso_0000000000000222.recipe",folder);f=fopen(path,"w");CHECK(f);fputs("synthetic",f);fclose(f);
    snprintf(path,sizeof path,"%s/pso_0000000000000999.recipe",folder);f=fopen(path,"w");CHECK(f);fputs("missing",f);fclose(f);
    ResetEvent(allow_driver);LONG start_trace=trace_count;began=GetTickCount64();pso_startup_begin();
    CHECK(GetTickCount64()-began<80);
    while(trace_count==start_trace) {CHECK(GetTickCount64()-began<3000);Sleep(1);}
    CHECK(s_startup_active && g_rsx_shader_busy==1);
    D3D12_GRAPHICS_PIPELINE_STATE_DESC urgent=template;urgent.SampleMask=123;
    CHECK(pso_queue_get(3,&urgent,&pso)==E_PENDING);SetEvent(allow_driver);
    CHECK(SUCCEEDED(poll(3,&pso)));pso->lpVtbl->Release(pso);
    while(s_startup_active) {CHECK(GetTickCount64()-began<5000);Sleep(1);}
    CHECK(trace[start_trace]==~0u && trace[start_trace+1]==123);
    CHECK(s_pso_warm_loaded>=2 && s_pso_warm_rejected==1 && g_rsx_shader_busy==0);
    puts("PASS: startup returns immediately; menu recipes lead; live draws preempt the remaining scan; damaged records are rejected");
    /* Race loading cancels startup: its race-set phase never runs (its
     * rejection count stays put) while the loading gate prepares the set. */
    AcquireSRWLockExclusive(&warm_lock);if(warm)warm->lpVtbl->Release(warm);warm=NULL;ReleaseSRWLockExclusive(&warm_lock);
    ResetEvent(allow_driver);u32 startup_rejected=s_pso_warm_rejected;LONG race_rejected=s_race_rejected;
    start_trace=trace_count;began=GetTickCount64();pso_startup_begin();
    while(trace_count==start_trace) {CHECK(GetTickCount64()-began<3000);Sleep(1);}
    _putenv_s("RSX_RACE_PREWARM_WAIT_MS","5");pso_race_notify("PitSceneRoot.gpb");pso_race_notify("LoadingRoot.gpb");
    SetEvent(allow_driver);
    while(s_startup_active) {CHECK(GetTickCount64()-began<5000);Sleep(1);}
    CHECK(WaitForSingleObject(s_race_ready,5000)==WAIT_OBJECT_0);
    CHECK(s_pso_warm_rejected==startup_rejected && s_race_rejected==race_rejected+1);
    puts("PASS: race loading cancels the startup pass; the loading gate prepares the race set");
    /* Maintenance: a recipe unused for 20 days and its bytecode go; index
     * entries without a recipe and duplicates go; newest use comes first. */
    {
        char m[1100],p[1200];snprintf(m,sizeof m,"%s/maint",folder);CreateDirectoryA(m,NULL);
        FILETIME now;GetSystemTimeAsFileTime(&now);u64 t=(u64)now.dwHighDateTime<<32|now.dwLowDateTime;
        const char* names[]={"pso_000000000000000a.recipe","pso_000000000000000b.recipe","pso_000000000000000d.recipe",
                             "code_0000000000000001.dxbc","code_0000000000000002.dxbc"};
        const u64 age_days[]={0,20,1,20,0};
        for(int i=0;i<5;i++){
            snprintf(p,sizeof p,"%s/%s",m,names[i]);f=fopen(p,"w");CHECK(f);fputs("x",f);fclose(f);
            u64 v=t-age_days[i]*864000000000ull;FILETIME ft={(DWORD)v,(DWORD)(v>>32)};
            HANDLE h=CreateFileA(p,FILE_WRITE_ATTRIBUTES,0,NULL,OPEN_EXISTING,0,NULL);CHECK(h!=INVALID_HANDLE_VALUE);
            CHECK(SetFileTime(h,NULL,NULL,&ft));CloseHandle(h);
        }
        char race[1200],menu[1200];snprintf(race,sizeof race,"%s/race-v1.txt",m);snprintf(menu,sizeof menu,"%s/menu-v1.txt",m);
        f=fopen(race,"w");CHECK(f);fputs("000000000000000b\n000000000000000d\n000000000000000a\n000000000000000a\n000000000000000c\n",f);fclose(f);
        f=fopen(menu,"w");CHECK(f);fputs("000000000000000a\n",f);fclose(f);
        pso_recipe_maintain(m,race,menu);
        snprintf(p,sizeof p,"%s/%s",m,names[1]);CHECK(GetFileAttributesA(p)==INVALID_FILE_ATTRIBUTES);
        snprintf(p,sizeof p,"%s/%s",m,names[3]);CHECK(GetFileAttributesA(p)==INVALID_FILE_ATTRIBUTES);
        for(int i=0;i<5;i++) if(i!=1 && i!=3){snprintf(p,sizeof p,"%s/%s",m,names[i]);CHECK(GetFileAttributesA(p)!=INVALID_FILE_ATTRIBUTES);}
        char text[256]={0};f=fopen(race,"r");CHECK(f);fread(text,1,sizeof text-1,f);fclose(f);
        CHECK(!strcmp(text,"000000000000000a\n000000000000000d\n"));
        memset(text,0,sizeof text);f=fopen(menu,"r");CHECK(f);fread(text,1,sizeof text-1,f);fclose(f);
        CHECK(!strcmp(text,"000000000000000a\n"));
        _putenv_s("RSX_RACE_PREWARM_WAIT_MS","30000");
    }
    puts("PASS: recipe maintenance prunes unused recipes/bytecode and compacts indexes newest-first");
    /* Saturation must never fall back to driver creation on the caller. */
    delay_ms=0;ResetEvent(allow_driver);
    for(u64 i=1000;i<1000+PSO_ASYNC_MAX+2;i++)CHECK(pso_queue_get(i,&template,&pso)==E_PENDING);
    CHECK(s_pso_full>0);SetEvent(allow_driver);began=GetTickCount64();
    while(g_rsx_shaders_pending) {CHECK(GetTickCount64()-began<15000);Sleep(1);}
    CHECK(s_pso_source_bytes==0);
    ResetEvent(allow_driver);
    AcquireSRWLockExclusive(&warm_lock);if(warm)warm->lpVtbl->Release(warm);warm=NULL;ReleaseSRWLockExclusive(&warm_lock);
    start_trace=trace_count;began=GetTickCount64();pso_startup_begin();
    while(trace_count==start_trace) {CHECK(GetTickCount64()-began<3000);Sleep(1);}
    CHECK(s_startup_active);
    void* bigvs=calloc(1,PSO_WARM_CODE_MAX);void* bigps=calloc(1,PSO_WARM_CODE_MAX);CHECK(bigvs && bigps);
    memcpy(bigvs,vertex,template.VS.BytecodeLength);memcpy(bigps,pixel,template.PS.BytecodeLength);
    D3D12_GRAPHICS_PIPELINE_STATE_DESC big=template;
    big.VS.pShaderBytecode=bigvs;big.PS.pShaderBytecode=bigps;
    big.VS.BytecodeLength=big.PS.BytecodeLength=PSO_WARM_CODE_MAX;
    LONG queued=s_pso_queued;
    for(u64 i=5000;i<5009;i++)CHECK(pso_queue_get(i,&big,&pso)==E_PENDING);
    CHECK(s_pso_source_bytes<=PSO_ASYNC_SOURCE_MAX && s_pso_queued-queued==8);
    free(bigvs);free(bigps);
    _putenv_s("RSX_RACE_PREWARM_WAIT_MS","30000");pso_race_notify("PitSceneRoot.gpb");
    HANDLE loaders[2]={CreateThread(NULL,0,load_script,NULL,0,NULL),CreateThread(NULL,0,load_script,NULL,0,NULL)};
    CHECK(loaders[0] && loaders[1]);began=GetTickCount64();
    while(s_race_waiters!=2){CHECK(GetTickCount64()-began<3000);Sleep(1);}
    SetEvent(allow_driver);pso_queue_stop();
    CHECK(WaitForMultipleObjects(2,loaders,TRUE,3000)==WAIT_OBJECT_0 && loaders_returned==2);
    CloseHandle(loaders[0]);CloseHandle(loaders[1]);
    CHECK(g_rsx_shaders_pending==0 && g_rsx_shader_busy==0 && s_pso_source_bytes==0 && s_race_waiters==0);
    puts("PASS: queue/source/resident budgets stay bounded; shutdown releases concurrent loading gates and pending ownership");
    if(warm)warm->lpVtbl->Release(warm);CloseHandle(allow_driver);
    vs->lpVtbl->Release(vs);ps->lpVtbl->Release(ps);s_d3d.vp_root_sig->lpVtbl->Release(s_d3d.vp_root_sig);
    s_d3d.device->lpVtbl->Release(s_d3d.device);return 0;
}
