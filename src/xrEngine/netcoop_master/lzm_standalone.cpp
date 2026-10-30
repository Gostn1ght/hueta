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
    HANDLE process = GetCurrentProcess(), thread = GetCurrentThread();
    SymSetOptions(SYMOPT_LOAD_LINES | SYMOPT_UNDNAME);
    SymInitialize(process, nullptr, TRUE);
    fprintf(stderr, "CRASH 0x%08lx at %p\n", info->ExceptionRecord->ExceptionCode, info->ExceptionRecord->ExceptionAddress);
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
            fprintf(stderr, "  #%d %s  %s:%lu\n", i, name, line.FileName, line.LineNumber);
        else
            fprintf(stderr, "  #%d %s  %p\n", i, name, (void*)frame.AddrPC.Offset);
    }
    fflush(stderr);
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
