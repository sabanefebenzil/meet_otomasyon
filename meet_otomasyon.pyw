import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from tkinter import filedialog, messagebox

try:
    import winreg
except ImportError:
    winreg = None

import customtkinter as ctk
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ==================== UYGULAMA VE GELİŞTİRİCİ BİLGİLERİ ====================
UYGULAMA_ADI = "Meet Otomasyon"
UYGULAMA_SURUM = "v1.1"
GELISTIRICI_ADI = "Şaban Efe Benzil"
GELISTIRICI_EPOSTA = "benzilsabanefe@gmail.com"
GELISTIRICI_WEB_GORUNEN = "sabanefebenzil.github.io"
GELISTIRICI_WEB_URL = "https://sabanefebenzil.github.io"

# Yazı Tipleri (Metro UI Tipografisi)
FONT_BASLIK = "Segoe UI Light"
FONT_KALIN = "Segoe UI Semibold"
FONT_GOVDE = "Segoe UI"
FONT_KOD = "Consolas"

# Windows Başlangıç Kayıt Defteri Ayarları
BASLANGIC_REG_YOLU = r"Software\Microsoft\Windows\CurrentVersion\Run"
BASLANGIC_UYGULAMA_ADI = "MeetOtomasyon"

# ==================== DOSYA YOLLARI ====================
if getattr(sys, "frozen", False):
    UYGULAMA_DIZINI = os.path.dirname(sys.executable)
else:
    UYGULAMA_DIZINI = os.path.dirname(os.path.abspath(__file__))

AYAR_DOSYASI = os.path.join(UYGULAMA_DIZINI, "ayarlar.json")
def kaynak_yolu(dosya_adi):
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, dosya_adi)
    return os.path.join(UYGULAMA_DIZINI, dosya_adi)


def varsayilan_profil_dizini():
    """Mevcut profil varsa onu korur, yeni kurulumlarda kullanıcı klasörünü seçer."""
    eski_yol = r"C:\MeetOtomasyonProfil"
    if os.path.exists(eski_yol):
        return eski_yol
    yerel_app = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(yerel_app, "MeetOtomasyon", "Profil")


VARSAYILAN_AYARLAR = {
    "grup_adi": "",
    "mesaj_metni": "Toplantı başladı. Katılmak için bağlantı:",
    "profil_dizini": varsayilan_profil_dizini(),
    "whatsapp_gonder": True,
    "panoya_kopyala": True,
    "otomatik_onay": True,
    "tam_ekran": True,
    "hazir_kutusunu_kapat": True,
    "mikrofon_kapali": False,
    "kamera_kapali": False,
    "windows_baslangic": False,
    "acilista_otomatik_baslat": True,
    "baslatma_suresi_sn": 60,
    "sohbet_kapatma_aktif": True,
    "kapatma_kelimesi": "!kapat",
}


# ==================== WINDOWS BAŞLANGIÇ YÖNETİMİ ====================
def baslangic_komutu_olustur():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    python_exe = sys.executable
    if python_exe.lower().endswith("python.exe"):
        pythonw = python_exe[:-10] + "pythonw.exe"
        if os.path.exists(pythonw):
            python_exe = pythonw
    return f'"{python_exe}" "{os.path.abspath(__file__)}"'


def windows_baslangic_ayarla(aktif):
    if winreg is None:
        return False, "Bu işlem yalnızca Windows üzerinde desteklenir."
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            BASLANGIC_REG_YOLU,
            0,
            winreg.KEY_SET_VALUE,
        ) as anahtar:
            if aktif:
                winreg.SetValueEx(
                    anahtar,
                    BASLANGIC_UYGULAMA_ADI,
                    0,
                    winreg.REG_SZ,
                    baslangic_komutu_olustur(),
                )
            else:
                try:
                    winreg.DeleteValue(anahtar, BASLANGIC_UYGULAMA_ADI)
                except FileNotFoundError:
                    pass
        return True, None
    except Exception as e:
        return False, str(e)


def windows_baslangic_aktif_mi():
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            BASLANGIC_REG_YOLU,
            0,
            winreg.KEY_READ,
        ) as anahtar:
            deger, _ = winreg.QueryValueEx(anahtar, BASLANGIC_UYGULAMA_ADI)
            return bool(deger)
    except Exception:
        return False


def ayarlari_yukle():
    ayarlar = VARSAYILAN_AYARLAR.copy()
    ilk_kurulum = not os.path.exists(AYAR_DOSYASI)
    if not ilk_kurulum:
        try:
            with open(AYAR_DOSYASI, "r", encoding="utf-8") as f:
                kayitli = json.load(f)
            if isinstance(kayitli, dict):
                ayarlar.update(kayitli)
        except Exception:
            pass

    # EXE farklı bir klasöre taşındıysa başlangıç yolunu otomatik senkronize et
    if ayarlar.get("windows_baslangic"):
        windows_baslangic_ayarla(True)
    elif ilk_kurulum:
        ayarlar["windows_baslangic"] = windows_baslangic_aktif_mi()

    return ayarlar, ilk_kurulum


def ayarlari_kaydet(ayarlar):
    with open(AYAR_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(ayarlar, f, ensure_ascii=False, indent=2)


def metin_komutu_iceriyor_mu(metin, kelime):
    """Türkçe karakter uyumlu ve tam kelime sınırlı komut kontrolü yapar."""
    if not metin or not kelime:
        return False
    hedef = kelime.strip()
    if not hedef:
        return False
    metin_k = metin.replace("İ", "i").replace("I", "ı").lower()
    hedef_k = hedef.replace("İ", "i").replace("I", "ı").lower()
    desen = r"(?<![0-9a-zçğıöşü])" + re.escape(hedef_k) + r"(?![0-9a-zçğıöşü])"
    return re.search(desen, metin_k) is not None


# ==================== OTOMASYON MOTORU ====================
class MeetOtomasyonMotoru:
    def __init__(self, ayarlar, log_fn, durum_fn, bitis_fn, durdur_olayi):
        self.ayarlar = ayarlar
        self.log = log_fn
        self.durum = durum_fn
        self.bitis = bitis_fn
        self.durdur = durdur_olayi
        self.bilgisayari_kapat_istegi = False

    def panoya_kopyala(self, metin):
        try:
            env = os.environ.copy()
            env["MEET_CLIP_TEXT"] = metin
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Set-Clipboard -Value $env:MEET_CLIP_TEXT",
                ],
                env=env,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.log("Bağlantı panoya kopyalandı.")
        except Exception as e:
            self.log(f"Pano kopyalama uyarısı: {e}")

    def hazir_kutusunu_kapat(self, meet_page):
        baslik_deseni = re.compile(
            r"Toplantınız hazır|Your meeting's ready|Katılımcı ekle|Add others",
            re.IGNORECASE,
        )
        kapat_deseni = re.compile(r"^(Kapat|Close)$", re.IGNORECASE)
        kapat_secici = 'button[aria-label="Kapat"], button[aria-label="Close"]'

        try:
            diyalog = (
                meet_page.locator('[role="dialog"]').filter(has_text=baslik_deseni).first
            )
            diyalog.wait_for(state="visible", timeout=3000)
            kapat_btn = diyalog.get_by_role("button", name=kapat_deseni).first
            if kapat_btn.count() > 0 and kapat_btn.is_visible():
                kapat_btn.click()
                self.log("'Toplantınız hazır' kutucuğu kapatıldı.")
                return
        except Exception:
            pass

        try:
            kutu = (
                meet_page.locator("div")
                .filter(has_text=baslik_deseni)
                .filter(has=meet_page.locator(kapat_secici))
                .last
            )
            if kutu.count() > 0 and kutu.is_visible():
                kutu.locator(kapat_secici).first.click()
                self.log("'Toplantınız hazır' kutucuğu kapatıldı.")
        except Exception:
            pass

    def cihazlari_ayarla(self, meet_page):
        if self.ayarlar.get("mikrofon_kapali"):
            try:
                mik_btn = meet_page.locator(
                    'button[data-is-muted="false"][aria-label*="mikrofon" i], '
                    'button[data-is-muted="false"][aria-label*="microphone" i]'
                ).first
                if mik_btn.count() > 0 and mik_btn.is_visible():
                    mik_btn.click()
                    self.log("Mikrofon kapatıldı.")
            except Exception:
                pass

        if self.ayarlar.get("kamera_kapali"):
            try:
                kam_btn = meet_page.locator(
                    'button[data-is-muted="false"][aria-label*="kamera" i], '
                    'button[data-is-muted="false"][aria-label*="camera" i]'
                ).first
                if kam_btn.count() > 0 and kam_btn.is_visible():
                    kam_btn.click()
                    self.log("Kamera kapatıldı.")
            except Exception:
                pass

    def tam_ekran_yap(self, context, page):
        page.bring_to_front()
        time.sleep(0.4)
        try:
            cdp = context.new_cdp_session(page)
            pencere = cdp.send("Browser.getWindowForTarget")
            cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": pencere["windowId"],
                    "bounds": {"windowState": "fullscreen"},
                },
            )
            self.log("Google Meet tam ekran yapıldı (Çıkmak için F11).")
        except Exception:
            page.keyboard.press("F11")

    def gorunur_ilk_butona_tikla(self, locator_grubu):
        try:
            adet = locator_grubu.count()
            for i in range(adet):
                btn = locator_grubu.nth(i)
                if btn.is_visible():
                    btn.click(timeout=2000)
                    return True
        except Exception:
            pass
        return False

    def panel_acik_mi(self, meet_page):
        try:
            ekle_btn = meet_page.locator("button, [role='button']").filter(
                has_text=re.compile(r"Kullanıcı ekle|Add people", re.IGNORECASE)
            )
            for i in range(ekle_btn.count()):
                if ekle_btn.nth(i).is_visible():
                    return True
        except Exception:
            pass
        return False

    def kullanicilar_panelini_kapat(self, meet_page):
        try:
            kapat_secici = 'button[aria-label="Kapat"], button[aria-label="Close"]'
            panel = (
                meet_page.locator("aside, [role='complementary'], [role='dialog'], div")
                .filter(has_text=re.compile(r"Kullanıcılar|People", re.IGNORECASE))
                .filter(has_text=re.compile(r"Kullanıcı ekle|Add people", re.IGNORECASE))
                .filter(has=meet_page.locator(kapat_secici))
                .last
            )
            if panel.count() > 0 and panel.is_visible():
                kapat_btn = panel.locator(kapat_secici).first
                if kapat_btn.is_visible():
                    kapat_btn.click(timeout=2000)
                    self.log("Kullanıcılar paneli kapatıldı.")
                    return True
        except Exception:
            pass
        return False

    def kabul_butonlarina_tikla(self, meet_page):
        onaylandi = False
        seciciler = [
            meet_page.locator("button, [role='button']").filter(
                has_text=re.compile(
                    r"^(Tümünü kabul et|Tümüne izin ver|Admit all)$", re.IGNORECASE
                )
            ),
            meet_page.locator("button, [role='button']").filter(
                has_text=re.compile(r"^(Kabul et|İzin ver|Admit)$", re.IGNORECASE)
            ),
            meet_page.locator(
                'button[aria-label*="kabul et" i], button[aria-label*="admit" i]'
            ),
        ]
        for secici in seciciler:
            for _ in range(15):
                if self.durdur.is_set():
                    return onaylandi
                if self.gorunur_ilk_butona_tikla(secici):
                    onaylandi = True
                    self.log("Yeni katılımcı otomatik onaylandı.")
                    time.sleep(0.4)
                else:
                    break
        return onaylandi

    # ---------- SOHBET İZLEME VE TOPLANTI SONLANDIRMA ----------
    def sohbet_paneli_acik_mi(self, meet_page):
        try:
            return meet_page.evaluate(
                r"""() => {
                    const alanlar = document.querySelectorAll('textarea, [contenteditable="true"]');
                    for (const el of alanlar) {
                        if (el.offsetParent === null) continue;
                        const lbl = (el.getAttribute('aria-label') || el.getAttribute('placeholder') || '');
                        if (/mesaj|message|sohbet|chat/i.test(lbl)) return true;
                    }
                    return false;
                }"""
            )
        except Exception:
            return False

    def sohbet_butonuna_tikla(self, meet_page):
        buton = meet_page.locator(
            'button[aria-label*="sohbet" i], button[aria-label*="chat" i]'
        )
        return self.gorunur_ilk_butona_tikla(buton)

    def sohbet_panelini_kapat(self, meet_page):
        try:
            kapat_secici = 'button[aria-label="Kapat"], button[aria-label="Close"]'
            panel = (
                meet_page.locator("aside, [role='complementary'], [role='dialog'], div")
                .filter(
                    has_text=re.compile(
                        r"Toplantı içi mesajlar|In-call messages", re.IGNORECASE
                    )
                )
                .filter(has=meet_page.locator(kapat_secici))
                .last
            )
            if panel.count() > 0 and panel.is_visible():
                kapat_btn = panel.locator(kapat_secici).first
                if kapat_btn.is_visible():
                    kapat_btn.click(timeout=2000)
                    return True
        except Exception:
            pass
        if self.sohbet_paneli_acik_mi(meet_page):
            self.sohbet_butonuna_tikla(meet_page)
        return False

    def sohbette_okunmamis_var_mi(self, meet_page):
        try:
            return meet_page.evaluate(
                r"""() => {
                    const butonlar = document.querySelectorAll('button[aria-label], [role="button"][aria-label]');
                    for (const btn of butonlar) {
                        if (btn.offsetParent === null) continue;
                        const lbl = btn.getAttribute('aria-label') || '';
                        if (!/sohbet|chat/i.test(lbl)) continue;
                        if (/okunmamış|unread|yeni mesaj|new message|\d+/i.test(lbl)) return true;
                        const btnTxt = (btn.innerText || '').trim();
                        if (btnTxt && /\d+/.test(btnTxt)) return true;
                        const parent = btn.parentElement;
                        if (parent && parent.querySelectorAll('button').length === 1) {
                            const pTxt = (parent.innerText || '').trim();
                            if (pTxt && /\d+/.test(pTxt)) return true;
                        }
                    }
                    return false;
                }"""
            )
        except Exception:
            return False

    def sohbet_mesajlarini_oku(self, meet_page):
        try:
            return meet_page.evaluate(
                r"""() => {
                    const sonuclar = [];
                    const ekle = (txt) => {
                        if (txt && typeof txt === 'string') {
                            const t = txt.trim();
                            if (t) sonuclar.push(t);
                        }
                    };

                    // 1. Google Meet'in standart sohbet mesaj özniteliği
                    document.querySelectorAll('[data-message-text]').forEach(el => {
                        ekle(el.getAttribute('data-message-text'));
                        ekle(el.innerText);
                    });

                    // 2. Gönderen bloğu taşıyan mesaj baloncukları
                    document.querySelectorAll('[data-sender-id]').forEach(el => {
                        if (el.offsetParent !== null) {
                            ekle(el.innerText);
                        }
                    });

                    // 3. Açık sohbet paneli içindeki mesaj metinleri
                    const paneller = document.querySelectorAll('aside, [role="complementary"], [role="dialog"]');
                    for (const panel of paneller) {
                        if (panel.offsetParent === null) continue;
                        const metin = panel.innerText || '';
                        if (/Toplantı içi mesajlar|In-call messages/i.test(metin)) {
                            panel.querySelectorAll('div, span, p').forEach(oge => {
                                if (oge.children.length === 0 && oge.offsetParent !== null) {
                                    if (!oge.closest('button, textarea, input, [contenteditable="true"]')) {
                                        ekle(oge.innerText);
                                    }
                                }
                            });
                        }
                    }
                    return sonuclar;
                }"""
            )
        except Exception:
            return []

    def toast_mesajlarini_oku(self, meet_page):
        """Sohbet kapalıyken sağ altta anlık beliren mesaj bildirimlerini okur."""
        try:
            return meet_page.evaluate(
                r"""() => {
                    const sonuclar = [];
                    const sistemDeseni = /mikrofon|kamera|katıldı|ayrıldı|ekran|davetli|bekliyor|kapatıldı|açıldı|microphone|camera|joined|left|muted|unmuted|waiting|recording/i;
                    const adaylar = document.querySelectorAll('[role="alert"], [role="status"], [aria-live="polite"], [aria-live="assertive"]');
                    for (const el of adaylar) {
                        if (el.offsetParent === null) continue;
                        const t = (el.innerText || '').trim();
                        if (!t || t.length > 400) continue;
                        if (sistemDeseni.test(t)) continue;
                        sonuclar.push(t);
                    }
                    return sonuclar;
                }"""
            )
        except Exception:
            return []

    def sohbet_kapatma_komutu_kontrol(self, meet_page, kelime):
        if not kelime:
            return False

        # 1. Açık sohbet panelindeki mesajları ve mevcut [data-message-text] öğelerini kontrol et
        for mesaj in self.sohbet_mesajlarini_oku(meet_page):
            if metin_komutu_iceriyor_mu(mesaj, kelime):
                return True

        # 2. Sohbet kapalıyken anlık açılan bildirim baloncuğunu kontrol et
        for bildirim in self.toast_mesajlarini_oku(meet_page):
            if metin_komutu_iceriyor_mu(bildirim, kelime):
                return True

        # 3. Sohbet ikonu üzerinde okunmamış mesaj rozeti varsa paneli açıp kontrol et
        if not self.sohbet_paneli_acik_mi(meet_page) and self.sohbette_okunmamis_var_mi(meet_page):
            if self.sohbet_butonuna_tikla(meet_page):
                time.sleep(0.6)
                bulundu = any(
                    metin_komutu_iceriyor_mu(m, kelime)
                    for m in self.sohbet_mesajlarini_oku(meet_page)
                )
                if bulundu:
                    return True
                self.sohbet_panelini_kapat(meet_page)

        return False

    def toplantiyi_sonlandir(self, meet_page):
        """Görüşmeden ayrıl butonuna basar ve yönetici onay penceresi çıkarsa herkes için bitirir."""
        try:
            ayril_btn = meet_page.locator(
                'button[aria-label*="Görüşmeden ayrıl" i], button[aria-label*="Leave call" i]'
            )
            if self.gorunur_ilk_butona_tikla(ayril_btn):
                time.sleep(0.8)
                # Ev sahibi için 'Görüşmeyi sonlandır' seçeneği çıkarsa tıkla
                sonlandir_btn = meet_page.locator("button, [role='button']").filter(
                    has_text=re.compile(
                        r"Görüşmeyi sonlandır|Herkes için sonlandır|End the call|End the meeting",
                        re.IGNORECASE,
                    )
                )
                if not self.gorunur_ilk_butona_tikla(sonlandir_btn):
                    sadece_ayril = meet_page.locator("button, [role='button']").filter(
                        has_text=re.compile(
                            r"Yalnızca görüşmeden ayrıl|Just leave the call",
                            re.IGNORECASE,
                        )
                    )
                    self.gorunur_ilk_butona_tikla(sadece_ayril)
                time.sleep(1.0)
                self.log("Google Meet toplantısı sonlandırıldı.")
        except Exception as e:
            self.log(f"Toplantı sonlandırma uyarısı: {e}")

    def toplanti_izleme_dongusu(self, meet_page):
        """Toplantı boyunca hem katılımcı onayını hem sohbet kapatma komutunu izler."""
        oto_onay = self.ayarlar.get("otomatik_onay", True)
        sohbet_kapat = self.ayarlar.get("sohbet_kapatma_aktif", False)
        kapatma_kelimesi = self.ayarlar.get("kapatma_kelimesi", "").strip()

        aktif_bilgiler = []
        if oto_onay:
            aktif_bilgiler.append("Otomatik onay")
        if sohbet_kapat and kapatma_kelimesi:
            aktif_bilgiler.append(f"Sohbet komutu: {kapatma_kelimesi}")

        if aktif_bilgiler:
            self.durum("Aktif — " + " | ".join(aktif_bilgiler))
            self.log("İzleme başladı: " + ", ".join(aktif_bilgiler))
        else:
            self.durum("Toplantı aktif")

        bekleyen_desen = re.compile(
            r"(davetli|kişi|katılımcı)\s*bekliyor|waiting", re.IGNORECASE
        )
        panel_otomatik_acildi = False

        while not meet_page.is_closed() and not self.durdur.is_set():
            try:
                # 1. Otomatik katılımcı onayı
                if oto_onay:
                    self.kabul_butonlarina_tikla(meet_page)

                    bekleyen_butonlar = meet_page.locator("button, [role='button']").filter(
                        has_text=bekleyen_desen
                    )
                    bekleyen_var = any(
                        bekleyen_butonlar.nth(i).is_visible()
                        for i in range(bekleyen_butonlar.count())
                    )

                    if bekleyen_var:
                        if not self.panel_acik_mi(meet_page):
                            if self.gorunur_ilk_butona_tikla(bekleyen_butonlar):
                                self.log("'Davetli bekliyor' bildirimi açıldı...")
                                panel_otomatik_acildi = True
                                time.sleep(0.6)

                        kapali_baslik = meet_page.locator('[aria-expanded="false"]').filter(
                            has_text=re.compile(
                                r"Kabul edilmeyi bekleyenler|Waiting to be admitted",
                                re.IGNORECASE,
                            )
                        )
                        if self.gorunur_ilk_butona_tikla(kapali_baslik):
                            time.sleep(0.4)

                        self.kabul_butonlarina_tikla(meet_page)

                    elif panel_otomatik_acildi:
                        time.sleep(0.4)
                        if not self.kabul_butonlarina_tikla(meet_page):
                            self.kullanicilar_panelini_kapat(meet_page)
                            panel_otomatik_acildi = False

                # 2. Sohbet kapatma komutu kontrolü
                if sohbet_kapat and kapatma_kelimesi:
                    if self.sohbet_kapatma_komutu_kontrol(meet_page, kapatma_kelimesi):
                        self.log(
                            f"Sohbette kapatma komutu ('{kapatma_kelimesi}') algılandı!"
                        )
                        self.durum("Kapatma komutu algılandı — Toplantı bitiriliyor...")
                        self.toplantiyi_sonlandir(meet_page)
                        self.bilgisayari_kapat_istegi = True
                        break
            except Exception:
                pass
            self.durdur.wait(0.8)

    # ---------- WHATSAPP PAYLAŞIMI ----------
    def arama_kutusunu_bul(self, wa_page):
        seciciler = [
            '#side div[contenteditable="true"]',
            '#side input[type="text"]',
            '#side [role="textbox"]',
            'div[role="textbox"][aria-label*="Ara"]',
            'div[role="textbox"][aria-label*="Search"]',
        ]
        for secici in seciciler:
            eleman = wa_page.locator(secici).first
            try:
                if eleman.count() > 0 and eleman.is_visible():
                    return eleman
            except Exception:
                continue
        return None

    def whatsapp_link_gonder(self, context, meet_link):
        grup_adi = self.ayarlar.get("grup_adi", "").strip()
        if not grup_adi:
            self.log("WhatsApp grup adı boş olduğu için paylaşım atlandı.")
            return

        mesaj_sablonu = self.ayarlar.get("mesaj_metni", "").strip()
        if "{link}" in mesaj_sablonu:
            tam_mesaj = mesaj_sablonu.replace("{link}", meet_link)
        elif mesaj_sablonu:
            tam_mesaj = f"{mesaj_sablonu} {meet_link}"
        else:
            tam_mesaj = meet_link

        self.durum("WhatsApp Web üzerinden paylaşılıyor...")
        wa_page = context.new_page()
        wa_page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")
        self.log("WhatsApp Web yükleniyor (İlk kullanımda QR kodu okutun)...")

        wa_page.locator("#pane-side").wait_for(state="visible", timeout=120000)
        time.sleep(1.5)

        if self.durdur.is_set():
            wa_page.close()
            return

        grup_bulundu = False
        dogrudan_grup = wa_page.locator(f'#pane-side span[title="{grup_adi}"]').first
        if dogrudan_grup.count() > 0 and dogrudan_grup.is_visible():
            dogrudan_grup.click()
            grup_bulundu = True
            self.log(f"'{grup_adi}' sohbet listesinde bulundu.")

        if not grup_bulundu:
            arama_kutusu = self.arama_kutusunu_bul(wa_page)
            if arama_kutusu:
                arama_kutusu.click()
            else:
                wa_page.keyboard.press("Control+Alt+/")

            time.sleep(0.5)
            wa_page.keyboard.press("Control+A")
            wa_page.keyboard.press("Backspace")
            wa_page.keyboard.insert_text(grup_adi)
            time.sleep(2)

            tam_eslesme = wa_page.locator(f'#pane-side span[title="{grup_adi}"]').first
            kismi_eslesme = (
                wa_page.locator("#pane-side span[title]")
                .filter(has_text=grup_adi)
                .first
            )

            if tam_eslesme.count() > 0 and tam_eslesme.is_visible():
                tam_eslesme.click()
            elif kismi_eslesme.count() > 0 and kismi_eslesme.is_visible():
                kismi_eslesme.click()
            else:
                wa_page.keyboard.press("Enter")

        mesaj_kutusu = wa_page.locator(
            '#main footer div[contenteditable="true"][role="textbox"], '
            '#main footer div[contenteditable="true"]'
        ).first
        mesaj_kutusu.wait_for(state="visible", timeout=20000)
        mesaj_kutusu.click()
        time.sleep(0.3)

        wa_page.keyboard.insert_text(tam_mesaj)
        time.sleep(0.4)
        wa_page.keyboard.press("Enter")
        self.log(f"Bağlantı '{grup_adi}' grubuna gönderildi.")

        time.sleep(3.5)
        wa_page.close()

    def calistir(self):
        context = None
        try:
            profil_dizini = self.ayarlar.get("profil_dizini") or varsayilan_profil_dizini()
            os.makedirs(profil_dizini, exist_ok=True)

            self.durum("Tarayıcı başlatılıyor...")
            self.log("Tarayıcı açılıyor...")

            with sync_playwright() as p:
                tarayici_ayarlari = {
                    "user_data_dir": profil_dizini,
                    "headless": False,
                    "chromium_sandbox": True,
                    "permissions": [
                        "microphone",
                        "camera",
                        "clipboard-read",
                        "clipboard-write",
                    ],
                    "args": [
                        "--disable-blink-features=AutomationControlled",
                        "--start-maximized",
                    ],
                    "ignore_default_args": ["--enable-automation", "--no-sandbox"],
                    "no_viewport": True,
                }

                for kanal in ("chrome", "msedge", None):
                    try:
                        if kanal:
                            context = p.chromium.launch_persistent_context(
                                channel=kanal, **tarayici_ayarlari
                            )
                        else:
                            context = p.chromium.launch_persistent_context(
                                **tarayici_ayarlari
                            )
                        break
                    except Exception:
                        continue

                if context is None:
                    raise RuntimeError(
                        "Bilgisayarda Chrome, Edge veya Chromium bulunamadı."
                    )

                meet_page = context.pages[0] if context.pages else context.new_page()
                self.durum("Google Meet toplantısı oluşturuluyor...")
                self.log("Yeni Google Meet toplantısı açılıyor...")
                meet_page.goto("https://meet.google.com/new", wait_until="domcontentloaded")

                try:
                    meet_page.wait_for_url(
                        re.compile(
                            r"https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}",
                            re.IGNORECASE,
                        ),
                        timeout=120000,
                    )
                except PlaywrightTimeoutError:
                    self.log("Zaman aşımı: Google hesabınıza giriş yaptığınızdan emin olun.")
                    return

                if self.durdur.is_set():
                    return

                meet_link = meet_page.url.split("?")[0]
                self.log(f"Toplantı hazır: {meet_link}")

                if self.ayarlar.get("panoya_kopyala", True):
                    self.panoya_kopyala(meet_link)

                if self.ayarlar.get("whatsapp_gonder", True):
                    try:
                        self.whatsapp_link_gonder(context, meet_link)
                    except Exception as e:
                        self.log(f"WhatsApp paylaşım hatası: {e}")

                if self.durdur.is_set():
                    return

                meet_page.bring_to_front()
                time.sleep(0.5)

                if self.ayarlar.get("hazir_kutusunu_kapat", True):
                    self.hazir_kutusunu_kapat(meet_page)

                self.cihazlari_ayarla(meet_page)

                if self.ayarlar.get("tam_ekran", True):
                    self.tam_ekran_yap(context, meet_page)

                self.toplanti_izleme_dongusu(meet_page)
                self.log("Toplantı oturumu sonlandı.")
        except Exception as e:
            self.log(f"Hata: {e}")
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass

            if self.bilgisayari_kapat_istegi:
                self.durum("Bilgisayar kapatılıyor...")
                self.log("Tarayıcı kapatıldı. Bilgisayar 5 saniye içinde kapatılıyor...")
                time.sleep(1.5)
                try:
                    subprocess.run(
                        [
                            "shutdown",
                            "/s",
                            "/t",
                            "5",
                            "/c",
                            "Meet Otomasyon: Sohbet komutu ile toplanti sonlandirildi, bilgisayar kapatiliyor.",
                        ],
                        check=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except Exception as e:
                    self.log(f"Bilgisayar kapatma komutu hatası: {e}")

            self.bitis()


# ==================== MASAÜSTÜ ARAYÜZÜ ====================
class MeetOtomasyonUygulamasi(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"{UYGULAMA_ADI} — {GELISTIRICI_ADI}")
        self.geometry("660x660")
        self.minsize(580, 560)
        ikon_yolu = kaynak_yolu("icon.ico")
        if os.path.exists(ikon_yolu):
            try:
                self.iconbitmap(ikon_yolu)
                self.after(250, lambda: self.iconbitmap(ikon_yolu))
            except Exception:
                pass

        self.ayarlar, self.ilk_kurulum = ayarlari_yukle()
        self.calisiyor = False
        self.durdur_olayi = threading.Event()
        self.otomatik_sayac_id = None
        self.kalan_saniye = 0

        self._arayuzu_olustur()
        self._ayarlari_forma_doldur()
        self._ozeti_guncelle()

        self.protocol("WM_DELETE_WINDOW", self._pencere_kapat)

        if self.ilk_kurulum:
            self.sekmeler.set("Ayarlar")
            self._log_yaz("İlk kurulum: Grup adı, zamanlayıcı ve kapatma ayarlarını kaydedin.")
        elif self.ayarlar.get("acilista_otomatik_baslat"):
            try:
                sure = max(0, int(self.ayarlar.get("baslatma_suresi_sn", 60)))
            except Exception:
                sure = 60
            self._otomatik_baslat_sayaci(sure)

    def _arayuzu_olustur(self):
        ust_cerceve = ctk.CTkFrame(self, fg_color="transparent")
        ust_cerceve.pack(fill="x", padx=22, pady=(16, 4))

        ctk.CTkLabel(
            ust_cerceve,
            text=UYGULAMA_ADI,
            font=ctk.CTkFont(family=FONT_BASLIK, size=28),
        ).pack(side="left")

        self.durum_rozet = ctk.CTkLabel(
            ust_cerceve,
            text="Hazır",
            font=ctk.CTkFont(family=FONT_KALIN, size=12),
            fg_color="#1e293b",
            text_color="#38bdf8",
            corner_radius=4,
            padx=12,
            pady=4,
        )
        self.durum_rozet.pack(side="right", pady=(6, 0))

        self.sekmeler = ctk.CTkTabview(
            self,
            corner_radius=6,
            segmented_button_selected_color="#0078d7",
            segmented_button_selected_hover_color="#005a9e",
        )
        self.sekmeler.pack(fill="both", expand=True, padx=22, pady=(4, 8))
        self.sekmeler._segmented_button.configure(
            font=ctk.CTkFont(family=FONT_KALIN, size=13)
        )
        self.sekmeler.add("Ana Ekran")
        self.sekmeler.add("Ayarlar")
        self.sekmeler.add("Hakkında")

        self._ana_ekrani_kur(self.sekmeler.tab("Ana Ekran"))
        self._ayarlar_ekranini_kur(self.sekmeler.tab("Ayarlar"))
        self._hakkinda_ekranini_kur(self.sekmeler.tab("Hakkında"))

        # Alt İmza Çubuğu
        alt_imza = ctk.CTkFrame(self, fg_color="transparent")
        alt_imza.pack(fill="x", padx=24, pady=(0, 12))

        ctk.CTkLabel(
            alt_imza,
            text=f"© 2026 {GELISTIRICI_ADI}  •  {UYGULAMA_SURUM}",
            font=ctk.CTkFont(family=FONT_GOVDE, size=11),
            text_color="#94a3b8",
        ).pack(side="left")

        web_link = ctk.CTkLabel(
            alt_imza,
            text=GELISTIRICI_WEB_GORUNEN,
            font=ctk.CTkFont(family=FONT_KALIN, size=11, underline=True),
            text_color="#38bdf8",
            cursor="hand2",
        )
        web_link.pack(side="right")
        web_link.bind("<Button-1>", lambda _e: webbrowser.open(GELISTIRICI_WEB_URL))

    def _ana_ekrani_kur(self, ebeveyn):
        ozet_kart = ctk.CTkFrame(ebeveyn, corner_radius=4)
        ozet_kart.pack(fill="x", padx=10, pady=(10, 12))

        self.ozet_grup_lbl = ctk.CTkLabel(
            ozet_kart,
            text="",
            font=ctk.CTkFont(family=FONT_KALIN, size=15),
            anchor="w",
        )
        self.ozet_grup_lbl.pack(fill="x", padx=14, pady=(10, 2))

        self.ozet_detay_lbl = ctk.CTkLabel(
            ozet_kart,
            text="",
            font=ctk.CTkFont(family=FONT_GOVDE, size=12),
            text_color="#94a3b8",
            anchor="w",
        )
        self.ozet_detay_lbl.pack(fill="x", padx=14, pady=(0, 10))

        self.buton_satir = ctk.CTkFrame(ebeveyn, fg_color="transparent")
        self.buton_satir.pack(fill="x", padx=10, pady=(0, 12))

        self.ayar_git_btn = ctk.CTkButton(
            self.buton_satir,
            text="Ayarlar",
            width=105,
            height=46,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_KALIN, size=14),
            fg_color="#334155",
            hover_color="#475569",
            command=self._ayarlara_gec,
        )
        self.ayar_git_btn.pack(side="right")

        self.baslat_btn = ctk.CTkButton(
            self.buton_satir,
            text="Toplantıyı Başlat",
            height=46,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_KALIN, size=15),
            fg_color="#107c10",
            hover_color="#0b5a0b",
            command=self._baslat_veya_durdur,
        )
        self.baslat_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Geri sayım sırasında beliren zamanlayıcı iptal butonu
        self.sayac_iptal_btn = ctk.CTkButton(
            self.buton_satir,
            text="İptal",
            width=85,
            height=46,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_KALIN, size=14),
            fg_color="#991b1b",
            hover_color="#7f1d1d",
            command=self._sayaci_iptal_et,
        )

        ctk.CTkLabel(
            ebeveyn,
            text="İŞLEM GÜNLÜĞÜ",
            font=ctk.CTkFont(family=FONT_KALIN, size=11),
            text_color="#94a3b8",
            anchor="w",
        ).pack(fill="x", padx=12, pady=(4, 4))

        self.log_kutusu = ctk.CTkTextbox(
            ebeveyn,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_KOD, size=12),
            state="disabled",
        )
        self.log_kutusu.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _ayarlar_ekranini_kur(self, ebeveyn):
        kaydirma = ctk.CTkScrollableFrame(ebeveyn, fg_color="transparent")
        kaydirma.pack(fill="both", expand=True, padx=4, pady=4)

        # ---- WHATSAPP & MESAJ ----
        ctk.CTkLabel(
            kaydirma,
            text="WHATSAPP VE MESAJ",
            font=ctk.CTkFont(family=FONT_KALIN, size=11),
            text_color="#38bdf8",
            anchor="w",
        ).pack(fill="x", padx=8, pady=(4, 4))

        ctk.CTkLabel(
            kaydirma,
            text="WhatsApp Grup Adı (Tam Adı)",
            font=ctk.CTkFont(family=FONT_KALIN, size=13),
            anchor="w",
        ).pack(fill="x", padx=8, pady=(2, 2))

        self.grup_giris = ctk.CTkEntry(
            kaydirma,
            placeholder_text="Örn: Proje Ekibi",
            height=36,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_GOVDE, size=13),
        )
        self.grup_giris.pack(fill="x", padx=8, pady=(0, 8))

        ctk.CTkLabel(
            kaydirma,
            text="Mesaj İçeriği (Linkin geleceği yere isteğe bağlı {link} yazabilirsiniz)",
            font=ctk.CTkFont(family=FONT_KALIN, size=13),
            anchor="w",
        ).pack(fill="x", padx=8, pady=(2, 2))

        self.mesaj_giris = ctk.CTkEntry(
            kaydirma,
            placeholder_text="Toplantı başladı. Katılmak için bağlantı:",
            height=36,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_GOVDE, size=13),
        )
        self.mesaj_giris.pack(fill="x", padx=8, pady=(0, 14))

        # ---- BAŞLANGIÇ VE ZAMANLAYICI ----
        ctk.CTkLabel(
            kaydirma,
            text="BAŞLANGIÇ VE ZAMANLAYICI",
            font=ctk.CTkFont(family=FONT_KALIN, size=11),
            text_color="#38bdf8",
            anchor="w",
        ).pack(fill="x", padx=8, pady=(2, 6))

        self.var_win_baslangic = ctk.BooleanVar()
        self.var_oto_baslat = ctk.BooleanVar()

        ctk.CTkSwitch(
            kaydirma,
            text="Bilgisayar açıldığında uygulamayı otomatik başlat",
            variable=self.var_win_baslangic,
            font=ctk.CTkFont(family=FONT_GOVDE, size=13),
            progress_color="#0078d7",
        ).pack(fill="x", padx=12, pady=4)

        ctk.CTkSwitch(
            kaydirma,
            text="Uygulama açılınca zamanlayıcı ile toplantıyı otomatik başlat",
            variable=self.var_oto_baslat,
            font=ctk.CTkFont(family=FONT_GOVDE, size=13),
            progress_color="#0078d7",
        ).pack(fill="x", padx=12, pady=4)

        sure_satir = ctk.CTkFrame(kaydirma, fg_color="transparent")
        sure_satir.pack(fill="x", padx=12, pady=(4, 14))

        ctk.CTkLabel(
            sure_satir,
            text="Bekleme Süresi (saniye):",
            font=ctk.CTkFont(family=FONT_KALIN, size=13),
        ).pack(side="left")

        self.sure_giris = ctk.CTkEntry(
            sure_satir,
            width=80,
            height=32,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_GOVDE, size=13),
        )
        self.sure_giris.pack(side="left", padx=(10, 8))

        ctk.CTkLabel(
            sure_satir,
            text="(Örn: 60 = 1 dakika, 0 = beklemeden)",
            font=ctk.CTkFont(family=FONT_GOVDE, size=12),
            text_color="#94a3b8",
        ).pack(side="left")

        # ---- SOHBET KOMUTU İLE KAPATMA ----
        ctk.CTkLabel(
            kaydirma,
            text="SOHBET KOMUTU İLE KAPATMA",
            font=ctk.CTkFont(family=FONT_KALIN, size=11),
            text_color="#38bdf8",
            anchor="w",
        ).pack(fill="x", padx=8, pady=(2, 6))

        self.var_sohbet_kapat = ctk.BooleanVar()

        ctk.CTkSwitch(
            kaydirma,
            text="Sohbette kapatma kelimesi yazılınca toplantıyı bitir ve bilgisayarı kapat",
            variable=self.var_sohbet_kapat,
            font=ctk.CTkFont(family=FONT_GOVDE, size=13),
            progress_color="#0078d7",
        ).pack(fill="x", padx=12, pady=4)

        komut_satir = ctk.CTkFrame(kaydirma, fg_color="transparent")
        komut_satir.pack(fill="x", padx=12, pady=(4, 14))

        ctk.CTkLabel(
            komut_satir,
            text="Kapatma Kelimesi:",
            font=ctk.CTkFont(family=FONT_KALIN, size=13),
        ).pack(side="left")

        self.komut_giris = ctk.CTkEntry(
            komut_satir,
            width=160,
            height=32,
            corner_radius=4,
            placeholder_text="!kapat",
            font=ctk.CTkFont(family=FONT_GOVDE, size=13),
        )
        self.komut_giris.pack(side="left", padx=(10, 8))

        ctk.CTkLabel(
            komut_satir,
            text="(Büyük/küçük harf duyarsız)",
            font=ctk.CTkFont(family=FONT_GOVDE, size=12),
            text_color="#94a3b8",
        ).pack(side="left")

        # ---- OTOMASYON TERCİHLERİ ----
        ctk.CTkLabel(
            kaydirma,
            text="OTOMASYON TERCİHLERİ",
            font=ctk.CTkFont(family=FONT_KALIN, size=11),
            text_color="#38bdf8",
            anchor="w",
        ).pack(fill="x", padx=8, pady=(2, 6))

        self.var_whatsapp = ctk.BooleanVar()
        self.var_pano = ctk.BooleanVar()
        self.var_onay = ctk.BooleanVar()
        self.var_tam_ekran = ctk.BooleanVar()
        self.var_hazir_kapat = ctk.BooleanVar()
        self.var_mik_kapali = ctk.BooleanVar()
        self.var_kam_kapali = ctk.BooleanVar()

        anahtarlar = [
            ("Bağlantıyı WhatsApp grubuna otomatik gönder", self.var_whatsapp),
            ("Toplantı bağlantısını panoya kopyala", self.var_pano),
            ("Gelen katılımcı isteklerini otomatik onayla", self.var_onay),
            ("'Toplantınız hazır' beyaz kutucuğunu kapat", self.var_hazir_kapat),
            ("Meet penceresini tam ekran yap", self.var_tam_ekran),
            ("Toplantıya başlarken mikrofonu kapat", self.var_mik_kapali),
            ("Toplantıya başlarken kamerayı kapat", self.var_kam_kapali),
        ]

        for metin, degisken in anahtarlar:
            ctk.CTkSwitch(
                kaydirma,
                text=metin,
                variable=degisken,
                font=ctk.CTkFont(family=FONT_GOVDE, size=13),
                progress_color="#0078d7",
            ).pack(fill="x", padx=12, pady=4)

        # ---- TARAYICI PROFİLİ ----
        ctk.CTkLabel(
            kaydirma,
            text="Tarayıcı Oturum Klasörü (Google & WhatsApp girişleri burada saklanır)",
            font=ctk.CTkFont(family=FONT_KALIN, size=12),
            text_color="#94a3b8",
            anchor="w",
        ).pack(fill="x", padx=8, pady=(14, 4))

        profil_satir = ctk.CTkFrame(kaydirma, fg_color="transparent")
        profil_satir.pack(fill="x", padx=8, pady=(0, 12))

        self.profil_giris = ctk.CTkEntry(
            profil_satir,
            height=34,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_GOVDE, size=12),
        )
        self.profil_giris.pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            profil_satir,
            text="Seç",
            width=70,
            height=34,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_KALIN, size=13),
            fg_color="#334155",
            hover_color="#475569",
            command=self._profil_sec,
        ).pack(side="right")

        alt_satir = ctk.CTkFrame(ebeveyn, fg_color="transparent")
        alt_satir.pack(fill="x", padx=10, pady=(6, 8))

        ctk.CTkButton(
            alt_satir,
            text="Ayarları Kaydet",
            height=40,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_KALIN, size=14),
            fg_color="#0078d7",
            hover_color="#005a9e",
            command=self._kaydet_tiklandi,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            alt_satir,
            text="Oturumu Sıfırla",
            width=130,
            height=40,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_KALIN, size=13),
            fg_color="#991b1b",
            hover_color="#7f1d1d",
            command=self._oturumu_sifirla,
        ).pack(side="right")

    def _hakkinda_ekranini_kur(self, ebeveyn):
        kart = ctk.CTkFrame(ebeveyn, corner_radius=4)
        kart.pack(fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(
            kart,
            text=UYGULAMA_ADI,
            font=ctk.CTkFont(family=FONT_BASLIK, size=30),
            anchor="w",
        ).pack(fill="x", padx=22, pady=(22, 2))

        ctk.CTkLabel(
            kart,
            text=f"Sürüm {UYGULAMA_SURUM}  •  Google Meet & WhatsApp Tek Tık Otomasyonu",
            font=ctk.CTkFont(family=FONT_GOVDE, size=13),
            text_color="#94a3b8",
            anchor="w",
        ).pack(fill="x", padx=22, pady=(0, 18))

        ctk.CTkLabel(
            kart,
            text="GELİŞTİRİCİ",
            font=ctk.CTkFont(family=FONT_KALIN, size=11),
            text_color="#38bdf8",
            anchor="w",
        ).pack(fill="x", padx=22, pady=(4, 2))

        ctk.CTkLabel(
            kart,
            text=GELISTIRICI_ADI,
            font=ctk.CTkFont(family=FONT_KALIN, size=18),
            anchor="w",
        ).pack(fill="x", padx=22, pady=(0, 16))

        bilgi_kutu = ctk.CTkFrame(kart, corner_radius=4, fg_color="#1e293b")
        bilgi_kutu.pack(fill="x", padx=22, pady=(0, 18))

        eposta_satir = ctk.CTkFrame(bilgi_kutu, fg_color="transparent")
        eposta_satir.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            eposta_satir,
            text="E-posta:",
            width=75,
            anchor="w",
            font=ctk.CTkFont(family=FONT_KALIN, size=13),
            text_color="#94a3b8",
        ).pack(side="left")

        eposta_lbl = ctk.CTkLabel(
            eposta_satir,
            text=GELISTIRICI_EPOSTA,
            anchor="w",
            font=ctk.CTkFont(family=FONT_GOVDE, size=13, underline=True),
            text_color="#38bdf8",
            cursor="hand2",
        )
        eposta_lbl.pack(side="left")
        eposta_lbl.bind(
            "<Button-1>", lambda _e: webbrowser.open(f"mailto:{GELISTIRICI_EPOSTA}")
        )

        web_satir = ctk.CTkFrame(bilgi_kutu, fg_color="transparent")
        web_satir.pack(fill="x", padx=14, pady=(4, 12))

        ctk.CTkLabel(
            web_satir,
            text="Web Sitesi:",
            width=75,
            anchor="w",
            font=ctk.CTkFont(family=FONT_KALIN, size=13),
            text_color="#94a3b8",
        ).pack(side="left")

        web_lbl = ctk.CTkLabel(
            web_satir,
            text=GELISTIRICI_WEB_GORUNEN,
            anchor="w",
            font=ctk.CTkFont(family=FONT_GOVDE, size=13, underline=True),
            text_color="#38bdf8",
            cursor="hand2",
        )
        web_lbl.pack(side="left")
        web_lbl.bind("<Button-1>", lambda _e: webbrowser.open(GELISTIRICI_WEB_URL))

        buton_grup = ctk.CTkFrame(kart, fg_color="transparent")
        buton_grup.pack(fill="x", padx=22, pady=(4, 10))

        ctk.CTkButton(
            buton_grup,
            text="Web Sitesini Aç",
            height=38,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_KALIN, size=13),
            fg_color="#0078d7",
            hover_color="#005a9e",
            command=lambda: webbrowser.open(GELISTIRICI_WEB_URL),
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            buton_grup,
            text="E-posta Gönder",
            height=38,
            corner_radius=4,
            font=ctk.CTkFont(family=FONT_KALIN, size=13),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: webbrowser.open(f"mailto:{GELISTIRICI_EPOSTA}"),
        ).pack(side="right", fill="x", expand=True)

    def _ayarlari_forma_doldur(self):
        self.grup_giris.delete(0, "end")
        self.grup_giris.insert(0, self.ayarlar.get("grup_adi", ""))

        self.mesaj_giris.delete(0, "end")
        self.mesaj_giris.insert(0, self.ayarlar.get("mesaj_metni", ""))

        self.sure_giris.delete(0, "end")
        self.sure_giris.insert(0, str(self.ayarlar.get("baslatma_suresi_sn", 60)))

        self.komut_giris.delete(0, "end")
        self.komut_giris.insert(0, self.ayarlar.get("kapatma_kelimesi", "!kapat"))

        self.profil_giris.delete(0, "end")
        self.profil_giris.insert(0, self.ayarlar.get("profil_dizini", ""))

        self.var_win_baslangic.set(self.ayarlar.get("windows_baslangic", False))
        self.var_oto_baslat.set(self.ayarlar.get("acilista_otomatik_baslat", True))
        self.var_sohbet_kapat.set(self.ayarlar.get("sohbet_kapatma_aktif", True))
        self.var_whatsapp.set(self.ayarlar.get("whatsapp_gonder", True))
        self.var_pano.set(self.ayarlar.get("panoya_kopyala", True))
        self.var_onay.set(self.ayarlar.get("otomatik_onay", True))
        self.var_tam_ekran.set(self.ayarlar.get("tam_ekran", True))
        self.var_hazir_kapat.set(self.ayarlar.get("hazir_kutusunu_kapat", True))
        self.var_mik_kapali.set(self.ayarlar.get("mikrofon_kapali", False))
        self.var_kam_kapali.set(self.ayarlar.get("kamera_kapali", False))

    def _ozeti_guncelle(self):
        grup = self.ayarlar.get("grup_adi", "").strip()
        if self.ayarlar.get("whatsapp_gonder", True):
            grup_metni = f"Hedef Grup: {grup}" if grup else "Hedef Grup: Henüz ayarlanmadı"
        else:
            grup_metni = "WhatsApp Paylaşımı: Kapalı"

        aktifler = []
        if self.ayarlar.get("windows_baslangic"):
            aktifler.append("Windows Başlangıç")
        if self.ayarlar.get("acilista_otomatik_baslat"):
            aktifler.append(f"Zamanlayıcı: {self.ayarlar.get('baslatma_suresi_sn', 60)} sn")
        if self.ayarlar.get("otomatik_onay"):
            aktifler.append("Otomatik Onay")
        if self.ayarlar.get("sohbet_kapatma_aktif") and self.ayarlar.get("kapatma_kelimesi"):
            aktifler.append(f"PC Kapatma: {self.ayarlar.get('kapatma_kelimesi')}")

        detay = "  •  ".join(aktifler) if aktifler else "Standart başlatma"
        self.ozet_grup_lbl.configure(text=grup_metni)
        self.ozet_detay_lbl.configure(text=detay)

    def _profil_sec(self):
        klasor = filedialog.askdirectory(title="Tarayıcı Profil Klasörünü Seçin")
        if klasor:
            self.profil_giris.delete(0, "end")
            self.profil_giris.insert(0, klasor)

    def _kaydet_tiklandi(self):
        sure_metni = self.sure_giris.get().strip()
        try:
            sure_sn = int(sure_metni)
            if sure_sn < 0 or sure_sn > 3600:
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                "Geçersiz Süre",
                "Bekleme süresi 0 ile 3600 arasında bir tam sayı (saniye) olmalıdır.",
            )
            return

        komut_metni = self.komut_giris.get().strip()
        if self.var_sohbet_kapat.get() and not komut_metni:
            messagebox.showwarning(
                "Eksik Komut",
                "Sohbet komutuyla kapatma açıkken bir kapatma kelimesi (örn: !kapat) girmelisiniz.",
            )
            return

        yeni_ayarlar = {
            "grup_adi": self.grup_giris.get().strip(),
            "mesaj_metni": self.mesaj_giris.get().strip(),
            "profil_dizini": self.profil_giris.get().strip() or varsayilan_profil_dizini(),
            "whatsapp_gonder": self.var_whatsapp.get(),
            "panoya_kopyala": self.var_pano.get(),
            "otomatik_onay": self.var_onay.get(),
            "tam_ekran": self.var_tam_ekran.get(),
            "hazir_kutusunu_kapat": self.var_hazir_kapat.get(),
            "mikrofon_kapali": self.var_mik_kapali.get(),
            "kamera_kapali": self.var_kam_kapali.get(),
            "windows_baslangic": self.var_win_baslangic.get(),
            "acilista_otomatik_baslat": self.var_oto_baslat.get(),
            "baslatma_suresi_sn": sure_sn,
            "sohbet_kapatma_aktif": self.var_sohbet_kapat.get(),
            "kapatma_kelimesi": komut_metni or "!kapat",
        }

        if yeni_ayarlar["whatsapp_gonder"] and not yeni_ayarlar["grup_adi"]:
            messagebox.showwarning(
                "Eksik Bilgi",
                "WhatsApp paylaşımı açıkken bir grup adı girmelisiniz.",
            )
            return

        basarili, hata = windows_baslangic_ayarla(yeni_ayarlar["windows_baslangic"])
        if not basarili:
            messagebox.showwarning(
                "Windows Başlangıç Uyarısı",
                f"Başlangıç kaydı güncellenemedi:\n{hata}",
            )

        self.ayarlar = yeni_ayarlar
        ayarlari_kaydet(self.ayarlar)
        self._ozeti_guncelle()
        self._log_yaz("Ayarlar kaydedildi.")
        self.sekmeler.set("Ana Ekran")

    def _oturumu_sifirla(self):
        if self.calisiyor:
            messagebox.showinfo("Uyarı", "Önce aktif toplantıyı durdurun.")
            return
        profil = self.profil_giris.get().strip() or self.ayarlar.get("profil_dizini")
        onay = messagebox.askyesno(
            "Oturumu Sıfırla",
            "Kayıtlı Google ve WhatsApp oturumları silinecek. Emin misiniz?",
        )
        if onay and profil and os.path.exists(profil):
            try:
                shutil.rmtree(profil)
                self._log_yaz("Tarayıcı oturumu sıfırlandı.")
                messagebox.showinfo("Tamamlandı", "Oturum bilgileri temizlendi.")
            except Exception as e:
                messagebox.showerror("Hata", f"Klasör silinemedi (Tarayıcı açık olabilir):\n{e}")

    def _ayarlara_gec(self):
        self._sayaci_iptal_et()
        self.sekmeler.set("Ayarlar")

    def _sayaci_iptal_et(self):
        if self.otomatik_sayac_id is not None:
            self.after_cancel(self.otomatik_sayac_id)
            self.otomatik_sayac_id = None
            self.sayac_iptal_btn.pack_forget()
            if not self.calisiyor:
                self._durum_guncelle("Hazır")
                self.baslat_btn.configure(text="Toplantıyı Başlat")
                self._log_yaz("Otomatik başlatma zamanlayıcısı iptal edildi.")

    def _otomatik_baslat_sayaci(self, saniye):
        self.kalan_saniye = saniye
        if self.kalan_saniye <= 0:
            self.otomatik_sayac_id = None
            self.sayac_iptal_btn.pack_forget()
            self._baslat()
            return

        if not self.sayac_iptal_btn.winfo_ismapped():
            self.sayac_iptal_btn.pack(side="right", padx=(0, 8), before=self.baslat_btn)

        dk, sn = divmod(self.kalan_saniye, 60)
        zaman_etiketi = f"{dk:02d}:{sn:02d}" if dk > 0 else f"{sn} sn"
        self._durum_guncelle(f"{zaman_etiketi} içinde başlıyor...")
        self.baslat_btn.configure(text=f"Hemen Başlat ({zaman_etiketi})")
        self.otomatik_sayac_id = self.after(
            1000, lambda: self._otomatik_baslat_sayaci(self.kalan_saniye - 1)
        )

    def _log_yaz(self, mesaj):
        zaman = time.strftime("%H:%M:%S")

        def ekle():
            self.log_kutusu.configure(state="normal")
            self.log_kutusu.insert("end", f"[{zaman}] {mesaj}\n")
            self.log_kutusu.see("end")
            self.log_kutusu.configure(state="disabled")

        self.after(0, ekle)

    def _durum_guncelle(self, metin):
        self.after(0, lambda: self.durum_rozet.configure(text=metin))

    def _baslat_veya_durdur(self):
        if self.otomatik_sayac_id is not None:
            self.after_cancel(self.otomatik_sayac_id)
            self.otomatik_sayac_id = None
            self.sayac_iptal_btn.pack_forget()
        if self.calisiyor:
            self._durdur()
        else:
            self._baslat()

    def _baslat(self):
        if self.ayarlar.get("whatsapp_gonder") and not self.ayarlar.get("grup_adi"):
            messagebox.showwarning(
                "Ayar Gerekli",
                "Lütfen önce Ayarlar sekmesinden WhatsApp grup adını girin.",
            )
            self.sekmeler.set("Ayarlar")
            return

        self.calisiyor = True
        self.durdur_olayi.clear()
        self.baslat_btn.configure(
            text="Toplantıyı Durdur",
            fg_color="#c42b1c",
            hover_color="#9e2216",
        )
        self.ayar_git_btn.configure(state="disabled")

        motor = MeetOtomasyonMotoru(
            ayarlar=self.ayarlar.copy(),
            log_fn=self._log_yaz,
            durum_fn=self._durum_guncelle,
            bitis_fn=self._islem_bitti,
            durdur_olayi=self.durdur_olayi,
        )
        threading.Thread(target=motor.calistir, daemon=True).start()

    def _durdur(self):
        self._log_yaz("Durduruluyor...")
        self._durum_guncelle("Durduruluyor...")
        self.durdur_olayi.set()

    def _islem_bitti(self):
        def sifirla():
            self.calisiyor = False
            self.baslat_btn.configure(
                text="Toplantıyı Başlat",
                fg_color="#107c10",
                hover_color="#0b5a0b",
            )
            self.ayar_git_btn.configure(state="normal")
            self._durum_guncelle("Hazır")

        self.after(0, sifirla)

    def _pencere_kapat(self):
        if self.otomatik_sayac_id is not None:
            self.after_cancel(self.otomatik_sayac_id)
        self.durdur_olayi.set()
        self.destroy()


if __name__ == "__main__":
    uygulama = MeetOtomasyonUygulamasi()
    uygulama.mainloop()