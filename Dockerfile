FROM python:3.11-slim

# Install system dependencies and Google Chrome stable
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
    unzip \
    --no-install-recommends \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor > /usr/share/keyrings/google-chrome-keyring.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y \
    google-chrome-stable \
    --no-install-recommends \
    && apt-get install -y \
    libxss1 \
    libappindicator3-1 \
    libindicator7 \
    libgconf-2-4 \
    libxkbcommon0 \
    libatk-bridge2.0-0 \
    libatspi2.0-0 \
    libgtk-3-0 \
    libgdk-pixbuf-2.0-0 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libxrandr2 \
    libxinerama1 \
    libxcursor1 \
    libxi6 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon-x11-0 \
    fonts-liberation \
    xdg-utils \
    wget \
    ca-certificates \
    --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install matching Chromedriver via Chrome for Testing JSON API (supports Chrome 115+)
RUN CHROME_FULL=$(google-chrome --version | grep -oP '[\d.]+') \
    && CHROME_MAJOR=$(echo "$CHROME_FULL" | cut -d. -f1) \
    && DRIVER_URL=$(curl -s "https://googlechromelabs.github.io/chrome-for-testing/latest-patch-versions-per-build-with-downloads.json" \
       | python3 -c "import sys,json; data=json.load(sys.stdin); builds=data['builds']; \
         key=next((k for k in sorted(builds.keys(), reverse=True) if k.split('.')[0]=='${CHROME_MAJOR}'), None); \
         print(builds[key]['downloads']['chromedriver'][next(i for i,d in enumerate(builds[key]['downloads']['chromedriver']) if d['platform']=='linux64')]['url'])") \
    && wget -q "$DRIVER_URL" -O /tmp/chromedriver.zip \
    && unzip /tmp/chromedriver.zip -d /tmp/chromedriver_dir \
    && mv /tmp/chromedriver_dir/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver \
    && chmod +x /usr/local/bin/chromedriver \
    && rm -rf /tmp/chromedriver.zip /tmp/chromedriver_dir

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["python", "main.py"]
