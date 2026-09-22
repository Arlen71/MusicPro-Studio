#ifndef UNICODE
#define UNICODE
#endif
#define _UNICODE
#include <windows.h>
#include <wchar.h>
#include <stdio.h>

/* Native launcher only: Python and media binaries remain application-local. */
static int fail(const wchar_t *detail) {
    MessageBoxW(NULL, detail, L"MusicPro Studio", MB_OK | MB_ICONERROR);
    return 1;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR args, int show) {
    (void)instance; (void)previous; (void)show;
    wchar_t root[32768], python[32768], boot[32768], command[65536];
    DWORD size = GetModuleFileNameW(NULL, root, 32768);
    if (size == 0 || size >= 32768) return fail(L"MusicPro papkasini aniqlab bo'lmadi.");
    wchar_t *slash = wcsrchr(root, L'\\');
    if (!slash) return fail(L"MusicPro papkasini aniqlab bo'lmadi.");
    *slash = 0;
    if (wcslen(root) > 30000) return fail(L"MusicPro papkasining manzili juda uzun.");
    swprintf(python, 32768, L"%ls\\runtime\\pythonw.exe", root);
    swprintf(boot, 32768, L"%ls\\app\\bootstrap.py", root);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES ||
        GetFileAttributesW(boot) == INVALID_FILE_ATTRIBUTES)
        return fail(L"Paket to'liq emas. MusicPro.exe bilan birga runtime va app papkalari ham kerak.\n\nZIP faylni to'liq oching yoki Setupni qayta ishga tushiring.");
    const wchar_t *mode = L"";
    if (wcscmp(args, L"--check") == 0) mode = L" --check";
    else if (wcscmp(args, L"--no-browser") == 0) mode = L" --no-browser";
    else if (*args) return fail(L"Noto'g'ri parametr. MusicPro.exe ni parametrsiz oching.");
    swprintf(command, 65536, L"\"%ls\" -X utf8 -B \"%ls\"%ls", python, boot, mode);
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                        NULL, root, &startup, &process)) {
        wchar_t message[1024];
        swprintf(message, 1024, L"MusicPro ishga tushmadi (Windows kodi: %lu).\n\nWindows 10/11 64-bit kerak. Paketni qayta ochib ko'ring. Antivirus xabari bo'lsa, tizim ma'muriga ko'rsating.", GetLastError());
        return fail(message);
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
