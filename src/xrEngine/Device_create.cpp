#include "stdafx.h"

//#include "resourcemanager.h"
#include "../Include/xrRender/DrawUtils.h"
//#include "xr_effgamma.h"
#include "render.h"
#include "dedicated_server_only.h"
#include "../xrcdb/xrxrc.h"

extern ENGINE_API bool g_dedicated_server;

//#include "securom_api.h"

extern XRCDB_API BOOL* cdb_bDebug;

void SetupGPU(IRenderDeviceRender* pRender)
{
	// Command line
	char* lpCmdLine = Core.Params;

	BOOL bForceGPU_SW;
	BOOL bForceGPU_NonPure;
	BOOL bForceGPU_REF;

	if (strstr(lpCmdLine, "-gpu_sw") != NULL) bForceGPU_SW = TRUE;
	else bForceGPU_SW = FALSE;
	if (strstr(lpCmdLine, "-gpu_nopure") != NULL) bForceGPU_NonPure = TRUE;
	else bForceGPU_NonPure = FALSE;
	if (strstr(lpCmdLine, "-gpu_ref") != NULL) bForceGPU_REF = TRUE;
	else bForceGPU_REF = FALSE;

	pRender->SetupGPU(bForceGPU_SW, bForceGPU_NonPure, bForceGPU_REF);
}

void CRenderDevice::_SetupStates()
{
	// General Render States
	mView.identity();
	mProject.identity();
	mFullTransform.identity();
	vCameraPosition.set(0, 0, 0);
	vCameraDirection.set(0, 0, 1);
	vCameraTop.set(0, 1, 0);
	vCameraRight.set(1, 0, 0);

	m_pRender->SetupStates();

	/*
	HW.Caps.Update ();
	for (u32 i=0; i<HW.Caps.raster.dwStages; i++) {
	float fBias = -.5f ;
	CHK_DX(HW.pDevice->SetSamplerState ( i, D3DSAMP_MAXANISOTROPY, 4 ));
	CHK_DX(HW.pDevice->SetSamplerState ( i, D3DSAMP_MIPMAPLODBIAS, *((LPDWORD) (&fBias))));
	CHK_DX(HW.pDevice->SetSamplerState ( i, D3DSAMP_MINFILTER, D3DTEXF_LINEAR ));
	CHK_DX(HW.pDevice->SetSamplerState ( i, D3DSAMP_MAGFILTER, D3DTEXF_LINEAR ));
	CHK_DX(HW.pDevice->SetSamplerState ( i, D3DSAMP_MIPFILTER, D3DTEXF_LINEAR ));
	}
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_DITHERENABLE, TRUE ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_COLORVERTEX, TRUE ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_ZENABLE, TRUE ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_SHADEMODE, D3DSHADE_GOURAUD ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_CULLMODE, D3DCULL_CCW ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_ALPHAFUNC, D3DCMP_GREATER ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_LOCALVIEWER, TRUE ));

	CHK_DX(HW.pDevice->SetRenderState( D3DRS_DIFFUSEMATERIALSOURCE, D3DMCS_MATERIAL ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_SPECULARMATERIALSOURCE,D3DMCS_MATERIAL ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_AMBIENTMATERIALSOURCE, D3DMCS_MATERIAL ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_EMISSIVEMATERIALSOURCE,D3DMCS_COLOR1 ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_MULTISAMPLEANTIALIAS, FALSE ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_NORMALIZENORMALS, TRUE ));

	if (psDeviceFlags.test(rsWireframe)) { CHK_DX(HW.pDevice->SetRenderState( D3DRS_FILLMODE, D3DFILL_WIREFRAME )); }
	else { CHK_DX(HW.pDevice->SetRenderState( D3DRS_FILLMODE, D3DFILL_SOLID )); }

	// ******************** Fog parameters
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_FOGCOLOR, 0 ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_RANGEFOGENABLE, FALSE ));
	if (HW.Caps.bTableFog) {
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_FOGTABLEMODE, D3DFOG_LINEAR ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_FOGVERTEXMODE, D3DFOG_NONE ));
	} else {
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_FOGTABLEMODE, D3DFOG_NONE ));
	CHK_DX(HW.pDevice->SetRenderState( D3DRS_FOGVERTEXMODE, D3DFOG_LINEAR ));
	}
	*/
}

/*
void CRenderDevice::_Create (LPCSTR shName)
{
Memory.mem_compact ();

// after creation
b_is_Ready = TRUE;
_SetupStates ();

// Signal everyone - device created
RCache.OnDeviceCreate ();
Gamma.Update ();
Resources->OnDeviceCreate (shName);
::Render->create ();
Statistic->OnDeviceCreate ();

#ifndef DEDICATED_SERVER
m_WireShader.create ("editor\\wire");
m_SelectionShader.create ("editor\\selection");

DU.OnDeviceCreate ();
#endif

dwFrame = 0;
}
*/

void CRenderDevice::_Create(LPCSTR shName)
{
	Memory.mem_compact();

	// after creation
	b_is_Ready = TRUE;
	_SetupStates();

	m_pRender->OnDeviceCreate(shName);
	m_imgui.OnDeviceCreate();
	dwFrame = 0;
}

/*
void CRenderDevice::Create ()
{
if (b_is_Ready) return; // prevent double call
Statistic = xr_new<CStats>();
Log ("Starting RENDER device...");


HW.CreateDevice (m_hWnd);
dwWidth = HW.DevPP.BackBufferWidth ;
dwHeight = HW.DevPP.BackBufferHeight ;
fWidth_2 = float(dwWidth/2) ;
fHeight_2 = float(dwHeight/2) ;
fFOV = 90.f;
fASPECT = 1.f;

string_path fname;
FS.update_path (fname,"$game_data$","shaders.xr");

//////////////////////////////////////////////////////////////////////////
Resources = xr_new<CResourceManager> ();
_Create (fname);

PreCache (0);
}
*/

void CRenderDevice::ConnectToRender()
{
	if (!m_pRender)
		m_pRender = RenderFactory->CreateRenderDeviceRender();
}

extern u32 g_screenmode;
extern void GetMonitorResolution(u32& horizontal, u32& vertical);
extern void GetMonitorPosition(int& x, int& y);

PROTECT_API void CRenderDevice::Create()
{
	//SECUROM_MARKER_SECURITY_ON(4)

	if (b_is_Ready) return; // prevent double call

	u32 w, h;
	GetMonitorResolution(w, h);
	int monX, monY;
	GetMonitorPosition(monX, monY);
	// Lost Zone: a location server is an ordinary desktop window. The game's
	// fullscreen/borderless setting made it cover the whole monitor, on top
	// of everything, with no frame to move it (owner 2026-10-12). Several
	// maps run at once: each window is offset by its port.
	int server_x = monX, server_y = monY;
	const bool background_server = g_dedicated_server && strstr(Core.Params, "-netcoop_background");
	if (g_dedicated_server)
	{
		g_screenmode = 0;
		psCurrentVidMode[0] = _max(900u, _min(1280u, w * 55 / 100));
		psCurrentVidMode[1] = _max(560u, _min(800u, h * 60 / 100));
		LPCSTR port_arg = strstr(Core.Params, "-netport ");
		const int port = port_arg ? atoi(port_arg + 9) : 0;
		const int step = (port / 2) % 10;
		server_x = monX + int(w - psCurrentVidMode[0]) / 2 + (step - 5) * 32;
		server_y = monY + int(h - psCurrentVidMode[1]) / 2 + (step - 5) * 24;
		server_x = _max(monX, server_x);
		server_y = _max(monY, server_y);
	}
	if (psCurrentVidMode[0] == 0 || psCurrentVidMode[1] == 0)
	{
		psCurrentVidMode[0] = w;
		psCurrentVidMode[1] = h;
	}

	DWORD style;
	if (g_screenmode == 0)
	{
		style = WS_OVERLAPPEDWINDOW;
		w = psCurrentVidMode[0];
		h = psCurrentVidMode[1];
	}
	else
	{
		style = WS_POPUP;
	}
	// The dedicated text console is a child window. The swap-chain host must
	// clip its client area or DXGI paints black over the log and status panel.
	if (g_dedicated_server)
		style |= WS_CLIPCHILDREN;

	SetWindowLongPtr(m_hWnd, GWL_STYLE, style);
	if (g_dedicated_server)
	{
		RECT frame = {0, 0, LONG(w), LONG(h)};
		AdjustWindowRect(&frame, style, FALSE);
		SetWindowPos(m_hWnd, HWND_NOTOPMOST, server_x, server_y, frame.right - frame.left, frame.bottom - frame.top,
		             SWP_FRAMECHANGED | SWP_NOACTIVATE | (background_server ? 0 : SWP_SHOWWINDOW));
		if (background_server) ShowWindow(m_hWnd, SW_HIDE);
	}
	else
		SetWindowPos(m_hWnd, HWND_TOP, monX, monY, w, h, SWP_FRAMECHANGED);

	Statistic = xr_new<CStats>();
#ifdef DEBUG
    cdb_clRAY = &Statistic->clRAY; // total: ray-testing
    cdb_clBOX = &Statistic->clBOX; // total: box query
    cdb_clFRUSTUM = &Statistic->clFRUSTUM; // total: frustum query
    cdb_bDebug = &bDebug;
#endif

	if (!m_pRender)
		m_pRender = RenderFactory->CreateRenderDeviceRender();
	SetupGPU(m_pRender);
	Log("Starting RENDER device...");


	fFOV = 90.f;
	fASPECT = 1.f;
	m_pRender->Create(
		m_hWnd,
		dwWidth,
		dwHeight,
		fWidth_2,
		fHeight_2,
		true
	);

	DisableProcessWindowsGhosting();

	RECT winRect;
	GetClientRect(m_hWnd, &winRect);
	clientWidth = winRect.right;
	clientHeight = winRect.bottom;
	MapWindowPoints(m_hWnd, nullptr, reinterpret_cast<LPPOINT>(&winRect), 2);
	if (g_dedicated_server)
		ClipCursor(nullptr);
	else
		ClipCursor(&winRect);
	if (!g_dedicated_server) SetActiveWindow(m_hWnd);

	string_path fname;
	FS.update_path(fname, "$game_data$", "shaders.xr");

	//////////////////////////////////////////////////////////////////////////
	_Create(fname);

	PreCache(0, false, false);

	//SECUROM_MARKER_SECURITY_OFF(4)
}
