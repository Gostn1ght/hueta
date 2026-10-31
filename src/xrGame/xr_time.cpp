#include "stdafx.h"
#include "xr_time.h"
#include "ui/UIInventoryUtilities.h"
#include "level.h"
#include "date_time.h"
#include "ai_space.h"
#include "alife_simulator.h"
#include "alife_time_manager.h"

#define sec2ms		1000
#define min2ms		60*sec2ms
#define hour2ms		60*min2ms
#define day2ms		24*hour2ms

extern LPCSTR alife_section;

ALife::_TIME_ID __game_time()
{
	// start_game_callback runs after set_alife(this), but BEFORE reload()
	// creates the time manager. A non-null simulator alone is not readiness.
	if (ai().get_alife() && ai().alife().initialized())
		return ai().alife().time().game_time();
	if (g_pGameLevel && Level().game)
		return Level().GetGameTime();

	// Read-only bootstrap calendar: never create/reset the persistent clock
	// here. Once the world is loaded, its committed time takes precedence.
	u32 year = 2018, month = 1, day = 1, hour = 12, minute = 0, second = 0;
	if (pSettings && pSettings->line_exist(alife_section, "start_date"))
	{
		u32 y = 0, m = 0, d = 0;
		if (sscanf(pSettings->r_string(alife_section, "start_date"), "%u.%u.%u", &d, &m, &y) == 3 &&
			y >= 1 && y <= 9999 && m >= 1 && m <= 12)
		{
			const u32 lengths[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
			const bool leap = y % 400 == 0 || (y % 4 == 0 && y % 100 != 0);
			if (d >= 1 && d <= lengths[m - 1] + (m == 2 && leap ? 1u : 0u))
			{ year = y; month = m; day = d; }
		}
	}
	if (pSettings && pSettings->line_exist(alife_section, "start_time"))
	{
		u32 h = 0, m = 0, s = 0;
		if (sscanf(pSettings->r_string(alife_section, "start_time"), "%u:%u:%u", &h, &m, &s) == 3 &&
			h < 24 && m < 60 && s < 60)
		{ hour = h; minute = m; second = s; }
	}
	static bool reported = false;
	if (!reported)
	{
		reported = true;
		Msg("[diag][clock] script requested time before world initialization; using configured bootstrap calendar");
	}
	return generate_time(year, month, day, hour, minute, second);
}

u32 get_time()
{
	return u32(__game_time() & u32(-1));
}

xrTime get_time_struct()
{
	return xrTime(__game_time());
}

LPCSTR xrTime::dateToString(int mode)
{
	return *InventoryUtilities::GetDateAsString(m_time, (InventoryUtilities::EDatePrecision)mode);
}

LPCSTR xrTime::timeToString(int mode)
{
	return *InventoryUtilities::GetTimeAsString(m_time, (InventoryUtilities::ETimePrecision)mode);
}

void xrTime::add(const xrTime& other)
{
	m_time += other.m_time;
}

void xrTime::sub(const xrTime& other)
{
	if (*this > other)
		m_time -= other.m_time;
	else
		m_time = 0;
}

void xrTime::setHMS(int h, int m, int s)
{
	m_time = 0;
	m_time += generate_time(1, 1, 1, h, m, s);
}

void xrTime::setHMSms(int h, int m, int s, int ms)
{
	m_time = 0;
	m_time += generate_time(1, 1, 1, h, m, s, ms);
}

void xrTime::set(int y, int mo, int d, int h, int mi, int s, int ms)
{
	m_time = 0;
	m_time += generate_time(y, mo, d, h, mi, s, ms);
}

void xrTime::get(u32& y, u32& mo, u32& d, u32& h, u32& mi, u32& s, u32& ms)
{
	split_time(m_time, y, mo, d, h, mi, s, ms);
}

float xrTime::diffSec(const xrTime& other)
{
	if (*this > other)
		return (m_time - other.m_time) / (float)sec2ms;
	return ((other.m_time - m_time) / (float)sec2ms) * (-1.0f);
}
