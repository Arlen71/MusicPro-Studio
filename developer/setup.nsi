Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "LogicLib.nsh"
!ifndef APPDIR
 !error "APPDIR must point to the validated portable bundle"
!endif
!ifndef OUTFILE
 !define OUTFILE "MusicPro_Studio_1.8_Setup.exe"
!endif
Name "MusicPro Studio 1.8"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\MusicPro Studio"
InstallDirRegKey HKCU "Software\MusicProStudio" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 32
BrandingText "MusicPro Studio | Offline Windows edition"
VIProductVersion "1.8.0.0"
VIAddVersionKey /LANG=1033 "ProductName" "MusicPro Studio"
VIAddVersionKey /LANG=1033 "FileDescription" "MusicPro Studio Offline Setup"
VIAddVersionKey /LANG=1033 "FileVersion" "1.8.0"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Third-party components retain their licenses."
Icon "musicpro.ico"
UninstallIcon "musicpro.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "MusicPro Studio 1.8"
!define MUI_WELCOMEPAGE_TEXT "Python va FFmpeg paket ichida.$\r$\nInternet yoki administrator huquqi talab qilinmaydi.$\r$\n$\r$\nWindows 10/11, Intel yoki AMD 64-bit uchun.$\r$\n$\r$\nDavom etish uchun Next tugmasini bosing."
!define MUI_FINISHPAGE_RUN "$INSTDIR\MusicPro.exe"
!define MUI_FINISHPAGE_RUN_TEXT "MusicPro Studio ni ochish"
!define MUI_FINISHPAGE_TEXT "MusicPro tayyor. Ish stolidagi yorliq orqali oching.$\r$\n$\r$\nDastur brauzerda, kompyuteringizning o'zida ishlaydi."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

!macro CheckNotRunning
 System::Call 'kernel32::OpenMutexW(i 0x100000, i 0, w "Local\MusicProStudio.Installed") p .r0'
 ${If} $0 != 0
  System::Call 'kernel32::CloseHandle(p r0)'
  MessageBox MB_OK|MB_ICONEXCLAMATION "MusicPro ishlamoqda. Brauzerda Chiqish tugmasini bosing, keyin qayta urinib ko'ring."
  Abort
 ${EndIf}
!macroend

Function .onInit
 ${IfNot} ${RunningX64}
  MessageBox MB_OK|MB_ICONSTOP "Windows 10/11 64-bit kerak."
  Abort
 ${EndIf}
 ${IfNot} ${AtLeastWin10}
  MessageBox MB_OK|MB_ICONSTOP "Windows 10 yoki Windows 11 kerak."
  Abort
 ${EndIf}
 SetShellVarContext current
 !insertmacro CheckNotRunning
FunctionEnd

Section "MusicPro Studio" SEC_MAIN
 !insertmacro CheckNotRunning
 SetOutPath "$INSTDIR"
 !include "install_files.nsh"
 FileOpen $0 "$INSTDIR\installed.flag" w
 FileWrite $0 "MusicPro Studio per-user installation$\r$\n"
 FileClose $0
 WriteUninstaller "$INSTDIR\Uninstall.exe"
 CreateDirectory "$SMPROGRAMS\MusicPro Studio"
 CreateShortcut "$DESKTOP\MusicPro Studio.lnk" "$INSTDIR\MusicPro.exe" "" "$INSTDIR\MusicPro.exe"
 CreateShortcut "$SMPROGRAMS\MusicPro Studio\MusicPro Studio.lnk" "$INSTDIR\MusicPro.exe"
 CreateShortcut "$SMPROGRAMS\MusicPro Studio\Tekshirish.lnk" "$INSTDIR\MusicPro.exe" "--check"
 CreateShortcut "$SMPROGRAMS\MusicPro Studio\Olib tashlash.lnk" "$INSTDIR\Uninstall.exe"
 WriteRegStr HKCU "Software\MusicProStudio" "InstallDir" "$INSTDIR"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicProStudio" "DisplayName" "MusicPro Studio"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicProStudio" "DisplayVersion" "1.8.0"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicProStudio" "DisplayIcon" "$INSTDIR\MusicPro.exe"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicProStudio" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
 WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicProStudio" "NoModify" 1
 WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicProStudio" "NoRepair" 1
SectionEnd

Function un.onInit
 SetShellVarContext current
 !insertmacro CheckNotRunning
FunctionEnd

Section "Uninstall"
 !insertmacro CheckNotRunning
 !include "uninstall_files.nsh"
 Delete "$INSTDIR\installed.flag"
 Delete "$INSTDIR\Uninstall.exe"
 RMDir "$INSTDIR"
 Delete "$DESKTOP\MusicPro Studio.lnk"
 Delete "$SMPROGRAMS\MusicPro Studio\MusicPro Studio.lnk"
 Delete "$SMPROGRAMS\MusicPro Studio\Tekshirish.lnk"
 Delete "$SMPROGRAMS\MusicPro Studio\Olib tashlash.lnk"
 RMDir "$SMPROGRAMS\MusicPro Studio"
 DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\MusicProStudio"
 DeleteRegKey HKCU "Software\MusicProStudio"
 ; Per-user data and all media are deliberately preserved.
SectionEnd
