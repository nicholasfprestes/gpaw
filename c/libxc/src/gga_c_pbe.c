/*
 Copyright (C) 2006-2007 M.A.L. Marques

 This program is free software; you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation; either version 3 of the License, or
 (at your option) any later version.
  
 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.
  
 You should have received a copy of the GNU General Public License
 along with this program; if not, write to the Free Software
 Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
*/

#include <stdio.h>
#include <stdlib.h>
#include <assert.h>

#include "util.h"

/************************************************************************
 Implements Perdew, Burke & Ernzerhof Generalized Gradient Approximation
 correlation functional.

 I based this implementation on a routine from L.C. Balbas and J.M. Soler
************************************************************************/

#define XC_GGA_C_PBE          130 /* Perdew, Burke & Ernzerhof correlation          */
#define XC_GGA_C_PBE_SOL      133 /* Perdew, Burke & Ernzerhof correlation SOL      */
#define XC_GGA_C_XPBE         136 /* xPBE reparametrization by Xu & Goddard         */
#define XC_GGA_C_PBE_REVTPSS  137 /* PBE for revTPSS                                */

static const FLOAT beta[4]  = {
  0.06672455060314922,  /* original PBE */
  0.046,                /* PBE sol      */
  0.089809,
  0.06672455060314922  /* PBE for revTPSS */
};
static FLOAT gamm[4];


static void gga_c_pbe_init(void *p_)
{
  XC(gga_type) *p = (XC(gga_type) *)p_;

  p->lda_aux = (XC(lda_type) *) malloc(sizeof(XC(lda_type)));
  XC(lda_init)(p->lda_aux, XC_LDA_C_PW_MOD, p->nspin);

  switch(p->info->number){
  case XC_GGA_C_XPBE:
    gamm[2] = beta[2]*beta[2]/(2.0*0.197363);
    break;
  case XC_GGA_C_PBE_REVTPSS:
  case XC_GGA_C_PBE_SOL:
  default: /* the original PBE */
    gamm[0] = gamm[1] = gamm[3] = (1.0 - log(2.0))/(M_PI*M_PI);
    break;
  }  
}


static void gga_c_pbe_end(void *p_)
{
  XC(gga_type) *p = (XC(gga_type) *)p_;

  free(p->lda_aux);
}


static inline void 
pbe_eq8(int func, int order, FLOAT rs, FLOAT ecunif, FLOAT phi, 
	FLOAT *A, FLOAT *dec, FLOAT *dphi, FLOAT *drs,
	FLOAT *dec2, FLOAT *decphi, FLOAT *dphi2)
{
  FLOAT phi3, f1, df1dphi, d2f1dphi2, f2, f3, dx, d2x;

  phi3 = POW(phi, 3);
  f1   = ecunif/(gamm[func]*phi3);
  f2   = exp(-f1);
  f3   = f2 - 1.0;

  *A   = beta[func]/(gamm[func]*f3);
  if(func == 3) *A *= (1. + 0.1*rs)/(1. + 0.1778*rs);

  if(order < 1) return;

  df1dphi = -3.0*f1/phi;
  dx      = (*A)*f2/f3;

  *dec    = dx/(gamm[func]*phi3);
  *dphi   = dx*df1dphi;
  *drs    = 0.0;
  if(func == 3) *drs = beta[func]*((0.1-0.1778)/POW(1+0.1778*rs,2))/(gamm[func]*f3);

  if(func ==3) return;
  if(order < 2) return;

  d2f1dphi2 = -4.0*df1dphi/phi;
  d2x       = dx*(2.0*f2 - f3)/f3;
  *dphi2    = d2x*df1dphi*df1dphi + dx*d2f1dphi2;
  *decphi   = (d2x*df1dphi*f1 + dx*df1dphi)/ecunif;
  *dec2     = d2x/(gamm[func]*gamm[func]*phi3*phi3);
}


static void 
pbe_eq7(int func, int order, FLOAT rs, FLOAT phi, FLOAT t, FLOAT A, 
	FLOAT *H, FLOAT *dphi, FLOAT *drs, FLOAT *dt, FLOAT *dA,
	FLOAT *d2phi, FLOAT *d2phit, FLOAT *d2phiA, FLOAT *d2t2, FLOAT *d2tA, FLOAT *d2A2)
{
  FLOAT t2, phi3, f1, f2, f3;
  FLOAT df1dt, df2drs, df2dt, df1dA, df2dA;
  FLOAT d2f1dt2, d2f2dt2, d2f2dA2, d2f1dtA, d2f2dtA;

  t2   = t*t;
  phi3 = POW(phi, 3);

  f1 = t2 + A*t2*t2;
  f3 = 1.0 + A*f1;
  f2 = beta[func]*f1/(gamm[func]*f3);
  if(func == 3) f2 *= (1. + 0.1*rs)/(1. + 0.1778*rs);

  *H = gamm[func]*phi3*log(1.0 + f2);

  if(order < 1) return;

  *dphi  = 3.0*(*H)/phi;
    
  df1dt  = t*(2.0 + 4.0*A*t2);
  df2dt  = beta[func]/(gamm[func]*f3*f3) * df1dt;
  if(func == 3) df2dt*=(1. + 0.1*rs)/(1. + 0.1778*rs);
  *dt    = gamm[func]*phi3*df2dt/(1.0 + f2);
    
  df1dA  = t2*t2;
  df2dA  = beta[func]/(gamm[func]*f3*f3) * (df1dA - f1*f1);
  if(func == 3) df2dA *= (1. + 0.1*rs)/(1. + 0.1778*rs);
  *dA    = gamm[func]*phi3*df2dA/(1.0 + f2);

  df2drs = 0.0;
  *drs = 0.0;
  if(func == 3){
 	  df2drs = beta[func]*((0.1-0.1778)/POW(1+0.1778*rs,2))*f1/(gamm[func]*f3);
	  *drs = gamm[func]*phi3*df2drs/(1.0 + f2);
  }

  if(func ==3) return;
  if(order < 2) return;

  *d2phi  = 2.0*(*dphi)/phi;
  *d2phit = 3.0*(*dt)/phi;
  *d2phiA = 3.0*(*dA)/phi;

  d2f1dt2 = 2.0 + 4.0*3.0*A*t2;
  d2f2dt2 = beta[func]/(gamm[func]*f3*f3) * (d2f1dt2 - 2.0*A/f3*df1dt*df1dt);
  *d2t2   = gamm[func]*phi3*(d2f2dt2*(1.0 + f2) - df2dt*df2dt)/((1.0 + f2)*(1.0 + f2));

  d2f1dtA = 4.0*t*t2;
  d2f2dtA = beta[func]/(gamm[func]*f3*f3) * 
    (d2f1dtA - 2.0*df1dt*(f1 + A*df1dA)/f3);
  *d2tA   = gamm[func]*phi3*(d2f2dtA*(1.0 + f2) - df2dt*df2dA)/((1.0 + f2)*(1.0 + f2));

  d2f2dA2 = beta[func]/(gamm[func]*f3*f3*f3) *(-2.0)*(2.0*f1*df1dA - f1*f1*f1 + A*df1dA*df1dA);
  *d2A2   = gamm[func]*phi3*(d2f2dA2*(1.0 + f2) - df2dA*df2dA)/((1.0 + f2)*(1.0 + f2));
}

static void 
gga_c_pbe(const void *p_, const FLOAT *rho, const FLOAT *sigma,
	  FLOAT *e, FLOAT *vrho, FLOAT *vsigma,
	  FLOAT *v2rho2, FLOAT *v2rhosigma, FLOAT *v2sigma2)
{
  XC(gga_type) *p = (XC(gga_type) *)p_;
  XC(perdew_t) pt;

  int func, order;
  FLOAT me;
  FLOAT A, dAdec, dAdphi, dAdrs, d2Adec2, d2Adecphi, d2Adphi2;
  FLOAT H, dHdphi, dHdrs, dHdt, dHdA, d2Hdphi2, d2Hdphit, d2HdphiA, d2Hdt2, d2HdtA, d2HdA2;

  switch(p->info->number){
  case XC_GGA_C_PBE_SOL:     func = 1; break;
  case XC_GGA_C_XPBE:        func = 2; break;
  case XC_GGA_C_PBE_REVTPSS: func = 3; break;
  default:                   func = 0; /* original PBE */
  }

  order = 0;
  if(vrho   != NULL) order = 1;
  if(v2rho2 != NULL) order = 2;

  XC(perdew_params)(p, rho, sigma, order, &pt);


  pbe_eq8(func, order, pt.rs, pt.ecunif, pt.phi,
	  &A, &dAdec, &dAdphi, &dAdrs, &d2Adec2, &d2Adecphi, &d2Adphi2);

  pbe_eq7(func, order, pt.rs, pt.phi, pt.t, A, 
	  &H, &dHdphi, &dHdrs, &dHdt, &dHdA, &d2Hdphi2, &d2Hdphit, &d2HdphiA, &d2Hdt2, &d2HdtA, &d2HdA2);

  me = pt.ecunif + H;
  if(e != NULL) *e = me;

  if(order >= 1){
    pt.dphi    = dHdphi + dHdA*dAdphi;
	pt.drs     = dHdrs + dHdA*dAdrs;
    pt.dt      = dHdt;
    pt.decunif = 1.0 + dHdA*dAdec;
  }

  if(order >= 2){
    pt.d2phi2      = d2Hdphi2 + 2.0*d2HdphiA*dAdphi + dHdA*d2Adphi2 + d2HdA2*dAdphi*dAdphi;
    pt.d2phit      = d2Hdphit + d2HdtA*dAdphi;
    pt.d2phiecunif = d2HdphiA*dAdec + d2HdA2*dAdphi*dAdec + dHdA*d2Adecphi;

    pt.d2t2        = d2Hdt2;
    pt.d2tecunif   = d2HdtA*dAdec;

    pt.d2ecunif2   = d2HdA2*dAdec*dAdec + dHdA*d2Adec2;
  }

  XC(perdew_potentials)(&pt, rho, me, order, vrho, vsigma, v2rho2, v2rhosigma, v2sigma2);
}


const XC(func_info_type) XC(func_info_gga_c_pbe) = {
  XC_GGA_C_PBE,
  XC_CORRELATION,
  "Perdew, Burke & Ernzerhof",
  XC_FAMILY_GGA,
  "JP Perdew, K Burke, and M Ernzerhof, Phys. Rev. Lett. 77, 3865 (1996)\n"
  "JP Perdew, K Burke, and M Ernzerhof, Phys. Rev. Lett. 78, 1396(E) (1997)",
  XC_PROVIDES_EXC | XC_PROVIDES_VXC | XC_PROVIDES_FXC,
  gga_c_pbe_init,
  gga_c_pbe_end,
  NULL,            /* this is not an LDA                   */
  gga_c_pbe,
};

const XC(func_info_type) XC(func_info_gga_c_pbe_sol) = {
  XC_GGA_C_PBE_SOL,
  XC_CORRELATION,
  "Perdew, Burke & Ernzerhof SOL",
  XC_FAMILY_GGA,
  "JP Perdew, et al, Phys. Rev. Lett. 100, 136406 (2008)",
  XC_PROVIDES_EXC | XC_PROVIDES_VXC | XC_PROVIDES_FXC,
  gga_c_pbe_init,
  gga_c_pbe_end,
  NULL,            /* this is not an LDA                   */
  gga_c_pbe,
};

const XC(func_info_type) XC(func_info_gga_c_xpbe) = {
  XC_GGA_C_XPBE,
  XC_CORRELATION,
  "Extended PBE by Xu & Goddard III",
  XC_FAMILY_GGA,
  "X Xu and WA Goddard III, J. Chem. Phys. 121, 4068 (2004)",
  XC_PROVIDES_EXC | XC_PROVIDES_VXC | XC_PROVIDES_FXC,
  gga_c_pbe_init,
  gga_c_pbe_end,
  NULL,            /* this is not an LDA                   */
  gga_c_pbe,
};
const XC(func_info_type) XC(func_info_gga_c_pbe_revtpss) = {
  XC_GGA_C_PBE_REVTPSS,
  XC_CORRELATION,
  "Perdew, Burke & Ernzerhof for TPSS",
  XC_FAMILY_GGA,
  "Perdew, Ruzsinszky, Csonka, Constantin and Sun PRL 103 026403 (2009)",
  XC_PROVIDES_EXC | XC_PROVIDES_VXC | XC_PROVIDES_FXC,
  gga_c_pbe_init,
  gga_c_pbe_end,
  NULL,            /* this is not an LDA                   */
  gga_c_pbe,
};
