# 🔍 CreatorScan

**Micro-creator discovery tool** — Βρίσκει creators 2K–100K followers σε YouTube & Twitch.

## Setup (5 λεπτά)

### 1. Εγκατάσταση
```bash
cd creator-scan
pip install -r requirements.txt
```

### 2. API Keys (δωρεάν)

**YouTube Data API v3:**
1. Πήγαινε στο [Google Cloud Console](https://console.cloud.google.com/)
2. New Project → Enable "YouTube Data API v3"
3. APIs & Services → Credentials → Create API Key
4. Quota: 10,000 units/day δωρεάν (= ~100 searches + χιλιάδες channel lookups)

**Twitch API:**
1. Πήγαινε στο [Twitch Dev Console](https://dev.twitch.tv/console/apps)
2. Register Your Application
3. Πάρε Client ID + Client Secret
4. Quota: Πρακτικά απεριόριστο για personal use

### 3. Ρύθμισε .env
```bash
cp .env.example .env
# Βάλε τα API keys στο .env
```

## Χρήση

```bash
# Σκανάρισε Gaming creators στο YouTube (2K–100K followers)
python main.py scan --platform youtube --niche Gaming

# Σκανάρισε Fitness σε όλες τις πλατφόρμες
python main.py scan --platform all --niche Fitness

# Σκανάρισε με custom range
python main.py scan --platform twitch --niche Gaming --min 5000 --max 50000

# Δες τα results
python main.py list --niche Gaming
python main.py list --niche Gaming --email        # μόνο με email
python main.py list --platform youtube --limit 100

# Στατιστικά
python main.py stats

# Export σε CSV
python main.py export --output gaming_creators.csv --niche Gaming

# Δες όλες τις niches
python main.py niches
```

## Διαθέσιμες Niches

Gaming, Fitness, Tech, Beauty, Food, Travel, Finance, Education,
Fashion, Music, Art & Design, Comedy, Lifestyle, Parenting,
DIY & Crafts, Sports, Pets & Animals, Business

## Αρχιτεκτονική

```
creator-scan/
├── main.py                 # CLI entry point
├── db.py                   # SQLite database (creators.db)
├── collectors/
│   ├── youtube.py          # YouTube Data API v3
│   └── twitch.py           # Twitch Helix API
└── processors/
    └── niche.py            # Keyword-based niche classifier + email extractor
```

## Roadmap

- **Φάση 1** (τώρα): YouTube + Twitch, SQLite, CLI ✅
- **Φάση 2**: React dashboard με live φίλτρα
- **Φάση 3**: REST API με API keys για AI integration
- **Φάση 4**: TikTok + Instagram scraping
- **Φάση 5**: SaaS με subscription tiers
