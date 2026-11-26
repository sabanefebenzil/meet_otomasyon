@echo off
chcp 65001 >nul
title Meet Otomasyon - Kurulum ve EXE Olusturucu
cd /d "%~dp0"

if not exist "meet_otomasyon.pyw" (
    echo [!] meet_otomasyon.pyw dosyasi bu klasorde bulunamadi.
    pause
    exit /b 1
)

if not exist "version_info.txt" (
    echo [!] version_info.txt dosyasi bu klasorde bulunamadi.
    pause
    exit /b 1
)

echo [1/5] Gerekli kutuphaneler kuruluyor...
python -m pip install --upgrade pip
python -m pip install playwright customtkinter pyinstaller pillow
if errorlevel 1 (
    echo [!] Kutuphane kurulumu basarisiz oldu.
    pause
    exit /b 1
)

echo.
echo [2/5] Playwright Chromium kontrol ediliyor...
python -m playwright install chromium

echo.
echo [3/5] Ikon hazirlaniyor...
if not exist "icon.png" goto ikon_atla
python -c "from PIL import Image, ImageDraw; img=Image.open('icon.png').convert('RGBA'); w,h=img.size; [ImageDraw.floodfill(img, pt, (0,0,0,0), thresh=40) for pt in ((0,0),(w-1,0),(0,h-1),(w-1,h-1))]; bb=img.getbbox(); img=img.crop(bb) if bb else img; m=max(img.size); sq=Image.new('RGBA',(m,m),(0,0,0,0)); sq.paste(img,((m-img.width)//2,(m-img.height)//2)); sq.save('icon.ico',format='ICO',sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
:ikon_atla

set ICON_ARGS=
if exist "icon.ico" set ICON_ARGS=--icon="icon.ico" --add-data="icon.ico;."

echo.
echo [4/5] MeetOtomasyon.exe olusturuluyor...
python -m PyInstaller --noconfirm --onefile --windowed --clean ^
    --name "MeetOtomasyon" ^
    --version-file "version_info.txt" ^
    %ICON_ARGS% ^
    --collect-all customtkinter ^
    --collect-all playwright ^
    meet_otomasyon.pyw

if not exist "dist\MeetOtomasyon.exe" (
    echo [!] EXE olusturulamadi. Yukaridaki hata mesajini kontrol edin.
    pause
    exit /b 1
)

echo.
echo [5/5] MeetOtomasyon.exe ana klasore kopyalaniyor...
copy /y "dist\MeetOtomasyon.exe" "MeetOtomasyon.exe" >nul

echo.
echo ======================================================
echo  ISLEM TAMAMLANDI!
echo  Hazir dosya: %~dp0MeetOtomasyon.exe
echo ======================================================
pause