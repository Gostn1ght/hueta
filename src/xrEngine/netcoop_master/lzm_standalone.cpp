// CI only: the engine master as a console test program (the same sources the
// engine links; .github/workflows/lostzone-master-cpp.yml). Not in the engine.
// A crash prints its exception and a symbolized stack (built with /Zi).
#include "lzm_config.h"

#include <windows.h>
#include <dbghelp.h>

#include <cstdio>

#pragma comment(lib, "dbghelp.lib")

static LONG WINAPI report(EXCEPTION_POINTERS* info)
{
    FILE* output=stderr;FILE* crash=nullptr;
    wchar_t executable[4096]{};GetModuleFileNameW(nullptr,executable,4096);
    wchar_t* basename=wcsrchr(executable,L'\\');
    if(basename && _wcsicmp(basename+1,L"LostZoneMaster.exe")==0) {
        *basename=0;wchar_t* parent=wcsrchr(executable,L'\\');
        if(parent) {
            *parent=0;std::wstring directory=std::wstring(executable)+L"\\appdata";
            CreateDirectoryW(directory.c_str(),nullptr);directory+=L"\\master";CreateDirectoryW(directory.c_str(),nullptr);
            directory+=L"\\logs";CreateDirectoryW(directory.c_str(),nullptr);
            SYSTEMTIME utc{};GetSystemTime(&utc);wchar_t filename[128];
            swprintf_s(filename,L"\\master_crash_%04u%02u%02u_%02u%02u%02u_%lu.log",utc.wYear,utc.wMonth,utc.wDay,utc.wHour,utc.wMinute,utc.wSecond,GetCurrentProcessId());
            crash=_wfopen((directory+filename).c_str(),L"wb");if(crash) output=crash;
        }
    }
    HANDLE process = GetCurrentProcess(), thread = GetCurrentThread();
    SymSetOptions(SYMOPT_LOAD_LINES | SYMOPT_UNDNAME);
    SymInitialize(process, nullptr, TRUE);
    fprintf(output, "[diag][crash] pid=%lu code=0x%08lx address=%p\n", GetCurrentProcessId(),info->ExceptionRecord->ExceptionCode, info->ExceptionRecord->ExceptionAddress);
    CONTEXT context = *info->ContextRecord;
    STACKFRAME64 frame{};
    frame.AddrPC.Offset = context.Rip;
    frame.AddrFrame.Offset = context.Rbp;
    frame.AddrStack.Offset = context.Rsp;
    frame.AddrPC.Mode = frame.AddrFrame.Mode = frame.AddrStack.Mode = AddrModeFlat;
    for (int i = 0; i < 40 && StackWalk64(IMAGE_FILE_MACHINE_AMD64, process, thread, &frame, &context, nullptr,
                                           SymFunctionTableAccess64, SymGetModuleBase64, nullptr); ++i)
    {
        char buffer[sizeof(SYMBOL_INFO) + 256] = {};
        auto symbol = (SYMBOL_INFO*)buffer;
        symbol->SizeOfStruct = sizeof(SYMBOL_INFO);
        symbol->MaxNameLen = 255;
        DWORD64 displacement = 0;
        IMAGEHLP_LINE64 line{ sizeof(line) };
        DWORD column = 0;
        const char* name = SymFromAddr(process, frame.AddrPC.Offset, &displacement, symbol) ? symbol->Name : "?";
        if (SymGetLineFromAddr64(process, frame.AddrPC.Offset, &column, &line))
            fprintf(output, "  #%d %s  %s:%lu\n", i, name, line.FileName, line.LineNumber);
        else
            fprintf(output, "  #%d %s  %p\n", i, name, (void*)frame.AddrPC.Offset);
    }
    fflush(output);if(crash) fclose(crash);
    return EXCEPTION_EXECUTE_HANDLER;
}

int wmain(int argc, wchar_t** argv)
{
    SetUnhandledExceptionFilter(report);
    std::vector<std::wstring> args(argv + 1, argv + argc);
#ifdef LZM_TEST_FIXTURES
    int lzm_host_fixture(const std::wstring&);
    int lzm_storage_fixture(const std::wstring&);
    if(args.size()==2 && args[0]==L"host-selftest") return lzm_host_fixture(args[1]);
    if(args.size()==2 && args[0]==L"storage-selftest") return lzm_storage_fixture(args[1]);
#endif
    if (!args.empty() && args[0] == L"-netcoop_master") args.erase(args.begin());
    return lzm::master_main(args);
}
