FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium system dependencies manually (font packages were renamed in newer Debian)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libdbus-1-3 libxkbcommon0 libatspi2.0-0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install Chromium browser binary only
RUN playwright install chromium

COPY . .

RUN mkdir -p data

ENV PYTHONUNBUFFERED=1

# מגביל את glibc לשני malloc arenas. שרת הפאנל (werkzeug) יוצר thread חדש
# לכל בקשה, ו-glibc נותן ל-threads arenas נפרדים — עד 8 לכל ליבה שהמארח
# חושף, לא לכל ליבה שהמכולה קיבלה. כל arena מחזיק זיכרון מפורגמנט שלא חוזר
# ל-OS, וה-RSS זוחל לאט גם בלי דליפה בקוד. נמדד: 3,000 בקשות לפאנל — בלי
# המגבלה ה-RSS עדיין טיפס ב-3,000; עם המגבלה הוא שטוח לגמרי מבקשה 1,500.
# האפליקציה תלויה ב-I/O ולא בהקצאות מקבילות, אז התחרות על המנעול זניחה (באג #22).
ENV MALLOC_ARENA_MAX=2

# פאנל הגדרות + health check — פורט 8080 (ברירת מחדל, נדרס ע"י PORT)
EXPOSE 8080

CMD ["python", "main.py"]
