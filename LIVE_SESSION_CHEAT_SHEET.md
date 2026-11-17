# SMC Live Session Automated Cheat Sheet & Protocol SOP

> **Session Goal:** Verify live option quotes recording for both **NIFTY** and **SENSEX** into `results\live_nifty_option_quotes.jsonl` and `results\live_sensex_option_quotes.jsonl`, verify dashboard display, and audit quote quality for walk-forward learning history.

---

## १. ॲप्लिकेशन सुरू करणे (Start Live Session)

```powershell
cd E:\Project\SMC
.\run_smc.ps1 -Live
```

- **TOTP Authentication:** वेगळी कन्सोल विंडो उघडेल; तिथे Angel One 6-digit TOTP टाका.
- **Dashboard Open:** ब्राऊझरमध्ये [http://127.0.0.1:8765](http://127.0.0.1:8765) उघडा.

---

## २. Live Recording पडताळणी चेकलिस्ट (Intraday Checklist)

| तपासण्याचे ठिकाण | काय पाहायचे | अपेक्षा / मानके |
| :--- | :--- | :--- |
| **Market Selector** | NIFTY आणि SENSEX दोन्ही निवडून योग्य index व CE/PE strikes दिसतात का | दोन्ही बाजूंसाठी ATM/ITM कॉन्ट्रॅक्ट्स अचूक मॅच व्हायला हवेत |
| **Option Chain Table** | `Bid`, `Ask`, `Volume` आणि `quote_at` टाइमस्टॅम्प्स | प्रत्येक मिनिटाला किमती व व्हॉल्यूम बदलताना दिसावेत |
| **OTM Ranking Table** | मोमेंटम रँकिंग सक्रिय होते का | किमान ३ सलग कोट्सनंतर OTM रँकिंग येते. `WAIT` असल्यास कारण नोंदवा |
| **Market Sentiment** | सिम्बॉल, टाइमस्टॅम्प आणि डेटा सोर्स | **Strategy Gate: OFF** ठेवा. केवळ इन्फॉर्मेशनल मॉनिटरिंग |

### Quote Tape वाढ तपासण्याची कमांड (दुसऱ्या PowerShell मध्ये):
```powershell
Get-Item .\results\live_nifty_option_quotes.jsonl, .\results\live_sensex_option_quotes.jsonl | Select-Object Name, Length, LastWriteTime
```
थोड्या वेळाने पुन्हा हीच कमांड देऊन फाइल्सचा आकार (`Length`) आणि वेळ (`LastWriteTime`) वाढतोय का ते पहा.

---

## ३. सेशननंतर Data Audit चालवणे (Post-Session Audit)

मार्केट संपल्यावर (१५:३० IST नंतर):
```powershell
.\.venv\Scripts\python.exe -m smc.option_tape_auditor
```
किंवा संपूर्ण सुपरवायझर स्टेटससाठी:
```powershell
.\.venv\Scripts\python.exe -m smc.live_session_supervisor
```

### काय नोंदवले जाईल:
1. **Usable Quotes:** एकूण वैध रेकॉर्ड्स आणि रेकॉर्डिंग कालावधी (मिनिटे).
2. **Gaps > 120s:** सत्रादरम्यान २ मिनिटांपेक्षा मोठा खंड पडला आहे का.
3. **Invalid Bid/Ask:** शून्य, मिसिंग किंवा `bid > ask` (उलटे) कोट्स.
4. **Strike Coverage:** ATM, ITM आणि OTM चे एकूण कॉन्ट्रॅक्ट्स.

---

## ४. Paper Research Settings (सध्याचे Frozen Rules)

| Market | सध्याची Research Setting | टार्गेट / रिस्क निकष |
| :--- | :--- | :--- |
| **NIFTY** | **Baseline (OFF)** | Min index target $\ge 50$ pts, Planned RR $\ge 2.0$ |
| **SENSEX** | **Structural Stop + Session Timing Window** | Windows: `[09:30–11:00)` किंवा `[13:15–14:45)` IST. Min target $\ge 100$ pts, Planned RR $\ge 2.0$ |
| **Option Premium Plan** | **Quote-based पडताळणी बाकी** | किमान **२० training + १० validation sessions** आणि **१५ + ८ simulated trades** आवश्यक |

