# ✈️ Automated Flight Deal Tracker

A Python 3.12+ backend service that monitors flight prices for specific seasonal windows, evaluates offers using a multi-factor deal scoring algorithm (0–100), enforces strict quality rules (direct flights for NYC, connection bounds for TYO/SCL, anti-mixed cabin for Business/Premium), and dispatches responsive HTML email digest alerts via Gmail SMTP whenever a deal scores $\ge 80.0$.

---

## 🎯 Target Routes & Quality Rules

| Destination | Airport(s) | Seasonal Months | Stay Duration | Transfer Rules |
| :--- | :--- | :--- | :--- | :--- |
| **NYC (New York)** | JFK, EWR | Apr–Jun, Sep–Oct | **7–10 nights** | **Direct flights only** (`max_stops = 0`). Reject layovers. |
| **TYO (Tokyo)** | NRT, HND | Mar–May, Oct–Jan | **14–21 nights** | **Max 1 stop** (`max_stops = 1`). Layover: 75m to 6h. Single ticket only. |
| **SCL (Santiago)** | SCL | Nov–Feb | **14–21 nights** | **Max 1 stop** (`max_stops = 1`). Layover: 75m to 6h. Single ticket only. |

*Origins Monitored*: **Prague (PRG)** and **Dublin (DUB)**.

---

## 🛡️ Anti-Mixed Cabin & Airline Quality Rules

- **Anti-Mixed Cabin Rule**:
  - When evaluating **Business** or **Premium Economy** offers, **every single flight segment** across outbound and return legs must match the target cabin class.
  - If any feeder or connecting segment is in Economy, the offer is disqualified immediately.
  - Standard **Economy** offers are evaluated normally (not disqualified).
- **Airline Filter**:
  - Evaluates full-service and alliance airlines only (e.g. Delta, United, Air France, KLM, Lufthansa, British Airways, Iberia, Aer Lingus, ANA, JAL, LATAM).
  - Automatically rejects unbundled budget/low-cost long-haul carriers (e.g. Norse Atlantic, Play, French Bee, LEVEL).
- **Single-Ticket Protection**:
  - Disqualifies self-transfer or virtual interlining (separate uncoordinated tickets) to ensure passenger rights on delayed connections.

---

## 📊 Fixed Benchmark Price Thresholds (CZK)

| Destination | Origin | Economy (Avg / Min) | Premium Economy (Avg / Min) | Business (Avg / Min) |
| :--- | :--- | :--- | :--- | :--- |
| **NYC** | PRG | 13,500 / 8,500 CZK | 23,000 / 15,000 CZK | 48,000 / 29,000 CZK |
| | DUB | 10,500 / 6,500 CZK | 19,000 / 12,500 CZK | 42,000 / 26,000 CZK |
| **TYO** | PRG | 19,500 / 12,500 CZK | 32,000 / 21,000 CZK | 62,000 / 38,000 CZK |
| | DUB | 18,500 / 12,000 CZK | 31,000 / 20,000 CZK | 59,000 / 36,000 CZK |
| **SCL** | PRG | 24,000 / 15,500 CZK | 38,000 / 26,000 CZK | 75,000 / 46,000 CZK |
| | DUB | 22,500 / 14,500 CZK | 36,000 / 25,000 CZK | 71,000 / 44,000 CZK |

---

## 🧮 Multi-Factor Deal Scoring Formula (0 to 100)

$$\text{Total Score} = (S_{\text{price}} \times 0.40) + (S_{\text{savings}} \times 0.30) + (S_{\text{timing}} \times 0.30)$$

1. **$S_{\text{price}}$ (40% weight)**:
   - If $price \le deal\_min \implies 100\text{ pts}$.
   - If $price \ge baseline\_avg \implies 0\text{ pts}$.
   - Linearly interpolated:
     $$S_{\text{price}} = \max\left(0.0, \min\left(100.0, \frac{avg - price}{avg - deal\_min} \times 100\right)\right)$$
2. **$S_{\text{savings}}$ (30% weight)**:
   - Relates price discount percentage to savings:
     $$S_{\text{savings}} = \max\left(0.0, \min\left(100.0, \frac{avg - price}{avg} \times 200\right)\right)$$
3. **$S_{\text{timing}}$ (30% weight)**:
   - $100\text{ pts}$ if departure falls within the peak seasonal months, else $40\text{ pts}$.
4. **Trigger Alert**:
   - Only flights with $\text{Total Score} \ge 80.0$ trigger an email digest alert.

---

## 📧 Email Alerts & De-duplication

- **Consolidated HTML Digest**: Groups all deals meeting $\ge 80$ from a scan into a single email sorted by score.
- **Minimalist Subject Line**: `Flight Deals Tracker - 18 Oct 2026`
- **Dual Currency for DUB**: Displays primary CZK and approximate EUR equivalent (e.g. `11,200 CZK (~€445)`).
- **Dual Direct Links**: Each deal includes 1-click search buttons for both **Google Flights** and **Skyscanner**.
- **48-Hour Cooldown**: Identical deals are suppressed for 48 hours unless the price drops further by at least 3%.

---

## 🚀 Quickstart & Local Usage

### 1. Run Unit Tests
```bash
python3 -m unittest discover -s tests -v
```

### 2. Run Dry-Run Scan (No Email Sent, Generates HTML Preview)
```bash
python3 -m src.tracker --dry-run --sample-data
```
The generated email can be inspected in `artifacts/email_preview.html`.

### 3. Send Real Email Alert (Gmail SMTP)
Create a `.env` file from `.env.example`:
```bash
cp .env.example .env
```
Fill in your Gmail credentials (using a Google Account **App Password**):
```env
GMAIL_USER=your_email@gmail.com
GMAIL_APP_PASSWORD=your_16_character_app_password
RECIPIENT_EMAIL=your_email@gmail.com
```
Run the tracker:
```bash
python3 -m src.tracker
```

---

## ⚙️ Deployment Options

### Option 1: GitHub Actions (Recommended, 100% Free)
The included workflow `.github/workflows/scheduled_run.yml`:
- Runs automatically **every 6 hours** (`0 */6 * * *`).
- Caches `data/deal_history.json` across workflow runs for de-duplication.
- Outputs a rich markdown run summary in the GitHub Actions Step Summary tab.
- Add your secrets in **GitHub Repo -> Settings -> Secrets and variables -> Actions**:
  - `GMAIL_USER`
  - `GMAIL_APP_PASSWORD`
  - `RECIPIENT_EMAIL`
  - `KIWI_API_KEY` (optional)

### Option 2: Docker / VPS / Raspberry Pi
```bash
docker compose up -d
```
Runs an initial scan on start and schedules subsequent scans every 6 hours via cron inside the container.
