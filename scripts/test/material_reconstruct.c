/* Isolated native descriptor replacement; no D3D device or game. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <d3d12.h>
#include "rsx_material_reconstruct.h"
#include "rsx_pass_reconstruct.h"
static void write_state(const char* dir,const char* text) {
    char path[640];snprintf(path,sizeof path,"%s/material.state",dir);
    FILE* f=fopen(path,"wb");assert(f);fwrite(text,1,strlen(text),f);fclose(f);
}
int main(int argc,char** argv) {
    assert(argc==2);
    D3D12_GRAPHICS_PIPELINE_STATE_DESC pd={0};
    pd.NumRenderTargets=3;pd.DepthStencilState.DepthEnable=TRUE;
    pd.RasterizerState.CullMode=D3D12_CULL_MODE_FRONT;
    pd.RTVFormats[0]=DXGI_FORMAT_R8G8B8A8_UNORM;
    pd.BlendState.RenderTarget[0].SrcBlend=D3D12_BLEND_INV_DEST_COLOR;
    D3D12_GRAPHICS_PIPELINE_STATE_DESC before=pd;
    const char* bad[]={"", "GT5P_MATERIAL_V1 0 f 30000000 extra", "GT5P_MATERIAL_V1 0 10 30000000",
        "GT5P_MATERIAL_V1 1 f 30000000", "GT5P_MATERIAL_V1 80000000 f 30000000",
        "GT5P_MATERIAL_V1 0 f 30000001", "GT5P_MATERIAL_V2 0 f 30000000"};
    for(unsigned i=0;i<sizeof bad/sizeof *bad;i++) {
        write_state(argv[1],bad[i]);assert(!pso_material_apply(argv[1],&pd));assert(!memcmp(&pd,&before,sizeof pd));
    }
    write_state(argv[1],"GT5P_MATERIAL_V1 0 e b0000000\n");
    assert(pso_material_apply(argv[1],&pd));
    for(unsigned i=0;i<3;i++) {
        assert(!pd.BlendState.RenderTarget[i].BlendEnable);
        assert(pd.BlendState.RenderTarget[i].SrcBlend==D3D12_BLEND_ONE);
        assert(pd.BlendState.RenderTarget[i].DestBlend==D3D12_BLEND_ZERO);
        assert(pd.BlendState.RenderTarget[i].RenderTargetWriteMask==14);
    }
    assert(pd.DepthStencilState.DepthFunc==D3D12_COMPARISON_FUNC_LESS_EQUAL);
    assert(pd.DepthStencilState.DepthWriteMask==D3D12_DEPTH_WRITE_MASK_ZERO);
    assert(pd.RasterizerState.CullMode==before.RasterizerState.CullMode);
    assert(pd.RTVFormats[0]==before.RTVFormats[0]);
    pd=before;pd.DepthStencilState.StencilEnable=TRUE;before=pd;
    assert(!pso_material_apply(argv[1],&pd));assert(!memcmp(&pd,&before,sizeof pd));
    /* Start with deliberately wrong face state; independent replacements must
     * overwrite it and preserve every unrelated descriptor byte. */
    const unsigned keys[]={0,1,5};
    for(unsigned i=0;i<3;i++) {
        pd=before;pd.RasterizerState.CullMode=D3D12_CULL_MODE_FRONT;
        pd.RasterizerState.FrontCounterClockwise=(keys[i]&4)?FALSE:TRUE;
        D3D12_GRAPHICS_PIPELINE_STATE_DESC expected=pd;
        expected.RasterizerState.CullMode=keys[i]?D3D12_CULL_MODE_BACK:D3D12_CULL_MODE_NONE;
        expected.RasterizerState.FrontCounterClockwise=(keys[i]&4)?TRUE:FALSE;
        char path[640];snprintf(path,sizeof path,"%s/pass.state",argv[1]);
        FILE* f=fopen(path,"wb");assert(f);fprintf(f,"GT5P_PASS_V1 %x\n",keys[i]);fclose(f);
        assert(pso_pass_apply(argv[1],&pd));assert(!memcmp(&pd,&expected,sizeof pd));
    }
    const char* invalid_pass[]={"", "GT5P_PASS_V1 2", "GT5P_PASS_V1 4", "GT5P_PASS_V1 ffffffff",
        "GT5P_PASS_V1 5 extra", "GT5P_PASS_V2 5", "GT5P_PASS_V1 5\0trailing", "GT5P_PASS_V1 100000005"};
    for(unsigned i=0;i<sizeof invalid_pass/sizeof *invalid_pass;i++) {
        char path[640];snprintf(path,sizeof path,"%s/pass.state",argv[1]);
        FILE* f=fopen(path,"wb");assert(f);
        fwrite(invalid_pass[i],1,i==6?sizeof "GT5P_PASS_V1 5\0trailing"-1:strlen(invalid_pass[i]),f);fclose(f);
        before=pd;assert(!pso_pass_apply(argv[1],&pd));assert(!memcmp(&pd,&before,sizeof pd));
    }
    puts("Conditional pass descriptor replacement and malformed pass rejection passed");
    puts("Partial descriptor replacement, MRT fields, untouched pass fields and invalid-input rejection passed");
    return 0;
}
