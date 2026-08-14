import requests
from bs4 import BeautifulSoup

url = "https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/?tb_eg=Sports&tb_edate=n30days&tb_emt=0&itm_content=Sports"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}

response = requests.get(url, headers=headers)
soup = BeautifulSoup(response.text, "html.parser")

print(f"--> Status HTTP: {response.status_code}")
print(f"--> Longitud del HTML: {len(response.text)} caracteres")

events = soup.select(".tb-se")
print(f"--> Elementos '.tb-se' encontrados: {len(events)}")

iframes = soup.find_all("iframe")
print(f"--> Iframes en la pagina: {len(iframes)}")
for i, iframe in enumerate(iframes):
    print(f"    [Iframe {i+1}] src: {iframe.get('src')}")

with open("debug_sports.html", "w", encoding="utf-8") as f:
    f.write(response.text)

print("\n✓ HTML guardado en 'debug_sports.html'")
