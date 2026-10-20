/* Synthetic volumes only; no game assets or programs. */
#include <d3d11.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "rsx_fp_decompiler.h"
#include "rsx_texture_layout.h"
using Microsoft::WRL::ComPtr;
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); exit(1); } } while(0)
static void hr(HRESULT r) { CHECK(SUCCEEDED(r)); }
static void word(u8* p,u32 w) { w=(w<<16)|(w>>16); for(int i=0;i<4;i++)p[i]=(u8)(w>>(24-8*i)); }
static void cpu_checks() {
    rsx_tex_layout layout; rsx_texture_layout(0x85,4,2,&layout);
    u8 source[64]={}, decoded[192]; memset(decoded,0xcd,sizeof decoded);
    for(u32 z=0;z<2;z++)for(u32 y=0;y<2;y++)for(u32 x=0;x<4;x++) {
        u32 address=(x&1)|((y&1)<<1)|((z&1)<<2)|((x&2)<<2);
        source[address*4]=255; source[address*4+1]=(u8)(x*50);
        source[address*4+2]=(u8)(y*100); source[address*4+3]=(u8)(z*150);
    }
    CHECK(rsx_texture_decode_volume(decoded,32,96,source,4,2,2,&layout,0));
    for(u32 z=0;z<2;z++)for(u32 y=0;y<2;y++)for(u32 x=0;x<4;x++) {
        u8* p=decoded+z*96+y*32+x*4;
        CHECK(p[0]==x*50 && p[1]==y*100 && p[2]==z*150 && p[3]==255);
    }
    CHECK(decoded[16]==0xcd && decoded[64]==0xcd && decoded[191]==0xcd);
    CHECK(!rsx_texture_decode_volume(decoded,4,8,source,4,2,2,&layout,0));
    // VTC: two blocks across, four full Z planes, then a two-plane tail.
    const u32 colours[]={0xf800,0x07e0,0x001f,0xffff,0xf81f,0xffe0};
    for(u32 format=0x86;format<=0x88;format++) {
        rsx_texture_layout(format,8,4,&layout);
        u32 bytes=format==0x86?8:16; std::vector<u8> blocks(12*bytes,0), pixels(8*4*6*4,0);
        for(u32 z=0;z<6;z++)for(u32 bx=0;bx<2;bx++) {
            u32 start=(z/4)*4, group=z<4?4:2;
            u32 index=start*2+bx*group+(z-start);
            u8* b=blocks.data()+index*bytes; u8* c=b+(format==0x86?0:8);
            u32 colour=colours[(z+bx)%6]; c[0]=(u8)colour;c[1]=(u8)(colour>>8);
            if(format==0x87)memset(b,(int)((z+1)*17),8);
            if(format==0x88){b[0]=(u8)(20+z*20);b[1]=0;}
        }
        CHECK(rsx_texture_decode_volume(pixels.data(),32,128,blocks.data(),8,4,6,&layout,0));
        for(u32 z=0;z<6;z++)for(u32 y=0;y<4;y++)for(u32 x=0;x<8;x++) {
            u32 c=colours[(z+x/4)%6]; u8* p=pixels.data()+(z*32+y*8+x)*4;
            CHECK(p[0]==((c>>11)&31)*255/31 && p[1]==((c>>5)&63)*255/63 && p[2]==(c&31)*255/31);
            CHECK(p[3]==(format==0x86?255:format==0x87?(z+1)*17:20+z*20));
        }
    }
    // Non-extreme RGB565 endpoints, interpolation, transparent BC1 and BC3 alpha branches.
    for(u32 format: {0x86u,0x88u}) {
        rsx_texture_layout(format,4,4,&layout);
        u8 block[16]={}, result[64]={}; u8* c=block+(format==0x86?0:8);
        c[0]=0x10;c[1]=0x84; // RGB565 -> (132,130,132)
        c[4]=0xe4; // first four indices 0,1,2,3
        if(format==0x88) {block[0]=20;block[1]=120;block[2]=0xd0;block[3]=0x0f;} // 0,2,7,7
        CHECK(rsx_texture_decode_volume(result,16,64,block,4,4,1,&layout,0));
        CHECK(result[0]==132 && result[1]==130 && result[2]==132);
        CHECK(result[8]==88 && result[9]==86 && result[12]==44);
        if(format==0x88) CHECK(result[3]==20 && result[7]==40 && result[11]==255);
        if(format==0x86) {
            memset(block,0,sizeof block);block[2]=0xff;block[3]=0xff;block[4]=3;
            CHECK(rsx_texture_decode_volume(result,16,64,block,4,4,1,&layout,0));
            CHECK(result[0]==0 && result[3]==0);
        }
    }
    puts("PASS: rectangular 3D Morton layout, pitched output, BC1/2/3 VTC depth groups and tail");
}
int main() {
    cpu_checks();
    ComPtr<ID3D11Device> device; ComPtr<ID3D11DeviceContext> context;
    hr(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_WARP,nullptr,0,nullptr,0,D3D11_SDK_VERSION,&device,nullptr,&context));
    const char* vertex="float4 main(uint i:SV_VertexID):SV_POSITION{return float4(i==1?3:-1,i==2?3:-1,0,1);}";
    ComPtr<ID3DBlob> code,errors; hr(D3DCompile(vertex,strlen(vertex),nullptr,nullptr,nullptr,"main","vs_5_0",0,0,&code,&errors));
    ComPtr<ID3D11VertexShader> vs;hr(device->CreateVertexShader(code->GetBufferPointer(),code->GetBufferSize(),nullptr,&vs));
    context->VSSetShader(vs.Get(),nullptr,0);context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    D3D11_RASTERIZER_DESC raster={};raster.FillMode=D3D11_FILL_SOLID;raster.CullMode=D3D11_CULL_NONE;
    ComPtr<ID3D11RasterizerState> rs;hr(device->CreateRasterizerState(&raster,&rs));context->RSSetState(rs.Get());
    D3D11_VIEWPORT viewport={0,0,1,1,0,1};context->RSSetViewports(1,&viewport);
    D3D11_TEXTURE2D_DESC rt={};rt.Width=rt.Height=rt.MipLevels=rt.ArraySize=1;rt.SampleDesc.Count=1;
    rt.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;rt.BindFlags=D3D11_BIND_RENDER_TARGET;
    ComPtr<ID3D11Texture2D> target,read;hr(device->CreateTexture2D(&rt,nullptr,&target));
    ComPtr<ID3D11RenderTargetView> rtv;hr(device->CreateRenderTargetView(target.Get(),nullptr,&rtv));
    rt.BindFlags=0;rt.Usage=D3D11_USAGE_STAGING;rt.CPUAccessFlags=D3D11_CPU_ACCESS_READ;hr(device->CreateTexture2D(&rt,nullptr,&read));
    ID3D11RenderTargetView* rawrt=rtv.Get();context->OMSetRenderTargets(1,&rawrt,nullptr);
    u8 pixels[32];for(int z=0;z<2;z++)for(int y=0;y<2;y++)for(int x=0;x<2;x++) {
        u8* p=pixels+((z*2+y)*2+x)*4;p[0]=(u8)(x*255);p[1]=(u8)(y*255);p[2]=(u8)(z*255);p[3]=255;
    }
    D3D11_TEXTURE3D_DESC volume={};volume.Width=volume.Height=volume.Depth=2;volume.MipLevels=1;
    volume.Format=DXGI_FORMAT_R8G8B8A8_UNORM;volume.BindFlags=D3D11_BIND_SHADER_RESOURCE;
    D3D11_SUBRESOURCE_DATA data={pixels,8,16};ComPtr<ID3D11Texture3D> texture;hr(device->CreateTexture3D(&volume,&data,&texture));
    ComPtr<ID3D11ShaderResourceView> srv;hr(device->CreateShaderResourceView(texture.Get(),nullptr,&srv));
    ID3D11ShaderResourceView* rawsrv=srv.Get();context->PSSetShaderResources(5,1,&rawsrv);
    D3D11_SAMPLER_DESC sampler={};sampler.Filter=D3D11_FILTER_MIN_MAG_MIP_POINT;
    sampler.AddressU=sampler.AddressV=sampler.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sampler.MaxLOD=D3D11_FLOAT32_MAX;
    ComPtr<ID3D11SamplerState> ss;hr(device->CreateSamplerState(&sampler,&ss));ID3D11SamplerState* rawss=ss.Get();context->PSSetSamplers(5,1,&rawss);
    unsigned count=0;
    for(u32 opcode: {0x17u,0x18u,0x2fu,0x31u})for(int z=0;z<2;z++)for(int y=0;y<2;y++)for(int x=0;x<2;x++) {
        u8 stream[32]={};word(stream,(opcode<<24)|(5u<<17)|(15u<<9)|1u);
        word(stream+4,2u|(0xe4u<<9)|(7u<<18));word(stream+8,2u);word(stream+12,2u);
        float coords[4]={(x+.5f)/2,(y+.5f)/2,(z+.5f)/2,1};
        if(opcode==0x18){for(int i=0;i<3;i++)coords[i]*=2;coords[3]=2;}
        for(int i=0;i<4;i++){u32 bits;memcpy(&bits,coords+i,4);word(stream+16+4*i,bits);}
        char text[32768];CHECK(rsx_fp_decompile_ex(stream,sizeof stream,0x40,1u<<(16+5),text,sizeof text)==1);
        errors.Reset();code.Reset();HRESULT r=D3DCompile(text,strlen(text),nullptr,nullptr,nullptr,"main","ps_5_0",0,0,&code,&errors);
        if(FAILED(r)&&errors)fwrite(errors->GetBufferPointer(),1,errors->GetBufferSize(),stderr);hr(r);
        ComPtr<ID3D11PixelShader> ps;hr(device->CreatePixelShader(code->GetBufferPointer(),code->GetBufferSize(),nullptr,&ps));
        context->PSSetShader(ps.Get(),nullptr,0);context->Draw(3,0);context->CopyResource(read.Get(),target.Get());
        D3D11_MAPPED_SUBRESOURCE mapped;hr(context->Map(read.Get(),0,D3D11_MAP_READ,0,&mapped));
        const float* p=(const float*)mapped.pData;
        CHECK(fabsf(p[0]-x)<.001f && fabsf(p[1]-y)<.001f && fabsf(p[2]-z)<.001f && fabsf(p[3]-1)<.001f);
        context->Unmap(read.Get(),0);count++;
    }
    printf("PASS: %u rendered volume lookups across TEX, TXP, TXL and TXB on unit 5\n",count);
}
