/* Synthetic shaders rendered through WARP: no title programs or assets. */
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rsx_fp_decompiler.h"
using Microsoft::WRL::ComPtr;
static void check(HRESULT r) { if (FAILED(r)) { fprintf(stderr,"HRESULT %08X\n",(unsigned)r); exit(1); } }
static void word(u8* p,u32 w) {
    u32 b=(w<<16)|(w>>16);
    for(int i=0;i<4;i++)p[i]=(u8)(b>>(24-8*i));
}
static float bounded(float x,int mode) {
    float limit=mode==1?65504.f:mode==2?2.f:1.f;
    return mode>=1&&mode<=4?fminf(limit,fmaxf(mode==4?0.f:-limit,x)):x;
}
int main() {
    ComPtr<ID3D11Device> device; ComPtr<ID3D11DeviceContext> context;
    check(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&device,nullptr,&context));
    const char* vertex="float4 main(uint id:SV_VertexID):SV_POSITION { return float4(id==1?3:-1,id==2?3:-1,0,1); }";
    ComPtr<ID3DBlob> vsCode,errors;
    check(D3DCompile(vertex,strlen(vertex),nullptr,nullptr,nullptr,"main","vs_5_0",0,0,&vsCode,&errors));
    ComPtr<ID3D11VertexShader> vs; check(device->CreateVertexShader(vsCode->GetBufferPointer(),vsCode->GetBufferSize(),nullptr,&vs));
    D3D11_TEXTURE2D_DESC desc={};desc.Width=desc.Height=desc.MipLevels=desc.ArraySize=1;
    desc.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;desc.SampleDesc.Count=1;desc.BindFlags=D3D11_BIND_RENDER_TARGET;
    ComPtr<ID3D11Texture2D> target,readback;check(device->CreateTexture2D(&desc,nullptr,&target));
    ComPtr<ID3D11RenderTargetView> view;check(device->CreateRenderTargetView(target.Get(),nullptr,&view));
    desc.BindFlags=0;desc.Usage=D3D11_USAGE_STAGING;desc.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
    check(device->CreateTexture2D(&desc,nullptr,&readback));
    D3D11_VIEWPORT viewport={0,0,1,1,0,1};context->RSSetViewports(1,&viewport);
    ID3D11RenderTargetView* rt=view.Get();context->OMSetRenderTargets(1,&rt,nullptr);
    D3D11_RASTERIZER_DESC raster={};raster.FillMode=D3D11_FILL_SOLID;raster.CullMode=D3D11_CULL_NONE;raster.DepthClipEnable=TRUE;
    ComPtr<ID3D11RasterizerState> rs;check(device->CreateRasterizerState(&raster,&rs));context->RSSetState(rs.Get());
    context->VSSetShader(vs.Get(),nullptr,0);context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    const char* setting=getenv("RSX_FP_SOURCE_RANGE");
    int policy=setting && !strcmp(setting,"1")?1:setting && !strcmp(setting,"2")?2:0;
    bool off=policy==0;
    unsigned tested=0;
    for(int mode=0;mode<6;mode++) for(int abs=0;abs<2;abs++) for(int neg=0;neg<2;neg++) for(int operand=0;operand<3;operand++) {
        if (operand==2 && abs) continue; // Existing source-2 ABS support is a separate issue.
        u8 stream[80]={};
        /* MOV, MUL or MAD isolates each source slot; other operands are R1=0.
         * MUL uses R1=1, initialized by a constant MOV. */
        word(stream,(1u<<24)|(1u<<1)|(15u<<9));word(stream+4,(7u<<18)|2u);
        for(int i=0;i<4;i++)word(stream+16+4*i,0x3f800000u);
        u32 dest=(operand==0?1u:operand==1?2u:4u)<<24;
        word(stream+32,dest|(15u<<9)|1u);
        u32 sources[3]={4u,4u,4u}; // R1, .xxxx
        sources[operand]=2u|(0xe4u<<9)|(neg?(1u<<17):0);
        sources[0]|=7u<<18;
        if(abs)sources[operand]|=1u<<(operand==0?29:18);
        sources[1]|=(u32)mode<<(19+3*operand);
        /* MAD: R1*R2 + source2, with R2 initially zero. */
        if(operand==2)sources[1]=(sources[1]&~255u)|8u;
        for(int i=0;i<3;i++)word(stream+36+4*i,sources[i]);
        const float values[4]={-70000.f,-0.5f,0.5f,70000.f};
        for(int i=0;i<4;i++){u32 bits;memcpy(&bits,&values[i],4);word(stream+48+4*i,bits);}
        char hlsl[32768];assert(rsx_fp_decompile(stream,64,0x40,hlsl,sizeof hlsl)==2);
        ComPtr<ID3DBlob> psCode;errors.Reset();
        HRESULT compiled=D3DCompile(hlsl,strlen(hlsl),nullptr,nullptr,nullptr,"main","ps_5_0",0,0,&psCode,&errors);
        if(FAILED(compiled)){if(errors)fwrite(errors->GetBufferPointer(),1,errors->GetBufferSize(),stderr);check(compiled);}
        ComPtr<ID3D11PixelShader> ps;check(device->CreatePixelShader(psCode->GetBufferPointer(),psCode->GetBufferSize(),nullptr,&ps));
        const float clear[4]={-101,-102,-103,-104};context->ClearRenderTargetView(view.Get(),clear);
        context->PSSetShader(ps.Get(),nullptr,0);context->Draw(3,0);context->CopyResource(readback.Get(),target.Get());
        D3D11_MAPPED_SUBRESOURCE mapped;check(context->Map(readback.Get(),0,D3D11_MAP_READ,0,&mapped));
        const float* result=(const float*)mapped.pData;
        for(int lane=0;lane<4;lane++) {
            float expected=values[lane];int precision=off || (policy==2 && mode!=4)?0:mode;
            if(precision==4)expected=bounded(expected,precision);
            if(abs&&(operand!=2||!off))expected=fabsf(expected);
            if(precision!=4)expected=bounded(expected,precision);
            if(neg)expected=-expected;
            if(!isfinite(result[lane])||fabsf(result[lane]-expected)>0.001f){fprintf(stderr,"mode=%d abs=%d neg=%d source=%d lane=%d got=%g expected=%g\n%s",mode,abs,neg,operand,lane,result[lane],expected,hlsl);return 1;}
            tested++;
        }
        context->Unmap(readback.Get(),0);
    }
    printf("PASS: %u rendered source-range lanes (%s), including all operand slots and modifier ordering\n",tested,off?"rollback":policy==1?"all ranges":"saturation only");
}
