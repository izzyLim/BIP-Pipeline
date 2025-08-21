import requests
API_KEY = "0c713b53bae2ba475be918c68117c710"

url = f"https://gnews.io/api/v4/top-headlines?category=general&lang=en&country=us&max=100&apikey={API_KEY}"
response = requests.get(url)
for article in response.json().get("articles", []):
    print(article["publishedAt"], article["title"])
