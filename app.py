from flask import Flask, render_template_string, jsonify, request
import yfinance as yf
import pandas as pd
import threading
import time
 import pandas_ta as ta
import random
import warnings
import logging
import os
from datetime import datetime

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('yfinance').setLevel(logging.CRITICAL) 

app = Flask(__name__)

# --- GLOBAL DEĞİŞKENLER VE GÜVENLİK (THREAD SAFETY) ---
data_lock = threading.Lock()
notif_lock = threading.Lock()

TUM_BIST_100 = [
    "AEFES", "AGHOL", "AKBNK", "AKCNS", "AKENR", "AKFGY", "AKGRT", "AKSA", "AKSEN", "ALARK",
    "ALBRK", "ALFAS", "ALGYO", "ALKA", "ALKIM", "ANELE", "ARCLK", "ASELS", "ASTOR", "BAGFAS",
    "BANVT", "BERA", "BEYAZ", "BIZIM", "BIMAS", "BRISA", "BRSAN", "BUCIM", "CANTE", "CCOLA",
    "CEMTS", "CIMSA", "CLEBI", "CONSE", "CWENE", "DOAS", "DOHOL", "EGEEN", "EGGUB", "EKGYO",
    "ENJSA", "ENKAI", "ERBOS", "EREGL", "EUPWR", "FROTO", "GARAN", "GESAN", "GLYHO", "GSDHO",
    "GUBRF", "GWIND", "HALKB", "HEKTS", "IPEKE", "ISCTR", "ISDMR", "ISGYO", "ISMEN", "IZMDC",
    "KARDM", "KCHOL", "KONTR", "KORDS", "KOZAA", "KOZAL", "KRDMD", "MAVI", "MGROS", "MIATK",
    "ODAS", "OTKAR", "OYAKC", "PENTA", "PETKM", "PGSUS", "QUAGR", "SAHOL", "SASA", "SAYAS",
    "SDTTR", "SISE", "SKBNK", "SMRTG", "SOKM", "TARKM", "TAVHL", "TCELL", "THYAO", "TKFEN",
    "TMSN", "TOASO", "TSKB", "TTKOM", "TUPRS", "TURSG", "ULKER", "VAKBN", "VESBE", "VESTL",
    "YEOTK", "YKBNK", "YYLGD", "ZOREN"
]

radar_listesi = ["THYAO.IS", "AKBNK.IS", "ASELS.IS"] 
borsa_verisi = []
bildirimler = [] 
maliyetler = {} 
sanal_cuzdan = {"bakiye": 100000.0, "hisseler": {}}
son_guncelleme_zamani = "Bekleniyor..." 

# --- YENİLENMİŞ A.I. AYARLARI ---
AYARLAR = {
    "rsi_period": 14,
    "rsi_ob": 70,       
    "rsi_os": 30,       
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_sig": 9,
    "sma_fast": 50,
    "sma_slow": 200,
    "bb_period": 20,    
    "bb_std": 2.0,      
    "vol_multi": 2.5,   
    "sent_limit": 2.0,  
    "ai_score": 5,      
    "tp_yuzde": 3.0,
    "sl_yuzde": 1.0,
    "cdl_aktif": True,
    "cdl_guclu": True,
    "cdl_carpan": 1.0
}

GUCLU_FORMASYONLAR = [
    "cdl_engulfing", "cdl_hammer", "cdl_morningstar", "cdl_eveningstar", 
    "cdl_shootingstar", "cdl_doji", "cdl_piercing", "cdl_darkcloudcover", 
    "cdl_marubozu", "cdl_harami"
]
# --- A.I. MOTORU ---
def analiz_motoru():
    global borsa_verisi, radar_listesi, maliyetler, sanal_cuzdan, AYARLAR, son_guncelleme_zamani
    while True:
        with data_lock: 
            sanal_hisseler = [h + ".IS" for h in sanal_cuzdan["hisseler"].keys()]
            takip_edilecekler = list(set(radar_listesi + sanal_hisseler))
        
        if not takip_edilecekler: 
            with data_lock:
                borsa_verisi = [] 
            time.sleep(2)
            continue
            
        try:
            df_full = yf.download(" ".join(takip_edilecekler), period="60d", interval="15m", group_by='ticker', progress=False)
            temp_data = []
            
            for hisse in takip_edilecekler:
                try: 
                    df = df_full[hisse] if len(takip_edilecekler) > 1 else df_full
                    df = df.dropna()
                    if df.empty: continue
                    
                    fiyat = float(df['Close'].iloc[-1])
                    op, hi, lo, cl, vol = df['Open'], df['High'], df['Low'], df['Close'], df['Volume']
                    
                    # --- PANDAS_TA GÜNCELLEMESİ (Hatasız Versiyon) ---
                    # RSI Hesaplama
                    rsi_all = df.ta.rsi(length=int(AYARLAR['rsi_period']))
                    rsi = rsi_all.iloc[-1] if rsi_all is not None and not rsi_all.empty else 0
                    
                    # MACD Hesaplama
                    macd_df = df.ta.macd(fast=int(AYARLAR['macd_fast']), slow=int(AYARLAR['macd_slow']), signal=int(AYARLAR['macd_sig']))
                    if macd_df is not None and not macd_df.empty:
                        macd = macd_df.iloc[:, 0].iloc[-1]        # MACD Line
                        macdsignal = macd_df.iloc[:, 2].iloc[-1]  # Signal Line
                    else:
                        macd, macdsignal = 0, 0

                    # SMA Hesaplamaları
                    sma50_series = df.ta.sma(length=int(AYARLAR['sma_fast']))
                    sma50 = sma50_series.iloc[-1] if sma50_series is not None else 0
                    
                    sma200_series = df.ta.sma(length=int(AYARLAR['sma_slow']))
                    sma200 = sma200_series.iloc[-1] if sma200_series is not None else 0
                    
                    vol_sma_series = df.ta.sma(close=vol, length=20)
                    vol_sma = vol_sma_series.iloc[-1] if vol_sma_series is not None else 0
                    
                    degisim = ((cl.iloc[-1] - cl.iloc[-2]) / cl.iloc[-2]) * 100
                    
                    # Uzun Vade Trend ve Hacim Şoku
                    sma800_series = df.ta.sma(length=800)
                    uzun_vade_trend = True if (len(cl) > 800 and sma800_series is not None and fiyat > sma800_series.iloc[-1]) else False
                    hacim_soku = True if (vol_sma > 0 and vol.iloc[-1] > (vol_sma * float(AYARLAR['vol_multi']))) else False
                    # ------------------------------------------------
                    haber_etkisi = "Nötr Haber Akışı"
                    if degisim > float(AYARLAR['sent_limit']) and vol.iloc[-1] > vol_sma * 1.5: 
                        haber_etkisi = f"📈 Pozitif Haber/Beklenti"
                    elif degisim < -float(AYARLAR['sent_limit']) and vol.iloc[-1] > vol_sma * 1.5: 
                        haber_etkisi = f"📉 Negatif Haber/Baskı"

                    # --- PANDAS_TA MUM FORMASYON GÜNCELLEMESİ ---
                    boga_sayisi, ayi_sayisi = 0, 0
                    aktif_formasyonlar = []
                    
                    if AYARLAR['cdl_aktif']:
                        # pandas_ta ile tüm mum formasyonlarını tek seferde hesaplıyoruz
                        # Not: Formasyon isimleri küçük harf olmalı (cdl_hammer gibi)
                        try:
                            # GUCLU_FORMASYONLAR listesindeki tüm mumları tarar
                            cdl_df = df.ta.cdl_pattern(name=GUCLU_FORMASYONLAR)
                            
                            if cdl_df is not None and not cdl_df.empty:
                                son_mum_degerleri = cdl_df.iloc[-1]
                                
                                for fn in GUCLU_FORMASYONLAR:
                                    if fn in son_mum_degerleri:
                                        sonuc = son_mum_degerleri[fn]
                                        if sonuc > 0: # Boğa formasyonu (Genelde 100 döner)
                                            boga_sayisi += 1
                                            aktif_formasyonlar.append(fn.replace("cdl_", "").upper() + "(B)")
                                        elif sonuc < 0: # Ayı formasyonu (Genelde -100 döner)
                                            ayi_sayisi += 1
                                            aktif_formasyonlar.append(fn.replace("cdl_", "").upper() + "(A)")
                        except Exception as e:
                            logging.error(f"Formasyon tarama hatası: {e}")
                    # --------------------------------------------

                    # YENİ: A.I. MENTÖR SİSTEMİ (Neden Al/Sat Dedi?)
                    skor = 0
                    mentor_notlari = []
                    
                    if not pd.isna(rsi):
                        if rsi < int(AYARLAR['rsi_os']): 
                            skor += 3; mentor_notlari.append(f"🟢 RSI Çok Ucuz (Aşırı Satım) [+3]")
                        elif rsi < int(AYARLAR['rsi_os']) + 10: 
                            skor += 1; mentor_notlari.append("🟢 RSI Dibe Yakın [+1]")
                        if rsi > int(AYARLAR['rsi_ob']): 
                            skor -= 3; mentor_notlari.append(f"🔴 RSI Çok Pahalı (Aşırı Alım) [-3]")
                        elif rsi > int(AYARLAR['rsi_ob']) - 10: 
                            skor -= 1; mentor_notlari.append("🔴 RSI Tepeye Yakın [-1]")
                    
                    if not pd.isna(macd.iloc[-1]) and not pd.isna(macdsignal.iloc[-1]):
                        if macd.iloc[-1] > macdsignal.iloc[-1]: 
                            skor += 1; mentor_notlari.append("🟢 MACD Trendi Pozitif Kesim [+1]")
                        else: 
                            skor -= 1; mentor_notlari.append("🔴 MACD Trendi Negatif Kesim [-1]")
                    
                    if not pd.isna(sma50) and fiyat > sma50: 
                        skor += 1; mentor_notlari.append(f"🟢 Fiyat SMA{AYARLAR['sma_fast']} Üzerinde Güçlü [+1]")
                    if not pd.isna(sma50) and not pd.isna(sma200):
                        if sma50 > sma200: 
                            skor += 2; mentor_notlari.append(f"🌟 Golden Cross (Yükseliş Trendi) [+2]")
                        else: 
                            skor -= 2; mentor_notlari.append(f"☠️ Death Cross (Düşüş Trendi) [-2]")
                    
                    fm_etkisi = (boga_sayisi - ayi_sayisi) * float(AYARLAR['cdl_carpan'])
                    skor += fm_etkisi
                    if fm_etkisi > 0: mentor_notlari.append(f"🕯️ Boğa (Alış) Mum Formasyonları [+{fm_etkisi}]")
                    elif fm_etkisi < 0: mentor_notlari.append(f"🕯️ Ayı (Satış) Mum Formasyonları [{fm_etkisi}]")
                    
                    if uzun_vade_trend: mentor_notlari.append("📈 Uzun Vade Trend Pozitif")
                    if hacim_soku: mentor_notlari.append("💥 Beklenmedik Hacim Şoku Var!")
                    
                    if not mentor_notlari: mentor_notlari.append("Öne çıkan belirgin bir teknik sinyal yok.")
                    
                    # HTML Title özelliği için satır atlamalarını ayarla
                    mentor_metni = "A.I. Mentör Analizi:&#10;---------------------&#10;" + "&#10;".join(mentor_notlari) + f"&#10;---------------------&#10;NET SKOR: {skor}"

                    ai_hedef = int(AYARLAR['ai_score'])
                    if skor >= ai_hedef and uzun_vade_trend and macd.iloc[-1] > 0: sinyal = "🔥 KUSURSUZ AL"
                    elif skor >= ai_hedef: sinyal = "GÜÇLÜ AL"
                    elif skor >= (ai_hedef / 2): sinyal = "AL"
                    elif skor <= -ai_hedef: sinyal = "GÜÇLÜ SAT"
                    elif skor <= -(ai_hedef / 2): sinyal = "SAT"
                    else: sinyal = "NÖTR"
                    
                    fm = ", ".join(aktif_formasyonlar) if aktif_formasyonlar else "-"
                    if hacim_soku: fm = "💥 HACİM ŞOKU<br>" + fm
                    fm += f"<br><span style='color:#ccc; font-size:10px;'>📰 {haber_etkisi}</span>"

                    h_kod = hisse.replace(".IS", "")
                    maliyet = maliyetler.get(h_kod, 0)
                    kar_zarar_yuzde = ((fiyat - maliyet) / maliyet) * 100 if maliyet > 0 else 0

                    temp_data.append({
                        'hisse': h_kod, 'fiyat': fiyat, 'rsi': f"{rsi:.1f}" if not pd.isna(rsi) else "-", 
                        'formasyon': fm, 'sinyal': sinyal, 'skor': skor,
                        'maliyet': maliyet, 'kar_zarar': kar_zarar_yuzde,
                        'mentor': mentor_metni # Mentör bilgisini arayüze iletiyoruz
                    })
                except Exception as inner_e:
                    logging.error(f"Analiz motorunda hisse hatası ({hisse}): {inner_e}")

            with data_lock: 
                guncel = [i['hisse'] for i in temp_data]
                for m_item in borsa_verisi:
                    if m_item['hisse'] not in guncel and m_item['hisse'] + ".IS" in takip_edilecekler:
                        temp_data.append(m_item)
                borsa_verisi = temp_data
                son_guncelleme_zamani = datetime.now().strftime("%H:%M:%S")

        except Exception as e: 
            logging.error(f"Analiz motoru genel veri çekme hatası: {e}") 
        time.sleep(5)

# --- FIRSAT TARAYICISI (GÜÇLENDİRİLMİŞ) ---
def firsat_tarayici():
    global bildirimler, TUM_BIST_100, radar_listesi, AYARLAR
    bildirilen_hisseler = {} 
    while True:
        try:
            with data_lock:
                hedef_hisseler = [h + ".IS" for h in TUM_BIST_100 if h + ".IS" not in radar_listesi]
            if not hedef_hisseler: time.sleep(30); continue
            tarama_listesi = random.sample(hedef_hisseler, min(10, len(hedef_hisseler)))
            df_full = yf.download(" ".join(tarama_listesi), period="5d", interval="15m", group_by='ticker', progress=False)

            for hisse in tarama_listesi:
                try:
                    # Hisse verisini seçiyoruz
                    df = df_full[hisse] if len(tarama_listesi) > 1 else df_full
                    df = df.dropna()
                    if df.empty: continue

                    fiyat = float(df['Close'].iloc[-1])
                    
                    # --- PANDAS_TA DÖNÜŞÜMÜ (TALIB YOK) ---
                    # RSI Hesaplama
                    rsi_series = df.ta.rsi(length=int(AYARLAR['rsi_period']))
                    rsi = rsi_series.iloc[-1] if rsi_series is not None and not rsi_series.empty else 50
                    
                    # MACD Hesaplama
                    macd_df = df.ta.macd(fast=int(AYARLAR['macd_fast']), slow=int(AYARLAR['macd_slow']), signal=int(AYARLAR['macd_sig']))
                    
                    firsat_bulundu = False
                    formasyon_adi = ""
                    
                    # 1. Mum Formasyon Taraması
                    if AYARLAR['cdl_aktif']:
                        try:
                            # GUCLU_FORMASYONLAR listesindeki cdl_... isimlerini tarar
                            cdl_df = df.ta.cdl_pattern(name=GUCLU_FORMASYONLAR)
                            if cdl_df is not None and not cdl_df.empty:
                                son_mum = cdl_df.iloc[-1]
                                for fn in GUCLU_FORMASYONLAR:
                                    if fn in son_mum and son_mum[fn] == 100: # 100 = AL Sinyali
                                        firsat_bulundu = True
                                        formasyon_adi = fn.replace("cdl_", "").upper()
                                        break
                        except: pass
                    
                    # 2. RSI Dip Tespiti
                    if not firsat_bulundu and rsi < int(AYARLAR['rsi_os']):
                        firsat_bulundu = True
                        formasyon_adi = f"RSI Dip Tespiti ({rsi:.1f})"
                    
                    # 3. MACD Kesişimi (AL Sinyali)
                    if not firsat_bulundu and macd_df is not None and len(macd_df) >= 2:
                        m_line = macd_df.iloc[:, 0] # MACD Çizgisi
                        s_line = macd_df.iloc[:, 2] # Sinyal Çizgisi
                        if m_line.iloc[-1] > s_line.iloc[-1] and m_line.iloc[-2] <= s_line.iloc[-2]:
                            firsat_bulundu = True
                            formasyon_adi = "A.I. MACD Kesişimi (AL)"
                    
                    # --- BİLDİRİM GÖNDERME SİSTEMİ ---
                    if firsat_bulundu:
                        su_an = time.time()
                        if hisse not in bildirilen_hisseler or (su_an - bildirilen_hisseler[hisse]) > 7200:
                            with notif_lock: 
                                if len(bildirimler) >= 20: 
                                    bildirimler.pop(0)
                                bildirimler.append({
                                    "hisse": hisse.replace(".IS", ""), 
                                    "fiyat": f"{fiyat:.2f}", 
                                    "mesaj": f"{formasyon_adi}", 
                                    "zaman": time.strftime("%H:%M:%S")
                                })
                            bildirilen_hisseler[hisse] = su_an
                except Exception as hisse_hata:
                    logging.error(f"{hisse} tarama hatası: {hisse_hata}")
                    continue
        except Exception as e: 
            logging.error(f"Fırsat tarayıcı genel hatası: {e}") 
        time.sleep(20) 

# --- ARAYÜZ ---
INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>BIST 100 ANALIZING</title>
    <script src="https://cdn.jsdelivr.net/npm/apexcharts"></script>
    <script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
    <style>
        body { background: #050505; color: white; font-family: monospace; margin: 0; padding: 20px; }
        .swal2-container { z-index: 100000 !important; }
        
        .nav { background: #111; padding: 15px; border-bottom: 2px solid #f1c40f; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px; }
        
        /* ARAMA MOTORLARI */
        .search-container { position: relative; display: flex; gap: 10px; align-items: center; }
        .search-input { padding: 10px; width: 200px; background: #222; border: 1px solid #444; color: white; border-radius: 5px; outline: none; }
        .search-results { position: absolute; top: 40px; left:0; width: 200px; background: #222; border: 1px solid #444; display: none; z-index: 1000; max-height: 200px; overflow-y: auto; border-radius: 5px; box-shadow: 0 5px 15px rgba(0,0,0,0.5);}
        .result-item { padding: 10px; cursor: pointer; } .result-item:hover { background: #f1c40f; color: black; }
        
        .tabs-container { display: flex; gap: 10px; margin-top: 20px; }
        .tab-btn { background: #1a1a1a; color: #888; border: 1px solid #333; padding: 10px 25px; font-size: 16px; font-weight: bold; cursor: pointer; border-radius: 5px 5px 0 0; transition: 0.3s; }
        .tab-btn.active { background: #f1c40f; color: black; border-color: #f1c40f; }
        .tab-btn:hover:not(.active) { background: #333; color: white; }
        .tab-content { display: none; background: #0a0a0a; border: 1px solid #333; padding: 20px; border-radius: 0 5px 5px 5px; }
        .tab-content.active { display: block; }

        .backtest-panel { display: flex; gap: 5px; align-items: center;}
        .backtest-panel select { background: #222; color: white; border: 1px solid #444; padding: 5px; border-radius: 3px; }
        .bt-btn { background: #8e44ad; color: white; border: none; padding: 6px 15px; cursor: pointer; font-weight: bold; border-radius: 3px; } .bt-btn:hover { background: #9b59b6; }
        .ayar-btn { background: #34495e; color: white; border: none; padding: 6px 15px; cursor: pointer; font-weight: bold; border-radius: 3px; } .ayar-btn:hover { background: #2c3e50; }

        table { width: 100%; border-collapse: collapse; text-align: center; font-size: 14px; }
        th { color: #f1c40f; padding: 15px; border-bottom: 2px solid #333; cursor: pointer; user-select: none; transition: 0.2s;} th:hover { background: #222; }
        td { padding: 12px; border-bottom: 1px solid #222; font-weight: bold; vertical-align: middle; }
        tr:hover { background: #151515; }
        
        .btn-analiz { background: #007bff; color: white; border: none; padding: 8px 15px; cursor: pointer; font-weight: bold; border-radius: 3px; } .btn-analiz:hover { background: #0056b3; }
        .btn-sil { background: #e74c3c; color: white; border: none; padding: 5px 10px; font-size: 11px; cursor: pointer; font-weight: bold; border-radius: 3px; margin-right: 15px; } .btn-sil:hover { background: #c0392b; }

        /* YENİ: Mentör (Tooltip) İmleci */
        .mentor-ipucu { cursor: help; border-bottom: 1px dotted #888; }
        
        .sinyal-rozet { cursor: help; padding: 8px 10px; border-radius: 5px; font-weight: bold; font-size: 11px; display: inline-block; width: 110px; text-align: center; color: black; box-shadow: 0 0 10px rgba(0,0,0,0.5);}
        .s-kusursuz { background: linear-gradient(45deg, #f1c40f, #e67e22, #e74c3c); color: white; animation: p-gold 1s infinite; font-size: 12px; }
        .s-g-al { background: #00ff00; animation: p-green 1s infinite; }
        .s-al { background: #2ecc71; }
        .s-notr { background: #95a5a6; color: white; }
        .s-sat { background: #e67e22; color: white;}
        .s-g-sat { background: #ff0000; color: white; animation: p-red 1s infinite; }
        
        @keyframes p-gold { 0% { box-shadow: 0 0 5px #f1c40f; transform: scale(1); } 50% { box-shadow: 0 0 20px #e67e22; transform: scale(1.05); } 100% { box-shadow: 0 0 5px #f1c40f; transform: scale(1); } }
        @keyframes p-green { 0% { box-shadow: 0 0 5px #00ff00; } 50% { box-shadow: 0 0 20px #00ff00; } 100% { box-shadow: 0 0 5px #00ff00; } }
        @keyframes p-red { 0% { box-shadow: 0 0 5px #ff0000; } 50% { box-shadow: 0 0 20px #ff0000; } 100% { box-shadow: 0 0 5px #ff0000; } }

        .cost-input { width: 70px; background: #222; border: 1px solid #444; color: #f1c40f; padding: 6px; border-radius: 3px; text-align: center; font-weight: bold; outline: none; transition: 0.2s; }
        .cost-input:focus { border-color: #f1c40f; background: #111; box-shadow: 0 0 5px rgba(241,196,15,0.5); }

        #modal, #settings-modal { display: none; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #080808; border: 2px solid #f1c40f; padding: 25px; width: 1250px; max-width: 95vw; max-height: 95vh; overflow-y: auto; overflow-x: hidden; box-sizing: border-box; z-index: 2000; border-radius: 15px; box-shadow: 0 0 50px rgba(241,196,15,0.3); }
        #settings-modal { width: 850px; }
        
        .s-grid { display:grid; grid-template-columns: 1fr 1fr; gap:20px; margin-bottom:20px; }
        .s-box { background: #111; border: 1px solid #333; padding: 15px; border-radius: 5px; }
        .s-box h4 { color:#00ffff; margin-top:0; border-bottom:1px dashed #333; padding-bottom:5px; margin-bottom:15px; }
        .s-group { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;}
        .s-group label { color:#ccc; font-size:12px; }
        .s-group input[type="number"] { background:#222; color:#f1c40f; border:1px solid #444; padding:6px; border-radius:4px; outline:none; width:60px; text-align:center; font-weight:bold;}

        #overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.95); z-index: 1500; }
        .modal-grid { display: grid; grid-template-columns: 3fr 1fr; gap: 20px; margin-top: 15px; margin-bottom: 15px; min-width: 0; }
        .charts-container { display: flex; flex-direction: column; gap: 5px; min-width: 0; overflow: hidden; }
        
        .info-panel { background: #111; padding: 15px; border: 1px solid #333; border-radius: 5px; height: fit-content; min-width: 0; }
        .info-row { display: flex; justify-content: space-between; margin-bottom: 10px; border-bottom: 1px dashed #333; padding-bottom: 5px; align-items:center; }
        .info-row span:last-child { color: #f1c40f; font-weight: bold; }
        .price-header { display: flex; align-items: center; gap: 15px; flex-wrap: wrap; width: 100%; }
        
        .sanal-btn-group { margin-left: auto; display: flex; gap: 10px;}
        .btn-ekle-modal { background: #2ecc71; color: black; border: none; padding: 8px 15px; font-size: 14px; font-weight: bold; border-radius: 5px; cursor: pointer; transition: 0.2s; }
        .btn-s-al { background: #3498db; color: white; border: none; padding: 8px 15px; font-size: 12px; font-weight: bold; border-radius: 5px; cursor: pointer; transition: 0.2s; }
        .btn-s-sat { background: #e74c3c; color: white; border: none; padding: 8px 15px; font-size: 12px; font-weight: bold; border-radius: 5px; cursor: pointer; transition: 0.2s; }
        
        .vites-bar { display: flex; gap: 8px; margin-bottom: 15px; flex-wrap: wrap; align-items: center;}
        .vites-btn { background: #222; color: white; border: 1px solid #444; padding: 8px 12px; cursor: pointer; font-weight: bold; } 
        .vites-btn.active { background: #f1c40f; color: black; }
        .sr-toggle-label { margin-left: 20px; font-size: 13px; color: #00ffff; display: flex; align-items: center; gap: 5px; cursor: pointer;}

        /* BİLDİRİM PANELİ (MİNİ NANO MOD) */
        #scanner-panel { position: fixed; bottom: 20px; right: 20px; width: 300px; background: #111; border: 1px solid #f1c40f; border-radius: 8px; box-shadow: 0 0 20px rgba(241,196,15,0.15); z-index: 1000; display: flex; flex-direction: column; overflow: hidden; transition: all 0.3s ease; }
        
        #scanner-panel.collapsed { width: 120px; height: 38px; border-radius: 20px; bottom: 15px; right: 15px; }
        #scanner-panel.collapsed .scanner-header { padding: 0 15px; height: 100%; border-bottom: none; border-radius: 20px; justify-content: space-between;}
        #scanner-panel.collapsed .full-text { display: none; }
        .mini-text { display: none; color: #f1c40f; font-weight: bold; font-size:12px; }
        #scanner-panel.collapsed .mini-text { display: inline-block; }
        
        .scanner-header { background: #1a1a1a; padding: 12px; border-bottom: 1px solid #333; display: flex; justify-content: space-between; align-items: center; font-weight: bold; color: #f1c40f; font-size: 14px; user-select: none; cursor: pointer; transition: 0.3s;}
        .panel-toggle { background: none; border: none; color: #f1c40f; font-weight: bold; font-size: 16px; cursor: pointer; padding:0; margin:0;}
        .live-dot { height: 10px; width: 10px; background-color: #2ecc71; border-radius: 50%; display: inline-block; animation: blinker 1.5s linear infinite; margin-right:8px;}
        
        /* BALONCUK (BUBBLE) SİSTEMİ */
        .buble-badge { position: absolute; top: -4px; right: -4px; background: #e74c3c; color: white; font-size: 9px; padding: 3px 5px; border-radius: 50%; display: none; animation: b-pulse 1s infinite; box-shadow: 0 0 5px #e74c3c; border:1px solid #111;}

        .scanner-body { padding: 10px; max-height: 250px; overflow-y: auto; } .scanner-body.collapsed { display: none; }
        .scanner-body::-webkit-scrollbar { width: 5px; } .scanner-body::-webkit-scrollbar-thumb { background: #444; border-radius: 5px; }
        
        .scanning-status { color: #888; text-align: center; font-style: italic; padding: 20px 0; font-size: 12px; animation: pulseText 2s infinite; }
        .toast-item { background: #222; border-left: 4px solid #2ecc71; padding: 10px; margin-bottom: 10px; border-radius: 4px; position: relative; animation: slideIn 0.3s; }
        .toast-item:hover { background: #2a2a2a; transform: translateX(-2px); }
        .toast-title { font-weight: bold; color: #f1c40f; display: flex; justify-content: space-between; align-items: center; }
        .toast-desc { color: #ccc; font-size: 11px; margin-top: 5px; margin-bottom: 8px; }
        .toast-btn-group { display: flex; gap: 5px; margin-top: 8px;} 
        .toast-btn { background: #333; color: white; border: 1px solid #444; padding: 4px 8px; font-size: 10px; cursor: pointer; border-radius: 3px; font-weight: bold; flex: 1;}
        .t-btn-incele:hover { background: #007bff; border-color: #007bff; } .t-btn-ekle:hover { background: #2ecc71; color: black; border-color: #2ecc71; }
        .toast-close { font-weight: bold; color: #e74c3c; cursor: pointer; margin-left: 10px; padding: 0 5px; } .toast-close:hover { color: white; }
        
        .yasal-uyari { position: fixed; bottom: 10px; left: 10px; color: rgba(255, 255, 255, 0.4); font-size: 10px; pointer-events: none; z-index: 500; }
        
        @keyframes b-pulse { 0% { transform: scale(1); opacity:1; } 50% { transform: scale(1.2); opacity:0.8; } 100% { transform: scale(1); opacity:1; } }
        @keyframes blinker { 50% { opacity: 0; } }
        @keyframes pulseText { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
        @keyframes slideIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
    </style>
    
    <script>
        const allStocks = {{ all_stocks|tojson }};
        let AYARLAR = {};
        let currentHisse = "", currentFiyat = 0;
        let mainChart = null, rsiChart = null, macdChart = null; 
        let sortCol = -1, sortAsc = true;
        let srLines = { upper: 0, lower: 0 };
        let isSRVisible = true; 
        let activeTab = 'gercek'; 
        let isMuted = false;
        let audioUnlocked = false;

        let audioCtx;
        function initAudio() {
            if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            if (audioCtx.state === 'suspended') audioCtx.resume();
            audioUnlocked = true;
        }
        document.addEventListener('click', initAudio, { once: true });

        function playDing() {
            if (isMuted) return;
            initAudio();
            const osc = audioCtx.createOscillator();
            const gain = audioCtx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(800, audioCtx.currentTime);
            gain.gain.setValueAtTime(0.1, audioCtx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.1);
            osc.connect(gain); gain.connect(audioCtx.destination);
            osc.start(); osc.stop(audioCtx.currentTime + 0.1);
            
            setTimeout(() => {
                const osc2 = audioCtx.createOscillator();
                const gain2 = audioCtx.createGain();
                osc2.type = 'sine'; osc2.frequency.setValueAtTime(1000, audioCtx.currentTime);
                gain2.gain.setValueAtTime(0.1, audioCtx.currentTime); gain2.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.2);
                osc2.connect(gain2); gain2.connect(audioCtx.destination);
                osc2.start(); osc2.stop(audioCtx.currentTime + 0.2);
            }, 100);
        }

        function toggleMute(e) {
            e.stopPropagation();
            isMuted = !isMuted;
            document.getElementById('mute-btn').innerText = isMuted ? '🔇' : '🔊';
        }

        function openAyarlar() {
            fetch('/api/ayarlar').then(r=>r.json()).then(data => {
                AYARLAR = data;
                document.getElementById('a-rsi').value = AYARLAR.rsi_period;
                document.getElementById('a-rsi-ob').value = AYARLAR.rsi_ob;
                document.getElementById('a-rsi-os').value = AYARLAR.rsi_os;
                document.getElementById('a-macd-f').value = AYARLAR.macd_fast;
                document.getElementById('a-macd-s').value = AYARLAR.macd_slow;
                document.getElementById('a-macd-sig').value = AYARLAR.macd_sig;
                document.getElementById('a-sma-f').value = AYARLAR.sma_fast;
                document.getElementById('a-sma-s').value = AYARLAR.sma_slow;
                document.getElementById('a-bb-p').value = AYARLAR.bb_period;
                document.getElementById('a-bb-std').value = AYARLAR.bb_std;
                document.getElementById('a-vol').value = AYARLAR.vol_multi;
                document.getElementById('a-sent').value = AYARLAR.sent_limit;
                document.getElementById('a-ai-sc').value = AYARLAR.ai_score;
                document.getElementById('a-tp').value = AYARLAR.tp_yuzde;
                document.getElementById('a-sl').value = AYARLAR.sl_yuzde;
                
                document.getElementById('a-cdl-aktif').checked = AYARLAR.cdl_aktif;
                document.getElementById('a-cdl-guclu').checked = AYARLAR.cdl_guclu;
                document.getElementById('a-cdl-carp').value = AYARLAR.cdl_carpan;
                
                document.getElementById('settings-modal').style.display='block';
                document.getElementById('overlay').style.display='block';
            });
        }
        
        function saveAyarlar() {
            let payload = {
                rsi_period: document.getElementById('a-rsi').value,
                rsi_ob: document.getElementById('a-rsi-ob').value,
                rsi_os: document.getElementById('a-rsi-os').value,
                macd_fast: document.getElementById('a-macd-f').value,
                macd_slow: document.getElementById('a-macd-s').value,
                macd_sig: document.getElementById('a-macd-sig').value,
                sma_fast: document.getElementById('a-sma-f').value,
                sma_slow: document.getElementById('a-sma-s').value,
                bb_period: document.getElementById('a-bb-p').value,
                bb_std: document.getElementById('a-bb-std').value,
                vol_multi: document.getElementById('a-vol').value,
                sent_limit: document.getElementById('a-sent').value,
                ai_score: document.getElementById('a-ai-sc').value,
                tp_yuzde: document.getElementById('a-tp').value,
                sl_yuzde: document.getElementById('a-sl').value,
                cdl_aktif: document.getElementById('a-cdl-aktif').checked,
                cdl_guclu: document.getElementById('a-cdl-guclu').checked,
                cdl_carpan: document.getElementById('a-cdl-carp').value
            };
            fetch('/api/ayarlar', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) })
            .then(r=>r.json()).then(res => {
                AYARLAR = res.ayarlar;
                document.getElementById('settings-modal').style.display='none'; document.getElementById('overlay').style.display='none';
                Swal.fire({title: 'Kurallar Değişti!', text: 'Yapay zeka yeni stratejinize göre tarama yapıyor.', icon: 'success', background: '#111', color: '#fff'});
            });
        }

        function switchTab(tabId) {
            activeTab = tabId;
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById('btn-' + tabId).classList.add('active');
            document.getElementById('content-' + tabId).classList.add('active');
            if(tabId === 'gercek') updateGercek(); else updateSanal();
        }

        function filterGercek(val) { filterGenel(val, 'results', 'search', 'gercek', true); }
        function filterSanal(val) { filterGenel(val, 'sanal-results', 'sanal-hisse-input', 'sanal', false); }

        function filterGenel(val, resId, inputId, tab, addDirectly) {
            let res = document.getElementById(resId);
            if(!val) { res.style.display = 'none'; return; }
            let filtered = allStocks.filter(h => h.includes(val.toUpperCase())).slice(0,10);
            res.innerHTML = '';
            filtered.forEach(h => {
                let d = document.createElement('div'); d.className = 'result-item'; d.innerText = h;
                d.onclick = () => { 
                    if(addDirectly) {
                        addRadar(h); switchTab(tab); 
                    } else {
                        document.getElementById(inputId).value = h;
                    }
                    res.style.display = 'none'; document.getElementById(inputId).value = h;
                };
                res.appendChild(d);
            });
            res.style.display = 'block';
        }

        document.addEventListener('click', e => {
            if(!e.target.closest('.search-container')) {
                document.getElementById('results').style.display = 'none';
                if(document.getElementById('sanal-results')) document.getElementById('sanal-results').style.display = 'none';
            }
            if (e.target && e.target.classList.contains('btn-analiz')) { openAnaliz(e.target.getAttribute('data-hisse')); }
        });

        function sanalYeniAl() {
            let val = document.getElementById('sanal-hisse-input').value.toUpperCase();
            if(!val) return;
            let h = allStocks.find(s => s.includes(val)) || val;
            if(!h.includes('.IS')) h += '.IS';
            openAnaliz(h); document.getElementById('sanal-hisse-input').value = '';
        }

        function toggleScanner(e) { 
            if(e && e.target.id === 'mute-btn') return;
            const panel = document.getElementById('scanner-panel');
            const body = document.getElementById('scanner-body');
            panel.classList.toggle('collapsed');
            body.classList.toggle('collapsed'); 
            if(!panel.classList.contains('collapsed')) {
                document.getElementById('scanner-badge').style.display = 'none'; 
            }
        }

        function removeToast(ev, el) { 
            if(ev) ev.stopPropagation(); 
            el.closest('.toast-item').remove(); 
            if(document.querySelectorAll('.toast-item').length === 0) document.getElementById('scanning-status').style.display = 'block';
        }

        function addRadar(h) { fetch('/api/add_radar?h='+h).then(() => { updateGercek(); document.querySelectorAll('.toast-item').forEach(t => { if (t.querySelector('.toast-title span').textContent.startsWith(h)) t.remove(); }); }); }
        function removeRadar(h) { fetch('/api/remove_radar?h='+h).then(updateGercek); }
        function checkEnter(ev, h, input) { if(ev.key === 'Enter') input.blur(); }
        function updateCost(h, val) { fetch(`/api/set_cost?h=${h}&c=${val}`).then(updateGercek); }

        function sortTable(tableId, n) {
            const table = document.getElementById(tableId);
            let rows, switching = true, i, x, y, shouldSwitch;
            if(sortCol === n) sortAsc = !sortAsc; else sortAsc = true;
            sortCol = n;
            while (switching) {
                switching = false; rows = table.rows;
                for (i = 1; i < (rows.length - 1); i++) {
                    shouldSwitch = false; x = rows[i].getElementsByTagName("TD")[n]; y = rows[i + 1].getElementsByTagName("TD")[n];
                    let valX = x.innerText.replace('₺', '').replace('%', '').trim(); let valY = y.innerText.replace('₺', '').replace('%', '').trim();
                    let numX = parseFloat(valX); let numY = parseFloat(valY);
                    if (!isNaN(numX) && !isNaN(numY)) { if (sortAsc) { if (numX > numY) { shouldSwitch = true; break; } } else { if (numX < numY) { shouldSwitch = true; break; } } } 
                    else { if (sortAsc) { if (valX.toLowerCase() > valY.toLowerCase()) { shouldSwitch = true; break; } } else { if (valX.toLowerCase() < valY.toLowerCase()) { shouldSwitch = true; break; } } }
                }
                if (shouldSwitch) { rows[i].parentNode.insertBefore(rows[i + 1], rows[i]); switching = true; }
            }
        }

        async function runBacktest() {
            const h = document.getElementById('bt-hisse').value;
            Swal.fire({ title: 'A.I. Geçmişi Taranıyor...', text: h + ' için 1 yıllık geçmiş veriler analiz ediliyor.', allowOutsideClick: false, didOpen: () => { Swal.showLoading() } });
            const res = await fetch(`/api/backtest?h=${h}.IS`);
            const data = await res.json();
            if(data.error) { Swal.fire('Hata', 'Yeterli geçmiş veri bulunamadı.', 'error'); return; }
            
            let color = data.getiri.includes('-') ? '#e74c3c' : '#2ecc71';
            Swal.fire({ background: '#111', color: '#fff', title: `${h} | 1 Yıllık A.I. Raporu`,
                html: `<div style="text-align:left; font-family:monospace; font-size:16px; margin-top:20px;">
                        <div>👉 Strateji (RSI: ${AYARLAR.rsi_period})</div>
                        <div>👉 Toplam İşlem: <b style="color:#f1c40f">${data.islem}</b></div>
                        <div>✅ Başarılı İşlem: <b style="color:#2ecc71">${data.kar_sayisi}</b></div>
                        <div>❌ Hatalı İşlem: <b style="color:#e74c3c">${data.zarar_sayisi}</b></div>
                        <hr style="border-color:#333; margin:15px 0;">
                        <div style="font-size:22px;">A.I. Net Kâr: <b style="color:${color}">${data.getiri}</b></div>
                       </div>`, confirmButtonColor: '#f1c40f', confirmButtonText: 'Kapat'
            });
        }

        function sanalIslemPrompt(islemTipi) {
            Swal.fire({
                title: `Sanal ${islemTipi} - ${currentHisse}`, input: 'number', 
                inputLabel: `Kaç LOT ${islemTipi} yapmak istiyorsun? (Anlık Fiyat: ₺${currentFiyat})`, inputPlaceholder: 'Lot Adedi', 
                background: '#111', color: '#fff', confirmButtonColor: islemTipi === 'AL' ? '#3498db' : '#e74c3c', showCancelButton: true, cancelButtonText: 'İptal',
                preConfirm: (adet) => {
                    if (!adet || adet <= 0) { Swal.showValidationMessage('Geçerli bir adet girin.'); return false; }
                    return fetch(`/api/sanal_islem?h=${currentHisse}&islem=${islemTipi}&adet=${adet}&fiyat=${currentFiyat}`)
                        .then(r => r.json()).then(data => { if(data.status === 'error') throw new Error(data.msg); return data; }).catch(e => { Swal.showValidationMessage(e.message); });
                }
            }).then((result) => {
                if (result.isConfirmed) {
                    Swal.fire({ title: 'Başarılı!', text: result.value.msg, icon: 'success', background: '#111', color: '#fff' });
                    updateSanalCuzdan(); if(activeTab === 'sanal') updateSanal();
                }
            });
        }

        function updateSanalCuzdan() {
            fetch('/api/sanal_portfoy').then(r=>r.json()).then(data => {
                document.getElementById('sBakiye').innerText = parseFloat(data.bakiye).toLocaleString('tr-TR', {minimumFractionDigits:2}) + ' ₺';
                document.getElementById('sPortfoy').innerText = parseFloat(data.toplam_deger).toLocaleString('tr-TR', {minimumFractionDigits:2}) + ' ₺';
            });
        }

        function toggleSR() {
            isSRVisible = document.getElementById('toggle-sr').checked;
            if(!mainChart) return;
            mainChart.clearAnnotations();
            if(isSRVisible) {
                mainChart.addYaxisAnnotation({ y: srLines.upper, borderColor: '#e74c3c', strokeDashArray:4, label: {text: 'Direnç', style:{background:'#e74c3c', color:'#fff', padding:{left:5, right:5, top:2, bottom:2}}} });
                mainChart.addYaxisAnnotation({ y: srLines.lower, borderColor: '#2ecc71', strokeDashArray:4, label: {text: 'Destek', style:{background:'#2ecc71', color:'#fff', padding:{left:5, right:5, top:2, bottom:2}}} });
            }
        }

        async function openAnaliz(h, p='15m') {
            currentHisse = h; 
            document.querySelectorAll('.vites-btn').forEach(b => { b.classList.remove('active'); if(b.getAttribute('data-p') === p) b.classList.add('active'); });

            document.getElementById('m_title').innerText = h + " - VERİLER ÇEKİLİYOR...";
            document.getElementById('m_graph').innerHTML = '<div style="text-align:center; padding:100px; color:#f1c40f;">Yapay Zeka Hesaplanıyor... Lütfen Bekleyin.</div>';
            document.getElementById('modal').style.display='block'; document.getElementById('overlay').style.display='block';

            const res = await fetch(`/api/detail?h=${h}&p=${p}`);
            const data = await res.json();
            if(data.status === 'error') { document.getElementById('m_graph').innerHTML = `<div style="color:red; padding:20px;">Hata: ${data.message}</div>`; return; }

            currentFiyat = parseFloat(data.fiyat);
            srLines.lower = parseFloat(data.analiz['Destek']); srLines.upper = parseFloat(data.analiz['Direnç']);

            const isHisseOnRadar = currentRadarList.includes(h);
            const ekleBtn = (!isHisseOnRadar && activeTab === 'gercek') ? `<button class="btn-ekle-modal" title="Bu hisseyi canlı radar listenize ekleyin" onclick="addRadar('${h}'); this.innerText='✓ EKLENDİ'; this.disabled=true;">+ ANA EKRANA EKLE</button>` : '';

            let sanalBtns = '';
            if (activeTab === 'sanal') {
                sanalBtns = `
                    <button class="btn-s-al" title="Risk almadan sanal parayla bu hisseyi cüzdanınıza ekleyin." onclick="sanalIslemPrompt('AL')">🛒 SANAL AL</button>
                    <button class="btn-s-sat" title="Cüzdanınızdaki hisseyi satarak sanal kâr/zarar elde edin." onclick="sanalIslemPrompt('SAT')">💸 SANAL SAT</button>
                `;
            }

            document.getElementById('m_title').innerHTML = `
                <div class="price-header">
                    <span>${h} A.I. DETAYLI ANALİZ</span>
                    <span style="font-size: 24px; color:#fff;">₺${data.fiyat}</span>
                    <span style="font-size: 14px; color:#888;" title="Yapay zekanın bu hisseye verdiği toplam puan.">(Skor: ${data.analiz['Skor']}/${AYARLAR.ai_score})</span>
                    <div class="sanal-btn-group">${sanalBtns}${ekleBtn}</div>
                </div>
            `;

            document.getElementById('m_graph').innerHTML = `
                <div class="modal-grid">
                    <div class="charts-container">
                        <div id="main-chart" style="background:#111; border:1px solid #333; border-radius:5px; height: 300px;"></div>
                        <div id="rsi-chart" style="background:#111; border:1px solid #333; border-radius:5px; height: 120px;"></div>
                        <div id="macd-chart" style="background:#111; border:1px solid #333; border-radius:5px; height: 120px;"></div>
                    </div>
                    <div class="info-panel">
                        <h3 style="margin-top:0; color:#888; border-bottom:1px solid #333; padding-bottom:5px;">Temel & Teknik Zeka</h3>
                        <div class="info-row"><span title="Göreceli Güç Endeksi. 30 altı ucuz, 70 üstü pahalıdır." class="mentor-ipucu">RSI (${AYARLAR.rsi_period})</span><span>${data.analiz['RSI']}</span></div>
                        <div class="info-row"><span title="Kısa vadeli trend yönünü belirler." class="mentor-ipucu">SMA ${AYARLAR.sma_fast}</span><span>${data.analiz['SMA50']}</span></div>
                        <div class="info-row"><span title="Uzun vadeli trend yönünü belirler. Fiyat bunun üstündeyse boğa piyasasıdır." class="mentor-ipucu">SMA ${AYARLAR.sma_slow}</span><span>${data.analiz['SMA200']}</span></div>
                        <div class="info-row"><span title="Anlık hacim ve fiyat hareketine göre genel piyasa beklentisi." class="mentor-ipucu">A.I. Duygusu</span><span style="color:#00ffff; font-size:12px;">${data.analiz['Sentiment']}</span></div>
                        
                        <div class="info-row" style="flex-direction:column; border:none; margin-top:20px;">
                            <span title="A.I. ayarlarına göre ulaşılması beklenen olumlu fiyat." class="mentor-ipucu" style="margin-bottom:5px; color:#ccc;">Kar Hedefi (%${AYARLAR.tp_yuzde})</span>
                            <span style="font-size:18px; color:#2ecc71;">₺${data.analiz['TP']}</span>
                        </div>
                        <div class="info-row" style="flex-direction:column; border:none;">
                            <span title="Düşüş durumunda zararı durdurmanız gereken güvenlik noktası." class="mentor-ipucu" style="margin-bottom:5px; color:#ccc;">Zarar Kes (%${AYARLAR.sl_yuzde})</span>
                            <span style="font-size:18px; color:#e74c3c;">₺${data.analiz['SL']}</span>
                        </div>
                    </div>
                </div>
            `;

            if(mainChart) mainChart.destroy(); if(rsiChart) rsiChart.destroy(); if(macdChart) macdChart.destroy();
            
            document.getElementById('toggle-sr').checked = isSRVisible;
            let annots = [];
            if(isSRVisible) {
                annots = [
                    { y: srLines.upper, borderColor: '#e74c3c', strokeDashArray:4, label: {text: 'Direnç', style:{background:'#e74c3c', color:'#fff', padding:{left:5, right:5, top:2, bottom:2}}} }, 
                    { y: srLines.lower, borderColor: '#2ecc71', strokeDashArray:4, label: {text: 'Destek', style:{background:'#2ecc71', color:'#fff', padding:{left:5, right:5, top:2, bottom:2}}} }
                ];
            }

            var mainOpt = { series: [ { name: 'Fiyat', type: 'candlestick', data: data.candles }, { name: `SMA ${AYARLAR.sma_fast}`, type: 'line', data: data.sma50_data }, { name: `SMA ${AYARLAR.sma_slow}`, type: 'line', data: data.sma200_data }, { name: 'BB Üst', type: 'line', data: data.bb_upper }, { name: 'BB Alt', type: 'line', data: data.bb_lower } ], chart: { height: 300, id: 'sync1', group: 'ai-charts', background: 'transparent', foreColor: '#ccc', animations:{enabled:false}, toolbar: { show: true } }, stroke: { width: [1, 2, 2, 1, 1], dashArray: [0, 0, 0, 4, 4] }, colors: ['#fff', '#f1c40f', '#e74c3c', '#00ffff', '#00ffff'], xaxis: { type: 'category', labels: {show:false} }, yaxis: { tooltip: {enabled: true}, labels: {formatter: val => val ? val.toFixed(2) : ''} }, grid: { borderColor: '#333', strokeDashArray: 4 }, annotations: { yAxis: annots }, plotOptions: { candlestick: { colors: { upward: '#2ecc71', downward: '#e74c3c' } } }, theme: { mode: 'dark' } };
            mainChart = new ApexCharts(document.querySelector("#main-chart"), mainOpt); mainChart.render();
            
            var rsiOpt = { series: [{ name: 'RSI', data: data.rsi_data }], chart: { type: 'line', height: 120, id: 'sync2', group: 'ai-charts', background: 'transparent', foreColor: '#ccc', animations:{enabled:false}, toolbar: {show:false} }, colors: ['#f1c40f'], stroke: { width: 2 }, xaxis: { type: 'category', labels: {show:false} }, yaxis: { min: 0, max: 100, tickAmount: 2 }, grid: { borderColor: '#333', strokeDashArray: 4 }, annotations: { yAxis: [ { y: AYARLAR.rsi_ob, borderColor: '#e74c3c', strokeDashArray:4 }, { y: AYARLAR.rsi_os, borderColor: '#2ecc71', strokeDashArray:4 } ] }, theme: { mode: 'dark' } };
            rsiChart = new ApexCharts(document.querySelector("#rsi-chart"), rsiOpt); rsiChart.render();

            var macdOpt = { series: [ { name: 'MACD', type: 'line', data: data.macd_line }, { name: 'Sinyal', type: 'line', data: data.macd_signal }, { name: 'Histogram', type: 'bar', data: data.macd_hist } ], chart: { height: 120, id: 'sync3', group: 'ai-charts', background: 'transparent', foreColor: '#ccc', animations:{enabled:false}, toolbar: {show:false} }, colors: ['#008ffb', '#ff4560', '#2ecc71'], stroke: { width: [2, 2, 0] }, xaxis: { type: 'category', labels:{style:{colors:'#888'}} }, grid: { borderColor: '#333', strokeDashArray: 4 }, plotOptions: { bar: { columnWidth: '50%', colors: { ranges: [{ from: -1000, to: 0, color: '#e74c3c' }] } } }, theme: { mode: 'dark' } };
            macdChart = new ApexCharts(document.querySelector("#macd-chart"), macdOpt); macdChart.render();
        }

        function updateGercek() {
            if (activeTab !== 'gercek') return; 
            if (document.activeElement && document.activeElement.classList.contains('cost-input')) return;
            
            fetch('/api/data').then(r=>r.json()).then(res => {
                let data = res.veriler; 
                document.getElementById('son-guncelleme-saati').innerText = "(Son Veri: " + res.son_guncelleme + ")"; 
                let html = ''; currentRadarList = data.map(item => item.hisse); 
                fetch('/api/radar_list').then(r=>r.json()).then(rList => {
                    data.forEach(h => {
                        if (!rList.includes(h.hisse + ".IS")) return;
                        let fiyatT = typeof h.fiyat === 'number' ? '₺' + h.fiyat.toFixed(2) : h.fiyat;
                        let bClass = 's-notr';
                        if (h.sinyal === '🔥 KUSURSUZ AL') bClass = 's-kusursuz';
                        else if (h.sinyal === 'GÜÇLÜ AL') bClass = 's-g-al';
                        else if (h.sinyal === 'AL') bClass = 's-al';
                        else if (h.sinyal === 'SAT') bClass = 's-sat';
                        else if (h.sinyal === 'GÜÇLÜ SAT') bClass = 's-g-sat';
                        
                        let kzRenk = h.kar_zarar > 0 ? '#2ecc71' : (h.kar_zarar < 0 ? '#e74c3c' : '#888');
                        let kzText = h.maliyet > 0 ? `%${h.kar_zarar.toFixed(2)}` : '-';

                        html += `<tr>
                            <td style="display:flex; justify-content:center; align-items:center;">
                                <button class="btn-sil" title="Radardan Çıkar" onclick="removeRadar('${h.hisse}')">X</button>
                                <button class="btn-analiz" title="A.I. Grafiklerini ve Detayları Gör" data-hisse="${h.hisse}">İNCELE</button>
                            </td>
                            <td style="color:#f1c40f; text-align:left;">${h.hisse}</td>
                            <td style="font-size:16px;">${fiyatT}</td>
                            <td><input type="number" step="0.01" class="cost-input" title="Buraya alım yaptığınız fiyatı yazarak kar/zarar hesabı yaptırabilirsiniz." value="${h.maliyet > 0 ? h.maliyet : ''}" placeholder="0.00" onkeypress="checkEnter(event, '${h.hisse}', this)" onblur="updateCost('${h.hisse}', this.value)"></td>
                            <td style="color:${kzRenk}; font-weight:bold; font-size:16px;">${kzText}</td>
                            <td style="color:#00ffff; font-size:11px; max-width:200px; word-wrap:break-word;">${h.formasyon}</td>
                            <td><div class="sinyal-rozet ${bClass}" title="${h.mentor || 'Mentör bilgisi bekleniyor...'}">${h.sinyal}</div></td>
                        </tr>`;
                    });
                    document.getElementById('tb-gercek').innerHTML = html;
                });
            });
        }

        function updateSanal() {
            if (activeTab !== 'sanal') return;
            fetch('/api/sanal_portfoy_detay').then(r=>r.json()).then(data => {
                let html = '';
                if(data.length === 0) {
                    html = '<tr><td colspan="7" style="padding:40px; color:#888;">Henüz sanal hisse almadınız. Yukarıdan "A.I. İNCELE & AL" tuşunu kullanın.</td></tr>';
                } else {
                    data.forEach(h => {
                        let bClass = 's-notr';
                        if (h.sinyal === '🔥 KUSURSUZ AL') bClass = 's-kusursuz';
                        else if (h.sinyal === 'GÜÇLÜ AL') bClass = 's-g-al';
                        else if (h.sinyal === 'AL') bClass = 's-al';
                        else if (h.sinyal === 'SAT') bClass = 's-sat';
                        else if (h.sinyal === 'GÜÇLÜ SAT') bClass = 's-g-sat';
                        let kzRenk = h.kar_zarar_yuzde > 0 ? '#2ecc71' : (h.kar_zarar_yuzde < 0 ? '#e74c3c' : '#888');

                        html += `<tr>
                            <td style="display:flex; justify-content:center; align-items:center; gap:5px;">
                                <button class="btn-s-sat" style="padding:5px 8px;" title="Sanal hisselerinizi satarak kar/zararınızı bakiyenize yansıtın." onclick="sanalIslemPrompt('SAT', '${h.hisse}')">SAT</button>
                                <button class="btn-analiz" style="padding:5px 8px;" title="A.I. Grafiklerini ve Detayları Gör" data-hisse="${h.hisse}">İNCELE</button>
                            </td>
                            <td style="color:#f1c40f; text-align:left;">${h.hisse}</td>
                            <td style="font-weight:bold;">${h.adet} Lot</td>
                            <td style="color:#888;">₺${h.maliyet.toFixed(2)}</td>
                            <td style="font-size:16px;">₺${h.fiyat.toFixed(2)}</td>
                            <td style="color:${kzRenk}; font-weight:bold; font-size:16px;">
                                ₺${h.kar_zarar_tl.toFixed(2)} <br><span style="font-size:12px">(%${h.kar_zarar_yuzde.toFixed(2)})</span>
                            </td>
                            <td><div class="sinyal-rozet ${bClass}" title="Gerçek piyasa modunda olduğu gibi neden al/sat dendiğini buradan görebilirsiniz. Detaylar için GERÇEK PİYASA sekmesine bakın.">${h.sinyal}</div></td>
                        </tr>`;
                    });
                }
                document.getElementById('tb-sanal').innerHTML = html;
            });
        }

        function checkNotifications() {
            fetch('/api/notifications').then(r=>r.json()).then(data => {
                const panel = document.getElementById('scanner-panel');
                const sBody = document.getElementById('scanner-body');
                if (data.length > 0) {
                    const st = document.getElementById('scanning-status'); if(st) st.style.display = 'none';
                    
                    if (!isMuted && audioUnlocked) playDing();
                    
                    if (panel.classList.contains('collapsed')) {
                        document.getElementById('scanner-badge').style.display = 'block';
                    }

                    data.forEach(n => {
                        let item = document.createElement('div'); item.className = 'toast-item';
                        item.innerHTML = `<div class="toast-title"><span>${n.hisse} <span style="font-size:11px; color:white;">(₺${n.fiyat})</span></span><span class="toast-close" onclick="removeToast(event, this)">X</span></div><div class="toast-desc">A.I: ${n.mesaj}</div><div class="toast-btn-group"><button type="button" class="toast-btn t-btn-incele" onclick="openAnaliz('${n.hisse}')">İNCELE</button><button type="button" class="toast-btn t-btn-ekle" onclick="addRadar('${n.hisse}')">EKLE</button></div>`;
                        sBody.prepend(item);
                    });
                    while (sBody.querySelectorAll('.toast-item').length > 7) { 
                        let items = sBody.querySelectorAll('.toast-item'); items[items.length - 1].remove(); 
                    }
                }
            });
        }

        setInterval(() => { if(activeTab==='gercek') updateGercek(); else updateSanal(); }, 3000); 
        setInterval(checkNotifications, 5000); 
        setInterval(updateSanalCuzdan, 5000);
        
        window.onload = () => { 
            fetch('/api/ayarlar').then(r=>r.json()).then(d => { AYARLAR = d; });
            let sel = document.getElementById('bt-hisse');
            allStocks.forEach(h => { let opt = document.createElement('option'); opt.value = h; opt.innerText = h; sel.appendChild(opt); });
            updateGercek(); updateSanalCuzdan();
        };
    </script>
</head>
<body>
    <div class="nav">
        <div style="display: flex; align-items: baseline; gap: 15px;">
            <h1 style="margin:0; font-size: 26px; color: white;">BIST 100 ANALIZING <span id="son-guncelleme-saati" style="font-size: 12px; color: #888; font-weight: normal;">(Son Veri: Bekleniyor...)</span></h1>
            <span style="font-size: 13px; color: #888; font-style: italic;">by Adem Efe Eren</span>
        </div>

        <div class="backtest-panel">
            <select id="bt-hisse" title="Sistem geçmişte bu hissede başarılı olmuş mu? Analiz için hisse seçin."></select>
            <button class="bt-btn" title="Seçilen hissede yapay zekanın geçmişte kaç kez başarılı / başarısız al-sat yaptığını hesaplar." onclick="runBacktest()">A.I. Geçmişi Sına</button>
            <button class="ayar-btn" title="İndikatörleri ve AI sisteminin parametrelerini değiştirin." onclick="openAyarlar()">⚙️ A.I. Ayarları</button>
        </div>

        <div class="search-container">
            <input type="text" class="search-input" id="search" placeholder="Gerçek Piyasa Ara..." oninput="filterGercek(this.value)" autocomplete="off">
            <div id="results" class="search-results"></div>
        </div>
    </div>
    
    <div class="tabs-container">
        <button id="btn-gercek" class="tab-btn active" title="Gerçek zamanlı olarak Borsa İstanbul hisselerini takip edin." onclick="switchTab('gercek')">🌍 GERÇEK PİYASA</button>
        <button id="btn-sanal" class="tab-btn" title="Sanal parayla risk almadan stratejilerinizi test edin." onclick="switchTab('sanal')">💼 SANAL PORTFÖY</button>
    </div>

    <div id="content-gercek" class="tab-content active">
        <table id="tableGercek">
            <thead>
                <tr>
                    <th style="width: 120px;">İŞLEM</th>
                    <th style="text-align:left;" onclick="sortTable('tableGercek', 1)">HİSSE ↕</th>
                    <th onclick="sortTable('tableGercek', 2)">FİYAT ↕</th>
                    <th>GERÇEK MALİYET</th>
                    <th onclick="sortTable('tableGercek', 4)">KÂR/ZARAR ↕</th>
                    <th>AI TESPİT PANELİ</th>
                    <th onclick="sortTable('tableGercek', 6)">AKILLI SİNYAL ↕</th>
                </tr>
            </thead>
            <tbody id="tb-gercek"></tbody>
        </table>
    </div>

    <div id="content-sanal" class="tab-content">
        <div style="background:#1a1a1a; padding:15px; border-radius:5px; border:1px solid #333; margin-bottom:20px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:15px;">
            <div style="display:flex; gap:20px; font-size:16px;">
                <div>Cüzdan Bakiyesi: <b style="color:#2ecc71" id="sBakiye">Yükleniyor...</b></div>
                <div>Toplam Varlık: <b style="color:#f1c40f" id="sPortfoy">Yükleniyor...</b></div>
            </div>
            <div class="search-container">
                <input type="text" class="search-input" id="sanal-hisse-input" placeholder="Hisse Ara (Örn: THYAO)" oninput="filterSanal(this.value)" autocomplete="off">
                <div id="sanal-results" class="search-results"></div>
                <button style="background:#3498db; color:white; border:none; padding:10px 15px; border-radius:3px; font-weight:bold; cursor:pointer;" onclick="sanalYeniAl()">A.I. İNCELE & AL</button>
            </div>
        </div>

        <table id="tableSanal">
            <thead>
                <tr>
                    <th style="width: 120px;">İŞLEM</th>
                    <th style="text-align:left;" onclick="sortTable('tableSanal', 1)">HİSSE ↕</th>
                    <th>LOT ADEDİ</th>
                    <th>ORT. MALİYET</th>
                    <th onclick="sortTable('tableSanal', 4)">ANLIK FİYAT ↕</th>
                    <th onclick="sortTable('tableSanal', 5)">KÂR/ZARAR (₺) ↕</th>
                    <th>A.I. TAVSİYESİ</th>
                </tr>
            </thead>
            <tbody id="tb-sanal"></tbody>
        </table>
    </div>

    <div id="overlay" onclick="this.style.display=document.getElementById('modal').style.display=document.getElementById('settings-modal').style.display='none'"></div>
    
    <div id="settings-modal">
        <h2 style="color:#f1c40f; margin-top:0; border-bottom:1px solid #333; padding-bottom:10px;">⚙️ A.I. Zekası & İndikatör Ayarları</h2>
        
        <div class="s-grid">
            <div class="s-box">
                <h4>Osilatörler (Momentum)</h4>
                <div class="s-group"><label class="mentor-ipucu" title="Genellikle 14 gün kullanılır. Sayıyı düşürmek sinyalleri hızlandırır fakat hatalı sinyal ihtimalini artırır.">RSI Periyodu</label><input type="number" id="a-rsi"></div>
                <div class="s-group"><label class="mentor-ipucu" title="Fiyatın aşırı yükseldiğini ve bir düşüş olabileceğini gösteren değerdir (Standart: 70).">RSI Aşırı Alım Sınırı</label><input type="number" id="a-rsi-ob"></div>
                <div class="s-group"><label class="mentor-ipucu" title="Fiyatın aşırı düştüğünü ve buradan bir tepki gelebileceğini gösteren değerdir (Standart: 30).">RSI Aşırı Satım Sınırı</label><input type="number" id="a-rsi-os"></div>
                <div class="s-group"><label class="mentor-ipucu" title="Kısa ve uzun vadeli üssel ortalamalar arasındaki farktır (Standart: 12, 26).">MACD Hızlı / Yavaş</label>
                    <div style="display:flex; gap:5px;"><input type="number" id="a-macd-f" style="width:30px;"><input type="number" id="a-macd-s" style="width:30px;"></div>
                </div>
                <div class="s-group"><label class="mentor-ipucu" title="MACD çizgisi bu sinyal hattını yukarı keserse AL, aşağı keserse SAT anlamına gelir (Standart: 9).">MACD Sinyal Hattı</label><input type="number" id="a-macd-sig"></div>
            </div>
            
            <div class="s-box">
                <h4>Trend & Volatilite</h4>
                <div class="s-group"><label class="mentor-ipucu" title="Kısa vadeli hareketli ortalama. Fiyat bu çizginin üstündeyse genelde pozitif bakılır. (Standart: 50)">SMA Hızlı Çizgi</label><input type="number" id="a-sma-f"></div>
                <div class="s-group"><label class="mentor-ipucu" title="Uzun vadeli hareketli ortalama. Hızlı çizgi yavaş çizgiyi yukarı keserse Golden Cross olur. (Standart: 200)">SMA Yavaş Çizgi</label><input type="number" id="a-sma-s"></div>
                <div class="s-group"><label class="mentor-ipucu" title="Bollinger Bantlarının gün/mum hesaplaması (Standart: 20)">B. Bantları Periyodu</label><input type="number" id="a-bb-p"></div>
                <div class="s-group"><label class="mentor-ipucu" title="Bant genişliğini (standart sapmayı) belirler. Fiyat bant dışına çıkarsa genelde tekrar içeri döner (Standart: 2.0)">B. Bantları Genişliği</label><input type="number" step="0.1" id="a-bb-std"></div>
            </div>
            
            <div class="s-box">
                <h4>A.I. & Temel Duyarlılık</h4>
                <div class="s-group"><label class="mentor-ipucu" title="Tüm algoritmaların toplamında yapay zekanın GÜÇLÜ AL demesi için ulaşması gereken minimum puandır.">GÜÇLÜ AL Skor Şartı</label><input type="number" id="a-ai-sc"></div>
                <div class="s-group"><label class="mentor-ipucu" title="Mevcut hacmin, 20 günlük ortalama hacmin kaç katı olduğunda 'ŞOK' olarak niteleneceğini belirler.">Hacim Şoku Çarpanı (x)</label><input type="number" step="0.1" id="a-vol"></div>
                <div class="s-group"><label class="mentor-ipucu" title="Fiyattaki anlık sıçramanın (yüzde) ne zaman sisteme 'Haber Akışı' olarak kaydedileceğini belirler.">Haber Etkisi İçin % Fark</label><input type="number" step="0.1" id="a-sent"></div>
            </div>
            
            <div class="s-box">
                <h4>🕯️ Mum & Formasyon Zekası</h4>
                <div class="s-group" style="justify-content: flex-start; gap:10px;"><input type="checkbox" id="a-cdl-aktif" style="width:auto;"><label class="mentor-ipucu" title="Yapay zeka, Doji, Yutan Boğa vb. Japon mum çubuğu formasyonlarını analiz etsin mi?">Formasyon Taraması</label></div>
                <div class="s-group" style="justify-content: flex-start; gap:10px;"><input type="checkbox" id="a-cdl-guclu" style="width:auto;"><label class="mentor-ipucu" title="Sadece güvenilirliği çok yüksek olan temel dönüş mumlarını tarar.">Sadece Güçlü Mumlar</label></div>
                <div class="s-group" style="margin-top:10px;"><label class="mentor-ipucu" title="Bulunan mum formasyonunun AI Skoru üzerinde ne kadar etki (puan) yapacağını belirler.">Skor Etki Çarpanı (x)</label><input type="number" step="0.5" id="a-cdl-carp"></div>
            </div>

            <div class="s-box" style="grid-column: span 2;">
                <h4>Risk Yönetimi</h4>
                <div style="display:flex; justify-content:space-around;">
                    <div class="s-group" style="width:40%;"><label class="mentor-ipucu" title="Aldığınız bir hissede % kaç kar gördüğünüzde sistemin hedef fiyat (Take Profit) önereceğini belirler.">Otomatik Kar Hedefi (%)</label><input type="number" step="0.1" id="a-tp" style="width:100%;"></div>
                    <div class="s-group" style="width:40%;"><label class="mentor-ipucu" title="Hisse düşüşe geçtiğinde anaparayı korumak için % kaçta zararı keseceğinizi (Stop Loss) belirler.">Zarar Kes / Stop (%)</label><input type="number" step="0.1" id="a-sl" style="width:100%;"></div>
                </div>
            </div>
        </div>
        <button style="width:100%; background:#2ecc71; color:black; font-weight:bold; font-size:16px; padding:12px; border:none; border-radius:5px; cursor:pointer;" onclick="saveAyarlar()">KAYDET VE A.I.'YI YENİDEN BAŞLAT</button>
    </div>

    <div id="modal">
        <h2 id="m_title" style="color:#f1c40f; margin:0; border-bottom:1px solid #333; padding-bottom:10px;"></h2>
        <div class="vites-bar">
            <button class="vites-btn" data-p="1m" onclick="openAnaliz(currentHisse, '1m')">1 DK</button>
            <button class="vites-btn" data-p="5m" onclick="openAnaliz(currentHisse, '5m')">5 DK</button>
            <button class="vites-btn active" data-p="15m" onclick="openAnaliz(currentHisse, '15m')">15 DK</button>
            <button class="vites-btn" data-p="30m" onclick="openAnaliz(currentHisse, '30m')">30 DK</button>
            <button class="vites-btn" data-p="1h" onclick="openAnaliz(currentHisse, '1h')">1 SAAT</button>
            <button class="vites-btn" data-p="1d" onclick="openAnaliz(currentHisse, '1d')">1 GÜN</button>
            <button class="vites-btn" data-p="1wk" onclick="openAnaliz(currentHisse, '1wk')">1 HAFTA</button>
            <label class="sr-toggle-label"><input type="checkbox" id="toggle-sr" onchange="toggleSR()" checked> Destek/Direnç Çizgileri Açık</label>
        </div>
        <div id="m_graph"></div>
    </div>
    
    <div id="scanner-panel">
        <div class="scanner-header" onclick="toggleScanner(event)">
            <span class="full-text">📡 OTOMATİK A.I. TARAYICI</span>
            <span class="mini-text">📡 A.I.</span>
            <div style="display:flex; align-items:center;">
                <div id="scanner-badge" class="buble-badge">🔴</div>
                <button id="mute-btn" onclick="toggleMute(event)">🔊</button>
                <span class="live-dot full-text"></span>
                <button type="button" class="panel-toggle">↕</button>
            </div>
        </div>
        <div class="scanner-body" id="scanner-body"><div class="scanning-status" id="scanning-status">Arka planda hisseler taranıyor...</div></div>
    </div>
    <div class="yasal-uyari">Bu sayfada yer alan bilgiler yatırım danışmanlığı içermemektedir.</div>
</body>
</html>
"""

# --- BACKEND API'LERİ ---
@app.route('/api/ayarlar', methods=['GET', 'POST'])
def api_ayarlar():
    global AYARLAR
    if request.method == 'POST':
        data = request.json
        if data:
            for k, v in data.items():
                if k in AYARLAR: 
                    if isinstance(AYARLAR[k], bool):
                        AYARLAR[k] = bool(v)
                    else:
                        AYARLAR[k] = float(v) if '.' in str(v) else int(v)
        return jsonify({"status": "ok", "ayarlar": AYARLAR})
    return jsonify(AYARLAR)

@app.route('/api/radar_list')
def get_radar_list():
    with data_lock: 
        return jsonify(radar_listesi)

@app.route('/api/sanal_portfoy_detay')
def get_sanal_portfoy_detay():
    global sanal_cuzdan, borsa_verisi
    with data_lock: 
        detaylar = []
        for h, v in sanal_cuzdan["hisseler"].items():
            hisse_veri = next((item for item in borsa_verisi if item["hisse"] == h), None)
            if hisse_veri and hisse_veri["fiyat"] != "Yükleniyor":
                anlik_fiyat = hisse_veri["fiyat"]
                sinyal = hisse_veri["sinyal"]
            else:
                anlik_fiyat = v["maliyet"] 
                sinyal = "BEKLEYİN"
                
            kar_zarar_tl = (anlik_fiyat - v["maliyet"]) * v["adet"]
            kar_zarar_yuzde = ((anlik_fiyat - v["maliyet"]) / v["maliyet"]) * 100

            detaylar.append({
                "hisse": h, "adet": v["adet"], "maliyet": v["maliyet"], "fiyat": anlik_fiyat,
                "kar_zarar_tl": kar_zarar_tl, "kar_zarar_yuzde": kar_zarar_yuzde, "sinyal": sinyal
            })
        return jsonify(detaylar)

@app.route('/api/sanal_portfoy')
def get_sanal_portfoy():
    global sanal_cuzdan, borsa_verisi
    with data_lock: 
        toplam_deger = sanal_cuzdan["bakiye"]
        for h, v in sanal_cuzdan["hisseler"].items():
            hisse_veri = next((item for item in borsa_verisi if item["hisse"] == h), None)
            if hisse_veri and hisse_veri["fiyat"] != "Yükleniyor":
                toplam_deger += (hisse_veri["fiyat"] * v['adet'])
            else:
                toplam_deger += (v['maliyet'] * v['adet'])
        return jsonify({"bakiye": sanal_cuzdan["bakiye"], "toplam_deger": toplam_deger})

@app.route('/api/sanal_islem')
def sanal_islem():
    global sanal_cuzdan
    h = request.args.get('h').replace(".IS", "")
    islem = request.args.get('islem')
    adet = int(request.args.get('adet'))
    fiyat = float(request.args.get('fiyat'))
    tutar = adet * fiyat
    
    with data_lock: 
        if islem == 'AL':
            if sanal_cuzdan["bakiye"] >= tutar:
                sanal_cuzdan["bakiye"] -= tutar
                if h in sanal_cuzdan["hisseler"]:
                    e_adet = sanal_cuzdan["hisseler"][h]['adet']
                    e_mal = sanal_cuzdan["hisseler"][h]['maliyet']
                    y_mal = ((e_adet * e_mal) + tutar) / (e_adet + adet)
                    sanal_cuzdan["hisseler"][h]['adet'] += adet
                    sanal_cuzdan["hisseler"][h]['maliyet'] = y_mal
                else: 
                    sanal_cuzdan["hisseler"][h] = {'adet': adet, 'maliyet': fiyat}
                return jsonify({'status': 'ok', 'msg': f'{adet} LOT {h} başarıyla portföye eklendi.'})
            return jsonify({'status': 'error', 'msg': 'Yetersiz Sanal Bakiye!'})
            
        elif islem == 'SAT':
            if h in sanal_cuzdan["hisseler"] and sanal_cuzdan["hisseler"][h]['adet'] >= adet:
                sanal_cuzdan["bakiye"] += tutar
                sanal_cuzdan["hisseler"][h]['adet'] -= adet
                if sanal_cuzdan["hisseler"][h]['adet'] == 0: 
                    del sanal_cuzdan["hisseler"][h]
                return jsonify({'status': 'ok', 'msg': f'{adet} LOT {h} kâr/zarar ile satıldı.'})
            return jsonify({'status': 'error', 'msg': 'Portföyünüzde bu kadar lot yok!'})

@app.route('/api/backtest')
def run_backtest():
    global AYARLAR
    h = request.args.get('h')
    try:
        df = yf.download(h, period="1y", interval="1d", progress=False)
        if df.empty: return jsonify({'error': True})
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
            
        cl = df['Close']
        if len(cl) < 15: return jsonify({'error': True}) 
        
        rsi_all = df.ta.rsi(length=int(AYARLAR['rsi_period']))
        rsi = rsi_all if rsi_all is not None else pd.Series(0, index=df.index)
        
        islem = 0; kar_s = 0; zarar_s = 0; getiri = 0.0; elde = False; alis = 0
        
        for i in range(14, len(cl)):
            v_rsi = float(rsi.iloc[i])
            v_cl = float(cl.iloc[i])
            if pd.isna(v_rsi): continue
            
            if not elde and v_rsi < int(AYARLAR['rsi_os']):
                elde = True; alis = v_cl
            elif elde and v_rsi > int(AYARLAR['rsi_ob']):
                elde = False; islem += 1; satis = v_cl
                k_orani = ((satis - alis) / alis) * 100
                getiri += k_orani
                if k_orani > 0: kar_s += 1
                else: zarar_s += 1
                
        return jsonify({'islem': islem, 'kar_sayisi': kar_s, 'zarar_sayisi': zarar_s, 'getiri': f"{'+' if getiri>0 else ''}%{getiri:.2f}"})
    except Exception as e: 
        logging.error(f"Backtest hatası: {e}")
        return jsonify({'error': True})

@app.route('/api/set_cost')
def set_cost():
    global maliyetler
    h = request.args.get('h'); c = request.args.get('c')
    with data_lock: 
        if c:
            try: maliyetler[h] = float(c)
            except: pass
        else:
            if h in maliyetler: del maliyetler[h]
    return jsonify({"status": "ok"})

@app.route('/api/notifications')
def get_notifications():
    global bildirimler
    with notif_lock: 
        kopya = bildirimler.copy()
        bildirimler.clear() 
    return jsonify(kopya)

@app.route('/api/add_radar')
def add_radar():
    global radar_listesi, borsa_verisi
    h = request.args.get('h').upper() + ".IS"
    with data_lock: 
        if h not in radar_listesi: 
            radar_listesi.append(h)
            borsa_verisi.append({'hisse': h.replace(".IS", ""), 'fiyat': "Yükleniyor", 'formasyon': "Veri Bekleniyor...", 'sinyal': "BEKLE", 'maliyet': 0, 'kar_zarar': 0})
    return jsonify({"status": "ok"})

@app.route('/api/remove_radar')
def remove_radar():
    global radar_listesi, borsa_verisi
    h = request.args.get('h').upper() + ".IS"
    with data_lock: 
        if h in radar_listesi: radar_listesi.remove(h)
        borsa_verisi = [item for item in borsa_verisi if item['hisse'] != h.replace(".IS", "")]
    return jsonify({"status": "ok"})

@app.route('/api/detail')
def get_detail():
    global MUM_FORMASYONLARI, AYARLAR, GUCLU_FORMASYONLAR, TUM_FORMASYONLAR
    h = request.args.get('h')
    if not h.endswith(".IS"): h += ".IS"
    p = request.args.get('p')
    
    period_map = { '1m':('1m','5d'), '5m':('5m','5d'), '15m':('15m','60d'), '30m':('30m','60d'), '1h':('1h','60d'), '1d':('1d','1y'), '1wk':('1wk','2y') }
    interval, period = period_map.get(p, ('1d', '1mo'))
    
    try:
        df = yf.download(h, period=period, interval=interval, progress=False)
        if df.empty: return jsonify({'error': 'Veri bulunamadı'})
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df = df.dropna()

        # --- TEKNİK GÖSTERGELER (PANDAS-TA GÜNCELLEMESİ) ---
        cl = df['Close']; op = df['Open']; hi = df['High']; lo = df['Low']; vol = df['Volume']
        
        # RSI hesaplama
        df['RSI'] = df.ta.rsi(length=int(AYARLAR['rsi_period']))
        
        # MACD hesaplama (Geriye tablo döner, kolonları parçalıyoruz)
        macd_df = df.ta.macd(fast=int(AYARLAR['macd_fast']), slow=int(AYARLAR['macd_slow']), signal=int(AYARLAR['macd_sig']))
        if macd_df is not None:
            macd = macd_df.iloc[:, 0]
            macdsig = macd_df.iloc[:, 2]
            macdhist = macd_df.iloc[:, 1]
        else:
            macd = macdsig = macdhist = pd.Series(0, index=df.index)
        
        # Hareketli Ortalamalar (SMA)
        sma50 = df.ta.sma(length=int(AYARLAR['sma_fast']))
        sma200 = df.ta.sma(length=int(AYARLAR['sma_slow']))
        
        # Bollinger Bantları hesaplama
        bb_df = df.ta.bbands(length=int(AYARLAR['bb_period']), std=float(AYARLAR['bb_std']))
        if bb_df is not None:
            lower = bb_df.iloc[:, 0]
            middle = bb_df.iloc[:, 1]
            upper = bb_df.iloc[:, 2]
        else:
            lower = middle = upper = pd.Series(0, index=df.index)
        # --------------------------------------------------
        gercek_skor = 0
        son_rsi = float(df['RSI'].iloc[-1]) if not pd.isna(df['RSI'].iloc[-1]) else 50
        son_macd = float(macd.iloc[-1]) if not pd.isna(macd.iloc[-1]) else 0
        son_macdsig = float(macdsig.iloc[-1]) if not pd.isna(macdsig.iloc[-1]) else 0
        son_sma50 = float(sma50.iloc[-1]) if not pd.isna(sma50.iloc[-1]) else 0
        son_sma200 = float(sma200.iloc[-1]) if not pd.isna(sma200.iloc[-1]) else 0
        fiyat_son = float(cl.iloc[-1])

        if son_rsi < int(AYARLAR['rsi_os']): gercek_skor += 3
        elif son_rsi < int(AYARLAR['rsi_os']) + 10: gercek_skor += 1
        if son_rsi > int(AYARLAR['rsi_ob']): gercek_skor -= 3
        elif son_rsi > int(AYARLAR['rsi_ob']) - 10: gercek_skor -= 1
        if son_macd > son_macdsig: gercek_skor += 1
        else: gercek_skor -= 1
        if son_sma50 > 0 and fiyat_son > son_sma50: gercek_skor += 1
        if son_sma50 > 0 and son_sma200 > 0:
            if son_sma50 > son_sma200: gercek_skor += 2 
            else: gercek_skor -= 2 
            
        boga_sayisi, ayi_sayisi = 0, 0
        # --- MUM FORMASYONLARI VE SENTİMENT ANALİZİ (PANDAS-TA) ---
        if AYARLAR['cdl_aktif']:
            try:
                # pandas_ta ile toplu formasyon taraması
                cdl_sonuclar = df.ta.cdl_pattern(name=GUCLU_FORMASYONLAR)
                if cdl_sonuclar is not None:
                    son_mum = cdl_sonuclar.iloc[-1]
                    for fn in GUCLU_FORMASYONLAR:
                        if fn in son_mum:
                            if son_mum[fn] == 100: boga_sayisi += 1
                            elif son_mum[fn] == -100: ayi_sayisi += 1
            except: pass
            
        gercek_skor += (boga_sayisi - ayi_sayisi) * float(AYARLAR['cdl_carpan'])

        degisim = ((cl.iloc[-1] - cl.iloc[-2]) / cl.iloc[-2]) * 100
        
        # SMA hesaplaması talıb olmadan yapılıyor
        vol_sma_series = df.ta.sma(close=vol, length=20)
        vol_sma = vol_sma_series.iloc[-1] if vol_sma_series is not None else 0
        
        sentiment = "Nötr (Olağan Piyasa Hareketi)"
        if vol_sma > 0:
            if degisim > float(AYARLAR['sent_limit']) and vol.iloc[-1] > vol_sma * 1.5: 
                sentiment = "📈 Pozitif Haber/Beklenti"
            elif degisim < -float(AYARLAR['sent_limit']) and vol.iloc[-1] > vol_sma * 1.5: 
                sentiment = "📉 Negatif Haber/Baskı"
        # ---------------------------------------------------------

        candles, rsi_data, macd_line, macd_signal, macd_hist = [], [], [], [], []
        sma50_data, sma200_data, bb_upper, bb_lower = [], [], [], []
        
        for index, row in df.tail(70).iterrows():
            t_str = index.strftime('%Y-%m-%d %H:%M') if p in ['1m', '5m', '15m', '30m', '1h'] else index.strftime('%Y-%m-%d')
            candles.append({'x': t_str, 'y': [float(row['Open']), float(row['High']), float(row['Low']), float(row['Close'])]})
            rsi_data.append({'x': t_str, 'y': float(row['RSI']) if not pd.isna(row['RSI']) else None})
            macd_line.append({'x': t_str, 'y': float(macd.loc[index]) if not pd.isna(macd.loc[index]) else None})
            macd_signal.append({'x': t_str, 'y': float(macdsig.loc[index]) if not pd.isna(macdsig.loc[index]) else None})
            macd_hist.append({'x': t_str, 'y': float(macdhist.loc[index]) if not pd.isna(macdhist.loc[index]) else 0})
            sma50_data.append({'x': t_str, 'y': float(sma50.loc[index]) if not pd.isna(sma50.loc[index]) else None})
            sma200_data.append({'x': t_str, 'y': float(sma200.loc[index]) if not pd.isna(sma200.loc[index]) else None})
            bb_upper.append({'x': t_str, 'y': float(upper.loc[index]) if not pd.isna(upper.loc[index]) else None})
            bb_lower.append({'x': t_str, 'y': float(lower.loc[index]) if not pd.isna(lower.loc[index]) else None})

        return jsonify({
            'status': 'ok', 'fiyat': f"{float(cl.iloc[-1]):.2f}",
            'candles': candles, 'rsi_data': rsi_data, 'macd_line': macd_line, 'macd_signal': macd_signal, 'macd_hist': macd_hist,
            'sma50_data': sma50_data, 'sma200_data': sma200_data, 'bb_upper': bb_upper, 'bb_lower': bb_lower,
            'analiz': {
                'RSI': f"{float(df['RSI'].iloc[-1]):.2f}" if not pd.isna(df['RSI'].iloc[-1]) else "-",
                'SMA50': f"₺{float(sma50.iloc[-1]):.2f}" if not pd.isna(sma50.iloc[-1]) else "-",
                'SMA200': f"₺{float(sma200.iloc[-1]):.2f}" if not pd.isna(sma200.iloc[-1]) else "-",
                'Destek': f"{float(df['Low'].tail(30).min()):.2f}", 'Direnç': f"{float(df['High'].tail(30).max()):.2f}",
                'Sentiment': sentiment, 'Skor': gercek_skor,
                'TP': f"{(fiyat_son * (1 + AYARLAR['tp_yuzde']/100)):.2f}",
                'SL': f"{(fiyat_son * (1 - AYARLAR['sl_yuzde']/100)):.2f}"
            }
        })
    except Exception as e: 
        logging.error(f"Detaylı analiz hatası: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/')
def index(): return render_template_string(INDEX_HTML, all_stocks=TUM_BIST_100)

@app.route('/api/data')
def get_data(): 
    with data_lock: 
        return jsonify({"veriler": borsa_verisi, "son_guncelleme": son_guncelleme_zamani})

if __name__ == '__main__':
    # Analiz motorlarını arka planda başlatıyoruz
    threading.Thread(target=analiz_motoru, daemon=True).start()
    threading.Thread(target=firsat_tarayici, daemon=True).start()
    
    # Render'ın bize atayacağı portu çekiyoruz, eğer bulamazsak varsayılan 10000 yapıyoruz
    port = int(os.environ.get("PORT", 10000))
    
    # Host '0.0.0.0' olmalı ki dış dünya (internet) uygulamana erişebilsin

    app.run(host='0.0.0.0', port=port, debug=False)


