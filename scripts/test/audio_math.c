#include "spu_helpers.h"
#ifndef NAME
#error NAME is required
#endif
u128 NAME(u128 a,u128 b,u128 c,int op) {
    return op==0?spu_fma(a,b,c):op==1?spu_fms(a,b,c):spu_fnms(a,b,c);
}
