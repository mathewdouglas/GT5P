#include <stdint.h>
#include <stdio.h>
#include <assert.h>
typedef struct spu_context { int unused; } spu_context;
typedef void (*spu_lifted_fn)(spu_context*);
#include "registry.inc"
static void a(spu_context* c){(void)c;}
static void b(spu_context* c){(void)c;}
static void fast(spu_context* c){(void)c;}
int main(void){
 spu_begin_image(0);spu_register_function(0x100,a);
 spu_begin_image(4);spu_register_function(0x100,a);
 spu_begin_image(7);spu_register_function(0x100,b);
 assert(spu_override_function(4,0x100,0));assert(s_registry[1].fn==a);
 assert(!spu_override_function(0,0x100,fast));
 assert(!spu_override_function(9,0x100,fast));assert(!spu_override_function(4,0x200,fast));
 assert(spu_override_function(4,0x100,fast));
 assert(s_registry_count==3 && s_registry[0].fn==a && s_registry[1].fn==fast && s_registry[2].fn==b);
 puts("bootstrap registry replacement: passed");
}
