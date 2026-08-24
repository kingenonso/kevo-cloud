# KEVO - Investor Liquidity Marketplace

from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "<h1>Welcome to King's Cloud Dashboard</h1>"
app.run()

